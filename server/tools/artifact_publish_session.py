from __future__ import annotations

import json
from typing import Any

from ..db import (
    db_session,
    get_artifact_by_id,
    get_artifact_reading_session,
    get_conversation_project_id,
    list_artifact_reading_steps,
    reindex_artifact_by_id,
    retain_conversation_artifact_conn,
    upsert_artifact_text,
)
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.publish_session",
    description="Create a durable artifact from a reading session as a recap or transcript-style journal.",
    input_schema={"type": "object"},
    system_usage="Use when the user wants to preserve a reading session as a durable artifact.",
    display_name="Publish Reading Session",
    tags=("artifact", "reading", "session", "publish"),
)


def _json_pretty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value).strip()


def _build_session_markdown(*, session: dict[str, Any], steps: list[dict[str, Any]], source_artifact: dict[str, Any] | None, publish_kind: str) -> tuple[str, str]:
    source_title = (source_artifact or {}).get("title") or session.get("artifact_id") or "Artifact"
    source_kind = (source_artifact or {}).get("source_kind") or ""
    session_id = int(session.get("id") or 0)
    step_count = len(steps)
    done_count = sum(1 for s in steps if str(s.get("status") or "").strip().lower() == "done")
    modes = []
    try:
        strategy = json.loads(str(session.get("strategy_json") or "").strip() or "{}")
        modes = list(strategy.get("modes") or []) if isinstance(strategy, dict) else []
    except Exception:
        modes = []

    if publish_kind == "reading_recap":
        title = f"Reading Recap — {source_title}"
    else:
        title = f"Reading Journal Transcript — {source_title}"

    lines = [
        f"# {title}",
        "",
        f"Source artifact: `{session.get('artifact_id')}`",
        f"Source title: {source_title}",
        f"Source kind: {source_kind}",
        f"Session ID: {session_id}",
        f"Conversation ID: {session.get('conversation_id')}",
        f"Mode: {(session.get('mode') or 'reading')}",
        f"Status: {(session.get('status') or 'active')}",
        f"Created at: {(session.get('created_at') or '')}",
        f"Updated at: {(session.get('updated_at') or '')}",
        f"Progress: {done_count}/{step_count} steps complete",
    ]
    if modes:
        lines.append(f"Modes: {', '.join(str(m) for m in modes)}")
    lines.extend(["", "## Running Summary", "", (str(session.get("summary_so_far") or "").strip() or "(none)")])

    if publish_kind == "reading_recap":
        lines.extend(["", "## Section Highlights", ""])
        for step in steps:
            ordinal = int(step.get("ordinal") or 0)
            label = (step.get("label") or f"Section {ordinal}").strip()
            notes_text = _json_pretty(step.get("notes")) or "(no notes)"
            if len(notes_text) > 1200:
                notes_text = notes_text[:1197].rstrip() + "..."
            lines.extend([
                f"### {ordinal}. {label}",
                "",
                f"Chunks: {int(step.get('chunk_start') or 0)}–{int(step.get('chunk_end') or 0)}",
                f"Status: {(step.get('status') or 'pending')}",
                "",
                notes_text,
                "",
            ])
    else:
        lines.extend(["", "## Session Turn Transcript", ""])
        for step in steps:
            ordinal = int(step.get("ordinal") or 0)
            label = (step.get("label") or f"Section {ordinal}").strip()
            notes_text = _json_pretty(step.get("notes")) or "(no notes captured)"
            lines.extend([
                f"### Turn {ordinal} — {label}",
                "",
                f"Chunk window: {int(step.get('chunk_start') or 0)}–{int(step.get('chunk_end') or 0)}",
                f"Step status: {(step.get('status') or 'pending')}",
                "",
                "```json" if notes_text.startswith("{") or notes_text.startswith("[") else "```text",
                notes_text,
                "```",
                "",
            ])

    return title, "\n".join(lines).strip() + "\n"


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    session_id = int(arguments.get("session_id") or 0)
    if session_id <= 0:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="session_id is required")

    publish_kind = str(arguments.get("publish_kind") or "reading_journal_transcript").strip() or "reading_journal_transcript"
    if publish_kind not in {"reading_recap", "reading_journal_transcript"}:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"unsupported publish_kind: {publish_kind}")

    session = get_artifact_reading_session(session_id)
    if not session:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"reading session not found: {session_id}")

    steps = list_artifact_reading_steps(session_id)
    source_artifact = get_artifact_by_id(str(session.get("artifact_id") or ""), hydrate=False)
    if source_artifact and str(source_artifact.get("source_kind") or "").strip().lower().startswith("reading_session:"):
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="cannot publish a reading session from a reading-session-derived artifact")

    title_override = str(arguments.get("title") or "").strip()
    retain_in_conversation = bool(arguments.get("retain_in_conversation", True))
    scope_type = str(arguments.get("scope_type") or "conversation").strip().lower() or "conversation"
    if scope_type not in {"conversation", "project", "global"}:
        scope_type = "conversation"

    conversation_id = str(session.get("conversation_id") or ctx.conversation_id or "").strip()
    source_title, markdown_text = _build_session_markdown(
        session=session,
        steps=steps,
        source_artifact=source_artifact,
        publish_kind=publish_kind,
    )
    title = title_override or source_title
    source_id = f"session:{session_id}:{publish_kind}"
    source_kind = f"reading_session:{publish_kind}"

    artifact_id = None
    scope_id = None
    with db_session() as conn:
        if scope_type == "conversation":
            scope_id = conversation_id or None
        elif scope_type == "project":
            scope_id = get_conversation_project_id(conn, conversation_id) if conversation_id else None
            if scope_id is None:
                scope_type = "global"
        artifact_id = upsert_artifact_text(
            conn=conn,
            source_kind=source_kind,
            source_id=source_id,
            title=title,
            scope_type=scope_type,
            scope_id=scope_id,
            text=markdown_text,
        )
        if retain_in_conversation and conversation_id:
            retain_conversation_artifact_conn(
                conn,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                origin_kind="reading_session_publish",
                retention_state="forced",
                carry_summary_text=None,
                inclusion_kind="whole",
                retrieval_channel="manual",
                message_id=None,
                note_text=f"Published reading session {session_id} as {publish_kind}",
                meta_json={"session_id": session_id, "publish_kind": publish_kind},
                increment_include_count=True,
            )
    reindex_info = reindex_artifact_by_id(artifact_id)
    published_artifact = get_artifact_by_id(artifact_id, hydrate=False) or {"id": artifact_id, "title": title}

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "artifact_id": artifact_id,
            "artifact": published_artifact,
            "session_id": session_id,
            "publish_kind": publish_kind,
            "scope_type": scope_type,
            "scope_id": scope_id,
            "retain_in_conversation": retain_in_conversation,
            "reindex": reindex_info,
            "step_count": len(steps),
        },
        display_text=f"Published reading session {session_id} as artifact {artifact_id} ({publish_kind}).",
        event_kind="tool_result",
    )
