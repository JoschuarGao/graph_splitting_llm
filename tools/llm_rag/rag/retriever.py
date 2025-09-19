import numpy as np
class Retriever:
    def __init__(self, embedder, vectordb):
        self.embedder = embedder
        self.vectordb = vectordb
    def query(self, question: str, k=3):
        qvec = self.embedder.encode([question])
        return self.vectordb.search(np.array(qvec), k=k)
