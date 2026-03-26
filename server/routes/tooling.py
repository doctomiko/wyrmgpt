import asyncio
from dataclasses import replace
from functools import partial
import hashlib
import json
import re
from datetime import datetime, timezone
import uuid
from typing import Any, Iterator

from server.api_helpers import RowDict, strip_zeitgeber_prefix
from server.db import (
    db_create_conversation_scaffold_event,
    db_get_conversation_project_id,
    db_list_conversation_scaffold_events_since,
    db_update_conversation_scaffold_event,
    reindex_artifact_by_id,
    retain_conversation_artifact_conn,
    upsert_artifact_text,
)
from server.db_helpers import db_session
from server.logging_helper import log_debug, log_info, log_warn
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.reading import maybe_capture_reading_notes_for_result
from server.tools.base import ToolExecutionContext, ToolInvocationRequest, ToolResult
from server.tools.registry import ToolRegistry

import server.runtime as runtime


_TOOL_BLOCK_FENCE_RE = re.compile(r"```tool\s*\{.*?\}\s*```", re.DOTALL | re.IGNORECASE)
_TOOL_TRIGGER_RE = re.compile(r"\b(read|reading|continue|section|chapter|page|passage|chunk|artifact|resume|next)\b", re.IGNORECASE)
_TRIVIAL_TOOL_WRAPPER_RE = re.compile(
    r"^(?:[\s\-–—:,.!]*|(?:okay|ok|sure|certainly|i(?:'ll| will)|let me|using|calling|requesting|fetching|loading)\b[\s\-–—:,.!]*)*$",
    re.IGNORECASE,
)


# region Tooling helpers

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _resolve_project_id(conversation_id: str) -> int | None:
    if not conversation_id:
        return None
    try:
        with db_session() as conn:
            return db_get_conversation_project_id(conn, conversation_id)
    except Exception as exc:
        log_warn(f"Tool execution could not resolve project for conversation {conversation_id}: {exc}")
        return None


def _tool_event_title(request: ToolInvocationRequest) -> str:
    return f"Scaffold · Tool call · {request.tool}"


def _tool_event_input_payload(request: ToolInvocationRequest) -> dict[str, Any]:
    return {"tool": request.tool, "arguments": dict(request.arguments or {})}


def _tool_event_start_body(request: ToolInvocationRequest) -> str:
    return f"Calling `{request.tool}`..."


def _tool_event_result_body(request: ToolInvocationRequest, result: ToolResult) -> str:
    lead = f"`{request.tool}` {'completed.' if result.ok else 'failed.'}"
    detail = (result.display_text or result.error or "").strip()
    if detail:
        return f"{lead}\n\n{detail}"
    return lead


def _default_retained_summary_text(request: ToolInvocationRequest, result: ToolResult) -> str:
    detail = (result.display_text or result.error or '').strip()
    if detail:
        return detail[:400]
    return f"Retained result from {request.tool}."


def _tool_result_retention_source_id(
    *,
    conversation_id: str,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> str:
    payload = {
        'conversation_id': conversation_id,
        'tool': request.tool,
        'arguments': dict(request.arguments or {}),
        'retained_title': result.retained_title,
        'retained_text': result.retained_text,
        'retained_summary_text': result.retained_summary_text,
        'retained_origin_kind': result.retained_origin_kind,
        'retained_state': result.retained_state,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    return f"{conversation_id}:{request.tool}:{digest[:24]}"


def _retain_tool_result_artifact(
    *,
    conversation_id: str,
    project_id: int | None,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> str | None:
    retain_flag = bool(result.retain_in_conversation) or bool((result.retained_text or '').strip())
    retained_text = (result.retained_text or '').strip()
    if not conversation_id or not retain_flag or not retained_text:
        return None

    retained_title = (result.retained_title or f"Retained Knowledge · {request.tool}").strip()
    retained_summary = (result.retained_summary_text or _default_retained_summary_text(request, result)).strip() or None
    origin_kind = (result.retained_origin_kind or 'tool_result').strip() or 'tool_result'
    retention_state = (result.retained_state or 'active').strip() or 'active'
    source_id = _tool_result_retention_source_id(
        conversation_id=conversation_id,
        request=request,
        result=result,
    )

    artifact_id: str | None = None
    with db_session() as conn:
        artifact_id = upsert_artifact_text(
            conn,
            source_kind='assistant_generated',
            source_id=source_id,
            title=retained_title,
            scope_type='conversation',
            scope_id=conversation_id,
            text=retained_text,
        )
        retain_conversation_artifact_conn(
            conn,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            origin_kind=origin_kind,
            retention_state=retention_state,
            carry_summary_text=retained_summary,
            inclusion_kind='whole',
            retrieval_channel='retained',
            message_id=None,
            note_text=f"Retained tool result from {request.tool} for conversation continuity",
            meta_json={
                'tool': request.tool,
                'arguments': dict(request.arguments or {}),
                'project_id': project_id,
                'retained_title': retained_title,
                'retained_summary_text': retained_summary,
                'tool_result_meta': result.retained_meta or {},
            },
            increment_include_count=False,
        )
    if artifact_id:
        try:
            reindex_artifact_by_id(artifact_id)
        except Exception as exc:
            log_warn('Retained tool artifact reindex failed aid=%s tool=%s: %s', artifact_id, request.tool, exc)
    return artifact_id


def _build_live_scaffold_row(
    *,
    event_id: int | str,
    conversation_id: str,
    request: ToolInvocationRequest,
    status: str,
    title: str,
    body_text: str,
    created_at: str,
    updated_at: str | None = None,
    output_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_event_id = int(event_id) if isinstance(event_id, int) or (isinstance(event_id, str) and event_id.isdigit()) else str(event_id)
    return {
        "id": row_event_id,
        "row_type": "scaffold_event",
        "conversation_id": conversation_id,
        "message_id": None,
        "event_kind": "tool_call",
        "status": status,
        "title": title,
        "body_text": body_text,
        "input_json": _tool_event_input_payload(request),
        "output_json": output_json,
        "created_at": created_at,
        "updated_at": updated_at or created_at,
    }


def _new_live_event_id(request: ToolInvocationRequest) -> str:
    slug = re.sub(r"[^a-z0-9_.-]+", "-", (request.tool or "tool").strip().lower()).strip("-") or "tool"
    return f"live:{slug}:{uuid.uuid4().hex[:10]}"


def _iter_additional_scaffold_rows(
    *,
    conversation_id: str,
    after_event_id: int,
    seen_event_ids: set[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    cursor = max(0, int(after_event_id or 0))
    rows = db_list_conversation_scaffold_events_since(conversation_id, after_event_id=cursor)
    out: list[dict[str, Any]] = []
    for row in rows:
        rid = int(row.get("id") or 0)
        if rid > cursor:
            cursor = rid
        if seen_event_ids is not None and rid in seen_event_ids:
            continue
        row["row_type"] = "scaffold_event"
        if seen_event_ids is not None:
            seen_event_ids.add(rid)
        out.append(row)
    return out, cursor


def _create_tool_event_start(
    *,
    conversation_id: str,
    request: ToolInvocationRequest,
) -> tuple[int | None, str, dict[str, Any]]:
    title = _tool_event_title(request)
    body_text = _tool_event_start_body(request)
    created_at = _utc_now_iso()
    persisted_event_id: int | None = None
    live_event_id = _new_live_event_id(request)
    try:
        persisted_event_id = int(db_create_conversation_scaffold_event(
            conversation_id=conversation_id,
            message_id=None,
            event_kind="tool_call",
            status="running",
            title=title,
            body_text=body_text,
            input_json=_tool_event_input_payload(request),
            output_json=None,
        ))
        live_event_id = str(persisted_event_id)
    except Exception as exc:
        log_warn(f"Tool scaffold start persistence failed for {request.tool}: {exc}")
    row = _build_live_scaffold_row(
        event_id=live_event_id,
        conversation_id=conversation_id,
        request=request,
        status="running",
        title=title,
        body_text=body_text,
        created_at=created_at,
    )
    return persisted_event_id, live_event_id, row


def _update_tool_event_result(
    *,
    conversation_id: str,
    live_event_id: int | str,
    persisted_event_id: int | None,
    request: ToolInvocationRequest,
    result: ToolResult,
    created_at: str | None,
) -> dict[str, Any]:
    status = "ok" if result.ok else "error"
    title = _tool_event_title(request)
    body_text = _tool_event_result_body(request, result)
    updated_at = _utc_now_iso()
    output_json = result.as_dict()
    if persisted_event_id is not None:
        try:
            db_update_conversation_scaffold_event(
                event_id=int(persisted_event_id),
                status=status,
                title=title,
                body_text=body_text,
                output_json=output_json,
            )
        except Exception as exc:
            log_warn(f"Tool scaffold result persistence failed for {request.tool}: {exc}")
    return _build_live_scaffold_row(
        event_id=live_event_id,
        conversation_id=conversation_id,
        request=request,
        status=status,
        title=title,
        body_text=body_text,
        created_at=created_at or updated_at,
        updated_at=updated_at,
        output_json=output_json,
    )


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


def iter_expand_input_with_tool_requests(
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
    request_options: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    del user_message_id  # reserved for future tool metadata, intentionally unused for now
    tools = tools or runtime.TOOL_REGISTRY
    if not _tooling_enabled(tool_cfg, tools):
        return_value = (list(base_input), initial_assistant_text, False, [])
        return return_value  # type: ignore[return-value]
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
    seen_event_ids: set[int] = set()
    scaffold_cursor = 0
    project_id = _resolve_project_id(conversation_id)
    exec_ctx = ToolExecutionContext(
        conversation_id=conversation_id,
        project_id=project_id,
        user_text=user_text,
    )

    while remaining_calls > 0:
        if pending_text is None:
            log_info(
                "Tool planner requesting assistant text cid=%s deployment=%s model=%s mode=complete",
                conversation_id,
                getattr(target, "id", ""),
                getattr(target, "model", ""),
            )
            print(
                f"[tool.planner] cid={conversation_id} deployment={getattr(target, 'id', '')} model={getattr(target, 'model', '')} mode=complete",
                flush=True,
            )
            result = provider.complete(target, working_input, request_options=request_options)
            pending_text = strip_zeitgeber_prefix(result.text or "")

        requests = tools.extract_requests_from_text(pending_text or "")
        if not response_requests_tool_execution(pending_text or "", tools):
            return_value = (working_input, pending_text, used_tools, event_ids)
            return return_value  # type: ignore[return-value]

        working_input.append({"role": "assistant", "content": pending_text or ""})
        allowed = requests[:remaining_calls]
        remaining_calls -= len(allowed)

        for request in allowed:
            persisted_event_id: int | None = None
            live_event_id: str | int = _new_live_event_id(request)
            created_at = None
            if conversation_id:
                persisted_event_id, live_event_id, start_row = _create_tool_event_start(
                    conversation_id=conversation_id,
                    request=request,
                )
                created_at = start_row.get("created_at")
                args_text = json.dumps(request.arguments or {}, ensure_ascii=False)
                log_info("Tool call start cid=%s tool=%s args=%s", conversation_id, request.tool, args_text)
                print(f"[tool.start] cid={conversation_id} tool={request.tool} args={args_text}", flush=True)
                yield start_row
                if persisted_event_id is not None:
                    event_ids.append(int(persisted_event_id))
                    seen_event_ids.add(int(persisted_event_id))
                    scaffold_cursor = max(scaffold_cursor, int(persisted_event_id))

            try:
                tool_result = tools.execute(request, ctx=exec_ctx)
                tool_result = maybe_capture_reading_notes_for_result(
                    target=target,
                    conversation_id=conversation_id,
                    user_text=user_text,
                    request=request,
                    result=tool_result,
                )
            except Exception as exc:
                log_warn("Tool call exception cid=%s tool=%s: %s", conversation_id, request.tool, exc)
                tool_result = ToolResult(
                    ok=False,
                    tool=request.tool,
                    error=f"{type(exc).__name__}: {exc}",
                )

            if conversation_id:
                retained_artifact_id: str | None = None
                try:
                    retained_artifact_id = _retain_tool_result_artifact(
                        conversation_id=conversation_id,
                        project_id=project_id,
                        request=request,
                        result=tool_result,
                    )
                except Exception as exc:
                    log_warn('Tool result retention failed cid=%s tool=%s: %s', conversation_id, request.tool, exc)
                if retained_artifact_id:
                    result_payload = dict(tool_result.result or {})
                    result_payload['retained_artifact_id'] = retained_artifact_id
                    tool_result = replace(tool_result, result=result_payload)
                    log_info('Tool result retained cid=%s tool=%s artifact_id=%s', conversation_id, request.tool, retained_artifact_id)
                done_row = _update_tool_event_result(
                    conversation_id=conversation_id,
                    live_event_id=live_event_id,
                    persisted_event_id=persisted_event_id,
                    request=request,
                    result=tool_result,
                    created_at=created_at,
                )
                log_info("Tool call done cid=%s tool=%s ok=%s", conversation_id, request.tool, tool_result.ok)
                print(f"[tool.done] cid={conversation_id} tool={request.tool} ok={tool_result.ok}", flush=True)
                yield done_row
                if persisted_event_id is not None:
                    seen_event_ids.add(int(persisted_event_id))
                    scaffold_cursor = max(scaffold_cursor, int(persisted_event_id))
                extra_rows, scaffold_cursor = _iter_additional_scaffold_rows(
                    conversation_id=conversation_id,
                    after_event_id=scaffold_cursor,
                    seen_event_ids=seen_event_ids,
                )
                for extra_row in extra_rows:
                    log_debug("Scaffold relay cid=%s kind=%s event_id=%s", conversation_id, extra_row.get("event_kind"), extra_row.get("id"))
                    yield extra_row

            working_input.append(_tool_result_to_input_message(tool_result))
            used_tools = True

        pending_text = None

    return_value = (working_input, None, used_tools, event_ids)
    return return_value  # type: ignore[return-value]


def expand_input_with_tool_requests(**kwargs):
    iterator = iter_expand_input_with_tool_requests(**kwargs)
    while True:
        try:
            next(iterator)
        except StopIteration as stop:
            return stop.value


async def expand_input_with_tool_requests_async(**kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(expand_input_with_tool_requests, **kwargs)
    return await loop.run_in_executor(None, fn)


# endregion
