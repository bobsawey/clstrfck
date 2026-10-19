# Provenance-Preserving Extraction Pipeline — First-Pass Spec (v1)

## Purpose

Build a resumable pipeline that snapshots a source directory, deterministically
indexes every file, normalizes supported documents to UTF-8 text/Markdown via
Xberg, runs LangExtract to produce semantic artifacts (decision, task, claim,
question, reference), and grounds every artifact to an exact character span
traceable back to the original file bytes.

## Core Principle (load-bearing, non-negotiable)

The LLM makes bounded semantic decisions. Deterministic code owns:
file paths, hashes, IDs, run IDs, page numbers, character offsets, cache
state, and all provenance relationships. No model output is ever used as an
identifier, hash, offset, or file reference. Model output that cannot be
verified against source text is quarantined, never committed.

## Environment

- Python 3.11+, stdlib-first: `pathlib`, `os.scandir`, `sqlite3`, `json`
- `blake3` (pip) for content hashes
- `xberg` (pip) — PIN THE EXACT VERSION (currently 1.0.0-rc.x; it is a
  release candidate). Record the pinned version in the index.
- `langextract` (pip) — pinned version, recorded in the index.
- `charset-normalizer` (pip) for encoding detection.
- One CLI entry point, `pipeline.py`, with subcommands:
  `snapshot`, `index`, `normalize`, `extract`, `report`.
- All state lives in one SQLite file: `work/index.sqlite`.
- All stages are idempotent and resumable. Re-running a stage skips
  completed work (see Incremental Rules).

## Directory Layout

    <source-root>/            original files, never written to
    work/
      snapshot/               stage 0 immutable archive copy
      normalized/             stage 2 text/markdown/layout outputs
      artifacts.jsonl         stage 3 grounded artifacts
      ungrounded.jsonl        stage 3 quarantined model output
      index.sqlite            all pipeline state
      logs/

---

## Stage 0 — Snapshot

Create one immutable archive copy of the source tree before any other
operation touches it.

    rsync -aAX --exclude-from=excludes.txt <source-root>/ work/snapshot/

- `-aAX` preserves permissions, mtimes, ACLs, and xattrs.
- Excludes: `.git/`, `node_modules/`, `__pycache__/`, `.venv/`, `venv/`,
  build output dirs, and `work/` itself.
- After rsync completes, the pipeline reads ONLY from `work/snapshot/`.
  The original source root is never opened again.
- Record in SQLite: snapshot timestamp, rsync exit code, source root URI,
  file count, total bytes.

## Stage 1 — Index

Recursively scan `work/snapshot/` and record every file (in scope or not).

For each file, compute and store:

- `relative_path` (relative to snapshot root)
- `extension`
- `mime_type` — from Xberg format detection, with Python `mimetypes` as
  fallback; record which detector answered
- `size_bytes`, `mtime_ns`, `mode`
- `xattrs_json` — full xattr dump (`os.listxattr`/`os.getxattr`)
  serialized to JSON; empty object if none. This preserves original
  metadata independent of any later copy/move.
- `content_hash` — blake3 of file bytes
- `source_id` — `"src_" + blake3(content_hash + "\x00" + relative_path)`
  hex-truncated to 16 chars. Deterministic; same file at same path always
  yields the same ID.
- `scope` — one of:
  - `text` — direct text inputs: .txt .md .rst .json .jsonl .csv .yaml
    .yml .py .js .ts .html
  - `document` — needs Xberg normalization: .pdf .png .jpg .jpeg .docx .pptx
  - `out_of_scope` — everything else. Still indexed (path, hash, metadata)
    so the corpus inventory is complete; skipped by later stages.
- `status` — `indexed` initially.

Scope assignment uses MIME type when detection succeeds, extension as
fallback; record which rule fired in a `scope_reason` column.

## Stage 2 — Normalize

Every in-scope source gets exactly one canonical text representation that
later stages ground against.

### 2a. Text files (`scope = text`)

- Detect encoding with charset-normalizer; record detected encoding and
  confidence.
- Convert to UTF-8, normalize line endings to `\n`, strip BOM.
- Write to `work/normalized/<relative_path>` preserving directory
  structure. If the byte content is already canonical (UTF-8, LF, no BOM),
  still write the copy — the normalized file is the single source of truth
  for spans.
- Record a `representation` row: kind `text_utf8`, its own blake3 hash,
  extractor `internal-textnorm`, extractor version = pipeline version.
- Files that fail decoding (binary masquerading as text, broken encodings)
  → `extraction_error` row, stage `normalize`, source status `quarantined`.
  Continue.

### 2b. Documents (`scope = document`)

Run Xberg extraction (Python bindings, batch API — batch per directory or
per N files, not one call per file):

- Markdown output → `work/normalized/<relative_path>.md`
  (e.g. `research/report.pdf` → `normalized/research/report.pdf.md`;
  keeping the original extension in the name prevents collisions between
  `report.pdf` and `report.docx`)
- Structured JSON output (Xberg "Structured" format: OCR metadata, page
  markers, bounding boxes where available) →
  `work/normalized/<relative_path>.layout.json`
- Enable Xberg page tracking so page markers appear in the Markdown.
- OCR: Xberg's default backend with its built-in fallback chain. Do NOT
  add Docling or VLM OCR in this pass.
- One deterministic retry rule (this is the entire "agent"): if the
  Markdown output is empty or under 32 bytes for a file whose source is
  over 4 KB, retry once with `force_ocr=true`. If still empty →
  `extraction_error`, status `quarantined`. Log every retry.
- Record one `representation` row per output file (kinds: `markdown`,
  `layout_json`), each with its own hash, extractor `xberg`, the pinned
  Xberg version, and a `config_hash` (blake3 of the serialized Xberg
  config used).

Raw layout JSON is preserved on disk but NOT modeled in SQLite beyond the
representation row. No observation/bbox tables in this pass.

## Stage 3 — Extract (LangExtract)

Follow the LangExtract getting-started pattern: define extraction classes
with a prompt description and 2–3 few-shot examples each, then run over
each canonical text representation (`text_utf8` and `markdown` kinds).

Extraction classes for this pass:

- `decision` — a choice that was made ("use SQLite for the index")
- `task` — an action to perform ("benchmark FTS5 before Friday")
- `claim` — a falsifiable assertion
- `question` — an open question
- `reference` — a citation, URL, or pointer to another document

For each extraction returned:

1. Read LangExtract's character interval (`char_start`, `char_end`)
   against the normalized text.
2. Verification (deterministic, ours): slice
   `normalized_text[char_start:char_end]` and compare to the extraction
   text. Record `exact_text_match` (bool) and `alignment_status`
   (LangExtract's own status: match_exact / match_fuzzy / etc.).
3. Compute `line_number` and `column_number` from the offset (cheap; do it
   here so consumers don't need the file).
4. `artifact_id` = `"art_" + blake3(representation_id + "\x00" +
   extraction_class + "\x00" + str(char_start) + ":" + str(char_end) +
   "\x00" + extraction_text)` truncated to 16 hex chars.
5. Grounded (valid interval + slice verification passes or fuzzy-matches):
   write to `artifact` table AND append to `artifacts.jsonl`.
6. Ungrounded (no interval, interval out of range, or slice mismatch
   beyond fuzzy tolerance): append full record to `ungrounded.jsonl` with
   rejection reason. Never write to the artifact table.

Batch documents into LangExtract calls per its API; continue past
per-document failures (record `extraction_error`, stage `extract`).

### artifacts.jsonl record shape

    {
      "artifact_id": "art_a6197b70deadbeef",
      "artifact": {
        "class": "task",
        "text": "benchmark FTS5 before Friday",
        "attributes": {"status": "open", "deadline_text": "before Friday"}
      },
      "provenance": {
        "source_id": "src_53caf681...",
        "relative_path": "research/database-notes.md",
        "content_hash": "1ce9d4...",
        "representation_id": "rep_43ab...",
        "run_id": "run_20260712_013455",
        "span": {"start": 114, "end": 143, "line": 7, "column": 9},
        "alignment_status": "match_exact",
        "exact_text_match": true
      }
    }

### ungrounded.jsonl record shape

Same shape plus `"rejection_reason"`, with span fields null where absent.

---

## SQLite Schema

    CREATE TABLE run (
      run_id TEXT PRIMARY KEY,          -- run_YYYYMMDD_HHMMSS
      stage TEXT NOT NULL,              -- snapshot|index|normalize|extract
      started_at TEXT, finished_at TEXT,
      pipeline_version TEXT,
      xberg_version TEXT, langextract_version TEXT,
      model_id TEXT,                    -- LLM used by LangExtract
      config_json TEXT
    );

    CREATE TABLE source (
      source_id TEXT PRIMARY KEY,
      root_uri TEXT, relative_path TEXT NOT NULL,
      extension TEXT, mime_type TEXT, mime_detector TEXT,
      scope TEXT NOT NULL, scope_reason TEXT,
      size_bytes INTEGER, mtime_ns INTEGER, mode INTEGER,
      xattrs_json TEXT,
      content_hash TEXT NOT NULL,
      status TEXT NOT NULL,             -- indexed|normalized|extracted|quarantined
      first_run_id TEXT, last_run_id TEXT
    );
    CREATE UNIQUE INDEX idx_source_path ON source(relative_path);

    CREATE TABLE representation (
      representation_id TEXT PRIMARY KEY,   -- rep_ + blake3(source_id+kind+config_hash)[:16]
      source_id TEXT NOT NULL REFERENCES source(source_id),
      kind TEXT NOT NULL,                   -- text_utf8|markdown|layout_json
      relative_path TEXT NOT NULL,          -- under work/normalized/
      content_hash TEXT NOT NULL,
      extractor TEXT, extractor_version TEXT, config_hash TEXT,
      run_id TEXT
    );

    CREATE TABLE artifact (
      artifact_id TEXT PRIMARY KEY,
      representation_id TEXT NOT NULL REFERENCES representation(representation_id),
      extraction_class TEXT NOT NULL,
      extraction_text TEXT NOT NULL,
      attributes_json TEXT,
      char_start INTEGER, char_end INTEGER,
      line_number INTEGER, column_number INTEGER,
      alignment_status TEXT, exact_text_match INTEGER,
      run_id TEXT
    );

    CREATE TABLE extraction_error (
      source_id TEXT, stage TEXT, error_code TEXT,
      message TEXT, run_id TEXT
    );

## Incremental Rules

Skip a source in `normalize` when a representation exists whose
(source content_hash, extractor, extractor_version, config_hash) all match.

Skip a representation in `extract` when artifacts exist for it under the
same (langextract_version, model_id, schema config_hash).

Changing any element of either tuple produces new representations or a new
extraction pass. Never mutate existing artifact rows; new runs append.

## Failure Discipline

- No stage aborts on a single-file failure; log to `extraction_error`,
  mark status, continue.
- Encrypted, unreadable, or malformed files → `quarantined`, visible in
  the report.
- Model output without verifiable grounding → `ungrounded.jsonl` only.

## Run Report (`pipeline.py report`)

Print per-run and cumulative:

    N sources discovered / in scope / out of scope
    N unchanged and skipped
    N normalized (text / document), N OCR retries
    N quarantined (with reasons)
    N grounded artifacts by class
    N ungrounded outputs
    % exact span verification
    wall time, model cost if available from LangExtract

## Success Criteria

1. Two consecutive runs over an unchanged corpus: second run does no work.
2. Every artifact's `source_text` slice check reproducible by a 5-line
   script reading only `index.sqlite` + `work/normalized/`.
3. Quarantine and ungrounded paths demonstrably exercised (include one
   corrupt file and one adversarial doc in test fixtures).
4. Original xattrs/mtimes recoverable from the index for every source.

## Explicitly Deferred (do not build)

Rust indexer, PyO3 bindings, reflink/hardlink materialization, W3C PROV,
anchorpoint selectors, Docling/VLM OCR fallbacks, agentic processor
selection, OCR element identity across reruns, bbox modeling in SQLite,
graph databases, additional file formats, distributed execution.
