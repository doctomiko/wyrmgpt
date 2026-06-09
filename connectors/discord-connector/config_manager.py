from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional, Tuple

from guild_config import GuildConfig
from callie_store import Store
from global_config import GlobalConfig

# Module-level singleton Store instance
#CONFIG_MGR: Optional["ConfigManager"] # = None
#
#def init_config_manager(store: "Store", config: GlobalConfig) -> "ConfigManager":
#    global CONFIG_MGR
#    if CONFIG_MGR is None:
#        # Initialize module-level ConfigManager with the provided store and config.
#        CONFIG_MGR = ConfigManager(store, config)
#    return CONFIG_MGR

@dataclass
class ConfigManager:
    """
    Owns GlobalConfig and per-guild GuildConfig instances.

    Preventing bleedover rule:
      - GuildConfig objects are cached by guild_id.
      - In single-tenant mode, a single GuildConfig(guild_id=0) is used.
    """

    def __new__(cls, *args, **kwargs):
        if cls._singleton is not None:
            return cls._singleton
        cls._singleton = super(ConfigManager, cls).__new__(cls)
        return cls._singleton

    _singleton: ClassVar[Optional["ConfigManager"]] = None

    store: "Store"
    global_config: GlobalConfig
    _guild_configs: Dict[int, GuildConfig] = field(default_factory=dict)
    #_guild_cache: Dict[int, GuildConfig] = field(default_factory=dict)

    # TODO refactor to prevent passing in a guild_id directly.
    def _get_for_guild_id(self, guild_id: Optional[int]) -> GuildConfig:
        """
        Get GuildConfig for a guild id.
        DO NOT CALL THIS METHOD DIRECTLY FROM MESSAGE/INTERACTION HANDLERS.
        Use get_for_message() or get_for_interaction() instead.
        """
        gid = int(guild_id or 0)

        # Single-tenant: reuse guild_id=0 config
        if not self.global_config.multi_tenant:
            if 0 not in self._guild_configs:
                self._guild_configs[0] = GuildConfig(
                    store=self.store,
                    guild_id=0,
                    global_config=self.global_config,
                )
            return self._guild_configs[0]

        # Multi-tenant: cached per guild id
        cfg = self._guild_configs.get(gid)
        if cfg is not None:
            return cfg

        # TODO use the static loaders on GuildConfig since they have spoofing protections.
        cfg = GuildConfig(
            store=self.store,
            guild_id=gid,
            global_config=self.global_config,
        )
        self._guild_configs[gid] = cfg
        return cfg

    def invalidate_guild(self, guild_id: Optional[int]) -> None:
        """
        Drop cached GuildConfig for a guild.

        Call this after config changes (config_set, config_import_env, etc.)
        so the next access re-reads settings cleanly.
        """
        gid = int(guild_id or 0)
        self._guild_configs.pop(gid, None)

    def clear_all(self) -> None:
        """
        Drop ALL cached GuildConfig instances.
        """
        self._guild_configs.clear()

    #def purge(self, guild_id: int) -> None:
    #    self._guild_cache.pop(int(guild_id), None)

    #def purge_all(self) -> None:
    #    self._guild_cache.clear()

    #def _get_or_create(self, guild_id: int) -> GuildConfig:
    #    gid = int(guild_id)
    #    cfg = self._guild_cache.get(gid)
    #    if cfg is None:
    #        cfg = GuildConfig(store=self.store, guild_id=gid, multi_tenant=self.global_config.multi_tenant)
    #        # In single-tenant mode, we snapshot env defaults once into the instance so every call path is consistent.
    #        cfg.configure_from_env_if_single_tenant()
    #        self._guild_cache[gid] = cfg
    #    return cfg

    def check_guild_for_message(self, message: Any) -> Tuple[bool, str]:
        guild_id = getattr(message, "guild", 0)
        if guild_id == 0:
            return False, "No guild context (DMs not supported)."
        # We do not care about the guild in single-tenant mode.
        # It will always be valid.
        if not self.global_config.multi_tenant:
            return True, "Single tenant mode: guild check bypassed."
        cfg = self._get_for_guild_id(guild_id)
        check = cfg.assert_guild_id(guild_id, throw=False)
        if check:
            return True, f"Guild ID is valid. guild_id={guild_id}"
        return False, "Guild ID is invalid. guild_id={guild_id}"

    def check_guild(self, msg_or_interaction: Any, guild_required: Optional[bool] = True) -> Optional[GuildConfig] | None:
        """
        Get message or interaction for a guild ID, asserting guild context if required.
        0 guild ID is used for DMs or no guild context.
        For the message or interaction provided:
        0 guild ID is always invalid if guild_required is True.
        For the GuildConfig returned:
        0 guild ID is always invalid in multi-tenant mode if guild_required is True.
        0 guild ID is valid in multi-tenant mode if guild_required is False.
        0 guild ID is only valid in single-tenant mode.
        """
        guild = msg_or_interaction.guild 
        # This version didn't work!
        #getattr(message, "guild", None)
        gid = guild.id if guild is not None else 0 # int(getattr(guild, "id", guild))
        if not guild_required and gid == 0:
            return None # no guild context
        if guild_required and gid == 0:
            raise RuntimeError("No guild context for message (DMs not supported).")
        cfg = self._get_for_guild_id(gid)
        cfg.assert_guild_id(gid, throw=True)
        return cfg

    #def get_for_interaction(self, interaction: Any) -> GuildConfig:
    #    guild = getattr(interaction, "guild", None)
    #    if guild is None or getattr(guild, "id", None) is None:
    #        raise RuntimeError("No guild context for interaction (DMs not supported).")
    #    gid = int(guild.id)
    #    cfg = self._get_for_guild_id(gid)
    #    cfg.assert_guild_id(gid, throw=True)
    #    return cfg
