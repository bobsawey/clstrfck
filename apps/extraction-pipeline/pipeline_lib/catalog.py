"""Derived catalog -- `work/catalog.sqlite`.

A second SQLite file, deliberately separate from the spec-verbatim
`index.sqlite`: everything here is *derived* and can be rebuilt from the
primary DB + the JSONLs at any time, so this schema is free to be wide,
denormalized, and to grow columns as work evolves.

Three ideas:

- `artifact_wide`: one row per artifact (grounded AND ungrounded), with
  source/representation/run/model provenance flattened alongside it, plus
  context snippets from the normalized text. Model-emitted attribute keys
  become real `attr_<key>` columns, added automatically the first time a
  key appears (add-only ALTERs; every addition is recorded in
  `schema_log`). Pare back down by rebuilding: `sync(..., rebuild=True)`
  drops the wide table and re-derives it with only the columns the current
  data needs.
- Tags: `tag` (vocabulary) + `artifact_tag` (assignments). Auto tags are
  re-derived on every sync (`class:task`, `status:open`, `match:exact`,
  `ungrounded`, ...); manual tags (origin='manual') are never touched by a
  sync or rebuild. A denormalized `tags` JSON array column on
  `artifact_wide` keeps single-table queries easy.
- Upsert everywhere, keyed on artifact_id: syncing is idempotent and
  incremental, same as every other stage.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import NullProgress
from pipeline_lib.version import PIPELINE_VERSION

CONTEXT_CHARS = 100
TAG_VALUE_MAX = 60

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS artifact_wide (
  artifact_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS tag (
  tag TEXT PRIMARY KEY,
  description TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS artifact_tag (
  artifact_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  origin TEXT NOT NULL,             -- auto|manual
  created_at TEXT,
  PRIMARY KEY (artifact_id, tag)
);

CREATE TABLE IF NOT EXISTS schema_log (
  at TEXT, table_name TEXT, column_name TEXT, decl TEXT, reason TEXT
);

CREATE TABLE IF NOT EXISTS sync_run (
  started_at TEXT, finished_at TEXT, pipeline_version TEXT,
  grounded_rows INTEGER, ungrounded_rows INTEGER,
  columns_added_json TEXT, rebuild INTEGER
);
"""

# Everything except the primary key goes through ensure_columns(), so the
# base layout and later additions evolve by the exact same mechanism.
BASE_COLUMNS: dict[str, str] = {
    "grounded": "INTEGER",
    "extraction_class": "TEXT",
    "extraction_text": "TEXT",
    "text_length": "INTEGER",
    "word_count": "INTEGER",
    "attributes_json": "TEXT",
    "char_start": "INTEGER",
    "char_end": "INTEGER",
    "line_number": "INTEGER",
    "column_number": "INTEGER",
    "alignment_status": "TEXT",
    "exact_text_match": "INTEGER",
    "rejection_reason": "TEXT",
    "context_before": "TEXT",
    "context_after": "TEXT",
    "representation_id": "TEXT",
    "rep_kind": "TEXT",
    "rep_path": "TEXT",
    "rep_content_hash": "TEXT",
    "source_id": "TEXT",
    "source_path": "TEXT",
    "source_extension": "TEXT",
    "source_mime": "TEXT",
    "source_scope": "TEXT",
    "source_size_bytes": "INTEGER",
    "source_mtime_ns": "INTEGER",
    "source_status": "TEXT",
    "source_content_hash": "TEXT",
    "run_id": "TEXT",
    "run_started_at": "TEXT",
    "model_id": "TEXT",
    "langextract_version": "TEXT",
    "pipeline_version": "TEXT",
    "run_config_json": "TEXT",
    "tags": "TEXT",  # JSON array, denormalized mirror of artifact_tag
    "first_synced_at": "TEXT",
    "synced_at": "TEXT",
}

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_wide_class ON artifact_wide(extraction_class);
CREATE INDEX IF NOT EXISTS idx_wide_source ON artifact_wide(source_path);
CREATE INDEX IF NOT EXISTS idx_wide_grounded ON artifact_wide(grounded);
CREATE INDEX IF NOT EXISTS idx_atag_tag ON artifact_tag(tag);
"""


@dataclass
class CatalogStats:
    grounded_rows: int = 0
    ungrounded_rows: int = 0
    columns_added: list = field(default_factory=list)
    auto_tags: int = 0
    by_class: dict = field(default_factory=dict)
    stopped: bool = False


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def connect(catalog_path: Path) -> sqlite3.Connection:
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(catalog_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(BASE_SCHEMA)
    ensure_columns(conn, "artifact_wide", BASE_COLUMNS, reason="base")
    conn.executescript(INDEXES)
    conn.commit()
    return conn


# -- schema evolution --------------------------------------------------------

def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]

def ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str], reason: str,
) -> list[str]:
    """Add-only migration: any column not yet on `table` is ALTERed in and
    recorded in schema_log. Existing columns are never modified."""
    existing = set(table_columns(conn, table))
    added = []
    for name, decl in columns.items():
        if name in existing:
            continue
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {decl}')
        conn.execute(
            "INSERT INTO schema_log (at, table_name, column_name, decl, reason) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), table, name, decl, reason),
        )
        added.append(name)
    return added


def attr_column(key: str) -> str:
    return "attr_" + re.sub(r"[^a-z0-9_]+", "_", key.strip().lower()).strip("_")


def _attr_value(value) -> tuple[str, object]:
    """Map an attribute value to (column decl, stored value)."""
    if isinstance(value, bool):
        return "INTEGER", int(value)
    if isinstance(value, int):
        return "INTEGER", value
    if isinstance(value, float):
        return "REAL", value
    if isinstance(value, str):
        return "TEXT", value
    return "TEXT", json.dumps(value, sort_keys=True)


def upsert(conn: sqlite3.Connection, table: str, key_col: str, row: dict) -> None:
    cols = list(row)
    col_sql = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(
        f'"{c}" = excluded."{c}"'
        for c in cols
        if c not in (key_col, "first_synced_at")
    )
    conn.execute(
        f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders}) '
        f'ON CONFLICT("{key_col}") DO UPDATE SET {updates}',
        [row[c] for c in cols],
    )


# -- tagging -----------------------------------------------------------------

def _apply_tag(
    conn: sqlite3.Connection, artifact_id: str, tag: str, origin: str,
) -> bool:
    conn.execute(
        "INSERT OR IGNORE INTO tag (tag, created_at) VALUES (?, ?)", (tag, _now()),
    )
    cur = conn.execute(
        "INSERT OR IGNORE INTO artifact_tag (artifact_id, tag, origin, created_at) "
        "VALUES (?, ?, ?, ?)",
        (artifact_id, tag, origin, _now()),
    )
    return cur.rowcount > 0


def _refresh_tags_column(conn: sqlite3.Connection, artifact_id: str) -> list[str]:
    tags = [
        r["tag"] for r in conn.execute(
            "SELECT tag FROM artifact_tag WHERE artifact_id = ? ORDER BY tag",
            (artifact_id,),
        )
    ]
    conn.execute(
        "UPDATE artifact_wide SET tags = ? WHERE artifact_id = ?",
        (json.dumps(tags), artifact_id),
    )
    return tags


def _auto_tags(record: dict) -> list[str]:
    tags = [f"class:{record['extraction_class']}"]
    if record.get("grounded"):
        tags.append(
            "match:exact" if record.get("exact_text_match") else "match:fuzzy"
        )
    else:
        tags.append("ungrounded")
    attributes = record.get("attributes") or {}
    for key, value in sorted(attributes.items()):
        if isinstance(value, (str, int, float, bool)):
            tags.append(f"{key}:{value}"[:TAG_VALUE_MAX])
    return tags


def resolve_artifact(conn: sqlite3.Connection, prefix: str) -> str:
    """Expand an artifact_id prefix ('art_ab12' or just 'ab12') to the one
    matching row; raises ValueError when it matches zero or several."""
    if not prefix.startswith("art_"):
        prefix = "art_" + prefix
    rows = conn.execute(
        "SELECT artifact_id FROM artifact_wide WHERE artifact_id LIKE ? LIMIT 5",
        (prefix + "%",),
    ).fetchall()
    if len(rows) == 1:
        return rows[0]["artifact_id"]
    if not rows:
        raise ValueError(f"no artifact matches {prefix!r} (run `catalog` to sync?)")
    candidates = ", ".join(r["artifact_id"] for r in rows)
    raise ValueError(f"{prefix!r} is ambiguous: {candidates}")


def add_manual_tag(conn: sqlite3.Connection, artifact_prefix: str, tag: str) -> str:
    artifact_id = resolve_artifact(conn, artifact_prefix)
    _apply_tag(conn, artifact_id, tag, origin="manual")
    _refresh_tags_column(conn, artifact_id)
    conn.commit()
    return artifact_id


def remove_tag(conn: sqlite3.Connection, artifact_prefix: str, tag: str) -> str:
    artifact_id = resolve_artifact(conn, artifact_prefix)
    conn.execute(
        "DELETE FROM artifact_tag WHERE artifact_id = ? AND tag = ?",
        (artifact_id, tag),
    )
    _refresh_tags_column(conn, artifact_id)
    conn.commit()
    return artifact_id


def tag_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        r["tag"]: r["n"] for r in conn.execute(
            "SELECT tag, COUNT(*) AS n FROM artifact_tag "
            "GROUP BY tag ORDER BY n DESC, tag"
        )
    }


# -- sync --------------------------------------------------------------------

def _context(text: str | None, start, end) -> tuple[str | None, str | None]:
    if text is None or start is None or end is None:
        return None, None
    return (
        text[max(0, start - CONTEXT_CHARS):start],
        text[end:end + CONTEXT_CHARS],
    )


def _ungrounded_records(work: WorkPaths) -> dict[str, dict]:
    """Last record per artifact_id from ungrounded.jsonl (may repeat across
    runs; upsert semantics -- last one wins)."""
    records: dict[str, dict] = {}
    if not work.ungrounded_jsonl.exists():
        return records
    with open(work.ungrounded_jsonl, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rec = json.loads(line)
                records[rec["artifact_id"]] = rec
    return records


def sync(
    primary: sqlite3.Connection,
    catalog: sqlite3.Connection,
    work: WorkPaths,
    progress=None,
    rebuild: bool = False,
) -> CatalogStats:
    progress = progress or NullProgress()
    stats = CatalogStats()
    started_at = _now()

    if rebuild:
        # Pare-down path: drop the wide table (and stale attr_* columns with
        # it) and auto tags, then re-derive. Manual tags are kept.
        catalog.execute("DROP TABLE IF EXISTS artifact_wide")
        catalog.execute("DELETE FROM artifact_tag WHERE origin = 'auto'")
        catalog.execute(
            "INSERT INTO schema_log (at, table_name, column_name, decl, reason) "
            "VALUES (?, 'artifact_wide', '*', '', 'rebuild: table dropped')",
            (_now(),),
        )
        catalog.execute("CREATE TABLE artifact_wide (artifact_id TEXT PRIMARY KEY)")
        ensure_columns(catalog, "artifact_wide", BASE_COLUMNS, reason="rebuild")
        catalog.executescript(INDEXES)
        catalog.commit()

    runs = {r["run_id"]: r for r in primary.execute("SELECT * FROM run")}
    sources = {r["source_id"]: r for r in primary.execute("SELECT * FROM source")}
    reps = {
        r["representation_id"]: r
        for r in primary.execute("SELECT * FROM representation")
    }
    rep_texts: dict[str, str | None] = {}

    def rep_text(rep_row) -> str | None:
        rep_id = rep_row["representation_id"]
        if rep_id not in rep_texts:
            try:
                rep_texts[rep_id] = (work.root / rep_row["relative_path"]).read_text(
                    encoding="utf-8",
                )
            except OSError:
                rep_texts[rep_id] = None
        return rep_texts[rep_id]

    # Ungrounded first, grounded second: if the same artifact_id ever shows
    # up in both (rejected under one run, grounded under a later one), the
    # grounded row wins the upsert.
    items: list[dict] = []
    for rec in _ungrounded_records(work).values():
        prov = rec["provenance"]
        items.append({
            "artifact_id": rec["artifact_id"],
            "grounded": 0,
            "extraction_class": rec["artifact"]["class"],
            "extraction_text": rec["artifact"]["text"],
            "attributes": rec["artifact"].get("attributes") or {},
            "char_start": prov["span"]["start"],
            "char_end": prov["span"]["end"],
            "line_number": None,
            "column_number": None,
            "alignment_status": prov.get("alignment_status"),
            "exact_text_match": 0,
            "rejection_reason": rec.get("rejection_reason"),
            "representation_id": prov["representation_id"],
            "source_id": prov["source_id"],
            "run_id": prov["run_id"],
            "with_context": False,  # span is unverified; don't quote around it
        })
    for row in primary.execute("SELECT * FROM artifact"):
        items.append({
            "artifact_id": row["artifact_id"],
            "grounded": 1,
            "extraction_class": row["extraction_class"],
            "extraction_text": row["extraction_text"],
            "attributes": json.loads(row["attributes_json"] or "{}"),
            "char_start": row["char_start"],
            "char_end": row["char_end"],
            "line_number": row["line_number"],
            "column_number": row["column_number"],
            "alignment_status": row["alignment_status"],
            "exact_text_match": row["exact_text_match"],
            "rejection_reason": None,
            "representation_id": row["representation_id"],
            "source_id": row["source_id"] if "source_id" in row.keys() else None,
            "run_id": row["run_id"],
            "with_context": True,
        })

    progress.set_total(len(items))
    for item in items:
        if not progress.checkpoint():
            stats.stopped = True
            break

        rep = reps.get(item["representation_id"])
        source = sources.get(
            item["source_id"] or (rep["source_id"] if rep else None)
        )
        run = runs.get(item["run_id"])
        label = f"{source['relative_path'] if source else '?'} · {item['extraction_class']}"
        progress.item_start(label)

        context_before = context_after = None
        if item["with_context"] and rep is not None:
            context_before, context_after = _context(
                rep_text(rep), item["char_start"], item["char_end"],
            )

        wide = {
            "artifact_id": item["artifact_id"],
            "grounded": item["grounded"],
            "extraction_class": item["extraction_class"],
            "extraction_text": item["extraction_text"],
            "text_length": len(item["extraction_text"]),
            "word_count": len(item["extraction_text"].split()),
            "attributes_json": json.dumps(item["attributes"], sort_keys=True)
                if item["attributes"] else None,
            "char_start": item["char_start"],
            "char_end": item["char_end"],
            "line_number": item["line_number"],
            "column_number": item["column_number"],
            "alignment_status": item["alignment_status"],
            "exact_text_match": item["exact_text_match"],
            "rejection_reason": item["rejection_reason"],
            "context_before": context_before,
            "context_after": context_after,
            "representation_id": item["representation_id"],
            "rep_kind": rep["kind"] if rep else None,
            "rep_path": rep["relative_path"] if rep else None,
            "rep_content_hash": rep["content_hash"] if rep else None,
            "source_id": source["source_id"] if source else None,
            "source_path": source["relative_path"] if source else None,
            "source_extension": source["extension"] if source else None,
            "source_mime": source["mime_type"] if source else None,
            "source_scope": source["scope"] if source else None,
            "source_size_bytes": source["size_bytes"] if source else None,
            "source_mtime_ns": source["mtime_ns"] if source else None,
            "source_status": source["status"] if source else None,
            "source_content_hash": source["content_hash"] if source else None,
            "run_id": item["run_id"],
            "run_started_at": run["started_at"] if run else None,
            "model_id": run["model_id"] if run else None,
            "langextract_version": run["langextract_version"] if run else None,
            "pipeline_version": run["pipeline_version"] if run else None,
            "run_config_json": run["config_json"] if run else None,
            "first_synced_at": _now(),
            "synced_at": _now(),
        }

        attr_cols: dict[str, str] = {}
        for key, value in item["attributes"].items():
            decl, stored = _attr_value(value)
            col = attr_column(key)
            attr_cols[col] = decl
            wide[col] = stored
        if attr_cols:
            stats.columns_added += ensure_columns(
                catalog, "artifact_wide", attr_cols,
                reason=f"attribute key(s) seen on {item['artifact_id']}",
            )

        upsert(catalog, "artifact_wide", "artifact_id", wide)

        for tag_name in _auto_tags(item):
            if _apply_tag(catalog, item["artifact_id"], tag_name, origin="auto"):
                stats.auto_tags += 1
        tags = _refresh_tags_column(catalog, item["artifact_id"])

        if item["grounded"]:
            stats.grounded_rows += 1
        else:
            stats.ungrounded_rows += 1
        stats.by_class[item["extraction_class"]] = (
            stats.by_class.get(item["extraction_class"], 0) + 1
        )
        catalog.commit()
        progress.item_done(
            label,
            ("grounded" if item["grounded"] else "ungrounded")
            + f" · tags: {', '.join(tags)}",
        )

    catalog.execute(
        "INSERT INTO sync_run (started_at, finished_at, pipeline_version, "
        "grounded_rows, ungrounded_rows, columns_added_json, rebuild) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            started_at, _now(), PIPELINE_VERSION, stats.grounded_rows,
            stats.ungrounded_rows, json.dumps(stats.columns_added), int(rebuild),
        ),
    )
    catalog.commit()
    return stats
