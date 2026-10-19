"""Deterministic ID generation.

Every ID here is a pure function of already-known deterministic inputs
(content hashes, paths, offsets) -- never of model output. See the spec's
"Core Principle": no model output is ever used as an identifier.
"""

from __future__ import annotations

import datetime as _dt

import blake3


def _blake3_hex(*parts: str) -> str:
    h = blake3.blake3()
    for p in parts:
        h.update(p.encode("utf-8"))
    return h.hexdigest()


def content_hash_bytes(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def source_id(content_hash: str, relative_path: str) -> str:
    digest = _blake3_hex(content_hash, "\x00", relative_path)
    return "src_" + digest[:16]


def representation_id(source_id_: str, kind: str, config_hash: str) -> str:
    digest = _blake3_hex(source_id_, kind, config_hash)
    return "rep_" + digest[:16]


def artifact_id(
    representation_id_: str,
    extraction_class: str,
    char_start: int | None,
    char_end: int | None,
    extraction_text: str,
) -> str:
    digest = _blake3_hex(
        representation_id_,
        "\x00",
        extraction_class,
        "\x00",
        f"{char_start}:{char_end}",
        "\x00",
        extraction_text,
    )
    return "art_" + digest[:16]


def config_hash(serialized_config: str) -> str:
    return blake3.blake3(serialized_config.encode("utf-8")).hexdigest()


def new_run_id(now: _dt.datetime | None = None, conn=None) -> str:
    """run_YYYYMMDD_HHMMSS. If `conn` is given and the timestamp collides
    with an existing run (two stages invoked within the same second, which
    happens routinely in scripted/test usage), disambiguate with a short
    numeric suffix rather than raising a PRIMARY KEY collision."""
    now = now or _dt.datetime.now()
    base = "run_" + now.strftime("%Y%m%d_%H%M%S")
    if conn is None:
        return base

    candidate = base
    suffix = 2
    while conn.execute(
        "SELECT 1 FROM run WHERE run_id = ?", (candidate,)
    ).fetchone():
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate
