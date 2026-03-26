
import asyncio
from functools import partial
import uuid
import anyio
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from server.api_helpers import RowDict, attach_scaffold_events_to_message, trim_history, sleep_ms, postprocess_text, strip_zeitgeber_prefix
from server.api_models import ABCanonicalRequest, ABChatRequest, ChatRequest, NewChatResponse
from server.config import load_tool_config
from server.context import build_context, build_model_input
from server.db import db_add_message, db_create_conversation, db_ensure_files_artifacted_for_conversation, db_update_ab_canonical, db_update_conversation_scaffold_event
from server.logging_helper import log_warn
from server.providers.openai_provider import ProviderExecutionError, extract_error_message
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.files import strip_images, strip_file_messages
from server.routes.library import persist_citations_for_assistant_message
from server.routes.tooling import expand_input_with_tool_requests, tool_wrapper_text, response_requests_tool_execution, expand_input_with_tool_requests_async, should_attempt_tool_preflight, remove_tool_prompt_messages
from server.tools.registry import ToolRegistry
from server.web_ingest import ingest_urls_from_user_message
import server.runtime as runtime 

from server.routes.base import app


# region Chat Model helpers

async def _call_model(
    target,
    model_input,
    providers: ProviderRegistry | None = None
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

    # 1) Original input, retry once
    attempts.append(("original", model_input, 0))
    attempts.append(("original_retry", model_input, 250))

    # 2) Strip images, retry once
    mi_noimg = strip_images(model_input)
    attempts.append(("no_images", mi_noimg, 0))
    attempts.append(("no_images_retry", mi_noimg, 250))

    # 3) Strip file messages (more aggressive)
    mi_textonly = strip_file_messages(mi_noimg)
    attempts.append(("text_only", mi_textonly, 0))

    # 4) Trim history hard
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

            # Only ladder on 500s. If it’s a 400/422, don’t spam retries—just return it.
            if payload.get("status_code") and int(payload["status_code"]) < 500:
                return {"ok": False, "error": last_err_payload}

    return {"ok": False, "error": last_err_payload or {"status_code": 500, "body": {"error": {"message": "Unknown error"}}}}


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
    #providers: ProviderRegistry | None = None,
    #tools: ToolRegistry | None = None
    tools = runtime.TOOL_REGISTRY
    providers = runtime.PROVIDER_REGISTRY
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        db_create_conversation(cid)
    # Call before build_model_input to ensure that we use it to search RAG
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

    preflight_input = raw_input
    preflight_terminal_text: str | None = None
    used_preflight_tools = False
    pending_tool_event_ids: list[int] = []

    if should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=tools):
        try:
            preflight_input, preflight_terminal_text, used_preflight_tools, pending_tool_event_ids = expand_input_with_tool_requests(
                target=target,
                base_input=raw_input,
                conversation_id=cid,
                user_text=full,
                tool_cfg=tool_cfg,
                tools=tools,
                user_message_id=user_message_id,
            )
        except Exception as exc:
            log_warn(f"Tool preflight failed for conversation {cid}: {exc}")
            preflight_input = raw_input
            preflight_terminal_text = None
            used_preflight_tools = False
            pending_tool_event_ids = []

    def gen():
        final_text = ""
        try:
            if used_preflight_tools:
                wrapper_text = tool_wrapper_text(preflight_terminal_text or "")
                if wrapper_text:
                    yield wrapper_text + ""
                follow_input = remove_tool_prompt_messages(preflight_input)
                parts: list[str] = []
                for delta in provider.stream_text(target, follow_input):
                    parts.append(delta)
                    yield delta
                final_text = postprocess_text((wrapper_text + "" if wrapper_text else "") + "".join(parts))
            elif preflight_terminal_text is not None:
                final_text = postprocess_text(preflight_terminal_text)
                if final_text:
                    yield final_text
            else:
                parts: list[str] = []
                for delta in provider.stream_text(target, raw_input):
                    parts.append(delta)
                    yield delta

                streamed_text = strip_zeitgeber_prefix("".join(parts))
                if response_requests_tool_execution(streamed_text, tools):
                    expanded_input, terminal_text, used_tools, stream_tool_event_ids = expand_input_with_tool_requests(
                        target=target,
                        base_input=raw_input,
                        conversation_id=cid,
                        user_text=full,
                        tool_cfg=tool_cfg,
                        tools=tools,
                        user_message_id=user_message_id,
                        initial_assistant_text=streamed_text,
                    )
                    if used_tools:
                        pending_tool_event_ids.extend(stream_tool_event_ids)
                        if terminal_text is None:
                            follow_input = remove_tool_prompt_messages(expanded_input)
                            follow_parts: list[str] = []
                            for delta in provider.stream_text(target, follow_input):
                                follow_parts.append(delta)
                                yield delta
                            final_text = postprocess_text("".join(follow_parts))
                        else:
                            final_text = postprocess_text(terminal_text)
                            if final_text:
                                yield final_text
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
        except ProviderExecutionError as e:
            yield f"\n[server exception: {type(e).__name__}]"
        except Exception as e:
            yield f"\n[server exception: {type(e).__name__}]"

    resp = StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    return resp


@app.post("/api/chat_ab")
async def chat_ab(
    req: ABChatRequest,
):
    #providers: ProviderRegistry | None = None,
    #tools: ToolRegistry | None = None
    """
    A/B endpoint that:
      - never breaks the UI on OpenAI errors
      - runs A and B in parallel
      - uses slot A as the shared tool planner when tooling is needed
      - returns structured {a:{ok,text|error}, b:{ok,text|error}}
    """
    tools = runtime.TOOL_REGISTRY
    providers = runtime.PROVIDER_REGISTRY
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        db_create_conversation(cid)

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

    planner_text_a: str | None = None
    used_shared_tools = False
    final_input = raw_input
    shared_tool_event_ids: list[int] = []

    if should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=tools):
        try:
            expanded_input, planner_text_a, used_shared_tools, shared_tool_event_ids = await expand_input_with_tool_requests_async(
                target=target_a,
                base_input=raw_input,
                conversation_id=cid,
                user_text=full,
                tool_cfg=tool_cfg,
                tool_registry=tools,
                user_message_id=user_message_id,
            )
            final_input = remove_tool_prompt_messages(expanded_input if used_shared_tools else raw_input)
        except Exception as exc:
            log_warn(f"Shared tool planning failed for conversation {cid}: {exc}")
            planner_text_a = None
            used_shared_tools = False
            shared_tool_event_ids = []
            final_input = remove_tool_prompt_messages(raw_input)
    else:
        final_input = remove_tool_prompt_messages(raw_input)

    ab_group = str(uuid.uuid4())

    a_res = None
    b_res = None

    async def run_b():
        nonlocal b_res
        b_res = await call_model_with_recovery(target_b, final_input)

    if used_shared_tools:
        async with anyio.create_task_group() as tg:
            async def run_a():
                nonlocal a_res
                a_res = await call_model_with_recovery(target_a, final_input)
            tg.start_soon(run_a)
            tg.start_soon(run_b)
    else:
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_b)
            if planner_text_a is not None:
                a_res = {"ok": True, "text": strip_zeitgeber_prefix(planner_text_a or ""), "recovery": None}
            else:
                async def run_a_direct():
                    nonlocal a_res
                    a_res = await call_model_with_recovery(target_a, final_input)
                tg.start_soon(run_a_direct)

    assert a_res is not None and b_res is not None

    attached_shared_tool_events = False

    def store(slot: str, target, requested_model_name: str, res: RowDict):
        nonlocal attached_shared_tool_events
        if res.get("ok"):
            text = res.get("text") or ""
            full = postprocess_text(text)
            if full:
                assistant_message_id = db_add_message(cid, "assistant", full, meta={
                    "ab_group": ab_group,
                    "slot": slot,
                    "model": target.model,
                    "provider": target.provider_id,
                    "deployment_id": target.id,
                    "requested_model": requested_model_name,
                    "kind": "ab",
                    "recovery": res.get("recovery"),
                })
                if shared_tool_event_ids and not attached_shared_tool_events:
                    attach_scaffold_events_to_message(shared_tool_event_ids, assistant_message_id)
                    attached_shared_tool_events = True
                persist_citations_for_assistant_message(assistant_message_id, ctx)
        else:
            payload = res.get("error") or {}
            msg = extract_error_message(payload)
            status = payload.get("status_code")
            bubble = f"[Model {slot} error] {status or ''} {msg}".strip()
            full = postprocess_text(bubble)
            if full:
                db_add_message(
                    cid,
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
                        "recovery_step": res["error"].get("recovery_step"),
                        **payload,
                    },
                )
    store("A", target_a, model_a, a_res)
    store("B", target_b, model_b, b_res)

    return JSONResponse({
        "conversation_id": cid,
        "ab_group": ab_group,
        "model_a": target_a.model,
        "model_b": target_b.model,
        "deployment_a": target_a.id,
        "deployment_b": target_b.id,
        "provider_a": target_a.provider_id,
        "provider_b": target_b.provider_id,
        "requested_model_a": model_a,
        "requested_model_b": model_b,
        "tool_planner_slot": "A",
        "used_shared_tools": used_shared_tools,
        "a": a_res,
        "b": b_res,
    })


@app.post("/api/ab/canonical")
def api_ab_canonical(req: ABCanonicalRequest):
    """
    Flip which variant in an A/B pair is treated as canonical for context.
    """
    slot = (req.slot or "").upper()
    if slot not in ("A", "B"):
        return JSONResponse({"ok": False, "error": "slot must be 'A' or 'B'"}, status_code=400)

    db_update_ab_canonical(req.conversation_id, req.ab_group, slot)
    return JSONResponse({"ok": True})


# endregion

