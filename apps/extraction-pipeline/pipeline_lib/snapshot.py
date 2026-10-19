"""Stage 0 -- Snapshot.

Create one immutable archive copy of the source tree before any other
operation touches it. After this stage the pipeline reads ONLY from
work/snapshot/; the original source root is never opened again.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from pipeline_lib.paths import WorkPaths


@dataclass
class SnapshotResult:
    timestamp: str
    rsync_exit_code: int
    source_root: str
    file_count: int
    total_bytes: int


def run_snapshot(source_root: Path, work: WorkPaths, excludes_file: Path) -> SnapshotResult:
    work.ensure()
    source_root = source_root.resolve()

    cmd = [
        "rsync",
        "-aAX",
        f"--exclude-from={excludes_file}",
        f"{source_root}/",
        f"{work.snapshot}/",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)

    file_count = 0
    total_bytes = 0
    for p in work.snapshot.rglob("*"):
        if p.is_file() and not p.is_symlink():
            file_count += 1
            total_bytes += p.stat().st_size

    return SnapshotResult(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        rsync_exit_code=proc.returncode,
        source_root=str(source_root),
        file_count=file_count,
        total_bytes=total_bytes,
    )
