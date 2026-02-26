import json
import os
#from typing import cast
from .db import get_messages, list_memory_pins, get_context_sources
from pathlib import Path

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
    if file_path:
        p = Path(file_path)
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")

    val = os.getenv("SYSTEM_PROMPT", "")
    if val:
        # If your .env uses \n escapes, turn them into real newlines
        val = val.replace("\\n", "\n")
        return val

    return DEFAULT_SYSTEM_PROMPT

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

"""
def build_context(conversation_id: str, history_limit: int = 200, preview_limit: int = 20) -> dict:
    history = get_messages(conversation_id, limit=history_limit)

    pinned = list_memory_pins(limit=200)  # currently global pins
    pinned_texts = [p["text"] for p in pinned]

    summary = ""  # placeholder for later rolling-summary

    retrieved = []  # placeholder for later vector retrieval results

    system_prompt = get_system_prompt()
    system_blocks = [system_prompt]

    if pinned_texts:
        joined = "\n".join(f"- {t}" for t in pinned_texts)
        system_blocks.append("Pinned memories (user-curated, treat as true):\n" + joined)

    if summary.strip():
        system_blocks.append("Conversation summary:\n" + summary.strip())

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
