from __future__ import annotations

from typing import Any

from ..db import db_session, list_artifact_reading_sessions, list_artifact_reading_steps
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.list_sessions",
    description="Enumerate reading sessions filtered by artifact, title, conversation, or date range.",
    input_schema={"type": "object"},
    system_usage="Use when the user wants to find existing reading sessions by artifact, title, conversation, or date range.",
    display_name="List Artifact Reading Sessions",
    tags=("artifact", "reading", "session", "listing"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    conversation_id = str(arguments.get("conversation_id") or "").strip() or None
    artifact_id = str(arguments.get("artifact_id") or "").strip() or None
    title_query = str(arguments.get("title_query") or "").strip() or None
    created_after = str(arguments.get("created_after") or "").strip() or None
    created_before = str(arguments.get("created_before") or "").strip() or None
    include_complete = bool(arguments.get("include_complete", True))
    limit = max(1, min(int(arguments.get("limit") or 20), 100))
    project_id = arguments.get("project_id")
    if project_id not in (None, ""):
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            project_id = None
    else:
        project_id = None

    # Default to project-wide search when the current conversation belongs to a
    # real project; otherwise fall back to the current conversation.
    if conversation_id is None and project_id is None and ctx.conversation_id:
        try:
            with db_session() as conn:
                row = conn.execute(
                    "SELECT project_id FROM conversations WHERE id = ?",
                    (ctx.conversation_id,),
                ).fetchone()
                explicit_project_id = int(row["project_id"]) if row and row["project_id"] not in (None, "") else None
        except Exception:
            explicit_project_id = None
        if explicit_project_id is not None:
            project_id = explicit_project_id
        else:
            conversation_id = str(ctx.conversation_id).strip() or None

    rows = list_artifact_reading_sessions(
        conversation_id=conversation_id,
        project_id=project_id,
        artifact_id=artifact_id,
        title_query=title_query,
        created_after=created_after,
        created_before=created_before,
        include_complete=include_complete,
        limit=limit,
    )

    sessions: list[dict[str, Any]] = []
    for row in rows:
        session_id = int(row.get("id") or 0)
        steps = list_artifact_reading_steps(session_id)
        done_count = sum(1 for s in steps if str(s.get("status") or "").strip().lower() == "done")
        next_step = next(
            (
                s for s in steps
                if str(s.get("status") or "").strip().lower() in {"pending", "active"}
                and int(s.get("ordinal") or 0) > int(row.get("current_section_ordinal") or 0)
            ),
            None,
        )
        sessions.append({
            "id": session_id,
            "conversation_id": row.get("conversation_id"),
            "artifact_id": row.get("artifact_id"),
            "artifact_title": row.get("artifact_title") or row.get("artifact_id"),
            "artifact_source_kind": row.get("artifact_source_kind") or "",
            "mode": row.get("mode") or "reading",
            "status": row.get("status") or "active",
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "current_section_ordinal": row.get("current_section_ordinal"),
            "summary_so_far": row.get("summary_so_far") or "",
            "step_count": len(steps),
            "done_count": done_count,
            "next_step": {
                "ordinal": int(next_step.get("ordinal") or 0),
                "label": (next_step.get("label") or "").strip(),
                "chunk_start": int(next_step.get("chunk_start") or 0),
                "chunk_end": int(next_step.get("chunk_end") or 0),
            } if next_step else None,
        })

    display = f"Found {len(sessions)} reading session(s)."
    if artifact_id:
        display = f"Found {len(sessions)} reading session(s) for artifact {artifact_id}."
    elif title_query:
        display = f"Found {len(sessions)} reading session(s) matching title '{title_query}'."

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "count": len(sessions),
            "filters": {
                "project_id": project_id,
                "conversation_id": conversation_id,
                "artifact_id": artifact_id,
                "title_query": title_query,
                "created_after": created_after,
                "created_before": created_before,
                "include_complete": include_complete,
                "limit": limit,
            },
            "sessions": sessions,
        },
        display_text=display,
        event_kind="tool_result",
    )
