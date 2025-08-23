Data Mining & Preparation

This describes the end-to-end pipeline that turns raw files/web captures into canonical, chunked, embedded, and provenance-rich artifacts ready for the graph and retrieval.

TL;DR (one-box quickstart)

```
# 0) Configure
cp configs/mining.local.example.yaml configs/mining.local.yaml

# 1) Ingest & extract
python apps/miner/ingest.py   --config configs/mining.local.yaml
python apps/miner/extract.py  --config configs/mining.local.yaml

# 2) Normalize, dedupe, chunk
python apps/miner/normalize.py --config configs/mining.local.yaml
python apps/miner/dedupe.py    --config configs/mining.local.yaml
python apps/miner/chunk.py     --config configs/mining.local.yaml

# 3) Embed & enrich
python apps/miner/embed.py     --config configs/mining.local.yaml
python apps/miner/entities.py  --config configs/mining.local.yaml  # optional NER/topics

# 4) Load to graph (Neo4j) and build kNN edges
python apps/engine-graph/load_graph.py   --config configs/mining.local.yaml
python apps/engine-graph/build_knn.py    --k 20
```

---

Pipeline overview

Raw FS/Web → Ingest → Blob store (content-addressed) → Extract text
      → Normalize (recipe_v) → Dedupe (byte + text + near dup)
      → Chunk (semantic windows) → Embed → (optional) Entities/Topics
      → Write Parquet tables → Load to Graph + kNN + density
      → Ready for search (vector seeds + PPR) with full provenance

Everything is non-destructive: we never throw away source locations; we just canonicalize payloads for indexing.

---

Repo layout (suggested)

```
apps/
  miner/
    ingest.py        # discover sources, hash blobs, write sources.parquet + blobs.parquet
    extract.py       # parse/convert to text, write extractions.parquet
    normalize.py     # normalize text (recipe_v), write normalized_extractions.parquet
    dedupe.py        # exact + near-dup signatures, write dedupe_map.parquet
    chunk.py         # semantic windows, write chunks.parquet
    embed.py         # vectors for docs/chunks, write embeddings.parquet
    entities.py      # NER/topics (optional), write entities.parquet, mentions.parquet
    utils/           # hashing, CDC, text cleaning, io, logging helpers
configs/
  mining.local.example.yaml
data/
  raw/               # original inputs (read-only)
  objects/           # blobs/ (zstd), frags/ (if using CDC)
  processed/         # all parquet outputs
  logs/              # runs.jsonl (append-only)
docs/
  architecture.md
  mining-prep.md     # ← this file
```

---

Config (example)

```
configs/mining.local.example.yaml

paths:
  input_dirs:
    - "/abs/path/to/your/text"
  object_store: "data/objects"
  processed_dir: "data/processed"
  logs_dir: "data/logs"

ingest:
  include_globs: ["**/*.txt","**/*.md","**/*.pdf","**/*.html","**/*.eml","**/*.json"]
  exclude_globs: ["**/.git/**","**/node_modules/**"]
  cdc:
    enabled: false             # enable later if helpful
    avg_size_kb: 128

extract:
  html:
    strip_boilerplate: true
  pdf:
    strategy: "auto"           # "ocr"|"text"|"auto"
  email:
    keep_headers: true

normalize:
  recipe_v: "v1"
  unicode_nf: "NFKC"
  lower: false
  collapse_whitespace: true
  strip_boilerplate: true

dedupe:
  exact_hash: "blake3"
  near_dup:
    simhash_bits: 64
    minhash_bands: 32
    minhash_rows: 4
    threshold: 0.88

chunk:
  target_tokens: 800
  overlap_tokens: 200
  splitter: "semantic"     # "semantic" | "fixed"
  max_chars: 8000

embed:
  model: "bge-small"
  dtype: "fp16"
  batch_size: 128

entities:
  enabled: false
  model: "spacy/en_core_web_trf"

neo4j:
  uri: "bolt://localhost:7687"
  user: "neo4j"
  password: "test"
```

---

Data contracts (Parquet tables)

All tables live under data/processed/. Columns shown are minimum; you can add more.

```
sources.parquet (every acquisition)

coltypedescription
source_idstrUUID per acquisition
uristrpath/URL/mailbox ref
collected_atintepoch ms
mimestrdetected mime
size_bytesintoriginal size
sha256strraw file hash
blob_cidstrcontent-address (blake3)
headersjsonHTTP/email headers if available
licensestrknown/assumed license
labelsjsonuser tags

blobs.parquet

| blob_cid, sha256, size_bytes, mime, storage_uri |

extractions.parquet

coltype
ext_cid (hash of text + recipe_v)str
blob_cidstr
recipe_vstr
text_stats (chars,tokens,lang)json
text_uri (optional, zstd)str

normalized_extractions.parquet

| norm_cid, ext_cid, norm_hash, simhash64, minhash_sig, lang, text_uri |

chunks.parquet

| chunk_id (hash of text+recipe_v), norm_cid, span_start, span_end, text, norm_hash |

embeddings.parquet

| obj_type (“doc”|“chunk”), obj_id, model, dim, dtype, vector (list/ndarray) |

(optional) entities.parquet, mentions.parquet
•Entities: entity_id, name, type
•Mentions: chunk_id, entity_id, offset_start, offset_end

dedupe_map.parquet

| norm_hash, canonical_chunk_id |

runs.parquet

| run_id, kind, params_json, git_sha, started_at, ended_at, counts_json, status |
```

---

Step-by-step details

1) Ingest
•Walk inputs; record a source_id per file/mail/web fetch.
•Compute blob_cid = blake3(raw_bytes); store once under data/objects/blobs/<blob_cid>.zst.
•(Optional) CDC (content-defined chunking): cut blobs by rolling hash; store fragments under objects/frags/<frag_cid>. Keep a manifest to reconstruct originals.

CLI sketch (ingest.py)

```
# discover files → hash → write sources.parquet, blobs.parquet
# store blobs compressed (zstd) at objects/blobs/<cid>.zst
```

2) Extract
•Parse to text (PDF/HTML/email/Office). Keep raw HTML/WARC when possible.
•Write extractions.parquet with ext_cid = hash(text + recipe_v).

3) Normalize (versioned recipe)

Apply your recipe_v steps consistently:
•Unicode NFKC, collapse whitespace, strip boilerplate, (optionally) lowercase, normalize numbers/dates.
•Write norm_cid, norm_hash (exact), simhash64 and/or MinHash signature for near-dups.

Pseudo

```
norm = normalize(text, recipe_v="v1")
norm_hash = blake3(norm.encode())
simhash64 = simhash(norm, bits=64)
minhash_sig = minhash(norm, n_perm=128)
```

4) Dedupe (non-destructive)
•Exact: group by norm_hash; choose a canonical chunk per group.
•Near-dup: LSH over simhash or minhash to cluster; optionally point alternates to the canonical via dedupe_map.parquet.
•Never delete provenance: every source_id still links to its blob_cid and derivations.

5) Chunk
•Default: semantic windows targeting ~800 tokens with ~200 overlap (fallback to fixed length).
•Emit chunks.parquet with chunk_id = hash(chunk_text + recipe_v), offsets back into the normalized text.

6) Embed
•Pick a single model to start (e.g., bge-small). Store vectors in embeddings.parquet (doc-level + chunk-level).
•Use fp16 vectors to keep the graph index light; keep full-precision offline if you like.

7) (Optional) Entities/Topics
•Run NER/topic assignment and write entities.parquet + mentions.parquet.
•These become :Entity nodes and :MENTIONS edges in the graph.

8) Lineage & logging (every step)
•Append a line to data/logs/runs.jsonl:

```
{"run_id":"...","kind":"normalize","params":{"recipe_v":"v1"},"git_sha":"abc123","started_at":..., "ended_at":..., "counts":{"inputs":1234,"outputs":1201},"status":"ok"}
```

•Also create a :Run node in Neo4j and connect it to produced nodes when you load.

---

Graph loading & enrichment (bridge to /docs/architecture.md)
•Upsert :Doc, :Chunk, :Entity nodes + HAS_CHUNK, MENTIONS.
•Create Neo4j vector index on :Chunk(embedding).
•Build SIMILAR_TO edges via gds.knn.write and set knn_density = avg(outgoing.score).

---

“Hot set” policy (simple to start)
•Promote all chunks initially.
•Later, only promote chunks that are: recent, high-quality, clicked/used, or central (density/PR).
•Demotion = remove from vector/graph indices (keep Parquet + provenance).

---

Quality gates (optional, helpful)

Compute and store per-doc metrics; filter at query time or during promotion:
•lang, token_len, readability, link_density, dup_ratio, age_days, source_quality (hand-tuned).
•A simple rule: suppress results if token_len < 60 or dup_ratio > .9 unless explicitly requested.

---

Rehydration & provenance

Every result can be traced back:

Chunk → Extraction(norm_cid, span) → Blob(blob_cid) → Source(uri, collected_at)

Use spans to re-render the surrounding context or reconstruct full files from the blob (or CDC manifest).

---

Make/Just helpers (optional)

```
Justfile

setup:          # create venv, install deps
mine:           # ingest→extract→normalize→dedupe→chunk→embed
graph:          # load_graph→build_knn
rebuild:        # mine + graph
```

---

Testing (quick checks you’ll keep running)
•Determinism: hashing and recipe_v produce the same norm_hash across runs.
•Reversibility: every chunk maps back to a single norm_cid and blob lineage exists.
•Dedupe sanity: no two canonical chunks share the same norm_hash.
•Indexability: Neo4j vector index loaded for all promoted chunks.

---

Security & licensing notes
•If you’ll mine mailboxes/web: consider a PII scrub pass for output display while keeping raw blobs sealed.
•Track license and terms at the Source level; propagate to Doc/Chunk metadata.

---

What’s “pluggable”
•Extractors (Tika/Unstructured/Trafilatura/etc.)
•Normalizer (recipe versions)
•Dedup (SimHash/MinHash/LSH)
•Splitter (semantic/fixed)
•Embedder (model name/dim)
•Entity/Topic engines

All components are hidden behind tiny interfaces so you can swap them later without touching the graph/query surface.

---

If you want, I can also drop in minimal Python stubs for each step (typer CLIs + IO helpers) so Codex can expand them into fully working scripts.
