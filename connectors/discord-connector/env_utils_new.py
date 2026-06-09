import os
from typing import Any, List, Optional

from callie_logging import log

SENSITIVE_SUBSTRINGS = ("TOKEN", "KEY", "SECRET", "PASSWORD")

def is_sensitive_config_name(name: Optional[str]) -> bool:
    """True if a config/env key name should be treated as sensitive."""
    if not name:
        return False
    up = str(name).upper()
    return any(s in up for s in SENSITIVE_SUBSTRINGS)

def redact_config_value(name: Optional[str], value: Any) -> str:
    """Redact sensitive config values for logs/UI. Never returns the raw value for sensitive keys."""
    if is_sensitive_config_name(name):
        return "<redacted>"
    return repr(value)

def _norm(s: str) -> str:
    return s.strip()

def parse_bool(value: Any, default: bool = False, *, key: Optional[str] = None) -> bool:
    """Parse a bool from a string-ish value."""
    if value is None:
        return default
    v = _norm(str(value)).lower()
    if v in ("",):
        return default
    if v in ("1", "true", "t", "yes", "y", "on"):
        return True
    if v in ("0", "false", "f", "no", "n", "off"):
        return False
    log.warning(
        "Failed to parse bool for key %s from value %s; using default=%r",
        key or "<unknown>",
        redact_config_value(key, value),
        default,
    )
    return default


def parse_int(value: Any, default: int = 0, *, key: Optional[str] = None) -> int:
    if value is None:
        return default
    v = _norm(str(value))
    if v == "":
        return default
    try:
        return int(v)
    except Exception:
        log.warning(
            "Failed to parse int for key %s from value %s; using default=%r",
            key or "<unknown>",
            redact_config_value(key, value),
            default,
        )
        return default

def parse_float(value: Any, default: float = 0.0, *, key: Optional[str] = None) -> float:
    if value is None:
        return default
    v = _norm(str(value))
    if v == "":
        return default
    try:
        return float(v)
    except Exception:
        log.warning(
            "Failed to parse float for key %s from value %s; using default=%r",
            key or "<unknown>",
            redact_config_value(key, value),
            default,
        )
        return default

def parse_csv_ints(value: Any, *, key: Optional[str] = None) -> List[int]:
    if value is None:
        return []
    v = _norm(str(value))
    if not v:
        return []
    out: List[int] = []
    bad: List[str] = []
    for part in v.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(int(p))
        except Exception:
            bad.append(p)
    if bad:
        log.warning(
            "Failed to parse some csv ints for key %s from value %s; dropped=%s",
            key or "<unknown>",
            redact_config_value(key, value),
            bad,
        )
    return out

def env_str(
    key: str,
    default: Optional[str] = None,
    *,
    value_override: Optional[str] = None,
) -> Optional[str]:
    """
    Secure string fetch for configuration values.

    Resolution order:
    1. value_override (typically from DB / GuildConfig)
    2. os.environ[key]
    3. default

    This function NEVER logs values.
    Callers may log using redact_config_value(key, value).
    """

    if value_override is not None:
        return value_override

    v = os.getenv(key)
    if v is not None:
        return v

    return default

#def env_int(key: str, default: int = 0) -> int:
#    return parse_int(os.getenv(key), default, key=key)
def env_int(
    key: str,
    default: int,
    *,
    value_override: Optional[str] = None,
) -> int:
    v = env_str(key, None, value_override=value_override)
    return parse_int(v, default)

# def env_float(key: str, default: float = 0.0) -> float:
#     return parse_float(os.getenv(key), default, key=key)
def env_float(
    key: str,
    default: float,
    *,
    value_override: Optional[str] = None,
) -> float:
    v = env_str(key, None, value_override=value_override)
    return parse_float(v, default)

# def env_bool(key: str, default: bool = False) -> bool:
#     return parse_bool(os.getenv(key), default, key=key)
def env_bool(
    key: str,
    default: bool,
    *,
    value_override: Optional[str] = None,
) -> bool:
    v = env_str(key, None, value_override=value_override)
    return parse_bool(v, default)

# def env_csv_ints(key: str) -> List[int]:
#    return parse_csv_ints(os.getenv(key), key=key)
def env_csv_ints(
    key: str,
    *,
    value_override: Optional[str] = None,
) -> List[int]:
    v = env_str(key, "", value_override=value_override)
    return parse_csv_ints(v)

