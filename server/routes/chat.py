import asyncio
from functools import partial
import json
import traceback
import uuid
import re

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from server.api_helpers import (
    RowDict,
    attach_scaffold_events_to_message,
    coerce_optional_float,
    coerce_optional_int,
    postprocess_text,
    sleep_ms,
    strip_zeitgeber_prefix,
    trim_history,
)
from server.api_models import ABCanonicalRequest, ABChatRequest, ChatRequest, NewChatResponse
from server.config import load_tool_config
from server.context import build_context, build_model_input
from server.db import (
    db_add_message,
    db_create_conversation,
    db_create_conversation_scaffold_event,
    db_ensure_files_artifacted_for_conversation,
    db_get_latest_conversation_scaffold_event_id,
    db_list_conversation_scaffold_events_since,
    db_update_ab_canonical,
    db_update_conversation_scaffold_event,
)
from server.logging_helper import log_debug, log_error, log_info, log_warn
from server.providers.openai_provider import ProviderExecutionError, extract_error_message
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.base import app, get_effective_model_settings
from server.routes.files import strip_file_messages, strip_images
from server.routes.library import persist_citations_for_assistant_message
from server.routes.tooling import (
    iter_expand_input_with_tool_requests,
    remove_tool_prompt_messages,
    response_requests_tool_execution,
    should_attempt_tool_preflight,
    tool_wrapper_text,
)
from server.tools.registry import ToolRegistry
from server.web_ingest import ingest_urls_from_user_message
import server.runtime as runtime


# region Chat Model helpers

async def _call_model(
    target,
    model_input,
    providers: ProviderRegistry | None = None,
    request_options: dict | None = None,
):
    providers = providers or runtime.PROVIDER_REGISTRY
    if providers is None:
        raise RuntimeError("Provider registry is not initialized.")

    provider = providers.get_chat_provider(target)
    loop = asyncio.get_running_loop()
    fn = partial(provider.complete, target, model_input, request_options=request_options)
    return await loop.run_in_executor(None, fn)


async def call_model_with_recovery(target, model_input: ModelInput, request_options: dict | None = None) -> RowDict:
    """
    Returns either {"ok": True, "text": "..."} or {"ok": False, "error": {...}}.
    """
    attempts: list[tuple[str, ModelInput, int]] = []

    attempts.append(("original", model_input, 0))
    attempts.append(("original_retry", model_input, 250))

    mi_noimg = strip_images(model_input)
    attempts.append(("no_images", mi_noimg, 0))
    attempts.append(("no_images_retry", mi_noimg, 250))

    mi_textonly = strip_file_messages(mi_noimg)
    attempts.append(("text_only", mi_textonly, 0))

    mi_trim = trim_history(mi_textonly, keep_last_n=30)
    attempts.append(("trim30", mi_trim, 0))

    last_err_payload = None

    for label, mi, backoff_ms in attempts:
        if backoff_ms:
            await sleep_ms(backoff_ms)

        try:
            result = await _call_model(target, mi, request_options=request_options)
            text = strip_zeitgeber_prefix(result.text or "")
            return {"ok": True, "text": text, "recovery": label}
        except ProviderExecutionError as e:
            payload = dict(e.payload or {})
            payload["recovery_step"] = label
            last_err_payload = payload

            if payload.get("status_code") and int(payload["status_code"]) < 500:
                return {"ok": False, "error": last_err_payload}

    return {"ok": False, "error": last_err_payload or {"status_code": 500, "body": {"error": {"message": "Unknown error"}}}}


def _generic_error_payload(exc: Exception) -> RowDict:
    return {
        "status_code": None,
        "request_id": None,
        "body": {
            "message": str(exc) or repr(exc),
        },
        "provider_error_type": type(exc).__name__,
    }


def _store_single_error_message(
    *,
    conversation_id: str,
    target,
    payload: RowDict,
    pending_tool_event_ids: list[int],
) -> None:
    msg = extract_error_message(payload)
    status = payload.get("status_code")
    bubble = f"[Model error] {status or ''} {msg}".strip()
    full = postprocess_text(bubble)
    if not full:
        return

    assistant_message_id = db_add_message(
        conversation_id,
        "assistant",
        full,
        meta={
            "model": target.model,
            "provider": target.provider_id,
            "deployment_id": target.id,
            "kind": "error",
            **payload,
        },
    )
    attach_scaffold_events_to_message(pending_tool_event_ids, assistant_message_id)


def _store_partial_single_message(
    *,
    conversation_id: str,
    target,
    text: str,
    model_settings: dict[str, object] | None,
    pending_tool_event_ids: list[int],
    ctx: RowDict | None = None,
) -> int | None:
    full = postprocess_text(text)
    if not full:
        return None
    assistant_message_id = db_add_message(
        conversation_id,
        "assistant",
        full,
        meta={
            "model": target.model,
            "provider": target.provider_id,
            "deployment_id": target.id,
            "model_settings": model_settings or {},
            "kind": "partial",
            "completed": False,
            "terminated_by_error": True,
        },
    )
    attach_scaffold_events_to_message(pending_tool_event_ids, assistant_message_id)
    if ctx is not None:
        persist_citations_for_assistant_message(assistant_message_id, ctx)
    return assistant_message_id


def _store_ab_message(
    *,
    conversation_id: str,
    ab_group: str,
    slot: str,
    target,
    requested_model_name: str,
    res: RowDict,
    ctx: RowDict,
    shared_tool_event_ids: list[int],
    attach_state: dict[str, bool],
) -> None:
    if res.get("ok"):
        text = res.get("text") or ""
        full = postprocess_text(text)
        if not full:
            return
        assistant_message_id = db_add_message(
            conversation_id,
            "assistant",
            full,
            meta={
                "ab_group": ab_group,
                "slot": slot,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
                "requested_model": requested_model_name,
                "kind": "ab",
                "recovery": res.get("recovery"),
            },
        )
        if shared_tool_event_ids and not attach_state.get("attached"):
            attach_scaffold_events_to_message(shared_tool_event_ids, assistant_message_id)
            attach_state["attached"] = True
        persist_citations_for_assistant_message(assistant_message_id, ctx)
        return

    payload = res.get("error") or {}
    msg = extract_error_message(payload)
    status = payload.get("status_code")
    bubble = f"[Model {slot} error] {status or ''} {msg}".strip()
    full = postprocess_text(bubble)
    if not full:
        return
    assistant_message_id = db_add_message(
        conversation_id,
        "assistant",
        full,
        meta={
            "ab_group": ab_group,
            "slot": slot,
            "model": target.model,
            "provider": target.provider_id,
            "deployment_id": target.id,
            "requested_model": requested_model_name,
            "kind": "error",
            "recovery_step": payload.get("recovery_step"),
            **payload,
        },
    )
    if shared_tool_event_ids and not attach_state.get("attached"):
        attach_scaffold_events_to_message(shared_tool_event_ids, assistant_message_id)
        attach_state["attached"] = True


def _error_markdown_from_payload(title: str, payload: RowDict) -> str:
    status = payload.get("status_code")
    req_id = payload.get("request_id")
    msg = extract_error_message(payload)
    lines = [f"**{title}** (HTTP {status or '?'})"]
    if req_id:
        lines.append(f"request_id: `{req_id}`")
    lines.append(msg)
    return "\n\n".join(lines).strip()


def _assistant_final_payload(*, slot: str | None, target, res: RowDict) -> RowDict:
    data: RowDict = {
        "slot": slot,
        "ok": bool(res.get("ok")),
        "model": target.model,
        "provider": target.provider_id,
        "deployment_id": target.id,
        "recovery": res.get("recovery"),
    }
    if res.get("ok"):
        data["text"] = res.get("text") or ""
    else:
        data["error"] = res.get("error") or {}
    return data


def _sse(event: str, payload: RowDict | dict | list | str | None = None) -> str:
    data = payload if payload is not None else {}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _numeric_scaffold_event_id(row: RowDict | None) -> int | None:
    if not row:
        return None
    raw = row.get("id")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
    return coerce_optional_int(raw)


def _collect_new_scaffold_frames(
    *,
    conversation_id: str,
    after_event_id: int,
    seen_event_ids: set[int] | None = None,
) -> tuple[list[str], int]:
    rows = db_list_conversation_scaffold_events_since(conversation_id, after_event_id=after_event_id)
    cursor = max(0, int(after_event_id or 0))
    frames: list[str] = []
    for row in rows:
        row_id = _numeric_scaffold_event_id(row)
        if row_id is not None:
            cursor = max(cursor, row_id)
            if seen_event_ids is not None and row_id in seen_event_ids:
                continue
            if seen_event_ids is not None:
                seen_event_ids.add(row_id)
        row["row_type"] = "scaffold_event"
        log_debug("Scaffold stream relay cid=%s kind=%s event_id=%s", conversation_id, row.get("event_kind"), row.get("id"))
        frames.append(_sse("scaffold", row))
    return frames, cursor


def _planning_stream_results(
    planning_iter,
    *,
    conversation_id: str,
    seen_event_ids: set[int] | None = None,
    cursor_state: dict[str, int] | None = None,
):
    while True:
        try:
            row = next(planning_iter)
        except StopIteration as stop:
            return stop.value

        if not row:
            continue

        row_id = _numeric_scaffold_event_id(row)
        if row_id is not None:
            if seen_event_ids is not None:
                seen_event_ids.add(row_id)
            if cursor_state is not None:
                cursor_state["value"] = max(int(cursor_state.get("value") or 0), row_id)

        row["row_type"] = "scaffold_event"
        log_debug("Planning scaffold relay cid=%s kind=%s event_id=%s", conversation_id, row.get("event_kind"), row.get("id"))
        yield _sse("scaffold", row)


def _openai_supports_thinking(target) -> bool:
    model = str(getattr(target, "model", "") or "").strip().lower()
    return model.startswith("gpt-5") or model.startswith("o")


def _map_openai_reasoning_effort(level: int) -> str:
    lvl = max(0, min(10, int(level or 0)))
    if lvl <= 0:
        return "none"
    if lvl <= 2:
        return "low"
    if lvl <= 6:
        return "medium"
    return "high"


def _prefers_streaming_preflight(target, model_settings: dict[str, object] | None, request_options: dict[str, object] | None) -> bool:
    if not isinstance(request_options, dict) or not request_options.get("reasoning"):
        return False
    settings = dict(model_settings or {})
    if not bool(settings.get("show_thinking", True)):
        return False
    provider_type = str(getattr(target, "provider_type", "") or "").strip().lower()
    return provider_type == "openai" and _openai_supports_thinking(target)


def _build_request_options(target, model_settings: dict[str, object] | None) -> dict[str, object]:
    settings = dict(model_settings or {})
    options: dict[str, object] = {}
    max_output_tokens = coerce_optional_int(settings.get("max_output_tokens"))
    if max_output_tokens is not None:
        options["max_output_tokens"] = max_output_tokens
    provider_type = str(getattr(target, "provider_type", "") or "").strip().lower()
    temp_value = coerce_optional_float(settings.get("temperature"))
    if temp_value is not None:
        if provider_type == "openai" and _openai_supports_thinking(target):
            log_info("Skipping temperature for OpenAI reasoning model %s; API may reject it as unsupported.", getattr(target, "model", ""))
        else:
            options["temperature"] = temp_value
    top_p = coerce_optional_float(settings.get("top_p"))
    if top_p is not None:
        options["top_p"] = top_p
    top_k = coerce_optional_int(settings.get("top_k"))
    if top_k is not None:
        options["top_k"] = top_k

    thinking_level = coerce_optional_int(settings.get("thinking_level")) or 0
    show_thinking = bool(settings.get("show_thinking", True))

    if provider_type == "openai":
        if _openai_supports_thinking(target):
            if thinking_level > 0:
                reasoning = {"effort": _map_openai_reasoning_effort(thinking_level)}
                if show_thinking:
                    reasoning["summary"] = "auto"
                options["reasoning"] = reasoning
            elif show_thinking:
                log_info("Thinking disabled for deployment %s because thinking level is 0.", getattr(target, "id", ""))
        elif thinking_level > 0 or show_thinking:
            log_info("Thinking requested for unsupported OpenAI model %s; ignoring.", getattr(target, "model", ""))
    return options


def _thinking_event_input_payload(target, model_settings: dict[str, object], request_options: dict[str, object]) -> dict[str, object]:
    return {
        "provider": getattr(target, "provider_id", None),
        "deployment_id": getattr(target, "id", None),
        "model": getattr(target, "model", None),
        "thinking_level": model_settings.get("thinking_level"),
        "show_thinking": model_settings.get("show_thinking"),
        "request_options": request_options,
    }


def _create_thinking_event_start(*, conversation_id: str, target, model_settings: dict[str, object], request_options: dict[str, object]) -> tuple[int | None, dict[str, object]]:
    title = f"Thinking · {getattr(target, 'display_name', None) or getattr(target, 'model', 'model')}"
    row = {
        "id": None,
        "row_type": "scaffold_event",
        "conversation_id": conversation_id,
        "message_id": None,
        "event_kind": "thinking",
        "status": "running",
        "title": title,
        "body_text": "",
        "input_json": _thinking_event_input_payload(target, model_settings, request_options),
        "output_json": {"text": ""},
        "created_at": None,
        "updated_at": None,
    }
    try:
        event_id = db_create_conversation_scaffold_event(
            conversation_id=conversation_id,
            event_kind="thinking",
            status="running",
            title=title,
            body_text="",
            input_json=row["input_json"],
            output_json=row["output_json"],
        )
        row["id"] = event_id
    except Exception as exc:
        log_warn("Thinking scaffold start persistence failed for %s: %s", conversation_id, exc)
    return row.get("id"), row


def _normalize_thinking_heading(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\*\*(.+?)\*\*$", r"\1", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text.lower()


def _strip_bold_heading_markers(value: object) -> str:
    text = str(value or "").strip()
    return re.sub(r"^\*\*(.+?)\*\*$", r"\1", text).strip()


def _split_thinking_section_text(text_value: object) -> tuple[str, str]:
    text = str(text_value or "").strip()
    if not text:
        return "", ""
    cleaned = text.strip()
    parts = re.split(r"\n\s*\n", cleaned, maxsplit=1)
    first = _strip_bold_heading_markers(parts[0]) if parts else ""
    remainder = parts[1].strip() if len(parts) > 1 else ""
    if first and len(first) <= 140:
        return first, remainder
    first_line_raw = cleaned.splitlines()[0].strip() if cleaned.splitlines() else ""
    first_line = _strip_bold_heading_markers(first_line_raw)
    if first_line and len(first_line) <= 140:
        body = cleaned[len(first_line_raw):].lstrip("\n").strip()
        return first_line, body
    return "", cleaned

def _build_thinking_output_payload(thinking_sections: dict[str, dict[str, object]], thinking_section_order: list[str], current_text: str) -> dict[str, object]:
    sections_payload: list[dict[str, object]] = []
    for key in thinking_section_order:
        section = thinking_sections.get(key) or {}
        text_value = str(section.get("text") or "").strip()
        if not text_value:
            continue
        title_value, body_value = _split_thinking_section_text(text_value)
        history_list = []
        history_raw = section.get("history")
        if not isinstance(history_raw, list):
            history_raw = []
        for hist in history_raw:
            hist_text = str(hist or "").strip()
            if not hist_text or hist_text == text_value or hist_text in history_list:
                continue
            history_list.append(hist_text)
        sections_payload.append({
            "key": key,
            "title": title_value,
            "body": body_value,
            "text": text_value,
            "history": history_list,
        })
    return {"text": str(current_text or "").strip(), "sections": sections_payload}


def _update_thinking_event(*, event_id: int | None, row: dict[str, object], text_value: str, output_payload: dict[str, object] | None = None, done: bool = False) -> dict[str, object]:
    row["status"] = "ok" if done else "running"
    row["body_text"] = text_value.strip()
    row["output_json"] = dict(output_payload or {"text": text_value})
    if event_id is not None:
        try:
            db_update_conversation_scaffold_event(
                event_id=event_id,
                status=str(row["status"]),
                body_text=str(row["body_text"]),
                output_json=row["output_json"],
            )
        except Exception as exc:
            log_warn("Thinking scaffold update failed for event %s: %s", event_id, exc)
    row["row_type"] = "scaffold_event"
    return dict(row)


# endregion

# region Chat Endpoints

@app.post("/api/new", response_model=NewChatResponse)
def new_chat():
    cid = str(uuid.uuid4())
    db_create_conversation(cid)
    return {"conversation_id": cid}


@app.post("/api/chat")
def chat(
    req: ChatRequest,
    model: str | None = None,
):
    tools = runtime.TOOL_REGISTRY
    providers = runtime.PROVIDER_REGISTRY
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        db_create_conversation(cid)

    scaffold_baseline_id = db_get_latest_conversation_scaffold_event_id(cid)

    heal = db_ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    raw_user_message = req.message or ""
    full = postprocess_text(raw_user_message)
    user_message_id: int | None = None
    if full:
        user_message_id = db_add_message(cid, "user", full)
    try:
        ingest_urls_from_user_message(
            conversation_id=cid,
            request_message_id=user_message_id,
            raw_message=raw_user_message,
            max_urls=3,
            fetch_method="python",
        )
    except Exception as e:
        log_warn(f"URL ingest failed for conversation {cid}: {e}")

    ctx = build_context(cid, full, include_preview=False)
    raw_input = build_model_input(
        cid,
        full,
        ctx=ctx,
        tool_cfg=tool_cfg,
        tools=tools,
    )

    requested_model = (req.model or model or "").strip()
    if providers is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    target = providers.resolve_chat_target(requested_model or None)
    provider = providers.get_chat_provider(target)
    model_settings = get_effective_model_settings("conversation", cid)
    request_options = _build_request_options(target, model_settings)

    def gen():
        final_text = ""
        pending_tool_event_ids: list[int] = []
        preflight_input = raw_input
        preflight_terminal_text: str | None = None
        used_preflight_tools = False
        seen_scaffold_ids: set[int] = set()
        scaffold_cursor = max(0, int(scaffold_baseline_id or 0))
        scaffold_state = {"value": scaffold_cursor}
        thinking_event_id: int | None = None
        thinking_row: dict[str, object] | None = None
        thinking_sections: dict[str, dict[str, object]] = {}
        thinking_section_order: list[str] = []
        thinking_section_fallback_counter = 0
        thinking_section_aliases: dict[str, str] = {}
        live_text_parts: list[str] = []

        def _emit_assistant_delta(delta_text: str):
            if not delta_text:
                return
            live_text_parts.append(delta_text)
            return _sse("assistant.delta", {"slot": None, "text": delta_text})

        def _emit_stream_item(item, parts: list[str]):
            nonlocal thinking_event_id, thinking_row, thinking_section_fallback_counter
            if isinstance(item, dict) and str(item.get("type") or "").startswith("reasoning_"):
                event_type = str(item.get("event_type") or "")
                delta_text = str(item.get("delta") or "")
                part_text = str(item.get("part_text") or "")
                done_text = str(item.get("text") or "")
                done_flag = bool(item.get("done")) or str(item.get("type") or "") == "reasoning_done"

                provider_key = item.get("summary_index")
                if provider_key is None:
                    provider_key = item.get("item_id")
                if provider_key is None:
                    provider_key = "fallback"
                provider_key = str(provider_key)
                canonical_key = thinking_section_aliases.get(provider_key, provider_key)

                candidate = (part_text or done_text or delta_text).strip()
                title_candidate, _body_candidate = _split_thinking_section_text(candidate)
                if title_candidate:
                    title_key = f"title:{_normalize_thinking_heading(title_candidate)}"
                    previous_key = canonical_key
                    canonical_key = title_key
                    thinking_section_aliases[provider_key] = canonical_key
                    if previous_key != canonical_key and previous_key in thinking_sections:
                        previous_section = thinking_sections.pop(previous_key)
                        target_section = thinking_sections.get(canonical_key)
                        if target_section is None:
                            thinking_sections[canonical_key] = previous_section
                            if previous_key in thinking_section_order:
                                thinking_section_order[thinking_section_order.index(previous_key)] = canonical_key
                        else:
                            previous_history_raw = previous_section.get("history")
                            target_history_raw = target_section.get("history")
                            previous_history = list(previous_history_raw) if isinstance(previous_history_raw, list) else []
                            target_history = list(target_history_raw) if isinstance(target_history_raw, list) else []
                            for hist in [str(previous_section.get("text") or "").strip(), *previous_history]:
                                hist_text = str(hist or "").strip()
                                if hist_text and hist_text != str(target_section.get("text") or "").strip() and hist_text not in target_history:
                                    target_history.append(hist_text)
                            target_section["history"] = target_history[-8:]
                            if previous_key in thinking_section_order:
                                thinking_section_order.remove(previous_key)
                section = thinking_sections.get(canonical_key)
                if section is None:
                    section = {"text": "", "history": []}
                    thinking_sections[canonical_key] = section
                    thinking_section_order.append(canonical_key)
                current_section = str(section.get("text") or "").strip()
                updated_section = current_section

                if event_type.endswith(".delta"):
                    if delta_text:
                        if not current_section:
                            updated_section = delta_text
                        elif current_section.endswith(delta_text) or delta_text in current_section:
                            updated_section = current_section
                        else:
                            updated_section = current_section + delta_text
                else:
                    if candidate:
                        if not current_section:
                            updated_section = candidate
                        elif candidate == current_section or candidate in current_section:
                            updated_section = current_section
                        elif candidate.startswith(current_section):
                            updated_section = candidate
                        elif current_section.startswith(candidate):
                            updated_section = current_section
                        else:
                            current_title, _current_body = _split_thinking_section_text(current_section)
                            if current_title and title_candidate and _normalize_thinking_heading(current_title) == _normalize_thinking_heading(title_candidate):
                                updated_section = candidate
                            elif canonical_key.startswith("title:"):
                                updated_section = candidate
                            elif canonical_key == "fallback" and len(thinking_section_order) == 1:
                                updated_section = candidate
                            else:
                                thinking_section_fallback_counter += 1
                                canonical_key = f"fallback_{thinking_section_fallback_counter}"
                                section = thinking_sections.setdefault(canonical_key, {"text": "", "history": []})
                                if canonical_key not in thinking_section_order:
                                    thinking_section_order.append(canonical_key)
                                current_section = str(section.get("text") or "").strip()
                                updated_section = candidate

                updated_section = str(updated_section or "").strip()
                if updated_section != current_section and current_section:
                    history_raw = section.get("history")
                    history = list(history_raw) if isinstance(history_raw, list) else []
                    if not history or history[-1] != current_section:
                        history.append(current_section)
                    section["history"] = history[-8:]
                section["text"] = updated_section
                title_value, body_value = _split_thinking_section_text(updated_section)
                if title_value:
                    section["title"] = title_value
                if body_value:
                    section["body"] = body_value

                current_text = "\n\n".join(
                    text_value
                    for text_value in (str((thinking_sections.get(key) or {}).get("text") or "").strip() for key in thinking_section_order)
                    if text_value
                ).strip()
                if not current_text and not done_flag:
                    return
                if thinking_row is None:
                    thinking_event_id, thinking_row = _create_thinking_event_start(
                        conversation_id=cid,
                        target=target,
                        model_settings=model_settings,
                        request_options=request_options,
                    )
                    if thinking_event_id is not None:
                        pending_tool_event_ids.append(int(thinking_event_id))
                if thinking_row is not None:
                    row = _update_thinking_event(
                        event_id=thinking_event_id,
                        row=thinking_row,
                        text_value=current_text,
                        output_payload=_build_thinking_output_payload(thinking_sections, thinking_section_order, current_text),
                        done=done_flag,
                    )
                    yield _sse("scaffold", row)
                return
            delta = str(item or "")
            if delta:
                parts.append(delta)
                frame = _emit_assistant_delta(delta)
                if frame:
                    yield frame

        try:
            frames, scaffold_cursor = _collect_new_scaffold_frames(
                conversation_id=cid,
                after_event_id=scaffold_state["value"],
                seen_event_ids=seen_scaffold_ids,
            )
            scaffold_state["value"] = scaffold_cursor
            for frame in frames:
                yield frame
            attempted_tool_preflight = should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=tools)
            streaming_preflight = attempted_tool_preflight and _prefers_streaming_preflight(target, model_settings, request_options)
            if attempted_tool_preflight and streaming_preflight:
                log_info(
                    "Tool preflight switched to streaming accumulator cid=%s deployment=%s model=%s",
                    cid,
                    target.id,
                    target.model,
                )
                print(
                    f"[tool.preflight] cid={cid} deployment={target.id} model={target.model} mode=stream-accumulator",
                    flush=True,
                )
            elif attempted_tool_preflight:
                log_info(
                    "Tool preflight using complete planner cid=%s deployment=%s model=%s",
                    cid,
                    target.id,
                    target.model,
                )
                print(
                    f"[tool.preflight] cid={cid} deployment={target.id} model={target.model} mode=complete-planner",
                    flush=True,
                )
                try:
                    planning_iter = iter_expand_input_with_tool_requests(
                        target=target,
                        base_input=raw_input,
                        conversation_id=cid,
                        user_text=full,
                        tool_cfg=tool_cfg,
                        tools=tools,
                        user_message_id=user_message_id,
                        request_options=request_options,
                    )
                    preflight_result = yield from _planning_stream_results(
                        planning_iter,
                        conversation_id=cid,
                        seen_event_ids=seen_scaffold_ids,
                        cursor_state=scaffold_state,
                    )
                    scaffold_cursor = scaffold_state["value"]
                    preflight_input, preflight_terminal_text, used_preflight_tools, pending_tool_event_ids = preflight_result
                except Exception as exc:
                    log_warn(f"Tool preflight failed for conversation {cid}: {exc}")
                    preflight_input = raw_input
                    preflight_terminal_text = None
                    used_preflight_tools = False
                    pending_tool_event_ids = []

            if used_preflight_tools:
                wrapper_text = tool_wrapper_text(preflight_terminal_text or "")
                if wrapper_text:
                    frame = _emit_assistant_delta(wrapper_text)
                    if frame:
                        yield frame
                follow_input = remove_tool_prompt_messages(preflight_input)
                parts: list[str] = []
                for item in provider.stream_text(target, follow_input, request_options=request_options):
                    yield from _emit_stream_item(item, parts)
                if request_options.get("reasoning") and not any(
                    str((thinking_sections.get(key) or {}).get("text") or "").strip()
                    for key in thinking_section_order
                ):
                    log_info("No thinking summaries observed cid=%s deployment=%s model=%s", cid, target.id, target.model)
                final_text = postprocess_text((wrapper_text if wrapper_text else "") + "".join(parts))
            elif preflight_terminal_text is not None:
                final_text = postprocess_text(preflight_terminal_text)
                if final_text:
                    yield _sse("assistant.final", {
                        "slot": None,
                        "ok": True,
                        "text": final_text,
                        "model": target.model,
                        "provider": target.provider_id,
                        "deployment_id": target.id,
                    })
            else:
                if attempted_tool_preflight and streaming_preflight:
                    log_info(
                        "Tool preflight resolved via main stream cid=%s deployment=%s model=%s",
                        cid,
                        target.id,
                        target.model,
                    )
                parts: list[str] = []
                for item in provider.stream_text(target, raw_input, request_options=request_options):
                    yield from _emit_stream_item(item, parts)

                if request_options.get("reasoning") and not any(
                    str((thinking_sections.get(key) or {}).get("text") or "").strip()
                    for key in thinking_section_order
                ):
                    log_info("No thinking summaries observed cid=%s deployment=%s model=%s", cid, target.id, target.model)
                streamed_text = strip_zeitgeber_prefix("".join(parts))
                if response_requests_tool_execution(streamed_text, tools):
                    planning_iter = iter_expand_input_with_tool_requests(
                        target=target,
                        base_input=raw_input,
                        conversation_id=cid,
                        user_text=full,
                        tool_cfg=tool_cfg,
                        tools=tools,
                        user_message_id=user_message_id,
                        initial_assistant_text=streamed_text,
                        request_options=request_options,
                    )
                    while True:
                        try:
                            row = next(planning_iter)
                            if row:
                                row_id = _numeric_scaffold_event_id(row)
                                if row_id is not None:
                                    seen_scaffold_ids.add(row_id)
                                    scaffold_cursor = max(scaffold_cursor, row_id)
                                yield _sse("scaffold", row)
                        except StopIteration as stop:
                            expanded_input, terminal_text, used_tools, stream_tool_event_ids = stop.value
                            break
                    frames, scaffold_cursor = _collect_new_scaffold_frames(
                        conversation_id=cid,
                        after_event_id=scaffold_cursor,
                        seen_event_ids=seen_scaffold_ids,
                    )
                    for frame in frames:
                        yield frame
                    if used_tools:
                        pending_tool_event_ids.extend(stream_tool_event_ids)
                        if terminal_text is None:
                            follow_input = remove_tool_prompt_messages(expanded_input)
                            follow_parts: list[str] = []
                            for item in provider.stream_text(target, follow_input, request_options=request_options):
                                yield from _emit_stream_item(item, follow_parts)
                            if request_options.get("reasoning") and not any(
                                str((thinking_sections.get(key) or {}).get("text") or "").strip()
                                for key in thinking_section_order
                            ):
                                log_info("No thinking summaries observed cid=%s deployment=%s model=%s", cid, target.id, target.model)
                            final_text = postprocess_text("".join(follow_parts))
                        else:
                            final_text = postprocess_text(terminal_text)
                            if final_text:
                                yield _sse("assistant.final", {
                                    "slot": None,
                                    "ok": True,
                                    "text": final_text,
                                    "model": target.model,
                                    "provider": target.provider_id,
                                    "deployment_id": target.id,
                                })
                    else:
                        final_text = postprocess_text(streamed_text)
                else:
                    final_text = postprocess_text(streamed_text)

            if final_text:
                assistant_message_id = db_add_message(
                    cid,
                    "assistant",
                    final_text,
                    meta={
                        "model": target.model,
                        "provider": target.provider_id,
                        "deployment_id": target.id,
                        "model_settings": model_settings,
                    },
                )
                attach_scaffold_events_to_message(pending_tool_event_ids, assistant_message_id)
                persist_citations_for_assistant_message(assistant_message_id, ctx)
                yield _sse("assistant.done", {"slot": None, "message_id": assistant_message_id})
        except ProviderExecutionError as e:
            payload = dict(e.payload or {})
            if "provider_error_type" not in payload:
                payload["provider_error_type"] = type(e).__name__
            partial_text = postprocess_text("".join(live_text_parts)) if live_text_parts else ""
            had_partial = bool((partial_text or "").strip())
            if had_partial:
                _store_partial_single_message(
                    conversation_id=cid,
                    target=target,
                    text=partial_text,
                    model_settings=model_settings,
                    pending_tool_event_ids=pending_tool_event_ids,
                    ctx=ctx,
                )
            _store_single_error_message(
                conversation_id=cid,
                target=target,
                payload=payload,
                pending_tool_event_ids=[] if had_partial else pending_tool_event_ids,
            )
            yield _sse("assistant.final", {
                "slot": None,
                "ok": False,
                "text": _error_markdown_from_payload("Model error", payload),
                "error": payload,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
                "append_error": had_partial,
            })
        except Exception as e:
            log_error("Chat stream failed for conversation %s: %s%s", cid, e, traceback.format_exc())
            payload = _generic_error_payload(e)
            partial_text = postprocess_text("".join(live_text_parts)) if live_text_parts else ""
            had_partial = bool((partial_text or "").strip())
            if had_partial:
                _store_partial_single_message(
                    conversation_id=cid,
                    target=target,
                    text=partial_text,
                    model_settings=model_settings,
                    pending_tool_event_ids=pending_tool_event_ids,
                    ctx=ctx,
                )
            _store_single_error_message(
                conversation_id=cid,
                target=target,
                payload=payload,
                pending_tool_event_ids=[] if had_partial else pending_tool_event_ids,
            )
            yield _sse("assistant.final", {
                "slot": None,
                "ok": False,
                "text": f"**Server exception** ({type(e).__name__})\n\n{extract_error_message(payload)}",
                "error": payload,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
                "append_error": had_partial,
            })

    resp = StreamingResponse(gen(), media_type="text/event-stream; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.post("/api/chat_ab")
async def chat_ab(
    req: ABChatRequest,
):
    tools = runtime.TOOL_REGISTRY
    providers = runtime.PROVIDER_REGISTRY
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        db_create_conversation(cid)

    scaffold_baseline_id = db_get_latest_conversation_scaffold_event_id(cid)

    heal = db_ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    raw_user_message = req.message or ""
    full = postprocess_text(raw_user_message)

    user_message_id: int | None = None
    if full:
        user_message_id = db_add_message(cid, "user", full)

    try:
        ingest_urls_from_user_message(
            conversation_id=cid,
            request_message_id=user_message_id,
            raw_message=raw_user_message,
            max_urls=3,
            fetch_method="python",
        )
    except Exception as e:
        log_warn(f"URL ingest failed for conversation {cid}: {e}")

    ctx = build_context(cid, full, include_preview=False)
    raw_input = build_model_input(
        cid,
        full,
        ctx=ctx,
        tool_cfg=tool_cfg,
        tools=tools,
    )

    model_a = (req.model_a or "").strip()
    model_b = (req.model_b or model_a).strip()

    if providers is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    target_a = providers.resolve_chat_target(model_a or None)
    target_b = providers.resolve_chat_target(model_b or None)
    ab_group = str(uuid.uuid4())

    async def agen():
        planner_text_a: str | None = None
        used_shared_tools = False
        final_input = raw_input
        shared_tool_event_ids: list[int] = []
        seen_scaffold_ids: set[int] = set()
        scaffold_cursor = max(0, int(scaffold_baseline_id or 0))
        scaffold_state = {"value": scaffold_cursor}

        frames, scaffold_cursor = _collect_new_scaffold_frames(
            conversation_id=cid,
            after_event_id=scaffold_cursor,
            seen_event_ids=seen_scaffold_ids,
        )
        for frame in frames:
            yield frame

        if should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=tools):
            try:
                planning_iter = iter_expand_input_with_tool_requests(
                    target=target_a,
                    base_input=raw_input,
                    conversation_id=cid,
                    user_text=full,
                    tool_cfg=tool_cfg,
                    tools=tools,
                    user_message_id=user_message_id,
                    request_options=_build_request_options(target_a, get_effective_model_settings("conversation", cid)),
                )
                while True:
                    try:
                        row = next(planning_iter)
                        if not row:
                            continue
                        row_id = _numeric_scaffold_event_id(row)
                        if row_id is not None:
                            seen_scaffold_ids.add(row_id)
                            scaffold_state["value"] = max(int(scaffold_state.get("value") or 0), row_id)
                        row["row_type"] = "scaffold_event"
                        log_debug("Planning scaffold relay cid=%s kind=%s event_id=%s", cid, row.get("event_kind"), row.get("id"))
                        yield _sse("scaffold", row)
                    except StopIteration as stop:
                        expanded_input, planner_text_a, used_shared_tools, shared_tool_event_ids = stop.value
                        break
                scaffold_cursor = scaffold_state["value"]
                frames, scaffold_cursor = _collect_new_scaffold_frames(
                    conversation_id=cid,
                    after_event_id=scaffold_state["value"],
                    seen_event_ids=seen_scaffold_ids,
                )
                scaffold_state["value"] = scaffold_cursor
                for frame in frames:
                    yield frame
                final_input = remove_tool_prompt_messages(expanded_input if used_shared_tools else raw_input)
            except Exception as exc:
                log_warn(f"Shared tool planning failed for conversation {cid}: {exc}")
                planner_text_a = None
                used_shared_tools = False
                shared_tool_event_ids = []
                final_input = remove_tool_prompt_messages(raw_input)
        else:
            final_input = remove_tool_prompt_messages(raw_input)

        yield _sse("ab.init", {
            "ab_group": ab_group,
            "provider_a": target_a.provider_id,
            "provider_b": target_b.provider_id,
            "model_a": target_a.model,
            "model_b": target_b.model,
            "deployment_a": target_a.id,
            "deployment_b": target_b.id,
            "requested_model_a": model_a,
            "requested_model_b": model_b,
            "tool_planner_slot": "A",
            "used_shared_tools": used_shared_tools,
        })

        queue: asyncio.Queue[tuple[str, object, str, RowDict]] = asyncio.Queue()

        async def run_slot(slot: str, target, requested_model_name: str, forced_result: RowDict | None = None):
            res = forced_result if forced_result is not None else await call_model_with_recovery(target, final_input, request_options=_build_request_options(target, get_effective_model_settings("conversation", cid)))
            await queue.put((slot, target, requested_model_name, res))

        task_a = None
        if not used_shared_tools and planner_text_a is not None:
            task_a = asyncio.create_task(run_slot(
                "A",
                target_a,
                model_a,
                {"ok": True, "text": strip_zeitgeber_prefix(planner_text_a or ""), "recovery": None},
            ))
        else:
            task_a = asyncio.create_task(run_slot("A", target_a, model_a))
        task_b = asyncio.create_task(run_slot("B", target_b, model_b))

        results: dict[str, tuple[object, str, RowDict]] = {}
        for _ in range(2):
            slot, slot_target, requested_model_name, res = await queue.get()
            results[slot] = (slot_target, requested_model_name, res)
            yield _sse("assistant.final", _assistant_final_payload(slot=slot, target=slot_target, res=res))

        await asyncio.gather(task_a, task_b, return_exceptions=True)

        attach_state = {"attached": False}
        slot_a_target, slot_a_requested, slot_a_res = results["A"]
        slot_b_target, slot_b_requested, slot_b_res = results["B"]
        _store_ab_message(
            conversation_id=cid,
            ab_group=ab_group,
            slot="A",
            target=slot_a_target,
            requested_model_name=slot_a_requested,
            res=slot_a_res,
            ctx=ctx,
            shared_tool_event_ids=shared_tool_event_ids,
            attach_state=attach_state,
        )
        _store_ab_message(
            conversation_id=cid,
            ab_group=ab_group,
            slot="B",
            target=slot_b_target,
            requested_model_name=slot_b_requested,
            res=slot_b_res,
            ctx=ctx,
            shared_tool_event_ids=shared_tool_event_ids,
            attach_state=attach_state,
        )
        yield _sse("ab.done", {"ab_group": ab_group})

    resp = StreamingResponse(agen(), media_type="text/event-stream; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@app.post("/api/ab/canonical")
def api_ab_canonical(req: ABCanonicalRequest):
    slot = (req.slot or "").upper()
    if slot not in ("A", "B"):
        return JSONResponse({"ok": False, "error": "slot must be 'A' or 'B'"}, status_code=400)

    db_update_ab_canonical(req.conversation_id, req.ab_group, slot)
    return JSONResponse({"ok": True})


# endregion
