"""Stage 2 -- Normalize.

Every in-scope source gets exactly one canonical text representation that
later stages ground against: `text_utf8` for scope=text sources (2a),
`markdown` + `layout_json` for scope=document sources via Xberg (2b).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from pipeline_lib import ids, xberg_config
from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import NullProgress, human_bytes
from pipeline_lib.version import PIPELINE_VERSION

TEXTNORM_EXTRACTOR = "internal-textnorm"
# There's no real "config" for the internal text normalizer beyond the
# pipeline's own version -- normalize behavior only changes when the
# pipeline code changes.
TEXTNORM_CONFIG_HASH = PIPELINE_VERSION

OCR_RETRY_MIN_SOURCE_BYTES = 4096
OCR_RETRY_MAX_EMPTY_OUTPUT_BYTES = 32


@dataclass
class NormalizeStats:
    text_normalized: int = 0
    document_normalized: int = 0
    ocr_retries: int = 0
    quarantined: int = 0
    skipped_unchanged: int = 0
    errors: int = 0
    stopped: bool = False


def _log(work: WorkPaths, name: str, record: dict) -> None:
    work.logs.mkdir(parents=True, exist_ok=True)
    with open(work.logs / name, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def _record_error(
    conn: sqlite3.Connection, source_id: str, stage: str, error_code: str,
    message: str, run_id: str,
) -> None:
    conn.execute(
        "INSERT INTO extraction_error (source_id, stage, error_code, message, run_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (source_id, stage, error_code, message, run_id),
    )


def _existing_representation(
    conn: sqlite3.Connection, source_id: str, kind: str, extractor: str,
    extractor_version: str, config_hash: str,
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM representation WHERE source_id = ? AND kind = ? "
        "AND extractor = ? AND extractor_version = ? AND config_hash = ?",
        (source_id, kind, extractor, extractor_version, config_hash),
    ).fetchone()


def _write_representation_row(
    conn: sqlite3.Connection, representation_id: str, source_id: str, kind: str,
    relative_path: str, content_hash: str, extractor: str, extractor_version: str,
    config_hash: str, run_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO representation (
            representation_id, source_id, kind, relative_path, content_hash,
            extractor, extractor_version, config_hash, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            representation_id, source_id, kind, relative_path, content_hash,
            extractor, extractor_version, config_hash, run_id,
        ),
    )


def normalize_text_source(
    conn: sqlite3.Connection, source_row: sqlite3.Row, work: WorkPaths, run_id: str,
    stats: NormalizeStats,
) -> str:
    """Returns a one-line outcome description for progress logging."""
    from charset_normalizer import from_bytes

    source_id = source_row["source_id"]
    relative_path = source_row["relative_path"]

    if _existing_representation(
        conn, source_id, "text_utf8", TEXTNORM_EXTRACTOR, PIPELINE_VERSION,
        TEXTNORM_CONFIG_HASH,
    ):
        stats.skipped_unchanged += 1
        return "skip (unchanged)"

    raw = (work.snapshot / relative_path).read_bytes()
    match = from_bytes(raw).best()
    if match is None:
        _record_error(
            conn, source_id, "normalize", "decode_failure",
            "charset-normalizer could not determine a usable encoding", run_id,
        )
        conn.execute(
            "UPDATE source SET status = 'quarantined' WHERE source_id = ?",
            (source_id,),
        )
        stats.quarantined += 1
        stats.errors += 1
        return "quarantined (decode_failure)"

    _log(work, "normalize_encoding.jsonl", {
        "relative_path": relative_path,
        "detected_encoding": match.encoding,
        "percent_coherence": match.percent_coherence,
    })

    text = str(match)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("﻿"):
        text = text[1:]

    out_path = work.normalized / relative_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    content_hash = ids.content_hash_bytes(text.encode("utf-8"))
    representation_id = ids.representation_id(source_id, "text_utf8", TEXTNORM_CONFIG_HASH)
    _write_representation_row(
        conn, representation_id, source_id, "text_utf8",
        str(out_path.relative_to(work.root)), content_hash,
        TEXTNORM_EXTRACTOR, PIPELINE_VERSION, TEXTNORM_CONFIG_HASH, run_id,
    )
    conn.execute(
        "UPDATE source SET status = 'normalized' WHERE source_id = ?", (source_id,),
    )
    stats.text_normalized += 1
    return f"text_utf8 ok ({match.encoding}, {len(text)} chars)"


def normalize_document_source(
    conn: sqlite3.Connection, source_row: sqlite3.Row, work: WorkPaths, run_id: str,
    stats: NormalizeStats,
) -> str:
    """Returns a one-line outcome description for progress logging."""
    import xberg

    source_id = source_row["source_id"]
    relative_path = source_row["relative_path"]

    cfg = xberg_config.base_config()
    cfg_hash = xberg_config.config_hash_hex(cfg)
    xberg_version = xberg_config.xberg_runtime_version()

    if _existing_representation(
        conn, source_id, "markdown", "xberg", xberg_version, cfg_hash,
    ):
        stats.skipped_unchanged += 1
        return "skip (unchanged)"

    src_path = work.snapshot / relative_path
    source_size = src_path.stat().st_size

    try:
        result = xberg.extract_file_sync(str(src_path), None, cfg)
    except Exception as exc:  # xberg.KreuzbergError and friends
        _record_error(
            conn, source_id, "normalize", type(exc).__name__, str(exc), run_id,
        )
        conn.execute(
            "UPDATE source SET status = 'quarantined' WHERE source_id = ?",
            (source_id,),
        )
        stats.quarantined += 1
        stats.errors += 1
        return f"quarantined ({type(exc).__name__})"

    markdown = result.content or ""
    retried = False
    if (
        len(markdown.encode("utf-8")) < OCR_RETRY_MAX_EMPTY_OUTPUT_BYTES
        and source_size > OCR_RETRY_MIN_SOURCE_BYTES
    ):
        retried = True
        retry_cfg = xberg_config.base_config(force_ocr=True)
        try:
            result = xberg.extract_file_sync(str(src_path), None, retry_cfg)
            markdown = result.content or ""
        except Exception as exc:
            _log(work, "normalize_ocr_retries.jsonl", {
                "relative_path": relative_path,
                "outcome": "retry_raised",
                "error": str(exc),
            })
            _record_error(
                conn, source_id, "normalize", type(exc).__name__, str(exc), run_id,
            )
            conn.execute(
                "UPDATE source SET status = 'quarantined' WHERE source_id = ?",
                (source_id,),
            )
            stats.quarantined += 1
            stats.errors += 1
            stats.ocr_retries += 1
            return f"quarantined ({type(exc).__name__} during force_ocr retry)"
        stats.ocr_retries += 1
        _log(work, "normalize_ocr_retries.jsonl", {
            "relative_path": relative_path,
            "outcome": "retried",
            "result_bytes": len(markdown.encode("utf-8")),
        })

    if len(markdown.encode("utf-8")) < OCR_RETRY_MAX_EMPTY_OUTPUT_BYTES and source_size > OCR_RETRY_MIN_SOURCE_BYTES:
        _record_error(
            conn, source_id, "normalize", "empty_output_after_retry",
            f"Markdown output still under {OCR_RETRY_MAX_EMPTY_OUTPUT_BYTES} bytes "
            f"after force_ocr retry (source is {source_size} bytes)",
            run_id,
        )
        conn.execute(
            "UPDATE source SET status = 'quarantined' WHERE source_id = ?",
            (source_id,),
        )
        stats.quarantined += 1
        stats.errors += 1
        return "quarantined (empty_output_after_retry)"

    md_relative = relative_path + ".md"
    md_path = work.normalized / md_relative
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(markdown, encoding="utf-8")
    md_hash = ids.content_hash_bytes(markdown.encode("utf-8"))
    md_rep_id = ids.representation_id(source_id, "markdown", cfg_hash)
    _write_representation_row(
        conn, md_rep_id, source_id, "markdown",
        str(md_path.relative_to(work.root)), md_hash,
        "xberg", xberg_version, cfg_hash, run_id,
    )

    layout_relative = relative_path + ".layout.json"
    layout_path = work.normalized / layout_relative
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_payload = xberg_config.result_to_layout_json(result)
    layout_text = json.dumps(layout_payload, sort_keys=True, indent=2)
    layout_path.write_text(layout_text, encoding="utf-8")
    layout_hash = ids.content_hash_bytes(layout_text.encode("utf-8"))
    layout_rep_id = ids.representation_id(source_id, "layout_json", cfg_hash)
    _write_representation_row(
        conn, layout_rep_id, source_id, "layout_json",
        str(layout_path.relative_to(work.root)), layout_hash,
        "xberg", xberg_version, cfg_hash, run_id,
    )

    conn.execute(
        "UPDATE source SET status = 'normalized' WHERE source_id = ?", (source_id,),
    )
    stats.document_normalized += 1
    outcome = f"markdown ok ({human_bytes(len(markdown.encode('utf-8')))})"
    if retried:
        outcome += " after force_ocr retry"
    return outcome


def run_normalize(
    conn: sqlite3.Connection, work: WorkPaths, run_id: str, progress=None,
) -> NormalizeStats:
    progress = progress or NullProgress()
    stats = NormalizeStats()
    rows = conn.execute(
        "SELECT * FROM source WHERE scope IN ('text', 'document') "
        "AND status != 'quarantined' ORDER BY relative_path"
    ).fetchall()
    progress.set_total(len(rows))

    for row in rows:
        if not progress.checkpoint():
            stats.stopped = True
            break
        progress.item_start(row["relative_path"])
        if row["scope"] == "text":
            outcome = normalize_text_source(conn, row, work, run_id, stats)
        else:
            outcome = normalize_document_source(conn, row, work, run_id, stats)
        conn.commit()
        progress.item_done(row["relative_path"], outcome)

    return stats
