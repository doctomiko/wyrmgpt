from __future__ import annotations

from typing import Any

from ..db import get_artifact_reading_session, get_next_artifact_reading_step
from .artifact_read_section import execute as execute_read_section
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.read_next",
    description="Advance a reading session to the next pending step and return its text.",
    input_schema={"type": "object"},
    system_usage="Use when continuing a reading session.",
    display_name="Read Next Artifact Step",
    tags=("artifact", "reading", "session"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    session_id = int(arguments.get("session_id") or 0)
    mark_active = bool(arguments.get("mark_active", True))
    if session_id <= 0:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="session_id is required")

    session = get_artifact_reading_session(session_id)
    if not session:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"reading session not found: {session_id}")

    after_ordinal = session.get("current_section_ordinal")
    step = get_next_artifact_reading_step(session_id, after_ordinal=after_ordinal)
    if not step:
        return ToolResult(
            ok=True,
            tool=TOOL_SPEC.name,
            result={"session": session, "next_step": None, "done": True},
            display_text=f"Reading session {session_id} has no pending steps left.",
        )

    read_result = execute_read_section(
        {
            "artifact_id": session.get("artifact_id"),
            "session_id": session_id,
            "ordinal": int(step.get("ordinal") or 0),
            "mark_active": mark_active,
        },
        ctx,
    )
    if not read_result.ok:
        return read_result

    payload = dict(read_result.result)
    payload["session"] = session
    payload["next_step"] = step
    payload["done"] = False
    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result=payload,
        display_text=f"Loaded next reading step {int(step.get('ordinal') or 0)} for session {session_id}.",
    )
