# server/identity_context_patch.py
"""Runtime patch for adding active persona prompts to assembled context.

Kept separate from server/context.py on purpose: context.py is large and high-risk
for connector-based whole-file edits. This wrapper is small and reversible.
"""

from __future__ import annotations

from typing import Any

from server.identity_db import get_persona_prompt_for_conversation
from server.logging_helper import log_warn

_INSTALLED = False


def _persona_block(persona: dict[str, Any]) -> str:
    name = str(persona.get("name") or "Persona").strip()
    slug = str(persona.get("slug") or "").strip()
    source = str(persona.get("source") or "custom").strip()
    prompt_file = str(persona.get("prompt_file") or "").strip()
    text = str(persona.get("text") or "").strip()

    header = f"ACTIVE CHAT PERSONA: {name}"
    meta = []
    if slug:
        meta.append(f"slug={slug}")
    if source:
        meta.append(f"source={source}")
    if prompt_file:
        meta.append(f"prompt_file={prompt_file}")

    if meta:
        header = header + " [" + "; ".join(meta) + "]"
    return f"{header}\n{text}".strip()


def _apply_persona_to_context(ctx: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    try:
        persona = get_persona_prompt_for_conversation(conversation_id)
    except Exception as exc:
        log_warn("Failed loading active persona prompt for %s: %s", conversation_id, exc)
        return ctx

    if not persona or not str(persona.get("text") or "").strip():
        return ctx

    block = _persona_block(persona)
    existing = str(ctx.get("system_text") or ctx.get("effective_system_prompt") or "").strip()
    system_text = f"{existing}\n\n{block}".strip() if existing else block

    ctx["system_text"] = system_text
    ctx["effective_system_prompt"] = system_text
    ctx["active_persona_prompt"] = {
        "persona_id": persona.get("persona_id"),
        "name": persona.get("name"),
        "slug": persona.get("slug"),
        "source": persona.get("source"),
        "prompt_file": persona.get("prompt_file"),
    }

    preview = ctx.get("assembled_input_preview")
    if isinstance(preview, list) and preview and isinstance(preview[0], dict) and preview[0].get("role") == "system":
        preview[0] = {**preview[0], "content": system_text}

    return ctx


def install_persona_context_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    import server.context as context_mod

    original = context_mod.build_context
    if getattr(original, "_persona_context_wrapped", False):
        _INSTALLED = True
        return

    def wrapped_build_context(conversation_id: str, *args, **kwargs):
        ctx = original(conversation_id, *args, **kwargs)
        if isinstance(ctx, dict):
            return _apply_persona_to_context(ctx, conversation_id)
        return ctx

    wrapped_build_context._persona_context_wrapped = True  # type: ignore[attr-defined]
    context_mod.build_context = wrapped_build_context
    _INSTALLED = True
