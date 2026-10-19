"""SQLite schema and connection helper. One file, `work/index.sqlite`,
holds all pipeline state (spec: "All state lives in one SQLite file")."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
  run_id TEXT PRIMARY KEY,          -- run_YYYYMMDD_HHMMSS
  stage TEXT NOT NULL,              -- snapshot|index|normalize|extract
  started_at TEXT, finished_at TEXT,
  pipeline_version TEXT,
  xberg_version TEXT, langextract_version TEXT,
  model_id TEXT,                    -- LLM used by LangExtract
  config_json TEXT
);

CREATE TABLE IF NOT EXISTS source (
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
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_path ON source(relative_path);

CREATE TABLE IF NOT EXISTS representation (
  representation_id TEXT PRIMARY KEY,   -- rep_ + blake3(source_id+kind+config_hash)[:16]
  source_id TEXT NOT NULL REFERENCES source(source_id),
  kind TEXT NOT NULL,                   -- text_utf8|markdown|layout_json
  relative_path TEXT NOT NULL,          -- under work/normalized/
  content_hash TEXT NOT NULL,
  extractor TEXT, extractor_version TEXT, config_hash TEXT,
  run_id TEXT
);

CREATE TABLE IF NOT EXISTS artifact (
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

CREATE TABLE IF NOT EXISTS extraction_error (
  source_id TEXT, stage TEXT, error_code TEXT,
  message TEXT, run_id TEXT
);
"""


def connect(sqlite_path: Path) -> sqlite3.Connection:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
