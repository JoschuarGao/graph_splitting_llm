# 优先用 SentenceTransformer；失败时给出友好报错提示
class Embedder:
    def __init__(self, model_name="sentence-transformers/all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(model_name)
            self._use_sbert = True
        except Exception as e:
            self._use_sbert = False
            raise RuntimeError(
                f"加载 sentence-transformers 失败：{e}\n"
                "若网络下载模型受阻，可改用我之前提供的 TF-IDF 版本 embedder.py。"
            )
    def encode(self, texts):
        vecs = self.model.encode(texts, normalize_embeddings=True)
        return vecs
