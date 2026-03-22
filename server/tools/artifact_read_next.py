from __future__ import annotations

from typing import Any

from ..db import (
    get_artifact_reading_session,
    get_artifact_reading_session_for_conversation_artifact,
    get_next_artifact_reading_step,
    get_artifact_reading_step,
    list_artifact_reading_sessions_for_conversation,
)
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
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    conversation_id = str(arguments.get("conversation_id") or ctx.conversation_id or "").strip()
    mark_active = bool(arguments.get("mark_active", True))

    session = None
    if session_id > 0:
        session = get_artifact_reading_session(session_id)
    elif artifact_id and conversation_id:
        session = get_artifact_reading_session_for_conversation_artifact(conversation_id, artifact_id)
    elif conversation_id:
        sessions = list_artifact_reading_sessions_for_conversation(conversation_id)
        if len(sessions) == 1:
            session = sessions[0]

    if not session:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="session_id or artifact_id is required for artifact.read_next")

    session_id = int(session.get("id") or 0)

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

    session = get_artifact_reading_session(session_id) or session
    refreshed_current = session.get("current_section_ordinal")
    current_step = None
    if refreshed_current is not None:
        try:
            current_step = get_artifact_reading_step(session_id, int(refreshed_current))
        except Exception:
            current_step = None
    next_step = get_next_artifact_reading_step(session_id, after_ordinal=refreshed_current)
    done = str(session.get("status") or "").strip().lower() == "complete" or next_step is None

    payload = dict(read_result.result)
    payload["session"] = session
    payload["current_step"] = current_step or step
    payload["next_step"] = next_step
    payload["done"] = done
    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result=payload,
        display_text=f"Loaded reading step {int((current_step or step).get('ordinal') or 0)} for session {session_id}.",
    )
