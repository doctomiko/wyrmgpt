from __future__ import annotations

from typing import Any

from ..web_ingest import ingest_urls_from_user_message
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="web.ingest_url",
    description="Fetch and ingest a specific web URL into the current conversation as an artifact.",
    input_schema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {
                "type": "string",
                "minLength": 8,
                "description": "The absolute web URL to fetch and ingest.",
            },
            "conversation_id": {
                "type": "string",
                "minLength": 1,
                "description": "Optional; defaults to the current conversation.",
            },
        },
        "additionalProperties": False,
    },
    system_usage="Use when the assistant wants to fetch a specific URL and turn it into a retained web artifact.",
    display_name="Fetch Web URL",
    tags=("web", "artifact", "ingest"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    url = str(arguments.get("url") or "").strip()
    conversation_id = str(arguments.get("conversation_id") or ctx.conversation_id or "").strip()
    if not url:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="url is required")
    if not conversation_id:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="conversation_id is required")

    ingest = ingest_urls_from_user_message(
        conversation_id=conversation_id,
        request_message_id=None,
        raw_message=url,
        max_urls=1,
        fetch_method="python",
    )

    artifact_ids = list(ingest.get("artifact_ids") or [])
    warnings = [str(e) for e in (ingest.get("errors") or []) if str(e).strip()]
    artifact_id = artifact_ids[0] if artifact_ids else None

    # Treat successful artifact creation as success, even if a later
    # step (like reindexing) emitted warnings.
    warnings = [str(e) for e in (ingest.get("errors") or []) if str(e).strip()]
    artifact_id = artifact_ids[0] if artifact_ids else None

    # Treat successful artifact creation as success, even if a later
    # step (like reindexing) emitted warnings.
    ok = bool(artifact_id)

    error_text = None
    if not ok:
        if warnings:
            error_text = "; ".join(warnings)
        else:
            error_text = "URL ingest produced no artifact"

    display_text = f"Fetched and ingested {url} as artifact {artifact_id}."
    if ok and warnings:
        display_text += f" Warnings: {'; '.join(warnings)}"
    elif not ok:
        display_text = f"Failed to ingest {url}."

    error_text = None
    if not ok:
        if warnings:
            error_text = "; ".join(warnings)
        else:
            error_text = "URL ingest produced no artifact"

    display_text = f"Fetched and ingested {url} as artifact {artifact_id}."
    if ok and warnings:
        display_text += f" Warnings: {'; '.join(warnings)}"
    elif not ok:
        display_text = f"Failed to ingest {url}."

    return ToolResult(
        ok=ok,
        tool=TOOL_SPEC.name,
        result={
            "url": url,
            "conversation_id": conversation_id,
            "ingest": ingest,
            "artifact_id": artifact_id,
            "warnings": warnings,
        },
        error=error_text,
        display_text=display_text,
        event_kind="tool_result",
    )
