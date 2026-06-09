# A cheap way to estimate tokens, not very accurate but good enough for now.
import gc
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from callie_logging import log, setup_logging
from guild_config import GuildConfig
from helpers import _iso_utc
log, _log_settings = setup_logging("openai_helpers")


def est_tokens(s: str) -> int:
    return max(1, len(s) // 4)

_MARKER_RE = re.compile(r"^\s*\[(INPUT|OUTPUT|SYSTEM|ASSISTANT|USER)\]\s*:\s*", re.IGNORECASE)

def sanitize_content(txt: str) -> str:
    """
    Prevent feedback-loop markers and easy prompt injection artifacts.
    This runs ONLY on connector-owned storage and prompt construction — users cannot spoof roles/identity here.
    
    :param txt: This is the input to be screened
    :type txt: str
    :return: This is the sanitized output
    :rtype: str
    """
    if not txt:
        return ""
    # Strip only leading markers to avoid mirrored "[INPUT]:" growth without losing user content.
    return _MARKER_RE.sub("", txt, count=1)

def build_trimmed_transcript(all_msgs: List[dict], token_limit: int) -> Tuple[List[dict], List[dict[str, Any]], int]:
    # Keep the most recent messages that fit under token_limit (estimated), preserving order.
    # Returns (kept_messages, dropped_messages, kept_est_tokens).
    # dropped_messages are the oldest messages that did not fit.
    
    kept_rev: List[dict] = []
    used = 0

    for m in reversed(all_msgs):
        line = f"{m['author_name']}: {m['content']}"
        t = est_tokens(line) + 4  # overhead
        if kept_rev and (used + t) > token_limit:
            break
        if not kept_rev and t > token_limit:
            # Always keep at least one message, even if huge.
            kept_rev.append(m)
            used += t
            break
        if (used + t) <= token_limit:
            kept_rev.append(m)
            used += t
        else:
            break

    kept = list(reversed(kept_rev))
    dropped_count = max(0, len(all_msgs) - len(kept))
    dropped_msgs: List[dict] = all_msgs[:dropped_count] if dropped_count else []
    return kept, dropped_msgs, used

async def summarize_messages_block(messages: List[dict], model: str, max_output_tokens: int, *, api_key: Optional[str] = None) -> str:
    """
    Ask the model to summarize a block of raw (non-summary) messages.
    Returns summary text (markdown).
    
    :param messages: Description
    :type messages: List[dict]
    :param model: Description
    :type model: str
    :param max_output_tokens: Description
    :type max_output_tokens: int
    :param api_key: It's really not optional, is it?
    :type api_key: Optional[str]
    :return: Description
    :rtype: str
    """
    if not messages:
        return ""
    if not api_key:
        log.warning("No OpenAI API key provided for summarization. This is probably not going to work out.")

    start_ts = int(messages[0].get("created_at", 0))
    end_ts = int(messages[-1].get("created_at", 0))
    participants = sorted(set([m.get("author_name", "") for m in messages if m.get("author_name")]))

    payload = {
        "participants": participants,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "messages": [
            {
                "ts": int(m.get("created_at", 0)),
                "author": m.get("author_name", ""),
                "is_callie": bool(m.get("is_callie")),
                "content": m.get("content", ""),
            }
            for m in messages
        ],
    }

    summ_sys = (
        "You are compressing a Discord conversation log into a concise, useful summary.\n"
        "Rules:\n"
        "- Attribute important points to speakers when possible.\n"
        "- Capture key facts, decisions, commitments, and unresolved questions.\n"
        "- Include meaningful context and tone only when it affects decisions/relationships.\n"
        "- Do NOT invent information.\n"
        "- Do NOT summarize prior summaries; only summarize the provided raw messages.\n"
        "- Output markdown. Start with a header that includes participants and timestamp range, then a tight narrative.\n"
    )

    header = f"Participants: {', '.join(participants)}\nRange: {_iso_utc(start_ts)} → {_iso_utc(end_ts)}\n"
    user_text = header + "\nRAW_LOG_JSON:\n" + json.dumps(payload, ensure_ascii=False)

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload_req = {
            "model": model,
            "input": [
                {"role": "system", "content": summ_sys},
                {"role": "user", "content": user_text},
            ],
            "max_output_tokens": max_output_tokens,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload_req)
            r.raise_for_status()
            data = r.json()

        out_text: List[str] = []
        for item in data.get("output", []):
            if not isinstance(item, dict):
                continue
            for c in item.get("content", []) or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "output_text" and c.get("text"):
                    out_text.append(str(c.get("text")))
        return ("".join(out_text)).strip()
    except Exception as e:
        log.error(f"Summary call failed: {e}")
        return ""

async def openai_respond(
    system_prompt: str,
    memory_blob: str,
    transcript: List[dict],
    server_ctx: str,
    ctx_notice: str,
    max_output_tokens: int,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    extra_content_parts: Optional[List[Dict]] = None,
) -> Tuple[str, str]:
    api_key_to_use = (api_key if api_key is not None else "").strip()
    model_to_use = (model if model is not None else "gpt-4o-mini").strip() 
    ## we used to use else (os.getenv("OPENAI_API_KEY") / else (os.getenv("OPENAI_MODEL") but we are moving away from doing that
    # model to use defaults to being stupid...
    if model is None:
        log.warning("No OpenAI model specified; defaulting to gpt-4o-mini.")
    if not api_key or api_key_to_use == "":
        log.error("OpenAI API key is missing!")
        return "Sorry, nobody put in an Open AI key yet. Tell the server admin to fix the configuration.", "0"
    headers = {
        "Authorization": f"Bearer {api_key_to_use}",
        "Content-Type": "application/json",
    }

    chatlog_lines: List[str] = []
    for m in transcript:
        who = "Callie" if m["is_callie"] else m["author_name"]
        chatlog_lines.append(f"[{who}|id:{m['author_id']}]: {m['content']}")

    full_input = system_prompt
    if memory_blob:
        full_input += "\n\n" + memory_blob

    full_input += "\n\nServer context (not user-provided):\n" + server_ctx.strip() + "\n"

    if ctx_notice.strip():
        full_input += "\n\nContext notice (connector-generated):\n" + ctx_notice.strip() + "\n"

    full_input += "\n\nRecent transcript:\n" + "\n".join(chatlog_lines)

    est_input_tokens = est_tokens(full_input)

    # Use the structured Responses API input format so we can attach files/images.
    # Text-only is still supported by passing a single input_text part.
    content_parts: List[Dict] = [{"type": "input_text", "text": full_input}]
    if extra_content_parts:
        content_parts.extend(extra_content_parts)

    payload = {
        "model": model_to_use,
        "input": [
            {
                "role": "user",
                "content": content_parts,
            }
        ],
        "max_output_tokens": max_output_tokens,
    }

    t0 = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post("https://api.openai.com/v1/responses", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
    dt_ms = int((time.time() - t0) * 1000)

    response_id = str(data.get("id", ""))

    out_text: List[str] = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    out_text.append(c.get("text", ""))

    text = "".join(out_text).strip() or "(no output)"
    log.info(
        f"OpenAI ok response_id={response_id} dt_ms={dt_ms} "
        f"in_est_tokens≈{est_input_tokens} out_chars={len(text)} model={model_to_use} max_out_tokens={max_output_tokens}"
    )
    return text, response_id

async def openai_upload_file(
        data: bytes, 
        filename: str, 
        purpose: str = "user_data", *, 
        api_key: Optional[str] = None
        ) -> str:
    """
    Upload a file to OpenAI Files API and return the file id.
    Note: This is primarily for non-PDF/non-image attachments. PDFs/images under
    50 MB are sent inline via base64 content parts.
    """
    # We are NOT using guild_config here because this is a helper function.
    #if not (await gc.openai_api_key()):
    #    raise RuntimeError("(await gc.openai_api_key()) missing")
    api_key_to_use = (api_key if api_key is not None else "").strip()
    if not api_key_to_use or api_key_to_use == "":
        log.error("OpenAI API key is missing!")
        return "Sorry, nobody put in an Open AI key yet. Tell the server admin to fix the configuration."

    headers = {
        "Authorization": f"Bearer {api_key_to_use}",
    }

    # Multipart form-data: purpose + file
    files = {
        "file": (filename, data),
    }
    form = {
        "purpose": purpose,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post("https://api.openai.com/v1/files", headers=headers, data=form, files=files)
        r.raise_for_status()
        j = r.json()
    return str(j.get("id", ""))

