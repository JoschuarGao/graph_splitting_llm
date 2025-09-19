import faiss
import numpy as np

# 做了L2 归一化 + 内积 ≈ 余弦相似度。 L1 L2皈依话分别是什么
class FaissDB:
    def __init__(self, dim: int):
        self.index = faiss.IndexFlatIP(dim)
        self.meta = []

    def add(self, vecs: np.ndarray, metas):
        self.index.add(vecs.astype("float32"))
        self.meta.extend(metas)

    def search(self, qvec: np.ndarray, k=3):
        # 若索引为空，直接返回空结果
        ntotal = self.index.ntotal
        if ntotal == 0:
            return []

        # 将 k 裁剪到 [1, ntotal]
        kk = int(max(1, min(k, ntotal)))

        D, I = self.index.search(qvec.astype("float32"), kk)
        results = []
        for idx in I[0]:
            # 仅接收合法下标，忽略 -1 或越界值
            if isinstance(idx, (int, np.integer)) and 0 <= idx < len(self.meta):
                results.append(self.meta[idx])
        return results
