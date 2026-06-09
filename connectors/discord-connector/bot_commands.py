from datetime import datetime, timezone
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple
#import traceback
import inspect
import discord
from discord import app_commands
from callie_store import Store
from config_manager import ConfigManager
from discord_helpers import _require_admin, chunk_for_discord, interaction_member, is_admin, passes_access_gate_gc
from env_utils_new import is_sensitive_config_name
from global_config import GlobalConfig
from guild_config import GuildConfig
from helpers import _ts_to_str, canonical_json, now_epoch, parse_iso_datetime_to_epoch, parse_prefixed_int, time_str_local
from openai_helpers import summarize_messages_block
from callie_logging import log, setup_logging

log, _log_settings = setup_logging("bot_commands")

# Initialize the global Store, GlobalConfig, and ConfigManager
global_config = GlobalConfig()
store = Store(global_config)
config_mgr = ConfigManager(store, global_config)

callie_group = app_commands.Group(name="callie", description="Callie session controls")
memory_group = app_commands.Group(name="memory", description="Curated memory management", parent=callie_group)
suggestions_group = app_commands.Group(name="suggestions", description="Pending memory suggestions", parent=callie_group)
admin_group = app_commands.Group(name="admin", description="Admin maintenance tools (SQL + summaries).", parent=callie_group, default_permissions=discord.Permissions(manage_messages=True))

@admin_group.command(name="config_list", description="List tenant config entries for this server.")
async def admin_config_list(interaction: discord.Interaction):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    cfg = await store.config_list(interaction.guild_id or 0)
    if not cfg:
        await interaction.response.send_message("No tenant_config entries for this server.", ephemeral=True)
        return
    lines = []
    for k, v, ts in cfg:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        safe_v = "<redacted>" if is_sensitive_config_name(k) else v
        lines.append(f"- {k} = {safe_v} (updated {dt.strftime('%Y-%m-%d %H:%M:%S %Z')})")
    await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

@admin_group.command(name="config_get", description="Get a tenant config value by key.")
@app_commands.describe(key="Config key")
async def admin_config_get(interaction: discord.Interaction, key: str):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    v = await store.config_get(interaction.guild_id or 0, key)
    if v is None:
        await interaction.response.send_message(f"{key} is not set in tenant_config for this server.", ephemeral=True)
        return
    safe_v = "<redacted>" if is_sensitive_config_name(key) else v
    await interaction.response.send_message(f"{key} = {safe_v}", ephemeral=True)

@admin_group.command(name="config_set", description="Set a tenant config value (string).")
@app_commands.describe(key="Config key", value="Config value")
async def admin_config_set(interaction: discord.Interaction, key: str, value: str):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    await store.config_set(interaction.guild_id or 0, key, value)
    safe_v = "<redacted>" if is_sensitive_config_name(key) else value
    await interaction.response.send_message(f"Set {key} = {safe_v}", ephemeral=True)

@admin_group.command(name="config_unset", description="Remove a tenant config value.")
@app_commands.describe(key="Config key")
async def admin_config_unset(interaction: discord.Interaction, key: str):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    ok = await store.config_unset(interaction.guild_id or 0, key)
    await interaction.response.send_message(("Removed." if ok else "Key not found."), ephemeral=True)

@admin_group.command(name="config_import_env", description="Copy current .env values into tenant_config for this server.")
async def admin_config_import_env(interaction: discord.Interaction):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    # Import all current process env vars that start with CALLIE_/or known keys; here we take the full allowlist used by this bot.
    keys = [
        "set(await gc.allowed_channel_ids())","set(await gc.allowed_role_ids())","(await gc.require_callie_role())","(await gc.role_channels_access_mode())","ADMIN_ROLE_IDS",
        "TEXT_INJECT_MAX_CHARS","UPLOAD_THROTTLE_ENABLED","NONADMIN_UPLOAD_LIMIT_HOURLY_MB","NONADMIN_UPLOAD_LIMIT_DAILY_MB",
        "ALLOWED_ATTACHMENT_EXTS","BLOCKED_ATTACHMENT_EXTS","(await gc.context_messages())","(await gc.context_token_limit())","(await gc.context_summary_target_tokens())",
        "SUMMARY_TRIGGER_DROPPED_MIN_MESSAGES","SUMMARY_BATCH_MIN_MESSAGES","SUMMARY_BATCH_MAX_MESSAGES","SUMMARY_BATCH_MAX_CHARS","SUMMARY_TARGET_MAX_TOKENS","SUMMARY_MIN_INTERVAL_SECONDS","SUMMARY_ENABLED","MAX_OUTPUT_TOKENS_SHORT","MAX_OUTPUT_TOKENS_LONG",
        "(await gc.openai_api_key())","OPENAI_MODEL","DISCORD_TOKEN","DISCORD_GUILD_ID","(await gc.reply_policy())","(await gc.msg_enrich_policy())","(await gc.require_callie_role())","SUPPRESS_AMBIENT_REPLIES"
    ]
    gid = interaction.guild_id or 0
    count = 0
    for k in keys:
        if k in os.environ:
            await store.config_set(gid, k, os.environ[k])
            count += 1
    await interaction.response.send_message(f"Imported {count} keys from environment into tenant_config for this server.", ephemeral=True)

@admin_group.command(name="summaries_list", description="List summary rows in this channel/thread (newest first).")
@app_commands.describe(limit="How many to list (max 50)", offset="Skip this many newest rows")
async def admin_summaries_list(interaction: discord.Interaction, limit: int = 20, offset: int = 0):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        return
    limit = max(1, min(50, limit))
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    rows = await store.list_summaries(int(channel_id), limit=limit, offset=max(0, offset))
    if not rows:
        await interaction.response.send_message("No summaries found in this channel/thread.", ephemeral=True)
        return

    lines: List[str] = []
    for r in rows:
        lines.append(
            f"id={r['id']}  created={_ts_to_str(r['created_at'])}  chars={r['chars']}  "
            f"range={r['summary_start_db_id']}..{r['summary_end_db_id']}  participants={r['summary_participants'] or ''}"
        )

    raw = "\n".join(lines)
    # chunk safely under Discord's 2000 char limit; wrap each chunk in its own code block
    limit = await gc.discord_safe_limit()
    chunks = chunk_for_discord(raw, limit=max(500, limit - 10))
    for idx, ch in enumerate(chunks):
        payload = f"```{ch}```"
        if idx == 0:
            await interaction.response.send_message(payload, ephemeral=True)
        else:
            await interaction.followup.send(payload, ephemeral=True)

@admin_group.command(name="summaries_merge", description="Create a 'summary of summaries' in this channel/thread for a date range.")
@app_commands.describe(
    start="Optional ISO date/datetime (UTC). Example: 2025-12-01 or 2025-12-01T14:30",
    end="Optional ISO date/datetime (UTC). Example: 2025-12-23 or 2025-12-23T20:00",
    max_chars="Skip any individual summary longer than this many characters (default ≈ 650 tokens).",
)
async def admin_summaries_merge(
    interaction: discord.Interaction,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_chars: int = 2800,
):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return

    # Default range if omitted: one month ago .. one hour ago (to avoid merging the still-hot latest context)
    now_ts = int(time.time())
    default_start_ts = now_ts - (30 * 24 * 60 * 60)
    default_end_ts = now_ts - (60 * 60)
    try:
        start_ts = parse_iso_datetime_to_epoch(start, is_end=False) if start else default_start_ts
        end_ts = parse_iso_datetime_to_epoch(end, is_end=True) if end else default_end_ts
    except Exception as e:
        await interaction.response.send_message(
            f"Invalid start/end date. Use ISO like 2025-12-01 or 2025-12-01T14:30. ({e})",
            ephemeral=True,
        )
        return

    if start_ts is None or end_ts is None or end_ts < start_ts:
        await interaction.response.send_message("End must be >= start.", ephemeral=True)
        return

    max_chars = max(1, int(max_chars))

    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
        return

    # This can take longer than Discord's interaction response window.
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True, thinking=True)

    summary_batch_max_chars = await gc.get_int("SUMMARY_BATCH_MAX_CHARS", 12000)
    summary_target_max_tokens = await gc.get_int("SUMMARY_TARGET_MAX_TOKENS", 650)

    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("This command must be used in a server channel.", ephemeral=True)
        return

    rows = await store.list_summaries_in_range(int(channel_id), start_ts=start_ts, end_ts=end_ts, limit=1000)
    if not rows:
        await interaction.response.send_message("No summaries found in that range for this channel/thread.", ephemeral=True)
        return

    kept = []
    skipped = 0
    participants: List[str] = []
    for r in rows:
        chars = int(r["chars"]) if "chars" in r.keys() else int(r[4])
        if chars > max_chars:
            skipped += 1
            continue
        kept.append(r)
        try:
            p = (r["summary_participants"] or "").strip()
            if p:
                participants.extend([x.strip() for x in p.split(",") if x.strip()])
        except Exception:
            pass
        try:
            participants.append(str(r["author_name"]))
        except Exception:
            pass

    if not kept:
        await interaction.response.send_message(
            f"All {len(rows)} summaries were above max_chars={max_chars}; nothing to merge.",
            ephemeral=True,
        )
        return

    pseudo_messages: List[dict] = []
    total_chars = 0
    for r in kept:
        content = str(r['content']) if 'content' in r.keys() else str(r[3])
        if total_chars + len(content) > summary_batch_max_chars and pseudo_messages:
            break
        total_chars += len(content)
        pseudo_messages.append(
            {
                "db_id": int(r["id"]) if "id" in r.keys() else int(r[0]),
                "author_name": "Callie (summary)",
                "content": content,
                "created_at": int(r["created_at"]) if "created_at" in r.keys() else int(r[1]),
                "is_callie": True,
                "is_summary": True,
                "is_summarized": False,
            }
        )
    merged_text = await summarize_messages_block(pseudo_messages, await gc.openai_model(), max_output_tokens=summary_target_max_tokens)
    if not merged_text:
        await interaction.response.send_message("Merge failed: model returned empty output.", ephemeral=True)
        return

    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("This command must be used in a server channel.", ephemeral=True)
        return

    new_id = await store.insert_summary_row_only(
        int(channel_id),
        merged_text,
        start_ts=start_ts,
        end_ts=end_ts,
        participants=list(sorted(set([p for p in participants if p]))),
    )

    header = (
        f"Created merged summary id={new_id}. Included {len(kept)}/{len(rows)} summaries "
        f"(skipped {skipped} over max_chars={max_chars}).\n"
    )
    body = header + merged_text
    limit = await gc.discord_safe_limit()
    chunks = chunk_for_discord(body, limit - 10)
    if not chunks:
        await interaction.followup.send("Created merged summary, but nothing to display.", ephemeral=True)
        return

    await interaction.followup.send(f"```{chunks[0]}```", ephemeral=True)
    for ch in chunks[1:]:
        await interaction.followup.send(f"```{ch}```", ephemeral=True)


@admin_group.command(name="summaries_dedupe", description="Remove duplicate summary rows in a date range (by covered range and/or exact text).")
@app_commands.describe(
    start="Optional ISO date/datetime (UTC) like 2025-12-01 or 2025-12-01T14:30. Default: 1 month ago.",
    end="Optional ISO date/datetime (UTC). Default: 1 hour ago.",
    limit="Max summaries to scan (oldest first). Default: 2000."
)
async def admin_summaries_dedupe(
    interaction: discord.Interaction,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = 2000,
):
    """Dedupe summaries by (summary_start_db_id, summary_end_db_id) when present, else by exact content."""
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return

    # Defer early to avoid "Unknown interaction" for longer operations
    await interaction.response.defer(ephemeral=True, thinking=True)

    store = interaction.client.store  # type: ignore

    # Defaults: last month through one hour ago (avoid touching the very latest churn by default)
    now_ts = int(time.time())
    default_start_ts = now_ts - (30 * 24 * 60 * 60)
    default_end_ts = max(0, now_ts - (60 * 60))

    try:
        start_ts = parse_iso_datetime_to_epoch(start, is_end=False) if start else default_start_ts
        end_ts = parse_iso_datetime_to_epoch(end, is_end=True) if end else default_end_ts
    except Exception as e:
        await interaction.followup.send(
            f"Invalid start/end date. Use ISO like 2025-12-01 or 2025-12-01T14:30. ({e})",
            ephemeral=True,
        )
        return

    if start_ts is None or end_ts is None or end_ts < start_ts:
        await interaction.followup.send("End must be >= start.", ephemeral=True)
        return

    # Pull summary rows
    rows = await store.list_summaries_in_range(interaction.channel_id, start_ts=start_ts, end_ts=end_ts, limit=int(limit or 2000))

    if not rows:
        await interaction.followup.send("No summaries found in that range.", ephemeral=True)
        return

    seen: Dict[Tuple[str, str], int] = {}
    dupes: List[int] = []
    kept: List[int] = []

    def norm_text(s: str) -> str:
        # Exact-text dedupe, but normalize trivial whitespace so accidental newline differences don't create twins.
        return "\n".join(line.rstrip() for line in (s or "").strip().splitlines()).strip()

    for r in rows:
        sid = int(r["id"])
        s_start = r["summary_start_db_id"]
        s_end = r["summary_end_db_id"]
        content = r["content"] or ""

        # Prefer coverage-range key when available.
        if s_start is not None and s_end is not None:
            key = ("range", f"{int(s_start)}:{int(s_end)}")
        else:
            key = ("text", norm_text(content))

        if key in seen:
            dupes.append(sid)
        else:
            seen[key] = sid
            kept.append(sid)

    if not dupes:
        await interaction.followup.send(f"No duplicates found. Scanned {len(rows)} summaries.", ephemeral=True)
        return

    deleted = 0
    failed: List[int] = []
    for sid in dupes:
        ok = await store.delete_summary(interaction.channel_id, sid, unsummarize=False)
        if ok:
            deleted += 1
        else:
            failed.append(sid)

    # Report
    lines: List[str] = []
    lines.append(f"Summaries scanned: {len(rows)}")
    lines.append(f"Unique keys: {len(seen)}")
    lines.append(f"Duplicates found: {len(dupes)}")
    lines.append(f"Deleted: {deleted}")
    if failed:
        lines.append(f"Failed to delete ({len(failed)}): " + ", ".join(str(x) for x in failed[:50]) + (" ..." if len(failed) > 50 else ""))

    out = "\n".join(lines)
    max_len = await gc.discord_safe_limit()
    chunks = chunk_for_discord(out, max_len)
    for i, c in enumerate(chunks):
        await interaction.followup.send(f"```{c}```", ephemeral=True)

@admin_group.command(name="summaries_show", description="Show a specific summary by its DB id (with metadata).")
@app_commands.describe(summary_id="SQLite message id of the summary row")
async def admin_summaries_show(interaction: discord.Interaction, summary_id: int):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    row = await store.read_summary(int(channel_id), int(summary_id))
    if not row:
        await interaction.response.send_message("Summary not found (in this channel/thread).", ephemeral=True)
        return

    meta = (
        f"id={row['id']}\n"
        f"created_at={_ts_to_str(row['created_at'])}\n"
        f"author={row['author_name']} ({row['author_id']})\n"
        f"range_db={row['summary_start_db_id']}..{row['summary_end_db_id']}\n"
        f"range_ts={row['summary_start_ts']}..{row['summary_end_ts']}\n"
        f"participants={row['summary_participants']}\n"
    )
    body = row["content"] or ""

    # keep within Discord limits; show full-ish, but truncate if huge
    max_body = 12000
    if len(body) > max_body:
        body = body[:max_body] + "\n\n[TRUNCATED]"

    # First response: metadata
    await interaction.response.send_message("**Summary metadata**\n```" + meta + "```", ephemeral=True)

    # Followups: body, chunked
    limit = await gc.discord_safe_limit()
    chunks = chunk_for_discord(body, limit=max(500, limit - 10))
    for ch in chunks:
        await interaction.followup.send("**Summary**\n```" + ch + "```", ephemeral=True)

@admin_group.command(name="summaries_delete", description="Delete a summary by DB id and mark its messages as unsummarized.")
@app_commands.describe(summary_id="SQLite message id of the summary row")
async def admin_summaries_delete(interaction: discord.Interaction, summary_id: int):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    ok = await store.delete_summary(int(channel_id), int(summary_id), unsummarize=False)
    await interaction.response.send_message("Deleted." if ok else "Not found.", ephemeral=True)

@admin_group.command(name="messages_stats", description="Basic message counts by day for this channel/thread.")
@app_commands.describe(days="How many days back to summarize (max 90)")
async def admin_messages_stats(interaction: discord.Interaction, days: int = 14):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    days = max(1, min(90, days))
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    rows = await store.message_stats_by_day(int(channel_id), days=days)
    if not rows:
        await interaction.response.send_message("No message rows found.", ephemeral=True)
        return
    lines = ["day  total callie summaries summarized active"]
    for r in rows:
        lines.append(f"{r['day']}  {r['total']}  {r['callie']}  {r['summaries']}  {r['summarized_msgs']}  {r['active_msgs']}")
    await interaction.response.send_message("```" + "\n".join(lines[:100]) + "```", ephemeral=True)

@admin_group.command(name="messages_list", description="List message rows with snippets (newest first).")
@app_commands.describe(day="Filter by YYYY-MM-DD (optional)", limit="How many to list (max 50)", offset="Skip this many newest rows", include_summaries="Include summary rows too")
async def admin_messages_list(interaction: discord.Interaction, day: Optional[str] = None, limit: int = 20, offset: int = 0, include_summaries: bool = False):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    if day is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", day.strip()):
        await interaction.response.send_message("day must be YYYY-MM-DD", ephemeral=True)
        return
    limit = max(1, min(50, limit))
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    rows = await store.list_messages(int(channel_id), day=day.strip() if day else None, limit=limit, offset=max(0, offset), include_summaries=include_summaries)
    if not rows:
        await interaction.response.send_message("No messages found.", ephemeral=True)
        return
    lines = []
    for r in rows:
        flags = []
        if r["is_callie"]: flags.append("callie")
        if r["is_summary"]: flags.append("summary")
        if r["is_summarized"]: flags.append(f"summarized_in={r['summarized_in']}")
        fl = ",".join(flags) if flags else "-"
        lines.append(f"id={r['id']}  { _ts_to_str(r['created_at']) }  {r['author_name']}  [{fl}]  {r['snippet']!r}")
    await interaction.response.send_message("```" + "\n".join(lines[:50]) + "```", ephemeral=True)

@admin_group.command(name="messages_show", description="Show a message by DB id (with metadata).")
@app_commands.describe(message_id="SQLite message id")
async def admin_messages_show(interaction: discord.Interaction, message_id: int):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    row = await store.read_message(channel_id, int(message_id))
    if not row:
        await interaction.response.send_message("Message not found (in this channel/thread).", ephemeral=True)
        return
    meta = (
        f"id={row['id']}\n"
        f"created_at={_ts_to_str(row['created_at'])}\n"
        f"author={row['author_name']} ({row['author_id']})\n"
        f"is_callie={row['is_callie']}  is_summary={row['is_summary']}  is_summarized={row['is_summarized']}  summarized_in={row['summarized_in']}\n"
    )
    body = row["content"] or ""
    max_body = 3500
    if len(body) > max_body:
        body = body[:max_body] + "\n\n[TRUNCATED]"
    await interaction.response.send_message("**Message metadata**\n```" + meta + "```\n**Message**\n```" + body + "```", ephemeral=True)

@admin_group.command(name="messages_delete", description="Delete a message by DB id (DANGEROUS).")
@app_commands.describe(message_id="SQLite message id")
async def admin_messages_delete(interaction: discord.Interaction, message_id: int):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, True, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    row = await store.read_message(channel_id, int(message_id))
    if not row:
        await interaction.response.send_message("Not found.", ephemeral=True)
        return
    if row["is_summary"]:
        await interaction.response.send_message("That row is a summary. Use `/callie admin summaries_delete`.", ephemeral=True)
        return
    ok = await store.delete_message(channel_id, int(message_id))
    await interaction.response.send_message("Deleted." if ok else "Not found.", ephemeral=True)

@callie_group.command(name="start", description="Start/resume a Callie session in this channel.")
async def start(interaction: discord.Interaction):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to use Callie here.", ephemeral=True)
        return

    # TODO this asssumes the session is always in the first allowed channel; fix later
    # desk_channel_id = (await gc.allowed_channel_ids())[0]
    st = await store.get_session(channel_id)
    st.is_active = True
    st.last_activity = now_epoch()
    await store.set_session(st)
    await interaction.response.send_message(
        "Session started. Default: mention/reply to invoke me. Use `/callie ambient on` for ambient.",
        ephemeral=False
    )

@callie_group.command(name="stop", description="Stop the Callie session in the Desk.")
async def stop(interaction: discord.Interaction):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code

    st = await store.get_session(channel_id) # await gc.desk_channel_id()
    st.is_active = False
    st.ambient = (await gc.ambient_default())
    await store.set_session(st)
    await interaction.response.send_message("Session stopped.", ephemeral=False)

@admin_group.command(name="reply_policy", description="Set Callie's reply policy for this server (admin only).")
@app_commands.describe(policy="Ambient (reply without mention) or Mention (only reply when invoked)")
async def admin_reply_policy(interaction: discord.Interaction, policy: str):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    gid = int(interaction.guild_id or 0)
    pol = (policy or "").strip().lower()
    if pol not in ("ambient", "mention"):
        await interaction.response.send_message("Policy must be 'Ambient' or 'Mention'.", ephemeral=True)
        return
    await store.config_set(gid, "(await gc.reply_policy())", pol.title())
    await interaction.response.send_message(f"Reply policy set to **{pol.title()}**.", ephemeral=False)

@admin_group.command(name="enrich_policy", description="Set Callie's message enrichment policy for this server (admin only).")
@app_commands.describe(policy="Full, Minimal, or Anon")
async def admin_enrich_policy(interaction: discord.Interaction, policy: str):
    gc = config_mgr.check_guild(interaction)
    assert gc
    if _require_admin(interaction, await gc.admin_role_ids()) is None:
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return
    gid = int(interaction.guild_id or 0)
    pol = (policy or "").strip().lower()
    if pol not in ("full", "minimal", "anon"):
        await interaction.response.send_message("Policy must be 'Full', 'Minimal', or 'Anon'.", ephemeral=True)
        return
    await store.config_set(gid, "(await gc.msg_enrich_policy())", pol.title())
    await interaction.response.send_message(f"Enrichment policy set to **{pol.title()}**.", ephemeral=False)

@callie_group.command(name="verbose", description="Turn verbose mode on/off (adds context-drop notices).")
@app_commands.describe(mode="on or off")
async def verbose(interaction: discord.Interaction, mode: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        log.info(f"Bot Command Fn PyName=verbose: denied: {msg}")
        await interaction.response.send_message("Use this command in an approved Callie Desk Channel.", ephemeral=True)
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to change verbose mode.", ephemeral=True)
        return

    mode_l = (mode or "").strip().lower()
    if mode_l not in ("on", "off"):
        await interaction.response.send_message("Mode must be `on` or `off`.", ephemeral=True)
        return

    st = await store.get_session(channel_id) # await gc.desk_channel_id()
    st.verbose = (mode_l == "on")
    st.last_activity = now_epoch()
    await store.set_session(st)
    await interaction.response.send_message(f"Verbose mode is now {mode_l}.", ephemeral=False)

@admin_group.command(name="remember", description="(Admin) Promote a note into curated memory (does NOT auto-learn from chat).")
@app_commands.describe(note="What to remember")
async def admin_remember(interaction: discord.Interaction, note: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, True, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to promote memory.", ephemeral=True)
        return

    # Strict gate: only configured admin roles can write curated memory.
    if not is_admin(mem, await gc.admin_role_ids()):
        await interaction.response.send_message("Access denied: curated memory is admin-only.", ephemeral=True)
        return

    await store.add_memory(interaction.user.id, getattr(interaction.user, "display_name", "user"), note.strip())
    await interaction.response.send_message("Stored (curated memory).", ephemeral=True)

@callie_group.command(name="quiet", description="Ignore ambient chatter for N minutes (defaults from env).")
@app_commands.describe(minutes="How many minutes to ignore ambient replies")
async def quiet(interaction: discord.Interaction, minutes: Optional[int] = None):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to change this.", ephemeral=True)
        return

    mins = int(minutes) if minutes is not None else int(await gc.ignore_default_minutes())
    mins = max(1, min(mins, 24 * 60))
    # TODO It is dangerous to let a regular user run a command that is 24 hrs.. check for admin if longer than the max for a regular user
    # Use IGNORE_MAX_MINUTES instead of hardcoded 24*60?

    st = await store.get_session(channel_id)
    st.ignore_until = now_epoch() + (mins * 60)
    await store.set_session(st)
    await interaction.response.send_message(f"Okay. I’ll keep quiet for {mins} minute(s) unless you directly invoke me.", ephemeral=True)

@callie_group.command(name="listen", description="Resume ambient replies immediately.")
async def listen(interaction: discord.Interaction):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to change this.", ephemeral=True)
        return

    st = await store.get_session(channel_id)
    st.ignore_until = 0
    await store.set_session(st)
    await interaction.response.send_message("Listening again.", ephemeral=True)

@memory_group.command(name="list", description="List curated memory items (newest-first).")
@app_commands.describe(limit="How many items to list")
async def memory_list(interaction: discord.Interaction, limit: int = 25):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to view memory.", ephemeral=True)
        return

    rows = await store.list_memory_items(limit=limit)
    if not rows:
        await interaction.response.send_message("Curated memory is empty.", ephemeral=True)
        return

    text = "\n".join([f"{r['mid']} · {time_str_local(r['created_at'])} · {r['author_name']}: {r['content']}" for r in rows])
    await interaction.response.send_message(text[:1900], ephemeral=True)

@memory_group.command(name="show", description="Show a curated memory item by id (e.g. M000123).")
@app_commands.describe(mid="Memory id like M000123")
async def memory_show(interaction: discord.Interaction, mid: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to view memory.", ephemeral=True)
        return

    n = parse_prefixed_int(mid, "M")
    if n is None:
        await interaction.response.send_message("Give me an id like M000123.", ephemeral=True)
        return
    item = await store.get_memory_item(n)
    if not item:
        await interaction.response.send_message("Not found.", ephemeral=True)
        return

    text = f"{item['mid']} · {time_str_local(item['created_at'])} · {item['author_name']}\n\n{item['content']}"
    await interaction.response.send_message(text[:1900], ephemeral=True)

@memory_group.command(name="memory_edit", description="Edit a curated memory item (admin-gated if CALLIE_ADMIN_ROLE_IDS set).")
@app_commands.describe(mid="Memory id like M000123", new_content="New content for this memory item")
async def memory_edit(interaction: discord.Interaction, mid: str, new_content: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to edit memory.", ephemeral=True)
        return
    if not is_admin(mem, await gc.admin_role_ids()):
        await interaction.response.send_message("Admin-gated. Add a role id to CALLIE_ADMIN_ROLE_IDS if you want this locked down differently.", ephemeral=True)
        return

    n = parse_prefixed_int(mid, "M")
    if n is None:
        await interaction.response.send_message("Give me an id like M000123.", ephemeral=True)
        return
    if not (new_content or "").strip():
        await interaction.response.send_message("New content can’t be empty.", ephemeral=True)
        return

    ok = await store.update_memory_item(n, new_content.strip())
    await interaction.response.send_message("Updated." if ok else "No change.", ephemeral=True)

@memory_group.command(name="delete", description="Delete a curated memory item (admin-gated if CALLIE_ADMIN_ROLE_IDS set).")
@app_commands.describe(mid="Memory id like M000123")
async def memory_delete(interaction: discord.Interaction, mid: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to delete memory.", ephemeral=True)
        return
    if not is_admin(mem, await gc.admin_role_ids()):
        await interaction.response.send_message("Admin-gated. Add a role id to CALLIE_ADMIN_ROLE_IDS if you want this locked down differently.", ephemeral=True)
        return

    n = parse_prefixed_int(mid, "M")
    if n is None:
        await interaction.response.send_message("Give me an id like M000123.", ephemeral=True)
        return

    ok = await store.delete_memory_item(n)
    await interaction.response.send_message("Deleted." if ok else "Not found.", ephemeral=True)

@suggestions_group.command(name="list", description="List pending memory suggestions (captured from the model).")
@app_commands.describe(limit="How many suggestions to list", status="pending / accepted / rejected")
async def suggestions_list(interaction: discord.Interaction, limit: int = 25, status: str = "pending"):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to view suggestions.", ephemeral=True)
        return

    rows = await store.list_memory_suggestions(limit=limit, status=status)
    if not rows:
        await interaction.response.send_message(f"No {status} suggestions.", ephemeral=True)
        return

    def summarize_payload(p: str) -> str:
        try:
            obj = json.loads(p)
            # If it has a 'text' field, prefer it; otherwise compact JSON
            if isinstance(obj, dict) and "text" in obj:
                return str(obj["text"])
            return canonical_json(obj)
        except Exception:
            return (p or "").strip()

    text = "\n".join([f"{r['pid']} · {time_str_local(r['created_at'])} · {r['author_name']}: {summarize_payload(r['payload_json'])}" for r in rows])
    await interaction.response.send_message(text[:1900], ephemeral=True)

@suggestions_group.command(name="accept", description="Accept a pending suggestion P<id> and commit it to curated memory.")
@app_commands.describe(pid="Suggestion id like P12")
async def suggestions_accept(interaction: discord.Interaction, pid: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to accept suggestions.", ephemeral=True)
        return
    if not is_admin(mem, await gc.admin_role_ids()):
        await interaction.response.send_message("Admin-gated. Add a role id to CALLIE_ADMIN_ROLE_IDS if you want this locked down.", ephemeral=True)
        return

    sid = parse_prefixed_int(pid, "P")
    if sid is None:
        await interaction.response.send_message("Give me an id like P12.", ephemeral=True)
        return

    ok = await store.decide_memory_suggestion(sid, "accepted", interaction.user.id, getattr(interaction.user, "display_name", "user"))
    await interaction.response.send_message("Accepted." if ok else "Not found / already decided.", ephemeral=True)

@suggestions_group.command(name="reject", description="Reject a pending suggestion P<id>.")
@app_commands.describe(pid="Suggestion id like P12")
async def suggestions_reject(interaction: discord.Interaction, pid: str):
    # repeating code: TODO refactor
    gc = config_mgr.check_guild(interaction)
    assert gc
    check, msg = await check_gate(interaction, True, False, gc)
    if not check:
        return
    mem = interaction_member(interaction)
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message("Use this command in a server channel (not a DM).", ephemeral=True)
        return
    # end of repeating code
    # TODO this fn should support None for channel and return an error
    if not (await passes_access_gate_gc(gc, channel_id, mem)):
        await interaction.response.send_message("You don't have access to reject suggestions.", ephemeral=True)
        return
    if not is_admin(mem, await gc.admin_role_ids()):
        await interaction.response.send_message("Admin-gated. Add a role id to CALLIE_ADMIN_ROLE_IDS if you want this locked down.", ephemeral=True)
        return

    sid = parse_prefixed_int(pid, "P")
    if sid is None:
        await interaction.response.send_message("Give me an id like P12.", ephemeral=True)
        return

    ok = await store.decide_memory_suggestion(sid, "rejected", interaction.user.id, getattr(interaction.user, "display_name", "user"))
    await interaction.response.send_message("Rejected." if ok else "Not found / already decided.", ephemeral=True)

# TODO refactor for a unified access check system with passes_access_gate_gc
async def check_gate(interaction: discord.Interaction, checkAdmin: bool, checkChannel:bool, gc: Optional[GuildConfig] | None = None) -> Tuple[bool, Optional[str]]:
    """Check if the current channel is allowed by channel gate config. Returns None if allowed, else reason string."""
    # sanity check to prevent us from mixing up guilds
    called_by = inspect.stack()[1].function
    if gc:
        if gc.global_config.multi_tenant and gc.guild_id != interaction.guild_id:
            log.error(f"check_for_channel_gate: called by {called_by}; multi-tenant mode with mismatched guild ids: gc.guild_id={gc.guild_id} vs interaction.guild_id={interaction.guild_id}")
            return False, "Internal error: guild mismatch. Contact your server admin."
    # It is OK to use gc because we checked it against iteraction.guild_id above.
    gc_used = gc if gc else config_mgr.check_guild(interaction)
    assert gc_used
    # Double-check, just in case!
    if gc_used.global_config.multi_tenant and gc_used.guild_id != interaction.guild_id:
        log.error(f"check_for_channel_gate: called by {called_by}; multi-tenant mode with mismatched guild ids: gc_used.guild_id={gc_used.guild_id} vs interaction.guild_id={interaction.guild_id}")
        return False, "Internal error: guild mismatch. Contact your server admin."

    if checkAdmin:
        if _require_admin(interaction, await gc_used.admin_role_ids()) is None:
            await interaction.response.send_message("Admins only.", ephemeral=True)
            return False, f"Admin role check failed. Called by {called_by}"

    if checkChannel:
        channel_gate_ids = await gc_used.allowed_channel_ids()
        if not channel_gate_ids:
            await interaction.response.send_message("Use No allowed channel configuration found. Contact your server admin.", ephemeral=False)
            return False, f"No allowed channel configuration found. Called by {called_by}"
        # TODO verify this is going to accept commands run in threads also
        if interaction.channel_id in channel_gate_ids:
            return True, f"Allowed because channel {interaction.channel_id} is in the allowed list. Called by {called_by}"
        msg = f"Channel gate in effect: Callie commands can only be used in specific channels."
        log.info(f"Bot Command Fn PyName={called_by}: denied: {msg}")
        await interaction.response.send_message("Use this command in an approved Callie Desk Channel.", ephemeral=True)
        return False, msg
    # TODO for sanity we should probably log this...
    return True, f"No channel gate check required. Called by {called_by}"