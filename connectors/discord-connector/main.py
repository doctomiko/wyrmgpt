import os
import asyncio
from dataclasses import dataclass
#import time
import socket
from typing import Callable, Optional, List, Tuple, Dict, Awaitable

#import base64

#import discord 
#from discord import app_commands
import aiohttp
from dotenv import load_dotenv
#import random
#import httpx
#import traceback
#import re
from collections import deque
import threading
import hashlib

# The basics almost every module needs
from callie_bot import CallieBot
from callie_logging import log, setup_logging

from global_config import GlobalConfig
from callie_store import Store
#from guild_config import GuildConfig
from config_manager import ConfigManager

# BEGIN SECTION ------------ SANITY BANNER ---------------
# Runs at start of program to help verify which main.py is being used.
# Can possibly be replaced someday with a more robust versioning system.
# For example we could be calling the repo branch hash.

_MAINPY_SANITY_TAG = "CALLIE_MAINPY_SANITY_2025-12-28A"
_MAINPY_SANITY_ENV = "CALLIE_MAINPY_VERSION"

def _emit_mainpy_sanity() -> None:
    try:
        env_val = os.getenv(_MAINPY_SANITY_ENV, "")
        with open(__file__, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()
        print(f"[MainPySanity] tag={_MAINPY_SANITY_TAG} {_MAINPY_SANITY_ENV}={env_val!r} sha256={sha256}", flush=True)
    except Exception as e:
        # Never let sanity logging break startup.
        try:
            print(f"[MainPySanity] tag={_MAINPY_SANITY_TAG} FAILED: {e!r}", flush=True)
        except Exception:
            pass

_emit_mainpy_sanity()

# END SECTION ------------ SANITY BANNER ---------------

# Load the .env file into memory
# maybe not needed anymore?
#load_dotenv()

# BEGIN SECTION ------------ SETUP LOGGING ---------------

# Step 2: Setup logging
log, _log_settings = setup_logging("callie")
log.info("Logging initialized. Level=%s", log.getEffectiveLevel())

# END SECTION ------------ SETUP LOGGING ---------------

# Initialize the global Store, GlobalConfig, and ConfigManager
global_config: GlobalConfig = GlobalConfig()
# By default the Store will connect to the DB when __init__ is called
store: "Store" = Store(global_config)
config_mgr = ConfigManager(store, global_config)
# Add the bot commands - DO NOT CALL THEM UNTIL STORE OPENS
from bot_commands import callie_group 
# these are sub-groups and do not need import here
# memory_group, suggestions_group, admin_group
# Make the actual bot instance
bot = CallieBot(store)
bot.tree.add_command(callie_group)

async def main():
    await store.ensure_open()
    try:
        # Start the bot with reconnect logic
        await bot.run_main_loop(global_config.discord_token)
        #await bot.start(global_config.discord_token)
    finally:
        # 🔻 THIS IS THE IMPORTANT PART 🔻
        await bot.close()
        await store.close()
if __name__ == "__main__":
    asyncio.run(main())