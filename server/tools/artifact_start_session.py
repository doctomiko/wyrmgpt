from __future__ import annotations

from typing import Any

from ..artifact_reading_planner import get_artifact_readiness
from ..db import (
    get_artifact_reading_session_for_conversation_artifact,
    get_next_artifact_reading_step,
    list_artifact_reading_steps,
    replace_artifact_reading_steps,
    update_artifact_reading_session,
    upsert_artifact_reading_session,
)
from .artifact_helpers import load_or_synthesize_artifact_chunks
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.start_session",
    description="Create or refresh a durable reading session for an artifact.",
    input_schema={"type": "object"},
    system_usage="Use before sequential reading so progress and notes can persist across turns.",
    display_name="Start Artifact Reading Session",
    tags=("artifact", "reading", "session"),
)


def _build_steps_from_readiness(artifact_id: str) -> tuple[list[dict[str, Any]], str | None]:
    readiness = get_artifact_readiness(artifact_id)
    if readiness and readiness.index_sections:
        steps = []
        for idx, sec in enumerate(readiness.index_sections, start=1):
            c0 = sec.get("chunk_start")
            c1 = sec.get("chunk_end")
            if c0 is None or c1 is None:
                continue
            label = (sec.get("label") or sec.get("section_kind") or f"Section {idx}").strip()
            steps.append({
                "ordinal": int(sec.get("ordinal") or idx),
                "label": label,
                "chunk_start": int(c0),
                "chunk_end": int(c1),
                "status": "pending",
            })
        if steps:
            return steps, readiness.title

    art, chunks = load_or_synthesize_artifact_chunks(artifact_id)
    if not art or not chunks:
        return [], None
    return [{
        "ordinal": 1,
        "label": (art.get("title") or artifact_id).strip() or "Full artifact",
        "chunk_start": int(chunks[0].get("chunk_index") or 0),
        "chunk_end": int(chunks[-1].get("chunk_index") or 0),
        "status": "pending",
    }], (art.get("title") or artifact_id).strip()


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    conversation_id = str(arguments.get("conversation_id") or ctx.conversation_id or "").strip()
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    mode = str(arguments.get("mode") or "reading").strip() or "reading"
    strategy = arguments.get("strategy")
    restart = bool(arguments.get("restart", False))

    if not conversation_id:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="conversation_id is required")
    if not artifact_id:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="artifact_id is required")

    steps, title = _build_steps_from_readiness(artifact_id)
    if not steps:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="artifact has no readable sections or chunks yet")

    existing = get_artifact_reading_session_for_conversation_artifact(conversation_id, artifact_id)
    if existing and not restart:
        session_id = int(existing["id"])
        stored_steps = list_artifact_reading_steps(session_id)
        next_step = get_next_artifact_reading_step(
            session_id,
            after_ordinal=existing.get("current_section_ordinal"),
            include_active=True,
        )
        existing = update_artifact_reading_session(session_id, status="active")
        return ToolResult(
            ok=True,
            tool=TOOL_SPEC.name,
            result={
                "session": existing,
                "steps": stored_steps,
                "artifact_id": artifact_id,
                "title": title or artifact_id,
                "step_count": len(stored_steps),
                "reused_existing_session": True,
                "next_step": next_step,
            },
            display_text=f"Reusing reading session {session_id} for {title or artifact_id}.",
        )

    summary_so_far = None if restart or not existing else existing.get("summary_so_far")

    session = upsert_artifact_reading_session(
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        mode=mode,
        status="active",
        strategy_json=strategy,
        current_section_ordinal=None,
        current_chunk_position=None,
        summary_so_far=summary_so_far,
    )

    session_id = int(session["id"])
    stored_steps = replace_artifact_reading_steps(session_id, steps)
    session = update_artifact_reading_session(session_id, current_section_ordinal=None, current_chunk_position=None, status="active")
    next_step = get_next_artifact_reading_step(session_id, after_ordinal=None, include_active=True)

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "session": session,
            "steps": stored_steps,
            "artifact_id": artifact_id,
            "title": title or artifact_id,
            "step_count": len(stored_steps),
            "reused_existing_session": False,
            "next_step": next_step,
        },
        display_text=f"Prepared reading session {session_id} for {title or artifact_id} with {len(stored_steps)} steps.",
    )
