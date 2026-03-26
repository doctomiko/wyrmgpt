from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    system_usage: str = ""
    display_name: str = ""
    enabled: bool = True
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolInvocationRequest:
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionContext:
    conversation_id: str | None = None
    project_id: int | None = None
    user_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    tool: str
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    display_text: str = ""
    event_kind: str = "tool_result"
    retain_in_conversation: bool = False
    retained_title: str = ""
    retained_text: str = ""
    retained_summary_text: str = ""
    retained_origin_kind: str = "tool_result"
    retained_state: str = "active"
    retained_meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "result": self.result,
            "error": self.error,
            "display_text": self.display_text,
            "event_kind": self.event_kind,
            "retain_in_conversation": self.retain_in_conversation,
            "retained_title": self.retained_title,
            "retained_summary_text": self.retained_summary_text,
            "retained_origin_kind": self.retained_origin_kind,
            "retained_state": self.retained_state,
            "retained_meta": self.retained_meta,
        }
