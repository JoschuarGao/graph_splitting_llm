import argparse, numpy as np, os, sys
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(BASE)

from rag.embedder import Embedder
from rag.vectordb import FaissDB
from rag.retriever import Retriever
from rag.generator import generate_answer

def load_index(out_dir):
    X = np.load(os.path.join(out_dir, "vectors.npy"))
    with open(os.path.join(out_dir, "texts.txt"), "r", encoding="utf-8") as f:
        texts = [line.strip() for line in f]
    return X, texts

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index_dir", default="tools/llm_rag/data/index")
    ap.add_argument("--question", required=True)
    ap.add_argument("--top_k", type=int, default=3)
    args = ap.parse_args()

    X, texts = load_index(args.index_dir)
    emb = Embedder()
    db = FaissDB(dim=X.shape[1])
    db.add(X, texts)
    ret = Retriever(emb, db)
    ctxs = ret.query(args.question, k=args.top_k)
    print(generate_answer(args.question, ctxs))

if __name__ == "__main__":
    main()
