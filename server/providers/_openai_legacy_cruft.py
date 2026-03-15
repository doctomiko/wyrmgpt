# Do not uncomment OpenAI calls in main.py - code moved to ./providers/openai_provider.py
import asyncio
from functools import partial
from typing import cast

from openai import OpenAI, APIStatusError
from openai.types.responses import ResponseInputParam

from server.config import load_openai_config
from server.providers.types import ModelInput
#From openai/types/responses/response_create_params.py

oai_cfg = load_openai_config()

# We are phasing this out, do not uncomment it
# New code comes from ./providers/openai_provider.py
client = OpenAI(api_key=oai_cfg.open_ai_apikey)

def _extract_output_text(resp) -> str:
    # SDKs vary; try the obvious fields first
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t.strip()

    # fallback: walk resp.output items if present
    out = getattr(resp, "output", None)
    if isinstance(out, list):
        chunks = []
        for item in out:
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for c in content:
                    if getattr(c, "type", None) == "output_text":
                        chunks.append(getattr(c, "text", ""))
        joined = "".join(chunks).strip()
        if joined:
            return joined
    return ""


def _openai_error_payload(e: APIStatusError) -> dict:
    # Pull out useful fields safely
    status = getattr(e, "status_code", None)
    req_id = None
    err_json = None
    try:
        err_json = e.response.json()
        req_id = err_json.get("error", {}).get("request_id") or err_json.get("request_id")
    except Exception:
        try:
            err_json = {"raw": e.response.text}
        except Exception:
            err_json = {"raw": repr(getattr(e, "response", None))}
    return {
        "status_code": status,
        "request_id": req_id,
        "body": err_json,
    }


def _extract_err_msg(payload: dict) -> str:
    body = payload.get("body") or {}
    if isinstance(body, dict):
        return (body.get("error") or {}).get("message") or body.get("message") or "OpenAI API error"
    return "OpenAI API error"


if (False): # from chat()
    model_input = cast(ResponseInputParam, raw_input)
    print("[debug] model_input:", json.dumps(model_input, indent=2)[:5000])
    model = (req.model or model or MODEL).strip()
    def gen():
        parts: list[str] = []
        try:
            with client.responses.stream(
                model=model,
                input=model_input,
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        parts.append(event.delta)
                        yield event.delta
                    elif event.type == "response.refusal.delta":
                        parts.append(event.delta)
                        yield event.delta
                    elif event.type == "response.error":
                        yield "\n[error]\n"

                full = postprocess_text("".join(parts))
                if full:
                    add_message(cid, "assistant", full, meta={"model": model})
        except Exception as e:
            yield f"\n[server exception: {type(e).__name__}]"


async def _call_model(model_name: str, model_input: ModelInput):
    loop = asyncio.get_running_loop()
    fn = partial(client.responses.create, model=model_name, input=cast(ResponseInputParam, model_input))
    return await loop.run_in_executor(None, fn)


if (False):
    async def call_model_with_recovery(model: str, model_input: ModelInput) -> dict:
        try:
            resp = await _call_model(model, mi)  # uses your run_in_executor helper
            text = strip_zeitgeber_prefix(_extract_output_text(resp) or "")
            return {"ok": True, "text": text, "recovery": label}
        except APIStatusError as e:
            payload = _openai_error_payload(e)
            payload["recovery_step"] = label
            last_err_payload = payload


    def chat_ab():
        model_a = (req.model_a or MODEL).strip()
        model_b = (req.model_b or model_a).strip()
        ...
        async def run_one(slot: str, model_name: str):
            try:
                resp = await _call_model(model_name, model_input)
                text = strip_zeitgeber_prefix(_extract_output_text(resp) or "")
                return {"ok": True, "text": text}
            except APIStatusError as e:
                payload = _openai_error_payload(e)
                return {"ok": False, "error": payload}
            # tg.start_soon(lambda: None)  # harmless; avoids lint complaining about empty group in some editors
            #a_res = await run_one("A", model_a)
            #a_res = await call_model_with_recovery(model_a, model_input)                
            #b_res = await run_one("B", model_b)
            #b_res = await call_model_with_recovery(model_b, model_input)                
            def store(slot: str, model_name: str, res: dict):
                meta={"ab_group": ab_group, "slot": slot, "model": model_name, "kind": "ab", "recovery": res.get("recovery")}
                msg = _extract_err_msg(payload)
                meta={"ab_group": ab_group, "slot": slot, "model": model_name, "kind": "error", 
                    "recovery_step": res["error"].get("recovery_step"),
                    **payload},
                store("A", model_a, a_res)
                store("B", model_b, b_res)


if (False):
    @app.get("/api/models")
    def api_models():
        #from .db import get_conn  # if you need it; otherwise ignore
        global _MODELS_CACHE, _MODELS_CACHE_TS
        now = time.time()
        if _MODELS_CACHE and (now - _MODELS_CACHE_TS) < _MODELS_TTL_SECONDS:
            return _MODELS_CACHE
        try:
            model_objs = client.models.list()
            items: list[dict] = []
            for m in model_objs:
                mid = getattr(m, "id", None)
                if not mid:
                    continue

                if _ALLOWED_MODEL_PREFIXES and not mid.startswith(_ALLOWED_MODEL_PREFIXES):
                    continue

                meta = MODEL_CATALOG.get(mid, {})

                created = getattr(m, "created", None)
                owned_by = getattr(m, "owned_by", None)
                vendor = meta.get("vendor", "OpenAI")
                display_name = meta.get("display_name", mid)
                description = meta.get("description", "")
                input_cost = meta.get("input_cost_per_million")
                output_cost = meta.get("output_cost_per_million")
                context_window = meta.get("context_window")
                tags = meta.get("tags", [])

                items.append(
                    {
                        "id": mid,
                        "created": created,
                        "owned_by": owned_by,
                        "vendor": vendor,
                        "display_name": display_name,
                        "description": description,
                        "input_cost_per_million": input_cost,
                        "output_cost_per_million": output_cost,
                        "context_window": context_window,
                        "tags": tags,
                    }
                )

            # Sort by display_name to keep dropdowns stable
            items.sort(key=lambda m: m["display_name"].lower())
            # Save to cache to prevent constant re-query
            payload = {"models": items, "cached": True, "fetched_at": int(now)}
            _MODELS_CACHE = payload
            _MODELS_CACHE_TS = now
            return payload
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to list models: {e}")

