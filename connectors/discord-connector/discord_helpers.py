import asyncio
import json
import logging
import random
import re
import socket
import traceback
from types import CoroutineType
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp
import discord

from global_config import GlobalConfig
from outage_helpers import classify_discord_exception, format_admin_outage
from pk_helper import PKResolver
_pk = PKResolver(ttl_seconds=3600)

from callie_logging import log, setup_logging
# TODO avoid circular import if possible by moving these to a separate module
from guild_config import GuildConfig
log, _log_settings = setup_logging("discord_helpers")

global_config = GlobalConfig()

# Discord/aiohttp are chatty during reconnects; dial them down
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.client").setLevel(logging.WARNING)
logging.getLogger("discord.gateway").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

# Filter to suppress reconnect spam
class DiscordReconnectNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "Attempting a reconnect" in msg:
            # Drop the traceback spam; you can re-log your own concise message elsewhere
            return False
        return True

#handler0 = logging.getLogger("discord").handlers[0]  # or however you get your handler
#handler0.addFilter(DiscordReconnectNoiseFilter())
#handler1 = logging.getLogger("discord.client").handlers[0]  # or however you get your handler
#handler1.addFilter(DiscordReconnectNoiseFilter())
#handler2 = logging.getLogger("discord.gateway").handlers[0]  # or however you get your handler
#handler2.addFilter(DiscordReconnectNoiseFilter())
#handler3 = logging.getLogger("aiohttp").handlers[0]  # or however you get your handler
#handler3.addFilter(DiscordReconnectNoiseFilter())


def chunk_for_discord(text: str, limit: int) -> List[str]:
    """
    Split a long string into chunks that are safe to send to Discord.

    Chunking strategy (best-effort, in this order):
      1) Prefer paragraph breaks: '\n\n'
      2) Then sentence ends: '. ', '! ', '? ' (also handles newline after punctuation)
      3) Then whitespace (word boundary)
      4) Finally, hard cut

    Notes:
      - We do NOT double-escape anything. The string is split as-is.
      - We try to avoid producing empty chunks.
    """
    if limit <= 0:
        limit = 1900

    s = text or ""
    if len(s) <= limit:
        return [s]

    def _best_cut(window: str) -> int:
        """Return a cut index within window (0 < idx <= len(window))."""
        if not window:
            return 0

        # 1) Paragraph break
        i = window.rfind("\n\n")
        if i > 0:
            return i + 2  # include the break

        # 2) Sentence end: . ! ? followed by space/tab/newline
        for j in range(len(window) - 2, 0, -1):
            ch = window[j]
            if ch in ".!?":
                nxt = window[j + 1]
                if nxt in (" ", "\n", "\t"):
                    return j + 1  # cut right after punctuation

        # 3) Whitespace
        for j in range(len(window) - 1, 0, -1):
            if window[j].isspace():
                return j + 1

        # 4) Hard cut
        return len(window)

    chunks: List[str] = []
    rest = s
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break

        window = rest[:limit]
        cut = _best_cut(window)

        # Safety: if cut is 0 (shouldn't happen), hard cut.
        if cut <= 0:
            cut = limit

        part = rest[:cut]
        rest = rest[cut:]

        # Avoid leading whitespace explosion from word/sentence cuts.
        if rest and rest[0] == " " and part and part[-1].isspace():
            rest = rest.lstrip(" ")

        if part:
            chunks.append(part)

    # Final pass: avoid empty messages (Discord rejects empty content)
    return [c for c in chunks if c and c.strip() != ""]


async def passes_access_gate_gc(gc: GuildConfig, channel_id: int, member: Optional[discord.Member]) -> bool:
    """RBAC + channel gating using GuildConfig as source of truth.

    - gc.require_callie_role is the sole arbiter of RBAC enablement for regular users.
    - If gc.require_callie_role is true, member must have one of gc.allowed_role_ids.
    - Channel must be in gc.allowed_role_ids.
    - gc.role_channels_access_mode controls whether channel+role is AND or OR when RBAC is enabled.
    """
    require_role = await gc.require_callie_role()
    allowed_channels = set(await gc.allowed_channel_ids())
    allowed_roles = set(await gc.allowed_role_ids())
    access_mode = (await gc.role_channels_access_mode()).strip().upper()

    # No member (webhooks, etc): cannot satisfy role requirement if enabled.
    has_role = False
    if member is not None and allowed_roles:
        has_role = any(getattr(r, "id", None) in allowed_roles for r in getattr(member, "roles", []) or [])

    in_channel = (channel_id in allowed_channels) if allowed_channels else False

    if not require_role:
        return in_channel

    # RBAC enabled:
    if access_mode == "AND":
        return in_channel and has_role
    # Default OR
    return in_channel or has_role

def _anonymize_name(author_id: int, anon_map: Dict[int, str]) -> str:
    if author_id in anon_map:
        return anon_map[author_id]
    # Stable-ish within a single request: Uxxx where xxx is last 3 digits of id
    suffix = str(int(author_id))[-3:] if author_id else "000"
    label = f"User{suffix}"
    anon_map[author_id] = label
    return label

def apply_enrich_policy_to_transcript(transcript: List[dict], enrich_policy: str) -> Tuple[List[dict], Dict[int, str]]:
    """
    For enrich_policy='Anon', remove usernames and roles from model-visible transcript by
    pseudonymizing author_name values. Callie remains 'Callie'.
    Returns (new_transcript, anon_map).
    """
    pol = (enrich_policy or "full").strip().lower()
    anon_map: Dict[int, str] = {}
    if pol != "anon":
        return transcript, anon_map

    out: List[dict] = []
    for m in transcript:
        mm = dict(m)
        if mm.get("is_callie"):
            mm["author_name"] = "Callie"
        else:
            aid = int(mm.get("author_id") or 0)
            mm["author_name"] = _anonymize_name(aid, anon_map)
        out.append(mm)
    return out, anon_map

def get_effective_channel_id(message: "discord.Message", *, parent: bool = True) -> int:
    """
    If parent=True: return the real channel id (thread parent if in thread, else channel id).
    If parent=False: return the thread id (channel id as-is).
    """
    try:
        if parent and isinstance(message.channel, discord.Thread) and message.channel.parent_id:
            return int(message.channel.parent_id)
    except Exception:
        pass
    return int(message.channel.id)


def _default_callie_names_from_bot_user(bot_user: Optional[discord.ClientUser]) -> List[str]:
    names = global_config.build_callie_names()
    try:
        if bot_user is not None:
            dn = getattr(bot_user, "display_name", None)
            nm = getattr(bot_user, "name", None)
            if dn:
                names.append(str(dn))
            if nm:
                names.append(str(nm))
    except Exception:
        pass
    out: List[str] = []
    seen = set()
    for n in names:
        nn = (n or "").strip()
        if not nn:
            continue
        key = nn.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(nn)
    return out

def _build_callie_names_from_message(message: discord.Message) -> list[str]:
    names = global_config.build_callie_names()
    try:
        g = getattr(message, "guild", None)
        me = getattr(g, "me", None) if g is not None else None
        if me is not None:
            dn = getattr(me, "display_name", None)
            nm = getattr(me, "name", None)
            if dn:
                names.append(str(dn))
            if nm:
                names.append(str(nm))
    except Exception:
        pass
    out: list[str] = []
    seen = set()
    for n in names:
        nn = (n or "").strip()
        if not nn:
            continue
        key = nn.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(nn)
    return out

def _message_contains_callie_name(content: str, callie_names: Optional[List[str]] | None = None) -> bool:
    callie_names = callie_names or global_config.build_callie_names()
    lowered = (content or "").lower()
    for nm in callie_names or []:
        n = (nm or "").strip().lower()
        if not n:
            continue
        if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", lowered):
            return True
    return False

async def is_message_invoked(
    message: discord.Message,
    *,
    bot_user: Optional[discord.ClientUser] = None,
    bot_user_id: Optional[int] = None,
    bot_names: Optional[List[str]] = None,
) -> bool:
    """
    Unified invocation detection used by BOTH:
      - access gate (reply-only / passive channels)
      - ambient suppression override

    Invocation sources:
      - explicit @mention of the bot
      - reply-to a bot-authored message (resolved OR fetched)
      - presence of any Callie nickname anywhere in the message text (e.g. "Callie", "Calliope")
    """
    bid = int(bot_user_id or 0)
    if bid <= 0:
        bid = int(getattr(bot_user, "id", 0) or 0)
    if bid <= 0:
        return False

    # 1) @mention
    try:
        for u in getattr(message, "mentions", []) or []:
            if u and int(getattr(u, "id", 0) or 0) == bid:
                return True
    except Exception:
        pass

    # 2a) Reply-to Callie - resolved message
    # bid should generally always be valid here
    if message.reference and isinstance(message.reference.resolved, discord.Message):
        if message.reference.resolved.author.id == bid:
            return True
    if bot_user in message.mentions:
        return True
    # 2b) Fallback: try fetching referenced message if not resolved
    try:
        ref = getattr(message, "reference", None)
        if ref is not None:

            resolved = getattr(ref, "resolved", None)
            if isinstance(resolved, discord.Message):
                a = getattr(resolved, "author", None)
                if a is not None and int(getattr(a, "id", 0) or 0) == bid:
                    return True

            ref_msg_id = getattr(ref, "message_id", None)
            if ref_msg_id is not None:
                try:
                    mid = int(ref_msg_id)
                except Exception:
                    mid = None
                if mid:
                    fetched = None
                    # try current channel first
                    try:
                        fetched = await message.channel.fetch_message(mid)
                    except Exception as e:
                        log.exception("is_message_invoked: exception fetching referenced message in channel %s: %s", message.channel.id, e)
                        fetched = None
                    # thread fallback: try the parent channel too
                    if fetched is None:
                        parent = getattr(message.channel, "parent", None)
                        if parent is not None:
                            try:
                                fetched = await parent.fetch_message(mid)
                            except Exception as e:
                                log.exception("is_message_invoked: exception fetching referenced message in parent channel %s: %s", parent.id, e)
                                fetched = None
                    if fetched is not None:
                        a = getattr(fetched, "author", None)
                        if a is not None and int(getattr(a, "id", 0) or 0) == bid:
                            return True
                else:
                    log.warning("is_message_invoked: ref_msg_id could not be converted to int: %s", ref_msg_id)
            else:
                log.warning("is_message_invoked: ref = message.reference.message_id is None")
        else:
            log.warning("is_message_invoked: ref = message.reference is None")
    except Exception as e:
        log.exception("is_message_invoked: exception fetching referenced message: %s", e)

    # 3) Name/nickname anywhere in content
    names = bot_names or _build_callie_names_from_message(message) or _default_callie_names_from_bot_user(bot_user)
    try:
        if _message_contains_callie_name(getattr(message, "content", "") or "", names):
            return True
    except Exception as e:
        log.warning("is_message_invoked: exception checking message content for bot names: %s", e)

    return False

#def is_invocation(message: discord.Message, bot_user: discord.ClientUser) -> bool:
#    if message.reference and isinstance(message.reference.resolved, discord.Message):
#        if message.reference.resolved.author.id == bot_user.id:
#            return True
#    if bot_user in message.mentions:
#        return True
#    return False

async def is_pseudo_reply_by_name_prefix(message: discord.Message, *, bot_user_id: int) -> bool:
    """
    Heuristic for ambient mode: treat messages that start with a user's name (e.g. "@Alara, ...") as a reply to that user,
    even if Discord did not set message.reference.

    Suppression rule: if Callie is explicitly mentioned anywhere in the message, do NOT treat it as a pseudo-reply.
    """
    try:
        content = (getattr(message, "content", "") or "").strip()
        if not content:
            return False

        # If Callie is explicitly mentioned anywhere, do not suppress.
        try:
            if any(int(u.id) == int(bot_user_id) for u in getattr(message, "mentions", []) or []):
                return False
        except Exception:
            pass

        # If the message begins with a direct user mention (e.g. "<@123...>"), treat it as a pseudo-reply to that user
        # (unless it's mentioning Callie herself, handled above).
        try:
            first_tok = content.split(None, 1)[0]
            mm = re.match(r"^<@!?(\d+)>$", first_tok)
            if mm:
                mid = int(mm.group(1))
                if mid != int(bot_user_id):
                    return True
        except Exception:
            pass

        # Extract first token and strip common punctuation (commas/colons/etc.)
        first = content.split(None, 1)[0]
        first_clean = re.sub(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$", "", first)
        if not first_clean:
            return False

        g = getattr(message, "guild", None)
        if g is None:
            return False

        # If the first token is Callie herself, don't suppress.
        try:
            me = getattr(g, "me", None)
            bot_names = set()
            if me is not None:
                if getattr(me, "display_name", None):
                    bot_names.add(str(me.display_name).lower())
                if getattr(me, "name", None):
                    bot_names.add(str(me.name).lower())
            if first_clean.lower() in bot_names:
                return False
        except Exception:
            pass

        # Try to resolve a member by name/display_name.
        target = None
        tl = first_clean.lower()

        # Avoid O(n) scans on huge guilds.
        member_count = getattr(g, "member_count", None)
        if member_count is None or int(member_count) <= 2000:
            members = getattr(g, "members", None) or []
            for m in members:
                try:
                    if getattr(m, "display_name", "").lower() == tl or getattr(m, "name", "").lower() == tl:
                        target = m
                        break
                except Exception:
                    continue
        else:
            try:
                target = g.get_member_named(first_clean)
            except Exception:
                target = None

        if target is None:
            return False

        # Only treat as "reply to other user" if it's not the author and not Callie.
        if int(getattr(target, "id", 0)) in (int(getattr(message.author, "id", 0)), int(bot_user_id)):
            return False

        return True
    except Exception:
        return False

def is_pseudo_reply_by_name_prefix_by_names(
    message: discord.Message,
    *,
    callie_names: list[str],
) -> bool:
    """
    Return True if the message appears to address Callie by name at the start,
    e.g. 'Callie, ...', 'Callie: ...', 'Hey Callie ...'
    """
    if not callie_names or len(callie_names) == 0:
        callie_names = global_config.build_callie_names()

    content = (message.content or "").lstrip()
    if not content:
        return False

    lowered = content.lower()

    for name in callie_names:
        n = name.lower()

        # Exact-name prefix
        if lowered.startswith(n):
            return True

        # Common separators
        for sep in (",", ":", "-", "—"):
            if lowered.startswith(f"{n}{sep}"):
                return True

        # Casual speech: "hey callie", "ok callie"
        if lowered.startswith(f"hey {n}") or lowered.startswith(f"ok {n}"):
            return True

    return False

async def should_suppress_ambient_reply(
    message: discord.Message,
    *,
    bot_user: Optional[discord.ClientUser],
    suppress_enabled: bool,
    allow_name_prefix: bool = False,
    bot_names: Optional[List[str]] = None,
) -> bool:
    """
    Returns True if we should suppress an ambient (non-invoked) reply.

    Suppress when:
      - The message is a reply to another user (not Callie)
      - The message *appears* to be a reply to another user via:
          • leading @user mention
          • name-prefix heuristic

    Do NOT suppress when:
      - The message replies to Callie
      - The message explicitly mentions Callie anywhere
      - Reference resolution fails (fail open)
    """
    log.info(
        "Ambient check: suppress=%s reply=%s mention=%s prefix=%s content='%s'",
        suppress_enabled,
        bool(message.reference),
        bot_user in message.mentions,
        allow_name_prefix,
        message.content[:80],
    )

    if not suppress_enabled or bot_user is None:
        return False

    content = message.content or ""

    if not bot_names or len(bot_names) == 0:
        bot_names = global_config.build_callie_names() or _default_callie_names_from_bot_user(bot_user)
        log.debug("should_suppress_ambient_reply: bot_names=%s", bot_names)

    # Unified invocation detection: mention, reply-to, or name/nickname anywhere.
    # If invoked, we must NOT suppress.
    #names = bot_names or _build_callie_names_from_message(message) or _default_callie_names_from_bot_user(bot_user)
    try:
        if await is_message_invoked(message, bot_user=bot_user, bot_user_id=int(getattr(bot_user, 'id', 0) or 0), bot_names=bot_names):
            return False
    except Exception:
        pass

    # 0) If the user says one of Callie's names anywhere, treat it as an invocation.
    # This must override ambient suppression so "Callie ..." works even without an @mention.
    if allow_name_prefix:
        lowered = content.lower()
        if not bot_names:
            log.warning("should_suppress_ambient_reply: bot_names is None; cannot apply name search heuristic")
        try:
            # If the message *starts* with Callie's name ("Callie, ..."), that's an invocation,
            # not a reason to suppress ambient replies.
            if is_pseudo_reply_by_name_prefix_by_names(message, callie_names=bot_names or []):
                return False
            # Now search the whole message for any occurrence of Callie's name.
            for nm in (bot_names or []):
                n = (nm or "").strip().lower()
                if not n:
                    continue
                # Rough "whole token" match so we don't trigger on substrings.
                # Example: matches "callie" in "hey callie" but not in "recallie".
                if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", lowered):
                    return False
        except Exception:
            pass

    # 1) Explicit mention of Callie anywhere → always respond
    try:
        if f"<@{bot_user.id}>" in content or f"<@!{bot_user.id}>" in content:
            return False
    except Exception:
        pass

    # 2) True Discord reply logic
    ref = getattr(message, "reference", None)
    if ref is not None:
        # Prefer resolved reference (no API call)
        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved.author.id != bot_user.id

        # Fallback: fetch referenced message
        ref_msg_id = getattr(ref, "message_id", None)
        if ref_msg_id is not None:
            try:
                fetched = await message.channel.fetch_message(ref_msg_id)
                return fetched.author.id != bot_user.id
            except Exception:
                # Cannot determine → fail open
                return False

    # 3) Leading @mention (pseudo-reply)
    try:
        stripped = content.lstrip()
        if stripped.startswith("<@"):
            # If it's not Callie, suppress
            if not (
                stripped.startswith(f"<@{bot_user.id}>")
                or stripped.startswith(f"<@!{bot_user.id}>")
            ):
                return True
    except Exception:
        pass

    # 5) Name-prefix heuristic (e.g. "Alara: ...")
    #try:
    #    if not bot_user:
    #        log.warning("should_suppress_ambient_reply: bot_user is None; cannot apply name-prefix heuristic")
    #    else:
    #        if is_pseudo_reply_by_name_prefix_by_names(message, callie_names=bot_names or []):
    #            return True
    #except Exception:
    #    pass
    return False

async def send_with_retry(
    send_coro_factory: Callable[[], Awaitable[discord.Message]],
    fallback_send_coro_factory: Optional[Callable[[], Awaitable[discord.Message]]] = None,
    *,
    trace_id: int,
    part_idx: int,
    total_parts: int,
    chars: int,
    cooldown_seconds: float,
    max_retries: int,
    retry_base_seconds: float,
    retry_max_seconds: float,
    retry_jitter_seconds: float,
) -> Optional[discord.Message]:
    # send_coro_factory must return a *fresh awaitable/coroutine* each attempt.
    # We retry the exact same payload; caller controls the content via closure.
    for attempt in range(1, max_retries + 1):
        try:
            log.info(
                f"TX try trace={trace_id} part={part_idx}/{total_parts} "
                f"attempt={attempt}/{max_retries} chars={chars}"
            )

            sent = await send_coro_factory()

            log.info(
                f"TX ok  trace={trace_id} part={part_idx}/{total_parts} "
                f"sent_msg_id={sent.id} chars={chars}"
            )

            if cooldown_seconds > 0:
                await asyncio.sleep(cooldown_seconds)

            return sent

        except asyncio.CancelledError:
            # If the bot is shutting down / task cancelled, make it visible.
            log.warning(
                f"TX cancelled trace={trace_id} part={part_idx}/{total_parts} "
                f"attempt={attempt}/{max_retries}"
            )
            raise

        except discord.HTTPException as e:
            status = getattr(e, "status", None)
            code = getattr(e, "code", None)

            # Try to extract retry_after if present (varies by discord.py version)
            retry_after = getattr(e, "retry_after", None)

            # If Discord rejects the message_reference (Unknown message), immediately fall back
            # to sending without a reply reference so we don't lose the content.
            try:
                txt = getattr(e, "text", None) or ""
                err_s = str(e)
                unknown_ref = (
                    status == 400
                    and code == 50035
                    and ("Unknown message" in err_s or "Unknown message" in str(txt))
                )
                if unknown_ref and fallback_send_coro_factory is not None:
                    log.warning(
                        f"TX reference invalid trace={trace_id} part={part_idx}/{total_parts} "
                        f"attempt={attempt}/{max_retries} -> retry without message_reference"
                    )
                    send_coro_factory = fallback_send_coro_factory
                    fallback_send_coro_factory = None  # only fall back once
                    # immediately retry next loop iteration
                    continue
            except Exception:
                pass


            # Sometimes e.text includes JSON with retry_after for 429s
            if retry_after is None and status == 429:
                try:
                    txt = getattr(e, "text", None)
                    if isinstance(txt, str) and txt.strip().startswith("{"):
                        data = json.loads(txt)
                        retry_after = float(data.get("retry_after", 0))
                except Exception:
                    pass

            # Fallback exponential backoff + jitter
            if not retry_after or retry_after <= 0:
                backoff = retry_base_seconds * (2 ** (attempt - 1))
                retry_after = min(retry_max_seconds, backoff)
                retry_after += random.random() * retry_jitter_seconds

            log.warning(
                f"TX http trace={trace_id} part={part_idx}/{total_parts} "
                f"attempt={attempt}/{max_retries} status={status} code={code} "
                f"wait={retry_after:.2f}s err={e}"
            )

            # If we've exhausted retries, stop.
            if attempt >= max_retries:
                log.error(
                    f"TX giveup trace={trace_id} part={part_idx}/{total_parts} "
                    f"status={status} code={code} after={attempt} attempts"
                )
                log.debug(traceback.format_exc())
                return None

            await asyncio.sleep(float(retry_after))
            continue

        except (aiohttp.ClientConnectorError, socket.gaierror, TimeoutError, OSError) as e:
            outage = classify_discord_exception(e)
            backoff = retry_base_seconds * (2 ** (attempt - 1))
            retry_after = min(retry_max_seconds, backoff) + (random.random() * retry_jitter_seconds)
            detail = format_admin_outage(outage, context="send") if outage else f"Discord send network failure: {type(e).__name__}"
            log.warning(
                f"TX network trace={trace_id} part={part_idx}/{total_parts} "
                f"attempt={attempt}/{max_retries} wait={retry_after:.2f}s {detail}"
            )
            if attempt >= max_retries:
                log.error(
                    f"TX giveup trace={trace_id} part={part_idx}/{total_parts} "
                    f"network={type(e).__name__} after={attempt} attempts"
                )
                log.debug(traceback.format_exc())
                return None
            await asyncio.sleep(float(retry_after))
            continue

        except Exception as e:
            log.error(
                f"TX fatal trace={trace_id} part={part_idx}/{total_parts} "
                f"attempt={attempt}/{max_retries} err={type(e).__name__}: {e}"
            )
            log.debug(traceback.format_exc())
            return None

    return None

def roles_meta(member: Optional[discord.Member]) -> str:

    if member is None:
        return "roles=[]"
    items: List[str] = []
    for r in getattr(member, "roles", []):
        try:
            if r.is_default():  # @everyone
                continue
        except Exception:
            pass
        items.append(f"{r.name}({r.id})")
    return "roles=[" + ", ".join(items) + "]"

def identity_meta(message: discord.Message) -> str:
    author = message.author
    guild_id = getattr(getattr(message, "guild", None), "id", None)
    channel_id = getattr(message.channel, "id", None)

    user_id = getattr(author, "id", None)
    user_handle = getattr(author, "name", str(author))
    user_display = getattr(author, "display_name", user_handle)
    is_bot = getattr(author, "bot", False)
    mention = getattr(author, "mention", f"<@{user_id}>")

    lines = [
        f"guild_id={guild_id}",
        f"channel_id={channel_id}",
        f"message_id={message.id}",
        f"user_id={user_id}",
        f"user_handle={user_handle}",
        f"user_display={user_display}",
        f"user_mention={mention}",
        f"is_bot={is_bot}",
    ]
    return "\n".join(lines)

# def has_allowed_role(member: discord.Member) -> bool:
#     if not ALLOWED_ROLE_IDS:
#         return True
#     return any(r.id in ALLOWED_ROLE_IDS for r in member.roles)
#
def is_admin(member: Optional[discord.Member], admin_role_ids: List[int]) -> bool:
    # If no admin roles configured, treat as "no extra gate".
    if not admin_role_ids:
        log.warning("is_admin: no admin_role_ids configured; treating all users as admins")
        return True
    if member is None:
        return False
    return any((r.id in admin_role_ids) for r in getattr(member, "roles", []))

# --- Webhook/PluralKit proxy resolution helpers ---
_DISCORD_ID_MENTION_RE = re.compile(r"<@!?(\d{17,20})>")
_DISCORD_ID_BARE_RE = re.compile(r"\b(\d{17,20})\b")

def _extract_user_ids_from_message_for_proxy(message: discord.Message) -> List[int]:
    """Try to recover the underlying user id from PluralKit-style webhook proxy messages."""
    ids: set[int] = set()

    parts: List[str] = []
    if getattr(message, "content", None):
        parts.append(str(message.content))

    for e in getattr(message, "embeds", []) or []:
        if getattr(e, "title", None):
            parts.append(str(e.title))
        if getattr(e, "description", None):
            parts.append(str(e.description))
        for f in getattr(e, "fields", []) or []:
            if getattr(f, "name", None):
                parts.append(str(f.name))
            if getattr(f, "value", None):
                parts.append(str(f.value))
        footer = getattr(e, "footer", None)
        if footer and getattr(footer, "text", None):
            parts.append(str(footer.text))

    blob = "\n".join(parts)

    for m in _DISCORD_ID_MENTION_RE.finditer(blob):
        try:
            ids.add(int(m.group(1)))
        except Exception:
            pass
    for m in _DISCORD_ID_BARE_RE.finditer(blob):
        try:
            ids.add(int(m.group(1)))
        except Exception:
            pass

    return list(ids)

async def send_reply(
    message: discord.Message,
    reply_text: str,
    *,
    pk_proxy_name: Optional[str] = None,
    view: Optional[discord.ui.View] = None,
) -> discord.Message:
    """Send a Discord reply without pinging or adding redundant speaker prefixes."""
    if pk_proxy_name:
        log.debug("send_reply ignored deprecated pk_proxy_name prefix for msg_id=%s", message.id)
    return await message.reply(reply_text, mention_author=False, view=view)

async def resolve_member_for_gate(message: discord.Message, member: Optional[discord.Member]):
    """
    Return (member, meta, pk_info) for gating and later annotation.
    """
    if getattr(message, "webhook_id", None) is None:
        return member, "not_webhook", None
    # 1) Try PluralKit API
    pk_info = await _pk.resolve(message)
    if pk_info:
        # Set return_member to either member or None, depending on what you want as fallback
        # Callie Prime says to use None to prevent accidental access grants downstream
        return_member = None # member
        # We still acknowledge the passed-in member as fallback
        # Even if pk_info is present, we may not be able to resolve the guild Member.
        if message.guild:
            m = message.guild.get_member(pk_info.sender_id)
            if m is None:
                try:
                    m = await message.guild.fetch_member(pk_info.sender_id)
                except Exception as e:
                    # Keep pk_info even if member fetch fails
                    return return_member, f"proxied_pk_unresolved sender={pk_info.sender_id} err={type(e).__name__}", pk_info        
                    #m = None
            if m is not None:
                return m, f"proxied_pk sender={pk_info.sender_id}", pk_info
            else:
                # used for fallback when m is None
                mid = member.id if member is not None else "None"
                return return_member, f"proxied_pk_unresolved sender={mid} no_sender", pk_info
        return return_member, f"proxied_pk_unresolved sender={pk_info.sender_id} no_guild", pk_info

    # 2) Fallback to your existing heuristic extractor
    # only when pk_info is None
    m2, meta2 = await resolve_member_for_gate_heuristic(message)
    if m2 is not None and isinstance(meta2, str) and meta2.startswith("proxied"):
        return m2, meta2, None
    # 3) Unresolved webhook
    return None, f"webhook_unresolved webhook_id={getattr(message,'webhook_id',None)}", None

async def resolve_member_for_gate_heuristic(message: discord.Message, member: Optional[discord.Member] | None = None) -> Tuple[Optional[discord.Member], str]:
    """Return (member, meta) for gating. If webhook/proxy, try to resolve the underlying user."""
    if member is not None:
        return member, "direct"
    guild = getattr(message, "guild", None)
    if guild is None:
        return None, "no_guild"
    webhook_id = getattr(message, "webhook_id", None)
    if not webhook_id:
        return None, "no_member"
    # Webhook/proxy message. Try to resolve as PluralKit proxy; if we can't, treat as untrusted webhook.
    candidates = _extract_user_ids_from_message_for_proxy(message)
    for uid in candidates:
        m = guild.get_member(uid)
        if m is None:
            try:
                m = await guild.fetch_member(uid)
            except Exception:
                m = None
        if m is not None:
            return m, f"proxied uid={uid} webhook_id={webhook_id}"
    return None, f"webhook_unresolved webhook_id={webhook_id} candidates={candidates}"

def compute_storage_identity(message: "discord.Message", pk_info):
    # default: raw Discord author
    author_id = message.author.id
    author_name = getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Unknown"
    # PK proxied webhook: store underlying sender for continuity, keep proxy name for voice
    if pk_info is not None:
        author_id = pk_info.sender_id
        # The visible speaker identity is the webhook/proxy display name
        author_name = author_name
    return author_id, author_name

# # def passes_access_gate(channel_id: int, member: Optional[discord.Member]) -> bool:
# #     # If role gating is disabled, allow.
# #     if not REQUIRE_CALLIE_ROLE:
# #         return True
#
#     has_role = True
#     if ALLOWED_ROLE_IDS:
#         has_role = (member is not None) and has_allowed_role(member)
#
#     if ROLE_CHANNELS_ACCESS_MODE == "AND":
#         return (channel_id in ALLOWED_CHANNEL_IDS) and has_role
#     # OR mode
#     return (channel_id in ALLOWED_CHANNEL_IDS) or has_role

def interaction_member(interaction: discord.Interaction) -> Optional[discord.Member]:
    return interaction.user if isinstance(interaction.user, discord.Member) else None

def _require_admin(interaction: discord.Interaction, admin_role_ids: List[int]) -> Optional[discord.Member]:
    mem = interaction_member(interaction)
    if not is_admin(mem, admin_role_ids):
        return None
    return mem

def _has_any_role(member: Optional[discord.Member], role_ids: List[int]) -> bool:
    if member is None:
        return False
    try:
        mids = set([int(r.id) for r in getattr(member, "roles", [])])
        return any(int(rid) in mids for rid in role_ids)
    except Exception:
        return False

async def is_reply_to_other_user(message: discord.Message, *, bot_user_id: int) -> bool:
    """Return True if message is an explicit reply to someone other than Callie.
    Best-effort: if we cannot resolve the referenced message, treat it as 'other user' to avoid ambient drive-bys.
    """
    try:
        ref = getattr(message, "reference", None)
        if ref is None:
            return False
        ref_id = getattr(ref, "message_id", None)
        if not ref_id:
            return False

        resolved = getattr(ref, "resolved", None)
        ref_msg = resolved if isinstance(resolved, discord.Message) else None
        if ref_msg is None:
            try:
                ref_msg = await message.channel.fetch_message(int(ref_id))
            except Exception:
                ref_msg = None

        if ref_msg is None or getattr(ref_msg, "author", None) is None:
            return True  # unknown target -> treat as "other user"
        return int(ref_msg.author.id) != int(bot_user_id)
    except Exception:
        return True
