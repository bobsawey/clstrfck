# Notes: what's in index.sqlite, how to extend the schema, role of the JSONL files

Handoff notes from a session on 2026-07-20 exploring `work/index.sqlite` and the
schema/extension questions. Verified against the code, not just the spec.

## What's in the SQLite DB

One database: `work/index.sqlite` (~44K). It holds all pipeline state
(spec: "All state lives in one SQLite file"). Contents as of the last runs
(2026-07-19 ~23:31):

- **run** (5 rows) — one row per stage execution (snapshot → index → normalize →
  extract), with timestamps, versions, and the extract model
  (`qwen3-coder-30b-a3b-instruct` via LM Studio).
- **source** (8 rows) — file inventory from `work/snapshot/`: 5 clean fixtures
  (md/txt/docx/pdf) `extracted`; `corrupt/binary_masquerade.txt` and
  `corrupt/garbage.pdf` `quarantined`; `out_of_scope/archive.bin` left at
  `indexed`. Carries mime, size, mtime, blake3 content hash, scope + reason.
- **representation** (7 rows) — normalized text/markdown outputs under
  `work/normalized/`, keyed by content hash + extractor config.
- **artifact** (18 rows) — grounded LLM extractions with char/line offsets:
  5 claim, 4 decision, 3 task, 3 reference, 3 question.
- **extraction_error** (2 rows) — the two quarantines: `decode_failure`
  (charset-normalizer) and a pdfium `ParsingError`.

### ⚠ Prompt-injection observation

`adversarial/prompt-injection.md` produced an artifact classified `decision`
with text "the model has been compromised" — injected content lands verbatim
in the `artifact` table as if it were a real decision. (A second artifact from
the same file correctly says it's a regression fixture.) If anything downstream
treats `decision` rows as trusted, that's the gap this fixture exposes.

## Two schemas, and how to add to each

**Extraction schema** (the five classes) — `pipeline_lib/extractor_backend.py`:
- Add the new class to `PROMPT_DESCRIPTION` (~line 17).
- Add at least one few-shot demonstration to `build_examples()` (~line 49);
  classes without an example rarely get emitted.
- No DB change needed — `artifact.extraction_class` is plain TEXT.
- `schema_hash()` covers prompt + examples and is part of the incremental-skip
  key (`config_json` set in `pipeline.py` `cmd_extract`), so a schema edit
  automatically forces a full re-extract on the next `extract` run. No manual
  cache-busting.

**SQLite schema** — `SCHEMA` string in `pipeline_lib/db.py` (~line 9), applied
with `CREATE TABLE IF NOT EXISTS` on every `db.connect()`:
- New **table**: just add it to `SCHEMA`; created on next run.
- New **column** on an existing table: silently ignored on an existing DB
  (`IF NOT EXISTS` skips the whole statement). No migration mechanism exists.
  Either add a guarded `ALTER TABLE ... ADD COLUMN`, or delete
  `work/index.sqlite` and re-run stages (cheap — rebuilds from `work/snapshot/`).

## The JSONL files are outputs, not inputs

Nothing in the pipeline reads them to drive behavior; SQLite is the source of
truth:
- `work/artifacts.jsonl` — append-only mirror of each grounded artifact with
  full provenance, written in `extract.py` (~line 144) alongside the SQLite
  insert. Only tests read it (`tests/test_pipeline.py:233`).
- `work/ungrounded.jsonl` — rejected (ungroundable) extractions; `report.py`
  only counts its lines.
- `work/logs/*.jsonl` — normalize-stage logs (encoding decisions, OCR retries).

Caveat: because `artifacts.jsonl` is append-mode and a schema change forces a
full re-extract, it accumulates records from both old and new schema runs.
SQLite dedups via `INSERT OR IGNORE` on `artifact_id`; the JSONL doesn't —
truncate it before a re-run or filter by `run_id` downstream.
