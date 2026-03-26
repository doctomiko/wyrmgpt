from __future__ import annotations

from typing import Any

from ..db import db_add_memory
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="memory.create",
    description="Create a durable memory at project or global scope from information worth remembering later.",
    input_schema={"type": "object"},
    system_usage="Use when the assistant wants to save a durable project or global memory from the current conversation for later retrieval. Prefer project scope when the memory is specific to this project; otherwise use global.",
    display_name="Create Memory",
    tags=("memory", "corpus", "persistence"),
)


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",")]
        return [p for p in parts if p]
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                out.append(text)
        return out
    text = str(value).strip()
    return [text] if text else []


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    content = str(arguments.get("content") or "").strip()
    if not content:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="content is required")

    requested_scope = str(arguments.get("scope_type") or "").strip().lower()
    if requested_scope not in {"project", "global"}:
        requested_scope = "project" if ctx.project_id is not None else "global"

    scope_id = arguments.get("scope_id")
    if requested_scope == "project":
        try:
            scope_id = int(scope_id) if scope_id is not None else int(ctx.project_id) if ctx.project_id is not None else None
        except Exception:
            scope_id = None
        if scope_id is None:
            requested_scope = "global"

    importance = int(arguments.get("importance") or 50)
    importance = max(0, min(importance, 100))
    tags = _normalize_tags(arguments.get("tags"))
    origin_kind = str(arguments.get("origin_kind") or "assistant_tool").strip() or "assistant_tool"

    mem = db_add_memory(
        content=content,
        importance=importance,
        tags=tags,
        created_by="assistant",
        origin_kind=origin_kind,
        source_conversation_id=ctx.conversation_id,
        scope_type=requested_scope,
        scope_id=scope_id,
    )

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "memory": mem,
            "memory_id": mem.get("id"),
            "artifact_id": mem.get("artifact_id"),
            "scope_type": mem.get("scope_type"),
            "scope_id": mem.get("scope_id"),
        },
        display_text=f"Created {mem.get('scope_type')} memory {mem.get('id')} and artifact {mem.get('artifact_id')}.",
        event_kind="tool_result",
    )
