"""Utility helpers for the mining pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    """Load a YAML configuration file."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dir(path: Path) -> None:
    """Create *path* and its parents if they do not exist."""
    path.mkdir(parents=True, exist_ok=True)


def touch_parquet(path: Path) -> None:
    """Create an empty placeholder file to mimic Parquet output."""
    ensure_dir(path.parent)
    if not path.exists():
        path.touch()


def log_run(logs_dir: Path, kind: str, params: dict) -> None:
    """Append a simple run record to ``runs.jsonl`` in *logs_dir*."""
    ensure_dir(logs_dir)
    entry = {
        "run_id": datetime.utcnow().isoformat(),
        "kind": kind,
        "params": params,
        "status": "ok",
    }
    with (logs_dir / "runs.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
