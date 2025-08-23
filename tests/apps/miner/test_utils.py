from pathlib import Path

import apps.miner.utils as utils


def test_load_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text("foo: 1\n")
    cfg = utils.load_config(cfg_path)
    assert cfg["foo"] == 1
