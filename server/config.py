import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import tomllib  # type: ignore # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # Python <3.11, requires 'tomli'
    except ModuleNotFoundError:
        raise ImportError(
            "Neither 'tomllib' nor 'tomli' could be imported. "
            "Install 'tomli' for Python versions earlier than 3.11: pip install tomli"
        )

load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


def _bool_to_str(val: bool) -> str:
    return str(val)


def _str_to_bool(val: str) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return _str_to_bool(v)


def _normalize_csv_set(value: str, allowed: set[str]) -> str:
    raw = str(value or "").replace(" ", ",")
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    kept: list[str] = []
    seen: set[str] = set()
    for p in parts:
        if p in allowed and p not in seen:
            kept.append(p)
            seen.add(p)
    return ",".join(kept)


def _parse_csv_set(value: str, allowed: set[str]) -> set[str]:
    norm = _normalize_csv_set(value, allowed)
    return set(norm.split(",")) if norm else set()


_MISSING = object()
_TOML_CACHE: dict[str, Any] | None = None
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DEFAULT_TOML_PATH = _ROOT / "config.toml"
_DEFAULT_SECRETS_TOML_PATH = _ROOT / "config.secrets.toml"


def _config_toml_path() -> Path:
    raw = os.getenv("WYRMGPT_CONFIG_TOML", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_TOML_PATH


def _secrets_toml_path() -> Path:
    raw = os.getenv("WYRMGPT_SECRETS_TOML", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_SECRETS_TOML_PATH


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def _load_single_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        data = tomllib.load(fh) or {}
    return data if isinstance(data, dict) else {}


def _load_toml_config() -> dict[str, Any]:
    global _TOML_CACHE
    if _TOML_CACHE is not None:
        return _TOML_CACHE

    base_cfg = _load_single_toml(_config_toml_path())
    secrets_cfg = _load_single_toml(_secrets_toml_path())
    _TOML_CACHE = _deep_merge_dicts(base_cfg, secrets_cfg)
    return _TOML_CACHE


def reset_config_cache() -> None:
    global _TOML_CACHE
    _TOML_CACHE = None


def _toml_get(path: tuple[str, ...], default: Any = _MISSING) -> Any:
    node: Any = _load_toml_config()
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _first_toml(*paths: tuple[str, ...], default: Any = _MISSING) -> Any:
    for path in paths:
        value = _toml_get(path, _MISSING)
        if value is not _MISSING:
            return value
    return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _str_to_bool(str(value))


def _cfg_str(*paths: tuple[str, ...], env_name: str, default: str) -> str:
    value = _first_toml(*paths, default=_MISSING)
    if value is not _MISSING:
        return str(value).strip()
    return _env_str(env_name, default)


def _cfg_int(*paths: tuple[str, ...], env_name: str, default: int) -> int:
    value = _first_toml(*paths, default=_MISSING)
    if value is not _MISSING:
        try:
            return int(value)
        except Exception:
            return default
    return _env_int(env_name, default)


def _cfg_float(*paths: tuple[str, ...], env_name: str, default: float) -> float:
    value = _first_toml(*paths, default=_MISSING)
    if value is not _MISSING:
        try:
            return float(value)
        except Exception:
            return default
    return _env_float(env_name, default)


def _cfg_bool(*paths: tuple[str, ...], env_name: str, default: bool) -> bool:
    value = _first_toml(*paths, default=_MISSING)
    if value is not _MISSING:
        return _coerce_bool(value, default)
    return _env_bool(env_name, default)


def _cfg_csv_set(*paths: tuple[str, ...], env_name: str, default: str, allowed: set[str]) -> str:
    value = _first_toml(*paths, default=_MISSING)
    if value is not _MISSING:
        if isinstance(value, (list, tuple, set)):
            raw = ",".join(str(x) for x in value)
        else:
            raw = str(value)
        return _normalize_csv_set(raw, allowed)
    return _normalize_csv_set(_env_str(env_name, default), allowed)


@dataclass(frozen=True)
class CoreConfig:
    system_prompt_file: str = ".\\prompts\\_default_system_prompt.txt"
    default_system_prompt: str = (
        "You are a helpful assistant operating in a locally hosted scaffolding called "
        "WyrmGPT. Be concise, candid, and technically accurate."
    )
    debug_mode: bool = False
    debug_errors: bool = True
    limit_api_conversations: int = 2000
    limit_api_conversation_messages: int = 5000

CORE_DEFAULTS: CoreConfig = CoreConfig()


@dataclass(frozen=True)
class OpenAIConfig:
    open_ai_apikey: str = ""
    open_ai_model: str = "gpt-5.4"
    summary_model: str = "gpt-5-mini"


OPENAI_DEFAULTS: OpenAIConfig = OpenAIConfig()


@dataclass(frozen=True)
class UIConfig:
    local_timezone: str = "America/Los_Angeles"
    context_preview_limit_min: int = 20
    context_preview_limit_max: int = 200
    min_rag_query_text_len: int = 5
    context_idle_ms: int = 5000
    transcript_idle_ms: int = 120000
    debug_boot: bool = True


UI_DEFAULTS: UIConfig = UIConfig()


@dataclass(frozen=True)
class SummaryConfig:
    summary_max_tokens: int = 800
    summary_conversation_prompt_file: str = ".\\prompts\\_summary_convo_prompt.txt"
    summary_conversation_prompt: str = """
        You are generating a memory summary for internal storage and later retrieval.

        This is not a chat reply.
        Do not ask questions.
        Do not address the user.
        Do not add greetings, closings, advice, commentary, or invitations to continue.

        Read the entire transcript before writing.
        Summarize the conversation as a whole, not just the last exchange.
        Prefer chronological order: early important events first, later developments after.
        If the conversation changes topics, mention the main topic shifts in order.

        Include:
        - the main topics discussed
        - important facts learned
        - decisions made
        - unresolved questions or next steps

        Omit:
        - filler chatter
        - repeated phrasing
        - ornamental wording
        - markdown
        - headings
        - bullets
        - titles
        - labels such as "Summary", "Summary:", or "Summary -"

        Output only the summary text itself.
        Write 2 to 5 short paragraphs in plain text.
        Target roughly 180 to 450 words.
    """
    summary_reduce_threshold_chars: int = 18000
    summary_chunk_target_chars: int = 7000
    summary_chunk_hard_max_chars: int = 10000
    summary_chunk_max_tokens: int = 350


SUMMARY_DEFAULTS: SummaryConfig = SummaryConfig()


@dataclass(frozen=True)
class ContextConfig:
    max_tokens: int = 6000
    memory_pin_limit: int = 250
    history_limit: int = 200
    preview_limit: int = 20
    estimate_model: str = "gpt-5-mini"


CONTEXT_DEFAULTS: ContextConfig = ContextConfig()


@dataclass(frozen=True)
class QueryConfig:
    max_terms: int = 14
    max_phrase_words: int = 8
    max_phrase_chars: int = 64
    filler_words_file: str = ".\\FTS filler+stop words.txt"
    filler_words: str = """
        a, an, the, and, or, but, so, if, then, than, because, while, though,
        to, of, in, on, at, by, for, with, from, as, into, about, over, under,
        is, are, was, were, be, been, being, do, does, did, have, has, had,
        i, me, my, mine, we, us, our, you, your, yours, he, him, his, she, her, hers, they, them, their, theirs,
        it, its, this, that, these, those, there, here,
        not, no, yes, ok, okay, like, just, really, very, maybe, basically, actually,
        what, which, who, whom, when, where, why, how,
        tell, know, about, please, show, explain, give, want, need
        """

    long_query_chars: int = 400
    max_query_slices: int = 6

    llm_expand_enabled: bool = True
    llm_expand_prompt_file: str = ".\\prompts\\_expand_query_prompt.txt"
    llm_expand_min_terms: int = 4
    llm_expand_min_results: int = 3
    llm_expand_max_keywords: int = 10
    llm_expand_model: str = "gpt-5-mini"
    llm_expand_max_tokens: int = 800
QUERY_DEFAULTS: QueryConfig = QueryConfig()


@dataclass(frozen=True)
class RetrievalConfig:
    query_include: str = "CHAT_SUMMARY,FTS,EMBEDDING"
    query_expand_results: str = "FILE,MEMORY,CHAT"
    query_max_full_files: int = 50
    query_max_full_memories: int = 500
    query_max_full_chats: int = 5
    query_expand_min_artifact_hits: int = 2
    query_expand_chat_window_before: int = 1
    query_expand_chat_window_after: int = 1

    query_global_artifacts: bool = True

    retrieval_cache_ttl_sec: float = 180.0
    retrieval_cache_max_entries: int = 64

    query_include_project_conversation_transcripts: bool = True
    query_include_global_conversation_transcripts: bool = True
    query_include_recent_conversation_transcripts: bool = True
    recent_conversation_transcript_limit: int = 40
RETRIEVAL_DEFAULTS: RetrievalConfig = RetrievalConfig()

QUERY_INCLUDE_ALLOWED = {"FILE", "MEMORY", "CHAT", "CHAT_SUMMARY", "FTS", "EMBEDDING"}
QUERY_EXPAND_ALLOWED = {"FILE", "MEMORY", "CHAT"}

if (False):
    def _legacy_query_mode_to_include(mode: str) -> str:
        mode = str(mode or "").strip().upper()
        if mode == "FILES":
            return "FILE"
        if mode == "FTS":
            return "FTS"
        if mode == "VECTOR":
            return "EMBEDDING"
        if mode == "HYBRID":
            return "FTS,EMBEDDING"
        if mode == "ALL":
            return "FILE,FTS,EMBEDDING"
        return RETRIEVAL_DEFAULTS.query_include


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-large"
    dimensions: int = 0
    batch_size: int = 64
    cache_enabled: bool = True
    cache_dir: str = ".\\data\\embedding_cache"


EMBEDDING_DEFAULTS: EmbeddingConfig = EmbeddingConfig()


@dataclass(frozen=True)
class VectorConfig:
    backend: str = "qdrant_local"
    collection_name: str = "wyrmgpt_chunks"
    local_path: str = ".\\data\\qdrant"
    server_url: str = ""
    api_key: str = ""
    distance_metric: str = "cosine"
    search_limit: int = 24
VECTOR_DEFAULTS: VectorConfig = VectorConfig()


@dataclass(frozen=True)
class ImportConfig:
    prose_chunk_target_chars: int = 6000
    prose_chunk_hard_max_chars: int = 9000
    code_chunk_target_chars: int = 5200
    code_chunk_hard_max_chars: int = 7800
    transcript_chunk_target_chars: int = 2200
    transcript_chunk_hard_max_chars: int = 3200
    trailing_merge_min_chars: int = 800

    ensure_files_limit_per_scope: int = 10
    artifact_sidecar_threshold_bytes: int = 500 * 1024
IMPORT_DEFAULTS: ImportConfig = ImportConfig()


@dataclass
class AppConfig:
    search_chat_history: bool = True


APP_DEFAULTS: AppConfig = AppConfig()


class AppConfigKeys:
    search_chat_history: str = "search_chat_history"


APP_KEYS: AppConfigKeys = AppConfigKeys()


def ensure_default_app_settings() -> None:
    from .db import ensure_default_app_setting

    scope_type = "global"
    scope_id = ""
    enable_search_chat_history = _cfg_bool(
        ("app", "search_chat_history"),
        env_name="SEARCH_CHAT_HISTORY_ENABLED",
        default=APP_DEFAULTS.search_chat_history,
    )
    ensure_default_app_setting(
        APP_KEYS.search_chat_history,
        _bool_to_str(enable_search_chat_history),
        scope_type,
        scope_id,
    )


def load_app_config() -> AppConfig:
    from .db import get_app_setting_bool, init_schema

    init_schema()
    ensure_default_app_settings()
    return AppConfig(
        search_chat_history=get_app_setting_bool(APP_KEYS.search_chat_history)
    )


def load_core_config() -> CoreConfig:
    return CoreConfig(
        system_prompt_file=_cfg_str(
            ("core", "system_prompt_file"),
            env_name="SYSTEM_PROMPT_FILE",
            default=CORE_DEFAULTS.system_prompt_file,
        ),
        default_system_prompt=_cfg_str(
            ("core", "default_system_prompt"),
            env_name="SYSTEM_PROMPT",
            default=CORE_DEFAULTS.default_system_prompt,
        ),
        debug_mode=_cfg_bool(
            ("core", "debug_mode"),
            env_name="DEBUG_MODE",
            default=CORE_DEFAULTS.debug_mode,
        ),
        debug_errors=_cfg_bool(
            ("core", "debug_errors"),
            env_name="DEBUG_ERRORS",
            default=CORE_DEFAULTS.debug_errors,
        ),
    )


def load_ui_config() -> UIConfig:
    return UIConfig(
        local_timezone=_cfg_str(
            ("ui", "local_timezone"),
            env_name="LOCAL_TIMEZONE",
            default=_env_str("UI_TIMEZONE", _env_str("APP_TIMEZONE", _env_str("TZ", UI_DEFAULTS.local_timezone))),
        ),
        context_preview_limit_min=_cfg_int(
            ("ui", "context_preview_limit_min"),
            env_name="UI_CONTEXT_PREVIEW_LIMIT_MIN",
            default=UI_DEFAULTS.context_preview_limit_min,
        ),
        context_preview_limit_max=_cfg_int(
            ("ui", "context_preview_limit_max"),
            env_name="UI_CONTEXT_PREVIEW_LIMIT_MAX",
            default=UI_DEFAULTS.context_preview_limit_max,
        ),
        min_rag_query_text_len=_cfg_int(
            ("ui", "min_rag_query_text_len"),
            env_name="UI_MIN_RAG_QUERY_TEXT_LEN",
            default=UI_DEFAULTS.min_rag_query_text_len,
        ),
        context_idle_ms=_cfg_int(
            ("ui", "context_idle_ms"),
            env_name="UI_CONTEXT_IDLE_MS",
            default=UI_DEFAULTS.context_idle_ms,
        ),
        transcript_idle_ms=_cfg_int(
            ("ui", "transcript_idle_ms"),
            env_name="UI_TRANSCRIPT_IDLE_MS",
            default=UI_DEFAULTS.transcript_idle_ms,
        ),
        debug_boot=_cfg_bool(
            ("ui", "debug_boot"),
            env_name="UI_DEBUG_BOOT",
            default=UI_DEFAULTS.debug_boot,
        ),
    )


def load_openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        open_ai_apikey=_cfg_str(
            ("providers", "openai", "api_key"),
            ("openai", "api_key"),
            env_name="OPENAI_API_KEY",
            default=OPENAI_DEFAULTS.open_ai_apikey,
        ),
        open_ai_model=_cfg_str(
            ("providers", "openai", "model"),
            ("openai", "model"),
            env_name="OPENAI_MODEL",
            default=OPENAI_DEFAULTS.open_ai_model,
        ),
        summary_model=_cfg_str(
            ("providers", "openai", "summary_model"),
            ("openai", "summary_model"),
            env_name="SUMMARY_MODEL",
            default=OPENAI_DEFAULTS.summary_model,
        ),
    )


def load_summary_config() -> SummaryConfig:
    return SummaryConfig(
        summary_max_tokens=_cfg_int(
            ("summary", "summary_max_tokens"),
            env_name="SUMMARY_MAX_TOKENS",
            default=SUMMARY_DEFAULTS.summary_max_tokens,
        ),
        summary_conversation_prompt_file=_cfg_str(
            ("summary", "summary_conversation_prompt_file"),
            env_name="SUMMARY_CONVO_PROMPT_FILE",
            default=SUMMARY_DEFAULTS.summary_conversation_prompt_file,
        ),
        summary_conversation_prompt=_cfg_str(
            ("summary", "summary_conversation_prompt"),
            env_name="SUMMARY_CONVO_PROMPT",
            default=SUMMARY_DEFAULTS.summary_conversation_prompt,
        ),
        summary_reduce_threshold_chars=_cfg_int(
            ("summary", "summary_reduce_threshold_chars"),
            env_name="SUMMARY_REDUCE_THRESHOLD_CHARS",
            default=SUMMARY_DEFAULTS.summary_reduce_threshold_chars,
        ),
        summary_chunk_target_chars=_cfg_int(
            ("summary", "summary_chunk_target_chars"),
            env_name="SUMMARY_CHUNK_TARGET_CHARS",
            default=SUMMARY_DEFAULTS.summary_chunk_target_chars,
        ),
        summary_chunk_hard_max_chars=_cfg_int(
            ("summary", "summary_chunk_hard_max_chars"),
            env_name="SUMMARY_CHUNK_HARD_MAX_CHARS",
            default=SUMMARY_DEFAULTS.summary_chunk_hard_max_chars,
        ),
        summary_chunk_max_tokens=_cfg_int(
            ("summary", "summary_chunk_max_tokens"),
            env_name="SUMMARY_CHUNK_MAX_TOKENS",
            default=SUMMARY_DEFAULTS.summary_chunk_max_tokens,
        ),
    )


def load_context_config() -> ContextConfig:
    return ContextConfig(
        max_tokens=_cfg_int(
            ("context", "max_tokens"),
            env_name="CONTEXT_MAX_TOKENS",
            default=CONTEXT_DEFAULTS.max_tokens,
        ),
        memory_pin_limit=_cfg_int(
            ("context", "memory_pin_limit"),
            env_name="CONTEXT_MEMORY_LIMIT",
            default=CONTEXT_DEFAULTS.memory_pin_limit,
        ),
        history_limit=_cfg_int(
            ("context", "history_limit"),
            env_name="CONTEXT_HISTORY_LIMIT",
            default=CONTEXT_DEFAULTS.history_limit,
        ),
        preview_limit=_cfg_int(
            ("context", "preview_limit"),
            env_name="CONTEXT_PREVIEW_LIMIT",
            default=CONTEXT_DEFAULTS.preview_limit,
        ),
        estimate_model=_cfg_str(
            ("context", "estimate_model"),
            env_name="CONTEXT_ESTIMATE_MODEL",
            default=CONTEXT_DEFAULTS.estimate_model,
        ),
    )


def load_query_config() -> QueryConfig:
    return QueryConfig(
        max_terms=max(1, _cfg_int(("query", "max_terms"), env_name="QUERY_MAX_TERMS", default=QUERY_DEFAULTS.max_terms)),
        max_phrase_words=max(1, _cfg_int(("query", "max_phrase_words"), env_name="QUERY_MAX_PHRASE_WORDS", default=QUERY_DEFAULTS.max_phrase_words)),
        max_phrase_chars=max(1, _cfg_int(("query", "max_phrase_chars"), env_name="QUERY_MAX_PHRASE_CHARS", default=QUERY_DEFAULTS.max_phrase_chars)),
        filler_words_file=_cfg_str(("query", "filler_words_file"), env_name="QUERY_FILLER_WORDS_FILE", default=QUERY_DEFAULTS.filler_words_file),
        filler_words=_cfg_str(("query", "filler_words"), env_name="QUERY_FILLER_WORDS", default=QUERY_DEFAULTS.filler_words),
        long_query_chars=max(1, _cfg_int(("query", "long_query_chars"), env_name="QUERY_LONG_CHARS", default=QUERY_DEFAULTS.long_query_chars)),
        max_query_slices=max(1, _cfg_int(("query", "max_query_slices"), env_name="QUERY_MAX_SLICES", default=QUERY_DEFAULTS.max_query_slices)),
        llm_expand_enabled=_cfg_bool(("query", "llm_expand_enabled"), env_name="QUERY_LLM_EXPAND", default=QUERY_DEFAULTS.llm_expand_enabled),
        llm_expand_prompt_file=_cfg_str(("query", "llm_expand_prompt_file"), env_name="EXPAND_QUERY_PROMPT_FILE", default=QUERY_DEFAULTS.llm_expand_prompt_file),
        llm_expand_min_terms=max(1, _cfg_int(("query", "llm_expand_min_terms"), env_name="QUERY_LLM_MIN_TERMS", default=QUERY_DEFAULTS.llm_expand_min_terms)),
        llm_expand_min_results=max(1, _cfg_int(("query", "llm_expand_min_results"), env_name="QUERY_LLM_MIN_RESULTS", default=QUERY_DEFAULTS.llm_expand_min_results)),
        llm_expand_max_keywords=max(1, _cfg_int(("query", "llm_expand_max_keywords"), env_name="QUERY_LLM_MAX_KEYWORDS", default=QUERY_DEFAULTS.llm_expand_max_keywords)),
        llm_expand_model=_cfg_str(("query", "llm_expand_model"), env_name="QUERY_LLM_EXPAND_MODEL", default=QUERY_DEFAULTS.llm_expand_model),
        llm_expand_max_tokens=max(1, _cfg_int(("query", "llm_expand_max_tokens"), env_name="QUERY_LLM_EXPAND_MAX_TOKENS", default=QUERY_DEFAULTS.llm_expand_max_tokens)),
    )


def load_retrieval_config() -> RetrievalConfig:
    raw_include = _cfg_csv_set(
        ("retrieval", "query_include"),
        env_name="QUERY_INCLUDE",
        default=RETRIEVAL_DEFAULTS.query_include,
        allowed=QUERY_INCLUDE_ALLOWED,
    )
    if not raw_include:
        raw_include = RETRIEVAL_DEFAULTS.query_include

    raw_expand = _cfg_csv_set(
        ("retrieval", "query_expand_results"),
        env_name="QUERY_EXPAND_RESULTS",
        default=RETRIEVAL_DEFAULTS.query_expand_results,
        allowed=QUERY_EXPAND_ALLOWED,
    )
    if not raw_expand:
        raw_expand = RETRIEVAL_DEFAULTS.query_expand_results

    return RetrievalConfig(
        query_include=raw_include,
        query_expand_results=raw_expand,
        query_max_full_files=max(1, _cfg_int(("retrieval", "query_max_full_files"), env_name="QUERY_MAX_FULL_FILES", default=RETRIEVAL_DEFAULTS.query_max_full_files)),
        query_max_full_memories=max(1, _cfg_int(("retrieval", "query_max_full_memories"), env_name="QUERY_MAX_FULL_MEMORIES", default=RETRIEVAL_DEFAULTS.query_max_full_memories)),
        query_max_full_chats=max(1, _cfg_int(("retrieval", "query_max_full_chats"), env_name="QUERY_MAX_FULL_CHATS", default=RETRIEVAL_DEFAULTS.query_max_full_chats)),
        query_expand_min_artifact_hits=max(1, _cfg_int(("retrieval", "query_expand_min_artifact_hits"), env_name="QUERY_EXPAND_MIN_ARTIFACT_HITS", default=RETRIEVAL_DEFAULTS.query_expand_min_artifact_hits)),
        query_expand_chat_window_before=max(0, _cfg_int(("retrieval", "query_expand_chat_window_before"), env_name="QUERY_EXPAND_CHAT_WINDOW_BEFORE", default=RETRIEVAL_DEFAULTS.query_expand_chat_window_before)),
        query_expand_chat_window_after=max(0, _cfg_int(("retrieval", "query_expand_chat_window_after"), env_name="QUERY_EXPAND_CHAT_WINDOW_AFTER", default=RETRIEVAL_DEFAULTS.query_expand_chat_window_after)),
        query_global_artifacts=_cfg_bool(("retrieval", "query_global_artifacts"), env_name="QUERY_GLOBAL_ARTIFACTS", default=RETRIEVAL_DEFAULTS.query_global_artifacts),
        retrieval_cache_ttl_sec=_cfg_float(("retrieval", "retrieval_cache_ttl_sec"), env_name="QUERY_CACHE_TTL_SEC", default=RETRIEVAL_DEFAULTS.retrieval_cache_ttl_sec),
        retrieval_cache_max_entries=max(1, _cfg_int(("retrieval", "retrieval_cache_max_entries"), env_name="QUERY_CACHE_MAX", default=RETRIEVAL_DEFAULTS.retrieval_cache_max_entries)),
        query_include_project_conversation_transcripts=_cfg_bool(("retrieval", "query_include_project_conversation_transcripts"), env_name="QUERY_INCLUDE_PROJECT_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_project_conversation_transcripts),
        query_include_global_conversation_transcripts=_cfg_bool(("retrieval", "query_include_global_conversation_transcripts"), env_name="QUERY_INCLUDE_GLOBAL_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_global_conversation_transcripts),
        query_include_recent_conversation_transcripts=_cfg_bool(("retrieval", "query_include_recent_conversation_transcripts"), env_name="QUERY_INCLUDE_RECENT_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_recent_conversation_transcripts),
        recent_conversation_transcript_limit=max(1, _cfg_int(("retrieval", "recent_conversation_transcript_limit"), env_name="QUERY_RECENT_CONVERSATION_TRANSCRIPT_LIMIT", default=RETRIEVAL_DEFAULTS.recent_conversation_transcript_limit)),
    )


def load_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=_cfg_str(("embeddings", "provider"), env_name="EMBEDDING_PROVIDER", default=EMBEDDING_DEFAULTS.provider),
        model=_cfg_str(("embeddings", "model"), env_name="EMBEDDING_MODEL", default=EMBEDDING_DEFAULTS.model),
        dimensions=max(0, _cfg_int(("embeddings", "dimensions"), env_name="EMBEDDING_DIMENSIONS", default=EMBEDDING_DEFAULTS.dimensions)),
        batch_size=max(1, _cfg_int(("embeddings", "batch_size"), env_name="EMBEDDING_BATCH_SIZE", default=EMBEDDING_DEFAULTS.batch_size)),
        cache_enabled=_cfg_bool(("embeddings", "cache_enabled"), env_name="EMBEDDING_CACHE_ENABLED", default=EMBEDDING_DEFAULTS.cache_enabled),
        cache_dir=_cfg_str(("embeddings", "cache_dir"), env_name="EMBEDDING_CACHE_DIR", default=EMBEDDING_DEFAULTS.cache_dir),
    )


def load_vector_config() -> VectorConfig:
    return VectorConfig(
        backend=_cfg_str(("vector", "backend"), env_name="VECTOR_BACKEND", default=VECTOR_DEFAULTS.backend),
        collection_name=_cfg_str(("vector", "collection_name"), env_name="VECTOR_COLLECTION_NAME", default=VECTOR_DEFAULTS.collection_name),
        local_path=_cfg_str(("vector", "local_path"), env_name="VECTOR_LOCAL_PATH", default=VECTOR_DEFAULTS.local_path),
        server_url=_cfg_str(("vector", "server_url"), env_name="VECTOR_SERVER_URL", default=VECTOR_DEFAULTS.server_url),
        api_key=_cfg_str(("vector", "api_key"), env_name="VECTOR_API_KEY", default=VECTOR_DEFAULTS.api_key),
        distance_metric=_cfg_str(("vector", "distance_metric"), env_name="VECTOR_DISTANCE_METRIC", default=VECTOR_DEFAULTS.distance_metric),
        search_limit=max(1, _cfg_int(("vector", "search_limit"), env_name="VECTOR_SEARCH_LIMIT", default=VECTOR_DEFAULTS.search_limit)),
    )


def load_import_config() -> ImportConfig:
    return ImportConfig(
        prose_chunk_target_chars=max(1, _cfg_int(("import", "prose_chunk_target_chars"), env_name="IMPORT_PROSE_CHUNK_TARGET_CHARS", default=IMPORT_DEFAULTS.prose_chunk_target_chars)),
        prose_chunk_hard_max_chars=max(1, _cfg_int(("import", "prose_chunk_hard_max_chars"), env_name="IMPORT_PROSE_CHUNK_HARD_MAX_CHARS", default=IMPORT_DEFAULTS.prose_chunk_hard_max_chars)),
        code_chunk_target_chars=max(1, _cfg_int(("import", "code_chunk_target_chars"), env_name="IMPORT_CODE_CHUNK_TARGET_CHARS", default=IMPORT_DEFAULTS.code_chunk_target_chars)),
        code_chunk_hard_max_chars=max(1, _cfg_int(("import", "code_chunk_hard_max_chars"), env_name="IMPORT_CODE_CHUNK_HARD_MAX_CHARS", default=IMPORT_DEFAULTS.code_chunk_hard_max_chars)),
        transcript_chunk_target_chars=max(1, _cfg_int(("import", "transcript_chunk_target_chars"), env_name="IMPORT_TRANSCRIPT_CHUNK_TARGET_CHARS", default=IMPORT_DEFAULTS.transcript_chunk_target_chars)),
        transcript_chunk_hard_max_chars=max(1, _cfg_int(("import", "transcript_chunk_hard_max_chars"), env_name="IMPORT_TRANSCRIPT_CHUNK_HARD_MAX_CHARS", default=IMPORT_DEFAULTS.transcript_chunk_hard_max_chars)),
        trailing_merge_min_chars=max(1, _cfg_int(("import", "trailing_merge_min_chars"), env_name="IMPORT_TRAILING_MERGE_MIN_CHARS", default=IMPORT_DEFAULTS.trailing_merge_min_chars)),
        ensure_files_limit_per_scope=max(1, _cfg_int(("import", "ensure_files_limit_per_scope"), env_name="IMPORT_ENSURE_FILES_LIMIT_PER_SCOPE", default=IMPORT_DEFAULTS.ensure_files_limit_per_scope)),
        artifact_sidecar_threshold_bytes=max(1, _cfg_int(("import", "artifact_sidecar_threshold_bytes"), env_name="IMPORT_ARTIFACT_SIDECAR_THRESHOLD_BYTES", default=IMPORT_DEFAULTS.artifact_sidecar_threshold_bytes)),
    )