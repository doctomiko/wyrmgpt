
import asyncio
import base64
from collections import deque
import json
import os
import re
import socket
import threading
import time
import traceback
from typing import Any, Dict, List, Optional, Set, Tuple, cast
import inspect
import aiohttp
import discord
from discord import app_commands
from docx import Document
import httpx
from callie_logging import log, setup_logging
from discord_helpers import apply_enrich_policy_to_transcript, chunk_for_discord, get_effective_channel_id, identity_meta, resolve_member_for_gate, roles_meta, send_reply, send_with_retry, should_suppress_ambient_reply
from global_config import GlobalConfig
from callie_store import Store
from guild_config import GuildConfig
from config_manager import ConfigManager
from helpers import _norm_content, canonical_json, now_epoch
from openai_helpers import build_trimmed_transcript, est_tokens, openai_respond, openai_upload_file, sanitize_content, summarize_messages_block
from outage_helpers import classify_discord_exception, classify_openai_exception, format_admin_outage
from provider_backends import resolve_oauth_tokens, validate_provider_config
from pk_helper import PKInfo, build_pk_context_block, format_pk_proxy_note
from reply_cleanup import strip_obvious_reply_prefix
from word_helpers import extract_docx_markdown, extract_text_bytes
from access_control import AccessDecision, compute_access_decision #, ChannelReplyMode

# Tuneables (env/config these if you want)
PK_PREPROXY_DELAY_SECONDS = 1.2          # wait for PK webhook repost
PK_ACTIVE_TTL_SECONDS = 600              # how long a channel stays "pk-active"
PK_REPOST_SCAN_LIMIT = 50                # how many recent messages to scan
PK_REPOST_TIME_WINDOW_SECONDS = 6        # how close in time counts as "same event"

log, _log_settings = setup_logging("callie_bot")

# TODO move this to a variable or part of class later
# Initialize the global Store, GlobalConfig, and ConfigManager
global_config: GlobalConfig = GlobalConfig()

# BEGIN SECTION ------------ HOTKEYS MENU ---------------
# Module level vars are OK in this section.

# --------------------
# Console hotkeys (Windows-friendly)
# Ctrl+Q => graceful shutdown
# Ctrl+P => admin console menu (pauses message processing while active)
# Note: Ctrl+M is Enter in most terminals, so it's not usable as a distinct hotkey.
# --------------------
PAUSE_PROCESSING = False
RECENT_AUTHORS = deque(maxlen=10)

# populate these after you create the bot instance and have a running loop
BOT_INSTANCE: Optional[discord.Client] = None
MAIN_LOOP: asyncio.AbstractEventLoop | None = None


def _fmt_diag_int(value: Any) -> str:
    try:
        if value is None:
            return "?"
        return f"{int(value):,}"
    except Exception:
        return "?"


def _fmt_diag_money(value: Any) -> str:
    try:
        if value is None:
            return "?"
        return f"${float(value):.6f}"
    except Exception:
        return "?"


def _fmt_diag_pct(value: Any) -> str:
    try:
        if value is None:
            return "?"
        return f"{float(value):.1f}%"
    except Exception:
        return "?"


def _reply_diagnostics_brief(diagnostics: Dict[str, Any]) -> str:
    model = diagnostics.get("model") or "?"
    backend = diagnostics.get("backend") or diagnostics.get("provider") or "?"
    auth_mode = diagnostics.get("auth_mode") or "?"
    total = _fmt_diag_int(diagnostics.get("total_tokens"))
    cost = _fmt_diag_money(diagnostics.get("estimated_cost_usd"))
    return f"model={model} · backend={backend}/{auth_mode} · tokens={total} · est={cost}"


def _reply_diagnostics_details(diagnostics: Dict[str, Any]) -> str:
    lines = [
        "Reply diagnostics",
        f"model: {diagnostics.get('model') or '?'}",
        f"backend: {diagnostics.get('backend') or diagnostics.get('provider') or '?'}",
        f"auth_mode: {diagnostics.get('auth_mode') or '?'}",
        f"response_id: {diagnostics.get('response_id') or '?'}",
        f"latency_ms: {_fmt_diag_int(diagnostics.get('dt_ms'))}",
        f"input_tokens: {_fmt_diag_int(diagnostics.get('input_tokens'))}",
        f"output_tokens: {_fmt_diag_int(diagnostics.get('output_tokens'))}",
        f"total_tokens: {_fmt_diag_int(diagnostics.get('total_tokens'))}",
        f"estimated_cost: {_fmt_diag_money(diagnostics.get('estimated_cost_usd'))}",
        f"budget_used_pct: {_fmt_diag_pct(diagnostics.get('budget_used_pct'))}",
        f"pricing_source: {diagnostics.get('pricing_source') or '?'}",
        f"attachment_parts: image={diagnostics.get('image_parts', 0)} file={diagnostics.get('file_parts', 0)} text={diagnostics.get('text_parts', 0)}",
    ]
    if diagnostics.get("estimated_input_tokens") is not None:
        lines.append(f"estimated_prompt_tokens: {_fmt_diag_int(diagnostics.get('estimated_input_tokens'))}")
    return "\n".join(lines)[:1900]


class ReplyDiagnosticsView(discord.ui.View):
    def __init__(self, diagnostics: Dict[str, Any]):
        super().__init__(timeout=24 * 60 * 60)
        self._details = _reply_diagnostics_details(diagnostics)

    @discord.ui.button(label="Details", style=discord.ButtonStyle.secondary)
    async def details_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(self._details, ephemeral=True)

# It is not great that this gets called directly from inside the message processing function.
# We may want to refactor this later to use an event or similar.
def _record_author(message: discord.Message) -> None:
    """
    helper to track recent authors for console hotkey menu
    """
    try:
        name = getattr(message.author, "name", str(message.author))
        RECENT_AUTHORS.appendleft(name)
    except Exception:
        pass

def _request_shutdown() -> None:
    global BOT_INSTANCE, MAIN_LOOP
    if BOT_INSTANCE is None or MAIN_LOOP is None:
        raise SystemExit(0)
    try:
        fut = asyncio.run_coroutine_threadsafe(BOT_INSTANCE.close(), MAIN_LOOP)
        # Don't block forever; just kick it.
        try:
            fut.result(timeout=5)
        except Exception:
            pass
    except Exception:
        raise SystemExit(0)

def _console_menu(store: "Store") -> None:
    global PAUSE_PROCESSING
    PAUSE_PROCESSING = True
    try:
        print("\n=== Callie Console Menu ===")
        print("WARNING: While this menu is active, Discord messages will not be processed.")
        while True:
            print("\nOptions: [R]esume  [U]sers(last10)  [S]tats  [T]enants  [Q]uit")
            choice = input("> ").strip().lower()
            if choice in ("r", "resume", ""):
                return
            if choice in ("q", "quit", "exit"):
                _request_shutdown()
                return
            if choice in ("u", "users", "last", "last10"):
                if not RECENT_AUTHORS:
                    print("(no recent authors yet)")
                else:
                    print("Last authors:", ", ".join(list(RECENT_AUTHORS)[:10]))
                continue
            if choice in ("s", "stats"):
                try:
                    # High-level SQL view; uses global store schema
                    msg_stats = store.admin_message_stats_sync()
                    sum_stats = store.admin_summary_stats_sync()
                    print("Messages:", msg_stats)
                    print("Summaries:", sum_stats)
                except Exception as e:
                    print(f"(stats unavailable: {e})")
                continue
            if choice in ("t", "tenants"):
                try:
                    n = store.count_tenants_sync()
                    print(f"Tenants with any config rows: {n}")
                except Exception as e:
                    print(f"(tenants unavailable: {e})")
                continue
            print("Unknown choice.")
    finally:
        PAUSE_PROCESSING = False
        return

def _start_console_hotkeys(store: "Store") -> None:
    # Only works on Windows consoles; no-op elsewhere.
    try:
        import msvcrt  # type: ignore
    except Exception:
        return

    def _run():
        while True:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    # Ctrl+Q => 0x11
                    if ch == "\x11":
                        print("\n[Hotkey] Ctrl+Q pressed: shutting down.")
                        _request_shutdown()
                        return
                    # Ctrl+P => 0x10
                    if ch == "\x10":
                        _console_menu(store)
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.2)
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# END SECTION ------------ HOTKEYS MENU ---------------


class CallieBot(discord.Client):
    def __init__(self, store: Store):
        # TODO use a class and event model instead
        _start_console_hotkeys(store)

        intents = discord.Intents.default()
        intents.message_content = True # required to read message content in many servers
        intents.guilds = True
        intents.messages = True
        intents.members = True  # required to read roles of members, foolproof
        super().__init__(intents=intents)

        # Event handler for Ctrl+Q shutdown
        self._shutdown_requested = asyncio.Event()
        self._runner_backoff_seconds = 5

        # PK tracking state
        self._pk_active_channels: Dict[int, float] = {}  # channel_id -> last_seen_ts
        self._pk_suppressed_originals: Set[int] = set()   # message_ids we've decided to skip

        self.tree = app_commands.CommandTree(self)
        self.store = Store(global_config)
        self.config_mgr = ConfigManager(self.store, global_config)

    async def close(self) -> None:
        # Signal the runner loop to stop restarting us.
        try:
            self._shutdown_requested.set()
        except Exception:
            pass
        await super().close()

    async def setup_hook(self):
        # Hook the main look
        global BOT_INSTANCE, MAIN_LOOP
        if BOT_INSTANCE is None:
            BOT_INSTANCE = self
        try:
            MAIN_LOOP = asyncio.get_running_loop()
            log.info("on_ready: successfully got running loop in CallieBot.setup_hook.")
        except Exception:
            log.warning("on_ready: failed to get running loop in CallieBot.on_ready! Menu and key break may not work as intended.")

        # Sync commands to dev guild if set, else globally
        if (global_config.dev_guild_id or 0):
            guild = discord.Object(id=(global_config.dev_guild_id or 0))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        log.info(f"Discord ready user={self.user} user_id={getattr(self.user, 'id', None)}")
        # Startup banner uses global config only (no guild context in on_ready)
        log.info(f"Startup config: multi_tenant={global_config.multi_tenant} ")
        log.info(f"Default Open AI model: model={global_config.default_openai_model} ") # default_max_output_tokens={global_config.default_openai_max_output_tokens}
        log.info(f"SQL store: sqlite_path={global_config.sqlite_path}")
        log.info(f"Dev Guild ID: dev_guild_id={global_config.dev_guild_id}")
        discord_token_set = {'SET' if global_config.discord_token else 'MISSING'}
        log.info(f"Discord Bot Token: discord_token_set={discord_token_set}")

        #if not global_config.multi_tenant:
        #    gc = self.config_mgr.get_for_guild_id(global_config.primary_guild_id)

        # TODO in single-tenant mode, pre-load primary guild config for faster startup
        if global_config.dev_guild_id:
            log.info(f"Primary guild config load for dev_guild_id={global_config.dev_guild_id}")
            try:
                gc = self.config_mgr._get_for_guild_id(global_config.dev_guild_id)
                log.info(f"Primary guild config loaded for dev_guild_id={global_config.dev_guild_id}")
                await gc.log_explicit()
            except Exception as e:
                log.error(f"Primary guild config load failed for dev_guild_id={global_config.dev_guild_id} err={type(e).__name__}: {e}")

    async def run_main_loop(self, token: str) -> None:
        backoff = self._runner_backoff_seconds or 5
        while not self._shutdown_requested.is_set():
            try:
                log.info("Starting Discord client...")
                # Let our outer loop classify DNS/network failures instead of
                # letting discord.py emit noisy reconnect tracebacks.
                await self.start(token, reconnect=False)

                # If start() returns, we were closed/logged out.
                if self._shutdown_requested.is_set():
                    break

                # Unexpected clean exit (rare). Treat like a fault and restart gently.
                log.warning("Discord client exited unexpectedly; restarting in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

            except (aiohttp.ClientConnectorDNSError, socket.gaierror) as e:
                # DNS hiccup: back off harder, but honor shutdown.
                if self._shutdown_requested.is_set():
                    break
                outage = classify_discord_exception(e)
                detail = format_admin_outage(outage, context="connect") if outage else f"Discord connect failed (DNS): {type(e).__name__}"
                log.warning("%s. Retrying in %ss", detail, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

            except OSError as e:
                if self._shutdown_requested.is_set():
                    break
                outage = classify_discord_exception(e)
                detail = format_admin_outage(outage, context="connect") if outage else f"Discord connect failed (network/OS): {type(e).__name__}"
                log.warning("%s. Retrying in %ss", detail, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

            except Exception:
                if self._shutdown_requested.is_set():
                    break
                log.exception("Fatal error in Discord client loop; restarting in %ss", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

            finally:
                # If we're shutting down, close once and leave.
                if self._shutdown_requested.is_set():
                    try:
                        await super().close()
                    except Exception:
                        pass
                    break

    async def on_disconnect(self):
        log.warning("Discord disconnected (will attempt reconnect).")

    async def on_resumed(self):
        log.info("Discord session resumed.")

    async def is_allowed_channel(self, message: "discord.Message") -> Tuple[bool, GuildConfig]:
        gc = self.config_mgr.check_guild(message)
        assert gc
        try:
            allowed_result = gc.allowed_channel_ids()
            allowed = await allowed_result if inspect.isawaitable(allowed_result) else allowed_result
        except Exception:
            # If we can't determine allowed channels, default to deny.
            return False, gc
        return get_effective_channel_id(message, parent=True) in (allowed or []), gc

    async def _build_attachment_parts(
        self,
        message: discord.Message,
        cfg: "GuildConfig",
        *,
        should_process: bool,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Process Discord message attachments into model-ready extra parts.

        Returns:
          (extra_parts, user_visible_notes)

        - extra_parts: list of input_* parts to append to the model request (e.g., input_file/input_image/input_text).
        - user_visible_notes: optional short notes you may want to include in your response/logging.
        """

        extra_parts: List[Dict[str, Any]] = []
        user_notes: List[str] = []

        if not should_process or not message.attachments:
            return extra_parts, user_notes

        blocked: List[str] = []
        shielded: List[str] = []
        attachment_notes: List[str] = []

        # Pull config once (avoid repeated awaits in loop)
        blocked_exts = await cfg.blocked_attachment_exts()
        allowed_exts = await cfg.allowed_attachment_exts()
        max_api_bytes = await cfg.max_files_api_bytes()
        max_attachment_bytes = (await cfg.max_attachment_mb()) * 1024 * 1024
        api_key = await cfg.openai_api_key()

        for att in message.attachments:
            fname = att.filename or "(unnamed)"
            ext = os.path.splitext(fname)[1].lower()
            mime = (att.content_type or "").lower()

            # Block dangerous extensions
            if ext in (blocked_exts or []):
                blocked.append(fname)
                continue

            # If allowlist is configured, enforce it
            if allowed_exts:
                # If file has no extension, treat as unsupported for safety
                if not ext or ext not in allowed_exts:
                    shielded.append(f"{fname} (unsupported type: {ext or 'no extension'})")
                    continue

            # Check size limits
            if att.size is not None and max_api_bytes and att.size > max_api_bytes:
                shielded.append(
                    f"{fname} (too large: {att.size} bytes; Files API cap {max_api_bytes} bytes)"
                )
                continue

            # Download bytes from Discord CDN
            try:
                data = await self._download_discord_attachment(att)
            except Exception as e:
                shielded.append(f"{fname} (download failed: {type(e).__name__})")
                continue

            # Try inline attach for small images / PDFs
            is_pdf = ext == ".pdf" or mime == "application/pdf"
            is_image = mime.startswith("image/") or ext in {
                ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"
            }
            is_word = ext == ".docx"
            is_text = ext == ".txt" or ext == ".md" or ext == ".py" or ext == ".csv" or mime == "text/plain"

            if is_image and len(data) <= max_attachment_bytes:
                # Best-effort MIME for data URL
                if not mime.startswith("image/"):
                    if ext == ".png":
                        mime = "image/png"
                    elif ext in {".jpg", ".jpeg"}:
                        mime = "image/jpeg"
                    else:
                        mime = "image/*"
                b64 = base64.b64encode(data).decode("utf-8")
                extra_parts.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}"})
                attachment_notes.append(f"image attached inline: {fname} ({len(data)} bytes)")
                continue

            if is_pdf and len(data) <= max_attachment_bytes:
                b64 = base64.b64encode(data).decode("utf-8")
                extra_parts.append(
                    {"type": "input_file", "filename": fname, "file_data": f"data:application/pdf;base64,{b64}"}
                )
                attachment_notes.append(f"PDF attached inline: {fname} ({len(data)} bytes)")
                continue

            # TODO: support TXT extraction similarly
            if is_text and len(data) <= global_config.text_inject_max_chars:
                try:
                    extracted = extract_text_bytes(data, global_config.text_inject_max_chars)[0]
                    extra_parts.append({
                        "type": "input_text",
                        "text": f"Attachment: {fname} (extracted text follows):\n" + extracted,
                    })
                    attachment_notes.append(f"Text extracted: {fname} ({len(data)} bytes)")
                    continue
                except Exception as e:
                    shielded.append(f"{fname} (Text extraction failed: {type(e).__name__})")
                    continue

            # DOCX: extract readable text and inject as input_text (preferred), rather than uploading a blob.
            if is_word:
                if Document is None:
                    shielded.append(f"{fname} (DOCX extraction unavailable: python-docx not installed)")
                    continue
                try:
                    extracted = extract_docx_markdown(data, global_config.text_inject_max_chars)
                    # Keep the model’s context sane: extracted already respects TEXT_INJECT_MAX_CHARS.
                    extra_parts.append({
                        "type": "input_text",
                        "text": f"Attachment: {fname} (extracted DOCX text follows):\n" + extracted,
                    })
                    attachment_notes.append(f"DOCX extracted: {fname} ({len(data)} bytes)")
                    continue
                except Exception as e:
                    shielded.append(f"{fname} (DOCX extraction failed: {type(e).__name__})")
                    continue

            # Otherwise: upload to OpenAI Files API (or your wrapper)
            try:
                file_id = await openai_upload_file(
                    data=data,
                    filename=fname,
                    purpose="user_data",
                    api_key=api_key,
                )
                if file_id and not file_id.startswith("Sorry,"):
                    extra_parts.append({"type": "input_file", "file_id": file_id})
                attachment_notes.append(f"file uploaded: {fname} (file_id={file_id})")
            except Exception as e:
                # Do NOT explode the whole message; just shield this attachment.
                shielded.append(f"{fname} (upload failed: {type(e).__name__})")

        # Summarize shielding/blocking for the model (and optionally user)
        if blocked:
            user_notes.append("Blocked attachments: " + ", ".join(blocked))
        if shielded:
            user_notes.append("Shielded attachments: " + "; ".join(shielded))

        # Add a connector note into model context so the model “knows” what happened
        if attachment_notes:
            extra_parts.append({"type": "input_text", "text": "Connector note: " + " | ".join(attachment_notes)})
        if user_notes:
            extra_parts.append(
                {"type": "input_text", "text": "Connector note (shielded/blocked): " + " | ".join(user_notes)}
            )

        image_parts = sum(1 for part in extra_parts if part.get("type") == "input_image")
        file_parts = sum(1 for part in extra_parts if part.get("type") == "input_file")
        text_parts = sum(1 for part in extra_parts if part.get("type") == "input_text")
        log.info(
            "Attachment processing msg_id=%s attachments=%s extra_parts=%s image_parts=%s file_parts=%s text_parts=%s blocked=%s shielded=%s",
            message.id,
            len(message.attachments),
            len(extra_parts),
            image_parts,
            file_parts,
            text_parts,
            len(blocked),
            len(shielded),
        )

        return extra_parts, user_notes

    async def _download_discord_attachment(self, att: discord.Attachment) -> bytes:
        """
        Download attachment bytes from Discord.
        Isolated so failures are contained and easy to test/memoize later.
        """
        # discord.Attachment has .url and .read(), but .read() sometimes depends on internal state.
        # CDN GET is straightforward and works reliably.
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
            r = await client.get(att.url)
            r.raise_for_status()
            return r.content

    async def _maybe_send_attachment_invocation_reminder(
        self,
        message: discord.Message,
        decision: AccessDecision,
        *,
        force: bool = False,
        source: str = "gate",
        reminder: Optional[str] = None,
    ) -> None:
        """
        If attachments were withheld only because this was not an invocation,
        tell the user how to get them inspected instead of silently dropping them.
        """
        if not getattr(message, "attachments", None):
            return
        if decision.is_invoked:
            return
        if not decision.record:
            return
        if not force and decision.can_speak and not decision.speak_suppressed:
            return

        log.info(
            "Attachment reminder: msg_id=%s attachments=%s source=%s mode=%s can_speak=%s speak_suppressed=%s reason=%s",
            message.id,
            len(message.attachments),
            source,
            decision.mode.value,
            decision.can_speak,
            decision.speak_suppressed,
            decision.reason,
        )
        if reminder is None:
            reminder = (
                "(Attachment note: I saw the upload, but I only inspect files/images when you mention me "
                "or reply to me directly. Please resend it with a mention if you want me to look at it.)"
            )
        try:
            await message.reply(reminder, mention_author=False)
        except Exception as e:
            log.warning("Attachment reminder send failed msg_id=%s err=%s", message.id, type(e).__name__)

    def _mark_pk_active(self, channel_id: int) -> None:
        self._pk_active_channels[channel_id] = time.time()

    def _is_pk_active(self, channel_id: int) -> bool:
        ts = self._pk_active_channels.get(channel_id)
        return bool(ts and (time.time() - ts) <= PK_ACTIVE_TTL_SECONDS)

    async def _maybe_defer_preproxy_message(self, message: discord.Message) -> bool:
        """
        Returns True if we deferred/ignored this message because it's likely a pre-proxy original
        that will be reposted via PK webhook.

        Strategy:
          - Only applies to non-webhook messages in channels that are PK-active recently.
          - Short delay, then look for a near-immediate webhook repost with matching content.
        """
        if message.webhook_id is not None:
            return False
        if message.guild is None:
            return False
        if not self._is_pk_active(message.channel.id):
            return False
        if message.id in self._pk_suppressed_originals:
            return True

        original_text = _norm_content(message.content)
        if not original_text:
            # If you want, you can still defer empties with attachments, but keep it simple.
            return False

        # Delay to let PK repost happen
        await asyncio.sleep(PK_PREPROXY_DELAY_SECONDS)

        # If the original was deleted, skip it (PK likely did its thing)
        try:
            await message.channel.fetch_message(message.id)
        except Exception:
            self._pk_suppressed_originals.add(message.id)
            return True

        # Look for a webhook repost very near in time with the same content
        try:
            async for m in message.channel.history(limit=PK_REPOST_SCAN_LIMIT, after=message.created_at):
                if m.webhook_id is None:
                    continue
                if abs((m.created_at - message.created_at).total_seconds()) > PK_REPOST_TIME_WINDOW_SECONDS:
                    continue
                if _norm_content(m.content) == original_text:
                    # Found the repost; skip original.
                    self._pk_suppressed_originals.add(message.id)
                    return True
        except Exception:
            # If history scan fails, fail open: process original
            return False

        # No repost detected: treat as normal user message
        return False

    async def record_incoming_message(self, message: discord.Message, decision: AccessDecision, pk_info: Optional[PKInfo] = None):
        # Always archive messages
        # Done after pk_info is populated
        try:
            # We may be able to get this from decision.effective_author now but just to be safe
            # Vivian - commented out because Callie said to do it
            #pk_aware_author_id, pk_aware_author_name = compute_storage_identity(message, pk_info)

            author_id = int(decision.effective_author.author_id)
            author_name = str(decision.effective_author.author_name or "").strip()

            if not author_name:
                # last-ditch fallback, should almost never happen once decision uses pk_info
                author_name = (
                    getattr(message.author, "display_name", None)
                    or getattr(message.author, "name", None)
                    or str(message.author)
                )

            created_ts = int(message.created_at.timestamp()) if getattr(message, "created_at", None) else now_epoch()
            clean_content = sanitize_content(message.content or "<No message content>")
            # Optional stopgap: if pk_info exists, prepend a compact tag.
            # This is ugly but useful until schema support exists.
            content_to_store = clean_content
            if pk_info is not None:
                content_to_store = f"[PK:{pk_info.system_name or '?'}::{pk_info.member_name or '?'} as {author_name}]\n{content_to_store}"
            await self.store.log_message(
                channel_id=int(message.channel.id), # note in some cases this is thread ID, and that's OK!
                discord_guild_id=message.guild.id if message.guild else 0,
                discord_message_id=int(message.id),
                author_id=author_id,
                author_name=author_name,
                content=content_to_store,
                created_at=created_ts,
                is_callie=False,
            )
            if _log_settings.log_sql_every_message:
                log.debug(f"SQL stored RX msg_id={message.id}")
        except Exception as e:
            log.error(f"SQL store RX failed msg_id={message.id} err={type(e).__name__}: {e}")

    async def record_outgoing_callie(self, sent_msg: discord.Message, cfg: GuildConfig):
        created_ts = int(sent_msg.created_at.timestamp()) if getattr(sent_msg, "created_at", None) else now_epoch()
        # Safely resolve bot identity: self.user may be None before the client is ready.
        if getattr(self, "user", None):
            author_id = int(getattr(self.user, "id", 0))
            author_name = str(getattr(self.user, "display_name", getattr(self.user, "name", "Callie")))
        else:
            author_id = 0
            author_name = await cfg.callie_name() or "Callie"
        clean_content = sanitize_content(sent_msg.content or "<No message content>")
        await self.store.log_message(
            channel_id=int(sent_msg.channel.id),
            discord_guild_id=sent_msg.guild.id if sent_msg.guild else 0,
            discord_message_id=int(sent_msg.id),
            author_id=author_id,
            author_name=author_name,
            content=clean_content,
            created_at=created_ts,
            is_callie=True,
        )

    async def check_message_guild(self, message: discord.Message) -> Tuple[bool, str, Optional[discord.Member]]:
        # This may need streamlining later.
        member = message.author if isinstance(message.author, discord.Member) else None
        try:
            member = message.guild.get_member(message.author.id) if message.guild else None
        except Exception:
            member = None
            pass
        # Ignore DMs (no guild context)
        if message.guild is None:
            return False, "DM message (no guild)", member
        # (optional) also ignore group DMs / weird channel types if needed
        # member = message.author if isinstance(message.author, discord.Member) else None
        # This was advised to be more reliable than the above
        if member is None and message.guild is not None:
            try:
                member = await message.guild.fetch_member(message.author.id)
            except Exception:
                log.debug("message.guild.get_member and message.guild.fetch_member both failed to return a result.")
                member = None
        if member is None:
            try:
                member = await message.guild.fetch_member(message.author.id)
            except Exception:
                member = None
        if message.guild is None:
            return False, "No guild context for member and guild.", member
        return True, "", member

    async def _prepare_transcript_with_summaries(
        self,
        message: discord.Message,
        cfg: "GuildConfig",
    ):
        """
        Extracted from on_message with NO behavior changes.
        Returns:
          (all_transcript, transcript, dropped_count, summary_ctx_note, memory_blob, transcript_budget, reserve, kept_tokens)
        """

        all_transcript = await self.store.recent_messages(message.channel.id, (await cfg.context_messages()))

        # --- Summary / context budget configuration
        summary_enabled = await cfg.summary_enabled()
        summary_trigger_dropped = await cfg.summary_trigger_dropped_min_messages()
        summary_batch_min = await cfg.summary_batch_min_messages()
        summary_batch_max = await cfg.summary_batch_max_messages()
        summary_batch_max_chars = await cfg.summary_batch_max_chars()
        summary_min_interval = await cfg.summary_min_interval_seconds()
        summary_target_max_tokens = await cfg.summary_target_max_tokens()
        summary_max_loops = await cfg.summary_max_loops()
        summary_ctx_note = ""
        memory_newest = await cfg.memory_newest()
        memory_oldest = await cfg.memory_oldest()
        memory_random = await cfg.memory_random()
        memory_blob = await self.store.get_memory_blob(
            newest=memory_newest,
            oldest=memory_oldest,
            random_mid=memory_random
        )

        # Reserve room for system prompt + memory + server_ctx + notices + output.
        reserve = est_tokens(await cfg.system_prompt()) + est_tokens(memory_blob) + (await cfg.summary_target_max_tokens()) + 400
        transcript_budget = max(1200, (await cfg.context_token_limit()) - reserve)

        def _filter_visible_for_prompt(rows: List[dict]) -> List[dict]:
            # Once a raw message is summarized, it should stop showing up as raw history.
            out: List[dict] = []
            for mm in rows:
                if mm.get("is_summary"):
                    out.append(mm)
                    continue
                if mm.get("is_summarized"):
                    continue
                out.append(mm)
            return out

        # 1) Compute what *would* be dropped (but do not drop yet).
        visible = _filter_visible_for_prompt(all_transcript)
        transcript, dropped_msgs, kept_tokens = build_trimmed_transcript(visible, transcript_budget)
        would_drop = len(dropped_msgs)

        if would_drop:
            log.info(f"CTX pre-summary: would_drop={would_drop} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        else:
            log.info(f"CTX pre-summary: ok kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")

        # 2) If enough would be dropped, summarize *those* messages first, then recompute.
        did_summary = False
        summarized_n = 0
        try:
            total_summarized = 0
            loops = max(1, int(summary_max_loops or 0))
            for loop_i in range(loops):
                if not (summary_enabled and would_drop >= summary_trigger_dropped):
                    break

                # On the first loop, respect SUMMARY_MIN_INTERVAL_SECONDS; on subsequent loops within this same
                # message, allow additional summaries so we can drain a backlog.
                if loop_i == 0:
                    last_sum = await self.store.most_recent_summary_time(int(message.channel.id))
                    if (now_epoch() - int(last_sum or 0)) < summary_min_interval:
                        break

                dropped_ids = [m.get("db_id") for m in dropped_msgs if m.get("db_id")]
                batch = await self.store.unsummarized_dropped_messages(
                    int(message.channel.id),
                    cast(List[int], dropped_ids),
                    summary_batch_max
                )
                if not batch:
                    break

                emergency = (would_drop >= (summary_trigger_dropped * 2))
                if len(batch) < summary_batch_min and not emergency:
                    break

                total_chars = 0
                trimmed_batch: List[dict] = []
                for mm in batch:
                    total_chars += len(mm.get("content", "") or "")
                    trimmed_batch.append(mm)
                    if total_chars >= summary_batch_max_chars:
                        break

                if not trimmed_batch:
                    break

                summary_text = await summarize_messages_block(
                    trimmed_batch,
                    await cfg.openai_model(),
                    summary_target_max_tokens,
                    api_key=await cfg.openai_api_key(),
                    cost_telemetry=await cfg.cost_telemetry_config(),
                )
                if not summary_text:
                    break

                start_db = int(trimmed_batch[0]["db_id"])
                end_db = int(trimmed_batch[-1]["db_id"])
                start_ts = int(trimmed_batch[0]["created_at"])
                end_ts = int(trimmed_batch[-1]["created_at"])
                participants = [m.get("author_name", "") for m in trimmed_batch]
                await self.store.insert_summary_and_mark(
                    int(message.channel.id),
                    summary_text,
                    start_db,
                    end_db,
                    start_ts,
                    end_ts,
                    participants,
                )

                did_summary = True
                total_summarized += len(trimmed_batch)

                # Recompute trim after those raws are hidden before the next loop.
                all_transcript = await self.store.recent_messages(message.channel.id, (await cfg.context_messages()))
                visible = _filter_visible_for_prompt(all_transcript)
                transcript, dropped_msgs, kept_tokens = build_trimmed_transcript(visible, transcript_budget)
                would_drop = len(dropped_msgs)

                log.info(
                    f"CTX post-summary[{loop_i+1}/{loops}]: summarized_batch={len(trimmed_batch)} "
                    f"would_drop_now={would_drop} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}"
                )

                if would_drop < summary_trigger_dropped:
                    break

            if did_summary:
                summarized_n = total_summarized
                summary_ctx_note = f"(Context note: I summarized {summarized_n} older message(s) into a stored summary to save context.)"
        except Exception as e:
            log.error(f"Summarization step failed (non-fatal): {e}")

        # Final drop-count after (possible) summarization.
        dropped_count = len(dropped_msgs)
        if dropped_count:
            log.info(f"CTX trim: dropped_msgs={dropped_count} kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        else:
            log.info(f"CTX ok: kept_msgs={len(transcript)} kept_est_tokens≈{kept_tokens} budget≈{transcript_budget}")
        return (
            all_transcript,
            transcript,
            dropped_count,
            summary_ctx_note,
            memory_blob,
            transcript_budget,
            reserve,
            kept_tokens,
        )
        # Test

    async def check_session_gate(
        self,
        decision,
    ) -> bool:
        """
        Returns True if we should continue speaking.
        """
        st = await self.store.get_session(decision.effective_channel_id)

        if st is not None and st.is_closed():
            log.info(
                "Gate: session explicitly inactive -> ignore "
                "(chan=%s)",
                decision.effective_channel_id,
            )
            return False
        return True

    async def touch_session(
        self,
        decision,
    ) -> None:
        st = await self.store.get_session(decision.effective_channel_id)
        if st is None:
            return
        st.touch(now_epoch())
        await self.store.set_session(st)

    async def quick_access_disallowed_decision(
        self,
        message: discord.Message,
    ) -> Tuple[bool, str, Optional[discord.Member]]:
        """
        Quick path for immediate disallow decisions.
        """
        # Preliminary guild check
        is_guild, reason, member = await self.check_message_guild(message)
        if not is_guild:
            return False, reason, member
        # Always ignore self - our sent messages were already recorded
        if message.author and self.user and int(message.author.id) == int(self.user.id):
            return False, "self message", member
        # Never respond to Discord system messages
        try:
            if message.is_system():
                log.info("Ignore: system message")
                return False, "system message", member
        except Exception:
            # discord.py compatibility
            if getattr(message, 'type', None) not in (None, discord.MessageType.default, discord.MessageType.reply):
                return False, "system message", member
        return True, "ok", member

    async def on_message(self, message: discord.Message):
        # This is a quick exist ramp and duplicates some work done later in compute_access_decision
        # but it's worth it to avoid wasted processing on obviously ignored messages.
        # We also grab the member here for later use.
        quick_disallowed_decision_result, reason, member = await self.quick_access_disallowed_decision(message)
        if not quick_disallowed_decision_result:
            log.info(f"on_message - Early Ignore: {reason}")
            return
        
        # BEGIN SECTION --- HOTKEYS MENU ---

        # Console menu pause (no processing while active)
        # TODO implement an event handler so the menu can be moved to another module
        if PAUSE_PROCESSING:
            log.info("Processing paused by console menu; ignoring message.")
            return
        # External model-level call: Record the author for console hotkey menu        
        # This is not going to be a very good idea long-term, because it
        # will cause the module to travel outside of the intended scope.
        _record_author(message)

        # END SECTION --- HOTKEYS MENU ---

        # --- EARLY PK INFO (move this ABOVE compute_access_decision) ---
        # BEGIN SECTION --- EARLY PK AND DECISION INFO ---
        # Get PK Info early so we can use it for recording

        # If this is a webhook/proxy message (PluralKit), attempt to resolve the underlying member for role gating.
        # callie_bot.py (inside on_message after gating resolution)
        member_res_meta = "PK no_resolve_attempt"
        pk_info = None

        cfg = GuildConfig.load_from_message(self.store, message, global_config)
        assert cfg
        # Get the PK data now that we have cfg / guild context
        try:
            member, member_res_meta, pk_info = await resolve_member_for_gate(message, member)
        except Exception as e:
            member_res_meta = f"PK resolve_failed:{type(e).__name__}"
            pk_info = None
        # If PK resolver found PK info, treat the channel as PK-active immediately
        if pk_info is not None:
            self._mark_pk_active(message.channel.id)

        # BEGIN --- Now compute access decision with pk_info ---
        
        bot_id = int(getattr(getattr(self, "user", None), "id", 0))
        decision = await compute_access_decision(
            cfg,
            message,
            bot_user_id=bot_id,
            bot_user=self.user,
            pk_info=pk_info,
            #resolved_member=member # <-- optional but useful
            force_invoked=False # we want all messages evaluated here
        )
        # Centralized gate logging (short + useful)
        # The way return logic works in compute_access_decision, it is not easy to log it inside the function.
        log.info(
            f"Gate: mode={decision.mode.value} allowed={decision.allowed} "
            f"record={decision.record} can_speak={decision.can_speak} speak_suppressed={decision.speak_suppressed} invoked={decision.is_invoked} "
            f"chan={message.channel.id} parent={decision.parent_channel_id} eff_chan={decision.effective_channel_id} "
            f"author={decision.effective_author.author_id} pk={decision.effective_author.is_pk_proxy} reason={decision.reason}"
        )
        # END SECTION --- Now compute access decision with pk_info ---
        # END SECTION --- EARLY PK AND DECISION INFO ---

        # BEGIN PluralKit (PK) handling
        # you need pk_info to do the above. If you don't have it yet at this point,
        # you can mark pk-active simply on ANY webhook message and let PK resolver refine later.
        # Technically, should be unneccesary now.
        if decision.effective_author.is_pk_proxy or message.webhook_id is not None:
            self._mark_pk_active(message.channel.id)
            # Optionally only mark active if PK resolver says it's a PK message (200).
            # If you already have pk_info in-hand, use that instead of unconditional marking.

        # Now: if this looks like a pre-proxy original in a PK-active channel, defer/skip it.
        if await self._maybe_defer_preproxy_message(message):
            log.info("PK preproxy: skipping likely-original msg_id=%s channel=%s", message.id, message.channel.id)
            return

        # END PluralKit (PK) handling

        # Hard stop: disallowed / not recording / not speaking means we do nothing.
        if not decision.record and not decision.can_speak:
            log.debug("Gate: neither recording nor speaking allowed -> ignore")
            return

        # Record message if policy says so.
        if decision.record:
            await self.record_incoming_message(message, decision, pk_info)
            # Optional: you can also kick your summary maintenance here even if can_speak is False.
            # That’s where PASSIVE channels become “aware”.

        author_name = decision.effective_author.author_name or getattr(message.author, "display_name", str(message.author))
        raw_content = message.content or ""

        log.info(f"RX guild_id={message.guild.id if message.guild else None} "
                 f"msg_id={message.id} author={author_name} author_id={message.author.id} "
                 f"chars={len(raw_content)} attachments={len(getattr(message, 'attachments', []) or [])}")

        # If we aren't allowed to speak, stop after recording/summary work.
        if not decision.can_speak:
            await self._maybe_send_attachment_invocation_reminder(message, decision)
            log.info("Gate: speaking not allowed -> stop after recording")
            return
        # Ambient reply suppression
        if decision.speak_suppressed:
            await self._maybe_send_attachment_invocation_reminder(message, decision)
            log.info("Gate: ambient/passive suppression -> stop after recording")
            return

        attachment_policy = await cfg.attachment_inspection_policy()
        if getattr(message, "attachments", None):
            log.info(
                "Attachment policy msg_id=%s policy=%s invoked=%s can_speak=%s attachments=%s",
                message.id,
                attachment_policy,
                decision.is_invoked,
                decision.can_speak,
                len(message.attachments),
            )
        if attachment_policy == "disabled" and getattr(message, "attachments", None):
            log.info("Attachment policy disabled -> stop before model msg_id=%s", message.id)
            await self._maybe_send_attachment_invocation_reminder(
                message,
                decision,
                force=True,
                source="attachment_policy_disabled",
                reminder="(Attachment note: file/image inspection is currently disabled for this connector.)",
            )
            return
        if attachment_policy == "invoked" and getattr(message, "attachments", None) and not decision.is_invoked:
            await self._maybe_send_attachment_invocation_reminder(
                message,
                decision,
                force=True,
                source="attachment_policy_requires_invocation",
            )
            log.info("Attachment policy requires invocation -> stop before model msg_id=%s", message.id)
            return
        #if cfg.reply_policy == "Ambient":
        #    if should_suppress_ambient_reply(
        #      message, bot_user=self.user,
        #        suppress_enabled=await cfg.suppress_ambient_replies(),
        #        allow_name_prefix=await cfg.allow_name_prefix(),
        #    ):

        # Diagnostic: help prove when/why guild/member context is missing.
        try:
            log.info(
                f"Gate debug: guild={'yes' if message.guild else 'no'} guild_id={getattr(message.guild,'id',None)} "
                f"webhook_id={getattr(message,'webhook_id',None)} author_id={getattr(message.author,'id',None)} "
                f"member={'yes' if member else 'no'} resolved={member_res_meta} {roles_meta(member)}"
            )
        except Exception:
            pass

        # If this is a generic webhook (not PluralKit-resolved), do NOT attempt RBAC based on it.
        # We refuse to process it as a user message to avoid granting powers to arbitrary integrations.
        if getattr(message, "webhook_id", None) and member is None and pk_info is None:
            log.info(
                f"Gate: untrusted webhook (no resolved member); ignoring msg_id={getattr(message,'id',None)} "
                f"webhook_id={getattr(message,'webhook_id',None)}"
            )
            return

        session_channel_id = message.channel.id
        # This was set above already - then we commented it out
        parent_channel_id = get_effective_channel_id(message, parent=True)

        st = await self.store.get_session(session_channel_id)
        if not await self.check_session_gate(decision):
            log.info("Gate: check_session_gate -> ignore (chan=%s parent=%s)", session_channel_id, parent_channel_id)
            return
        # This will abort if the session for this channel was explicitly closed by an admin.
        if st is not None and st.is_closed():
             log.info("Gate: session inactive -> ignore (chan=%s parent=%s)", session_channel_id, parent_channel_id)
             return
        enrich_policy = await cfg.msg_enrich_policy()

        # Log policy sources for easier debugging
        enrich_policy2, enrich_src = await cfg.get_raw_with_source("MSG_ENRICH_POLICY", "full")
        enrich_policy = (enrich_policy or "full").strip().lower()
        log.info("Policy: msg_enrich_policy=%s source=%s", enrich_policy, enrich_src)

        # replaces all_transcript to require_callie_role
        (
            all_transcript,
            transcript,
            dropped_count,
            summary_ctx_note,
            memory_blob,
            transcript_budget,
            reserve,
            kept_tokens,
        ) = await self._prepare_transcript_with_summaries(message, cfg)

        # Build server context for the model. Enrichment controls what identity/role data we expose.
        #require_callie_role = await cfg.require_callie_role()
        pol = await cfg.msg_enrich_policy()
        if pol == "anon":
            server_ctx = (
                f"[Server]\n"
                f"guild_id={getattr(message.guild,'id',None)} channel_id={getattr(message.channel,'id',None)}\n"
                f"effective_user_id={getattr(member,'id',getattr(message.author,'id',None))}\n"
            )
        elif pol == "minimal":
            server_ctx = identity_meta(message)
        else:
            server_ctx = identity_meta(message) + "\n" + roles_meta(member)

        # PK behavior note for the model, if we saw any PK-style messages recently.
        saw_any_pk_recently = member_res_meta.startswith("proxied:") if isinstance(member_res_meta, str) else False
        if pk_info is not None:
            saw_any_pk_recently = True
        if saw_any_pk_recently:
            server_ctx += (
                "\n\n[PK behavior note]\n"
                "PluralKit proxying may produce a short-lived original user message followed by a webhook proxy repost "
                "with near-identical content. If you see duplicates close together, treat the webhook/proxy speaker "
                "message as canonical and ignore the transient original.\n"
                "Address speakers by their visible proxy name when present.\n"
            )

        # If this was a webhook/proxy message and we resolved an underlying member (PluralKit-style),
        # add metadata so the model can keep conversational identity (proxy/fronter) distinct from the RBAC identity.
        # If we could not resolve the underlying member, still add metadata so the model knows it was proxied.
        try:
            if getattr(message, "webhook_id", None) and (pk_info is not None or (isinstance(member_res_meta, str) and member_res_meta.startswith("proxied"))):
                proxy_name = getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Unknown"
                if pk_info is not None:
                    pk_visible_to_model = (enrich_policy == "full")  # or allow "minimal" if you redact IDs
                    if getattr(message, "webhook_id", None) and pk_info is not None:
                        log.info("PK: resolved msg_id=%s member=%s system=%s sender_id=%s enrich_policy=%s inject=%s",
                                message.id, pk_info.member_name, pk_info.system_name, pk_info.sender_id, enrich_policy, pk_visible_to_model)
                        if pk_visible_to_model:
                            server_ctx += format_pk_proxy_note(pk_info, visible_proxy_name=proxy_name, resolved_member=member)
                            server_ctx += build_pk_context_block(pk_info=pk_info, message=message)
                        else:
                            log.info("PK: resolved but NOT injected due to msg_enrich_policy=%s (privacy)", enrich_policy)
                    #server_ctx += format_pk_proxy_note(pk_info, visible_proxy_name=proxy_name, resolved_member=member)
                    #server_ctx += build_pk_context_block(
                    #    pk_info=pk_info,
                    #    message=message,
                    #)
                else:
                    server_ctx += (
                        "\n\n[Proxy note]\n"
                        "This message was posted via a webhook/proxy (likely PluralKit).\n"
                        f"Visible proxy name: {proxy_name}\n"
                        f"Resolution meta: {member_res_meta}\n"
                        "Use Resolution meta for role/permission assumptions, but address the user conversationally by the visible proxy name when appropriate.  Prefer replying to the message (message reference) rather than pinging a user."
                    )
        except Exception:
            pass

        if (await cfg.require_guild_context()) and (message.guild is None or member is None):
            log.error(
                f"Hard-stop: missing guild/member context; refusing OpenAI call "
                f"msg_id={message.id} author_id={getattr(message.author,'id',None)}"
            )
            try:
                await message.reply(
                    "(connector error: missing server role context; refusing to call model)",
                    mention_author=False,
                )
            except Exception as e:
                # a fallback error to the console, just in case nobody noticed that the Discord replies also failed
                log.error(f"cfg.require_guild_context() err ack to Discord err={type(e).__name__}: {e}")
                log.debug(traceback.format_exc())
            return

        # We never share a message where the user has zero roles
        if member is None:
            log.error(f"CTX missing member/roles; refusing OpenAI call msg_id={message.id} author_id={message.author.id}")
            await message.reply("(connector error: missing server role context; refusing to call model)", mention_author=False)
            return

        ctx_notice = ""
        if dropped_count:
            oldest_kept = transcript[0]["created_at"] if transcript else None
            ctx_notice = (
                "Older chat context was omitted to stay within the context budget.\n"
                f"dropped_messages={dropped_count}\n"
                f"oldest_kept_epoch={oldest_kept}\n"
                "If the user asks about omitted content, ask for a refresher or use /callie verbose on."
            )
        
        # Add summary context note into the model-visible context notice.
        if summary_ctx_note:
            ctx_notice = (summary_ctx_note + "\n" + (ctx_notice or "")).strip()

        # Apply enrichment redaction to the transcript for the model, if requested.
        transcript, anon_map = apply_enrich_policy_to_transcript(transcript, enrich_policy)
        if anon_map:
            try:
                server_ctx += "\n(Anon mode: speaker names are pseudonymized.)"
            except Exception:
                pass
        log.info(f"Dispatch: transcript_msgs={len(transcript)}/{len(all_transcript)} memory_chars={len(memory_blob)} replying_to_msg_id={message.id}")

        # Call OpenAI to get a response
        extra_parts: List[Dict[str, Any]] = []
        user_notes: List[str] = []
        reply_diagnostics: Dict[str, Any] = {}
        async with message.channel.typing():
            try:
                provider_config = await cfg.connector_provider_config()
                model = await cfg.openai_model()
                oauth_sources = resolve_oauth_tokens(provider_config) if not provider_config.is_openai_api else None
                log.info(
                    "LLM provider selected backend=%s auth_mode=%s model=%s oauth_access_source=%s oauth_refresh_source=%s msg_id=%s",
                    provider_config.backend,
                    provider_config.auth_mode,
                    model,
                    oauth_sources.access_source if oauth_sources else "not_applicable",
                    oauth_sources.refresh_source if oauth_sources else "not_applicable",
                    message.id,
                )
                validate_provider_config(provider_config)

                extra_parts, user_notes = await self._build_attachment_parts(
                    message,
                    cfg,
                    should_process=bool(
                        decision.can_speak
                        and (attachment_policy == "reply" or decision.is_invoked)
                    ),
                )
                system_prompt = await cfg.system_prompt()
                max_output_tokens = await cfg.max_output_tokens()
                api_key = await cfg.openai_api_key()
                # Hard guards with non-leaky errors
                if not model or not str(model).strip():
                    raise RuntimeError("Missing OPENAI_MODEL")
                if not api_key or not str(api_key).strip():
                    raise RuntimeError("Missing OPENAI_API_KEY")
                if not isinstance(max_output_tokens, int) or max_output_tokens <= 0:
                    raise RuntimeError(f"Invalid max_output_tokens={max_output_tokens!r}")

                reply, response_id, reply_diagnostics = await openai_respond(
                    system_prompt=system_prompt,
                    memory_blob=memory_blob,
                    transcript=transcript,
                    server_ctx=server_ctx,
                    ctx_notice=ctx_notice,
                    max_output_tokens=max_output_tokens,
                    api_key=api_key,
                    model=model,
                    extra_content_parts=extra_parts,
                    cost_telemetry=await cfg.cost_telemetry_config(),
                    provider_config=provider_config,
                )
                image_parts = sum(1 for part in extra_parts if part.get("type") == "input_image")
                file_parts = sum(1 for part in extra_parts if part.get("type") == "input_file")
                text_parts = sum(1 for part in extra_parts if part.get("type") == "input_text")
                reply_diagnostics.update(
                    {
                        "backend": provider_config.backend,
                        "auth_mode": provider_config.auth_mode,
                        "image_parts": image_parts,
                        "file_parts": file_parts,
                        "text_parts": text_parts,
                    }
                )

                log.info("OpenAI response_id=%s chars=%s for msg_id=%s", response_id, len(reply), message.id)
            except NotImplementedError as e:
                response_id = ""
                log.warning("Connector provider backend unavailable msg_id=%s err=%s", message.id, str(e))
                reply = "(connector config error: selected LLM backend is not implemented yet; see logs)"
            except Exception as e:
                response_id = ""
                # Log full traceback to console logs, but DO NOT echo exception text to Discord
                outage = classify_openai_exception(e)
                if outage:
                    log.warning("%s msg_id=%s", format_admin_outage(outage, context="respond"), message.id)
                else:
                    log.exception("OpenAI failed msg_id=%s err=%s", message.id, type(e).__name__)
                log.debug(traceback.format_exc())
                # Safe user-facing message
                reply = outage.user_message if outage else "(error calling model; see logs)"

        # Capture structured memory suggestions from the model (but do not auto-commit).
        # Format: [[MEMORY_SUGGEST]] {json...} [[/MEMORY_SUGGEST]]
        suggestions: List[int] = []
        try:
            for match in re.finditer(r"\[\[MEMORY_SUGGEST\]\](.*?)\[\[/MEMORY_SUGGEST\]\]", reply, flags=re.S):
                raw = match.group(1).strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    canon = canonical_json(obj)
                except Exception:
                    canon = canonical_json({"raw": raw})
                sid = await self.store.add_memory_suggestion(
                    author_id=message.author.id,
                    author_name=author_name,
                    payload_json=canon,
                )
                suggestions.append(sid)

            if suggestions:
                reply = re.sub(r"\[\[MEMORY_SUGGEST\]\].*?\[\[/MEMORY_SUGGEST\]\]\s*", "", reply, flags=re.S).strip()
        except Exception as e:
            log.warning(f"Suggestion capture failed: {type(e).__name__}: {e}")

        if suggestions:
            reply += "\n\n(Connector note: captured memory suggestions pending approval: " + ", ".join([f"P{sid}" for sid in suggestions]) + ")"

        # TODO fix the summary context note so the memory suggestion is visible to the user
        if st.verbose and summary_ctx_note:
            reply = f"{summary_ctx_note}\n\n{reply}"

        if st.verbose and dropped_count:
            reply = f"(Context note: I omitted {dropped_count} older message(s) to stay within limits.)\n\n{reply}"
        
        if user_notes:
            # Tell the user what we shielded, but still proceed with the message.
            shield_msg = "(Attachment notes: " + " | ".join(user_notes) + ")"
            reply = shield_msg + "\n\n" + reply

        cleanup_names = [
            decision.effective_author.author_name,
            getattr(message.author, "display_name", None),
            getattr(message.author, "name", None),
        ]
        before_cleanup = reply
        reply = strip_obvious_reply_prefix(reply, [str(name) for name in cleanup_names if name])
        if reply != before_cleanup:
            log.info("Reply cleanup: stripped leading addressee prefix msg_id=%s", message.id)

        diagnostics_mode = await cfg.reply_diagnostics_mode()
        diagnostics_view: Optional[ReplyDiagnosticsView] = None
        if diagnostics_mode in {"spoiler", "both"} and reply_diagnostics:
            reply += f"\n\n||{_reply_diagnostics_brief(reply_diagnostics)}||"
        if diagnostics_mode in {"button", "both"} and reply_diagnostics:
            diagnostics_view = ReplyDiagnosticsView(reply_diagnostics)

        limit = await cfg.discord_safe_limit()
        chunks = chunk_for_discord(reply, limit)
        log.info(f"TX plan: chunks={len(chunks)} sizes={[len(c) for c in chunks]} in_reply_to={message.id}")

        # This time, try it with *more feeling*... much better... X_x
        sent_messages = []
        for idx, chunk in enumerate(chunks):
            part = idx + 1
            total = len(chunks)
            chars = len(chunk)

            # For the first chunk, try to reply directly to the message.
            # If that fails (deleted message, etc), fall back to a standard send.
            if idx == 0:
                try:
                    factory = (lambda ch=chunk: send_reply(message, ch, view=diagnostics_view))
                    fallback_factory = (lambda ch=chunk: message.channel.send(ch, silent=True, view=diagnostics_view))
                except Exception:
                    log.error("Failed to build PK-aware reply factory; falling back to standard reply.")
                    factory = (lambda ch=chunk: message.reply(ch, mention_author=False, view=diagnostics_view))
                    fallback_factory = (lambda ch=chunk: message.channel.send(ch, silent=True, view=diagnostics_view))
            else:
                factory = (lambda ch=chunk: message.channel.send(ch, reference=message, silent=True))
                fallback_factory = (lambda ch=chunk: message.channel.send("(Context note: I couldn't reply directly because the referenced message was deleted or unavailable.)\n\n" + ch, silent=True))

            sent = await send_with_retry(
                factory,
                fallback_send_coro_factory=fallback_factory,
                trace_id=message.id,
                part_idx=part,
                total_parts=total,
                chars=chars,
                cooldown_seconds=cfg.global_config.discord_send_cooldown_secs,
                max_retries=cfg.global_config.discord_send_max_retries,
                retry_base_seconds=cfg.global_config.discord_send_retry_base_secs,
                retry_max_seconds=cfg.global_config.discord_send_retry_max_secs,
                retry_jitter_seconds=cfg.global_config.discord_send_retry_jitter_secs,
            )
            if not sent:
                break
            # We sent is reply so tap the session
            await self.touch_session(decision)

            # Vivian - Is it silly at this point to ask what is the state of decision.record?
            if decision.record:
                try:
                    await self.record_outgoing_callie(sent, cfg)
                    if _log_settings.log_sql_every_message:
                        log.debug(f"SQL stored TX msg_id={sent.id}")
                except Exception as e:
                    log.error(f"SQL store TX failed msg_id={sent.id} err={type(e).__name__}: {e}")

            sent_messages.append(sent)

            # Vivian - Callie says it won't do what we want... whatever
            # Log sent messages to SQL
            #for sent in sent_messages:
                
