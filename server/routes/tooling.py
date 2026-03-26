import asyncio
from functools import partial
import json
import re
from typing import Any

from server.api_helpers import RowDict, postprocess_text, strip_zeitgeber_prefix, attach_scaffold_events_to_message
from server.api_models import ChatRequest
from server.config import load_tool_config
from server.context import build_context, build_model_input
from server.db import db_create_conversation, db_add_message, db_create_conversation_scaffold_event, db_ensure_files_artifacted_for_conversation, db_get_conversation_project_id
from server.db_helpers import db_session
from server.logging_helper import log_warn
from server.providers.openai_provider import ProviderExecutionError
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.library import persist_citations_for_assistant_message
from server.routes.reading import maybe_capture_reading_notes_for_result
from server.tools.base import ToolExecutionContext, ToolInvocationRequest, ToolResult
from server.tools.registry import ToolRegistry
from server.web_ingest import ingest_urls_from_user_message

import server.runtime as runtime
from server.routes.base import app


_TOOL_BLOCK_FENCE_RE = re.compile(r"```tool\s*\{.*?\}\s*```", re.DOTALL | re.IGNORECASE)
_TOOL_TRIGGER_RE = re.compile(r"\b(read|reading|continue|section|chapter|page|passage|chunk|artifact|resume|next)\b", re.IGNORECASE)
_TRIVIAL_TOOL_WRAPPER_RE = re.compile(
    r"^(?:[\s\-–—:,.!]*|(?:okay|ok|sure|certainly|i(?:'ll| will)|let me|using|calling|requesting|fetching|loading)\b[\s\-–—:,.!]*)*$",
    re.IGNORECASE,
)

# region Tooling helpers

def _tooling_enabled(tool_cfg, tool_registry) -> bool:
    return bool(
        tool_cfg
        and tool_cfg.enabled
        and tool_cfg.allow_assistant_tool_blocks
        and tool_registry is not None
        and tool_registry.list_enabled()
    )


def _tool_text_without_blocks(text: str) -> str:
    return _TOOL_BLOCK_FENCE_RE.sub("", text or "").strip()


def tool_wrapper_text(text: str) -> str:
    return _tool_text_without_blocks(text or "")


def _tool_remainder_is_trivial(text: str) -> bool:
    remainder = tool_wrapper_text(text or "")
    if not remainder:
        return True
    if len(remainder) <= 80 and _TRIVIAL_TOOL_WRAPPER_RE.match(remainder):
        return True
    return False


def response_requests_tool_execution(text: str, tool_registry: ToolRegistry | None) -> bool:
    if not tool_registry:
        return False
    requests = tool_registry.extract_requests_from_text(text or "")
    if not requests:
        return False
    remainder = tool_wrapper_text(text or "")
    if not remainder:
        return True
    if len(remainder) <= 400:
        return True
    return _tool_remainder_is_trivial(text or "")


def _is_tool_prompt_message(msg: dict[str, Any]) -> bool:
    if (msg.get("role") or "") != "system":
        return False
    content = msg.get("content")
    return isinstance(content, str) and content.lstrip().startswith("TOOL USE")


def remove_tool_prompt_messages(model_input: ModelInput) -> ModelInput:
    return [msg for msg in model_input if not _is_tool_prompt_message(msg)]


def _tool_result_to_input_message(result: ToolResult) -> dict[str, Any]:
    payload = {
        "ok": result.ok,
        "tool": result.tool,
        "result": result.result,
        "error": result.error,
    }
    body = [
        "TOOL RESULT",
        f"Tool: {result.tool}",
        f"OK: {'true' if result.ok else 'false'}",
        "",
        "JSON:",
        json.dumps(payload, ensure_ascii=False, indent=2),
    ]
    return {"role": "user", "content": "\n".join(body).strip()}


def _persist_tool_event(
    *,
    conversation_id: str,
    message_id: int | None,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> int | None:
    try:
        body_lines = [
            f"Tool: {request.tool}",
            f"Status: {'ok' if result.ok else 'error'}",
        ]
        if result.display_text:
            body_lines.extend(["", result.display_text.strip()])
        elif result.error:
            body_lines.extend(["", result.error.strip()])
        return db_create_conversation_scaffold_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_kind=result.event_kind or "tool_result",
            status="ready" if result.ok else "error",
            title=f"Tool · {request.tool}",
            body_text="\n".join(body_lines).strip(),
            input_json={"tool": request.tool, "arguments": request.arguments},
            output_json=result.as_dict(),
        )
    except Exception as exc:
        log_warn(f"Tool scaffold event persistence failed for {request.tool}: {exc}")
        return None


def _execute_tool_requests(
    *,
    target,
    tool_registry: ToolRegistry,
    conversation_id: str,
    user_text: str,
    requests: list[ToolInvocationRequest],
) -> tuple[list[ToolResult], list[int]]:
    project_id = None
    if conversation_id:
        try:
            with db_session() as conn:
                project_id = db_get_conversation_project_id(conn, conversation_id)
        except Exception as exc:
            log_warn(f"Tool execution could not resolve project for conversation {conversation_id}: {exc}")

    exec_ctx = ToolExecutionContext(
        conversation_id=conversation_id,
        project_id=project_id,
        user_text=user_text,
    )
    out: list[ToolResult] = []
    event_ids: list[int] = []
    for request in requests:
        try:
            result = tool_registry.execute(request, ctx=exec_ctx)
            result = maybe_capture_reading_notes_for_result(
                target=target,
                conversation_id=conversation_id,
                user_text=user_text,
                request=request,
                result=result,
            )
        except Exception as exc:
            result = ToolResult(
                ok=False,
                tool=request.tool,
                error=f"{type(exc).__name__}: {exc}",
            )
        event_id = _persist_tool_event(
            conversation_id=conversation_id,
            message_id=None,
            request=request,
            result=result,
        )
        if event_id:
            event_ids.append(int(event_id))
        out.append(result)
    return out, event_ids


def should_attempt_tool_preflight(
    *,
    user_text: str,
    ctx: RowDict | None,
    tool_cfg,
    tool_registry: ToolRegistry | None,
) -> bool:
    if not _tooling_enabled(tool_cfg, tool_registry):
        return False

    if _TOOL_TRIGGER_RE.search(user_text or ""):
        return True

    for msg in (ctx or {}).get("whole_artifact_messages") or []:
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        first = (content.splitlines() or [""])[0].strip()
        if first in {"ARTIFACT READING PLAN", "ARTIFACT INDEX", "ARTIFACT SUMMARY"}:
            return True
    return False


def expand_input_with_tool_requests(
    *,
    target,
    base_input: ModelInput,
    conversation_id: str,
    user_text: str,
    tool_cfg,
    tools: ToolRegistry | None = None,
    providers: ProviderRegistry | None = None,
    user_message_id: int | None = None,
    initial_assistant_text: str | None = None,
) -> tuple[ModelInput, str | None, bool, list[int]]:
    tools = tools or runtime.TOOL_REGISTRY
    if not _tooling_enabled(tool_cfg, tools):
        return list(base_input), initial_assistant_text, False, []
    assert tools is not None
    providers = providers or runtime.PROVIDER_REGISTRY
    if providers is None:
        raise RuntimeError("Provider registry is not initialized.")

    provider = providers.get_chat_provider(target)
    working_input: ModelInput = list(base_input)
    remaining_calls = max(1, int(tool_cfg.max_calls_per_message))
    used_tools = False
    pending_text = initial_assistant_text
    event_ids: list[int] = []

    while remaining_calls > 0:
        if pending_text is None:
            result = provider.complete(target, working_input)
            pending_text = strip_zeitgeber_prefix(result.text or "")

        requests = tools.extract_requests_from_text(pending_text or "")
        if not response_requests_tool_execution(pending_text or "", tools):
            return working_input, pending_text, used_tools, event_ids

        working_input.append({"role": "assistant", "content": pending_text or ""})
        allowed = requests[:remaining_calls]
        remaining_calls -= len(allowed)
        tool_results, new_event_ids = _execute_tool_requests(
            target=target,
            tool_registry=tools,
            conversation_id=conversation_id,
            user_text=user_text,
            requests=allowed,
        )
        event_ids.extend(new_event_ids)
        for result in tool_results:
            working_input.append(_tool_result_to_input_message(result))

        used_tools = True
        pending_text = None

    return working_input, None, used_tools, event_ids


async def expand_input_with_tool_requests_async(**kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(expand_input_with_tool_requests, **kwargs)
    return await loop.run_in_executor(None, fn)


# endregion