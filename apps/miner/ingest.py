"""Discover files, hash them, and record source metadata."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import utils


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, required=True, help="Path to YAML config"
    )
    args = parser.parse_args()

    cfg = utils.load_config(args.config)
    paths = cfg["paths"]
    processed = Path(paths["processed_dir"])
    objects = Path(paths["object_store"])
    utils.ensure_dir(processed)
    utils.ensure_dir(objects)

    # Placeholder: walk input directories and hash files.
    for base in paths.get("input_dirs", []):
        for file in Path(base).rglob("*"):
            if file.is_file():
                data = file.read_bytes()
                hashlib.sha256(data).hexdigest()

    utils.touch_parquet(processed / "sources.parquet")
    utils.touch_parquet(processed / "blobs.parquet")
    utils.log_run(Path(paths["logs_dir"]), "ingest", {"config": str(args.config)})


if __name__ == "__main__":
    main()
