from datetime import datetime, timezone
import json
import os
#from typing import cast
from pathlib import Path
import re

from .logging_helper import log_debug, log_warn
from .db import (
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
)
from .config import ContextConfig, CoreConfig, QueryConfig, load_context_config, load_core_config, load_query_config
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

if (False):
    def _get_prompt(default_prompt: str, filepath: str = "", cfg_default = "(cfg default)", cfg_filepath = "(cfg filepath name)") -> str:
        """
        Loads a given system prompt in this precedence order:
        1) filepath (read text file)
        3) default_prompt (fallback from cfg values, derrived from .env or hardcoded string, supports literal '\n' sequences)
        """
        log_debug(f"Loading system prompt from file: {filepath}")
        if filepath:
            p = Path(filepath)
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8")

        log_debug(f"No valid {cfg_filepath} found, checking {cfg_default}...")  # Debug print
        val = default_prompt
        print(f"Loaded {cfg_default} from env var: {val[:60]}...")  # Debug print (showing only first 60 chars)
        # If your .env uses \n escapes, turn them into real newlines
        val = val.replace("\\n", "\n")
        return val

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

        block_parts.append(header + "\n" + text)

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
            "preview_text": text,
            "full_text_chars": len(full_text),
        })

        cites.append(f"{src_label}#{chunk_index} (chunk_id={chunk_id})")

    return ("\n\n".join(block_parts)).strip(), meta, cites

if (False):
    def _format_retrieved_chunks(rows: list[dict], *, max_chunks: int = 8, max_chars: int = 1200) -> tuple[str, list[dict], list[str]]:
        """
        Returns:
        - block_text: ready to paste into system prompt (includes provenance headers + chunk text)
        - meta: structured per-chunk metadata for UI / later expansion
        - cites: short single-line citations (back-compat with your retrieved_memories list usage)
        """
        block_parts: list[str] = []
        meta: list[dict] = []
        cites: list[str] = []

        for r in (rows or [])[:max_chunks]:
            text = (r.get("text") or "").strip()
            if not text:
                continue

            if len(text) > max_chars:
                text = text[:max_chars] + f"\n[...truncated chunk; max_chars={max_chars}]"

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

            # Best “source timestamp” we can show:
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
            #header = f"[chunk_id={chunk_id} score={score} src={src_label} artifact_id={artifact_id} chunk_index={chunk_index} file_id={file_id}]"

            block_parts.append(header + "\n" + text)

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
            })

            cites.append(f"{src_label}#{chunk_index} (chunk_id={chunk_id})")

        return ("\n\n".join(block_parts)).strip(), meta, cites

def zeitgeber_prefix(created_at: str, raw_content: str) -> str:
    stamp = iso_to_compact_utc(created_at)
    age = iso_to_age_seconds(created_at)
    text = f"⟂t={stamp} ⟂age={age}\n{raw_content}"
    return text

"""
def iso_to_epoch_ms(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))
"""

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

# TODO support a configurable pin / memory limit for performance
def build_context(
        conversation_id: str, # shapes the context by scope
        user_text: str, # needed for RAG queries
        ctx_cfg: ContextConfig | None = None,
        query_cfg: QueryConfig | None = None,
        include_preview: bool = True,
        ) -> dict:
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_query_config()

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
    do_include_files = has_user_text and query_cfg.query_mode in ("FILES", "ALL")
    do_fts_rag = has_user_text and query_cfg.query_mode in ("FTS", "HYBRID", "ALL")
    do_vector_rag = has_user_text and query_cfg.query_mode in ("VECTOR", "HYBRID", "ALL")

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

    if (False):
        pinned = list_memory_pins(limit=ctx_cfg.memory_pin_limit)
        personalization = _build_personalization_blocks(pinned)
        pinned_texts = personalization["plain_texts"]
        log_debug("[context] pins:", [(p.get("id"), p.get("pin_kind"), p.get("title"), p.get("text")) for p in pinned])
        log_debug("[context] personalization blocks:", personalization["blocks"])
        log_debug("[context] pinned_texts:", pinned_texts)
        sources = get_context_sources(conversation_id)
    
    # Pull summary if present
    summary = get_conversation_summary_text(conversation_id)
    if (False):
        summary = ""
        sj = sources.get("summary_json")
        if sj:
            try:
                obj = json.loads(sj)
                summary = (obj.get("summary") or "").strip()
            except Exception:
                summary = ""

    retrieved_rows_raw: list[dict] = []
    retrieved_rows: list[dict] = []
    retrieved_block = ""
    retrieved_meta: list[dict] = []
    retrieved_cites: list[str] = []
    retrieval_debug: dict | None = None

    if do_fts_rag:
        chunks_resp = retrieve_chunks_for_message(
            conversation_id=conversation_id,
            user_message=user_text,
            limit=8,
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

        retrieved_block, retrieved_meta, retrieved_cites = _format_retrieved_chunks(
            retrieved_rows,
            max_chunks=8,
            max_chars=2200, #1200
            excerpt_query=user_text,
        )

    # We're skipping all searches - say why
    if not (do_fts_rag or do_vector_rag):
        retrieval_debug = {
            "skipped": True,
            "reason": f"query_mode={query_cfg.query_mode} user_text_present={bool(user_text.strip())}",
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
        assembled_input_preview = [{"role": "system", "content": system_text}] + normalized_file_messages + assembled_input_preview
        token_stats = estimate_context_tokens(conversation_id, ctx_cfg, user_text, model=ctx_cfg.estimate_model)

    return {
        "conversation_id": conversation_id,
        "project_id": sources.get("project_id"),
        "project_name": sources.get("project_name"),
        "file_include": bool(do_include_files),
        "fts_rag_active": bool(do_fts_rag),
        "vector_rag_active": bool(do_vector_rag),
        "query_mode": query_cfg.query_mode,
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
        "scoped_files": scoped_files,
        "file_messages": normalized_file_messages,
    }

def build_model_input(
        conversation_id: str, 
        user_text: str, 
        ctx_cfg: ContextConfig | None = None,
        query_cfg: QueryConfig | None = None,
        ctx: dict | None = None
    ) -> list[dict]:
    """
    Build a Responses-API compatible input.
    Use string `content` for all text messages (max compatibility).
    Keep file/image messages as typed parts ONLY when needed.
    """
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_query_config()
    
    ctx = ctx or build_context(conversation_id, user_text, ctx_cfg, query_cfg, include_preview=False)

    # TODO ensure pinned, summary, and retrieved are included in system_text
    history_rows = ctx.get("history_rows") or []
    system_message = {"role": "system", "content": ctx["system_text"]}
    normalized_file_messages = ctx.get("file_messages") or []

    # If first message, just return the system prompt and the files list
    # Otherwise split the last message off and show it after the file list.
    # TODO could this be simplified?
    if not history_rows:
        return [system_message] + normalized_file_messages
    typed_history = ctx["history_rows_typed"]
    *prior_msgs, last_msg = typed_history
    return [system_message] + prior_msgs + normalized_file_messages + [last_msg]

def build_context_panel_payload(
    conversation_id: str,
    user_text: str,
    ctx_cfg: ContextConfig | None = None,
    query_cfg: QueryConfig | None = None,
) -> dict:
    """
    Side-panel-only diagnostic payload.
    This is NOT the function used to assemble model input for a live chat turn.
    """
    ctx_cfg = ctx_cfg or load_context_config()
    query_cfg = query_cfg or load_query_config()

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
    included_file_labels = [_panel_label_for_file_message(m) for m in file_messages]

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

def _build_file_messages_for_conversation(conversation_id: str) -> list[dict]:
    """
    Build extra user messages representing file and image artifacts that should
    be included in the model input.

    Returns a list of message dicts:
    [
    {"role": "user", "content": [ { "type": "input_text", "text": "..." }, ... ]},
    ...
    ]
    """
    files_by_id: dict[str, dict] = gather_scoped_files(conversation_id)
    if not files_by_id:
        return []

    ensure_artifacts_for_files(files_by_id)

    file_messages: list[dict] = []

    # After artifacting, pull artifacts per file and turn them into messages.
    for file_id, file_row in files_by_id.items():
        try:
            artifacts = list_artifacts_for_file(file_id, include_deleted=False)
        except Exception as exc:
            print(f"[context] list_artifacts_for_file (post-artifact) failed for file {file_id}: {exc}")
            continue

        if not artifacts:
            continue

        # Use a friendly name if present
        orig_name = file_row.get("original_name") or Path(file_row.get("path") or "").name

        for art in artifacts:
            source_kind = art.get("source_kind") or ""
            # As of v8 schema, this is the only thing in this file calling this field by this particular name
            content = art.get("content_text") or ""

            # Image artifacts: content is a JSON blob created by build_image_reference_json
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
                            {
                                "type": "input_text",
                                "text": f"[Image file: {orig_name}]",
                            },
                            {
                                "type": "input_image",
                                "image_url": data_url,
                            },
                        ],
                    }
                )
            else:
                # Everything else is treated as text; large files may be chunked into multiple artifacts.
                text = str(content)
                if not text.strip():
                    continue

                file_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": f"[File: {orig_name}]\n{text}",
                            }
                        ],
                    }
                )

    return file_messages

if(False):
    def build_model_input(conversation_id: str, history_limit: int = 200) -> list[dict]:
        """
        Build a Responses-API compliant input where EVERY message.content is a list of typed parts.
        This avoids mixed formats (string content vs list-of-parts), which some models reject.
        """
        ctx = build_context(conversation_id, history_limit=history_limit)
        history_rows = get_messages(conversation_id, limit=history_limit)

        pinned = ctx["pinned_memories"]
        summary = ctx["summary"]
        retrieved = ctx["retrieved_memories"]

        system_blocks = [ctx["system_prompt"]]
        if pinned:
            system_blocks.append(
                "Pinned memories (user-curated, treat as true):\n"
                + "\n".join(f"- {t}" for t in pinned)
            )
        if summary.strip():
            system_blocks.append("Conversation summary:\n" + summary.strip())
        if retrieved:
            system_blocks.append(
                "Retrieved memories (machine-selected; verify if uncertain):\n"
                + "\n".join(f"- {t}" for t in retrieved)
            )

        system_text = "\n\n".join(system_blocks)

        system_message = {
            "role": "system",
            "content": [{"type": "input_text", "text": system_text}],
        }

        if not history_rows:
            return [system_message]

        # Build typed history (assistant+user as input_text parts)
        typed_history: list[dict] = []
        for r in history_rows:
            created_at = (r.get("created_at") or "").strip() if r.get("created_at") else ""
            raw_content = r.get("content") or ""

            if created_at:
                text = zeitgeber_prefix(created_at, raw_content)
            else:
                text = raw_content

            typed_history.append(
                {
                    "role": r["role"],
                    "content": [{"type": "input_text", "text": text}],
                }
            )

        # Split last message so we can insert file context before it
        *prior_msgs, last_msg = typed_history

        # File messages already return typed parts including input_image for image files
        file_messages = _build_file_messages_for_conversation(conversation_id)

        return [system_message] + prior_msgs + file_messages + [last_msg]

if (False): # improved error handling
    def build_model_input(conversation_id: str, history_limit: int = 200) -> list[dict]:
        ctx = build_context(conversation_id, history_limit=history_limit)
        history_rows = get_messages(conversation_id, limit=history_limit)

        pinned = ctx["pinned_memories"]
        summary = ctx["summary"]
        retrieved = ctx["retrieved_memories"]

        system_blocks = [ctx["system_prompt"]]
        if pinned:
            system_blocks.append(
                "Pinned memories (user-curated, treat as true):\n"
                + "\n".join(f"- {t}" for t in pinned)
            )
        if summary.strip():
            system_blocks.append("Conversation summary:\n" + summary.strip())
        if retrieved:
            system_blocks.append(
                "Retrieved memories (machine-selected; verify if uncertain):\n"
                + "\n".join(f"- {t}" for t in retrieved)
            )

        system_message = {
            "role": "system",
            "content": "\n\n".join(system_blocks),
        }

        # No history yet: just the system prompt.
        if not history_rows:
            return [system_message]

        # Rebuild history so we ONLY pass role + content to OpenAI.
        annotated_history: list[dict] = []
        for r in history_rows:
            created_at = (r.get("created_at") or "").strip() if r.get("created_at") else ""
            raw_content = r.get("content") or ""

            # If you want timestamps visible to the model, keep this prefix.
            # If not, just set `text = raw_content`.
            if created_at:
                text = zeitgeber_prefix(created_at, raw_content)
            else:
                text = raw_content

            annotated_history.append(
                {
                    "role": r["role"],
                    "content": text,
                }
            )

        # Split out the last message so we can insert file context before it.
        *prior_msgs, last_msg = annotated_history

        # Build file-derived messages (text + images) for this conversation.
        file_messages = _build_file_messages_for_conversation(conversation_id)

        # Final input: system prompt, prior conversation, file context, then the latest user turn.
        return [system_message] + prior_msgs + file_messages + [last_msg]

if (False):  # legacy version without zeitgeber prefix and with raw DB content in history
    def build_model_input(conversation_id: str, history_limit: int = 200) -> list[dict]:
        ctx = build_context(conversation_id, history_limit=history_limit)
        history = get_messages(conversation_id, limit=history_limit)

        pinned = ctx["pinned_memories"]
        summary = ctx["summary"]
        retrieved = ctx["retrieved_memories"]

        system_blocks = [ctx["system_prompt"]]
        if pinned:
            system_blocks.append(
                "Pinned memories (user-curated, treat as true):\n"
                + "\n".join(f"- {t}" for t in pinned)
            )
        if summary.strip():
            system_blocks.append("Conversation summary:\n" + summary.strip())
        if retrieved:
            system_blocks.append(
                "Retrieved memories (machine-selected; verify if uncertain):\n"
                + "\n".join(f"- {t}" for t in retrieved)
            )

        system_message = {
            "role": "system",
            "content": "\n\n".join(system_blocks),
        }

        # If there's no message history yet, just return the system message.
        if not history:
            return [system_message]

        # Split out the last message so we can insert file context right before it.
        *prior_msgs, last_msg = history

        # Build file-derived messages (text + images) for this conversation.
        file_messages = _build_file_messages_for_conversation(conversation_id)

        # Final input: system prompt, prior conversation, file context, then the latest user turn.
        return [system_message] + prior_msgs + file_messages + [last_msg]
    
    def build_model_input(conversation_id: str, history_limit: int = 200) -> list[dict]:
        ctx = build_context(conversation_id, history_limit=history_limit)
        # Rebuild full input without truncating to preview
        history = get_messages(conversation_id, limit=history_limit)
        
        pinned = ctx["pinned_memories"]
        summary = ctx["summary"]
        retrieved = ctx["retrieved_memories"]
        system_blocks = [ctx["system_prompt"]]
        if pinned:
            system_blocks.append("Pinned memories (user-curated, treat as true):\n" + "\n".join(f"- {t}" for t in pinned))
        if summary.strip():
            system_blocks.append("Conversation summary:\n" + summary.strip())
        if retrieved:
            system_blocks.append("Retrieved memories (machine-selected, verify if uncertain):\n" + "\n".join(f"- {t}" for t in retrieved))

        return [{"role": "system", "content": "\n\n".join(system_blocks)}] + history