from __future__ import annotations

from enum import Enum
from typing import Optional, Set, Iterable
from dataclasses import dataclass
import discord

from callie_logging import log
#Fixed a circular import by moving build_callie_names to discord_helpers
from discord_helpers import _default_callie_names_from_bot_user, is_message_invoked, should_suppress_ambient_reply
from global_config import GlobalConfig
from pk_helper import PKInfo

class ChannelReplyMode(str, Enum):
    DISALLOWED = "disallowed"   # not allowed at all (no record, no summary, no reply)
    REPLY_ONLY = "reply_only"   # allowed, but only when invoked (mention/reply/etc.)
    PASSIVE = "passive"         # allowed for record/summary, but do not speak unless invoked / heuristics allow it
    AMBIENT = "ambient"         # allowed to speak ambiently to every post (subject to heuristics/gates)

global_config: GlobalConfig = GlobalConfig()

@dataclass(frozen=True)
class EffectiveAuthor:
    author_id: int
    author_name: str
    is_bot: bool
    is_pk_proxy: bool = False
    pk_owner_id: Optional[int] = None

@dataclass(frozen=True)
class AccessDecision:
    mode: ChannelReplyMode
    allowed: bool                 # overall, including RBAC
    record: bool                  # should we store the message in DB
    can_speak: bool               # may we generate a response at all
    speak_suppressed: bool        # whether speaking was suppressed (e.g., ambient suppression)
    is_invoked: bool              # mention/reply/command
    effective_channel_id: int     # usually parent for threads
    parent_channel_id: Optional[int]
    reason: str                   # for logs
    effective_author: EffectiveAuthor

def _as_set(ids: Iterable[int]) -> Set[int]:
    return set(int(x) for x in ids if x)

def _get_parent_channel_id(message: discord.Message) -> Optional[int]:
    ch = message.channel
    # discord.Thread has .parent_id
    parent_id = getattr(ch, "parent_id", None)
    if parent_id is None:
        return None
    try:
        return int(parent_id)
    except Exception:
        return None

async def resolve_channel_reply_mode(
    cfg,
    channel_id: int,
    parent_channel_id: Optional[int],
) -> tuple[ChannelReplyMode, int]:
    """
    Returns (mode, effective_channel_id).
    effective_channel_id is the channel id that satisfied the ALLOWED gate.
    In threads, this will usually be parent_channel_id.
    """
    allowed = _as_set(await cfg.allowed_channel_ids())
    passive = _as_set(await cfg.passive_channel_ids())
    ambient = _as_set(await cfg.ambient_channel_ids())

    candidates = [int(channel_id)]
    if parent_channel_id:
        candidates.append(int(parent_channel_id))

    if not any(cid in allowed for cid in candidates):
        return (ChannelReplyMode.DISALLOWED, int(channel_id))

    effective_channel_id = next((cid for cid in candidates if cid in allowed), int(channel_id))

    # Diagnostic: if someone double-listed, make it obvious and deterministic.
    # PASSIVE wins over AMBIENT.
    check_ids = set(candidates)
    for cid in check_ids:
        if (cid in passive) and (cid in ambient):
            log.warning(
                f"AccessGate: channel in BOTH PASSIVE and AMBIENT; PASSIVE wins. channel_id={cid}"
            )

    if any(cid in passive for cid in candidates):
        return (ChannelReplyMode.PASSIVE, effective_channel_id)

    if any(cid in ambient for cid in candidates):
        return (ChannelReplyMode.AMBIENT, effective_channel_id)

    return (ChannelReplyMode.REPLY_ONLY, effective_channel_id)

#async def resolve_effective_author_pk(message: discord.Message) -> EffectiveAuthor:
#    """
#    IMPORTANT: wire this to your existing PluralKit logic.
#    The goal is: if it's a PK proxied message, return the owning user's id/name and is_bot=False.
#
#    Placeholder behavior here: treat message.author as the author.
#    Replace/augment with your real PK resolution.
#    """
#    a = message.author
#    # If your existing code detects PK and extracts "owner_id" and "proxy_name",
#    # return EffectiveAuthor(owner_id, proxy_name, is_bot=False, is_pk_proxy=True, pk_owner_id=owner_id)
#    return EffectiveAuthor(
#        author_id=int(a.id),
#        author_name=str(a.display_name),
#        is_bot=bool(a.bot),
#        is_pk_proxy=False,
#        pk_owner_id=None,
#    )

async def _passes_rbac_if_enabled(
    cfg,
    message: discord.Message,
    eff_author: EffectiveAuthor,
    #resolved_member: discord.Member | None = None,
) -> tuple[bool, str]:
    """
    RBAC gate. Preserve your existing semantics:
    - If REQUIRE_CALLIE_ROLE is false -> pass.
    - If true -> user must have an allowed role (for the effective author).
    For PK: effective author should be the owning user id, and member lookup should use that.
    """
    require_role = await cfg.require_callie_role()
    if not require_role:
        return (True, "rbac:skipped")

    # DMs or no guild context can't pass RBAC in multi-tenant mode.
    if not message.guild:
        return (False, "rbac:missing_guild")

    allowed_roles = set(await cfg.allowed_role_ids())
    if not allowed_roles:
        return (False, "rbac:no_allowed_roles_configured")

    # Find the member for effective author id (works for normal users and PK owner_id)
    member: discord.Member | None = message.guild.get_member(int(eff_author.author_id))
    if member is None:
        try:
            member = await message.guild.fetch_member(int(eff_author.author_id))
        except Exception:
            member = None

    if member is None:
        return (False, "rbac:member_not_found")

    member_roles = {int(r.id) for r in getattr(member, "roles", []) if r}
    if member_roles.intersection(allowed_roles):
        return (True, "rbac:ok")

    return (False, "rbac:denied")



async def compute_access_decision(
    cfg,
    message: discord.Message,
    bot_user_id: int,
    bot_user: Optional[discord.ClientUser] | None = None,
    pk_info: PKInfo | None = None,
    #resolved_member: discord.Member | None = None,
    *,
    force_invoked: Optional[bool] = None,
) -> AccessDecision:
    """
    Single, deterministic access decision used by on_message and command handlers.
    This function should NOT have side effects (no DB writes).
    """

    # default: the Discord message author
    effective_author_id = int(getattr(message.author, "id", 0))
    effective_author_name = (
        getattr(message.author, "display_name", None)
        or getattr(message.author, "name", None)
        or str(message.author)
    )
    is_pk_proxy = False
    # if PK was detected, store under the owning user (sender_id) but keep the proxy name for conversational identity elsewhere
    if pk_info is not None and pk_info.sender_id:
        is_pk_proxy = True
        effective_author_id = int(pk_info.sender_id)
        # keep author_name as the visible proxy name, because that’s what humans see
        proxy_name = (
            getattr(message.author, "display_name", None)
            or getattr(message.author, "name", None)
            or effective_author_name
        )
        effective_author_name = proxy_name
    # Vivian - don't we think the above code does the same as resolve_effective_author_pk
    # I'll delete commented code over my dead body!
    #eff_author = await resolve_effective_author_pk(message)
    eff_author = EffectiveAuthor(
        author_id=effective_author_id,
        author_name=effective_author_name,
        is_bot=bool(message.author.bot),
        is_pk_proxy=is_pk_proxy,
        pk_owner_id=int(pk_info.sender_id) if (is_pk_proxy and pk_info is not None) else None,
    )

    # Ignore Discord system messages (cannot reply; also usually no meaningful content)
    if message.type != discord.MessageType.default and message.type != discord.MessageType.reply:
        return AccessDecision(
            mode=ChannelReplyMode.DISALLOWED,
            allowed=False,
            record=False,
            can_speak=False,
            speak_suppressed=False,
            is_invoked=False,
            effective_channel_id=int(message.channel.id),
            parent_channel_id=_get_parent_channel_id(message),
            reason=f"system_message:{message.type}",
            effective_author=eff_author,
        )
    # determine correct actual channel ID to check
    parent_id = _get_parent_channel_id(message)
    mode, effective_channel_id = await resolve_channel_reply_mode(
        cfg,
        channel_id=int(message.channel.id),
        parent_channel_id=parent_id,
    )

    # If not allowed channel-wise, we go dark: no record, no summaries, no replies.
    if mode == ChannelReplyMode.DISALLOWED:
        return AccessDecision(
            mode=mode,
            allowed=False,
            record=False,
            can_speak=False,
            speak_suppressed=False,
            is_invoked=False,
            effective_channel_id=int(effective_channel_id),
            parent_channel_id=parent_id,
            reason="channel:disallowed",
            effective_author=eff_author,
        )
    # Now handle bot filtering AFTER PK resolution.
    # If it's a real bot and not PK proxy, ignore.
    if eff_author.is_bot and not eff_author.is_pk_proxy:
        return AccessDecision(
            mode=mode,
            allowed=False,
            record=False,
            can_speak=False,
            speak_suppressed=False,
            is_invoked=False,
            effective_channel_id=int(effective_channel_id),
            parent_channel_id=parent_id,
            reason="author:bot",
            effective_author=eff_author
        )

    # Ensure we have bot_user available if it was not provided.
    if bot_user is None:
        try:
            bot_user = bot_user or message.guild.me or message._state._get_client()  # type: ignore
        except Exception:
            bot_user = message._state._get_client()  # type: ignore 
    # Pre-build bot names for invocation detection and ambient suppression.
    bot_names = cfg.global_config.build_callie_names()
    if not bot_names or len(bot_names) == 0:
        try:
            bot_names = global_config.build_callie_names() or _default_callie_names_from_bot_user(bot_user)
        except Exception:
            pass
    log.debug("compute_access_decision: bot_names=%s", bot_names)

    # Determine invocation state.
    if force_invoked is None:
        invoked = await is_message_invoked(message, bot_user=bot_user, bot_user_id=bot_user_id, bot_names=bot_names)
    else:
        invoked = bool(force_invoked)
    # RBAC gate (only applies to allowed channels).
    rbac_ok, rbac_reason = await _passes_rbac_if_enabled(
        cfg,
        message,
        eff_author,
    )
    if not rbac_ok:
        # Conservative: if RBAC denies, don't record either (keeps “awareness” bounded).
        return AccessDecision(
            mode=mode,
            allowed=False,
            record=False,
            can_speak=False,
            speak_suppressed=False,
            is_invoked=invoked,
            effective_channel_id=int(effective_channel_id),
            parent_channel_id=parent_id,
            reason=rbac_reason,
            effective_author=eff_author,
        )

    # Recording policy for this phase:
    # allowed channels => record is True (you already do this today)
    record = True

    # Speaking rules:
    # - AMBIENT: can speak even if not invoked (later: heuristics throttle)
    # - REPLY_ONLY: only if invoked
    # - PASSIVE: only if invoked (but still record/summarize)
    speak_suppressed: bool = False
    if mode == ChannelReplyMode.AMBIENT:
        can_speak = True
        # Ambient reply suppression
        speak_suppressed = await should_suppress_ambient_reply(
            message, bot_user=bot_user,
            suppress_enabled=await cfg.suppress_ambient_replies(),
            allow_name_prefix=await cfg.allow_name_prefix(),
            bot_names=bot_names) or False
    else:
        can_speak = invoked

    return AccessDecision(
        mode=mode,
        allowed=True,
        record=record,
        can_speak=can_speak,
        speak_suppressed=speak_suppressed,
        is_invoked=invoked,
        effective_channel_id=int(effective_channel_id),
        parent_channel_id=parent_id,
        reason="ok",
        effective_author=eff_author,
    )