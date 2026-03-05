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
    # create_file_artifacts,
    resolve_scope_for_file,
    #get_file_by_id,
)
try:
    # Optional; if missing we simply won't special-case DOCX.
    from . import word_helpers  # type: ignore[attr-defined]
except Exception:  # defensive
    word_helpers = None  # type: ignore[assignment]

from .image_helpers import is_image_file, build_image_reference_json
from .zip_helpers import is_zip_file, list_zip_entries, build_zip_index_text
from .markdown_helper import autolink_text, apply_house_markdown_normalization

logger = logging.getLogger(__name__)

# --- Config constants ---
TEXT_INJECT_MAX_CHARS = 1_000_000  # safety cap per file before chunking

#def _utcnow_iso() -> str:
#    return datetime.now(timezone.utc).isoformat()

if (False): # Moved to chunking.py
    CHUNK_TARGET_CHARS = 4000        # soft target per artifact chunk
    CHUNK_HARD_MAX_CHARS = 6000      # absolute max per artifact chunk

    # File extensions that we will treat as "code" for chunking purposes.
    CODE_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".cs",
        ".cpp",
        ".c",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".sh",
        ".ps1",
        ".bat",
        ".sql",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
    }

    def _is_probably_code(path: Path, mime_type: Optional[str]) -> bool:
        ext = path.suffix.lower()
        if ext in CODE_EXTENSIONS:
            return True
        if mime_type and mime_type.startswith("text/"):
            # Some text/* types are more "code-like" than prose (e.g. application/json),
            # but for now we treat unknown text types as prose.
            return False
        return False

    def _chunk_text_blocks(blocks: List[str]) -> List[str]:
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        def flush_current() -> None:
            nonlocal current, current_len
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0

        for block in blocks:
            block = block.rstrip()
            if not block:
                # preserve paragraph breaks by appending an empty block if we already
                # have content, otherwise ignore.
                if current:
                    current.append("")
                    current_len += 1
                continue

            block_len = len(block)
            if block_len > CHUNK_HARD_MAX_CHARS:
                # over-sized block; split on single newlines inside it
                sublines = block.split("\n")
                sub_current: List[str] = []
                sub_len = 0
                for line in sublines:
                    line_len = len(line)
                    if sub_len and sub_len + 1 + line_len > CHUNK_HARD_MAX_CHARS:
                        chunks.append("\n".join(sub_current).strip())
                        sub_current = [line]
                        sub_len = line_len
                    else:
                        sub_current.append(line)
                        sub_len += line_len + (1 if sub_current else 0)
                if sub_current:
                    chunks.append("\n".join(sub_current).strip())
                continue

            if current_len and current_len + 2 + block_len > CHUNK_TARGET_CHARS:
                flush_current()

            current.append(block)
            current_len += block_len + (2 if current else 0)

        flush_current()
        return [c for c in chunks if c]

    def _chunk_text_general(text: str) -> List[str]:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        blocks = text.split("\n\n")
        chunks = _chunk_text_blocks(blocks)
        if not chunks:
            return [text]
        # Ensure small trailing chunk is merged if it's tiny.
        if len(chunks) >= 2 and len(chunks[-1]) < 500:
            penultimate = chunks[-2]
            last = chunks[-1]
            if len(penultimate) + 2 + len(last) <= CHUNK_HARD_MAX_CHARS:
                chunks[-2] = penultimate + "\n\n" + last
                chunks.pop()
        return chunks

    def _chunk_text_code(text: str) -> List[str]:
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        def flush_current() -> None:
            nonlocal current, current_len
            if current:
                chunks.append("\n".join(current).rstrip())
                current = []
                current_len = 0

        for line in lines:
            line_len = len(line)
            if line_len > CHUNK_HARD_MAX_CHARS:
                # Monster line (minified bundle, etc). Hard-split it.
                start = 0
                while start < line_len:
                    end = min(start + CHUNK_HARD_MAX_CHARS, line_len)
                    part = line[start:end]
                    if current_len and current_len + 1 + len(part) > CHUNK_HARD_MAX_CHARS:
                        flush_current()
                    current.append(part)
                    current_len += len(part) + (1 if current else 0)
                    start = end
                continue

            if current_len and current_len + 1 + line_len > CHUNK_TARGET_CHARS:
                flush_current()

            current.append(line)
            current_len += line_len + 1

        flush_current()
        return [c for c in chunks if c]

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

# TODO This was only being called in functions that no longer exist; does it do anything that the other version does not do? If so, we should make sure we do not have feature drift/loss
if (False): 
    def _extract_text_for_file(path: Path, mime_type: Optional[str], autolink: bool = True) -> Optional[str]:
        """
        Best-effort text extraction for a generic file.

        For now we support:
        - plain text / markdown / JSON / CSV / source-code via a generic text decoder
        - DOCX via word_helpers if available

        PDF, images, and ZIPs will be handled in later passes.
        """
        ext = path.suffix.lower()

        # DOCX (if helper + dependency are available)
        if ext in {".docx", ".docm"} and word_helpers is not None:
            try:
                data = path.read_bytes()
            except OSError as e:
                logger.warning("Failed to read DOCX file %s: %s", path, e)
                return None
            try:
                return word_helpers.extract_docx_markdown(data, TEXT_INJECT_MAX_CHARS)  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning("DOCX extraction failed for %s: %s", path, e)
                return None

        # PDF via pypdf
        if ext == ".pdf" or (mime_type and mime_type.lower() == "application/pdf"):
            text = _extract_pdf_text(path)
            if not text:
                logger.info("PDF %s appears to have no extractable text; skipping.", path)
                return None
            return text

        # ZIP and images: still skipped for now
        if ext == ".zip":
            logger.info("Skipping ZIP expansion for now: %s", path)
            return None
        
        if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}:
            logger.info("Skipping image artifacting for now: %s", path)
            return None

        # Generic text-ish file
        try:
            data = path.read_bytes()
        except OSError as e:
            logger.warning("Failed to read file %s: %s", path, e)
            return None

        # Reuse the helper logic if available.
        if word_helpers is not None and hasattr(word_helpers, "extract_text_bytes"):
            try:
                text, _truncated = word_helpers.extract_text_bytes(
                    data, TEXT_INJECT_MAX_CHARS
                )  # type: ignore[attr-defined]
                return text
            except Exception as e:
                logger.warning("extract_text_bytes failed for %s: %s", path, e)

        # Fallback: naive UTF-8 decode with replacement.
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")

        if len(text) > TEXT_INJECT_MAX_CHARS:
            text = (
                text[:TEXT_INJECT_MAX_CHARS]
                + f"\n\n[...truncated; exceeded TEXT_INJECT_MAX_CHARS={TEXT_INJECT_MAX_CHARS}]"
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

if (False): # Legacy was replaced by above that uses helpers more effectively
    def extract_text_from_file(file_row) -> tuple[str, str]:
        """
        Returns (text, source_kind).
        source_kind can be: 'file:pdf', 'file:image', 'file:zip', 'file:text' etc.
        This function MUST NOT touch the database.
        """
        from .db import DATA_DIR # only used for storage paths; the database is not touched at all by this function

        mime = (file_row["mime_type"] if "mime_type" in file_row.keys() else None) or ""
        path = file_row["path"] if "path" in file_row.keys() else None
        if not path:
            return ("", "file")

        abs_path = Path(path)
        if not abs_path.is_absolute():
            abs_path = Path(DATA_DIR) / path

        # Images: store a reference-json (no OCR/caption yet)
        if mime.startswith("image/"):
            payload = {
                "kind": "file:image",
                "file_id": file_row["id"],
                "mime_type": mime,
                "path": str(abs_path),
            }
            # no need to do markdown normalization for this file type
            return (json.dumps(payload, ensure_ascii=False, indent=2), "file:image")

        # ZIP: store an index of entries
        if mime in ("application/zip",) or abs_path.suffix.lower() == ".zip":
            import zipfile
            try:
                with zipfile.ZipFile(abs_path, "r") as z:
                    names = z.namelist()
                text = "ZIP CONTENTS:\n" + "\n".join(names[:5000])
                # TODO optionally extract the ZIP into a subfolder of data/files and add the contents to articles
                # Currently no need to normalize markdown syntax
                return (text, "file:zip")
            except Exception as e:
                return (f"ZIP READ ERROR: {e}", "file:zip")

        # PDF: extract text via pypdf if available
        if mime == "application/pdf" or abs_path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(abs_path))
                parts = []
                for page in reader.pages:
                    parts.append(page.extract_text() or "")
                # TO DO make sure we're doing our maximumn to interpret the PDF file here
                text = "\n".join(parts).strip()
                text = apply_house_markdown_normalization(text)
                text = autolink_text(text)        
                return (text, "file:pdf")
            except Exception as e:
                return (f"PDF EXTRACT ERROR: {e}", "file:pdf")

        # DOCX: optional
        if mime in ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",) or abs_path.suffix.lower() == ".docx":
            try:
                import docx
                d = docx.Document(str(abs_path))
                # TO DO make sure we're doing our maximumn to interpret the DOCX file here
                text = "\n".join(p.text for p in d.paragraphs).strip()
                text = apply_house_markdown_normalization(text)
                text = autolink_text(text)        
                return (text, "file:docx")
            except Exception as e:
                return (f"DOCX EXTRACT ERROR: {e}", "file:docx")

        # Fallback: try text
        try:
            data = abs_path.read_bytes()
            text = data.decode("utf-8", errors="replace")
            # May as well assume we can make things MD-like
            # TO DO do not alter code files!!!
            text = apply_house_markdown_normalization(text)
            text = autolink_text(text)    
            return (text, "file:text")
        except Exception as e:
            return (f"READ ERROR: {e}", "file")

if False: # LEGACY (kept for reference; safe block)
    def artifact_file(file_row: dict) -> list[str]:
        """
        End-to-end artifacting for a single file.

        This function is deliberately best-effort: on failure it logs and returns [].
        """
        file_id = file_row.get("id")
        path = Path(str(file_row.get("path", "")))

        if not file_id or not path:
            logger.warning("artifact_file called with incomplete file_row: %r", file_row)
            return []

        scope = resolve_scope_for_file(file_row)
        if scope.project_id is None:
            logger.info(
                "Skipping artifacting for file %s (%s); no project_id could be resolved.",
                file_id,
                path,
            )
            return []

        mime_type = file_row.get("mime_type") or mimetypes.guess_type(path.name)[0]

        # --- IMAGE PATH: create a single "image_reference" artifact and bail ---
        if is_image_file(path, mime_type):
            try:
                payload = build_image_reference_json(file_row)

                chunks = [payload]  # one artifact per image for now

                # TODO need to replace this...
                artifact_ids = create_file_artifacts(
                    file_row=file_row,
                    project_id=scope.project_id,
                    scope_type=scope.scope_type,
                    scope_id=scope.scope_id,
                    scope_uuid=scope.scope_uuid,
                    chunks=chunks,
                    # TODO cleanup the data if the file_row source_kind is something else (e.g. "file:zip")? For now we just preserve it if present since it may be useful for debugging, but we want to make sure it's always set to some image-specific value for image files at least.
                    source_kind="file:image", # file_row.get("source_kind") or
                    provenance=file_row.get("provenance") or "artifact:file_upload",
                )
                return artifact_ids
            except Exception as e:
                logger.exception(
                    "Image artifacting failed for file %s (%s): %s", file_id, path, e
                )
                return []

        # --- ZIP PATH: create a single "zip index" artifact for now ---
        if is_zip_file(path, mime_type):
            try:
                entries = list_zip_entries(path)
                index_text = build_zip_index_text(path, entries)
                chunks = [index_text]  # one artifact describing the archive

                # TODO need to replace this...
                artifact_ids = create_file_artifacts(
                    file_row=file_row,
                    project_id=scope.project_id,
                    scope_type=scope.scope_type,
                    scope_id=scope.scope_id,
                    scope_uuid=scope.scope_uuid,
                    chunks=chunks,
                    source_kind="file:zip", # file_row.get("source_kind") or
                    provenance=file_row.get("provenance") or "artifact:file_upload",
                )
                return artifact_ids
            except Exception as e:
                logger.exception(
                    "ZIP artifacting failed for file %s (%s): %s", file_id, path, e
                )
                return []

        # --- TEXT / DOCX / PDF / CODE PATH (existing logic) ---
        try:
            text = _extract_text_for_file(path, mime_type)
            if not text:
                logger.info(
                    "No extractable text for file %s (%s); skipping artifacts.",
                    file_id,
                    path,
                )
                return []

            is_code = _is_probably_code(path, mime_type)
            chunks = _chunk_text_code(text) if is_code else _chunk_text_general(text)
            if not chunks:
                logger.info(
                    "Chunker returned no chunks for file %s (%s); skipping artifacts.",
                    file_id,
                    path,
                )
                return []

            # TODO need to replace this...
            artifact_ids = create_file_artifacts(
                file_row=file_row,
                project_id=scope.project_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                scope_uuid=scope.scope_uuid,
                chunks=chunks,
                source_kind="file:upload", # file_row.get("source_kind") or
                provenance=file_row.get("provenance") or "artifact:file_upload",
            )
            return artifact_ids
        except Exception as e:
            logger.exception(
                "artifact_file failed for file %s (%s): %s", file_id, path, e
            )
            return []

    def artifact_file(file_row: dict) -> List[str]:
        """
        End-to-end artifacting for a single file.

        This function is deliberately best-effort: on failure it logs and returns [].
        """
        file_id = file_row.get("id")
        path = Path(str(file_row.get("path", "")))

        if not file_id or not path:
            logger.warning("artifact_file called with incomplete file_row: %r", file_row)
            return []

        scope = resolve_scope_for_file(file_row)
        if scope.project_id is None:
            logger.info(
                "Skipping artifacting for file %s (%s); no project_id could be resolved.",
                file_id,
                path,
            )
            return []

        mime_type = file_row.get("mime_type") or mimetypes.guess_type(path.name)[0]

        try:
            text = _extract_text_for_file(path, mime_type)
            if not text:
                logger.info(
                    "No extractable text for file %s (%s); skipping artifacts.",
                    file_id,
                    path,
                )
                return []

            is_code = _is_probably_code(path, mime_type)
            chunks = _chunk_text_code(text) if is_code else _chunk_text_general(text)
            if not chunks:
                logger.info(
                    "Chunker returned no chunks for file %s (%s); skipping artifacts.",
                    file_id,
                    path,
                )
                return []

            artifact_ids = create_file_artifacts(
                file_row=file_row,
                project_id=scope.project_id,
                scope_type=scope.scope_type,
                scope_id=scope.scope_id,
                scope_uuid=scope.scope_uuid,
                chunks=chunks,
                source_kind=file_row.get("source_kind") or "file:upload",
                provenance=file_row.get("provenance") or "artifact:file_upload",
            )
            return artifact_ids
        except Exception as e:
            logger.exception(
                "artifact_file failed for file %s (%s): %s", file_id, path, e
            )
            return []