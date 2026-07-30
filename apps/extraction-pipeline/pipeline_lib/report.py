"""Stage 4 (`pipeline.py report`) -- prints per-run and cumulative counts."""

from __future__ import annotations

import sqlite3

from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import bar_chart


def build_report(conn: sqlite3.Connection, work: WorkPaths) -> str:
    lines: list[str] = []

    def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return conn.execute(sql, params).fetchall()

    total_sources = q("SELECT COUNT(*) AS n FROM source")[0]["n"]
    by_scope = {r["scope"]: r["n"] for r in q(
        "SELECT scope, COUNT(*) AS n FROM source GROUP BY scope"
    )}
    lines.append(f"Sources discovered: {total_sources}")
    lines.append(
        f"  in scope: text={by_scope.get('text', 0)} "
        f"document={by_scope.get('document', 0)}  "
        f"out of scope: {by_scope.get('out_of_scope', 0)}"
    )

    by_status = {r["status"]: r["n"] for r in q(
        "SELECT status, COUNT(*) AS n FROM source GROUP BY status"
    )}
    lines.append("Status breakdown:")
    lines.extend(bar_chart(by_status))

    rep_counts = {r["kind"]: r["n"] for r in q(
        "SELECT kind, COUNT(*) AS n FROM representation GROUP BY kind"
    )}
    lines.append(f"Representations: {dict(rep_counts)}")

    ocr_retries = 0
    retry_log = work.logs / "normalize_ocr_retries.jsonl"
    if retry_log.exists():
        with open(retry_log, encoding="utf-8") as fh:
            ocr_retries = sum(1 for _ in fh)
    lines.append(f"OCR retries: {ocr_retries}")

    # no_grounded_extractions is a bookkeeping marker (lets extract skip a
    # representation that was tried and found nothing groundable), not a
    # failure -- keep it out of the quarantine/error listing.
    quarantined = q(
        "SELECT source_id, stage, error_code, message FROM extraction_error "
        "WHERE error_code != 'no_grounded_extractions'"
    )
    lines.append(f"Quarantined / errors logged: {len(quarantined)}")
    for row in quarantined:
        lines.append(
            f"  [{row['stage']}] {row['source_id']} {row['error_code']}: {row['message']}"
        )

    grounded = q(
        "SELECT extraction_class, COUNT(*) AS n FROM artifact GROUP BY extraction_class"
    )
    total_grounded = sum(r["n"] for r in grounded)
    lines.append(f"Grounded artifacts: {total_grounded}")
    lines.extend(bar_chart({
        f"{row['extraction_class']}:": row["n"] for row in grounded
    }))

    exact_stats = q(
        "SELECT "
        "  SUM(exact_text_match) AS exact_n, COUNT(*) AS total_n "
        "FROM artifact"
    )[0]
    total_n = exact_stats["total_n"] or 0
    exact_n = exact_stats["exact_n"] or 0
    pct = (100.0 * exact_n / total_n) if total_n else 0.0
    lines.append(f"Exact span verification: {exact_n}/{total_n} ({pct:.1f}%)")

    ungrounded_count = 0
    if work.ungrounded_jsonl.exists():
        with open(work.ungrounded_jsonl, encoding="utf-8") as fh:
            ungrounded_count = sum(1 for _ in fh)
    lines.append(f"Ungrounded outputs (see ungrounded.jsonl): {ungrounded_count}")

    runs = q(
        "SELECT run_id, stage, started_at, finished_at, model_id "
        "FROM run ORDER BY started_at"
    )
    lines.append("Runs:")
    for row in runs:
        lines.append(
            f"  {row['run_id']} [{row['stage']}] {row['started_at']} -> "
            f"{row['finished_at']} model={row['model_id']}"
        )

    return "\n".join(lines)
