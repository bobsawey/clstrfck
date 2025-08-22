import os
from pathlib import Path

from rag_soup.mine_dump import mine_dataset


def test_mining_end_to_end(tmp_path: Path):
    src = tmp_path / "input"
    src.mkdir()
    (src / "a.txt").write_text("hello world\n\nthis is clean.", encoding="utf-8")
    (src / "b.txt").write_text("explicit content nude nsfw", encoding="utf-8")  # should quarantine

    root = tmp_path / "data"
    root.mkdir()
    mine_dataset(src, root, "ds_test_001")

    # bronze exists
    assert (root / "bronze_raw").exists()

    # catalogs exist
    assert (root / "catalog" / "docs.parquet").exists()
    assert (root / "catalog" / "chunks.parquet").exists()

    # zones
    assert (root / "silver_normalized").exists()
    assert (root / "red_quarantine").exists()
