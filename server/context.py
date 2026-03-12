from datetime import datetime, timezone
import json
import os
#from typing import cast
from pathlib import Path
import re

from .logging_helper import log_debug, log_warn
from .db import (
    get_app_setting,
    get_conversation_summary_text,
    get_messages,
    get_context_sources,
    list_memory_pins,
    # list_files_for_conversation,
    # list_files_for_project,
    # list_all_files,
    list_artifacts_for_file,
    ensure_artifacts_for_files,
    gather_scoped_files,
    ensure_conversation_transcript_artifact_fresh,
    list_memories,
    list_conversations,
    load_artifact_row_for_context,
    memory_artifact_id,
    conversation_summary_artifact_id,
    conversation_transcript_artifact_id,
    db_session,
    hydrate_artifact_content_text,    
    
)

from .config import (
    CoreConfig, load_core_config, 
    ContextConfig, load_context_config,
    RetrievalConfig, load_retrieval_config, 
    QUERY_INCLUDE_ALLOWED, QUERY_EXPAND_ALLOWED,
    _normalize_csv_set,
    load_embedding_config, load_vector_config
)
# TODO untagle dependencies later if needed
# Now artifactor is used entirely from the database layer
# from .artifactor import artifact_file
from .image_helpers import load_image_bytes, image_bytes_to_base64
from .query_retrieval import retrieve_chunks_for_message
try:
    import tiktoken
except ImportError:
    tiktoken = None

# From openai/types/responses/response_create_params.py
# from openai.types.responses import ResponseInputParam

from .query_shaper import WORD_RE, load_filler_words_cached

_QUERY_WORD_RE = WORD_RE
_QUERY_STOP = load_filler_words_cached()

def _get_prompt(default_prompt: str, filepath: str = "", cfg_default="(cfg default)", cfg_filepath="(cfg filepath name)") -> str:
    """
    Loads a given prompt in this precedence order:
    1) filepath (read text file)
    2) default_prompt (fallback from cfg values, supports literal '\\n' sequences)
    """
    if filepath:
        raw = Path(filepath)

        candidates = []
        if raw.is_absolute():
            candidates.append(raw)
        else:
            candidates.append(raw)
            candidates.append(Path.cwd() / raw)
            candidates.append(Path(__file__).resolve().parents[1] / raw)  # repo root / relative path

        for p in candidates:
            try:
                if p.exists() and p.is_file():
                    log_debug("Loaded prompt from file %s (%s)", cfg_filepath, p)
                    return p.read_text(encoding="utf-8")
            except Exception as e:
                log_warn("Failed reading prompt file %s from %s: %s", cfg_filepath, p, e)

    log_debug("No valid %s found, falling back to %s", cfg_filepath, cfg_default)
    val = default_prompt or ""
    val = val.replace("\\n", "\n")
    return val

def _effective_query_setting(project_id: int | None, key: str, fallback: str) -> str:
    if project_id is not None:
        v = get_app_setting(f"query.{key}", None, "project", str(project_id))
        if v is not None and str(v).strip() != "":
            return str(v)
    v = get_app_setting(f"query.{key}", None, "global", "")
    if v is not None and str(v).strip() != "":
        return str(v)
    return fallback

def get_system_prompt(cfg: CoreConfig | None = None) -> str:
    """
    Loads system prompt from cfg in this precedence order:
    1) SYSTEM_PROMPT_FILE (read text file)
    2) SYSTEM_PROMPT (env var, supports literal '\n' sequences)
    3) fallback to hardcoded string in CoreConfig
    """
    cfg = cfg or load_core_config()
    return _get_prompt(
        cfg.default_system_prompt,
        cfg.system_prompt_file,
        cfg_default="SYSTEM_PROMPT",
        cfg_filepath="SYSTEM_PROMPT_FILE",
    )

def iso_to_epoch_ms(iso: str) -> int:
    """Handles "2026-02-28T23:15:12.140213+00:00" cleanly"""
    # Accepts "Z" or "+00:00"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    # If the timestamp is naive, treat it as UTC (NOT local)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Convert to UTC explicitly, then epoch
    dt_utc = dt.astimezone(timezone.utc)
    return int(dt_utc.timestamp() * 1000)

def iso_to_compact_utc(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")

def iso_to_age_seconds(iso: str) -> int:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, int((now - dt).total_seconds()))

def _excerpt_around_query(text: str, query: str | None, *, max_chars: int) -> str:
    full = (text or "").strip()
    if len(full) <= max_chars:
        return full

    q = (query or "").strip()
    candidates: list[str] = []

    if q:
        for m in re.finditer(r"\"([^\"]+)\"|'([^']+)'", q):
            phrase = (m.group(1) or m.group(2) or "").strip()
            if len(phrase) >= 4:
                candidates.append(phrase)

        for tok in _QUERY_WORD_RE.findall(q):
            tl = tok.lower()
            if len(tok) >= 3 and tl not in _QUERY_STOP:
                candidates.append(tok)

    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(c)

    hay = full.lower()
    for needle in sorted(ordered, key=len, reverse=True):
        idx = hay.find(needle.lower())
        if idx < 0:
            continue

        half = max_chars // 2
        start = max(0, idx - half)
        end = min(len(full), start + max_chars)
        start = max(0, end - max_chars)

        snippet = full[start:end].strip()
        if start > 0:
            snippet = "[...]\n" + snippet
        if end < len(full):
            snippet = snippet + "\n[...]"
        return snippet

    return full[:max_chars] + f"\n[...truncated chunk; max_chars={max_chars}]"


def _format_retrieved_chunks(
    rows: list[dict],
    *,
    max_chunks: int = 8,
    max_chars: int = 2200,
    excerpt_query: str | None = None,
) -> tuple[str, list[dict], list[str]]:
    """
    Returns:
      - block_text: ready to paste into system prompt (includes provenance headers + chunk text)
      - meta: structured per-chunk metadata for UI / later expansion
      - cites: short single-line citations
    """
    block_parts: list[str] = []
    meta: list[dict] = []
    cites: list[str] = []

    for r in (rows or [])[:max_chunks]:
        full_text = (r.get("text") or "").strip()
        if not full_text:
            continue

        text = _excerpt_around_query(full_text, excerpt_query, max_chars=max_chars)
        chat_prefix = _build_chat_chunk_context_prefix(r)

        chunk_id = r.get("chunk_id")
        artifact_id = r.get("artifact_id")
        chunk_index = r.get("chunk_index")
        score = r.get("score")
        filename = r.get("filename")
        scope_key = r.get("scope_key")
        source_kind = r.get("source_kind")
        source_id = r.get("source_id")
        file_id = r.get("file_id")
        mime_type = r.get("mime_type")
        src_label = filename or scope_key or source_kind or "source"

        artifact_title = r.get("artifact_title")
        artifact_updated_at = r.get("artifact_updated_at")
        file_created_at = r.get("file_created_at")
        file_updated_at = r.get("file_updated_at")

        ts = artifact_updated_at or file_updated_at or file_created_at
        age = None
        if ts:
            try:
                age = iso_to_age_seconds(ts)
            except Exception:
                age = None

        header = (
            f"[chunk_id={chunk_id} score={score} ts={ts} age={age} "
            f"src={src_label} artifact_id={artifact_id} chunk_index={chunk_index} file_id={file_id}]"
        )

        # block_parts.append(header + "\n" + text)
        block_body = text
        if chat_prefix:
            block_body = f"{chat_prefix}\n\n{text}"
        block_parts.append(header + "\n" + block_body)

        meta.append({
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "score": score,
            "artifact_id": artifact_id,
            "artifact_title": artifact_title,
            "artifact_updated_at": artifact_updated_at,
            "scope_key": scope_key,
            "source_kind": source_kind,
            "source_id": source_id,
            "file_id": file_id,
            "filename": filename,
            "file_created_at": file_created_at,
            "file_updated_at": file_updated_at,
            "mime_type": mime_type,
            "conversation_id": r.get("conversation_id"),
            "conversation_title": r.get("conversation_title"),
            "conversation_summary_excerpt": r.get("conversation_summary_excerpt"),
            "conversation_started_at": r.get("conversation_started_at"),
            "conversation_ended_at": r.get("conversation_ended_at"),
            "preview_text": text,
            "full_text_chars": len(full_text),
        })

        cites.append(f"{src_label}#{chunk_index} (chunk_id={chunk_id})")

    return ("\n\n".join(block_parts)).strip(), meta, cites

def _format_conversation_range(started_at: str | None, ended_at: str | None) -> str:
    start = (started_at or "").strip()
    end = (ended_at or "").strip()
    if start and end:
        return f"{start} → {end}"
    if start:
        return start
    if end:
        return end
    return ""

def _build_chat_chunk_context_prefix(r: dict) -> str:
    source_kind = (r.get("source_kind") or "").strip().lower()
    artifact_id = (r.get("artifact_id") or "").strip()

    is_chat = (
        artifact_id.startswith("conversation_transcript--")
        or source_kind in ("conversation:transcript", "conversation_transcript")
    )
    if not is_chat:
        return ""

    title = (r.get("conversation_title") or "").strip()
    summary = (r.get("conversation_summary_excerpt") or "").strip()
    started_at = r.get("conversation_started_at")
    ended_at = r.get("conversation_ended_at")
    dt_range = _format_conversation_range(started_at, ended_at)

    lines = ["[CHAT CONTEXT]"]
    if title:
        lines.append(f"Conversation: {title}")
    if dt_range:
        lines.append(f"Range: {dt_range}")
    if summary:
        lines.append(f"Summary: {summary}")

    return "\n".join(lines).strip()

def _select_other_project_conversation_rows_for_context(
    conversation_id: str,
    project_id: int | None,
    *,
    limit: int,
) -> list[dict]:
    if project_id is None or limit <= 0:
        return []

    rows = list_conversations(limit=max(limit * 8, 200), include_archived=False)
    out: list[dict] = []

    for c in rows:
        if str(c.get("id") or "").strip() == str(conversation_id).strip():
            continue
        if int(c.get("project_id") or 0) != int(project_id):
            continue
        out.append(c)
        if len(out) >= limit:
            break

    return out

def _conversation_span_map(conn, conversation_ids: list[str]) -> dict[str, tuple[str | None, str | None]]:
    if not conversation_ids:
        return {}

    placeholders = ",".join("?" * len(conversation_ids))
    rows = conn.execute(
        f"""
        SELECT
            conversation_id,
            MIN(created_at) AS started_at,
            MAX(created_at) AS ended_at
        FROM messages
        WHERE conversation_id IN ({placeholders})
        GROUP BY conversation_id
        """,
        tuple(conversation_ids),
    ).fetchall()

    return {
        str(r["conversation_id"]): (r["started_at"], r["ended_at"])
        for r in rows
    }

def _conversation_summary_to_input_message(
    *,
    conversation_id: str,
    title: str,
    summary_text: str,
    started_at: str | None,
    ended_at: str | None,
    artifact_id: str,
) -> dict:
    dt_range = _format_conversation_range(started_at, ended_at)

    lines = ["SCOPED CHAT SUMMARY"]
    if title:
        lines.append(f"Conversation: {title}")
    if dt_range:
        lines.append(f"Range: {dt_range}")
    if artifact_id:
        lines.append(f"Artifact ID: {artifact_id}")
    lines.append("")
    lines.append(summary_text.strip())

    return {"role": "user", "content": "\n".join(lines).strip()}

def zeitgeber_prefix(created_at: str, raw_content: str) -> str:
    stamp = iso_to_compact_utc(created_at)
    age = iso_to_age_seconds(created_at)
    text = f"⟂t={stamp} ⟂age={age}\n{raw_content}"
    return text

def estimate_tokens_for_messages(messages: list[dict], model: str = "gpt-4.1-mini") -> dict:
    """
    Rough token estimate for a list of messages.

    Counts:
      - total characters in text
      - approximate token count using tiktoken if available
      - number of image inputs (we just count them; their actual billing is resolution-based)
    """
    total_chars = 0
    num_images = 0
    text_pieces: list[str] = []

    for msg in messages:
        content = msg.get("content")

        # Legacy: plain string content
        if isinstance(content, str):
            total_chars += len(content)
            text_pieces.append(content)
            continue

        # Responses-style: list of input items
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                itype = item.get("type")
                if itype == "input_text":
                    text = item.get("text") or ""
                    total_chars += len(text)
                    text_pieces.append(text)
                elif itype == "input_image":
                    num_images += 1

    approx_tokens = None
    if tiktoken is not None and text_pieces:
        try:
            enc = tiktoken.encoding_for_model(model)
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")
        joined = "\n".join(text_pieces)
        approx_tokens = len(enc.encode(joined))

    return {
        "total_chars": total_chars,
        "approx_text_tokens": approx_tokens,
        "num_images": num_images,
    }

def estimate_context_tokens(
    conversation_id: str,
    ctx_cfg: ContextConfig, #history_limit: int = 200,
    addtl_user_text: str = "",
    model: str = "gpt-5.2",
    drop_last_user_message: bool = False,
) -> dict:
    """
    Estimate tokens for the context that will be sent with the next user message,
    excluding that next user message itself.
    """
    full_input = build_model_input(conversation_id, addtl_user_text, ctx_cfg)
    if not full_input:
        return {"total_chars": 0, "approx_text_tokens": 0, "num_images": 0}

    # Optionally, Drop the last message (most recent user turn) so this is “context load”, not “what they’re about to send”.
    if drop_last_user_message and full_input[-1].get("role") == "user":
        context = full_input[:-1]
    else:
        context = full_input
    return estimate_tokens_for_messages(context, model=model)


def _indent_block(text: str, prefix: str = "  ") -> str:
    lines = (text or "").splitlines() or [""]
    return "\n".join(prefix + line for line in lines)

def _bulletize(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    first = f"- {lines[0]}"
    rest = "".join(f"\n  {line}" for line in lines[1:])
    return first + rest

def _humanize_pin_title(title: str) -> str:
    raw = (title or "").strip().replace("_", " ").replace("-", " ")
    if not raw:
        return ""
    return " ".join(word.capitalize() for word in raw.split())

def _order_scoped_pins_for_context(
    pins: list[dict],
    project_id: int | None,
    *,
    limit: int | None = None,
) -> list[dict]:
    project_pins: list[dict] = []
    global_pins: list[dict] = []

    for p in pins or []:
        scope_type = (p.get("scope_type") or "global").strip().lower()
        scope_id = p.get("scope_id")

        if scope_type == "project":
            if project_id is not None and scope_id is not None and int(scope_id) == int(project_id):
                project_pins.append(p)
        else:
            global_pins.append(p)

    ordered = project_pins + global_pins
    if limit is not None and limit > 0:
        ordered = ordered[:limit]
    return ordered

def _build_personalization_blocks(pins: list[dict]) -> dict:
    about_lines: list[str] = []
    extra_profile_lines: list[str] = []
    instruction_lines: list[str] = []
    style_lines: list[str] = []
    preference_lines: list[str] = []
    plain_texts: list[str] = []

    for pin in pins or []:
        text = (pin.get("text") or "").strip()
        if text:
            plain_texts.append(text)

        kind = (pin.get("pin_kind") or "instruction").strip().lower()
        title = (pin.get("title") or "").strip()
        value = pin.get("value_json")

        if kind == "profile" and title == "about_you":
            if isinstance(value, dict):
                nickname = (value.get("nickname") or "").strip()
                age = (value.get("age") or "").strip()
                occupation = (value.get("occupation") or "").strip()
                more = (value.get("more_about_you") or "").strip()

                if nickname:
                    about_lines.append(f"- Nickname(s): {nickname}")
                if age:
                    about_lines.append(f"- Approximate age: {age}")
                if occupation:
                    about_lines.append(f"- Occupation: {occupation}")
                if more:
                    about_lines.append("- More about the user:")
                    about_lines.append(_indent_block(more))
            elif text:
                about_lines.append(_bulletize(text))
            continue

        item_text = text
        if not item_text and value is not None:
            if isinstance(value, dict):
                try:
                    item_text = json.dumps(value, ensure_ascii=False)
                except Exception:
                    item_text = str(value)
            else:
                item_text = str(value)

        item_text = (item_text or "").strip()
        if not item_text:
            continue

        label = _humanize_pin_title(title)
        rendered = _bulletize(f"{label}: {item_text}" if label else item_text)

        if kind == "profile":
            extra_profile_lines.append(rendered)
        elif kind == "style":
            style_lines.append(rendered)
        elif kind == "preference":
            preference_lines.append(rendered)
        else:
            instruction_lines.append(rendered)

    blocks: list[str] = []

    if about_lines or extra_profile_lines:
        body: list[str] = [
            "User-provided profile information. Use this for personalization and continuity. Treat it as true unless the user corrects or updates it."
        ]
        body.extend(about_lines)

        if extra_profile_lines:
            if about_lines:
                body.append("")
            body.append("Additional profile notes:")
            body.extend(extra_profile_lines)

        blocks.append("ABOUT THE USER:\n" + "\n".join(body))

    instruction_body: list[str] = []
    if instruction_lines:
        instruction_body.append(
            "User-provided instructions. Follow these unless they conflict with higher-priority system or safety rules."
        )
        instruction_body.extend(instruction_lines)

    if style_lines:
        if instruction_body:
            instruction_body.append("")
        instruction_body.append("Style preferences:")
        instruction_body.extend(style_lines)

    if preference_lines:
        if instruction_body:
            instruction_body.append("")
        instruction_body.append("Other preferences:")
        instruction_body.extend(preference_lines)

    if instruction_body:
        blocks.append("CUSTOM INSTRUCTIONS:\n" + "\n".join(instruction_body))

    return {
        "blocks": blocks,
        "plain_texts": plain_texts,
    }


# region Context Query Helpers

def _artifact_to_input_message(art: dict, *, label: str) -> dict:
    title = (art.get("title") or "").strip()
    artifact_id = (art.get("id") or "").strip()
    source_kind = (art.get("source_kind") or "").strip()
    body = (art.get("content_text") or "").strip()

    header_lines = [label]
    if title:
        header_lines.append(f"Title: {title}")
    if artifact_id:
        header_lines.append(f"Artifact ID: {artifact_id}")
    if source_kind:
        header_lines.append(f"Source kind: {source_kind}")

    header = "\n".join(header_lines).strip()
    text = f"{header}\n\n{body}".strip()
    return {"role": "user", "content": text}

def _order_scoped_memories_for_context(
    memories: list[dict],
    project_id: int | None,
    *,
    limit: int,
) -> list[dict]:
    relevant: list[dict] = []

    for m in memories or []:
        scope_type = (m.get("scope_type") or "global").strip().lower()
        scope_id = m.get("scope_id")

        if scope_type == "project":
            if project_id is not None and scope_id is not None and int(scope_id) == int(project_id):
                relevant.append(m)
        else:
            relevant.append(m)

    def _sort_key(m: dict):
        importance = int(m.get("importance") or 0)
        scope_type = (m.get("scope_type") or "global").strip().lower()
        scope_id = m.get("scope_id")
        scope_rank = 0 if (scope_type == "project" and project_id is not None and scope_id is not None and int(scope_id) == int(project_id)) else 1
        updated = (m.get("updated_at") or m.get("created_at") or "")
        return (
            0 if importance >= 10 else 1,   # pinned first
            -importance,                    # then descending importance
            scope_rank,                     # only then prefer local project over global
            updated,                        # stable-ish tiebreak
        )

    relevant.sort(key=_sort_key)
    return relevant[: max(0, int(limit))]

if (False):
    def _order_scoped_memories_for_context(
        memories: list[dict],
        project_id: int | None,
        *,
        limit: int,
    ) -> list[dict]:
        project_rows: list[dict] = []
        global_rows: list[dict] = []

        for m in memories or []:
            scope_type = (m.get("scope_type") or "global").strip().lower()
            scope_id = m.get("scope_id")

            if scope_type == "project":
                if project_id is not None and scope_id is not None and int(scope_id) == int(project_id):
                    project_rows.append(m)
            else:
                global_rows.append(m)

        ordered = project_rows + global_rows
        return ordered[: max(0, int(limit))]


def _select_scoped_conversation_ids_for_context(
    conversation_id: str,
    project_id: int | None,
    *,
    limit: int,
) -> list[str]:
    limit = max(0, int(limit))
    if limit <= 0:
        return []

    out: list[str] = []
    seen: set[str] = set()

    def _add(cid: str | None) -> None:
        if not cid:
            return
        cid = str(cid).strip()
        if not cid or cid in seen:
            return
        seen.add(cid)
        out.append(cid)

    # Always include the current conversation first.
    _add(conversation_id)

    if project_id is not None and len(out) < limit:
        rows = list_conversations(limit=max(limit * 8, 200), include_archived=False)
        for c in rows:
            if int(c.get("project_id") or 0) == int(project_id):
                _add(c.get("id"))
                if len(out) >= limit:
                    break

    return out[:limit]

# endregion

# region Query Expansion

def _expand_kind_for_row(row: dict) -> str | None:
    artifact_id = (row.get("artifact_id") or "").strip()
    source_kind = (row.get("source_kind") or "").strip().lower()
    file_id = (row.get("file_id") or "").strip()

    if file_id:
        return "FILE"

    if source_kind == "memory" or artifact_id.startswith("memory--"):
        return "MEMORY"

    if (
        artifact_id.startswith("conversation_transcript--")
        or source_kind in ("conversation_transcript", "conversation:transcript")
    ):
        return "CHAT"

    return None


def _recommend_expansion_candidates(
    *,
    raw_rows: list[dict],
    allowed_flags: set[str],
    already_included_artifact_ids: set[str],
    max_full_files: int,
    max_full_memories: int,
    max_full_chats: int,
    min_artifact_hits: int,
) -> list[dict]:
    counts_by_artifact: dict[str, int] = {}
    best_row_by_artifact: dict[str, dict] = {}

    for r in raw_rows or []:
        artifact_id = (r.get("artifact_id") or "").strip()
        if not artifact_id or artifact_id in already_included_artifact_ids:
            continue

        kind = _expand_kind_for_row(r)
        if not kind or kind not in allowed_flags:
            continue

        counts_by_artifact[artifact_id] = counts_by_artifact.get(artifact_id, 0) + 1

        prev = best_row_by_artifact.get(artifact_id)
        if prev is None or float(r.get("score", 1e9)) < float(prev.get("score", 1e9)):
            best_row_by_artifact[artifact_id] = r

    # Conservative first cut:
    # only recommend artifacts that got at least min_artifact_hits raw hits.
    ranked: list[dict] = []
    for artifact_id, hit_count in counts_by_artifact.items():
        if hit_count < max(1, int(min_artifact_hits or 1)):
            continue
        row = best_row_by_artifact[artifact_id]
        ranked.append({
            "artifact_id": artifact_id,
            "kind": _expand_kind_for_row(row),
            "raw_hit_count": hit_count,
            "score": row.get("score"),
            "file_id": row.get("file_id"),
            "source_kind": row.get("source_kind"),
            "source_id": row.get("source_id"),
            "artifact_title": row.get("artifact_title"),
            "conversation_id": row.get("conversation_id"),
            "conversation_title": row.get("conversation_title"),
            "conversation_summary_excerpt": row.get("conversation_summary_excerpt"),
            "conversation_started_at": row.get("conversation_started_at"),
            "conversation_ended_at": row.get("conversation_ended_at"),
            "filename": row.get("filename"),
            "chunk_index": row.get("chunk_index"),
        })

    ranked.sort(key=lambda x: (-int(x.get("raw_hit_count") or 0), float(x.get("score") or 1e9)))

    out: list[dict] = []
    file_count = 0
    memory_count = 0
    chat_count = 0

    for item in ranked:
        kind = item["kind"]
        if kind == "FILE":
            if file_count >= max_full_files:
                continue
            file_count += 1
        elif kind == "MEMORY":
            if memory_count >= max_full_memories:
                continue
            memory_count += 1
        elif kind == "CHAT":
            if chat_count >= max_full_chats:
                continue
            chat_count += 1
        out.append(item)

    return out

# endregion

def _load_transcript_chunk_window(
    conn,
    *,
    artifact_id: str,
    center_chunk_index: int,
    before: int,
    after: int,
) -> list[dict]:
    lo = max(0, int(center_chunk_index) - max(0, int(before)))
    hi = int(center_chunk_index) + max(0, int(after))

    rows = conn.execute(
        """
        SELECT chunk_index, text
        FROM corpus_chunks
        WHERE artifact_id = ?
          AND chunk_index BETWEEN ? AND ?
        ORDER BY chunk_index ASC
        """,
        (artifact_id, lo, hi),
    ).fetchall()

    return [dict(r) for r in rows]


def _chat_window_to_input_message(
    item: dict,
    window_rows: list[dict],
) -> dict:
    title = (item.get("conversation_title") or "").strip()
    summary = (item.get("conversation_summary_excerpt") or "").strip()
    dt_range = _format_conversation_range(
        item.get("conversation_started_at"),
        item.get("conversation_ended_at"),
    )
    artifact_id = (item.get("artifact_id") or "").strip()

    lines = ["EXPANDED CHAT WINDOW"]
    if title:
        lines.append(f"Conversation: {title}")
    if dt_range:
        lines.append(f"Range: {dt_range}")
    if summary:
        lines.append(f"Summary: {summary}")
    if artifact_id:
        lines.append(f"Artifact ID: {artifact_id}")

    lines.append("")

    for row in window_rows:
        idx = row.get("chunk_index")
        text = (row.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"[chunk {idx}]")
        lines.append(text)
        lines.append("")

    return {"role": "user", "content": "\n".join(lines).strip()}

def build_context(
        conversation_id: str, # shapes the context by scope
        user_text: str, # needed for RAG queries
        ctx_cfg: ContextConfig | None = None,
        query_cfg: RetrievalConfig | None = None,
        include_preview: bool = True,
        ) -> dict:
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_retrieval_config()

    # 3A lazy repair: keep the conversation transcript artifact reasonably fresh
    try:
        ensure_conversation_transcript_artifact_fresh(
            conversation_id,
            force_full=False,
            reason="build_context",
        )
    except Exception as exc:
        log_warn("Transcript lazy repair failed for %s: %s", conversation_id, exc)

    has_user_text = bool((user_text or "").strip())

    preview_limit = max(1, int(ctx_cfg.preview_limit))

    history_rows = get_messages(conversation_id, limit=ctx_cfg.history_limit)
    # Add the zeitgeber prefixes
    typed_history: list[dict] = []
    for r in history_rows:
        created_at = (r.get("created_at") or "").strip() if r.get("created_at") else ""
        raw_content = r.get("content") or ""
        text = zeitgeber_prefix(created_at, raw_content) if created_at else raw_content
        typed_history.append({"role": r["role"], "content": text})

    sources = get_context_sources(conversation_id)
    project_id = sources.get("project_id")

    effective_query_include = _normalize_csv_set(
        _effective_query_setting(project_id, "include", query_cfg.query_include),
        QUERY_INCLUDE_ALLOWED,
    )
    effective_query_expand_results = _normalize_csv_set(
        _effective_query_setting(project_id, "expand_results", query_cfg.query_expand_results),
        QUERY_EXPAND_ALLOWED,
    )
    expand_flags = set(effective_query_expand_results.split(",")) if effective_query_expand_results else set()
    include_flags = set(effective_query_include.split(",")) if effective_query_include else set()

    # Wholesale inclusion should reflect config even when the draft box is empty.
    # Retrieval stays gated on live query text.
    do_include_files = "FILE" in include_flags
    do_include_chat_summaries = "CHAT_SUMMARY" in include_flags
    do_include_memories = "MEMORY" in include_flags
    do_include_chats = "CHAT" in include_flags
    # RAG is dependent on there being user text
    do_fts_rag = has_user_text and ("FTS" in include_flags)
    do_vector_rag = has_user_text and ("EMBEDDING" in include_flags)

    max_full_files = int(_effective_query_setting(project_id, "max_full_files", str(query_cfg.query_max_full_files)))
    max_full_memories = int(_effective_query_setting(project_id, "max_full_memories", str(query_cfg.query_max_full_memories)))
    max_full_chats = int(_effective_query_setting(project_id, "max_full_chats", str(query_cfg.query_max_full_chats)))
    query_expand_min_artifact_hits = int(
        _effective_query_setting(
            project_id,
            "expand_min_artifact_hits",
            str(query_cfg.query_expand_min_artifact_hits),
        )
    )
    query_expand_chat_window_before = max(0, int(query_cfg.query_expand_chat_window_before))
    query_expand_chat_window_after = max(0, int(query_cfg.query_expand_chat_window_after))

    # Fetch a wider pool first, then scope/order locally so project pins do not get crowded out by globals.
    all_pins = list_memory_pins(limit=max(int(ctx_cfg.memory_pin_limit or 50) * 4, 200))
    # This breaks pins out into LLM readable information we can put in a system block
    pinned = _order_scoped_pins_for_context(
        all_pins,
        project_id,
        limit=ctx_cfg.memory_pin_limit,
    )

    # Build LLM-readable personalization blocks from scoped pins.
    personalization = _build_personalization_blocks(pinned)
    pinned_texts = personalization["plain_texts"]

    log_debug(
        "[context] scoped pins (project_id=%s): %s",
        project_id,
        [(p.get("id"), p.get("scope_type"), p.get("scope_id"), p.get("pin_kind"), p.get("title"), p.get("text")) for p in pinned]
    )
    log_debug("[context] personalization blocks: %s", personalization["blocks"])
    log_debug("[context] pinned_texts: %s", pinned_texts)
    
    # TODO if it doesn't exist, maybe generate one, assuming enough conversation history?
    # Pull summary if present
    summary = get_conversation_summary_text(conversation_id)

        # Whole-artifact inclusion channel.
    # Ordering matters:
    #   1) pinned/scoped memories
    #   2) files
    #   3) chat summaries
    #   4) full chat transcripts
    included_artifact_ids: set[str] = set()
    whole_artifact_messages: list[dict] = []
    included_memory_labels: list[str] = []
    included_chat_labels: list[str] = []
    included_chat_summary_labels: list[str] = []

    included_file_artifact_labels: list[str] = []
    expansion_candidates: list[dict] = []
    expanded_artifact_ids: set[str] = set()

    # Memories first.
    scoped_memories = _order_scoped_memories_for_context(
        list_memories(limit=max(max_full_memories * 4, 200)),
        project_id,
        limit=max(max_full_memories * 4, 200),
    )
    pinned_memories = [m for m in scoped_memories if int(m.get("importance") or 0) >= 10]
    memory_candidates = scoped_memories[:max_full_memories] if do_include_memories else pinned_memories

    if memory_candidates:
        with db_session() as conn:
            for m in memory_candidates:
                try:
                    artifact_id = memory_artifact_id(str(m["id"]))
                except Exception:
                    continue

                if artifact_id in included_artifact_ids:
                    continue

                art = load_artifact_row_for_context(conn, artifact_id)
                if not art or not (art.get("content_text") or "").strip():
                    continue

                included_artifact_ids.add(artifact_id)
                label = "PINNED MEMORY ARTIFACT" if int(m.get("importance") or 0) >= 10 else "SCOPED MEMORY ARTIFACT"
                whole_artifact_messages.append(_artifact_to_input_message(art, label=label))

                scope_type = (m.get("scope_type") or "global")
                scope_id = m.get("scope_id")
                title = (art.get("title") or f"Memory {m.get('id')}").strip()
                importance = int(m.get("importance") or 0)
                included_memory_labels.append(
                    f"{title} [importance={importance}; {scope_type}{':' + str(scope_id) if scope_id is not None else ''}]"
                )

    # Chat summaries second.
    if do_include_chat_summaries:
        summary_rows = _select_other_project_conversation_rows_for_context(
            conversation_id,
            project_id,
            limit=max_full_chats,
        )

        if summary_rows:
            with db_session() as conn:
                span_map = _conversation_span_map(conn, [str(r["id"]) for r in summary_rows])

                for row in summary_rows:
                    cid = str(row.get("id") or "").strip()
                    if not cid:
                        continue

                    artifact_id = conversation_summary_artifact_id(cid)
                    if artifact_id in included_artifact_ids:
                        continue

                    art = load_artifact_row_for_context(conn, artifact_id)
                    summary_text = ""
                    if art and (art.get("content_text") or "").strip():
                        summary_text = (art.get("content_text") or "").strip()
                    else:
                        summary_text = (get_conversation_summary_text(cid) or "").strip()

                    if not summary_text:
                        continue

                    if artifact_id and art:
                        included_artifact_ids.add(artifact_id)

                    started_at, ended_at = span_map.get(cid, (None, None))
                    title = (row.get("title") or (art.get("title") if art else "") or cid).strip()

                    whole_artifact_messages.append(
                        _conversation_summary_to_input_message(
                            conversation_id=cid,
                            title=title,
                            summary_text=summary_text,
                            started_at=started_at,
                            ended_at=ended_at,
                            artifact_id=artifact_id if art else "",
                        )
                    )

                    dt_range = _format_conversation_range(started_at, ended_at)
                    if dt_range:
                        included_chat_summary_labels.append(f"{title} [{dt_range}; summary]")
                    else:
                        included_chat_summary_labels.append(f"{title} [summary]")

    # Files third.
    if do_include_files:
        file_messages, included_file_artifact_labels, file_artifact_ids = _build_file_messages_for_conversation(
            conversation_id,
            limit=max_full_files,
            already_included_artifact_ids=included_artifact_ids,
        )
        whole_artifact_messages.extend(file_messages)
        included_artifact_ids.update(file_artifact_ids)

    # Full chats last.
    if do_include_chats:
        scoped_conversation_ids = _select_scoped_conversation_ids_for_context(
            conversation_id,
            project_id,
            limit=max_full_chats,
        )

        with db_session() as conn:
            for cid in scoped_conversation_ids:
                try:
                    ensure_conversation_transcript_artifact_fresh(
                        cid,
                        force_full=False,
                        reason="build_context.include_chat",
                    )
                except Exception as exc:
                    log_warn("Transcript lazy repair failed for included chat %s: %s", cid, exc)

                try:
                    artifact_id = conversation_transcript_artifact_id(cid)
                except Exception:
                    continue

                if artifact_id in included_artifact_ids:
                    continue

                art = load_artifact_row_for_context(conn, artifact_id)
                if not art or not (art.get("content_text") or "").strip():
                    continue

                included_artifact_ids.add(artifact_id)
                label = "SCOPED CHAT TRANSCRIPT"
                whole_artifact_messages.append(_artifact_to_input_message(art, label=label))

                title = (art.get("title") or cid).strip()
                included_chat_labels.append(title)

    if (False):
        # Whole-artifact inclusion channel (FILE is handled later through file_messages;
        # MEMORY and CHAT are handled here as text messages and deduped by artifact_id).
        included_artifact_ids: set[str] = set()
        whole_artifact_messages: list[dict] = []
        included_memory_labels: list[str] = []
        included_chat_labels: list[str] = []
        included_chat_summary_labels: list[str] = []
        
        # File Expansion
        included_file_artifact_labels: list[str] = []
        expansion_candidates: list[dict] = []
        expanded_artifact_ids: set[str] = set()

        if do_include_files:
            file_messages, included_file_artifact_labels, file_artifact_ids = _build_file_messages_for_conversation(
                conversation_id,
                limit=max_full_files,
                already_included_artifact_ids=included_artifact_ids,
            )
            whole_artifact_messages.extend(file_messages)
            included_artifact_ids.update(file_artifact_ids)

        if do_include_chat_summaries:
            summary_rows = _select_other_project_conversation_rows_for_context(
                conversation_id,
                project_id,
                limit=max_full_chats,
            )

            if summary_rows:
                with db_session() as conn:
                    span_map = _conversation_span_map(conn, [str(r["id"]) for r in summary_rows])

                    for row in summary_rows:
                        cid = str(row.get("id") or "").strip()
                        if not cid:
                            continue

                        artifact_id = conversation_summary_artifact_id(cid)
                        if artifact_id in included_artifact_ids:
                            continue

                        art = load_artifact_row_for_context(conn, artifact_id)
                        if not art or not (art.get("content_text") or "").strip():
                            continue

                        included_artifact_ids.add(artifact_id)

                        started_at, ended_at = span_map.get(cid, (None, None))
                        title = (row.get("title") or art.get("title") or cid).strip()

                        whole_artifact_messages.append(
                            _conversation_summary_to_input_message(
                                conversation_id=cid,
                                title=title,
                                summary_text=art.get("content_text") or "",
                                started_at=started_at,
                                ended_at=ended_at,
                                artifact_id=artifact_id,
                            )
                        )

                        dt_range = _format_conversation_range(started_at, ended_at)
                        if dt_range:
                            included_chat_summary_labels.append(f"{title} [{dt_range}; summary]")
                        else:
                            included_chat_summary_labels.append(f"{title} [summary]")
                        #if dt_range:
                        #    included_chat_labels.append(f"{title} [{dt_range}; summary]")
                        #else:
                        #    included_chat_labels.append(f"{title} [summary]")

        if do_include_memories:
            scoped_memories = _order_scoped_memories_for_context(
                list_memories(limit=max(max_full_memories * 4, 200)),
                project_id,
                limit=max(max_full_memories * 4, 200),
            )

            pinned_memories = [m for m in scoped_memories if int(m.get("importance") or 0) >= 10]
            memory_candidates = scoped_memories[:max_full_memories] if do_include_memories else pinned_memories

            if memory_candidates:
                with db_session() as conn:
                    for m in memory_candidates:
                        try:
                            artifact_id = memory_artifact_id(str(m["id"]))
                        except Exception:
                            continue

                        if artifact_id in included_artifact_ids:
                            continue

                        art = load_artifact_row_for_context(conn, artifact_id)
                        if not art or not (art.get("content_text") or "").strip():
                            continue

                        included_artifact_ids.add(artifact_id)
                        label = "SCOPED MEMORY ARTIFACT" if int(m.get("importance") or 0) < 10 else "PINNED MEMORY ARTIFACT"
                        whole_artifact_messages.append(_artifact_to_input_message(art, label=label))

                        scope_type = (m.get("scope_type") or "global")
                        scope_id = m.get("scope_id")
                        title = (art.get("title") or f"Memory {m.get('id')}").strip()
                        importance = int(m.get("importance") or 0)
                        included_memory_labels.append(
                            f"{title} [importance={importance}; {scope_type}{':' + str(scope_id) if scope_id is not None else ''}]"
                        )        
        if (False): # do_include_memories
            scoped_memories = _order_scoped_memories_for_context(
                list_memories(limit=max(max_full_memories * 4, 200)),
                project_id,
                limit=max_full_memories,
            )

            with db_session() as conn:
                for m in scoped_memories:
                    try:
                        artifact_id = memory_artifact_id(str(m["id"]))
                    except Exception:
                        continue

                    if artifact_id in included_artifact_ids:
                        continue

                    art = load_artifact_row_for_context(conn, artifact_id)
                    if not art or not (art.get("content_text") or "").strip():
                        continue

                    included_artifact_ids.add(artifact_id)
                    label = f"SCOPED MEMORY ARTIFACT"
                    whole_artifact_messages.append(_artifact_to_input_message(art, label=label))

                    scope_type = (m.get("scope_type") or "global")
                    scope_id = m.get("scope_id")
                    title = (art.get("title") or f"Memory {m.get('id')}").strip()
                    included_memory_labels.append(
                        f"{title} [{scope_type}{':' + str(scope_id) if scope_id is not None else ''}]"
                    )

        if do_include_chats:
            scoped_conversation_ids = _select_scoped_conversation_ids_for_context(
                conversation_id,
                project_id,
                limit=max_full_chats,
            )

            with db_session() as conn:
                for cid in scoped_conversation_ids:
                    try:
                        ensure_conversation_transcript_artifact_fresh(
                            cid,
                            force_full=False,
                            reason="build_context.include_chat",
                        )
                    except Exception as exc:
                        log_warn("Transcript lazy repair failed for included chat %s: %s", cid, exc)

                    try:
                        artifact_id = conversation_transcript_artifact_id(cid)
                    except Exception:
                        continue

                    if artifact_id in included_artifact_ids:
                        continue

                    art = load_artifact_row_for_context(conn, artifact_id)
                    if not art or not (art.get("content_text") or "").strip():
                        continue

                    included_artifact_ids.add(artifact_id)
                    label = "SCOPED CHAT TRANSCRIPT"
                    whole_artifact_messages.append(_artifact_to_input_message(art, label=label))

                    title = (art.get("title") or cid).strip()
                    included_chat_labels.append(title)

    retrieved_rows_raw: list[dict] = []
    retrieved_rows: list[dict] = []
    retrieved_block = ""
    retrieved_meta: list[dict] = []
    retrieved_cites: list[str] = []
    retrieval_debug: dict | None = None

    emb_cfg = load_embedding_config()
    vec_cfg = load_vector_config()

    # obsolete and we have moved on
    if (False):
        if do_fts_rag:
            chunks_resp = retrieve_chunks_for_message(
                conversation_id=conversation_id,
                user_message=user_text,
                limit=8,
                cfg=query_cfg,
            )

    rag_limit = 24 # was 8, but why bigger now?
    max_chars = 2200 #1200
    if do_fts_rag or do_vector_rag:
        chunks_resp = retrieve_chunks_for_message(
            conversation_id=conversation_id,
            user_message=user_text,
            limit=rag_limit, 
            cfg=query_cfg,
        )

        retrieved_rows_raw = chunks_resp.get("raw_results") or []
        retrieved_rows = chunks_resp.get("results") or []
        retrieval_debug = chunks_resp.get("debug") or {"skipped": False, "reason": None}

        # If full files are already included, do NOT also stuff file-derived chunks into the final RAG block.
        if do_include_files:
            suppressed = [r for r in retrieved_rows if r.get("file_id")]
            retrieved_rows = [r for r in retrieved_rows if not r.get("file_id")]

            retrieval_debug["suppressed_file_chunk_rows"] = [
                {
                    "chunk_id": r.get("chunk_id"),
                    "artifact_id": r.get("artifact_id"),
                    "file_id": r.get("file_id"),
                    "filename": r.get("filename"),
                    "chunk_index": r.get("chunk_index"),
                    "score": r.get("score"),
                    "reason": "file already fully included in ALL/FILES mode",
                }
                for r in suppressed[:50]
            ]

        if included_artifact_ids:
            suppressed = [r for r in retrieved_rows if (r.get("artifact_id") or "") in included_artifact_ids]
            retrieved_rows = [r for r in retrieved_rows if (r.get("artifact_id") or "") not in included_artifact_ids]

            retrieval_debug["suppressed_included_artifact_rows"] = [
                {
                    "chunk_id": r.get("chunk_id"),
                    "artifact_id": r.get("artifact_id"),
                    "source_kind": r.get("source_kind"),
                    "source_id": r.get("source_id"),
                    "chunk_index": r.get("chunk_index"),
                    "score": r.get("score"),
                    "reason": "whole artifact already included via QUERY_INCLUDE",
                }
                for r in suppressed[:100]
            ]

        if expand_flags:
            expansion_candidates = _recommend_expansion_candidates(
                raw_rows=retrieved_rows_raw,
                allowed_flags=expand_flags,
                already_included_artifact_ids=included_artifact_ids,
                max_full_files=max_full_files,
                max_full_memories=max_full_memories,
                max_full_chats=max_full_chats,
                min_artifact_hits=query_expand_min_artifact_hits,                
            )

            if expansion_candidates:
                with db_session() as conn:
                    for item in expansion_candidates:
                        artifact_id = (item.get("artifact_id") or "").strip()
                        if not artifact_id or artifact_id in included_artifact_ids:
                            continue

                        art = load_artifact_row_for_context(conn, artifact_id)
                        if not art or not (art.get("content_text") or "").strip():
                            continue

                        kind = item.get("kind") or "ARTIFACT"

                        if kind == "CHAT":
                            center_chunk_index = int(item.get("chunk_index") or 0)
                            window_rows = _load_transcript_chunk_window(
                                conn,
                                artifact_id=artifact_id,
                                center_chunk_index=center_chunk_index,
                                before=query_expand_chat_window_before,
                                after=query_expand_chat_window_after,
                            )
                            if not window_rows:
                                continue

                            included_artifact_ids.add(artifact_id)
                            expanded_artifact_ids.add(artifact_id)

                            whole_artifact_messages.append(
                                _chat_window_to_input_message(item, window_rows)
                            )

                            title = (
                                (item.get("conversation_title") or "").strip()
                                or (art.get("title") or "").strip()
                                or str(item.get("conversation_id") or artifact_id)
                            )
                            dt_range = _format_conversation_range(
                                item.get("conversation_started_at"),
                                item.get("conversation_ended_at"),
                            )
                            if dt_range:
                                included_chat_labels.append(f"{title} [{dt_range}; expanded window]")
                            else:
                                included_chat_labels.append(f"{title} [expanded window]")

                            continue

                        included_artifact_ids.add(artifact_id)
                        expanded_artifact_ids.add(artifact_id)

                        whole_artifact_messages.append(
                            _artifact_to_input_message(art, label=f"EXPANDED {kind} ARTIFACT")
                        )

                        if kind == "FILE":
                            title = (art.get("title") or item.get("filename") or artifact_id).strip()
                            included_file_artifact_labels.append(title)

                        elif kind == "MEMORY":
                            title = (art.get("title") or f"Memory {item.get('source_id')}").strip()
                            included_memory_labels.append(f"{title} [expanded]")

                        if (False):
                            kind = item.get("kind") or "ARTIFACT"
                            included_artifact_ids.add(artifact_id)
                            expanded_artifact_ids.add(artifact_id)

                            whole_artifact_messages.append(
                                _artifact_to_input_message(art, label=f"EXPANDED {kind} ARTIFACT")
                            )

                            if kind == "FILE":
                                title = (art.get("title") or item.get("filename") or artifact_id).strip()
                                included_file_artifact_labels.append(title)

                            elif kind == "MEMORY":
                                title = (art.get("title") or f"Memory {item.get('source_id')}").strip()
                                included_memory_labels.append(f"{title} [expanded]")

                            elif kind == "CHAT":
                                center_chunk_index = int(item.get("chunk_index") or 0)
                                window_rows = _load_transcript_chunk_window(
                                    conn,
                                    artifact_id=artifact_id,
                                    center_chunk_index=center_chunk_index,
                                    before=query_expand_chat_window_before,
                                    after=query_expand_chat_window_after,
                                )
                                if not window_rows:
                                    continue

                                # Replace the generic whole-artifact expansion for chats with a local window.
                                whole_artifact_messages.pop()  # remove the generic EXPANDED CHAT ARTIFACT we just appended
                                whole_artifact_messages.append(
                                    _chat_window_to_input_message(item, window_rows)
                                )

                                title = (
                                    (item.get("conversation_title") or "").strip()
                                    or (art.get("title") or "").strip()
                                    or str(item.get("conversation_id") or artifact_id)
                                )
                                dt_range = _format_conversation_range(
                                    item.get("conversation_started_at"),
                                    item.get("conversation_ended_at"),
                                )
                                if dt_range:
                                    included_chat_labels.append(f"{title} [{dt_range}; expanded window]")
                                else:
                                    included_chat_labels.append(f"{title} [expanded window]")

                        if (False): #elif kind == "CHAT":
                            title = (
                                (item.get("conversation_title") or "").strip()
                                or (art.get("title") or "").strip()
                                or str(item.get("conversation_id") or artifact_id)
                            )
                            included_chat_labels.append(f"{title} [expanded]")

                if expanded_artifact_ids:
                    suppressed = [
                        r for r in retrieved_rows
                        if (r.get("artifact_id") or "") in expanded_artifact_ids
                    ]
                    retrieved_rows = [
                        r for r in retrieved_rows
                        if (r.get("artifact_id") or "") not in expanded_artifact_ids
                    ]

                    retrieval_debug["suppressed_expanded_artifact_rows"] = [
                        {
                            "chunk_id": r.get("chunk_id"),
                            "artifact_id": r.get("artifact_id"),
                            "source_kind": r.get("source_kind"),
                            "source_id": r.get("source_id"),
                            "chunk_index": r.get("chunk_index"),
                            "score": r.get("score"),
                            "reason": "whole artifact expanded via QUERY_EXPAND_RESULTS",
                        }
                        for r in suppressed[:100]
                    ]

            retrieval_debug["expansion_candidates"] = expansion_candidates

        retrieved_block, retrieved_meta, retrieved_cites = _format_retrieved_chunks(
            retrieved_rows,
            max_chunks=rag_limit,
            max_chars=max_chars,
            excerpt_query=user_text,
        )
    else: # if not (do_fts_rag or do_vector_rag):
        # We're skipping all searches - say why
        retrieval_debug = {
            "skipped": True,
            "reason": f"query_include={effective_query_include} user_text_present={bool(user_text.strip())}",
            #"reason": f"query_mode={query_cfg.query_mode} user_text_present={bool(user_text.strip())}",
        }

    # Choose base system prompt
    core_system = get_system_prompt()
    proj_prompt = (sources.get("project_system_prompt") or "").strip()
    override = bool(sources.get("override_core_prompt"))
    if override and proj_prompt:
        system_prompt = proj_prompt
    elif proj_prompt:
        # project prompt augments core prompt
        system_prompt = core_system + "\n\n" + proj_prompt
    else:
        system_prompt = core_system

    system_blocks = [system_prompt]

    if personalization["blocks"]:
        system_blocks.extend(personalization["blocks"])
    #if pinned_texts:
    #    joined = "\n".join(f"- {t}" for t in pinned_texts)
    #    system_blocks.append("PINNED MEMORIES (user-curated, treat as true):\n" + joined)

    if summary:
        system_blocks.append("CONVERSATION SUMMARY:\n" + summary)

    if retrieved_block:
        system_blocks.append("RETRIEVED CONTENT (RAG; cite chunk_id if referencing):\n" + retrieved_block)
    # if retrieved:
    #    joined = "\n".join(f"- {m}" for m in retrieved)
    #    system_blocks.append("Retrieved memories (machine-selected using RAG, verify if uncertain):\n" + joined)

    system_text = "\n\n".join(system_blocks)

    # Build the list of scoped files regardless of do_include_files
    scoped_files_by_id = gather_scoped_files(conversation_id)
    scoped_files = []
    for file_id, file_row in scoped_files_by_id.items():
        scoped_files.append({
            "file_id": file_id,
            "name": file_row.get("original_name") or Path(file_row.get("path") or "").name,
            "mime_type": file_row.get("mime_type"),
            "scope_type": file_row.get("scope_type"),
            "scope_id": file_row.get("scope_id"),
            "scope_uuid": file_row.get("scope_uuid"),
            "description": file_row.get("description"),
            "created_at": file_row.get("created_at"),
            "updated_at": file_row.get("updated_at"),
            "sha256": file_row.get("sha256"),
        })

    file_messages: list[dict] = []
    normalized_file_messages: list[dict] = []
    if (False):
        # FILE CONTNENTS
        # check include_files and don't do this step if it is false
        file_messages = _build_file_messages_for_conversation(conversation_id) if do_include_files else []
        # Normalize any file_messages that are purely text parts
        normalized_file_messages = []
        # These file messages MUST already be in a format your app uses.
        # If they currently use [{"type":"input_text",...}] convert that to plain text.
        for m in file_messages:
            c = m.get("content")
            if isinstance(c, list) and c and isinstance(c[0], dict):
                # If it's your old "input_text" wrapper, collapse to string
                if all(p.get("type") in ("input_text", "text") and "text" in p for p in c):
                    normalized_file_messages.append({"role": m.get("role", "user"), "content": "\n".join(p["text"] for p in c)})
                    continue
            normalized_file_messages.append(m)

    # These are only needed for the /context debug endpoint, not for actual chat turns.
    assembled_input_count = None
    assembled_input_preview = None
    assembled_input_truncated = None
    token_stats = None
    # This will provide long or short preview when the call
    # is being made to populate the right-hand diagnostic panel.
    if include_preview:
        assembled_input_full = typed_history
        assembled_input_count = len(assembled_input_full)
        assembled_input_preview = assembled_input_full[-preview_limit:] if preview_limit > 0 else assembled_input_full
        assembled_input_truncated = len(assembled_input_preview) < len(assembled_input_full)
        # Include files in the assembled input also
        # assembled_input_preview = [{"role": "system", "content": system_text}] + normalized_file_messages + assembled_input_preview
        assembled_input_preview = (
            [{"role": "system", "content": system_text}]
            + whole_artifact_messages
            + normalized_file_messages
            + assembled_input_preview
        )
        token_stats = estimate_context_tokens(conversation_id, ctx_cfg, user_text, model=ctx_cfg.estimate_model)

    retrieval_debug["embedding_provider"] = emb_cfg.provider
    retrieval_debug["embedding_model"] = emb_cfg.model
    retrieval_debug["vector_backend"] = vec_cfg.backend
    retrieval_debug["vector_collection"] = vec_cfg.collection_name

    return {
        "conversation_id": conversation_id,
        "project_id": sources.get("project_id"),
        "project_name": sources.get("project_name"),
        "file_include": bool(do_include_files),
        "fts_rag_active": bool(do_fts_rag),
        "vector_rag_active": bool(do_vector_rag),
        #"query_mode": query_cfg.query_mode,  # legacy
        "query_include": effective_query_include,
        "query_expand_results": effective_query_expand_results,
        "query_max_full_files": int(_effective_query_setting(project_id, "max_full_files", str(query_cfg.query_max_full_files))),
        "query_max_full_memories": int(_effective_query_setting(project_id, "max_full_memories", str(query_cfg.query_max_full_memories))),
        "query_max_full_chats": int(_effective_query_setting(project_id, "max_full_chats", str(query_cfg.query_max_full_chats))),
        "query_expand_min_artifact_hits": query_expand_min_artifact_hits,
        "has_user_text": has_user_text,
        "core_system_prompt": core_system,
        "project_system_prompt": proj_prompt,
        "effective_system_prompt": system_prompt,
        "system_text": system_text, #"system_prompt": system_prompt,
        "personalization_blocks": personalization["blocks"],
        "token_stats": token_stats,
        "summary": summary,
        # This is still being used in diagnostics
        "pinned_memories": pinned_texts, #"retrieved_memories": retrieved,
        "retrieved_memories": retrieved_cites,     # keeps your existing key stable for UI
        "retrieved_chunks_raw": retrieved_rows_raw,
        #"retrieved_chunks": retrieved_rows,        
        "retrieved_chunks_final": retrieved_rows,  # full rows
        "retrieved_chunk_meta": retrieved_meta,    # tidy meta for future expand/open
        "retrieval_debug": retrieval_debug,        

        # Do we need assembled input here or not?
        "assembled_input_count": assembled_input_count,
        "assembled_input_preview": assembled_input_preview,
        "assembled_input_preview_limit": ctx_cfg.preview_limit,
        "assembled_input_preview_truncated": assembled_input_truncated,
        "history_count": len(history_rows),
        "history_rows": history_rows, 
        "history_rows_typed": typed_history,
        "memory_include": bool(do_include_memories),
        "chat_include": bool(do_include_chats),
        "included_artifact_ids": sorted(included_artifact_ids),
        "included_memory_labels": included_memory_labels,
        "included_chat_labels": included_chat_labels,
        "included_chat_summary_labels": included_chat_summary_labels,
        "scoped_files": scoped_files,
        "included_file_artifact_labels": included_file_artifact_labels,
        "whole_artifact_messages": whole_artifact_messages,
        "expansion_candidates": expansion_candidates,
        "expanded_artifact_ids": sorted(expanded_artifact_ids),        
        "file_messages": normalized_file_messages,
    }

def build_model_input(
        conversation_id: str, 
        user_text: str, 
        ctx_cfg: ContextConfig | None = None,
        query_cfg: RetrievalConfig | None = None,
        ctx: dict | None = None
    ) -> list[dict]:
    """
    Build a Responses-API compatible input.
    Use string `content` for all text messages (max compatibility).
    Keep file/image messages as typed parts ONLY when needed.
    """
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_retrieval_config()
    
    ctx = ctx or build_context(conversation_id, user_text, ctx_cfg, query_cfg, include_preview=False)

    history_rows = ctx.get("history_rows") or []
    system_message = {"role": "system", "content": ctx["system_text"]}
    normalized_file_messages = ctx.get("file_messages") or []
    whole_artifact_messages = ctx.get("whole_artifact_messages") or []

    # If first message, just return the system prompt and the files list
    # Otherwise split the last message off and show it after the file list.
    if not history_rows:
        return [system_message] + whole_artifact_messages + normalized_file_messages
    typed_history = ctx["history_rows_typed"]
    *prior_msgs, last_msg = typed_history
    return [system_message] + whole_artifact_messages + normalized_file_messages + prior_msgs + [last_msg]
if (False):
    def build_model_input(
            conversation_id: str, 
            user_text: str, 
            ctx_cfg: ContextConfig | None = None,
            query_cfg: RetrievalConfig | None = None,
            ctx: dict | None = None
        ) -> list[dict]:
        """
        Build a Responses-API compatible input.
        Use string `content` for all text messages (max compatibility).
        Keep file/image messages as typed parts ONLY when needed.
        """
        ctx_cfg = ctx_cfg or load_context_config()
        query_cfg = query_cfg or load_retrieval_config()
        
        ctx = ctx or build_context(conversation_id, user_text, ctx_cfg, query_cfg, include_preview=False)

        history_rows = ctx.get("history_rows") or []
        system_message = {"role": "system", "content": ctx["system_text"]}
        normalized_file_messages = ctx.get("file_messages") or []
        whole_artifact_messages = ctx.get("whole_artifact_messages") or []

        if not history_rows:
            return [system_message] + whole_artifact_messages + normalized_file_messages    
            # return [system_message] + normalized_file_messages
        typed_history = ctx["history_rows_typed"]
        *prior_msgs, last_msg = typed_history
        return [system_message] + prior_msgs + whole_artifact_messages + normalized_file_messages + [last_msg]
        # return [system_message] + prior_msgs + normalized_file_messages + [last_msg]

def build_context_panel_payload(
    conversation_id: str,
    user_text: str,
    ctx_cfg: ContextConfig | None = None,
    query_cfg: RetrievalConfig | None = None,
) -> dict:
    """
    Side-panel-only diagnostic payload.
    This is NOT the function used to assemble model input for a live chat turn.
    """
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_retrieval_config()

    # Build raw context state first
    ctx = build_context(
        conversation_id=conversation_id,
        user_text=user_text,
        ctx_cfg=ctx_cfg,
        query_cfg=query_cfg,
        include_preview=False,
    )

    # Build the ACTUAL model input from the same ctx so the side panel reflects reality
    full_input = build_model_input(
        conversation_id=conversation_id,
        user_text=user_text,
        ctx_cfg=ctx_cfg,
        query_cfg=query_cfg,
        ctx=ctx,
    )

    preview_limit = max(1, int(ctx_cfg.preview_limit))

    typed_history = ctx.get("history_rows_typed") or []
    recent_history_preview = typed_history[-preview_limit:] if preview_limit > 0 else typed_history
    recent_history_truncated = len(recent_history_preview) < len(typed_history)

    # File info
    scoped_files = ctx.get("scoped_files") or []
    file_messages = ctx.get("file_messages") or []
    file_labels = [f.get("name") or "(file)" for f in scoped_files]
    included_file_labels = ctx.get("included_file_artifact_labels") or []
    #included_file_labels = [_panel_label_for_file_message(m) for m in file_messages]
    #included_file_labels.extend(ctx.get("included_file_artifact_labels") or [])
    included_memory_labels = ctx.get("included_memory_labels") or []
    included_chat_labels = ctx.get("included_chat_labels") or []
    included_chat_summary_labels = ctx.get("included_chat_summary_labels") or []

    token_stats = estimate_tokens_for_messages(full_input, model=ctx_cfg.estimate_model)

    return {
        **ctx,
        "token_stats": token_stats,
        "assembled_input_count": len(full_input),
        "assembled_input_preview_limit": preview_limit,
        "assembled_input_preview_truncated": recent_history_truncated,
        "recent_history_preview": recent_history_preview,
        "file_labels": file_labels,
        "included_file_labels": included_file_labels,
        "included_memory_labels": included_memory_labels,
        "included_chat_labels": included_chat_labels,
        "included_chat_summary_labels": included_chat_summary_labels,
        "llm_input_messages": full_input,
    }

def _panel_label_for_file_message(msg: dict) -> str:
    content = msg.get("content") or ""
    if isinstance(content, str):
        first = content.splitlines()[0].strip()
        return first or "(file)"
    if isinstance(content, list) and content and isinstance(content[0], dict):
        txt = content[0].get("text") or ""
        first = str(txt).splitlines()[0].strip()
        return first or "(file)"
    return "(file)"

def _build_file_messages_for_conversation(
    conversation_id: str,
    *,
    limit: int,
    already_included_artifact_ids: set[str] | None = None,
) -> tuple[list[dict], list[str], set[str]]:
    files_by_id: dict[str, dict] = gather_scoped_files(conversation_id)
    if not files_by_id:
        return [], [], set()

    ensure_artifacts_for_files(files_by_id)

    already_included_artifact_ids = already_included_artifact_ids or set()
    file_messages: list[dict] = []
    included_file_labels: list[str] = []
    included_artifact_ids: set[str] = set()

    file_rows = list(files_by_id.values())
    file_rows.sort(key=lambda r: (r.get("updated_at") or r.get("created_at") or ""), reverse=True)

    files_taken = 0
    for file_row in file_rows:
        if files_taken >= max(0, int(limit)):
            break

        file_id = str(file_row.get("id") or "").strip()
        if not file_id:
            continue

        try:
            artifacts = list_artifacts_for_file(file_id, include_deleted=False)
        except Exception as exc:
            print(f"[context] list_artifacts_for_file failed for file {file_id}: {exc}")
            continue

        if not artifacts:
            continue

        orig_name = file_row.get("original_name") or Path(file_row.get("path") or "").name
        file_had_any = False

        for art in artifacts:
            artifact_id = (art.get("id") or "").strip()
            if artifact_id and artifact_id in already_included_artifact_ids:
                continue

            source_kind = art.get("source_kind") or ""
            content = art.get("content_text") or ""

            if source_kind.startswith("file:image"):
                try:
                    payload = json.loads(content)
                except Exception as exc:
                    print(f"[context] failed to parse image artifact JSON for file {file_id}: {exc}")
                    continue

                image_path_str = payload.get("path") or file_row.get("path")
                if not image_path_str:
                    continue

                try:
                    image_path = Path(image_path_str)
                    data = load_image_bytes(image_path)
                except Exception as exc:
                    print(f"[context] failed to load image bytes for {image_path_str}: {exc}")
                    continue

                if not data:
                    continue

                b64 = image_bytes_to_base64(data)
                mime_type = payload.get("mime_type") or "application/octet-stream"
                data_url = f"data:{mime_type};base64,{b64}"

                file_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"[FILE ARTIFACT]\nTitle: {orig_name}\nArtifact ID: {artifact_id}\nSource kind: {source_kind}"},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                )
            else:
                text = str(content)
                if not text.strip():
                    continue

                file_messages.append(
                    {
                        "role": "user",
                        "content": f"[FILE ARTIFACT]\nTitle: {orig_name}\nArtifact ID: {artifact_id}\nSource kind: {source_kind}\n\n{text}".strip(),
                    }
                )

            if artifact_id:
                included_artifact_ids.add(artifact_id)
            file_had_any = True

        if file_had_any:
            files_taken += 1
            included_file_labels.append(orig_name)

    return file_messages, included_file_labels, included_artifact_ids