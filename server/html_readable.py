from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Comment, NavigableString, Tag


_BLOCK_TAGS = {
    "article", "section", "main", "div", "p", "ul", "ol", "li", "blockquote",
    "pre", "table", "thead", "tbody", "tr", "td", "th", "figure", "figcaption",
    "details", "summary", "aside", "nav", "header", "footer", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
}
_DROP_TAGS = {
    "script", "style", "noscript", "svg", "canvas", "iframe", "template",
    "form", "input", "button", "select", "option", "textarea", "label",
}
_STRONG_HINT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".entry-content",
    ".post-content",
    ".article-content",
    ".content",
    ".post-body",
    ".story-body",
    ".article-body",
)
_DROP_CLASS_RX = re.compile(
    r"\b(nav|menu|header|footer|sidebar|aside|toolbar|breadcrumb|breadcrumbs|share|social|related|comments|comment|newsletter|subscribe|signup|login|register|cookie|consent|gdpr|paywall|modal|popup|banner|advert|ads|promo)\b",
    re.I,
)
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_WHITESPACE_RX = re.compile(r"[ \t\xa0]+")
_MULTI_BLANK_RX = re.compile(r"\n{3,}")


@dataclass
class ReadableHtmlResult:
    title: str
    markdown: str
    metadata: dict


def _clean_space(text: str) -> str:
    s = _WHITESPACE_RX.sub(" ", (text or "")).strip()
    return s


def _text_len(node: Tag | None) -> int:
    if node is None:
        return 0
    return len(_clean_space(node.get_text(" ", strip=True)))


def _link_density(node: Tag | None) -> float:
    if node is None:
        return 0.0
    text_len = _text_len(node)
    if text_len <= 0:
        return 0.0
    link_text = sum(_text_len(a) for a in node.find_all("a"))
    return link_text / max(1, text_len)


def _drop_noise(soup: BeautifulSoup) -> None:
    for item in soup.find_all(string=lambda s: isinstance(s, Comment)):
        item.extract()

    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()

    for tag in soup.find_all(True):
        tag_attrs = tag.attrs if isinstance(getattr(tag, "attrs", None), dict) else {}
        attrs = " ".join(
            str(v)
            for k, v in tag_attrs.items()
            if k in {"id", "class", "aria-label", "role", "data-testid", "data-component"}
        )
        style = str(tag_attrs.get("style") or "")
        if tag.name in {"nav", "header", "footer", "aside"}:
            tag.decompose()
            continue
        if tag_attrs.get("hidden") is not None or tag_attrs.get("aria-hidden") == "true":
            tag.decompose()
            continue
        if style and re.search(r"display\s*:\s*none|visibility\s*:\s*hidden", style, re.I):
            tag.decompose()
            continue
        if attrs and _DROP_CLASS_RX.search(attrs):
            if _text_len(tag) < 1200 or _link_density(tag) > 0.4:
                tag.decompose()


def _candidate_score(node: Tag) -> float:
    text_len = _text_len(node)
    if text_len < 200:
        return -1.0
    p_count = len(node.find_all(["p", "li", "blockquote"]))
    heading_count = len(node.find_all(list(_HEADING_TAGS)))
    link_density = _link_density(node)
    penalty = 400.0 * link_density
    bonus = p_count * 40 + heading_count * 60
    if node.name in {"article", "main", "section"}:
        bonus += 120
    return text_len + bonus - penalty


def _select_root(soup: BeautifulSoup) -> Tag | None:
    for selector in _STRONG_HINT_SELECTORS:
        hit = soup.select_one(selector)
        if hit and _text_len(hit) >= 300:
            return hit

    body = soup.body or soup
    candidates: list[tuple[float, Tag]] = []
    for node in body.find_all(_BLOCK_TAGS):
        score = _candidate_score(node)
        if score > 0:
            candidates.append((score, node))
    if not candidates:
        return body
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _node_text(node: Tag) -> str:
    return _clean_space(node.get_text(" ", strip=True))


def _fmt_inline(node: NavigableString | Tag, *, base_url: str | None) -> str:
    if isinstance(node, NavigableString):
        return _clean_space(str(node))
    if not isinstance(node, Tag):
        return ""

    name = node.name.lower()
    inner = " ".join(filter(None, (_fmt_inline(c, base_url=base_url) for c in node.children)))
    inner = _clean_space(inner)

    if name == "br":
        return "\n"
    if name in {"strong", "b"}:
        return f"**{inner}**" if inner else ""
    if name in {"em", "i"}:
        return f"*{inner}*" if inner else ""
    if name == "code":
        return f"`{inner}`" if inner else ""
    if name == "a":
        href = (node.get("href") or "").strip()
        if href and base_url:
            href = urljoin(base_url, href)
        if href and inner:
            return f"[{inner}]({href})"
        if href:
            return href
        return inner
    if name == "img":
        alt = _clean_space(node.get("alt") or "")
        src = (node.get("src") or "").strip()
        if src and base_url:
            src = urljoin(base_url, src)
        if alt and src:
            return f"![{alt}]({src})"
        return alt or src
    return inner


def _emit_block(node: Tag, *, base_url: str | None) -> list[str]:
    out: list[str] = []
    name = node.name.lower()

    if name in _HEADING_TAGS:
        level = int(name[1])
        text = _clean_space(" ".join(filter(None, (_fmt_inline(c, base_url=base_url) for c in node.children))))
        if text:
            out.append(f"{'#' * level} {text}")
        return out

    if name == "p":
        text = _clean_space(" ".join(filter(None, (_fmt_inline(c, base_url=base_url) for c in node.children))))
        if text:
            out.append(text)
        return out

    if name in {"ul", "ol"}:
        index = 1
        for li in node.find_all("li", recursive=False):
            text = _clean_space(" ".join(filter(None, (_fmt_inline(c, base_url=base_url) for c in li.children))))
            if not text:
                continue
            if name == "ol":
                out.append(f"{index}. {text}")
                index += 1
            else:
                out.append(f"- {text}")
        return out

    if name == "blockquote":
        text = _node_text(node)
        if text:
            out.extend(f"> {line}" for line in text.splitlines() if line.strip())
        return out

    if name == "pre":
        text = node.get_text("\n", strip=False).rstrip()
        if text:
            out.append("```\n" + text + "\n```")
        return out

    if name == "hr":
        return ["---"]

    if name == "table":
        rows = []
        for tr in node.find_all("tr"):
            cols = [_node_text(td) for td in tr.find_all(["th", "td"], recursive=False)]
            if any(cols):
                rows.append(cols)
        if rows:
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            head = rows[0]
            sep = ["---"] * width
            out.append("| " + " | ".join(head) + " |")
            out.append("| " + " | ".join(sep) + " |")
            for row in rows[1:]:
                out.append("| " + " | ".join(row) + " |")
        return out

    # Generic container: only emit direct block children; fall back to text if leaf-ish.
    child_blocks = [c for c in node.children if isinstance(c, Tag) and c.name and c.name.lower() in _BLOCK_TAGS]
    if child_blocks:
        for child in child_blocks:
            out.extend(_emit_block(child, base_url=base_url))
        return out

    text = _clean_space(" ".join(filter(None, (_fmt_inline(c, base_url=base_url) for c in node.children))))
    if text:
        out.append(text)
    return out


def _dedupe_adjacent(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    prev = None
    for raw in lines:
        line = (raw or "").rstrip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if prev == line:
            continue
        out.append(line)
        prev = line
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    return out


def extract_readable_html_markdown(
    html: str,
    *,
    base_url: str | None = None,
    fallback_title: str | None = None,
) -> ReadableHtmlResult:
    raw = (html or "").strip()
    if not raw:
        return ReadableHtmlResult(title=(fallback_title or "").strip(), markdown="", metadata={"reason": "empty_html"})

    soup = BeautifulSoup(raw, "html.parser")
    _drop_noise(soup)
    root = _select_root(soup)

    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = _clean_space(og_title.get("content") or "")
    if not title and soup.title and soup.title.string:
        title = _clean_space(soup.title.string)
    if not title:
        title = _clean_space(fallback_title or "")

    lines: list[str] = []
    if root is not None:
        for child in root.children:
            if isinstance(child, Tag):
                lines.extend(_emit_block(child, base_url=base_url))

    lines = _dedupe_adjacent(lines)
    markdown = "\n\n".join(line for line in lines if line is not None).strip()
    markdown = _MULTI_BLANK_RX.sub("\n\n", markdown)

    if title and markdown:
        first_heading = f"# {title}"
        if not markdown.startswith(first_heading):
            markdown = first_heading + "\n\n" + markdown
    elif title and not markdown:
        markdown = f"# {title}".strip()

    metadata = {
        "title": title,
        "base_url": base_url,
        "selected_tag": getattr(root, "name", None),
        "selected_text_chars": _text_len(root),
        "has_headings": bool(root and root.find(list(_HEADING_TAGS))),
        "link_count": len(root.find_all("a")) if root else 0,
        "image_count": len(root.find_all("img")) if root else 0,
    }
    return ReadableHtmlResult(title=title, markdown=markdown, metadata=metadata)
