import asyncio
from functools import partial
import json
import traceback
import uuid

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from server.api_helpers import (
    RowDict,
    attach_scaffold_events_to_message,
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
    db_ensure_files_artifacted_for_conversation,
    db_get_latest_conversation_scaffold_event_id,
    db_list_conversation_scaffold_events_since,
    db_update_ab_canonical,
)
from server.logging_helper import log_debug, log_error, log_info, log_warn
from server.providers.openai_provider import ProviderExecutionError, extract_error_message
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.base import app
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
):
    providers = providers or runtime.PROVIDER_REGISTRY
    if providers is None:
        raise RuntimeError("Provider registry is not initialized.")

    provider = providers.get_chat_provider(target)
    loop = asyncio.get_running_loop()
    fn = partial(provider.complete, target, model_input)
    return await loop.run_in_executor(None, fn)


async def call_model_with_recovery(target, model_input: ModelInput) -> RowDict:
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
            result = await _call_model(target, mi)
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


def _numeric_scaffold_event_id(row: dict | None) -> int | None:
    if not row:
        return None
    raw = row.get("id")
    try:
        return int(raw)
    except Exception:
        return None


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

    def gen():
        final_text = ""
        pending_tool_event_ids: list[int] = []
        preflight_input = raw_input
        preflight_terminal_text: str | None = None
        used_preflight_tools = False
        seen_scaffold_ids: set[int] = set()
        scaffold_cursor = max(0, int(scaffold_baseline_id or 0))
        scaffold_state = {"value": scaffold_cursor}

        try:
            frames, scaffold_cursor = _collect_new_scaffold_frames(
                conversation_id=cid,
                after_event_id=scaffold_state["value"],
                seen_event_ids=seen_scaffold_ids,
            )
            scaffold_state["value"] = scaffold_cursor
            for frame in frames:
                yield frame
            if should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=tools):
                try:
                    planning_iter = iter_expand_input_with_tool_requests(
                        target=target,
                        base_input=raw_input,
                        conversation_id=cid,
                        user_text=full,
                        tool_cfg=tool_cfg,
                        tools=tools,
                        user_message_id=user_message_id,
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
                    yield _sse("assistant.delta", {"slot": None, "text": wrapper_text})
                follow_input = remove_tool_prompt_messages(preflight_input)
                parts: list[str] = []
                for delta in provider.stream_text(target, follow_input):
                    parts.append(delta)
                    yield _sse("assistant.delta", {"slot": None, "text": delta})
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
                parts: list[str] = []
                for delta in provider.stream_text(target, raw_input):
                    parts.append(delta)
                    yield _sse("assistant.delta", {"slot": None, "text": delta})

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
                            for delta in provider.stream_text(target, follow_input):
                                follow_parts.append(delta)
                                yield _sse("assistant.delta", {"slot": None, "text": delta})
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
                    },
                )
                attach_scaffold_events_to_message(pending_tool_event_ids, assistant_message_id)
                persist_citations_for_assistant_message(assistant_message_id, ctx)
                yield _sse("assistant.done", {"slot": None, "message_id": assistant_message_id})
        except ProviderExecutionError as e:
            payload = dict(e.payload or {})
            if "provider_error_type" not in payload:
                payload["provider_error_type"] = type(e).__name__
            _store_single_error_message(
                conversation_id=cid,
                target=target,
                payload=payload,
                pending_tool_event_ids=pending_tool_event_ids,
            )
            yield _sse("assistant.final", {
                "slot": None,
                "ok": False,
                "text": _error_markdown_from_payload("Model error", payload),
                "error": payload,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
            })
        except Exception as e:
            log_error("Chat stream failed for conversation %s: %s%s", cid, e, traceback.format_exc())
            payload = _generic_error_payload(e)
            _store_single_error_message(
                conversation_id=cid,
                target=target,
                payload=payload,
                pending_tool_event_ids=pending_tool_event_ids,
            )
            yield _sse("assistant.final", {
                "slot": None,
                "ok": False,
                "text": f"**Server exception** ({type(e).__name__})\n\n{extract_error_message(payload)}",
                "error": payload,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
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
            res = forced_result if forced_result is not None else await call_model_with_recovery(target, final_input)
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
