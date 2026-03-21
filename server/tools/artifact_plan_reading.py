from __future__ import annotations

from typing import Any

from ..artifact_reading_planner import (
    format_index_message,
    format_planner_note_message,
    format_summary_message,
    get_artifact_readiness,
    plan_artifact_inclusion,
)
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.plan_reading",
    description="Inspect an artifact and return whether it should be included whole or via summary/index fallback for the current reading budget.",
    input_schema={"type": "object"},
    system_usage="Use when the user explicitly asks for a reading plan or wants to inspect the fallback strategy before reading.",
    display_name="Plan Artifact Reading",
    tags=("artifact", "reading", "planner"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    if not artifact_id:
        return ToolResult(
            ok=False,
            tool=TOOL_SPEC.name,
            error="artifact_id is required",
            display_text="Reading plan failed: artifact_id is required.",
        )

    readiness = get_artifact_readiness(artifact_id)
    if not readiness:
        return ToolResult(
            ok=False,
            tool=TOOL_SPEC.name,
            error="artifact not found",
            display_text=f"Reading plan failed: artifact {artifact_id} was not found.",
        )

    user_text = str(arguments.get("user_text") or ctx.user_text or "").strip()
    budget_remaining_chars = int(arguments.get("budget_remaining_chars") or 12000)
    whole_artifact_soft_cap_chars = int(arguments.get("whole_artifact_soft_cap_chars") or 12000)

    plan = plan_artifact_inclusion(
        user_text=user_text,
        readiness=readiness,
        budget_remaining_chars=budget_remaining_chars,
        whole_artifact_soft_cap_chars=whole_artifact_soft_cap_chars,
    )

    summary_msg = format_summary_message(readiness)
    index_msg = format_index_message(readiness)
    planner_msg = format_planner_note_message(plan)

    result = {
        "artifact_id": readiness.artifact_id,
        "title": readiness.title,
        "source_kind": readiness.source_kind,
        "content_chars": readiness.content_chars,
        "estimated_message_chars": readiness.estimated_message_chars,
        "has_summary": readiness.has_summary,
        "has_index": readiness.has_index,
        "index_sections": list(readiness.index_sections or []),
        "plan": plan,
        "messages": {
            "summary": summary_msg,
            "index": index_msg,
            "planner": planner_msg,
        },
    }

    action = str(plan.get("action") or "fallback_derivatives")
    if action == "include_whole":
        display_text = f"Reading plan: {readiness.title} fits whole-context inclusion right now."
    else:
        display_text = f"Reading plan: {readiness.title} should use summary/index fallback before sequential reading."

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result=result,
        display_text=display_text,
        event_kind="artifact_reading_plan",
    )
