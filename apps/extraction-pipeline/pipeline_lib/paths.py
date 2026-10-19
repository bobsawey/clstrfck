"""Layout of the `work/` directory, per spec's Directory Layout section."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkPaths:
    root: Path

    @property
    def snapshot(self) -> Path:
        return self.root / "snapshot"

    @property
    def normalized(self) -> Path:
        return self.root / "normalized"

    @property
    def sqlite(self) -> Path:
        return self.root / "index.sqlite"

    @property
    def catalog_sqlite(self) -> Path:
        return self.root / "catalog.sqlite"

    @property
    def artifacts_jsonl(self) -> Path:
        return self.root / "artifacts.jsonl"

    @property
    def ungrounded_jsonl(self) -> Path:
        return self.root / "ungrounded.jsonl"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for p in (self.root, self.snapshot, self.normalized, self.logs):
            p.mkdir(parents=True, exist_ok=True)
