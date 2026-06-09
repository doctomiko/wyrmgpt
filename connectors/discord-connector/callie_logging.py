"""Central logging setup for Callie Connector.

Goals:
- Lowest-layer safe: no Store/DB dependencies (stdlib + optional python-dotenv).
- Single source of truth for LOG_LEVEL / LOG_SQL_EVERY_MESSAGE.
- Other modules can import get_logger() without side effects.
- Entrypoint (main.py) calls setup_logging() once where logging used to live.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional, Tuple

try:
    # main.py already calls load_dotenv(), but this keeps logging usable in tests/tools.
    from dotenv import load_dotenv  # type: ignore
except Exception:  # pragma: no cover
    load_dotenv = None  # type: ignore


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or not str(v).strip():
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class CallieLoggingSettings:
    log_level: str = "INFO"
    log_sql_every_message: bool = False
    logger_name: str = "callie"

    @property
    def level_value(self) -> int:
        return getattr(logging, self.log_level, logging.INFO)


_configured: bool = False
_settings: CallieLoggingSettings = CallieLoggingSettings()
_logger: logging.Logger = logging.getLogger(_settings.logger_name)
log: logging.Logger = _logger  # convenient module-level logger alias


def setup_logging(logger_name: str = "callie") -> Tuple[logging.Logger, CallieLoggingSettings]:
    """Configure Python logging once and return the shared logger + settings.

    Safe to call multiple times; only the first call configures handlers.
    """
    global _configured, _settings, _logger, log

    if load_dotenv is not None:
        load_dotenv(override=False)

    log_level = (os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper()
    log_sql_every_message = env_bool("LOG_SQL_EVERY_MESSAGE", False)

    _settings = CallieLoggingSettings(
        log_level=log_level,
        log_sql_every_message=log_sql_every_message,
        logger_name=logger_name,
    )
    _logger = logging.getLogger(logger_name)
    log = _logger  # keep alias synced

    if not _configured:
        logging.basicConfig(
            level=_settings.level_value,
            format="%(asctime)s | %(levelname)s | %(message)s",
        )
        _configured = True
    else:
        # If something else configured logging first, still align this logger's level.
        _logger.setLevel(_settings.level_value)

    return _logger, _settings


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger safely. If setup_logging() has not run yet, this still returns a usable logger."""
    if name is None:
        return _logger
    return logging.getLogger(name)
def get_settings() -> CallieLoggingSettings:
    """Return last-loaded settings (defaults until setup_logging() runs)."""
    return _settings


def should_log_sql_every_message() -> bool:
    return _settings.log_sql_every_message