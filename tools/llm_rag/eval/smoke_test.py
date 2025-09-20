import os
from tools.llm_rag.rag.retriever import Retriever
from tools.llm_rag.rag.generator import generate_answer

IDX_V = "tools/llm_rag/data/index/vectors.npy"
IDX_T = "tools/llm_rag/data/index/texts.txt"

assert os.path.exists(IDX_V) and os.path.exists(IDX_T), "Index not found. Run build_index.py first."
r = Retriever(vectors_path=IDX_V, texts_path=IDX_T)
hits = r.search("What is in the demo?", top_k=3)
print("HITS:", hits)
ans = generate_answer("What is in the demo?", [h["text"] for h in hits])
print("ANSWER:", ans)
