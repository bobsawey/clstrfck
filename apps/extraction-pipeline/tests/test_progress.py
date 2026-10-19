"""Tests for the progress/pause/resume layer (pipeline_lib/progress.py).

Two concerns, tested separately:

1. Checkpoint-stop then resume at the stage level: when a user hits `q`
   (or Ctrl+C) mid-stage, `progress.checkpoint()` returns False, the stage
   breaks out with completed items committed, and re-running the same
   command finishes only the remaining work. Simulated here by injecting a
   scripted progress object whose checkpoint() returns False after N items
   -- exactly the signal the keyboard path produces, minus the terminal.

2. The StageProgress display itself: plain, ANSI-free output when the
   stream is not a TTY (safe to pipe to a log), quiet mode, Ctrl+C
   semantics (first checkpoints, second aborts), and the small formatting
   helpers used by the CLI summaries.
"""

from __future__ import annotations

import io
import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline_lib import db, extract as extract_stage, ids, indexer, normalize, runs
from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import (
    NullProgress,
    StageProgress,
    bar_chart,
    fmt_hms,
    human_bytes,
    sparkline,
)
from pipeline_lib.snapshot import run_snapshot

from tests.conftest import EXCLUDES, TEST_DOCS
from tests.fake_extractor import fake_extractor

PIPELINE_PY = Path(__file__).resolve().parent.parent / "pipeline.py"


@pytest.fixture
def work(tmp_path) -> WorkPaths:
    return WorkPaths(tmp_path / "work")


class StopAfter(NullProgress):
    """Progress stub whose checkpoint() allows n items, then asks to stop --
    the same signal a `q` keypress or first Ctrl+C produces."""

    def __init__(self, n: int):
        self.n = n
        self.checkpoints = 0

    def checkpoint(self) -> bool:
        self.checkpoints += 1
        return self.checkpoints <= self.n


def _snapshot_and_index(work: WorkPaths):
    conn = db.connect(work.sqlite)
    run_snapshot(TEST_DOCS, work, EXCLUDES)
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "index")
    indexer.run_index(conn, work.snapshot, f"file://{TEST_DOCS}", run_id)
    runs.finish_run(conn, run_id)
    return conn


def _run_normalize(conn, work, progress=None):
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "normalize")
    stats = normalize.run_normalize(conn, work, run_id, progress=progress)
    runs.finish_run(conn, run_id)
    return run_id, stats


def _run_extract(conn, work, extractor, progress=None):
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(
        conn, run_id, "extract",
        langextract_version="test-fake", model_id="test-fake-model",
        config={"schema_hash": "test-schema-v1"},
    )
    stats = extract_stage.run_extract(
        conn, work, run_id, extractor,
        "test-fake", "test-fake-model",
        json.dumps({"schema_hash": "test-schema-v1"}, sort_keys=True),
        progress=progress,
    )
    runs.finish_run(conn, run_id)
    return run_id, stats


# ---------------------------------------------------------------------------
# Checkpoint-stop, then resume
# ---------------------------------------------------------------------------

def test_index_stop_commits_completed_items_and_resume_finishes(work):
    conn = db.connect(work.sqlite)
    run_snapshot(TEST_DOCS, work, EXCLUDES)
    total_files = sum(1 for p in work.snapshot.rglob("*") if p.is_file())

    run1 = ids.new_run_id(conn=conn)
    runs.start_run(conn, run1, "index")
    stats1 = indexer.run_index(
        conn, work.snapshot, f"file://{TEST_DOCS}", run1, progress=StopAfter(3),
    )
    runs.finish_run(conn, run1)

    assert stats1.stopped
    assert stats1.discovered == 3
    # Completed items must be durably committed: a fresh connection (as a
    # re-run would open) sees exactly the 3 finished rows.
    fresh = db.connect(work.sqlite)
    assert fresh.execute("SELECT COUNT(*) AS n FROM source").fetchone()["n"] == 3

    run2 = ids.new_run_id(conn=conn)
    runs.start_run(conn, run2, "index")
    stats2 = indexer.run_index(conn, work.snapshot, f"file://{TEST_DOCS}", run2)
    runs.finish_run(conn, run2)

    assert not stats2.stopped
    rows = conn.execute(
        "SELECT relative_path, first_run_id, last_run_id FROM source "
        "ORDER BY relative_path"
    ).fetchall()
    assert len(rows) == total_files
    # The 3 files indexed before the stop were seen as unchanged on resume:
    # first_run_id still points at the interrupted run.
    assert [r["first_run_id"] for r in rows[:3]] == [run1] * 3
    assert all(r["last_run_id"] == run2 for r in rows)


def test_normalize_stop_then_resume_completes_corpus_without_redoing_work(work):
    conn = _snapshot_and_index(work)

    _, stats1 = _run_normalize(conn, work, progress=StopAfter(2))
    assert stats1.stopped
    done_before_stop = stats1.text_normalized + stats1.document_normalized
    assert done_before_stop == 2

    _, stats2 = _run_normalize(conn, work)
    assert not stats2.stopped
    # Resume skips exactly the work the interrupted run committed...
    assert stats2.skipped_unchanged == done_before_stop
    # ...and the combined outcome matches a straight-through run over
    # test_docs/ (3 text, 2 document, 2 quarantined -- see test_pipeline).
    assert stats1.text_normalized + stats2.text_normalized == 3
    assert stats1.document_normalized + stats2.document_normalized == 2
    assert stats1.quarantined + stats2.quarantined == 2

    reps = conn.execute("SELECT COUNT(*) AS n FROM representation").fetchone()["n"]
    assert reps == 3 + 2 * 2  # text_utf8 ×3, (markdown + layout_json) ×2


def test_extract_stop_then_resume_never_resends_finished_items_to_model(work):
    conn = _snapshot_and_index(work)
    _run_normalize(conn, work)
    total_reps = conn.execute(
        "SELECT COUNT(*) AS n FROM representation "
        "WHERE kind IN ('text_utf8', 'markdown')"
    ).fetchone()["n"]

    calls = {"n": 0}

    def counting_extractor(text):
        calls["n"] += 1
        return fake_extractor(text)

    _, stats1 = _run_extract(conn, work, counting_extractor, progress=StopAfter(2))
    assert stats1.stopped
    assert stats1.representations_processed == 2
    assert calls["n"] == 2

    calls["n"] = 0
    _, stats2 = _run_extract(conn, work, counting_extractor)
    assert not stats2.stopped
    # The model is only called for work the interrupted run didn't finish.
    assert calls["n"] == total_reps - 2
    assert stats2.representations_skipped == 2
    assert stats2.representations_processed == total_reps - 2

    # Third run: everything is done, model is never called (idempotency
    # holds across the stop/resume boundary, not just for clean runs).
    calls["n"] = 0
    _, stats3 = _run_extract(conn, work, counting_extractor)
    assert calls["n"] == 0
    assert stats3.representations_skipped == total_reps


# ---------------------------------------------------------------------------
# StageProgress display behavior (non-TTY)
# ---------------------------------------------------------------------------

def test_non_tty_output_is_plain_log_lines(work):
    stream = io.StringIO()
    with StageProgress("extract", stream=stream) as prog:
        prog.set_total(2)
        assert prog.checkpoint()  # keyboard is off; never blocks or stops
        prog.item_start("a.txt")
        prog.item_done("a.txt", "grounded=3 ungrounded=0")
        prog.log("something noteworthy")
    out = stream.getvalue()

    assert "\x1b" not in out and "\r" not in out  # no ANSI, no redraws
    assert "2 item(s) to consider" in out
    assert "extract 1/2 a.txt — grounded=3 ungrounded=0" in out
    assert "something noteworthy" in out
    assert "keys:" not in out  # no key hints when the keyboard is inactive


def test_quiet_mode_suppresses_item_lines_but_keeps_log(work):
    stream = io.StringIO()
    with StageProgress("normalize", verbose=False, stream=stream) as prog:
        prog.set_total(1)
        prog.item_start("a.txt")
        prog.item_done("a.txt", "text_utf8 ok")
        prog.log("stage-level message")
    out = stream.getvalue()

    assert "a.txt" not in out
    assert "stage-level message" in out


def test_first_sigint_checkpoints_second_aborts(work):
    stream = io.StringIO()
    with StageProgress("extract", stream=stream) as prog:
        assert prog.checkpoint()
        prog._on_sigint(signal.SIGINT, None)
        assert not prog.checkpoint()  # stop requested, but no exception
        with pytest.raises(KeyboardInterrupt):
            prog._on_sigint(signal.SIGINT, None)
    assert "stopping after the current item" in stream.getvalue()


def test_null_progress_never_stops():
    prog = NullProgress()
    with prog:
        assert prog.checkpoint()
        prog.set_total(5)
        prog.item_start("x")
        prog.item_done("x")
        prog.log("ignored")


# ---------------------------------------------------------------------------
# Formatting helpers used by the CLI summaries
# ---------------------------------------------------------------------------

def test_formatting_helpers():
    assert fmt_hms(0) == "0:00"
    assert fmt_hms(75) == "1:15"
    assert fmt_hms(3661) == "1:01:01"

    assert human_bytes(512) == "512 B"
    assert human_bytes(2048) == "2.0 KiB"
    assert human_bytes(3 * 1024 * 1024) == "3.0 MiB"

    lines = bar_chart({"text": 3, "document": 1, "none": 0}, width=10)
    assert len(lines) == 3
    assert "██████████" in lines[0]  # largest count fills the full width
    assert "█" not in lines[2]  # zero draws no bar
    assert bar_chart({}) == []

    assert sparkline([]) == ""
    spark = sparkline([0.1, 5.0, 2.0])
    assert len(spark) == 3
    assert spark[1] == "█"  # peak maps to the tallest block


# ---------------------------------------------------------------------------
# CLI flags (subprocess)
# ---------------------------------------------------------------------------

def test_cli_quiet_and_no_progress_flags(tmp_path):
    work_dir = tmp_path / "work"

    def run(*args):
        return subprocess.run(
            [sys.executable, str(PIPELINE_PY), "--work-dir", str(work_dir), *args],
            capture_output=True, text=True, check=True,
        )

    run("snapshot", str(TEST_DOCS))
    run("-q", "--no-progress", "index", str(TEST_DOCS))
    result = run("-q", "--no-progress", "normalize")

    # Quiet: no per-item lines; the stage summary survives.
    assert "clean/notes.txt" not in result.stdout
    assert "── normalize summary" in result.stdout
    # Non-interactive stdout: nothing ANSI in what we'd pipe to a log.
    assert "\x1b" not in result.stdout
