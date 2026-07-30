# Picking this up as a dev

Everything below assumes you're in `apps/extraction-pipeline/`. Context/history
lives in `SCRATCHPAD.md`; the spec is `extraction_pipeline.md`.

## 1. Environment

```bash
source .venv/bin/activate        # already has all deps
python3 -m pytest tests/ -q      # should be 33 passed, ~2s
```

If the venv is gone: `python3 -m venv .venv && pip install -r requirements.txt`,
then `python3 tests/generate_fixtures.py` to rebuild `test_docs/`.

## 2. Run the pipeline against a local model

Stages 0–2 and the report need nothing external:

```bash
python3 pipeline.py --work-dir work snapshot test_docs
python3 pipeline.py --work-dir work index test_docs
python3 pipeline.py --work-dir work normalize
```

Each stage shows a live progress bar (count, ETA, current file) plus
timestamped per-item log lines. While a stage runs: `p` pauses, `r`/space
resumes, `q` (or Ctrl+C) stops after the current item — completed items
are already committed, so re-running the same command resumes where it
left off and skips finished work. A second Ctrl+C aborts immediately.
`-q` drops the per-item lines, `--no-progress` disables the bar/keys
(both are top-level flags, before the subcommand — use them for CI or
when piping to a log; non-TTY output is automatically plain).

Stage 3 against a model you're serving. OpenAI-compatible server
(LM Studio, vLLM, llama.cpp — anything serving `/v1`), verified live
2026-07-19 against LM Studio:

```bash
python3 pipeline.py --work-dir work extract \
    --model-id qwen3-coder-30b-a3b-instruct \
    --model-url http://<local-llm-host>:1234/v1
python3 pipeline.py --work-dir work report
```

Ollama example:

```bash
python3 pipeline.py --work-dir work extract \
    --model-id llama3.2:3b \
    --model-url http://localhost:11434
python3 pipeline.py --work-dir work report
```

Notes on model wiring:

- **No API key needed for local models.** For hosted Gemini/OpenAI, set
  `LANGEXTRACT_API_KEY` or pass `--api-key`.
- A `--model-url` ending in `/v1` is auto-detected as OpenAI-compatible:
  `extractor_backend.py` selects langextract's OpenAI provider explicitly
  (with a placeholder api key — local servers ignore it), and the model id
  is passed through verbatim, so any name your server reports works.
- Otherwise langextract routes `--model-id` to a provider by name pattern:
  `gemma*`, `llama*`, `qwen*`, `mistral*`, `phi*`, `deepseek*`, … → Ollama
  provider; `gemini*` → Gemini; `gpt-4*/gpt-5*` → OpenAI. If your model
  name matches none of these, either alias it in Ollama or wire an
  explicit provider in `pipeline_lib/extractor_backend.py`
  (`make_langextract_extractor` passes extra kwargs straight into
  `lx.extract()`).
- If extraction runs but parsing fails (errors about fenced output /
  malformed JSON), add `fence_output=False, use_schema_constraints=False`
  to the `lx.extract()` call in `extractor_backend.py` — the usual fix for
  small local models.

## 3. Judge the result

- `python3 pipeline.py --work-dir work report` — look at "Exact span
  verification" (want high %) and the grounded-by-class counts.
- `work/ungrounded.jsonl` — everything the model asserted that we couldn't
  verify against the text, with rejection reasons. A weak local model will
  put a lot here; that's the quarantine working, not a pipeline bug.
- Spot-check provenance yourself (success criterion 2 — no pipeline code):

```python
import sqlite3, pathlib
conn = sqlite3.connect("work/index.sqlite"); conn.row_factory = sqlite3.Row
for a in conn.execute("SELECT a.*, r.relative_path p FROM artifact a JOIN representation r USING (representation_id)"):
    text = pathlib.Path("work", a["p"]).read_text()
    assert text[a["char_start"]:a["char_end"]] == a["extraction_text"] or not a["exact_text_match"]
```

- Re-run any stage: it should skip everything (`representations_skipped`,
  `skipped_unchanged`). If a second identical run does work, that's a bug.
- To force a fresh extraction pass (new model, changed prompt), just run
  extract again — the skip key is (langextract version, model id, schema
  hash, model url), so changing any of those redoes work; nothing is ever
  mutated, new runs append.

## 4. The derived catalog (wide table + tags)

`index.sqlite` stays spec-verbatim; anything richer goes in a second,
disposable DB derived from it:

```bash
python3 pipeline.py --work-dir work catalog      # build/update work/catalog.sqlite
python3 pipeline.py --work-dir work tag          # list all tags with counts
python3 pipeline.py --work-dir work tag 79d4 --add important --remove follow-up
python3 pipeline.py --work-dir work catalog --rebuild   # drop + re-derive
```

- `artifact_wide`: one row per artifact — grounded *and* ungrounded
  (`grounded` flag + `rejection_reason`) — with source/representation/run/
  model provenance flattened in, context snippets around each span, and an
  `attr_<key>` column auto-added the first time a model emits a new
  attribute key (every ALTER is audited in `schema_log`). Query it flat,
  no joins: `SELECT * FROM artifact_wide WHERE attr_status='open'`.
- Tags: auto tags re-derived on each sync (`class:task`, `status:open`,
  `match:exact`, `ungrounded`); manual tags (via `tag`, unique id prefix is
  enough) are never touched by sync or rebuild. The `tags` column carries
  a JSON-array mirror for single-table reads.
- Everything is an upsert keyed on artifact_id: re-syncing is idempotent,
  and `--rebuild` is the pare-down path — drops the wide table (stale
  attr columns with it) and re-derives from current data.

## 5. Known gaps to be aware of

- **OCR never ran against a real scanned doc here** (no tessdata in the
  sandbox). First time you feed it scanned PDFs/images, expect to install
  tesseract language data; the retry rule itself is unit-tested
  (`tests/test_ocr_retry.py`).
- Tests fake the model (`tests/fake_extractor.py`) — the grounding logic is
  well covered. The prompt/examples in `extractor_backend.py` got one live
  validation pass (qwen3-coder-30b via LM Studio, 2026-07-19: 18/18 exact
  spans on the test fixtures) but haven't been tuned on a real corpus.
  Iterate on `PROMPT_DESCRIPTION`/`build_examples()` as needed; the schema
  hash makes each iteration a new extraction pass automatically.
