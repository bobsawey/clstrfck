# rag-soup (clstrfck)

Dual-zone **data mining** pipeline:
- content-addressable **bronze_raw/**
- **safety adapter** routes risky content to **red_quarantine/**
- normalized **silver_normalized/**
- **catalog/** parquet tables + **dataset cards**

> This is *mining*. Indexing/RAG lives later. Clean vs. quarantine are physically/logically separate.

## Quick start
```bash
cd projects/data-mining/rag-soup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
rag-mine --input ~/some_folder --root ./data --dataset-id ds_example_001
```

Outputs:
- data/bronze_raw/ (immutable originals, content-addressed)
- data/red_quarantine/ vs data/silver_normalized/ (normalized text + chunks)
- data/catalog/docs.parquet, data/catalog/chunks.parquet
- data/catalog/dataset_cards/ds_example_001.yaml

Zones
- silver_normalized/: safe-ish content; OK to index later
- red_quarantine/: NSFW/toxic/illicit/PII/provenance risk; separate keys/ACL/indexes; never cross-query

Swap-ins (next PRs)
- Replace naive text extraction with Tika/unstructured/OCR
- Replace regex safety with ML classifiers
- Add Whoosh/BM25 + FAISS indexers per zone
- Add response controller modes & context envelopes to RAG stack
