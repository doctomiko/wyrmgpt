# pk_helpers.py
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any

import httpx
import discord


PK_API = "https://api.pluralkit.me/v2/messages/{message_id}"

@dataclass(frozen=True)
class PKInfo:
    sender_id: int
    #proxy_name: Optional[str]
    member_name: Optional[str]
    system_name: Optional[str]
    member_id: Optional[str]
    system_id: Optional[str]

    @staticmethod
    def from_api(data: Dict[str, Any]) -> "PKInfo":
        # PluralKit returns "sender" as a stringified Discord ID
        sender_raw = data.get("sender")
        if sender_raw is None:
            raise ValueError("Missing 'sender' in PluralKit data")
        sender_id = int(str(sender_raw))
        member = data.get("member") or {}
        system = data.get("system") or {}
        return PKInfo( 
            sender_id=sender_id,
            #proxy_name="", # member.get("name"),
            member_name=member.get("name"),
            system_name=system.get("name"),
            member_id=member.get("id"),
            system_id=system.get("id"),
        )

class PKResolver:
    """
    Small resolver with TTL cache so we don't hammer PK API.
    """
    def __init__(self, *, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._cache: Dict[int, Tuple[float, Optional[PKInfo]]] = {}

    def get_cached(self, message_id: int) -> Optional[PKInfo]:
        rec = self._cache.get(message_id)
        if not rec:
            return None
        ts, info = rec
        if (time.time() - ts) > self._ttl:
            self._cache.pop(message_id, None)
            return None
        return info

    def set_cached(self, message_id: int, info: Optional[PKInfo]) -> None:
        self._cache[message_id] = (time.time(), info)

    async def resolve(self, message: discord.Message) -> Optional[PKInfo]:
        if getattr(message, "webhook_id", None) is None:
            return None

        cached = self.get_cached(message.id)
        if cached is not None:
            return cached

        url = PK_API.format(message_id=message.id)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                if r.status_code == 404:
                    self.set_cached(message.id, None)
                    return None
                r.raise_for_status()
                info = PKInfo.from_api(r.json())
                self.set_cached(message.id, info)
                return info
        except Exception:
            # If PK API is down, don't break the bot; just treat as unresolved.
            self.set_cached(message.id, None)
            return None

def build_pk_context_block(
    *,
    pk_info,
    message: discord.Message,
) -> str:
    """
    Returns a compact, machine-readable PK annotation for model context.
    """
    proxy_name = (
        getattr(message.author, "display_name", None)
        or getattr(message.author, "name", None)
        or "Unknown"
    )
    payload = {
        "speaker_display": proxy_name,
        "speaker_kind": "plural_proxy",
        "pk_member": pk_info.member_name,
        "pk_system": pk_info.system_name,
        "sender_discord_id": str(pk_info.sender_id),
        "reply_policy": "reply_to_message_no_mention",
    }
    return (
        "\n[SpeakerIdentity]\n"
        "```json\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n```\n"
    )

def format_pk_proxy_note(pk: PKInfo, *, visible_proxy_name: str, resolved_member: Optional[discord.Member]) -> str:
    resolved_name = getattr(resolved_member, "display_name", None) or getattr(resolved_member, "name", None) if resolved_member else "Unknown"
    resolved_id = getattr(resolved_member, "id", None) if resolved_member else "Unknown"

    return (
        "\n\n[Proxy note]\n"
        "This message was posted via a webhook/proxy (PluralKit).\n"
        f"Visible proxy name: {visible_proxy_name}\n"
        f"PluralKit member: {pk.member_name or 'Unknown'} (member_id={pk.member_id or 'Unknown'})\n"
        f"PluralKit system: {pk.system_name or 'Unknown'} (system_id={pk.system_id or 'Unknown'})\n"
        f"Resolved Discord sender for permissions: {resolved_name} (id={resolved_id})\n"
        "Use the resolved Discord sender for role/permission checks, but address the speaker conversationally by the visible proxy name.  Prefer replying to the message (message reference) rather than pinging a user."
    )
