from pathlib import Path
def load_plain_texts(data_dir: str):
    p = Path(data_dir)
    docs = []
    for f in p.rglob("*.txt"):
        docs.append({"path": str(f), "text": f.read_text(encoding="utf-8", errors="ignore")})
    return docs
