from datetime import datetime, timezone
import json
import os
#from typing import cast
from pathlib import Path
from .db import (
    get_messages,
    list_memory_pins,
    get_context_sources,
    list_files_for_conversation,
    list_files_for_project,
    list_all_files,
    list_artifacts_for_file,
)
from .artifactor import artifact_file
from .image_helpers import load_image_bytes, image_bytes_to_base64
try:
    import tiktoken
except ImportError:
    tiktoken = None

# From openai/types/responses/response_create_params.py
# from openai.types.responses import ResponseInputParam

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Be concise, candid, and technically accurate."

def get_system_prompt() -> str:
    """
    Loads system prompt in this precedence order:
    1) SYSTEM_PROMPT_FILE (read text file)
    2) SYSTEM_PROMPT (env var, supports literal '\n' sequences)
    3) DEFAULT_SYSTEM_PROMPT (fallback hardcoded string)
    """
    file_path = os.getenv("SYSTEM_PROMPT_FILE", "").strip()
    print(f"Loading system prompt from file: {file_path}")  # Debug print)
    if file_path:
        p = Path(file_path)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")

    print("No valid SYSTEM_PROMPT_FILE found, checking SYSTEM_PROMPT env var...")  # Debug print
    val = os.getenv("SYSTEM_PROMPT", "")
    if val:
        print(f"Loaded SYSTEM_PROMPT from env var: {val[:60]}...")  # Debug print (showing only first 60 chars)
        # If your .env uses \n escapes, turn them into real newlines
        val = val.replace("\\n", "\n")
        return val
    
    print("No SYSTEM_PROMPT env var found, using default system prompt.")  # Debug print
    return DEFAULT_SYSTEM_PROMPT

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
    history_limit: int = 200,
    model: str = "gpt-5.2",
    drop_last_user_message: bool = False,
) -> dict:
    """
    Estimate tokens for the context that will be sent with the next user message,
    excluding that next user message itself.
    """
    full_input = build_model_input(conversation_id, history_limit=history_limit)
    if not full_input:
        return {"total_chars": 0, "approx_text_tokens": 0, "num_images": 0}

    # Optionally, Drop the last message (most recent user turn) so this is “context load”, not “what they’re about to send”.
    if drop_last_user_message and full_input[-1].get("role") == "user":
        context = full_input[:-1]
    else:
        context = full_input
    return estimate_tokens_for_messages(context, model=model)

def build_context(conversation_id: str, history_limit: int = 200, preview_limit: int = 20) -> dict:
    sources = get_context_sources(conversation_id)

    history = get_messages(conversation_id, limit=history_limit)

    pinned = list_memory_pins(limit=200)
    pinned_texts = [p["text"] for p in pinned]

    # Pull summary if present
    summary = ""
    sj = sources.get("summary_json")
    if sj:
        try:
            obj = json.loads(sj)
            summary = (obj.get("summary") or "").strip()
        except Exception:
            summary = ""

    retrieved = []  # still placeholder

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

    if pinned_texts:
        joined = "\n".join(f"- {t}" for t in pinned_texts)
        system_blocks.append("Pinned memories (user-curated, treat as true):\n" + joined)

    if summary:
        system_blocks.append("Conversation summary:\n" + summary)

    if retrieved:
        joined = "\n".join(f"- {m}" for m in retrieved)
        system_blocks.append("Retrieved memories (machine-selected, verify if uncertain):\n" + joined)

    assembled_input = [{"role": "system", "content": "\n\n".join(system_blocks)}] + history

    preview = assembled_input[-preview_limit:] if preview_limit > 0 else assembled_input
    truncated = len(preview) < len(assembled_input)

    return {
        "conversation_id": conversation_id,
        "system_prompt": system_prompt,
        "pinned_memories": pinned_texts,
        "retrieved_memories": retrieved,
        "summary": summary,
        "history_count": len(history),
        "assembled_input_preview": preview,
        "assembled_input_count": len(assembled_input),
        "assembled_input_preview_limit": preview_limit,
        "assembled_input_preview_truncated": truncated,
    }

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
    files_by_id: dict[str, dict] = _gather_scoped_files(conversation_id)
    if not files_by_id:
        return []

    _ensure_artifacts_for_files(files_by_id)

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
            content = art.get("content") or ""

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

def _ensure_artifacts_for_files(files_by_id: dict[str, dict]) -> None:
    """
    For each file, if there are no (non-deleted) artifacts, call artifact_file(file_row).
    Swallow errors per-file so one broken file doesn't kill the context build.
    """

    print(f"[context] _ensure_artifacts_for_files: checking {len(files_by_id)} files")     
    for file_id, file_row in files_by_id.items():
        try:
            existing = list_artifacts_for_file(file_id, include_deleted=False)
            print(f"[context] file {file_id}: {len(existing)} existing artifacts")
        except Exception as exc:
            print(f"[context] list_artifacts_for_file failed for file {file_id}: {exc}")
            continue

        if existing:
            continue  # already artifacted

        try:
            artifact_file(file_row)
        except Exception as exc:
            # This might be "no project_id for global file" or a decode error; just log and move on.
            print(f"[context] artifact_file failed for file {file_id}: {exc}")
            continue

def _gather_scoped_files(conversation_id: str) -> dict[str, dict]:
    """
    Collect all files that should be considered for this conversation:
    - conversation-scoped
    - project-scoped (if any)
    - global/unassigned
    Returns a dict keyed by file id -> file row, to dedupe across scopes.
    """
    sources = get_context_sources(conversation_id)
    project_id = sources.get("project_id")

    files_by_id: dict[str, dict] = {}

    # Conversation-scoped files
    for f in list_files_for_conversation(conversation_id, include_deleted=False):
        files_by_id[f["id"]] = f

    # Project-scoped files, if any
    if project_id:
        for f in list_files_for_project(project_id, include_deleted=False):
            files_by_id[f["id"]] = f

    # Global / unscoped files
    for f in list_all_files(include_deleted=False):
        scope_type = f.get("scope_type")
        # Treat explicit "global" or completely unscoped files as global.
        if not scope_type or scope_type == "global":
            files_by_id[f["id"]] = f

    print(f"[context] _gather_scoped_files({conversation_id!r}) -> {len(files_by_id)} files")
    return files_by_id

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

"""
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
"""
    
"""
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
"""