from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Sequence

import discord
from callie_logging import log, setup_logging
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from callie_store import Store
from global_config import GlobalConfig
from env_utils_new import (
    #env_str, this likely exists for redaction purposes; TODO import from secure version.
    env_int,
    env_bool,
    env_float,
    env_csv_ints,
    parse_bool, parse_int, parse_float, parse_csv_ints,
    # Optional but recommended in your security posture:
    is_sensitive_config_name, redact_config_value
)
import os

from helpers import normalize_exts
from cost_tracking import CostTelemetryConfig
from provider_backends import ConnectorProviderConfig, normalize_provider_backend

log, _log_settings = setup_logging("guild_config")

@dataclass(slots=True)
class GuildConfig:
    """
    Configuration resolver scoped to a single guild.

    Resolution rules:
    - If GlobalConfig.multi_tenant is True and guild_id != 0:
        -> prefer DB value for this guild
        -> fall back to env default
    - Otherwise:
        -> env only

    This class:
    - NEVER logs raw values
    - NEVER mutates guild_id
    - NEVER shares state across guilds
    """

    # Security note: assert_guild_id should be called by any caller
    # that has a guild_id context, to ensure no bleedover.
    # This is especially important in multi-tenant mode. Responsibility
    # lies with the caller, usually ConfigManager. Note that it is still far
    # too easy to inject a new guild_id into this class, so be careful.

    store: "Store"
    guild_id: int
    global_config: GlobalConfig
    # no longer needed as all references point to global_config
    #multi_tenant: bool=global_config.multi_tenant

    _single_tenant_initialized: bool = False
    _env_snapshot: Dict[str, str] = field(default_factory=dict)
    _db_cache: Dict[str, Optional[str]] = field(default_factory=dict)
    # This actually belongs in congfig manager, not here! 
    # _guild_configs: Dict[int, GuildConfig] = field(default_factory=dict)

    @classmethod
    def load_from_message(cls, store: "Store", message: discord.Message, global_config: GlobalConfig) -> "GuildConfig":
        """
        Load a GuildConfig from a discord.Message.
        Construction helper deliberately designed to make spoofing difficult.
        """
        guild_id = message.guild.id if message.guild and message.guild.id else 0
        if guild_id == 0 and global_config.multi_tenant:
            raise RuntimeError("No guild context for message (DMs not supported).")
        return cls(
            store=store,
            guild_id=guild_id,
            global_config=global_config
        )
    @classmethod
    def load_from_interaction(cls, store: "Store", interaction: discord.Interaction, global_config: GlobalConfig) -> "GuildConfig":
        """
        Load a GuildConfig from a discord.Interaction.
        Construction helper deliberately designed to make spoofing difficult.
        """
        guild_id = interaction.guild.id if interaction.guild and interaction.guild.id else 0
        if guild_id == 0 and global_config.multi_tenant:
            raise RuntimeError("No guild context for interaction. DMs not supported.")
        return cls(
            store=store,
            guild_id=guild_id,
            global_config=global_config
        )
        #cls.assert_guild_id(guild_id, throw=True)

    def assert_guild_id(self, guild_id: int, throw: bool) -> bool:
        """
        Assert that the given guild_id matches this config's guild_id.
        Raise RuntimeError if not matching and throw is True.
        Log a warning and let the caller handle it if throw is False.
        """
        if self.global_config.multi_tenant is False:
            # In single-tenant mode, we don't care about guild_id mismatches
            return True
        if guild_id != self.guild_id:
            if throw:
                raise RuntimeError(f"GuildConfig invariant violated: expected {self.guild_id}, got {guild_id}")
            else:
                log.warning(f"GuildConfig invariant violated: expected {self.guild_id}, got {guild_id}")
            return False
        return True

    # This actually belongs in config manager, not here!
    #def get_for_guild_id(self, guild_id: Optional[int]) -> GuildConfig:
    #    """
    #    Return a GuildConfig for the given guild_id.
    #
    #    guild_id may be None or 0 for non-guild contexts.
    #    In that case, we still return a GuildConfig bound to guild_id=0.
    #    """
    #    gid = int(guild_id or 0)
    #
    #    # Single-tenant shortcut: always return the same config
    #    if not self.global_config.multi_tenant:
    #        if 0 not in self._guild_configs:
    #            self._guild_configs[0] = GuildConfig(
    #                store=self.store,
    #                guild_id=0,
    #                multi_tenant=False,
    #                global_config=self.global_config,
    #            )
    #        return self._guild_configs[0]
    #
    #    # Multi-tenant path
    #    cfg = self._guild_configs.get(gid)
    #    if cfg is not None:
    #        return cfg
    #
    #    cfg = GuildConfig(
    #        store=self.store,
    #        guild_id=gid,
    #        multi_tenant=True,
    #        global_config=self.global_config,
    #    )
    #    self._guild_configs[gid] = cfg
    #    return cfg

    def log_all_configs(self) -> None:
        """
        Log all config keys and values for this guild.
        Redact sensitive values.
        """
        log.info(f"Configuration for guild_id={self.guild_id}:")
        # TODO fetch all keys from DB for this guild if multi-tenant
        # For now, just log env vars
        for key, value in os.environ.items():
            display_value = redact_config_value(key, value)
            log.info(f"  {key} = {display_value}")

    async def log_explicit(self) -> None:
        # Note we DO NOT send all config keys/values to log!
        # Especially not sensitive ones like OPENAI_API_KEY.
        log.info(f"Guild ID: {self.guild_id}")
        log.info(f"Allowed channels: {await self.allowed_channel_ids()}")
        # Desk Channel ID doesn't exist any more
        #log.info(f"Desk channel ID: {self.desk_channel_id()}")
        log.info(f"Allowed roles: {await self.allowed_role_ids()}") 
        log.info(f"Session TTL minutes: {await self.session_ttl_minutes()}")
        log.info(f"Ambient default: {await self.ambient_default()}")
        log.info(f"Require Callie role: {await self.require_callie_role()}")
        log.info(f"Role channels access mode: {await self.role_channels_access_mode()}")
        log.info(f"Default reply policy: {await self.reply_policy()}")
        log.info(f"Default message enrichment policy: {await self.msg_enrich_policy()}")
        log.info(f"Default context messages: {await self.context_messages()}")
        log.info(f"Default context token limit: {await self.context_token_limit()}")
        # TODO implement others as needed

    def clear_db_cache(self) -> None:
        self._db_cache.clear()

    def configure_from_env_if_single_tenant(self) -> None:
        if self.global_config.multi_tenant or self._single_tenant_initialized:
            return
        self._env_snapshot = dict(os.environ)
        self._single_tenant_initialized = True

    # -------------
    # Low-level raw fetch
    # -------------

    # Section for getting raw values from DB or env, and parsing them.

    async def _get_from_db(self, key: str) -> Optional[str]:
        if key in self._db_cache:
            return self._db_cache[key]
        v = await self.store.config_get(self.guild_id, key)
        self._db_cache[key] = v
        return v

    async def get_raw(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Return raw string value for key.
        """
        #if self.global_config.multi_tenant and self.guild_id:
        #    v = await self.store.config_get(self.guild_id, key)
        #    if v is not None:
        #        return v
        #return env_str(key, default)
        if self.global_config.multi_tenant:
            v = await self._get_from_db(key)
            if v is not None:
                return v
            return os.getenv(key, default)
        self.configure_from_env_if_single_tenant()
        if self._single_tenant_initialized:
            return self._env_snapshot.get(key, default)
        return os.getenv(key, default)

    async def get_raw_with_source(self, key: str, default: Optional[str] = None) -> tuple[Optional[str], str]:
        if self.global_config.multi_tenant:
            v = await self._get_from_db(key)
            if v is not None:
                return v, "db"
            return os.getenv(key, default), "env"
        self.configure_from_env_if_single_tenant()
        if self._single_tenant_initialized:
            return self._env_snapshot.get(key, default), "env_snapshot"
        return os.getenv(key, default), "env"

    # -------------
    # Typed getters (generic)
    # -------------

    async def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        result, src =await self.get_raw_with_source(key, default)
        return result

    async def get_int(self, key: str, default: int = 0) -> int:
        raw = await self.get_raw(key, None)
        return env_int(key, default=default, value_override=raw)
    #async def get_int(self, key: str, default: int = 0) -> int:
    #    return parse_int(await self.get_raw(key, None), default, key=key)

    async def get_float(self, key: str, default: float = 0.0) -> float:
        raw = await self.get_raw(key, None)
        return env_float(key, default=default, value_override=raw)
    #async def get_float(self, key: str, default: float = 0.0) -> float:
    #    return parse_float(await self.get_raw(key, None), default, key=key)

    async def get_bool(self, key: str, default: bool = False) -> bool:
        raw = await self.get_raw(key, None)
        return env_bool(key, default=default, value_override=raw)
    #async def get_bool(self, key: str, default: bool = False) -> bool:
    #    return parse_bool(await self.get_raw(key, None), default, key=key)

    async def get_csv_ints(self, key: str, default: Optional[Sequence[int]] = None) -> List[int]:
        raw = await self.get_raw(key, None)
        vals = env_csv_ints(key, value_override=raw)
        if vals:
            return vals
        return list(default) if default is not None else []
    #async def get_csv_ints(self, key: str) -> List[int]:
    #    return parse_csv_ints(await self.get_raw(key, None), key=key)

    # Back-compat shim (helps during refactors)
    async def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        return await self.get_raw(key, default)

    # -------------
    # Convenience getters (the “no more globals” layer)
    # -------------

    async def require_callie_role(self) -> bool:
        return await self.get_bool("REQUIRE_CALLIE_ROLE", False)

    async def allowed_role_ids(self) -> List[int]:
        """Roles allowed to summon Callie when REQUIRE_CALLIE_ROLE is true"""
        return await self.get_csv_ints("ALLOWED_ROLE_IDS")
    
    async def admin_role_ids(self) -> List[int]:
        # Roles allowed to run Callie admin commands
        return await self.get_csv_ints("ADMIN_ROLE_IDS")

    async def allowed_channel_ids(self) -> List[int]:
        """Channels where Callie may be invoked / may respond"""
        return await self.get_csv_ints(
            "ALLOWED_CHANNEL_IDS",
            default=self.global_config.allowed_channel_ids
        )
 
    async def passive_channel_ids(self) -> List[int]:
        """Channels that Callie may record/summarize but should not speak unless invoked."""
        return await self.get_csv_ints(
            "PASSIVE_CHANNEL_IDS",
            default=self.global_config.passive_channel_ids
        )

    async def ambient_channel_ids(self) -> List[int]:
        """Channels that allow ambient participation (subject to your other gates)."""
        return await self.get_csv_ints(
            "AMBIENT_CHANNEL_IDS",
            default=self.global_config.ambient_channel_ids
        )

    #async def desk_channel_id(self) -> int:
    #    """'Home' channel: first allowed channel, or 0 if none"""
    #    chans = await self.allowed_channel_ids()
    #    return int(chans[0]) if chans else 0

    async def role_channels_access_mode(self) -> str:
        """ AND / OR """
        v = (await self.get_str("ROLE_CHANNELS_ACCESS_MODE", "AND")) or "AND"
        return v.strip().upper()
    #async def role_channels_access_mode(self) -> str:
    #    raw = await self.get_raw("ROLE_CHANNELS_ACCESS_MODE", "AND")
    #    return (raw or "AND").strip().upper()

    async def reply_policy(self) -> str:
        """ 'ambient' or 'mention' """
        v = (await self.get_str("REPLY_POLICY", "mention")) or "mention"
        return v.strip().lower()
    #async def reply_policy(self) -> str:
    #    raw = await self.get_raw("REPLY_POLICY", "Mention")
    #    return (raw or "Mention").strip()

    async def msg_enrich_policy(self) -> str:
        """ 'full' / 'minimal' / 'anon' """
        v = (await self.get_str("MSG_ENRICH_POLICY", "full")) or "full"
        return v.strip().lower()
    #async def msg_enrich_policy(self) -> str:
    #    raw = await self.get_raw("MSG_ENRICH_POLICY", "Full")
    #    return (raw or "Full").strip()

    async def ambient_default(self) -> bool:
        return await self.get_bool("AMBIENT_DEFAULT", False)

    async def session_ttl_minutes(self) -> int:
        return await self.get_int("SESSION_TTL_MINUTES", 180)

    async def suppress_ambient_replies(self) -> bool:
        return await self.get_bool("SUPPRESS_AMBIENT_REPLIES", False)

    # Discord chunking

    async def discord_msg_limit(self) -> int:
        """
        Base default is 2000, but keep it configurable.
        DB override if multi-tenant; env fallback otherwise.
        """
        return await self.get_int("DISCORD_MSG_LIMIT", 2000)

    async def discord_safe_limit(self) -> int:
        """Safe headroom default"""
        return (await self.discord_msg_limit()) - 100
        # why even bother making this configurable separately?
        #return await self.get_int("DISCORD_SAFE_LIMIT", 1900)

    # Attachments
    async def max_attachment_mb(self) -> float:
        """This is the softer limit for PDFs and images we try to inline. Default 10 MB."""
        return await self.get_float("MAX_ATTACHMENT_MB", 10.0)
    
    # TODO consider making this a global config value
    async def max_files_api_bytes(self) -> int:
        """This is a hard limit for the files we send to OpenAI Files API. Default 50 MB."""
        return await self.get_int("MAX_FILES_API_BYTES", 50 * 1024 * 1024)

    async def allowed_attachment_exts(self) -> List[str]:
        raw = (await self.get_str("ALLOWED_ATTACHMENT_EXTS", "")) or ""
        if not raw or raw == "":
            return self.global_config.default_allowed_attachment_exts() if callable(self.global_config.default_allowed_attachment_exts) else self.global_config.default_allowed_attachment_exts
        return normalize_exts(raw.split(","))
        #return [p.strip().lower() for p in raw.split(",") if p.strip()]
    #async def allowed_attachment_exts(self) -> List[str]:
    #    raw = await self.get_raw("ALLOWED_ATTACHMENT_EXTS", "")
    #    if not raw:
    #        return []
    #    return [p.strip().lower() for p in str(raw).split(",") if p.strip()]

    async def blocked_attachment_exts(self) -> List[str]:
        raw = (await self.get_str("BLOCKED_ATTACHMENT_EXTS", "")) or ""
        if not raw or raw == "":
            return self.global_config.default_blocked_attachment_exts() if callable(self.global_config.default_blocked_attachment_exts) else self.global_config.default_blocked_attachment_exts
        return normalize_exts(raw.split(","))
        #return [p.strip().lower() for p in raw.split(",") if p.strip()]
    #async def blocked_attachment_exts(self) -> List[str]:
    #    raw = await self.get_raw("BLOCKED_ATTACHMENT_EXTS", "")
    #    if not raw:
    #        return []
    #    return [p.strip().lower() for p in str(raw).split(",") if p.strip()]

    # OpenAI “cost levers”
    async def openai_api_key(self) -> Optional[str]:
        """
        Prefer per-guild override (DB) if present; otherwise env.
        Never log the value; caller uses it for API calls only.
        """
        token = await self.get_str("OPENAI_API_KEY", None)
        if token:
            return token
        return await self.get_str("OPENAI_API_TOKEN", None)

    async def openai_oauth_token(self) -> Optional[str]:
        """
        ChatGPT/Codex-style OAuth/access token slot for future authenticated-session backends.
        This is intentionally separate from OPENAI_API_TOKEN so operators can keep both.
        """
        return await self.get_str("OPENAI_OAUTH_TOKEN", None)

    async def openai_model(self) -> str:
        default = self.global_config.default_openai_model() if callable(self.global_config.default_openai_model) else self.global_config.default_openai_model
        v = (await self.get_str("OPENAI_MODEL", default)) or default
        return str(v).strip()

    async def max_output_tokens(self) -> int:
        return await self.get_int("MAX_OUTPUT_TOKENS", 600)

    async def cost_telemetry_config(self) -> CostTelemetryConfig:
        return CostTelemetryConfig(
            enabled=await self.get_bool("OPENAI_COST_LOG_ENABLED", True),
            monthly_budget_usd=await self.get_float("OPENAI_MONTHLY_BUDGET_USD", 0.0),
            month_to_date_start_usd=await self.get_float("OPENAI_MONTH_TO_DATE_SPEND_USD", 0.0),
            default_input_per_1m=await self.get_float("OPENAI_COST_INPUT_PER_1M", 0.0),
            default_output_per_1m=await self.get_float("OPENAI_COST_OUTPUT_PER_1M", 0.0),
            model_pricing_json=(await self.get_str("OPENAI_MODEL_PRICING_JSON", "")) or "",
        )

    async def connector_provider_config(self) -> ConnectorProviderConfig:
        return ConnectorProviderConfig(
            backend=normalize_provider_backend(await self.get_str("CONNECTOR_LLM_BACKEND", "openai_api")),
            auth_mode=((await self.get_str("CONNECTOR_AUTH_MODE", "api_key")) or "api_key").strip().lower(),
            oauth_token=((await self.openai_oauth_token()) or "").strip(),
            oauth_refresh_token=((await self.get_str("OPENAI_OAUTH_REFRESH_TOKEN", "")) or "").strip(),
            token_path=((await self.get_str("OPENAI_OAUTH_TOKEN_PATH", "")) or "").strip(),
            refresh_token_path=((await self.get_str("OPENAI_OAUTH_REFRESH_TOKEN_PATH", "")) or "").strip(),
            oauth_device_code_command=((await self.get_str("CONNECTOR_OAUTH_DEVICE_CODE_COMMAND", "")) or "").strip(),
        )

    # Context management

    # AFAIK this will Always be true for now...
    async def require_guild_context(self) -> bool:
        return True; #await self.get_bool("REQUIRE_SERVER_CONTEXT", False)

    async def system_prompt(self) -> str:
        default = self.global_config.default_system_prompt() if callable(self.global_config.default_system_prompt) else self.global_config.default_system_prompt
        v = (await self.get_str("SYSTEM_PROMPT", default)) or default
        return str(v).strip()

    async def context_messages(self) -> int:
        return await self.get_int("CONTEXT_MESSAGES", 180)

    async def context_token_limit(self) -> int:
        return await self.get_int("CONTEXT_TOKEN_LIMIT", 12000)

    # Summary management

    async def summary_enabled(self) -> bool:
        return await self.get_bool("SUMMARY_ENABLED", False)

    #async def context_summary_target_tokens(self) -> int:
    #    return await self.get_int("CONTEXT_SUMMARY_TARGET_TOKENS", 800)
   
    async def summary_target_max_tokens(self) -> int:
        return await self.get_int("SUMMARY_TARGET_MAX_TOKENS", 800) #650

    async def summary_trigger_dropped_min_messages(self) -> int:
        return await self.get_int("SUMMARY_TRIGGER_DROPPED_MIN_MESSAGES", 40)
    
    async def summary_batch_min_messages(self) -> int:
        return await self.get_int("SUMMARY_BATCH_MIN_MESSAGES", 30) #15
    
    async def summary_batch_max_messages(self) -> int:
        return await self.get_int("SUMMARY_BATCH_MAX_MESSAGES", 60)
    
    async def summary_batch_max_chars(self) -> int:
        return await self.get_int("SUMMARY_BATCH_MAX_CHARS", 12000)
    
    async def summary_min_interval_seconds(self) -> int:
        return await self.get_int("SUMMARY_MIN_INTERVAL_SECONDS", 600)
    
    async def summary_max_loops(self) -> int:
        return await self.get_int("SUMMARY_MAX_LOOPS", 5)

    # Memory management

    async def memory_newest(self) -> int:
        return await self.get_int("MEMORY_NEWEST", 10)
    async def memory_oldest(self) -> int:
        return await self.get_int("MEMORY_OLDEST", 10)
    async def memory_random(self) -> int:
        return await self.get_int("MEMORY_RANDOM", 10)

    # Other convenience getters

    async def allow_name_prefix(self) -> bool:
        return True
    
    async def callie_name(self) -> str:
        #default = self.global_config.default_system_prompt() if callable(self.global_config.default_system_prompt) else self.global_config.default_system_prompt
        v = (await self.get_str("CALLIE_NAME", "Callie")) or "Callie"
        return str(v).strip()
    
    async def callie_aliases(self) -> List[str]:
        raw = (await self.get_str("CALLIE_ALIASES", "Callie,Calliope,Callie Two,Callie Echo,Secunda")) or "Callie,Calliope,Callie Two,Callie Echo,Secunda"
        return [p.strip() for p in raw.split(",") if p.strip()]

    async def ignore_default_minutes(self) -> int:
        return await self.get_int("IGNORE_DEFAULT_MINUTES", 15)

    
    
