from __future__ import annotations
#from http import client
from openai import OpenAI, APIStatusError


import re
from typing import List, Any, Callable
from .config import SummaryConfig, load_openai_config

oai_cfg = load_openai_config()

#from openai import OpenAI, APIStatusError

def extract_response_text(resp) -> str:
    """
    Best-effort extraction of assistant text from OpenAI Responses API result.
    """
    try:
        txt = getattr(resp, "output_text", None)
        if txt and str(txt).strip():
            return str(txt).strip()
    except Exception:
        pass

    parts: list[str] = []

    try:
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) != "message":
                continue

            for c in getattr(item, "content", []) or []:
                c_type = getattr(c, "type", None)

                if c_type == "output_text":
                    text = getattr(c, "text", None)
                    if text:
                        parts.append(str(text))
                elif c_type == "text":
                    text = getattr(c, "text", None)
                    if text:
                        parts.append(str(text))
                    else:
                        value = getattr(c, "value", None)
                        if value:
                            parts.append(str(value))
                else:
                    text = getattr(c, "text", None)
                    value = getattr(c, "value", None)
                    if text:
                        parts.append(str(text))
                    elif value:
                        parts.append(str(value))
    except Exception:
        pass

    return "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()


def cleanup_summary_text(text: str) -> str:
    """
    Strip stupid decoration the model insists on adding.
    """
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""

    # Trim leading blank lines
    lines = [ln.rstrip() for ln in s.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)

    if not lines:
        return ""

    # Remove leading markdown heading marks
    lines[0] = re.sub(r"^\s*#{1,6}\s*", "", lines[0], flags=re.IGNORECASE)

    # Remove leading Summary / Summary: / Summary - / **Summary**
    lines[0] = re.sub(
        r"^\s*(?:\*\*)?\s*summary(?:\s+of\b.*)?\s*(?:\*\*)?\s*[:\-–—]?\s*",
        "",
        lines[0],
        flags=re.IGNORECASE,
    )

    # If the first line is just bold wrapper, strip it
    lines[0] = re.sub(r"^\s*\*\*(.*?)\*\*\s*$", r"\1", lines[0])

    # Remove empty leading lines again
    while lines and not lines[0].strip():
        lines.pop(0)

    s = "\n".join(lines).strip()

    # Collapse giant blank streaks
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def _call_summary_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    complete_fn: Callable[[str, str, int], str] | None = None,
    client=None,
) -> str:
    if complete_fn is not None:
        raw = complete_fn(system_prompt, user_prompt, max_output_tokens)
        return cleanup_summary_text(raw)

    if client is None:
        raise RuntimeError("No completion path provided for summary model call.")

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=max_output_tokens,
    )
    return cleanup_summary_text(extract_response_text(resp))

if (False):
    def _call_summary_model(client, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int) -> str:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_output_tokens=max_output_tokens,
        )
        return cleanup_summary_text(extract_response_text(resp))


def _chunk_transcript(text: str, target_chars: int, hard_max_chars: int) -> List[str]:
    """
    Split on paragraph boundaries first, keeping speaker turns intact where possible.
    """
    t = (text or "").strip()
    if not t:
        return []

    paras = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if not paras:
        return [t[:hard_max_chars]]

    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    def flush():
        nonlocal cur, cur_len
        if cur:
            chunks.append("\n\n".join(cur).strip())
        cur = []
        cur_len = 0

    for p in paras:
        plen = len(p)
        if plen > hard_max_chars:
            # paragraph too big: split on speaker-ish lines or sentences
            lines = [ln.strip() for ln in p.split("\n") if ln.strip()]
            if not lines:
                lines = [p]

            buf = ""
            for ln in lines:
                candidate = (buf + "\n" + ln).strip() if buf else ln
                if buf and len(candidate) > hard_max_chars:
                    chunks.append(buf.strip())
                    buf = ln
                else:
                    buf = candidate
            if buf.strip():
                chunks.append(buf.strip())
            continue

        candidate_len = cur_len + (2 if cur else 0) + plen
        if cur and candidate_len > target_chars:
            flush()

        cur.append(p)
        cur_len += (2 if cur_len else 0) + plen

    flush()
    return [c for c in chunks if c.strip()]


def _one_pass_conversation_summary(
    *,
    model: str,
    title: str,
    transcript: str,
    cfg: SummaryConfig,
    system_prompt: str,
    complete_fn: Callable[[str, str, int], str] | None = None,
    client=None,
) -> str:
    base_user_prompt = (
        f"Title: {title}\n\n"
        f"Full transcript follows. Read all of it before writing.\n\n"
        f"Return only the summary text.\n"
        f"Do not use headings, bullets, markdown, or a 'Summary:' prefix.\n\n"
        f"{transcript}"
    )

    summary = _call_summary_model(
        model=model,
        system_prompt=system_prompt,
        user_prompt=base_user_prompt,
        max_output_tokens=cfg.summary_max_tokens,
        complete_fn=complete_fn,
        client=client,
    )
    if summary:
        return summary

    retry_prompt = (
        "You are writing a plain-text archival summary of a conversation.\n"
        "This is not a chat reply.\n"
        "Do not ask questions.\n"
        "Do not use markdown, headings, bullets, or any 'Summary:' prefix.\n"
        "Summarize the conversation as a whole in chronological order.\n"
        "Mention major topics, decisions, useful facts, and unresolved questions.\n"
        "Output only the summary text."
    )
    return _call_summary_model(
        model=model,
        system_prompt=retry_prompt,
        user_prompt=base_user_prompt,
        max_output_tokens=cfg.summary_max_tokens,
        complete_fn=complete_fn,
        client=client,
    )

if (False):
    def _one_pass_conversation_summary(*, client, model: str, title: str, transcript: str, cfg: SummaryConfig, system_prompt: str) -> str:
        base_user_prompt = (
            f"Title: {title}\n\n"
            f"Full transcript follows. Read all of it before writing.\n\n"
            f"Return only the summary text.\n"
            f"Do not use headings, bullets, markdown, or a 'Summary:' prefix.\n\n"
            f"{transcript}"
        )

        summary = _call_summary_model(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=base_user_prompt,
            max_output_tokens=cfg.summary_max_tokens,
        )
        if summary:
            return summary

        retry_prompt = (
            "You are writing a plain-text archival summary of a conversation.\n"
            "This is not a chat reply.\n"
            "Do not ask questions.\n"
            "Do not use markdown, headings, bullets, or any 'Summary:' prefix.\n"
            "Summarize the conversation as a whole in chronological order.\n"
            "Mention major topics, decisions, useful facts, and unresolved questions.\n"
            "Output only the summary text."
        )
        summary = _call_summary_model(
            client=client,
            model=model,
            system_prompt=retry_prompt,
            user_prompt=base_user_prompt,
            max_output_tokens=cfg.summary_max_tokens,
        )
        return summary


def summarize_conversation_text(
    *,
    model: str,
    title: str,
    transcript: str,
    cfg: SummaryConfig,
    system_prompt: str,
    complete_fn: Callable[[str, str, int], str] | None = None,
    client=None,
) -> str:
    """
    One-pass for short transcripts, map-reduce for long transcripts.
    Supports either:
      - complete_fn(system_prompt, user_prompt, max_output_tokens) -> str
      - legacy client + model path
    """
    transcript = (transcript or "").strip()
    if not transcript:
        raise RuntimeError("empty transcript")

    if len(transcript) <= cfg.summary_reduce_threshold_chars:
        summary = _one_pass_conversation_summary(
            model=model,
            title=title,
            transcript=transcript,
            cfg=cfg,
            system_prompt=system_prompt,
            complete_fn=complete_fn,
            client=client,
        )
        if summary:
            return summary
        raise RuntimeError(f"empty summary (title={title!r}, transcript_chars={len(transcript)})")

    chunks = _chunk_transcript(
        transcript,
        target_chars=cfg.summary_chunk_target_chars,
        hard_max_chars=cfg.summary_chunk_hard_max_chars,
    )
    if not chunks:
        raise RuntimeError("failed to chunk transcript")

    partials: List[str] = []
    chunk_system_prompt = (
        "You are generating an intermediate factual summary of part of a conversation.\n"
        "This is not a chat reply.\n"
        "Do not ask questions.\n"
        "Do not add headings, bullets, markdown, titles, or 'Summary:' prefixes.\n"
        "Summarize only what appears in this chunk.\n"
        "Capture important facts, decisions, and unresolved questions.\n"
        "Use plain text only."
    )

    for idx, chunk in enumerate(chunks, start=1):
        chunk_user_prompt = (
            f"Conversation title: {title}\n\n"
            f"This is chunk {idx} of {len(chunks)} from a longer conversation.\n"
            f"Summarize this chunk only.\n\n"
            f"{chunk}"
        )

        part = _call_summary_model(
            model=model,
            system_prompt=chunk_system_prompt,
            user_prompt=chunk_user_prompt,
            max_output_tokens=cfg.summary_chunk_max_tokens,
            complete_fn=complete_fn,
            client=client,
        )

        if part:
            partials.append(f"[Chunk {idx}/{len(chunks)}]\n{part}")

    if not partials:
        fallback = _one_pass_conversation_summary(
            model=model,
            title=title,
            transcript=transcript,
            cfg=cfg,
            system_prompt=system_prompt,
            complete_fn=complete_fn,
            client=client,
        )
        if fallback:
            return fallback
        raise RuntimeError(
            f"all chunk summaries were empty (title={title!r}, transcript_chars={len(transcript)}, chunks={len(chunks)})"
        )

    reduce_user_prompt = (
        f"Title: {title}\n\n"
        "Below are partial summaries of a longer conversation.\n"
        "Write one final plain-text conversation summary.\n"
        "Cover the whole conversation in chronological order.\n"
        "Mention major topic shifts, decisions, useful facts, and unresolved questions.\n"
        "Do not use headings, bullets, markdown, titles, or any 'Summary:' prefix.\n\n"
        + "\n\n".join(partials)
    )

    final_summary = _call_summary_model(
        model=model,
        system_prompt=system_prompt,
        user_prompt=reduce_user_prompt,
        max_output_tokens=cfg.summary_max_tokens,
        complete_fn=complete_fn,
        client=client,
    )

    if final_summary:
        return final_summary

    fallback = _one_pass_conversation_summary(
        model=model,
        title=title,
        transcript=transcript,
        cfg=cfg,
        system_prompt=system_prompt,
        complete_fn=complete_fn,
        client=client,
    )
    if fallback:
        return fallback

    raise RuntimeError(
        f"empty final summary after map-reduce (title={title!r}, transcript_chars={len(transcript)}, chunks={len(chunks)})"
    )

if (False):
    def summarize_conversation_text(
        model: str,
        title: str,
        transcript: str,
        cfg: SummaryConfig,
        system_prompt: str
    ) -> str:
        # temporary stub to facilitate disconnection in main.py
        client = OpenAI(api_key=oai_cfg.open_ai_apikey)

        """
        One-pass for short transcripts, map-reduce for long transcripts.
        """
        transcript = (transcript or "").strip()
        if not transcript:
            raise RuntimeError("empty transcript")

        base_user_prompt = (
            f"Title: {title}\n\n"
            f"Full transcript follows. Read all of it before writing.\n\n"
            f"Return only the summary text.\n"
            f"Do not use headings, bullets, markdown, or a 'Summary:' prefix.\n\n"
            f"{transcript}"
        )

        # One-pass for shorter conversations
        if len(transcript) <= cfg.summary_reduce_threshold_chars:
            summary = _one_pass_conversation_summary(
                client=client,
                model=model,
                title=title,
                transcript=transcript,
                cfg=cfg,
                system_prompt=system_prompt,
            )
            if summary:
                return summary
            raise RuntimeError(f"empty summary (title={title!r}, transcript_chars={len(transcript)})")

        # Map-reduce for long transcripts
        chunks = _chunk_transcript(
            transcript,
            target_chars=cfg.summary_chunk_target_chars,
            hard_max_chars=cfg.summary_chunk_hard_max_chars,
        )
        if not chunks:
            raise RuntimeError("failed to chunk transcript")

        partials: List[str] = []
        chunk_system_prompt = (
            "You are generating an intermediate factual summary of part of a conversation.\n"
            "This is not a chat reply.\n"
            "Do not ask questions.\n"
            "Do not add headings, bullets, markdown, titles, or 'Summary:' prefixes.\n"
            "Summarize only what appears in this chunk.\n"
            "Capture important facts, decisions, and unresolved questions.\n"
            "Use plain text only."
        )

        for idx, chunk in enumerate(chunks, start=1):
            chunk_user_prompt = (
                f"Conversation title: {title}\n\n"
                f"This is chunk {idx} of {len(chunks)} from a longer conversation.\n"
                f"Summarize this chunk only.\n\n"
                f"{chunk}"
            )

            part = _call_summary_model(
                client=client,
                model=model,
                system_prompt=chunk_system_prompt,
                user_prompt=chunk_user_prompt,
                max_output_tokens=cfg.summary_chunk_max_tokens,
            )

            if part:
                partials.append(f"[Chunk {idx}/{len(chunks)}]\n{part}")

        if not partials:
            # Cheap models sometimes flake out on the map step.
            # Fall back to one-pass instead of hard-failing.
            fallback = _one_pass_conversation_summary(
                client=client,
                model=model,
                title=title,
                transcript=transcript,
                cfg=cfg,
                system_prompt=system_prompt,
            )
            if fallback:
                return fallback
            raise RuntimeError(
                f"all chunk summaries were empty (title={title!r}, transcript_chars={len(transcript)}, chunks={len(chunks)})"
            )

        reduce_user_prompt = (
            f"Title: {title}\n\n"
            "Below are partial summaries of a longer conversation.\n"
            "Write one final plain-text conversation summary.\n"
            "Cover the whole conversation in chronological order.\n"
            "Mention major topic shifts, decisions, useful facts, and unresolved questions.\n"
            "Do not use headings, bullets, markdown, titles, or any 'Summary:' prefix.\n\n"
            + "\n\n".join(partials)
        )

        final_summary = _call_summary_model(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=reduce_user_prompt,
            max_output_tokens=cfg.summary_max_tokens,
        )

        if final_summary:
            return final_summary

        fallback = _one_pass_conversation_summary(
            client=client,
            model=model,
            title=title,
            transcript=transcript,
            cfg=cfg,
            system_prompt=system_prompt,
        )
        if fallback:
            return fallback

        raise RuntimeError(
            f"empty final summary after map-reduce (title={title!r}, transcript_chars={len(transcript)}, chunks={len(chunks)})"
        )
    

def cleanup_title_text(text: str, fallback: str = "New chat") -> str:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return fallback

    s = s.split("\n", 1)[0].strip()
    s = re.sub(r"^\s*#{1,6}\s*", "", s)
    s = re.sub(r"^\s*(?:title|suggested title)\s*[:\-–—]\s*", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("\"'`“”‘’")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[.?!:;\-–—\s]+$", "", s).strip()

    if len(s) > 80:
        s = s[:80].rsplit(" ", 1)[0].strip() or s[:80].strip()

    return s or fallback


def suggest_conversation_title_from_transcript(
    *,
    model: str,
    transcript: str,
    current_title: str = "",
    complete_fn: Callable[[str, str, int], str] | None = None,
    client=None,
    max_output_tokens: int = 48,
) -> str:
    text = (transcript or "").strip()
    if not text:
        return cleanup_title_text(current_title or "New chat")

    if len(text) > 12000:
        head = text[:6000].strip()
        tail = text[-6000:].strip()
        text = f"{head}\n\n[...]\n\n{tail}"

    system_prompt = (
        "You write short, useful conversation titles for a chat sidebar.\n"
        "Return only the title text.\n"
        "No quotes.\n"
        "No markdown.\n"
        "No leading labels like 'Title:'.\n"
        "Prefer 3 to 8 words.\n"
        "Be concrete and specific."
    )

    user_prompt = (
        f"Current title: {current_title or 'New chat'}\n\n"
        "Based on this conversation transcript, suggest a better short title.\n\n"
        f"{text}"
    )

    if complete_fn is not None:
        raw = complete_fn(system_prompt, user_prompt, max_output_tokens)
        return cleanup_title_text(raw, fallback=current_title or "New chat")

    if client is None:
        raise RuntimeError("No completion path provided for title suggestion.")

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_output_tokens=max_output_tokens,
    )
    return cleanup_title_text(extract_response_text(resp), fallback=current_title or "New chat")