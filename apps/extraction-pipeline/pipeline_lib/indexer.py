"""Stage 1 -- Index.

Recursively scans work/snapshot/ and records every file (in scope or not).
Idempotent: re-running upserts by relative_path, refreshing hash/metadata
and bumping last_run_id, but reuses first_run_id and does not touch
representation/artifact rows.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pipeline_lib import ids, scope as scope_mod
from pipeline_lib.progress import NullProgress


@dataclass
class IndexStats:
    discovered: int = 0
    in_scope_text: int = 0
    in_scope_document: int = 0
    out_of_scope: int = 0
    stopped: bool = False


def _read_xattrs(path: Path) -> dict:
    result = {}
    try:
        for name in os.listxattr(path, follow_symlinks=False):
            try:
                value = os.getxattr(path, name, follow_symlinks=False)
                try:
                    result[name] = value.decode("utf-8")
                except UnicodeDecodeError:
                    result[name] = value.hex()
            except OSError:
                continue
    except OSError:
        pass
    return result


def run_index(
    conn: sqlite3.Connection,
    snapshot_root: Path,
    source_root_uri: str,
    run_id: str,
    progress=None,
) -> IndexStats:
    progress = progress or NullProgress()
    stats = IndexStats()
    cur = conn.cursor()

    files = [
        p for p in sorted(snapshot_root.rglob("*"))
        if p.is_file() and not p.is_symlink()
    ]
    progress.set_total(len(files))

    for path in files:
        if not progress.checkpoint():
            stats.stopped = True
            break

        stats.discovered += 1
        relative_path = str(path.relative_to(snapshot_root))
        progress.item_start(relative_path)
        st = path.stat()
        data = path.read_bytes()
        content_hash = ids.content_hash_bytes(data)
        src_id = ids.source_id(content_hash, relative_path)

        mime_type, mime_detector = scope_mod.detect_mime_type(path)
        sc, scope_reason = scope_mod.classify_scope(path, mime_type)
        if sc == scope_mod.SCOPE_TEXT:
            stats.in_scope_text += 1
        elif sc == scope_mod.SCOPE_DOCUMENT:
            stats.in_scope_document += 1
        else:
            stats.out_of_scope += 1

        xattrs_json = json.dumps(_read_xattrs(path), sort_keys=True)

        existing = cur.execute(
            "SELECT source_id, first_run_id, content_hash, status "
            "FROM source WHERE relative_path = ?",
            (relative_path,),
        ).fetchone()

        if existing is None:
            change = "new"
            cur.execute(
                """
                INSERT INTO source (
                    source_id, root_uri, relative_path, extension, mime_type,
                    mime_detector, scope, scope_reason, size_bytes, mtime_ns,
                    mode, xattrs_json, content_hash, status,
                    first_run_id, last_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'indexed', ?, ?)
                """,
                (
                    src_id, source_root_uri, relative_path, path.suffix.lower(),
                    mime_type, mime_detector, sc, scope_reason,
                    st.st_size, st.st_mtime_ns, st.st_mode, xattrs_json,
                    content_hash, run_id, run_id,
                ),
            )
        elif existing["content_hash"] == content_hash:
            change = "unchanged"
            # Unchanged bytes: update mutable OS metadata in place, keep
            # source_id/status/first_run_id stable so representation/
            # artifact rows (which reference source_id) stay valid and
            # later stages see nothing to redo.
            cur.execute(
                """
                UPDATE source SET
                    mime_type = ?, mime_detector = ?, scope = ?, scope_reason = ?,
                    size_bytes = ?, mtime_ns = ?, mode = ?, xattrs_json = ?,
                    last_run_id = ?
                WHERE relative_path = ?
                """,
                (
                    mime_type, mime_detector, sc, scope_reason,
                    st.st_size, st.st_mtime_ns, st.st_mode, xattrs_json,
                    run_id, relative_path,
                ),
            )
        else:
            change = "content changed, reset to indexed"
            # Content changed at the same path: new source_id, back to
            # 'indexed' so normalize/extract redo the work under the new
            # content_hash. Old representation/artifact rows referencing
            # the previous source_id are left in place as history.
            cur.execute(
                """
                UPDATE source SET
                    source_id = ?, extension = ?, mime_type = ?, mime_detector = ?,
                    scope = ?, scope_reason = ?, size_bytes = ?, mtime_ns = ?,
                    mode = ?, xattrs_json = ?, content_hash = ?, status = 'indexed',
                    last_run_id = ?
                WHERE relative_path = ?
                """,
                (
                    src_id, path.suffix.lower(), mime_type, mime_detector,
                    sc, scope_reason, st.st_size, st.st_mtime_ns, st.st_mode,
                    xattrs_json, content_hash, run_id, relative_path,
                ),
            )

        # Commit per item (like normalize/extract) so an immediate abort
        # loses at most the file in flight, not the whole scan.
        conn.commit()
        progress.item_done(relative_path, f"{sc} · {mime_type} · {change}")

    return stats
