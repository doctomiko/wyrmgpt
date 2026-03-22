from __future__ import annotations

from typing import Any

from ..artifact_reading_planner import get_artifact_readiness
from ..reading_session_notes import coerce_reading_strategy, load_reading_questions
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


def _fallback_chunk_window_size(strategy_payload: dict[str, Any] | None) -> int:
    modes = {str(m).strip().lower() for m in ((strategy_payload or {}).get("modes") or []) if str(m).strip()}
    if modes & {"reader_experience", "narrative", "worldbuilding", "style"}:
        return 1
    if modes & {"scientific_research", "technical_systems", "argument"}:
        return 3
    return 2


def _chunk_window_steps(chunks: list[dict[str, Any]], *, title: str, window_size: int) -> list[dict[str, Any]]:
    if not chunks:
        return []

    ordered = sorted(chunks, key=lambda c: int(c.get("chunk_index") or 0))
    size = max(1, min(3, int(window_size or 2)))
    steps: list[dict[str, Any]] = []
    for i in range(0, len(ordered), size):
        group = ordered[i:i + size]
        c0 = int(group[0].get("chunk_index") or 0)
        c1 = int(group[-1].get("chunk_index") or c0)
        steps.append({
            "ordinal": len(steps) + 1,
            "label": f"{title or 'Artifact'} · chunks {c0}–{c1}",
            "chunk_start": c0,
            "chunk_end": c1,
            "status": "pending",
        })
    return steps


def _should_fallback_to_chunk_windows(readiness, chunks: list[dict[str, Any]], candidate_steps: list[dict[str, Any]]) -> bool:
    if not chunks:
        return False
    if not candidate_steps:
        return True
    if len(candidate_steps) == 1 and len(chunks) > 1:
        sec = candidate_steps[0]
        kind = str(sec.get("section_kind") or "").strip().lower()
        label = str(sec.get("label") or "").strip().lower()
        c0 = int(sec.get("chunk_start") or 0)
        c1 = int(sec.get("chunk_end") or c0)
        first_idx = int(chunks[0].get("chunk_index") or 0)
        last_idx = int(chunks[-1].get("chunk_index") or first_idx)
        spans_all = c0 <= first_idx and c1 >= last_idx
        if kind == "outline_placeholder":
            return True
        if spans_all and ("structure inference pending" in label or getattr(readiness, "has_index", False)):
            return True
    return False


def _build_steps_from_readiness(
    artifact_id: str,
    *,
    strategy_payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None, str]:
    readiness = get_artifact_readiness(artifact_id)
    art, chunks = load_or_synthesize_artifact_chunks(artifact_id)
    title = ((art or {}).get("title") or (readiness.title if readiness else artifact_id)).strip() or artifact_id

    candidate_steps: list[dict[str, Any]] = []
    if readiness and readiness.index_sections:
        for idx, sec in enumerate(readiness.index_sections, start=1):
            c0 = sec.get("chunk_start")
            c1 = sec.get("chunk_end")
            if c0 is None or c1 is None:
                continue
            label = (sec.get("label") or sec.get("section_kind") or f"Section {idx}").strip()
            candidate_steps.append({
                "ordinal": int(sec.get("ordinal") or idx),
                "label": label,
                "chunk_start": int(c0),
                "chunk_end": int(c1),
                "status": "pending",
                "section_kind": sec.get("section_kind"),
            })

    if chunks and _should_fallback_to_chunk_windows(readiness, chunks, candidate_steps):
        window_size = _fallback_chunk_window_size(strategy_payload)
        return _chunk_window_steps(chunks, title=title, window_size=window_size), title, "chunk_windows"

    if candidate_steps:
        normalized_steps = []
        for step in candidate_steps:
            normalized_steps.append({
                "ordinal": int(step.get("ordinal") or len(normalized_steps) + 1),
                "label": str(step.get("label") or f"Section {len(normalized_steps) + 1}").strip(),
                "chunk_start": int(step.get("chunk_start") or 0),
                "chunk_end": int(step.get("chunk_end") or 0),
                "status": "pending",
            })
        return normalized_steps, title, "index_sections"

    if art and chunks:
        window_size = _fallback_chunk_window_size(strategy_payload)
        return _chunk_window_steps(chunks, title=title, window_size=window_size), title, "chunk_windows"

    return [], None, "none"


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

    readiness = get_artifact_readiness(artifact_id)
    if readiness and str(readiness.source_kind or "").strip().lower().startswith("reading_session:"):
        return ToolResult(
            ok=False,
            tool=TOOL_SPEC.name,
            error="reading-session-derived artifacts are not eligible for automatic reading sessions",
            display_text="Refusing to start a recursive reading session on a reading-session artifact.",
        )

    question_sets = load_reading_questions()
    strategy_payload = coerce_reading_strategy(
        strategy,
        source_kind=(readiness.source_kind if readiness else ""),
        title=((readiness.title if readiness else artifact_id) or artifact_id),
        user_text=ctx.user_text,
        available_modes=sorted(question_sets.keys()),
    )

    steps, title, step_source = _build_steps_from_readiness(
        artifact_id,
        strategy_payload=strategy_payload,
    )
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
        existing = update_artifact_reading_session(
            session_id,
            status="active",
            strategy_json=(strategy_payload if (strategy is not None or not existing.get("strategy_json")) else None),
        )
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
                "step_source": step_source,
            },
            display_text=f"Reusing reading session {session_id} for {title or artifact_id}.",
        )

    summary_so_far = None if restart or not existing else existing.get("summary_so_far")

    session = upsert_artifact_reading_session(
        conversation_id=conversation_id,
        artifact_id=artifact_id,
        mode=mode,
        status="active",
        strategy_json=strategy_payload,
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
            "step_source": step_source,
        },
        display_text=f"Prepared reading session {session_id} for {title or artifact_id} with {len(stored_steps)} steps.",
    )
