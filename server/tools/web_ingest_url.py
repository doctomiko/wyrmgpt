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
        user_text=url,
        raw_message=url,
        max_urls=1,
        fetch_method="python",
        request_message_id=None,
    )
    artifact_ids = list(ingest.get("artifact_ids") or [])
    ok = bool(ingest.get("ok")) and bool(artifact_ids)
    return ToolResult(
        ok=ok,
        tool=TOOL_SPEC.name,
        result={
            "url": url,
            "conversation_id": conversation_id,
            "ingest": ingest,
            "artifact_id": artifact_ids[0] if artifact_ids else None,
        },
        error=None if ok else ("URL ingest failed" if not ingest.get("errors") else "; ".join(str(e) for e in ingest.get("errors") or [])),
        display_text=(
            f"Fetched and ingested {url} as artifact {artifact_ids[0]}."
            if ok else f"Failed to ingest {url}."
        ),
        event_kind="tool_result",
    )
