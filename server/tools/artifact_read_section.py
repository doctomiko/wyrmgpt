from __future__ import annotations

from typing import Any

from ..db import db_update_artifact_reading_session, db_update_artifact_reading_step
from .artifact_helpers import load_or_synthesize_artifact_chunks, render_chunk_window, resolve_artifact_section_reference
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.read_section",
    description="Load a concrete artifact section or chunk range into a tool result.",
    input_schema={"type": "object"},
    system_usage="Use when the user wants a section read or after resolving a section reference.",
    display_name="Read Artifact Section",
    tags=("artifact", "reading"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    section_ref = str(arguments.get("section_ref") or "").strip()
    session_id = arguments.get("session_id")
    ordinal = arguments.get("ordinal")
    mark_active = bool(arguments.get("mark_active", False))

    chunk_start = arguments.get("chunk_start")
    chunk_end = arguments.get("chunk_end")
    section_meta: dict[str, Any] | None = None

    if ordinal is not None and session_id is not None:
        from ..db import db_get_artifact_reading_step
        step = db_get_artifact_reading_step(int(session_id), int(ordinal))
        if not step:
            return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"reading step not found: session={session_id} ordinal={ordinal}")
        chunk_start = int(step.get("chunk_start"))
        chunk_end = int(step.get("chunk_end"))
        section_meta = {
            "ordinal": int(step.get("ordinal") or ordinal),
            "label": (step.get("label") or "").strip() or f"Section {int(step.get('ordinal') or ordinal)}",
        }
    elif section_ref:
        resolved = resolve_artifact_section_reference(artifact_id, section_ref)
        if not resolved.get("ok"):
            return ToolResult(ok=False, tool=TOOL_SPEC.name, error=str(resolved.get("error") or "section not found"), result=resolved)
        section_meta = dict(resolved.get("matched") or {})
        chunk_start = section_meta.get("chunk_start")
        chunk_end = section_meta.get("chunk_end")

    if chunk_start is None or chunk_end is None:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="chunk_start/chunk_end or section_ref/session step is required")

    art, chunks = load_or_synthesize_artifact_chunks(artifact_id)
    if not art:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"artifact not found: {artifact_id}")

    selected = [c for c in chunks if int(c.get("chunk_index") or 0) >= int(chunk_start) and int(c.get("chunk_index") or 0) <= int(chunk_end)]
    if not selected:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"no chunks found for artifact {artifact_id} range {chunk_start}-{chunk_end}")

    if mark_active and session_id is not None:
        ord_value = int(section_meta.get("ordinal") or ordinal or 0) if section_meta else 0
        if ord_value > 0:
            db_update_artifact_reading_step(int(session_id), ord_value, status="active")
            db_update_artifact_reading_session(
                int(session_id),
                current_section_ordinal=ord_value,
                current_chunk_position=int(chunk_end),
                status="active",
            )

    label = None
    if section_meta:
        label = (section_meta.get("label") or "").strip() or None
    if not label:
        label = f"chunks {int(chunk_start)}–{int(chunk_end)}"

    payload = {
        "artifact_id": artifact_id,
        "session_id": int(session_id) if session_id is not None else None,
        "title": (art.get("title") or artifact_id).strip(),
        "source_kind": (art.get("source_kind") or "").strip(),
        "section": {
            "label": label,
            "ordinal": section_meta.get("ordinal") if section_meta else None,
            "chunk_start": int(chunk_start),
            "chunk_end": int(chunk_end),
        },
        "chunk_count": len(selected),
        "text": render_chunk_window(selected),
    }
    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result=payload,
        display_text=f"Loaded {label} from {(art.get('title') or artifact_id).strip()} ({len(selected)} chunks).",
    )
