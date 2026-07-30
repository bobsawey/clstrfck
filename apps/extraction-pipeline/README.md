# extraction-pipeline

A provenance-preserving document extraction pipeline: snapshot a source
directory, deterministically index every file, normalize documents to UTF-8
text/Markdown, run LLM extraction (LangExtract) to produce semantic artifacts
(decision, task, claim, question, reference), and ground every artifact to an
exact character span traceable back to the original file bytes.

Core principle: the LLM makes bounded semantic decisions; deterministic code
owns all paths, hashes, IDs, offsets, and provenance. Model output that can't
be verified against source text is quarantined, never committed.

This is the working successor to the earlier `apps/miner` stubs and the
pipeline sketched in `docs/mining-prep.md`.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -m pytest tests/ -q          # 33 passed, ~2s

python3 pipeline.py --work-dir work snapshot test_docs
python3 pipeline.py --work-dir work index test_docs
python3 pipeline.py --work-dir work normalize
python3 pipeline.py --work-dir work extract \
    --model-id <your-model> --model-url http://localhost:1234/v1
python3 pipeline.py --work-dir work report
```

Works against any OpenAI-compatible server (LM Studio, vLLM, llama.cpp) or
Ollama with no API key; hosted Gemini/OpenAI via `LANGEXTRACT_API_KEY`.

## Docs

- [`extraction_pipeline.md`](extraction_pipeline.md) — the spec (v1)
- [`DEVELOPING.md`](DEVELOPING.md) — dev setup, running against local models,
  judging results, known gaps
- [`NOTES-sqlite-and-schema.md`](NOTES-sqlite-and-schema.md) — schema notes
- [`SCRATCHPAD.md`](SCRATCHPAD.md) — working history/context
