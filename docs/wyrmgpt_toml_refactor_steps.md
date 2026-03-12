# WyrmGPT TOML refactor steps
_Last updated: Thursday, March 12, 2026_

## Goal

Add `config.toml` support **now**, while keeping `.env` as fallback during the migration window.

This pass updates:

- `server/config.py`
- `server/main.py`
- `server/scripts/summarize_conversations.py`

and adds:

- `config.toml.example`

## Files to change

### 1. `server/config.py`

#### 1A. Replace lines 1–8 with:

```python
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

# from server.db import get_app_setting_bool

load_dotenv()
```

#### 1B. Insert this block right after `_env_bool(...)` (after current line 37)

```python
_MISSING = object()
_TOML_CACHE: dict[str, Any] | None = None
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_DEFAULT_TOML_PATH = _ROOT / "config.toml"


def _config_toml_path() -> Path:
    raw = os.getenv("WYRMGPT_CONFIG_TOML", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_TOML_PATH


def _load_toml_config() -> dict[str, Any]:
    global _TOML_CACHE
    if _TOML_CACHE is not None:
        return _TOML_CACHE

    path = _config_toml_path()
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh) or {}
            _TOML_CACHE = data if isinstance(data, dict) else {}
    else:
        _TOML_CACHE = {}

    return _TOML_CACHE


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
```

#### 1C. In `CoreConfig`, add a new field after `debug_mode`

```python
debug_errors: bool = True
```

#### 1D. Replace `ensure_default_app_settings()` with:

```python
def ensure_default_app_settings() -> None:
    # keep it local to avoid circular imports
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
```

#### 1E. Replace `load_core_config()` with:

```python
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
```

#### 1F. Replace `load_ui_config()` with:

```python
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
```

#### 1G. Replace `load_openai_config()` with:

```python
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
```

#### 1H. Replace `load_summary_config()` with:

```python
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
```

#### 1I. Replace `load_context_config()` with:

```python
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
```

#### 1J. Replace `load_retrieval_config()` with:

```python
def load_retrieval_config() -> RetrievalConfig:
    raw_include = _cfg_csv_set(
        ("retrieval", "query_include"),
        env_name="QUERY_INCLUDE",
        default=RETRIEVAL_DEFAULTS.query_include,
        allowed=QUERY_INCLUDE_ALLOWED,
    )

    raw_expand = _cfg_csv_set(
        ("retrieval", "query_expand_results"),
        env_name="QUERY_EXPAND_RESULTS",
        default=RETRIEVAL_DEFAULTS.query_expand_results,
        allowed=QUERY_EXPAND_ALLOWED,
    )

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
        max_terms=max(1, _cfg_int(("retrieval", "max_terms"), env_name="QUERY_MAX_TERMS", default=RETRIEVAL_DEFAULTS.max_terms)),
        max_phrase_words=max(1, _cfg_int(("retrieval", "max_phrase_words"), env_name="QUERY_MAX_PHRASE_WORDS", default=RETRIEVAL_DEFAULTS.max_phrase_words)),
        max_phrase_chars=max(1, _cfg_int(("retrieval", "max_phrase_chars"), env_name="QUERY_MAX_PHRASE_CHARS", default=RETRIEVAL_DEFAULTS.max_phrase_chars)),
        filler_words_file=_cfg_str(("retrieval", "filler_words_file"), env_name="QUERY_FILLER_WORDS_FILE", default=RETRIEVAL_DEFAULTS.filler_words_file),
        filler_words=_cfg_str(("retrieval", "filler_words"), env_name="QUERY_FILLER_WORDS", default=RETRIEVAL_DEFAULTS.filler_words),
        long_query_chars=max(1, _cfg_int(("retrieval", "long_query_chars"), env_name="QUERY_LONG_CHARS", default=RETRIEVAL_DEFAULTS.long_query_chars)),
        max_query_slices=max(1, _cfg_int(("retrieval", "max_query_slices"), env_name="QUERY_MAX_SLICES", default=RETRIEVAL_DEFAULTS.max_query_slices)),
        llm_expand_enabled=_cfg_bool(("retrieval", "llm_expand_enabled"), env_name="QUERY_LLM_EXPAND", default=RETRIEVAL_DEFAULTS.llm_expand_enabled),
        llm_expand_prompt_file=_cfg_str(("retrieval", "llm_expand_prompt_file"), env_name="EXPAND_QUERY_PROMPT_FILE", default=RETRIEVAL_DEFAULTS.llm_expand_prompt_file),
        llm_expand_min_terms=max(1, _cfg_int(("retrieval", "llm_expand_min_terms"), env_name="QUERY_LLM_MIN_TERMS", default=RETRIEVAL_DEFAULTS.llm_expand_min_terms)),
        llm_expand_min_results=max(1, _cfg_int(("retrieval", "llm_expand_min_results"), env_name="QUERY_LLM_MIN_RESULTS", default=RETRIEVAL_DEFAULTS.llm_expand_min_results)),
        llm_expand_max_keywords=max(1, _cfg_int(("retrieval", "llm_expand_max_keywords"), env_name="QUERY_LLM_MAX_KEYWORDS", default=RETRIEVAL_DEFAULTS.llm_expand_max_keywords)),
        llm_expand_model=_cfg_str(("retrieval", "llm_expand_model"), env_name="QUERY_LLM_EXPAND_MODEL", default=RETRIEVAL_DEFAULTS.llm_expand_model),
        llm_expand_max_tokens=max(1, _cfg_int(("retrieval", "llm_expand_max_tokens"), env_name="QUERY_LLM_EXPAND_MAX_TOKENS", default=RETRIEVAL_DEFAULTS.llm_expand_max_tokens)),
        retrieval_cache_ttl_sec=_cfg_float(("retrieval", "retrieval_cache_ttl_sec"), env_name="QUERY_CACHE_TTL_SEC", default=RETRIEVAL_DEFAULTS.retrieval_cache_ttl_sec),
        retrieval_cache_max_entries=max(1, _cfg_int(("retrieval", "retrieval_cache_max_entries"), env_name="QUERY_CACHE_MAX", default=RETRIEVAL_DEFAULTS.retrieval_cache_max_entries)),
        query_include_project_conversation_transcripts=_cfg_bool(("retrieval", "query_include_project_conversation_transcripts"), env_name="QUERY_INCLUDE_PROJECT_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_project_conversation_transcripts),
        query_include_global_conversation_transcripts=_cfg_bool(("retrieval", "query_include_global_conversation_transcripts"), env_name="QUERY_INCLUDE_GLOBAL_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_global_conversation_transcripts),
        query_include_recent_conversation_transcripts=_cfg_bool(("retrieval", "query_include_recent_conversation_transcripts"), env_name="QUERY_INCLUDE_RECENT_CONVERSATION_TRANSCRIPTS", default=RETRIEVAL_DEFAULTS.query_include_recent_conversation_transcripts),
        recent_conversation_transcript_limit=max(1, _cfg_int(("retrieval", "recent_conversation_transcript_limit"), env_name="QUERY_RECENT_CONVERSATION_TRANSCRIPT_LIMIT", default=RETRIEVAL_DEFAULTS.recent_conversation_transcript_limit)),
    )
```

#### 1K. Replace `load_embedding_config()` with:

```python
def load_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=_cfg_str(("embeddings", "provider"), env_name="EMBEDDING_PROVIDER", default=EMBEDDING_DEFAULTS.provider),
        model=_cfg_str(("embeddings", "model"), env_name="EMBEDDING_MODEL", default=EMBEDDING_DEFAULTS.model),
        dimensions=max(0, _cfg_int(("embeddings", "dimensions"), env_name="EMBEDDING_DIMENSIONS", default=EMBEDDING_DEFAULTS.dimensions)),
        batch_size=max(1, _cfg_int(("embeddings", "batch_size"), env_name="EMBEDDING_BATCH_SIZE", default=EMBEDDING_DEFAULTS.batch_size)),
        cache_enabled=_cfg_bool(("embeddings", "cache_enabled"), env_name="EMBEDDING_CACHE_ENABLED", default=EMBEDDING_DEFAULTS.cache_enabled),
        cache_dir=_cfg_str(("embeddings", "cache_dir"), env_name="EMBEDDING_CACHE_DIR", default=EMBEDDING_DEFAULTS.cache_dir),
    )
```

#### 1L. Replace `load_vector_config()` with:

```python
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
```

### 2. `server/main.py`

#### 2A. Remove these imports / lines

Delete:

```python
import os
from dotenv import load_dotenv
```

Delete:

```python
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"
load_dotenv()
```

#### 2B. Replace them with:

```python
DEBUG_ERRORS = load_core_config().debug_errors
```

Keep it near the top where `DEBUG_ERRORS` already lived.

### 3. `server/scripts/summarize_conversations.py`

#### 3A. Replace line 95

Replace:

```python
ap.add_argument("--model", default=os.getenv("SUMMARY_MODEL") or os.getenv("MODEL") or ctx_cfg.estimate_model or "gpt-5-mini")
```

with:

```python
ap.add_argument("--model", default=oai_cfg.summary_model or ctx_cfg.estimate_model or "gpt-5-mini")
```

That makes the script obey TOML through `load_openai_config()`.

### 4. Add `config.toml`

Use the attached example and place it at repo root as `config.toml`.

### 5. Test sequence

1. Leave `.env` in place.
2. Add `config.toml` with one obvious change, like timezone.
3. Start the app.
4. Verify `/api/ui_config` reflects TOML values.
5. Verify OpenAI calls still work.
6. Once stable, begin moving settings from `.env` into `config.toml`.

## Attached file

See:
- `config.toml.example`
