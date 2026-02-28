# server/image_helpers.py
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Optional


IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".tiff",
}


def is_image_file(path: Path, mime_type: Optional[str] = None) -> bool:
    """
    Decide if a given path/mime_type should be treated as an image.

    We rely primarily on the extension, with mime_type as a backup.
    """
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return True

    if mime_type:
        mt = mime_type.lower()
        if mt.startswith("image/"):
            return True

    guessed = mimetypes.guess_type(path.name)[0]
    if guessed and guessed.startswith("image/"):
        return True

    return False


def build_image_reference_json(file_row: dict) -> str:
    """
    Build a JSON string to store in an artifact's `content` column that
    describes this image in a way the context builder can later convert
    into an OpenAI input_image object.

    We keep this small and purely descriptive: no base64 here.
    """
    file_id = str(file_row.get("id") or "")
    path = str(file_row.get("path") or "")
    mime_type = file_row.get("mime_type")
    if not mime_type:
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"

    payload = {
        "type": "image_reference",
        "file_id": file_id,
        "path": path,
        "mime_type": mime_type,
    }
    return json.dumps(payload, ensure_ascii=False)


def load_image_bytes(path: Path) -> Optional[bytes]:
    """
    Convenience helper for when the context builder eventually wants to
    base64-encode the image bytes to feed OpenAI.

    Not used by the Artifactor directly, but this keeps all image-specific
    file handling in one place.
    """
    try:
        return path.read_bytes()
    except OSError:
        return None


def image_bytes_to_base64(data: bytes) -> str:
    """
    Turn raw image bytes into a base64-encoded string suitable for
    OpenAI's input_image object (the context builder will actually use this).
    """
    return base64.b64encode(data).decode("ascii")