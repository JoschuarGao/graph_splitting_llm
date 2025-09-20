# OSM Partition Viewer + RAG Q&A

## Quick Start
```bash
# 1) create env & install deps
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) build index (demo)
python tools/llm_rag/scripts/build_index.py \
  --data_dir tools/llm_rag/data/raw \
  --out_dir tools/llm_rag/data/index

# 3) run app
python app_qt.py
