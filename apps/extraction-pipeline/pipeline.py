#!/usr/bin/env python3
"""Provenance-Preserving Extraction Pipeline -- CLI entry point.

Subcommands: snapshot, index, normalize, extract, report.
See extraction_pipeline.md for the full spec this implements.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline_lib import catalog, db, extract as extract_stage, ids, indexer, normalize, report, runs
from pipeline_lib.extractor_backend import (
    langextract_version,
    make_langextract_extractor,
    schema_hash,
)
from pipeline_lib.paths import WorkPaths
from pipeline_lib.progress import StageProgress, bar_chart, fmt_hms, human_bytes, sparkline
from pipeline_lib.snapshot import run_snapshot
from pipeline_lib.xberg_config import xberg_runtime_version

DEFAULT_MODEL_ID = "gemini-2.5-flash"


def _progress(args: argparse.Namespace, stage: str) -> StageProgress:
    return StageProgress(
        stage, verbose=not args.quiet, interactive=not args.no_progress,
    )


def _banner(stage: str, run_id: str, extra: str = "") -> None:
    line = f"▶ {stage} · run {run_id}"
    if extra:
        line += f" · {extra}"
    print(line)


def _summary(title: str, pairs: list[tuple[str, object]], chart_lines: list[str] | None = None) -> None:
    print(f"── {title} " + "─" * max(4, 50 - len(title)))
    for key, value in pairs:
        print(f"  {key:<26} {value}")
    for line in chart_lines or []:
        print(line)


def _checkpoint_notice(stage: str) -> None:
    print(
        f"⏸ {stage} stopped at a checkpoint — completed items are committed; "
        f"re-run the same command to resume (finished work is skipped)."
    )


def cmd_snapshot(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    work.ensure()
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "snapshot")

    source_root = Path(args.source_root).resolve()
    _banner("snapshot", run_id, f"{source_root} → {work.snapshot}")
    if not args.quiet:
        print(f"  rsync -aAX --exclude-from={args.excludes} (single pass, no per-file progress)")

    result = run_snapshot(Path(args.source_root), work, Path(args.excludes))
    runs.finish_run(conn, run_id)

    _summary("snapshot summary", [
        ("rsync exit code", result.rsync_exit_code),
        ("files in snapshot", result.file_count),
        ("total size", f"{human_bytes(result.total_bytes)} ({result.total_bytes} bytes)"),
    ])
    # rsync 24 = "some files vanished before transfer" -- routine on a live
    # source tree, not a snapshot failure.
    if result.rsync_exit_code not in (0, 24):
        print("snapshot: rsync reported a hard failure", file=sys.stderr)
        return 1
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "index")

    _banner("index", run_id, f"scanning {work.snapshot}")
    with _progress(args, "index") as prog:
        stats = indexer.run_index(
            conn, work.snapshot, f"file://{Path(args.source_root).resolve()}",
            run_id, progress=prog,
        )
        elapsed = prog.elapsed()
    runs.finish_run(conn, run_id)

    _summary(
        "index summary",
        [
            ("files discovered", stats.discovered),
            ("elapsed", fmt_hms(elapsed)),
        ],
        bar_chart({
            "text": stats.in_scope_text,
            "document": stats.in_scope_document,
            "out_of_scope": stats.out_of_scope,
        }),
    )
    if stats.stopped:
        _checkpoint_notice("index")
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)
    runs.start_run(conn, run_id, "normalize", xberg_version=xberg_runtime_version())

    _banner("normalize", run_id, f"xberg {xberg_runtime_version()}")
    with _progress(args, "normalize") as prog:
        stats = normalize.run_normalize(conn, work, run_id, progress=prog)
        elapsed = prog.elapsed()
    runs.finish_run(conn, run_id)

    _summary(
        "normalize summary",
        [
            ("elapsed", fmt_hms(elapsed)),
            ("ocr retries", stats.ocr_retries),
        ],
        bar_chart({
            "text normalized": stats.text_normalized,
            "document normalized": stats.document_normalized,
            "skipped (unchanged)": stats.skipped_unchanged,
            "quarantined": stats.quarantined,
        }),
    )
    if stats.stopped:
        _checkpoint_notice("normalize")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    conn = db.connect(work.sqlite)
    run_id = ids.new_run_id(conn=conn)

    model_id = args.model_id
    api_key = args.api_key or os.environ.get("LANGEXTRACT_API_KEY")
    lx_version = langextract_version()
    config = {"schema_hash": schema_hash()}
    extractor_kwargs = {}
    if args.model_url:
        # Part of the incremental-skip key on purpose: a different endpoint
        # may serve different weights under the same model name.
        config["model_url"] = args.model_url
        extractor_kwargs["model_url"] = args.model_url
    config_json_str = json.dumps(config, sort_keys=True)

    runs.start_run(
        conn, run_id, "extract",
        langextract_version=lx_version, model_id=model_id, config=config,
    )

    extractor = make_langextract_extractor(model_id, api_key, **extractor_kwargs)

    endpoint = args.model_url or "provider default"
    _banner("extract", run_id, f"model {model_id} @ {endpoint}")
    with _progress(args, "extract") as prog:
        stats = extract_stage.run_extract(
            conn, work, run_id, extractor, lx_version, model_id, config_json_str,
            progress=prog,
        )
        elapsed = prog.elapsed()
    runs.finish_run(conn, run_id)

    pairs: list[tuple[str, object]] = [
        ("representations processed", stats.representations_processed),
        ("skipped (already done)", stats.representations_skipped),
        ("grounded artifacts", stats.grounded),
        ("ungrounded (rejected)", stats.ungrounded),
        ("extractor errors", stats.errors),
        ("elapsed", fmt_hms(elapsed)),
    ]
    if stats.per_item_seconds:
        secs = stats.per_item_seconds
        pairs.append((
            "seconds per item",
            f"{sparkline(secs)}  (min {min(secs):.1f} · max {max(secs):.1f} "
            f"· mean {sum(secs) / len(secs):.1f})",
        ))
    chart = bar_chart(stats.grounded_by_class)
    if chart:
        chart = ["  grounded by class:"] + ["  " + line for line in chart]
    _summary("extract summary", pairs, chart)
    if stats.stopped:
        _checkpoint_notice("extract")
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    primary = db.connect(work.sqlite)
    cat = catalog.connect(work.catalog_sqlite)

    mode = "rebuild (dropping wide table, keeping manual tags)" if args.rebuild else "sync"
    print(f"▶ catalog · {mode} · {work.catalog_sqlite}")
    with _progress(args, "catalog") as prog:
        stats = catalog.sync(primary, cat, work, progress=prog, rebuild=args.rebuild)
        elapsed = prog.elapsed()

    total_cols = len(catalog.table_columns(cat, "artifact_wide"))
    pairs: list[tuple[str, object]] = [
        ("grounded rows", stats.grounded_rows),
        ("ungrounded rows", stats.ungrounded_rows),
        ("auto tags applied", stats.auto_tags),
        ("columns on artifact_wide", total_cols),
        ("elapsed", fmt_hms(elapsed)),
    ]
    if stats.columns_added:
        pairs.append(("new columns this sync", ", ".join(stats.columns_added)))
    _summary("catalog summary", pairs, bar_chart(stats.by_class))
    if stats.stopped:
        _checkpoint_notice("catalog")
    return 0


def cmd_tag(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    cat = catalog.connect(work.catalog_sqlite)

    if not args.artifact_prefix:
        counts = catalog.tag_counts(cat)
        if not counts:
            print("no tags yet — run `catalog` first, or add one with "
                  "`tag <artifact-id-prefix> --add <tag>`")
            return 0
        _summary("tags", [("distinct tags", len(counts))], bar_chart(counts))
        return 0

    try:
        for tag_name in args.remove:
            artifact_id = catalog.remove_tag(cat, args.artifact_prefix, tag_name)
            print(f"− {artifact_id} · {tag_name}")
        for tag_name in args.add:
            artifact_id = catalog.add_manual_tag(cat, args.artifact_prefix, tag_name)
            print(f"+ {artifact_id} · {tag_name}")
        artifact_id = catalog.resolve_artifact(cat, args.artifact_prefix)
    except ValueError as exc:
        print(f"tag: {exc}", file=sys.stderr)
        return 1

    row = cat.execute(
        "SELECT extraction_class, extraction_text, source_path, tags "
        "FROM artifact_wide WHERE artifact_id = ?", (artifact_id,),
    ).fetchone()
    text = row["extraction_text"]
    if len(text) > 70:
        text = text[:69] + "…"
    _summary(f"tags · {artifact_id}", [
        ("class", row["extraction_class"]),
        ("source", row["source_path"]),
        ("text", text),
        ("tags", ", ".join(json.loads(row["tags"] or "[]")) or "(none)"),
    ])
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    work = WorkPaths(Path(args.work_dir))
    conn = db.connect(work.sqlite)
    print(report.build_report(conn, work))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline.py")
    parser.add_argument(
        "--work-dir", default="work", help="Path to the work/ directory (default: ./work)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress per-item log lines (summaries and progress bar remain)",
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="Disable the interactive progress bar and pause/resume keys "
             "(plain log lines only; for CI or log files)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_snap = sub.add_parser("snapshot", help="Stage 0: archive the source tree")
    p_snap.add_argument("source_root")
    p_snap.add_argument("--excludes", default="excludes.txt")
    p_snap.set_defaults(func=cmd_snapshot)

    p_idx = sub.add_parser("index", help="Stage 1: scan work/snapshot/")
    p_idx.add_argument("source_root", help="Original source root (for root_uri provenance only)")
    p_idx.set_defaults(func=cmd_index)

    p_norm = sub.add_parser("normalize", help="Stage 2: text + Xberg normalization")
    p_norm.set_defaults(func=cmd_normalize)

    p_ext = sub.add_parser("extract", help="Stage 3: LangExtract + grounding")
    p_ext.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    p_ext.add_argument("--api-key", default=None)
    p_ext.add_argument(
        "--model-url", default=None,
        help="Endpoint for a self-hosted model, e.g. http://localhost:11434 "
             "for Ollama. langextract forwards it as model_url/base_url to "
             "whichever provider the model-id routes to.",
    )
    p_ext.set_defaults(func=cmd_extract)

    p_rep = sub.add_parser("report", help="Stage 4: print run report")
    p_rep.set_defaults(func=cmd_report)

    p_cat = sub.add_parser(
        "catalog",
        help="Derived: build/update work/catalog.sqlite (wide artifact table "
             "+ auto tags; separate from the spec's index.sqlite)",
    )
    p_cat.add_argument(
        "--rebuild", action="store_true",
        help="Drop and re-derive artifact_wide (pares stale attr_* columns "
             "back down; manual tags survive)",
    )
    p_cat.set_defaults(func=cmd_catalog)

    p_tag = sub.add_parser(
        "tag", help="Manage manual tags in work/catalog.sqlite",
    )
    p_tag.add_argument(
        "artifact_prefix", nargs="?",
        help="artifact_id or unique prefix (e.g. art_1a2b or 1a2b); "
             "omit to list all tags with counts",
    )
    p_tag.add_argument(
        "--add", action="append", default=[], metavar="TAG",
        help="Add a manual tag (repeatable)",
    )
    p_tag.add_argument(
        "--remove", action="append", default=[], metavar="TAG",
        help="Remove a tag (repeatable)",
    )
    p_tag.set_defaults(func=cmd_tag)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
