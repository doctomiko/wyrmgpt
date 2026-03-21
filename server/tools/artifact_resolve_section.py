from __future__ import annotations

from typing import Any

from .artifact_helpers import resolve_artifact_section_reference
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="artifact.resolve_section",
    description="Resolve a user-facing section reference to a concrete artifact chunk range.",
    input_schema={"type": "object"},
    system_usage="Use when you need an exact section range before reading.",
    display_name="Resolve Artifact Section",
    tags=("artifact", "reading", "navigation"),
)


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    artifact_id = str(arguments.get("artifact_id") or "").strip()
    section_ref = str(arguments.get("section_ref") or "").strip()
    max_candidates = int(arguments.get("max_candidates") or 5)
    resolved = resolve_artifact_section_reference(artifact_id, section_ref, max_candidates=max_candidates)

    if not resolved.get("ok"):
        return ToolResult(
            ok=False,
            tool=TOOL_SPEC.name,
            error=str(resolved.get("error") or "section not found"),
            result=resolved,
            display_text=f"Could not resolve {section_ref!r} in artifact {artifact_id}.",
        )

    matched = resolved.get("matched") or {}
    label = matched.get("label") or f"Section {matched.get('ordinal') or '?'}"
    c0 = matched.get("chunk_start")
    c1 = matched.get("chunk_end")
    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result=resolved,
        display_text=f"Resolved {section_ref!r} to {label} (chunks {c0}–{c1}).",
    )
