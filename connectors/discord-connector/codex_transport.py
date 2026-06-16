from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from callie_logging import setup_logging
from cost_tracking import CostTelemetryConfig, calculate_usage_cost, format_cost_log
from provider_backends import ConnectorProviderConfig, resolve_oauth_tokens

log, _log_settings = setup_logging("codex_transport")

CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_AUTH_CLAIM = "https://api.openai.com/auth"
CODEX_UNSUPPORTED_PAYLOAD_FIELDS = {
    # OpenClaw's native Codex transport does not send this Responses API field.
    "max_output_tokens",
}


def _decode_jwt_payload(token: str) -> Dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
        parsed = json.loads(decoded)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def extract_codex_account_id(token: str) -> str:
    auth = _decode_jwt_payload(token).get(CODEX_AUTH_CLAIM)
    if isinstance(auth, dict):
        account_id = auth.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    raise RuntimeError("Could not extract ChatGPT account id from OAuth token.")


def _headers(access_token: str, account_id: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "chatgpt-account-id": account_id,
        "originator": "wyrmgpt-discord-connector",
        "User-Agent": "wyrmgpt-discord-connector",
        "OpenAI-Beta": "responses=experimental",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


def _iter_sse_events(text: str):
    for chunk in text.split("\n\n"):
        data_lines = []
        for line in chunk.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        data = "\n".join(data_lines).strip()
        if not data or data == "[DONE]":
            continue
        try:
            parsed = json.loads(data)
        except Exception:
            log.warning("Codex SSE event was not JSON; ignoring.")
            continue
        if isinstance(parsed, dict):
            yield parsed


def _extract_text_from_response(response: Dict[str, Any]) -> str:
    parts: List[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") == "output_text" and content.get("text"):
                    parts.append(str(content.get("text")))
    return "".join(parts).strip()


def _unsupported_parameter_from_message(message: str) -> str:
    match = re.search(r"Unsupported parameter:\s*[`'\"]?([A-Za-z_][A-Za-z0-9_]*)", message)
    if not match:
        return ""
    return match.group(1)


def _codex_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in CODEX_UNSUPPORTED_PAYLOAD_FIELDS}


def _extract_text_from_events(events: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
    deltas: List[str] = []
    final_response: Dict[str, Any] = {}
    for event in events:
        event_type = str(event.get("type") or "")
        if event_type in {"response.output_text.delta", "response.text.delta"} and event.get("delta"):
            deltas.append(str(event.get("delta")))
        if event_type in {"response.completed", "response.done", "response.incomplete"}:
            response = event.get("response")
            if isinstance(response, dict):
                final_response = response
        if event_type == "response.failed":
            response = event.get("response")
            if isinstance(response, dict):
                error = response.get("error")
                if isinstance(error, dict):
                    raise RuntimeError(str(error.get("message") or error.get("code") or "Codex response failed"))
            raise RuntimeError("Codex response failed")
        if event_type == "error":
            raise RuntimeError(str(event.get("message") or event.get("code") or "Codex transport error"))
    final_text = _extract_text_from_response(final_response) if final_response else ""
    return final_text or "".join(deltas).strip(), final_response


async def codex_respond(
    system_prompt: str,
    full_input: str,
    content_parts: List[Dict[str, Any]],
    max_output_tokens: int,
    *,
    provider_config: ConnectorProviderConfig,
    model: str,
    cost_telemetry: Optional[CostTelemetryConfig] = None,
) -> Tuple[str, str]:
    tokens = resolve_oauth_tokens(provider_config)
    if not tokens.has_access:
        raise RuntimeError("OPENAI_OAUTH_TOKEN or OPENAI_OAUTH_TOKEN_PATH is missing.")
    account_id = extract_codex_account_id(tokens.access_token)
    payload = _codex_payload({
        "model": model,
        "store": False,
        "stream": True,
        "instructions": system_prompt or "You are a helpful assistant.",
        "input": [{"role": "user", "content": content_parts}],
        "max_output_tokens": max_output_tokens,
    })

    t0 = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        removed_fields: List[str] = []
        while True:
            response = await client.post(
                CODEX_RESPONSES_URL,
                headers=_headers(tokens.access_token, account_id),
                json=payload,
            )
            body_text = response.text
            if response.status_code < 400:
                break
            try:
                parsed_error = response.json()
                err = parsed_error.get("error", {}) if isinstance(parsed_error, dict) else {}
                message = err.get("message") or err.get("code") or parsed_error.get("detail") or body_text
            except Exception:
                message = body_text
            unsupported = _unsupported_parameter_from_message(str(message))
            if response.status_code == 400 and unsupported and unsupported in payload and unsupported not in removed_fields:
                payload = dict(payload)
                payload.pop(unsupported, None)
                removed_fields.append(unsupported)
                log.warning("Codex transport removed unsupported payload field and retrying: %s", unsupported)
                continue
            raise RuntimeError(f"Codex transport failed: HTTP {response.status_code} {message}")

    events = list(_iter_sse_events(body_text))
    text, final_response = _extract_text_from_events(events)
    response_id = str(final_response.get("id") or "")
    text = text or "(no output)"
    cost_log = ""
    if cost_telemetry is not None and cost_telemetry.enabled and final_response:
        cost_log = " " + format_cost_log(calculate_usage_cost(final_response, model, cost_telemetry))
    log.info(
        "Codex ok response_id=%s dt_ms=%s input_chars=%s out_chars=%s model=%s max_out_tokens=%s%s",
        response_id,
        int((time.time() - t0) * 1000),
        len(full_input),
        len(text),
        model,
        max_output_tokens,
        cost_log,
    )
    return text, response_id
