from __future__ import annotations

import json
import logging
import mimetypes
#from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# PDF parsing is optional; if the dependency is missing we just disable the helper.
try:
    from pypdf import PdfReader
except ImportError:  # type: ignore
    PdfReader = None  # type: ignore
from typing import Optional # ,Any, Iterable, List
from .db import (
    db_session,
    get_web_source_snapshot_by_id,
    get_web_source_by_id,
    upsert_artifact_text,
    reindex_artifact_by_id,
)

try:
    # Optional; if missing we simply won't special-case DOCX.
    from . import word_helpers  # type: ignore[attr-defined]
except Exception:  # defensive
    word_helpers = None  # type: ignore[assignment]

from .image_helpers import is_image_file, build_image_reference_json
from .zip_helpers import is_zip_file, list_zip_entries, build_zip_index_text
from .markdown_helper import autolink_text, apply_house_markdown_normalization
from .html_readable import extract_readable_html_markdown

logger = logging.getLogger(__name__)

# --- Config constants ---
TEXT_INJECT_MAX_CHARS = 1_000_000  # safety cap per file before chunking

#def _utcnow_iso() -> str:
#    return datetime.now(timezone.utc).isoformat()


def _extract_docx_markdown(path: Path, autolink: bool = False) -> Optional[str]:
    """
    Extract DOCX -> markdown-ish using server/word_helpers.py (if available).
    Returns None if we can't extract.
    """
    if word_helpers is None:
        logger.warning("word_helpers not available; cannot extract DOCX %s", path)
        return None

    try:
        data = path.read_bytes()
    except OSError as e:
        logger.warning("Failed to read DOCX %s: %s", path, e)
        return None

    try:
        text = word_helpers.extract_docx_markdown(data, TEXT_INJECT_MAX_CHARS)  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning("DOCX extraction failed for %s: %s", path, e)
        return None

    if autolink:
        text = apply_house_markdown_normalization(text)
        text = autolink_text(text)

    return text

def _extract_pdf_text(path: Path, autolink: bool = False) -> Optional[str]:
    """
    Extract text from a PDF using pypdf.

    Returns a single string or None if no text could be extracted.
    """
    if PdfReader is None:
        logger.warning("pypdf not installed; cannot extract PDF %s", path)
        return None

    try:
        reader = PdfReader(str(path))
    except Exception as e:
        logger.warning("Failed to open PDF %s: %s", path, e)
        return None

    pieces: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as e:
            logger.warning("Failed to extract text from PDF %s page %s: %s", path, i, e)
            txt = ""
        if txt.strip():
            pieces.append(txt.strip())

    if not pieces:
        # Probably a scanned/image-only PDF.
        return None

    text = "\n\n".join(pieces)
    if len(text) > TEXT_INJECT_MAX_CHARS:
        text = (
            text[:TEXT_INJECT_MAX_CHARS]
            + f"\n\n[...PDF truncated; exceeded TEXT_INJECT_MAX_CHARS={TEXT_INJECT_MAX_CHARS}]"
        )

    if (autolink):
        text = apply_house_markdown_normalization(text)
        text = autolink_text(text)        
    return text


def extract_text_from_file(file_row) -> tuple[str, str]:
    """
    Returns (text, source_kind).
    source_kind can be: 'file:pdf', 'file:image', 'file:zip', 'file:docx', 'file:text'
    This function MUST NOT touch the database.
    """
    from .db import DATA_DIR  # only used to resolve storage paths

    mime = (file_row.get("mime_type") or "") if hasattr(file_row, "get") else ""
    path = file_row.get("path") if hasattr(file_row, "get") else None
    if not path:
        return ("", "file")

    abs_path = Path(path)
    if not abs_path.is_absolute():
        abs_path = Path(DATA_DIR) / path

    # --- Images: store a reference json (no OCR/caption yet) ---
    if is_image_file(abs_path, mime) or (mime.startswith("image/")):
        try:
            payload = build_image_reference_json(file_row)
            return (payload, "file:image")
        except Exception as e:
            return (f"IMAGE REF ERROR: {e}", "file:image")

    # --- ZIP: store an index of entries ---
    if is_zip_file(abs_path, mime) or abs_path.suffix.lower() == ".zip":
        try:
            entries = list_zip_entries(abs_path, max_files=5000)
            text = build_zip_index_text(abs_path, entries)
            return (text, "file:zip")
        except Exception as e:
            return (f"ZIP READ ERROR: {e}", "file:zip")

    # --- PDF: extract text via pypdf helper ---
    if mime.lower() == "application/pdf" or abs_path.suffix.lower() == ".pdf":
        text = _extract_pdf_text(abs_path, autolink=True)
        if not text:
            # Probably scanned/image-only.
            return ("[PDF had no extractable text via pypdf]", "file:pdf")
        return (text, "file:pdf")

    # --- DOCX: use word_helpers markdown extractor ---
    if (
        mime.lower() == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or abs_path.suffix.lower() == ".docx"
        or abs_path.suffix.lower() == ".docm"
    ):
        text = _extract_docx_markdown(abs_path, autolink=True)
        if not text:
            return ("[DOCX extract failed or produced no text]", "file:docx")
        return (text, "file:docx")

    # --- Fallback: treat as text bytes (with NUL/binary detection if available) ---
    try:
        data = abs_path.read_bytes()
    except Exception as e:
        return (f"READ ERROR: {e}", "file")

    # Prefer the helper’s binary detection / truncation
    if word_helpers is not None and hasattr(word_helpers, "extract_text_bytes"):
        try:
            text, _truncated = word_helpers.extract_text_bytes(data, TEXT_INJECT_MAX_CHARS)  # type: ignore[attr-defined]
            text = apply_house_markdown_normalization(text)
            text = autolink_text(text)
            return (text, "file:text")
        except Exception:
            # fall through to naive decode
            pass

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")

    if len(text) > TEXT_INJECT_MAX_CHARS:
        text = text[:TEXT_INJECT_MAX_CHARS] + f"\n\n[...truncated; exceeded TEXT_INJECT_MAX_CHARS={TEXT_INJECT_MAX_CHARS}]"

    text = apply_house_markdown_normalization(text)
    text = autolink_text(text)
    return (text, "file:text")


def _extract_text_from_html(
    html: str,
    *,
    base_url: str | None = None,
    fallback_title: str | None = None,
) -> tuple[str, str]:
    """
    Returns (title, markdown_text)
    """
    raw = (html or "").strip()
    if not raw:
        return ((fallback_title or "").strip(), "")

    parsed = extract_readable_html_markdown(
        raw,
        base_url=base_url,
        fallback_title=fallback_title,
    )
    title = (parsed.title or fallback_title or "").strip()
    text = apply_house_markdown_normalization(parsed.markdown)
    return (title, text)


def build_web_artifact_payload(
    *,
    snapshot: dict,
    source: dict,
) -> dict | None:
    raw_html = snapshot.get("raw_html") or ""
    raw_text = snapshot.get("raw_text") or ""

    if raw_html.strip():
        title, text = _extract_text_from_html(
            raw_html,
            base_url=(snapshot.get("final_url") or source.get("canonical_url") or "").strip() or None,
            fallback_title=source.get("canonical_url") or "Web Page",
        )
        if not (text or "").strip() and (raw_text or "").strip():
            title = title or source.get("canonical_url") or "Web Page"
            text = apply_house_markdown_normalization((raw_text or "").strip())
            text = autolink_text(text)
    else:
        title = source.get("canonical_url") or "Web Page"
        text = apply_house_markdown_normalization((raw_text or "").strip())
        text = autolink_text(text)

    text = (text or "").strip()
    if not text:
        return None

    return {
        "title": (title or source.get("canonical_url") or "Web Page").strip(),
        "text": text,
        "source_kind": "web:snapshot",
        "source_id": str(snapshot["id"]),
    }