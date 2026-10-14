"""Scope classification and MIME detection for Stage 1 -- Index."""

from __future__ import annotations

import mimetypes
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".json", ".jsonl", ".csv", ".yaml",
    ".yml", ".py", ".js", ".ts", ".html",
}
DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".docx", ".pptx"}

SCOPE_TEXT = "text"
SCOPE_DOCUMENT = "document"
SCOPE_OUT_OF_SCOPE = "out_of_scope"


def detect_mime_type(path: Path) -> tuple[str | None, str]:
    """Returns (mime_type, detector_name). Xberg first, mimetypes fallback."""
    try:
        import kreuzberg as xberg

        mime = xberg.detect_mime_type_from_path(str(path))
        if mime:
            return mime, "xberg"
    except Exception:
        pass

    mime, _ = mimetypes.guess_type(str(path))
    return mime, "mimetypes"


def classify_scope(path: Path, mime_type: str | None) -> tuple[str, str]:
    """Returns (scope, scope_reason). MIME wins when it maps cleanly to a
    known scope; extension is the fallback (this also covers the case where
    detection failed entirely)."""
    ext = path.suffix.lower()

    if mime_type:
        if mime_type == "application/pdf" or mime_type.startswith("image/"):
            return SCOPE_DOCUMENT, f"mime:{mime_type}"
        if mime_type in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ):
            return SCOPE_DOCUMENT, f"mime:{mime_type}"
        if mime_type.startswith("text/") or mime_type in (
            "application/json",
            "application/x-yaml",
            "application/yaml",
        ):
            if ext in TEXT_EXTENSIONS:
                return SCOPE_TEXT, f"mime:{mime_type}"

    if ext in TEXT_EXTENSIONS:
        return SCOPE_TEXT, f"extension:{ext}"
    if ext in DOCUMENT_EXTENSIONS:
        return SCOPE_DOCUMENT, f"extension:{ext}"
    return SCOPE_OUT_OF_SCOPE, f"extension:{ext or '(none)'}"
