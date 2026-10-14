"""Shared Xberg (Kreuzberg) extraction config for Stage 2b."""

from __future__ import annotations

import kreuzberg as xberg


def base_config(*, force_ocr: bool = False) -> "xberg.ExtractionConfig":
    return xberg.ExtractionConfig(
        output_format="structured",
        pages=xberg.PageConfig(extract_pages=True, insert_page_markers=True),
        include_document_structure=True,
        force_ocr=force_ocr,
    )


def config_hash_hex(config: "xberg.ExtractionConfig") -> str:
    import blake3

    serialized = xberg.config_to_json(config)
    return blake3.blake3(serialized.encode("utf-8")).hexdigest()


def xberg_runtime_version() -> str:
    return xberg.__version__


def result_to_layout_json(result) -> dict:
    """Plain-dict projection of an ExtractionResult for the .layout.json
    side file. Raw layout JSON is preserved on disk but NOT modeled in
    SQLite beyond the representation row (spec 2b)."""
    return {
        "mime_type": result.mime_type,
        "metadata": result.metadata,
        "tables": [
            {
                "cells": t.cells,
                "markdown": t.markdown,
                "page_number": t.page_number,
            }
            for t in (result.tables or [])
        ],
        "document": result.document,
        "detected_languages": result.detected_languages,
    }
