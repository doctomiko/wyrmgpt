from datetime import datetime, timezone
import time
import json
import re
import hashlib
from typing import Iterable, List, Optional

# Time and Date Helpers

def now_epoch() -> int:
    return int(time.time())

def iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def time_str_local(epoch: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(epoch)

def _iso_utc(ts: int) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return str(ts)

def parse_iso_datetime_to_epoch(value: Optional[str], *, is_end: bool = False) -> Optional[int]:
    """Parse an ISO-like date/datetime string to an epoch seconds int (UTC).

    Accepts:
      - YYYY-MM-DD
      - YYYY-MM-DDTHH:MM
      - YYYY-MM-DDTHH:MM:SS
      - Also allows a space instead of 'T'.

    If a date-only value is provided and is_end=True, the time is treated as 23:59:59.
    Otherwise date-only is treated as 00:00:00.

    Returns None if value is None/empty.
    Raises ValueError on invalid input.
    """
    if not value:
        return None
    s = value.strip().replace(" ", "T")
    # Date-only
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s = s + ("T23:59:59" if is_end else "T00:00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp())

def _ts_to_str(ts: int) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return str(ts)

# String Helpers

def _norm_content(s: str) -> str:
    # Keep this conservative to avoid false matches.
    return (s or "").strip()

def normalize_exts(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    for v in values:
        if not v:
            continue
        for part in v.split(","):
            p = part.strip().lower()
            if not p:
                continue
            if not p.startswith("."):
                p = "." + p
            out.append(p)
    return out

def canonical_json(obj) -> str:
    # Stable JSON for hashing / log receipts
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def parse_prefixed_int(s: str, prefix: str) -> Optional[int]:
    """
    This is a string parser for strings used as Discord parameter values.
    It looks for an integer value prefixed by a given string.
    (e.g. M00001 or PT02)
    
    :param s: The string to parse
    :type s: str
    :param prefix: The prefix to look for like "M" or "P"
    :type prefix: str
    :return: The integer value if found, otherwise None
    :rtype: int | None
    """
    s = (s or "").strip()
    if not s.upper().startswith(prefix.upper()):
        return None
    tail = s[len(prefix):].strip()
    if not tail.isdigit():
        return None
    return int(tail)


