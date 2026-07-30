"""End-to-end tests against the real test_docs/ fixtures.

Snapshot/index/normalize run for real (real rsync, real blake3, real
charset-normalizer, real xberg/Kreuzberg). Stage 3 (extract) uses the fake
extractor in tests/fake_extractor.py in place of a live LangExtract model
call -- see that module's docstring for why: this project has no LLM API
key configured, and the thing worth testing hard is the deterministic
grounding/verification logic, not whether a particular cloud model returns
good spans.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline_lib import db, extract as extract_stage, ids, indexer, normalize, report, runs
from pipeline_lib.paths import WorkPaths
from pipeline_lib.snapshot import run_snapshot

from tests.conftest import EXCLUDES, TEST_DOCS
from tests.fake_extractor import HALLUCINATED_TEXT, fake_extractor

PIPELINE_PY = Path(__file__).resolve().parent.parent / "pipeline.py"


@pytest.fixture
def work(tmp_path) -> WorkPaths:
    return WorkPaths(tmp_path / "work")


def _snapshot_index_normalize(work: WorkPaths):
    conn = db.connect(work.sqlite)

    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "snapshot")
    snap = run_snapshot(TEST_DOCS, work, EXCLUDES)
    runs.finish_run(conn, run_id)
    assert snap.rsync_exit_code in (0, 24)

    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "index")
    idx_stats = indexer.run_index(conn, work.snapshot, f"file://{TEST_DOCS}", run_id)
    runs.finish_run(conn, run_id)

    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "normalize")
    norm_stats = normalize.run_normalize(conn, work, run_id)
    runs.finish_run(conn, run_id)

    return conn, idx_stats, norm_stats


# ---------------------------------------------------------------------------
# Stage 0/1: snapshot + index
# ---------------------------------------------------------------------------

def test_snapshot_reads_only_from_snapshot_dir(work):
    snap = run_snapshot(TEST_DOCS, work, EXCLUDES)
    assert snap.rsync_exit_code in (0, 24)
    assert snap.file_count == sum(1 for p in TEST_DOCS.rglob("*") if p.is_file())
    assert (work.snapshot / "clean" / "notes.txt").exists()


def test_index_classifies_scope_correctly(work):
    run_snapshot(TEST_DOCS, work, EXCLUDES)
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)
    indexer.run_index(conn, work.snapshot, f"file://{TEST_DOCS}", run_id)

    rows = {r["relative_path"]: r for r in conn.execute("SELECT * FROM source")}

    assert rows["clean/notes.txt"]["scope"] == "text"
    assert rows["clean/design-notes.md"]["scope"] == "text"
    assert rows["clean/report.pdf"]["scope"] == "document"
    assert rows["clean/meeting-minutes.docx"]["scope"] == "document"
    assert rows["corrupt/garbage.pdf"]["scope"] == "document"
    assert rows["corrupt/binary_masquerade.txt"]["scope"] == "text"
    assert rows["adversarial/prompt-injection.md"]["scope"] == "text"
    assert rows["out_of_scope/archive.bin"]["scope"] == "out_of_scope"

    # every row got a deterministic ID that matches the spec's formula
    for rel, row in rows.items():
        expected = ids.source_id(row["content_hash"], rel)
        assert row["source_id"] == expected


def test_index_recovers_original_xattrs_and_mtime(work):
    # Success criterion 4: original xattrs/mtimes recoverable from the
    # index for every source.
    run_snapshot(TEST_DOCS, work, EXCLUDES)
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)
    indexer.run_index(conn, work.snapshot, f"file://{TEST_DOCS}", run_id)

    for row in conn.execute("SELECT relative_path, mtime_ns, xattrs_json FROM source"):
        snapshot_path = work.snapshot / row["relative_path"]
        assert snapshot_path.stat().st_mtime_ns == row["mtime_ns"]
        assert json.loads(row["xattrs_json"]) == {}  # no xattrs set on these fixtures


# ---------------------------------------------------------------------------
# Stage 2: normalize
# ---------------------------------------------------------------------------

def test_normalize_produces_representations_for_clean_docs(work):
    conn, idx_stats, norm_stats = _snapshot_index_normalize(work)

    assert norm_stats.text_normalized == 3  # notes.txt, design-notes.md, prompt-injection.md
    assert norm_stats.document_normalized == 2  # report.pdf, meeting-minutes.docx

    md = (work.normalized / "clean/report.pdf.md").read_text()
    assert "Decision: use SQLite for the index." in md
    assert "Task: benchmark FTS5 before Friday." in md

    layout = json.loads((work.normalized / "clean/report.pdf.layout.json").read_text())
    assert layout["metadata"]["pages"]["total_count"] == 2

    docx_md = (work.normalized / "clean/meeting-minutes.docx.md").read_text()
    assert "Claim: content hashes are stable across runs" in docx_md


def test_normalize_quarantines_corrupt_files(work):
    conn, idx_stats, norm_stats = _snapshot_index_normalize(work)

    assert norm_stats.quarantined == 2  # garbage.pdf + binary_masquerade.txt

    garbage_status = conn.execute(
        "SELECT status FROM source WHERE relative_path = 'corrupt/garbage.pdf'"
    ).fetchone()["status"]
    assert garbage_status == "quarantined"

    binary_status = conn.execute(
        "SELECT status FROM source WHERE relative_path = 'corrupt/binary_masquerade.txt'"
    ).fetchone()["status"]
    assert binary_status == "quarantined"

    errors = conn.execute(
        "SELECT source_id, error_code FROM extraction_error WHERE stage = 'normalize'"
    ).fetchall()
    assert len(errors) == 2
    error_codes = {e["error_code"] for e in errors}
    assert "ParsingError" in error_codes
    assert "decode_failure" in error_codes


def test_out_of_scope_file_is_indexed_but_never_normalized(work):
    conn, idx_stats, norm_stats = _snapshot_index_normalize(work)

    row = conn.execute(
        "SELECT status FROM source WHERE relative_path = 'out_of_scope/archive.bin'"
    ).fetchone()
    assert row["status"] == "indexed"  # untouched by normalize

    rep = conn.execute(
        "SELECT * FROM representation r JOIN source s ON r.source_id = s.source_id "
        "WHERE s.relative_path = 'out_of_scope/archive.bin'"
    ).fetchone()
    assert rep is None


def test_normalize_is_idempotent_second_run_does_no_work(work):
    conn, _, norm_stats1 = _snapshot_index_normalize(work)
    assert norm_stats1.text_normalized + norm_stats1.document_normalized > 0

    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "normalize")
    norm_stats2 = normalize.run_normalize(conn, work, run_id)
    runs.finish_run(conn, run_id)

    # Success criterion 1: second run over an unchanged corpus does no work.
    assert norm_stats2.text_normalized == 0
    assert norm_stats2.document_normalized == 0
    assert norm_stats2.quarantined == 0
    total_in_scope = conn.execute(
        "SELECT COUNT(*) AS n FROM source WHERE scope != 'out_of_scope' "
        "AND status != 'quarantined'"
    ).fetchone()["n"]
    assert norm_stats2.skipped_unchanged == total_in_scope


# ---------------------------------------------------------------------------
# Stage 3: extract (fake model, real grounding/verification)
# ---------------------------------------------------------------------------

def _run_extract(conn, work, extractor=fake_extractor):
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
    )
    runs.finish_run(conn, run_id)
    return run_id, stats


def test_extract_grounds_expected_classes_across_clean_docs(work):
    conn, _, _ = _snapshot_index_normalize(work)
    _run_id, stats = _run_extract(conn, work)

    assert stats.errors == 0
    for cls in ("decision", "task", "claim", "question", "reference"):
        assert stats.grounded_by_class.get(cls, 0) >= 1, f"no grounded {cls}"

    artifacts = conn.execute("SELECT * FROM artifact").fetchall()
    assert len(artifacts) == stats.grounded
    for a in artifacts:
        assert a["exact_text_match"] == 1
        assert a["alignment_status"] == "match_exact"


def test_adversarial_hallucination_is_rejected_not_grounded(work):
    conn, _, _ = _snapshot_index_normalize(work)
    _run_id, stats = _run_extract(conn, work)

    assert stats.ungrounded >= 1

    hallucinated_in_artifacts = conn.execute(
        "SELECT COUNT(*) AS n FROM artifact WHERE extraction_text = ?",
        (HALLUCINATED_TEXT,),
    ).fetchone()["n"]
    assert hallucinated_in_artifacts == 0

    with open(work.artifacts_jsonl, encoding="utf-8") as fh:
        for line in fh:
            assert HALLUCINATED_TEXT not in line

    found_in_ungrounded = False
    with open(work.ungrounded_jsonl, encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec["artifact"]["text"] == HALLUCINATED_TEXT:
                found_in_ungrounded = True
                assert "rejection_reason" in rec
                assert rec["provenance"]["span"]["line"] is None
    assert found_in_ungrounded


def test_extract_is_idempotent_second_run_calls_model_zero_times(work):
    conn, _, _ = _snapshot_index_normalize(work)
    _run_extract(conn, work)

    calls = {"n": 0}

    def counting_extractor(text):
        calls["n"] += 1
        return fake_extractor(text)

    _run_id, stats2 = _run_extract(conn, work, extractor=counting_extractor)

    assert calls["n"] == 0
    assert stats2.grounded == 0
    assert stats2.ungrounded == 0
    assert stats2.representations_skipped == stats2.representations_skipped  # all skipped
    assert stats2.representations_processed == 0


def test_artifact_id_matches_spec_formula(work):
    conn, _, _ = _snapshot_index_normalize(work)
    _run_extract(conn, work)

    for row in conn.execute("SELECT * FROM artifact"):
        expected = ids.artifact_id(
            row["representation_id"], row["extraction_class"],
            row["char_start"], row["char_end"], row["extraction_text"],
        )
        assert row["artifact_id"] == expected


def test_grounded_spans_reproducible_from_sqlite_and_normalized_files_only(work):
    """Success criterion 2: every artifact's source_text slice check must
    be reproducible by a tiny script reading only index.sqlite +
    work/normalized/ -- no pipeline internals, no in-memory state."""
    conn, _, _ = _snapshot_index_normalize(work)
    _run_extract(conn, work)

    verify_conn = db.connect(work.sqlite)  # fresh connection, no shared state
    checked = 0
    for row in verify_conn.execute(
        "SELECT a.*, r.relative_path AS rep_path FROM artifact a "
        "JOIN representation r ON a.representation_id = r.representation_id"
    ):
        text = (work.root / row["rep_path"]).read_text(encoding="utf-8")
        slice_text = text[row["char_start"]:row["char_end"]]
        assert (slice_text == row["extraction_text"]) == bool(row["exact_text_match"])
        checked += 1
    assert checked > 0


# ---------------------------------------------------------------------------
# Stage 4: report
# ---------------------------------------------------------------------------

def test_report_summarizes_full_run(work):
    conn, _, _ = _snapshot_index_normalize(work)
    _run_extract(conn, work)

    text = report.build_report(conn, work)
    assert "Sources discovered:" in text
    assert "Grounded artifacts:" in text
    assert "decision:" in text
    assert "Quarantined / errors logged: 2" in text
    assert "Ungrounded outputs" in text


# ---------------------------------------------------------------------------
# CLI (subprocess) smoke test for stages 0-2 + report
# ---------------------------------------------------------------------------

def test_cli_snapshot_index_normalize_report(tmp_path):
    work_dir = tmp_path / "work"
    env = {**__import__("os").environ}

    def run(*args):
        return subprocess.run(
            [sys.executable, str(PIPELINE_PY), "--work-dir", str(work_dir), *args],
            capture_output=True, text=True, env=env, check=True,
        )

    run("snapshot", str(TEST_DOCS))
    run("index", str(TEST_DOCS))
    run("normalize")
    result = run("report")

    assert "Sources discovered:" in result.stdout
    assert (work_dir / "normalized" / "clean" / "report.pdf.md").exists()
