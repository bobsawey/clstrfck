"""Unit test for the Stage 2b OCR retry rule, in isolation from any real
OCR backend.

This sandbox has no tessdata available (would need a network download), so
we can't reliably exercise xberg's real OCR path end-to-end here. Instead
we monkeypatch `xberg.extract_file_sync` to simulate exactly the scenario
the spec's retry rule targets: a document whose first pass comes back
empty, which recovers on a `force_ocr=True` retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import kreuzberg as xberg

from pipeline_lib import db, ids, normalize
from pipeline_lib.paths import WorkPaths


@dataclass
class FakeResult:
    content: str
    mime_type: str = "application/pdf"
    metadata: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)
    document: dict | None = None
    detected_languages: list | None = None


def _insert_fake_source(conn, relative_path: str, size_bytes: int) -> str:
    content_hash = "deadbeef" * 8
    source_id = ids.source_id(content_hash, relative_path)
    conn.execute(
        """
        INSERT INTO source (
            source_id, root_uri, relative_path, extension, mime_type,
            mime_detector, scope, scope_reason, size_bytes, mtime_ns, mode,
            xattrs_json, content_hash, status, first_run_id, last_run_id
        ) VALUES (?, 'file:///fake', ?, '.pdf', 'application/pdf', 'xberg',
                  'document', 'mime:application/pdf', ?, 0, 33188, '{}', ?,
                  'indexed', 'run_fake', 'run_fake')
        """,
        (source_id, relative_path, size_bytes, content_hash),
    )
    conn.commit()
    return source_id


def test_empty_first_pass_retries_with_force_ocr_and_recovers(tmp_path, monkeypatch):
    work = WorkPaths(tmp_path / "work")
    work.ensure()

    relative_path = "big.pdf"
    (work.snapshot / relative_path).write_bytes(b"%PDF-1.4 fake but large enough\n" * 200)
    source_size = (work.snapshot / relative_path).stat().st_size
    assert source_size > normalize.OCR_RETRY_MIN_SOURCE_BYTES

    conn = db.connect(work.sqlite)
    source_id = _insert_fake_source(conn, relative_path, source_size)
    source_row = conn.execute(
        "SELECT * FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()

    calls = []

    def fake_extract_file_sync(path, mime_type, config):
        calls.append(config.force_ocr)
        if not config.force_ocr:
            return FakeResult(content="")  # empty first pass -> triggers retry
        return FakeResult(
            content="Decision: recovered via retry after force_ocr kicked in.\n",
            document={"nodes": [], "source_format": "pdf"},
            metadata={"pages": {"total_count": 1}},
        )

    monkeypatch.setattr(xberg, "extract_file_sync", fake_extract_file_sync)

    stats = normalize.NormalizeStats()
    normalize.normalize_document_source(conn, source_row, work, "run_test", stats)

    assert calls == [False, True]  # exactly one retry, with force_ocr=True
    assert stats.ocr_retries == 1
    assert stats.document_normalized == 1
    assert stats.quarantined == 0

    md_path = work.normalized / f"{relative_path}.md"
    assert md_path.read_text() == "Decision: recovered via retry after force_ocr kicked in.\n"

    retry_log = work.logs / "normalize_ocr_retries.jsonl"
    assert retry_log.exists()
    assert "retried" in retry_log.read_text()

    row = conn.execute(
        "SELECT status FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()
    assert row["status"] == "normalized"


def test_still_empty_after_retry_is_quarantined(tmp_path, monkeypatch):
    work = WorkPaths(tmp_path / "work")
    work.ensure()

    relative_path = "unreadable.pdf"
    (work.snapshot / relative_path).write_bytes(b"%PDF-1.4 fake but large enough\n" * 200)
    source_size = (work.snapshot / relative_path).stat().st_size

    conn = db.connect(work.sqlite)
    source_id = _insert_fake_source(conn, relative_path, source_size)
    source_row = conn.execute(
        "SELECT * FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()

    def always_empty(path, mime_type, config):
        return FakeResult(content="")

    monkeypatch.setattr(xberg, "extract_file_sync", always_empty)

    stats = normalize.NormalizeStats()
    normalize.normalize_document_source(conn, source_row, work, "run_test", stats)

    assert stats.ocr_retries == 1
    assert stats.quarantined == 1
    assert stats.document_normalized == 0

    row = conn.execute(
        "SELECT status FROM source WHERE source_id = ?", (source_id,)
    ).fetchone()
    assert row["status"] == "quarantined"

    error = conn.execute(
        "SELECT error_code FROM extraction_error WHERE source_id = ?", (source_id,)
    ).fetchone()
    assert error["error_code"] == "empty_output_after_retry"
