# server/zip_helpers.py
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
import zipfile


ZIP_EXTENSIONS = {".zip"}


def is_zip_file(path: Path, mime_type: Optional[str] = None) -> bool:
    """
    Decide if a given path/mime_type should be treated as a ZIP archive.
    """
    ext = path.suffix.lower()
    if ext in ZIP_EXTENSIONS:
        return True

    if mime_type:
        mt = mime_type.lower()
        if mt in {"application/zip", "application/x-zip-compressed"}:
            return True

    guessed = mimetypes.guess_type(path.name)[0]
    if guessed and guessed in {"application/zip", "application/x-zip-compressed"}:
        return True

    return False


def list_zip_entries(
    zip_path: Path,
    *,
    max_files: int = 500,
    max_total_size: int = 100_000_000,
) -> List[Tuple[str, int]]:
    """
    Return a list of (name, uncompressed_size) for entries in the ZIP,
    subject to sane safety limits.

    We intentionally do NOT extract here; we just inspect.
    """
    entries: List[Tuple[str, int]] = []
    total_size = 0

    try:
        with zipfile.ZipFile(str(zip_path), "r") as zf:
            for info in zf.infolist():
                # Skip directories
                if info.is_dir():
                    continue

                name = info.filename
                size = info.file_size or 0

                total_size += size
                entries.append((name, size))

                if len(entries) >= max_files:
                    break
                if total_size > max_total_size:
                    break
    except Exception:
        # If we can't read the zip for some reason, just return empty.
        return []

    return entries


def build_zip_index_text(
    zip_path: Path,
    entries: Iterable[Tuple[str, int]],
) -> str:
    """
    Build a human-readable text description of the ZIP contents.
    This is what we'll store in the artifact content for now.
    """
    entries = list(entries)
    header_lines = [
        f"ZIP archive: {zip_path.name}",
        "",
        "Contents:",
    ]

    if not entries:
        header_lines.append("  (no readable file entries found)")
        return "\n".join(header_lines)

    lines: List[str] = header_lines
    for name, size in entries:
        lines.append(f"  - {name} ({size} bytes)")

    return "\n".join(lines)