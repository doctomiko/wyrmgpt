from __future__ import annotations

from typing import Any

from ..db import (
    get_artifact_reading_session,
    list_artifact_reading_steps,
    update_artifact_reading_session,
    update_artifact_reading_step,
)
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.update_session_notes",
    description="Persist summary-so-far and structured notes for a reading step.",
    input_schema={"type": "object"},
    system_usage="Use after reading a section so the session can continue with retained notes.",
    display_name="Update Artifact Session Notes",
    tags=("artifact", "reading", "session", "notes"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    session_id = int(arguments.get("session_id") or 0)
    ordinal = int(arguments.get("ordinal") or 0)
    summary_so_far = arguments.get("summary_so_far")
    notes = arguments.get("notes")
    status = str(arguments.get("status") or "done").strip() or "done"
    session_status = arguments.get("session_status")
    current_chunk_position = arguments.get("current_chunk_position")

    if session_id <= 0:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="session_id is required")
    if ordinal <= 0:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="ordinal is required")

    session = get_artifact_reading_session(session_id)
    if not session:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"reading session not found: {session_id}")

    step = update_artifact_reading_step(session_id, ordinal, status=status, notes=notes)
    steps = list_artifact_reading_steps(session_id)
    done_count = sum(1 for s in steps if (s.get("status") or "") == "done")
    complete = done_count == len(steps) and len(steps) > 0

    session = update_artifact_reading_session(
        session_id,
        current_section_ordinal=ordinal,
        current_chunk_position=int(current_chunk_position) if current_chunk_position is not None else None,
        summary_so_far=str(summary_so_far) if summary_so_far is not None else None,
        status=(str(session_status).strip() if session_status is not None else ("complete" if complete else "active")),
    )

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "session": session,
            "step": step,
            "complete": complete,
            "done_count": done_count,
            "step_count": len(steps),
        },
        display_text=f"Stored notes for session {session_id}, step {ordinal}.",
    )
