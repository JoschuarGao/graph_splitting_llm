import argparse, os, sys, numpy as np
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(BASE)

from rag.loader import load_plain_texts
from rag.splitter import split_text
from rag.embedder import Embedder
from rag.vectordb import FaissDB

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--out_dir", required=True)
    ap.add_argument("--chunk_size", type=int, default=500)
    ap.add_argument("--chunk_overlap", type=int, default=50)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    docs = load_plain_texts(args.data_dir)
    chunks = []
    for d in docs:
        for c in split_text(d["text"], args.chunk_size, args.chunk_overlap):
            if c.strip():
                chunks.append(c.strip())

    emb = Embedder()
    X = emb.encode(chunks)
    db = FaissDB(dim=X.shape[1])
    db.add(np.array(X), chunks)

    np.save(os.path.join(args.out_dir, "vectors.npy"), X)
    with open(os.path.join(args.out_dir, "texts.txt"), "w", encoding="utf-8") as f:
        for t in chunks: f.write(t.replace("\\n"," ") + "\\n")
    print(f"[OK] Indexed {len(chunks)} chunks to {args.out_dir}")

if __name__ == "__main__":
    main()
