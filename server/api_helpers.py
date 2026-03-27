# -------------------------
# API Helper Functions
# -------------------------

import asyncio
import re
import json
from typing import Any
from fastapi import HTTPException

from server.db import db_update_conversation_scaffold_event
from server.logging_helper import log_warn
from server.providers.types import ModelInput
from .markdown_helper import apply_house_markdown_normalization, autolink_text


# region Zeitgeber Helpers

ZEIT_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"⟂ts=\d+"
    r"|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=-?\d+)?"
    r")\s*\n",
    re.UNICODE
)
LEGACY_BRACKET_RE = re.compile(r"^\s*\[20\d\d-[^\]]+\]\s*\n")

def strip_zeitgeber_prefix(text: str) -> str:
    if not text:
        return text
    text = ZEIT_PREFIX_RE.sub("", text, count=1)
    text = LEGACY_BRACKET_RE.sub("", text, count=1)  # safety for old runs
    return text.lstrip("\ufeff")  # optional: strip BOM weirdness

# endregion

# region Misc Helper functions

RowDict = dict[str, Any]


async def sleep_ms(ms: int) -> None:
    await asyncio.sleep(ms / 1000.0)


def trim_history(model_input: ModelInput, keep_last_n: int = 30) -> ModelInput:
    # Keep system message(s) at front, keep last N non-system messages.
    system = [m for m in model_input if m.get("role") == "system"]
    non_system = [m for m in model_input if m.get("role") != "system"]
    return system + non_system[-keep_last_n:]


def load_json_object(value: Any) -> RowDict:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            loaded = json.loads(text)
        except Exception:
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def coerce_optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_scope_type(scope_type: str | None) -> str:
    st = (scope_type or "").strip().lower()
    if st in ("conversation", "chat"):
        return "conversation"
    if st == "project":
        return "project"
    return "global"


def postprocess_text(text: str) -> str:
    """
    House normalization for output before storing in DB or displaying on screen.
    - strip zeitgeber prefix
    - normalize markdown dialect
    - autolink URLs/domains
    """
    if not text:
        return text
    text = text.strip()
    text = strip_zeitgeber_prefix(text)
    text = apply_house_markdown_normalization(text)
    text = autolink_text(text)
    return text


def _preview_content(c):
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            t = (p.get("type") or "").strip()
            if t == "input_text":
                parts.append(p.get("text") or "")
            elif t == "input_image":
                url = p.get("image_url") or ""
                parts.append(f"[input_image data_url len={len(url)}]")
            else:
                parts.append(json.dumps(p, ensure_ascii=False))
        return "\n".join(parts)
    return str(c)


def http_from_value_error(e: ValueError) -> None:
    msg = str(e).strip() or "Invalid request."
    # crude but effective for now; tighten later if you want
    if "not found" in msg.lower():
        raise HTTPException(status_code=404, detail=msg)
    raise HTTPException(status_code=400, detail=msg)


def promote_targets_for_scope(scope_type: str, *, project_id: int | None = None) -> list[RowDict]:
    st = normalize_scope_type(scope_type)
    targets: list[RowDict] = []
    if st == "conversation" and project_id is not None:
        targets.append({"label": "Promote to Project", "scope_type": "project", "scope_id": int(project_id), "scope_uuid": None})
    if st in ("conversation", "project"):
        targets.append({"label": "Promote to Global", "scope_type": "global", "scope_id": None, "scope_uuid": None})
    return targets


def attach_scaffold_events_to_message(event_ids: list[int], message_id: int | None) -> None:
    """
    This helper connect a scaffold event card to a specific chat message.
    May be augmented / replaced later by a notification system.
    """
    if not message_id:
        return
    for event_id in event_ids:
        try:
            db_update_conversation_scaffold_event(event_id=event_id, message_id=message_id)
        except Exception as exc:
            log_warn(f"Tool scaffold event attachment failed for event {event_id}: {exc}")


# endregion
