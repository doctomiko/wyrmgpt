
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Set

#from .config import RetrievalConfig, load_retrieval_config
from .config import QueryConfig, load_query_config

DEFAULT_FILLER_WORDS: Set[str] = {
    "a","an","the","and","or","but","so","if","then","than","because","while","though",
    "to","of","in","on","at","by","for","with","from","as","into","about","over","under",
    "is","are","was","were","be","been","being","do","does","did","have","has","had",
    "i","me","my","mine","we","us","our","you","your","yours","he","him","his","she","her","hers","they","them","their","theirs",
    "it","its","this","that","these","those","there","here",
    "not","no","yes","ok","okay","like","just","really","very","maybe","basically","actually",
    "what","which","who","whom","when","where","why","how",
    "tell","know","about","please","show","explain","give","want","need",
}

WORD_RE = re.compile(r"[A-Za-z0-9_]+(?:[./-][A-Za-z0-9_]+)*")
QUOTE_RE = re.compile(r'("([^"]+)")|(\'([^\']+)\')')

@dataclass
class QueryShape:
    fts_query: str
    kept_phrases: List[str]
    kept_terms: List[str]
    dropped_phrases: List[str]
    original: str


def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _tokenize(s: str) -> List[str]:
    return [m.group(0) for m in WORD_RE.finditer(s or "")]


def _resolve_path(path_str: str) -> list[Path]:
    raw = Path(path_str)
    if raw.is_absolute():
        return [raw]
    return [
        raw,
        Path.cwd() / raw,
        Path(__file__).resolve().parents[1] / raw,  # repo root
    ]


def _parse_filler_words(text: str) -> Set[str]:
    words: Set[str] = set()
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        # allow comma-separated and whitespace-separated
        for part in re.split(r"[,\s]+", s):
            p = part.strip().lower()
            if p:
                words.add(p)
    return words


@lru_cache(maxsize=16)
#def load_filler_words_cached(filepath: str | None = None, fallback_text: str | None = None, cfg: RetrievalConfig | None = None) -> frozenset[str]:
#    cfg = cfg or load_retrieval_config()
def load_filler_words_cached(filepath: str | None = None, fallback_text: str | None = None, cfg: QueryConfig | None = None) -> frozenset[str]:
    cfg = cfg or load_query_config()
    filepath = filepath or cfg.filler_words_file
    fallback_text = fallback_text or cfg.filler_words
    # 1) file wins if present and readable
    if filepath:
        for p in _resolve_path(filepath):
            try:
                if p.exists() and p.is_file():
                    parsed = _parse_filler_words(p.read_text(encoding="utf-8"))
                    if parsed:
                        return frozenset(parsed)
            except Exception:
                pass

    # 2) fallback config string
    parsed = _parse_filler_words(fallback_text)
    if parsed:
        return frozenset(parsed)

    # 3) hardcoded backup
    return frozenset(DEFAULT_FILLER_WORDS)

#def _get_filler_words(cfg: RetrievalConfig) -> Set[str]:
def _get_filler_words(cfg: QueryConfig) -> Set[str]:
    return set(load_filler_words_cached(cfg.filler_words_file or "", cfg.filler_words or ""))


def _is_interesting_token(tok: str, filler_words: Set[str]) -> bool:
    t = tok.lower()
    if t in filler_words:
        return False
    # keep numbers and mixed tokens
    if any(ch.isdigit() for ch in tok):
        return True
    # keep tokens that look like identifiers / filenames / paths
    if any(sep in tok for sep in ("/", "\\", ".", "_", "-")):
        return True
    # keep longer words
    # TODO make the length configurable in QueryConfig
    min_query_word_chars = 3
    return len(tok) >= min_query_word_chars

def _phrase_is_usable(phrase: str, *, max_words: int, max_chars: int, filler_words: Set[str]) -> bool:
    p = _normalize_space(phrase)
    if not p:
        return False
    if len(p) > max_chars:
        return False
    words = _tokenize(p)
    if len(words) > max_words:
        return False
    # phrase must contain at least one interesting token
    return any(_is_interesting_token(w, filler_words) for w in words)

#def shape_fts_query(user_text: str, cfg: RetrievalConfig | None = None) -> QueryShape:
def shape_fts_query(user_text: str, cfg: QueryConfig | None = None) -> QueryShape:
    """
    Build an FTS MATCH query from user input.

    - Short quotes become phrase queries: "foo bar"
    - Long quotes are treated as normal prose (quotes ignored)
    - Stopwords/glue words removed
    - Keeps 'belongs' terms: identifiers, filenames, long-ish words, numbers
    """
    #cfg = cfg or load_retrieval_config()
    cfg = cfg or load_query_config()
    # use cfg.max_terms, cfg.max_phrase_words, cfg.max_phrase_chars
    filler_words = _get_filler_words(cfg)

    original = user_text or ""
    text = _normalize_space(original)

    kept_phrases: List[str] = []
    dropped_phrases: List[str] = []

    # Pull quotes, but only keep them as phrases if they're usable.
    # Either way, we remove the quote wrapper and leave the inner text in the stream
    # so "belongs" terms can still be picked up.
    def _quote_replacer(m: re.Match) -> str:
        phrase = m.group(2) if m.group(2) is not None else (m.group(4) or "")
        phrase_norm = _normalize_space(phrase)
        if _phrase_is_usable(
            phrase_norm,
            max_words=cfg.max_phrase_words,
            max_chars=cfg.max_phrase_chars,
            filler_words=filler_words,
        ):
            kept_phrases.append(phrase_norm)
        else:
            dropped_phrases.append(phrase_norm)
        # return inner text back into the stream (no quotes)
        return " " + phrase_norm + " "

    text_no_quotes = QUOTE_RE.sub(_quote_replacer, text)

    # Tokenize and keep terms
    tokens = _tokenize(text_no_quotes)
    kept_terms: List[str] = []
    seen = set()

    for tok in tokens:
        if not _is_interesting_token(tok, filler_words):
            continue
        key = tok.lower()
        if key in seen:
            continue
        seen.add(key)
        kept_terms.append(tok)
        if len(kept_terms) >= cfg.max_terms:
            break

    # Build MATCH query.
    # In FTS5, space is basically AND. Quotes create phrase queries.
    
    # 6am and tired version that quotes everything
    def _fts_quote(term: str) -> str:
        return f'"{(term or "").replace(chr(34), chr(34) * 2)}"'
    parts: List[str] = []
    for p in kept_phrases:
        parts.append(_fts_quote(p))
    for t in kept_terms:
        parts.append(_fts_quote(t))
    fts_query = " ".join(parts).strip()

    if (False): # complex only uses quotes when needed
        def _fts_quote(term: str) -> str:
            return f'"{(term or "").replace(chr(34), chr(34) * 2)}"'
        parts: List[str] = []
        for p in kept_phrases:
            parts.append(_fts_quote(p))
        for t in kept_terms:
            # Quote any term with punctuation/syntax-y characters so FTS treats it as text.
            # Examples: dual-weilding, ya-basic, foo/bar, x.y, file_name, etc.
            if re.search(r'[^A-Za-z0-9]', t):
                parts.append(_fts_quote(t))
            else:
                parts.append(t)
        fts_query = " ".join(parts).strip()

    if (False): # original that breaks on hyphens
        parts: List[str] = []
        for p in kept_phrases:
            # escape embedded quotes just in case
            parts.append(f'"{p.replace(chr(34), chr(34) * 2)}"')
        parts.extend(kept_terms)
        fts_query = " ".join(parts).strip()

    return QueryShape(
        fts_query=fts_query,
        kept_phrases=kept_phrases,
        kept_terms=kept_terms,
        dropped_phrases=dropped_phrases,
        original=original,
    )