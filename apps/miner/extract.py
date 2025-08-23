"""Parse source blobs into text extractions."""

from __future__ import annotations

import argparse
from pathlib import Path

import utils


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, required=True, help="Path to YAML config"
    )
    args = parser.parse_args()

    cfg = utils.load_config(args.config)
    processed = Path(cfg["paths"]["processed_dir"])
    utils.ensure_dir(processed)

    # Placeholder: read blobs and create text extractions.
    utils.touch_parquet(processed / "extractions.parquet")
    utils.log_run(
        Path(cfg["paths"]["logs_dir"]), "extract", {"config": str(args.config)}
    )


if __name__ == "__main__":
    main()
