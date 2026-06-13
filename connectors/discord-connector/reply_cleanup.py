from __future__ import annotations

import re
from typing import Iterable, List


_SPACE_RE = re.compile(r"\s+")


def _norm_name(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def reply_prefix_candidates(*names: str) -> List[str]:
    """Return useful speaker names for conservative reply-prefix cleanup."""
    candidates: List[str] = []
    seen: set[str] = set()

    for raw in names:
        name = _norm_name(raw)
        if not name:
            continue

        variants = {name}
        quote_stripped = name.replace('"', "").replace("'", "")
        variants.add(_norm_name(quote_stripped))

        first = name.split(" ", 1)[0].strip()
        if len(first) >= 3:
            variants.add(first)

        for variant in variants:
            if len(variant) < 3:
                continue
            key = variant.casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(variant)

    candidates.sort(key=len, reverse=True)
    return candidates


def strip_obvious_reply_prefix(reply: str, names: Iterable[str]) -> str:
    """
    Remove a leading "Name:" or "Name," when Discord's reply reference already
    makes the recipient obvious.
    """
    text = str(reply or "")
    leading = text[: len(text) - len(text.lstrip())]
    body = text.lstrip()

    for name in reply_prefix_candidates(*names):
        pattern = re.compile(rf"^{re.escape(name)}\s*[:,]\s+", re.IGNORECASE)
        match = pattern.match(body)
        if not match:
            continue
        stripped = body[match.end() :].lstrip()
        if stripped:
            return leading + stripped

    return text
