"""Stage 3 -- Extract.

Deterministic side of LangExtract-based extraction: reads each canonical
text representation, calls the (possibly fake, for tests) extractor, then
verifies every returned span against the source text ourselves. Nothing
here trusts the model for identifiers, offsets, or file references -- see
the spec's Core Principle.
"""

from __future__ import annotations

import difflib
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from pipeline_lib import ids
from pipeline_lib.extractor_backend import Extractor, RawExtraction
from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import NullProgress

FUZZY_ALIGNMENT_THRESHOLD = 0.75
NO_GROUNDED_OUTPUT_MARKER = "no_grounded_extractions"


@dataclass
class ExtractStats:
    representations_processed: int = 0
    representations_skipped: int = 0
    grounded: int = 0
    ungrounded: int = 0
    errors: int = 0
    stopped: bool = False
    grounded_by_class: dict = None
    per_item_seconds: list = None

    def __post_init__(self):
        if self.grounded_by_class is None:
            self.grounded_by_class = {}
        if self.per_item_seconds is None:
            self.per_item_seconds = []


def _line_col(text: str, offset: int) -> tuple[int, int]:
    prefix = text[:offset]
    line_number = prefix.count("\n") + 1
    last_newline = prefix.rfind("\n")
    column_number = offset - last_newline if last_newline != -1 else offset + 1
    return line_number, column_number


def _verify(
    text: str, raw: RawExtraction,
) -> tuple[bool, str | None, bool, str | None]:
    """Returns (grounded, rejection_reason, exact_text_match, alignment_status)."""
    if raw.char_start is None or raw.char_end is None:
        return False, "no_interval", False, raw.alignment_status

    if (
        raw.char_start < 0
        or raw.char_end > len(text)
        or raw.char_start > raw.char_end
    ):
        return False, "interval_out_of_range", False, raw.alignment_status

    slice_text = text[raw.char_start:raw.char_end]
    exact_match = slice_text == raw.extraction_text
    if exact_match:
        return True, None, True, raw.alignment_status or "match_exact"

    ratio = difflib.SequenceMatcher(None, slice_text, raw.extraction_text).ratio()
    if ratio >= FUZZY_ALIGNMENT_THRESHOLD:
        return True, None, False, raw.alignment_status or "match_fuzzy"

    return (
        False,
        f"slice_mismatch_beyond_fuzzy_tolerance(ratio={ratio:.3f})",
        False,
        raw.alignment_status,
    )


def _already_extracted(
    conn: sqlite3.Connection, representation_id: str, source_id: str,
    langextract_version: str, model_id: str, config_json: str,
) -> bool:
    # Skip when this representation already has grounded artifacts under
    # the same (langextract_version, model_id, schema config_hash) -- per
    # spec's Incremental Rules. A representation that was already attempted
    # under this exact config but produced zero groundable extractions is
    # ALSO skipped (via the no_grounded_extractions marker row), otherwise
    # it would be re-sent to the model on every run even though nothing
    # about it changed -- which would violate "second run does no work".
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM artifact a
        JOIN run r ON a.run_id = r.run_id
        WHERE a.representation_id = ?
          AND r.langextract_version = ?
          AND r.model_id = ?
          AND r.config_json = ?
        """,
        (representation_id, langextract_version, model_id, config_json),
    ).fetchone()
    if row["n"] > 0:
        return True

    marker = conn.execute(
        """
        SELECT COUNT(*) AS n FROM extraction_error e
        JOIN run r ON e.run_id = r.run_id
        WHERE e.source_id = ? AND e.stage = 'extract'
          AND e.error_code = ?
          AND r.langextract_version = ?
          AND r.model_id = ?
          AND r.config_json = ?
        """,
        (source_id, NO_GROUNDED_OUTPUT_MARKER, langextract_version, model_id, config_json),
    ).fetchone()
    return marker["n"] > 0


def run_extract(
    conn: sqlite3.Connection,
    work: WorkPaths,
    run_id: str,
    extractor: Extractor,
    langextract_version: str,
    model_id: str,
    config_json: str,
    progress=None,
) -> ExtractStats:
    progress = progress or NullProgress()
    stats = ExtractStats()

    reps = conn.execute(
        "SELECT * FROM representation WHERE kind IN ('text_utf8', 'markdown') "
        "ORDER BY representation_id"
    ).fetchall()
    progress.set_total(len(reps))

    artifacts_fh = open(work.artifacts_jsonl, "a", encoding="utf-8")
    ungrounded_fh = open(work.ungrounded_jsonl, "a", encoding="utf-8")
    try:
        for rep in reps:
            if not progress.checkpoint():
                stats.stopped = True
                break

            rep_id = rep["representation_id"]
            label = rep["relative_path"]
            if _already_extracted(
                conn, rep_id, rep["source_id"], langextract_version, model_id, config_json,
            ):
                stats.representations_skipped += 1
                progress.item_done(
                    label, "skip (already extracted under this model/config)",
                )
                continue

            progress.item_start(label)
            item_t0 = time.monotonic()
            text_path = work.root / rep["relative_path"]
            text = text_path.read_text(encoding="utf-8")

            source_row = conn.execute(
                "SELECT * FROM source WHERE source_id = ?", (rep["source_id"],)
            ).fetchone()

            try:
                raw_extractions = extractor(text)
            except Exception as exc:
                conn.execute(
                    "INSERT INTO extraction_error (source_id, stage, error_code, message, run_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (rep["source_id"], "extract", type(exc).__name__, str(exc), run_id),
                )
                stats.errors += 1
                conn.commit()
                progress.item_done(label, f"error ({type(exc).__name__}: {exc})")
                continue

            grounded_this_rep = 0
            ungrounded_this_rep = 0
            for raw in raw_extractions:
                grounded, reason, exact_match, alignment_status = _verify(text, raw)
                artifact_id = ids.artifact_id(
                    rep_id, raw.extraction_class, raw.char_start, raw.char_end,
                    raw.extraction_text,
                )

                if grounded:
                    line_number, column_number = _line_col(text, raw.char_start)
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO artifact (
                            artifact_id, representation_id, extraction_class,
                            extraction_text, attributes_json, char_start, char_end,
                            line_number, column_number, alignment_status,
                            exact_text_match, run_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            artifact_id, rep_id, raw.extraction_class,
                            raw.extraction_text,
                            json.dumps(raw.attributes) if raw.attributes else None,
                            raw.char_start, raw.char_end, line_number, column_number,
                            alignment_status, int(exact_match), run_id,
                        ),
                    )
                    record = {
                        "artifact_id": artifact_id,
                        "artifact": {
                            "class": raw.extraction_class,
                            "text": raw.extraction_text,
                            "attributes": raw.attributes or {},
                        },
                        "provenance": {
                            "source_id": rep["source_id"],
                            "relative_path": source_row["relative_path"],
                            "content_hash": source_row["content_hash"],
                            "representation_id": rep_id,
                            "run_id": run_id,
                            "span": {
                                "start": raw.char_start, "end": raw.char_end,
                                "line": line_number, "column": column_number,
                            },
                            "alignment_status": alignment_status,
                            "exact_text_match": exact_match,
                        },
                    }
                    artifacts_fh.write(json.dumps(record) + "\n")
                    stats.grounded += 1
                    grounded_this_rep += 1
                    stats.grounded_by_class[raw.extraction_class] = (
                        stats.grounded_by_class.get(raw.extraction_class, 0) + 1
                    )
                else:
                    record = {
                        "artifact_id": artifact_id,
                        "artifact": {
                            "class": raw.extraction_class,
                            "text": raw.extraction_text,
                            "attributes": raw.attributes or {},
                        },
                        "provenance": {
                            "source_id": rep["source_id"],
                            "relative_path": source_row["relative_path"],
                            "content_hash": source_row["content_hash"],
                            "representation_id": rep_id,
                            "run_id": run_id,
                            "span": {
                                "start": raw.char_start, "end": raw.char_end,
                                "line": None, "column": None,
                            },
                            "alignment_status": alignment_status,
                            "exact_text_match": exact_match,
                        },
                        "rejection_reason": reason,
                    }
                    ungrounded_fh.write(json.dumps(record) + "\n")
                    stats.ungrounded += 1
                    ungrounded_this_rep += 1

            if grounded_this_rep == 0:
                conn.execute(
                    "INSERT INTO extraction_error (source_id, stage, error_code, message, run_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        rep["source_id"], "extract", NO_GROUNDED_OUTPUT_MARKER,
                        f"{len(raw_extractions)} extraction(s) returned, none grounded",
                        run_id,
                    ),
                )

            conn.execute(
                "UPDATE source SET status = 'extracted' WHERE source_id = ?",
                (rep["source_id"],),
            )
            stats.representations_processed += 1
            conn.commit()

            item_secs = time.monotonic() - item_t0
            stats.per_item_seconds.append(item_secs)
            progress.item_done(
                label,
                f"grounded={grounded_this_rep} ungrounded={ungrounded_this_rep} "
                f"({item_secs:.1f}s)",
            )
    finally:
        artifacts_fh.close()
        ungrounded_fh.close()

    return stats
