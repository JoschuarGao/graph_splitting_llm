# tools/llm_rag/rag/retriever.py
from typing import List, Dict, Optional, Tuple, Any
import os
import numpy as np

class Retriever:
    """
    Two ways to construct:
    1) New (recommended for UI): Retriever(vectors_path=".../vectors.npy", texts_path=".../texts.txt", embedder=your_embedder)
       - Uses NumPy inner-product search over prebuilt matrix (no faiss at runtime).
       - If embedder is None, will try to lazy-load sentence-transformers (all-MiniLM-L6-v2).

    2) Legacy: Retriever(embedder=..., vectordb=...)
       - Will call vectordb.search(query_vec, k=top_k) and then normalize return.
    """

    def __init__(
        self,
        vectors_path: Optional[str] = None,
        texts_path: Optional[str] = None,
        embedder: Optional[Any] = None,
        vectordb: Optional[Any] = None,
    ):
        self.embedder = embedder
        self.vectordb = vectordb

        self._M = None      # (N, D) matrix of doc embeddings
        self._texts = None  # List[str]

        if vectors_path and texts_path:
            if not os.path.exists(vectors_path):
                raise FileNotFoundError(f"vectors_path not found: {vectors_path}")
            if not os.path.exists(texts_path):
                raise FileNotFoundError(f"texts_path not found: {texts_path}")

            self._M = np.load(vectors_path)
            with open(texts_path, "r", encoding="utf-8") as f:
                self._texts = [line.rstrip("\n") for line in f]

            if self._M.shape[0] != len(self._texts):
                raise ValueError(
                    f"Vector/text size mismatch: vectors={self._M.shape[0]} vs texts={len(self._texts)}"
                )

    # ---- Public API ----
    def search(self, question: str, top_k: int = 5) -> List[Dict[str, float]]:
        """
        Return: list of dicts like [{"text": "...", "score": 0.123}, ...]
        """
        # Path A: we have prebuilt matrix -> do NumPy inner-product search
        if self._M is not None and self._texts is not None:
            q = self._encode_question(question)  # (D,)
            return self._numpy_topk(q, top_k)

        # Path B: legacy backend (vectordb provided)
        if self.vectordb is None or self.embedder is None:
            raise RuntimeError(
                "Retriever is not properly initialized. Provide (vectors_path & texts_path) "
                "or (embedder & vectordb)."
            )

        qvec = self._ensure_2d(self.embedder.encode([question]))  # (1, D)
        raw = self.vectordb.search(np.array(qvec), k=top_k)
        return self._normalize_legacy_returns(raw, top_k)

    # Backward-compatible API
    def query(self, question: str, k: int = 3):
        return self.search(question, top_k=k)

    # ---- Internal helpers ----
    def _encode_question(self, question: str) -> np.ndarray:
        """
        Encode question to (D,) vector. If no embedder provided, try lazy-loading
        sentence-transformers (all-MiniLM-L6-v2).
        """
        if self.embedder is None:
            # Lazy import to avoid hard dependency at import time
            try:
                from sentence_transformers import SentenceTransformer
            except Exception as e:
                raise RuntimeError(
                    "No embedder provided and failed to import sentence-transformers. "
                    "Install it or pass an embedder with .encode(list[str])->np.ndarray"
                ) from e
            self.embedder = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        vec = self.embedder.encode([question])
        vec = self._ensure_2d(vec)[0]
        # Normalize (optional but usually good for IP similarity)
        denom = np.linalg.norm(vec) + 1e-12
        return vec / denom

    def _numpy_topk(self, q: np.ndarray, top_k: int) -> List[Dict[str, float]]:
        """
        NumPy inner-product similarity against prebuilt matrix self._M.
        Assumes rows of self._M are already normalized during indexing;
        if不确定，可在此处做一次按行归一化（代价是一次性内存拷贝）。
        """
        # 如果索引没归一化，可以启用以下两行（一次性成本）：
        # if not hasattr(self, "_normed"):
        #     self._M = self._M / (np.linalg.norm(self._M, axis=1, keepdims=True) + 1e-12)
        #     self._normed = True

        sims = self._M @ q  # (N,)
        k = min(int(top_k), sims.shape[0])
        if k <= 0:
            return []

        # argpartition + argsort for top-k
        idx = np.argpartition(-sims, kth=k-1)[:k]
        idx = idx[np.argsort(-sims[idx])]

        out: List[Dict[str, float]] = []
        for i in idx:
            out.append({"text": self._texts[int(i)], "score": float(sims[int(i)])})
        return out

    @staticmethod
    def _ensure_2d(x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)
        if x.ndim == 1:
            x = x[None, :]
        return x

    def _normalize_legacy_returns(self, raw: Any, top_k: int) -> List[Dict[str, float]]:
        """
        Try to normalize various possible returns from an existing vectordb:
          - list[dict]: [{'text': str, 'score': float}, ...] -> pass through
          - list[tuple]: [(text, score), ...]
          - tuple of (scores, indices) or (indices, scores)
          - numpy arrays ...
        We need access to texts — try self.vectordb.texts if available.
        """
        # Case 1: already in desired shape
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and "text" in raw[0]:
            return raw[:top_k]

        # Case 2: list of tuples (text, score)
        if isinstance(raw, list) and raw and isinstance(raw[0], (tuple, list)):
            out = []
            for item in raw[:top_k]:
                if len(item) == 2:
                    t, s = item
                    out.append({"text": str(t), "score": float(s)})
                else:
                    out.append({"text": str(item[0]), "score": float(item[1]) if len(item) > 1 else 0.0})
            return out

        # Case 3: tuple/array of (scores, indices) or (indices, scores)
        texts = getattr(self.vectordb, "texts", None) or getattr(self, "_texts", None)
        if texts is None:
            # Cannot map indices->text; best effort stringify
            if isinstance(raw, np.ndarray):
                raw = raw.tolist()
            return [{"text": str(x), "score": 0.0} for x in (raw if isinstance(raw, list) else [raw])]

        # Try to interpret shapes
        if isinstance(raw, tuple) and len(raw) == 2:
            a, b = raw
            a = np.asarray(a)
            b = np.asarray(b)
            # guess which is indices
            if a.dtype.kind in "iu" and b.dtype.kind in "fc":  # a: int, b: float
                indices, scores = a, b
            elif b.dtype.kind in "iu" and a.dtype.kind in "fc":  # b: int, a: float
                indices, scores = b, a
            else:
                # fallback: assume second is indices
                indices, scores = b, a
            k = min(top_k, indices.shape[-1] if indices.ndim > 1 else indices.shape[0])
            if indices.ndim > 1:
                indices = indices[0]
            if scores.ndim > 1:
                scores = scores[0]
            out = []
            for i in indices[:k]:
                i = int(i)
                sc = float(scores[i]) if i < scores.shape[0] else 0.0
                t = texts[i] if 0 <= i < len(texts) else ""
                out.append({"text": t, "score": sc})
            return out

        # Fallback: stringify
        if isinstance(raw, np.ndarray):
            raw = raw.tolist()
        return [{"text": str(x), "score": 0.0} for x in (raw if isinstance(raw, list) else [raw])]
