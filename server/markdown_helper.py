import re
from typing import Iterable

# House dialect:
# - underline uses __text__
# - bold uses **text**
# When rendering to HTML (if/when), convert __underline__ -> <u>underline</u>

_URL_RE = re.compile(r'(?i)\bhttps?://[^\s<>()]+\b')
# domain/path without scheme, excluding emails
_HOSTPATH_RE = re.compile(
    r'(?i)\b(?![\w.+-]+@)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9-]{2,})+)(/[^\s<>()]*)?\b'
)

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
    Autolink URLs and domain/path strings.
    Uses markdown autolink form: <https://...>
    """
    if not text:
        return text

    # 1) Wrap explicit URLs
    text = _URL_RE.sub(lambda m: f"<{m.group(0)}>", text)

    # 2) Wrap host/path that isn't already part of an URL autolink
    def repl(m):
        host = m.group(1)
        path = m.group(2) or ""
        # avoid double-wrapping inside <...>
        full = f"{host}{path}"
        # if it's already inside angle brackets, skip
        return f"<https://{full}>"

    # This is intentionally after URL pass; it won’t match inside <http...> due to '<' boundary.
    text = _HOSTPATH_RE.sub(repl, text)

    return text

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