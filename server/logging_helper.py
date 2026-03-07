import logging
from typing import Any

_log = logging.getLogger("wyrmgpt")

# TODO add a logging config to config.py and read value to enable/disable debug logging

def log_debug(msg: str, *args: Any, **kwargs: Any) -> None:
    try:
        _log.debug(msg, *args, **kwargs)
    except Exception:
        # last-resort fallback
        try:
            print("DEBUG:", msg % args if args else msg)
        except Exception:
            print("DEBUG:", msg, args, kwargs)

def log_info(msg: str, *args: Any, **kwargs: Any) -> None:
    try:
        _log.info(msg, *args, **kwargs)
    except Exception:
        try:
            print("INFO:", msg % args if args else msg)
        except Exception:
            print("INFO:", msg, args, kwargs)

def log_warn(msg: str, *args: Any, **kwargs: Any) -> None:
    try:
        _log.warning(msg, *args, **kwargs)
    except Exception:
        try:
            print("WARN:", msg % args if args else msg)
        except Exception:
            print("WARN:", msg, args, kwargs)

def log_error(msg: str, *args: Any, **kwargs: Any) -> None:
    try:
        _log.error(msg, *args, **kwargs)
    except Exception:
        try:
            print("ERROR:", msg % args if args else msg)
        except Exception:
            print("ERROR:", msg, args, kwargs)