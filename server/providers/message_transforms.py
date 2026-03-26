from __future__ import annotations

from typing import Any

from .types import ModelInput


def _data_url_parts(data_url: str) -> tuple[str, str] | None:
    raw = (data_url or "").strip()
    if not raw.startswith("data:"):
        return None
    try:
        header, data = raw.split(",", 1)
    except ValueError:
        return None
    if ";base64" not in header:
        return None
    mime_type = header[5:].split(";", 1)[0].strip() or "application/octet-stream"
    return mime_type, data


def _stringify_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "input_text":
                text = str(block.get("text", "") or "")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()
    return str(content or "").strip()


def to_openai_chat_messages(model_input: ModelInput) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []

    for msg in model_input:
        role = str(msg.get("role", "user") or "user").strip() or "user"
        content = msg.get("content", "")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue

        if not isinstance(content, list):
            messages.append({"role": role, "content": str(content or "")})
            continue

        parts: list[dict[str, Any]] = []
        text_fragments: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = str(block.get("type", "") or "").strip()
            if btype == "input_text":
                text = str(block.get("text", "") or "")
                if text:
                    text_fragments.append(text)
            elif btype == "input_image":
                image_url = str(block.get("image_url", "") or "").strip()
                if image_url:
                    parts.append({"type": "image_url", "image_url": {"url": image_url}})

        if text_fragments:
            joined_text = "\n".join(text_fragments).strip()
            if parts:
                parts.insert(0, {"type": "text", "text": joined_text})
            else:
                messages.append({"role": role, "content": joined_text})
                continue

        if parts:
            messages.append({"role": role, "content": parts})
        else:
            messages.append({"role": role, "content": ""})

    return messages


def to_anthropic_messages(model_input: ModelInput) -> tuple[str, list[dict[str, Any]]]:
    system_blocks: list[str] = []
    messages: list[dict[str, Any]] = []

    for msg in model_input:
        raw_role = str(msg.get("role", "user") or "user").strip().lower() or "user"
        content = msg.get("content", "")

        if raw_role == "system":
            system_text = _stringify_text_content(content)
            if system_text:
                system_blocks.append(system_text)
            continue

        role = "assistant" if raw_role == "assistant" else "user"
        blocks: list[dict[str, Any]] = []

        if isinstance(content, str):
            if content:
                blocks.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = str(block.get("type", "") or "").strip()
                if btype == "input_text":
                    text = str(block.get("text", "") or "")
                    if text:
                        blocks.append({"type": "text", "text": text})
                elif btype == "input_image":
                    image_url = str(block.get("image_url", "") or "").strip()
                    parsed = _data_url_parts(image_url)
                    if parsed is None:
                        continue
                    mime_type, data = parsed
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": data,
                            },
                        }
                    )
        else:
            text = str(content or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})

        if blocks:
            messages.append({"role": role, "content": blocks})

    return "\n\n".join(system_blocks).strip(), messages
