from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# -----------------------------
# Tunables (adjust later)
# -----------------------------

# Bigger chunks (hybrid soon). Characters are a fine proxy for now.
PROSE_CHUNK_TARGET_CHARS = 6000
PROSE_CHUNK_HARD_MAX_CHARS = 9000

CODE_CHUNK_TARGET_CHARS = 5200
CODE_CHUNK_HARD_MAX_CHARS = 7800

TRANSCRIPT_CHUNK_TARGET_CHARS = 2200
TRANSCRIPT_CHUNK_HARD_MAX_CHARS = 3200

# When a trailing chunk is tiny, merge it into the previous chunk if it fits.
TRAILING_MERGE_MIN_CHARS = 800

# File extensions that we treat as code.
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".cs",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".swift",
    ".sh",
    ".ps1",
    ".bat",
    ".sql",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
}

_MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdx"}


# -----------------------------
# Public helpers
# -----------------------------

def is_probably_code(path: Path, mime_type: Optional[str]) -> bool:
    ext = path.suffix.lower()
    if ext in CODE_EXTENSIONS:
        return True
    # If it's "text/*" but not a known code ext, we treat as prose by default.
    # (You can refine this later if you want to detect JSON, etc.)
    return False


def chunk_text_for_file(text: str, *, path: Path, mime_type: Optional[str]) -> List[str]:
    ext = path.suffix.lower()
    if ext in _MARKDOWN_EXTENSIONS:
        return chunk_markdown(text)
    if is_probably_code(path, mime_type):
        # Use ext as hint for code chunking strategy.
        return chunk_code(text, lang_hint=ext.lstrip("."))
    return chunk_prose(text)


# -----------------------------
# Core chunkers
# -----------------------------

def chunk_markdown(text: str) -> List[str]:
    """
    Split markdown by headings first, while respecting fenced code blocks as atomic blocks.
    Then within sections, prefer paragraph boundaries, then line breaks, then sentence-ish breaks.
    """
    text = _normalize_newlines(text)

    # Tokenize into alternating: normal text vs fenced code blocks.
    parts = _split_markdown_fences(text)

    # For non-code-fence parts: split by headings into sections.
    sections: List[str] = []
    for kind, payload in parts:
        if kind == "fence":
            sections.append(payload.strip())
        else:
            sections.extend(_split_markdown_by_headings(payload))

    # Now pack sections into chunks with size caps.
    chunks = _pack_blocks(
        blocks=[s for s in sections if s.strip()],
        target=PROSE_CHUNK_TARGET_CHARS,
        hard_max=PROSE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_prose_block,
        joiner="\n\n",
    )
    return _merge_tiny_trailing(chunks, hard_max=PROSE_CHUNK_HARD_MAX_CHARS)


def chunk_prose(text: str) -> List[str]:
    """
    Prose chunking: prefer paragraph boundaries (double newline),
    then line breaks, then sentence-ish boundaries, then whitespace.
    """
    text = _normalize_newlines(text).strip()
    if not text:
        return []

    # Start with paragraphs
    blocks = text.split("\n\n")
    chunks = _pack_blocks(
        blocks=[b.strip() for b in blocks if b.strip()],
        target=PROSE_CHUNK_TARGET_CHARS,
        hard_max=PROSE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_prose_block,
        joiner="\n\n",
    )
    return _merge_tiny_trailing(chunks, hard_max=PROSE_CHUNK_HARD_MAX_CHARS)


def chunk_code(text: str, *, lang_hint: str = "") -> List[str]:
    """
    Code chunking: try hard not to split inside functions/classes.
    - Python: AST-based splits (robust)
    - JS/TS: heuristic (brace depth + function boundaries)
    Fallback: blank-line packing with hard max.
    """
    text = _normalize_newlines(text).rstrip("\n")
    if not text:
        return []

    lang_hint = (lang_hint or "").lower()

    if lang_hint == "py" or lang_hint == "python":
        py_chunks = _chunk_python_ast(text)
        if py_chunks:
            return _merge_tiny_trailing(py_chunks, hard_max=CODE_CHUNK_HARD_MAX_CHARS)

    if lang_hint in {"js", "jsx", "ts", "tsx"}:
        js_chunks = _chunk_js_heuristic(text)
        if js_chunks:
            return _merge_tiny_trailing(js_chunks, hard_max=CODE_CHUNK_HARD_MAX_CHARS)

    # Fallback: pack by blank-line blocks, then lines.
    blocks = _split_code_into_blocks(text)
    chunks = _pack_blocks(
        blocks=blocks,
        target=CODE_CHUNK_TARGET_CHARS,
        hard_max=CODE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_code_block,
        joiner="\n\n",
    )
    return _merge_tiny_trailing(chunks, hard_max=CODE_CHUNK_HARD_MAX_CHARS)


def chunk_transcript(text: str) -> List[str]:
    """
    Conversation transcripts are rendered as repeated message blocks separated by blank lines.
    Keep these chunks materially smaller than generic prose so retrieval lands near the
    actual turn that matched, rather than swallowing half the conversation.
    """
    text = _normalize_newlines(text).strip()
    if not text:
        return []

    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    chunks = _pack_blocks(
        blocks=blocks,
        target=TRANSCRIPT_CHUNK_TARGET_CHARS,
        hard_max=TRANSCRIPT_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_prose_block,
        joiner="\n\n",
    )
    return _merge_tiny_trailing(chunks, hard_max=TRANSCRIPT_CHUNK_HARD_MAX_CHARS)

# -----------------------------
# Markdown helpers
# -----------------------------

_FENCE_RE = re.compile(r"(^```.*?$)(.*?)(^```[ \t]*$)", re.MULTILINE | re.DOTALL)

def _split_markdown_fences(text: str) -> List[Tuple[str, str]]:
    """
    Returns list of ("text"|"fence", payload). Fence payload includes the ``` lines.
    """
    parts: List[Tuple[str, str]] = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        start, end = m.span()
        if start > pos:
            parts.append(("text", text[pos:start]))
        fence = (m.group(1) + m.group(2) + m.group(3)).strip("\n")
        parts.append(("fence", fence))
        pos = end
    if pos < len(text):
        parts.append(("text", text[pos:]))
    return parts


_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)

def _split_markdown_by_headings(text: str) -> List[str]:
    """
    Splits markdown into sections that start at a heading and include content until next heading.
    If there are no headings, returns [text].
    """
    text = text.strip()
    if not text:
        return []

    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [text]

    sections: List[str] = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)
    return sections


# -----------------------------
# Python AST chunking
# -----------------------------

def _chunk_python_ast(text: str) -> List[str]:
    try:
        tree = ast.parse(text)
    except Exception:
        return []

    lines = text.split("\n")

    # Collect top-level def/class nodes.
    spans: List[Tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            lineno = getattr(node, "lineno", None)
            end_lineno = getattr(node, "end_lineno", None)
            if lineno and end_lineno and end_lineno >= lineno:
                spans.append((lineno, end_lineno))

    if not spans:
        return []

    # Add any "preamble" before first def/class (imports, constants, etc.)
    spans.sort()
    chunks: List[str] = []
    first_start = spans[0][0]
    if first_start > 1:
        pre = "\n".join(lines[0:first_start - 1]).strip()
        if pre:
            chunks.extend(_pack_code_text(pre))

    # Each def/class becomes a block; if too large, pack internally by lines.
    for (s, e) in spans:
        block = "\n".join(lines[s - 1:e]).rstrip()
        if len(block) <= CODE_CHUNK_HARD_MAX_CHARS:
            chunks.append(block)
        else:
            chunks.extend(_pack_code_text(block))

    # Tail after last def/class
    last_end = spans[-1][1]
    if last_end < len(lines):
        tail = "\n".join(lines[last_end:]).strip()
        if tail:
            chunks.extend(_pack_code_text(tail))

    # Finally, pack adjacent blocks if they’re small to approach target.
    return _pack_blocks(
        blocks=[c for c in chunks if c.strip()],
        target=CODE_CHUNK_TARGET_CHARS,
        hard_max=CODE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_code_block,
        joiner="\n\n",
    )


def _pack_code_text(text: str) -> List[str]:
    # Pack by lines, hard-splitting huge lines if needed.
    return _pack_blocks(
        blocks=text.split("\n"),
        target=CODE_CHUNK_TARGET_CHARS,
        hard_max=CODE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_code_line,
        joiner="\n",
    )


# -----------------------------
# JS/TS heuristic chunking
# -----------------------------

_JS_FUNC_RE = re.compile(
    r"""^\s*(export\s+)?(async\s+)?function\s+\w+\s*\(|^\s*(export\s+)?(const|let|var)\s+\w+\s*=\s*(async\s*)?\(""",
    re.MULTILINE,
)

def _chunk_js_heuristic(text: str) -> List[str]:
    lines = text.split("\n")

    # Identify candidate start lines for top-level functions (brace depth == 0)
    starts: List[int] = []
    depth = 0
    in_block_comment = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        # crude comment handling to avoid counting braces inside block comments
        if "/*" in stripped:
            in_block_comment = True
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue

        if depth == 0 and _JS_FUNC_RE.search(line):
            starts.append(i)

        # update brace depth (very rough; good enough for top-level splits)
        depth += line.count("{") - line.count("}")

    if not starts:
        return []

    chunks: List[str] = []

    # preamble
    if starts[0] > 0:
        pre = "\n".join(lines[:starts[0]]).strip()
        if pre:
            chunks.extend(_pack_code_text(pre))

    # Each function block = from start to next start at depth 0-ish.
    for idx, s in enumerate(starts):
        e = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        block = "\n".join(lines[s:e]).rstrip()
        if len(block) <= CODE_CHUNK_HARD_MAX_CHARS:
            chunks.append(block)
        else:
            chunks.extend(_pack_code_text(block))

    return _pack_blocks(
        blocks=[c for c in chunks if c.strip()],
        target=CODE_CHUNK_TARGET_CHARS,
        hard_max=CODE_CHUNK_HARD_MAX_CHARS,
        splitter=_fallback_split_code_block,
        joiner="\n\n",
    )


# -----------------------------
# Packing + fallback splitting
# -----------------------------

def _pack_blocks(
    *,
    blocks: List[str],
    target: int,
    hard_max: int,
    splitter,
    joiner: str,
) -> List[str]:
    """
    Packs blocks into chunks under hard_max, aiming for target.
    If a block is > hard_max, uses splitter(block) to sub-split it.
    """
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if current:
            joined = joiner.join(current).strip()
            if joined:
                chunks.append(joined)
        current = []
        current_len = 0

    def add_piece(piece: str) -> None:
        nonlocal current_len
        piece = piece.rstrip()
        if not piece:
            return
        piece_len = len(piece)
        # If current chunk would exceed target, flush first (soft boundary).
        if current_len and current_len + len(joiner) + piece_len > target:
            flush()
        # If piece still doesn't fit hard max with current, flush and add it alone.
        if current_len and current_len + len(joiner) + piece_len > hard_max:
            flush()
        current.append(piece)
        current_len += piece_len + (len(joiner) if len(current) > 1 else 0)

    for block in blocks:
        block = block.rstrip()
        if not block:
            continue

        if len(block) > hard_max:
            subs = splitter(block, hard_max)
            for sub in subs:
                add_piece(sub)
            continue

        add_piece(block)

    flush()
    return [c for c in chunks if c.strip()]


def _fallback_split_prose_block(block: str, hard_max: int) -> List[str]:
    # Prefer paragraph -> line -> sentence-ish -> whitespace
    block = block.strip()
    if len(block) <= hard_max:
        return [block]

    # Try double-newline (already a "block" usually), so next: single newline
    if "\n" in block:
        return _split_by_delim(block, "\n", hard_max)

    # Sentence-ish split
    sent = _split_by_sentenceish(block, hard_max)
    if sent:
        return sent

    # Whitespace fallback
    return _split_by_whitespace(block, hard_max)


def _fallback_split_code_block(block: str, hard_max: int) -> List[str]:
    # Prefer blank lines, then lines, then hard slicing.
    block = block.rstrip()
    if len(block) <= hard_max:
        return [block]

    if "\n\n" in block:
        parts = _split_by_delim(block, "\n\n", hard_max)
        if parts:
            return parts

    if "\n" in block:
        return _split_by_delim(block, "\n", hard_max)

    return [block[i:i + hard_max] for i in range(0, len(block), hard_max)]


def _fallback_split_code_line(line: str, hard_max: int) -> List[str]:
    line = line.rstrip("\n")
    if len(line) <= hard_max:
        return [line]
    return [line[i:i + hard_max] for i in range(0, len(line), hard_max)]


def _split_by_delim(text: str, delim: str, hard_max: int) -> List[str]:
    parts = text.split(delim)
    out: List[str] = []
    cur = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        candidate = (cur + (delim if cur else "") + p).strip()
        if cur and len(candidate) > hard_max:
            out.append(cur.strip())
            cur = p
        else:
            cur = candidate
    if cur.strip():
        out.append(cur.strip())

    # If any part is still too big, fallback to whitespace split.
    final: List[str] = []
    for s in out:
        if len(s) > hard_max:
            final.extend(_split_by_whitespace(s, hard_max))
        else:
            final.append(s)
    return final


_SENTENCEISH_RE = re.compile(r"([.?!])\s+(?=[A-Z])")

def _split_by_sentenceish(text: str, hard_max: int) -> List[str]:
    # Split on sentence-ish boundaries, then pack.
    parts: List[str] = []
    last = 0
    for m in _SENTENCEISH_RE.finditer(text):
        end = m.end()
        parts.append(text[last:end].strip())
        last = end
    tail = text[last:].strip()
    if tail:
        parts.append(tail)

    if not parts:
        return []

    return _pack_blocks(
        blocks=[p for p in parts if p],
        target=hard_max,     # when we’re here, we just need to stay under hard_max
        hard_max=hard_max,
        splitter=_fallback_split_prose_block,
        joiner=" ",
    )


def _split_by_whitespace(text: str, hard_max: int) -> List[str]:
    words = text.split()
    out: List[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip() if cur else w
        if cur and len(candidate) > hard_max:
            out.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _split_code_into_blocks(text: str) -> List[str]:
    # Blocks separated by blank lines are nicer for code.
    blocks = [b.rstrip() for b in text.split("\n\n") if b.strip()]
    return blocks if blocks else [text]


def _merge_tiny_trailing(chunks: List[str], *, hard_max: int) -> List[str]:
    if len(chunks) >= 2 and len(chunks[-1]) < TRAILING_MERGE_MIN_CHARS:
        a = chunks[-2]
        b = chunks[-1]
        if len(a) + 2 + len(b) <= hard_max:
            chunks[-2] = (a + "\n\n" + b).rstrip()
            chunks.pop()
    return chunks


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def chunk_text_with_hints(
    text: str,
    *,
    source_kind: str | None = None,
    filename: str | None = None,
    mime_type: str | None = None,
) -> List[str]:
    """
    Chunk text using whatever hints we have.

    - Conversation transcripts get their own smaller chunking strategy.
    - If we have a filename/path, use chunk_text_for_file() (best behavior: code vs md vs prose).
    - Otherwise, pick markdown vs prose vs code using light heuristics.
    """
    text = (text or "").strip()
    if not text:
        return []

    sk = (source_kind or "").lower()

    if sk == "conversation:transcript":
        return chunk_transcript(text)

    # Best case: we have a path hint.
    if filename:
        try:
            p = Path(filename)
            return chunk_text_for_file(text, path=p, mime_type=mime_type)
        except Exception:
            pass

    # Markdown signals
    if re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", text) or "```" in text or re.search(r"\[[^\]]+\]\([^)]+\)", text):
        return chunk_markdown(text)

    # Code-ish source kind signals
    if "code" in sk or "python" in sk or "javascript" in sk or "typescript" in sk:
        lang = ""
        if "python" in sk:
            lang = "py"
        elif "javascript" in sk:
            lang = "js"
        elif "typescript" in sk:
            lang = "ts"
        return chunk_code(text, lang_hint=lang)

    # Lightweight code heuristics
    if re.search(r"(?m)^\s*(def|class)\s+\w+", text) or re.search(r"(?m)^\s*(function\s+\w+|\w+\s*=>)\s*", text):
        return chunk_code(text)

    return chunk_prose(text)

if (False):
    def chunk_text_with_hints(
        text: str,
        *,
        source_kind: str | None = None,
        filename: str | None = None,
        mime_type: str | None = None,
    ) -> List[str]:
        """
        Chunk text using whatever hints we have.

        - If we have a filename/path, use chunk_text_for_file() (best behavior: code vs md vs prose).
        - Otherwise, pick markdown vs prose vs code using light heuristics.
        """
        text = (text or "").strip()
        if not text:
            return []

        # Best case: we have a path hint.
        if filename:
            try:
                p = Path(filename)
                return chunk_text_for_file(text, path=p, mime_type=mime_type)
            except Exception:
                # fall back to heuristics below
                pass

        # Heuristics if no path: decide markdown/code/prose
        # Markdown signals
        if re.search(r"(?m)^\s{0,3}#{1,6}\s+\S", text) or "```" in text or re.search(r"\[[^\]]+\]\([^)]+\)", text):
            return chunk_markdown(text)

        # Code-ish signals
        sk = (source_kind or "").lower()
        if "code" in sk or "python" in sk or "javascript" in sk or "typescript" in sk:
            # try to chunk as code with language hint if we can infer
            lang = ""
            if "python" in sk:
                lang = "py"
            elif "javascript" in sk:
                lang = "js"
            elif "typescript" in sk:
                lang = "ts"
            return chunk_code(text, lang_hint=lang)

        # More code heuristics (lightweight)
        if re.search(r"(?m)^\s*(def|class)\s+\w+", text) or re.search(r"(?m)^\s*(function\s+\w+|\w+\s*=>)\s*", text):
            return chunk_code(text)

        # Default prose
        return chunk_prose(text)