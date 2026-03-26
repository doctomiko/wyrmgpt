import re
from typing import Iterable

# House dialect:
# - underline uses __text__
# - bold uses **text**
# When rendering to HTML (if/when), convert __underline__ -> <u>underline</u>

_URL_RE = re.compile(r'(?i)\bhttps?://[^\s<>()]+\b')
_ANGLE_AUTOLINK_URL_RE = re.compile(r'(?i)<+\s*(https?://[^\s<>()]+)\s*>+')
# Intentionally do NOT autolink bare host/path strings like "example.com".
# House policy is conservative: only explicit http/https URLs become clickable links.

def _normalize_existing_autolinks(text: str) -> str:
    if not text:
        return text
    # Collapse any malformed <<https://...>> style sequences to one markdown autolink.
    return _ANGLE_AUTOLINK_URL_RE.sub(lambda m: f"<{m.group(1)}>", text)


def wrap_text(
        text: str, 
        bold: bool, 
        italic: bool, 
        underline: bool,
        strike: bool,
        spoiler: bool,
) -> str:
    if not text:
        return ''

    if bold and underline:
        return f"__**{text}**__"
    if bold and italic:
        return f"***{text}***"
    if bold:
        return f"**{text}**"
    if italic:
        return f"*{text}*"
    if underline:
        return f"__{text}__"
    if strike:
        return f"~~{text}~~"
    if spoiler:
        return f"||{text}||"
    return text

def apply_house_markdown_normalization(text: str) -> str:
    """
    Normalizes markdown output to our house dialect:
    - Avoid __bold__ usage (convert to **bold** if you detect it in sources you control)
    - Optionally run other normalizations later
    """
    # If any internal generators accidentally emit __bold__ intending bold,
    # you can convert obvious cases. This is conservative: it only converts
    # pairs of __...__ that do NOT look like underline tags you deliberately placed.
    # If you want zero ambiguity, remove this and rely on generators being fixed.
    text = _convert_double_underscore_to_bold_if_marked(text)
    return text


def autolink_text(text: str) -> str:
    """
    Autolink only explicit http/https URLs.
    Uses markdown autolink form: <https://...>.
    Avoids double-wrapping content that is already inside angle-bracket autolinks.
    """
    if not text:
        return text

    text = _normalize_existing_autolinks(text)
    parts = re.split(r"(<[^>\n]+>)", text)
    for i, part in enumerate(parts):
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            continue
        parts[i] = _URL_RE.sub(lambda m: f"<{m.group(0)}>", part)

    return _normalize_existing_autolinks("".join(parts))


def extract_explicit_urls(text: str) -> list[str]:
    """
    Return explicit http/https URLs found in raw text.
    Conservative on purpose: this is for auto-ingest, not autolinking.
    """
    if not text:
        return []

    out: list[str] = []
    seen: set[str] = set()

    for m in _URL_RE.finditer(text):
        url = (m.group(0) or "").strip()

        # Trim common trailing punctuation from prose/chat.
        url = url.rstrip('.,;:!?)\\]}>\'"')

        if not url:
            continue
        if url in seen:
            continue

        seen.add(url)
        out.append(url)

    return out


def underline(text: str) -> str:
    # House underline marker
    return f"__{text}__"


def bold(text: str) -> str:
    return f"**{text}**"


def italics(text: str) -> str:
    return f"*{text}*"


def italics_alt(text: str) -> str:
    return f"_{text}_"


def _convert_double_underscore_to_bold_if_marked(text: str) -> str:
    """
    Optional: only convert patterns that are explicitly marked as bold by our generators.
    If you don't have such markers, leave this off.
    """
    return text