"""Helpers for the `run` table: one row per stage invocation."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3

from pipeline_lib.version import PIPELINE_VERSION


def start_run(
    conn: sqlite3.Connection, run_id: str, stage: str, *, xberg_version: str | None = None,
    langextract_version: str | None = None, model_id: str | None = None,
    config: dict | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO run (
            run_id, stage, started_at, finished_at, pipeline_version,
            xberg_version, langextract_version, model_id, config_json
        ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            run_id, stage, dt.datetime.now().isoformat(), PIPELINE_VERSION,
            xberg_version, langextract_version, model_id,
            json.dumps(config or {}, sort_keys=True),
        ),
    )
    conn.commit()


def finish_run(conn: sqlite3.Connection, run_id: str) -> None:
    conn.execute(
        "UPDATE run SET finished_at = ? WHERE run_id = ?",
        (dt.datetime.now().isoformat(), run_id),
    )
    conn.commit()
