import os
from dataclasses import dataclass

from dotenv import load_dotenv

# from server.db import get_app_setting_bool

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
    # be consistent with logic in other modules
    #return val.strip().lower() not in ("0", "false", "no", "off", "")

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return _str_to_bool(v)

@dataclass(frozen=True)
class CoreConfig:
    system_prompt_file: str = ".\\prompts\\_default_system_prompt.txt"
    default_system_prompt: str = "You are a helpful assistant operating in a locally hosted scaffolding called WyrmGPT. Be concise, candid, and technically accurate."
    debug_mode: bool = False
CORE_DEFAULTS: CoreConfig = CoreConfig()

@dataclass(frozen=True)
class OpenAIConfig:
    open_ai_apikey: str = ""
    open_ai_model: str = "gpt-5.4"
    summary_model: str = "gpt-5-mini" # The model to use for summary generation - pick a cheap one
OPENAI_DEFAULTS: OpenAIConfig = OpenAIConfig()

@dataclass(frozen=True)
class UIConfig:
    local_timezone: str = "America/Los_Angeles" # America/New_York etc
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
    # TODO move to OpenAIConfig after that code is isolated in OpenAI.py
    estimate_model: str = "gpt-5-mini"
CONTEXT_DEFAULTS: ContextConfig = ContextConfig()

@dataclass(frozen=True)
class QueryConfig:
    query_mode: str = "ALL"  # FILES, FTS, VECTOR, HYBRID, ALL
    query_global_artifacts: bool = True # RAG queries will include global artifacts
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

    # Long-query slicing
    long_query_chars: int = 400
    max_query_slices: int = 6

    # When to ask LLM for keywords
    llm_expand_enabled: bool = True
    llm_expand_prompt_file: str = ".\\prompts\\_expand_query_prompt.txt"
    llm_expand_min_terms: int = 4          # if shaped terms < this, consider LLM
    llm_expand_min_results: int = 3        # if results < this, consider LLM
    llm_expand_max_keywords: int = 10
    # TODO move to OpenAIConfig after that code is isolated in OpenAI.py
    llm_expand_model: str = "gpt-5-mini"
    llm_expand_max_tokens: int = 800

    # “Keep what we loaded” cache
    retrieval_cache_ttl_sec: float = 180.0
    retrieval_cache_max_entries: int = 64

    # Scoping of conversation transcripts
    query_include_project_conversation_transcripts: bool = True
    query_include_global_conversation_transcripts: bool = True
    query_include_recent_conversation_transcripts: bool = True
    recent_conversation_transcript_limit: int = 40

QUERY_DEFAULTS: QueryConfig = QueryConfig()

# intentionally not frozen because these can change at runtime
@dataclass
class AppConfig:
    search_chat_history: bool = True
APP_DEFAULTS: AppConfig = AppConfig()

class AppConfigKeys:
    search_chat_history: str = "search_chat_history"
APP_KEYS: AppConfigKeys = AppConfigKeys()

# Helper to prep the database
def ensure_default_app_settings() -> None:
    # keep it local to avoid circular imports
    from .db import ensure_default_app_setting

    scope_type = "global"
    scope_id = ""
    enable_search_chat_history = _env_bool("SEARCH_CHAT_HISTORY_ENABLED", APP_DEFAULTS.search_chat_history)
    ensure_default_app_setting(APP_KEYS.search_chat_history, _bool_to_str(enable_search_chat_history), scope_type, scope_id)

def load_app_config() -> AppConfig:
    from .db import get_app_setting, get_app_setting_bool, init_schema
    init_schema() # just in case, should be FINE
    ensure_default_app_settings()
    return AppConfig(
        search_chat_history=get_app_setting_bool(APP_KEYS.search_chat_history)
    )

def load_core_config() -> CoreConfig:
    return CoreConfig(
        system_prompt_file=_env_str("SYSTEM_PROMPT_FILE", CORE_DEFAULTS.system_prompt_file),
        default_system_prompt=_env_str("SYSTEM_PROMPT", CORE_DEFAULTS.default_system_prompt),
        debug_mode=_env_bool("DEBUG_MODE", CORE_DEFAULTS.debug_mode)
    )

def load_ui_config() -> UIConfig:
    core_cfg = load_core_config()
    return UIConfig(
        local_timezone=_env_str("LOCAL_TIMEZONE",
            # Alternate naming
            _env_str("UI_TIMEZONE",
            _env_str("APP_TIMEZONE",
            _env_str("TZ", UI_DEFAULTS.local_timezone))),
        ),
        context_preview_limit_min=_env_int(
            "UI_CONTEXT_PREVIEW_LIMIT_MIN",
            UI_DEFAULTS.context_preview_limit_min,
        ),
        context_preview_limit_max=_env_int(
            "UI_CONTEXT_PREVIEW_LIMIT_MAX",
            UI_DEFAULTS.context_preview_limit_max,
        ),
        min_rag_query_text_len=_env_int(
            "UI_MIN_RAG_QUERY_TEXT_LEN",
            UI_DEFAULTS.min_rag_query_text_len,
        ),
        context_idle_ms=_env_int(
            "UI_CONTEXT_IDLE_MS",
            UI_DEFAULTS.context_idle_ms,
        ),
        transcript_idle_ms=_env_int(
            "UI_TRANSCRIPT_IDLE_MS",
            UI_DEFAULTS.transcript_idle_ms,
        ),
        debug_boot=_env_bool(
            "UI_DEBUG_BOOT",
            UI_DEFAULTS.debug_boot,
        ),
    )

def load_openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        open_ai_apikey=_env_str("OPENAI_API_KEY", OPENAI_DEFAULTS.open_ai_apikey),
        open_ai_model=_env_str("OPENAI_MODEL", OPENAI_DEFAULTS.open_ai_model),
        summary_model=_env_str("SUMMARY_MODEL", OPENAI_DEFAULTS.summary_model),
    )

def load_summary_config() -> SummaryConfig:
    return SummaryConfig(
        summary_max_tokens=_env_int("SUMMARY_MAX_TOKENS", SUMMARY_DEFAULTS.summary_max_tokens),
        summary_conversation_prompt_file=_env_str("SUMMARY_CONVO_PROMPT_FILE", SUMMARY_DEFAULTS.summary_conversation_prompt_file),
        summary_conversation_prompt=_env_str("SUMMARY_CONVO_PROMPT", SUMMARY_DEFAULTS.summary_conversation_prompt),
        summary_reduce_threshold_chars=_env_int("SUMMARY_REDUCE_THRESHOLD_CHARS", SUMMARY_DEFAULTS.summary_reduce_threshold_chars),
        summary_chunk_target_chars=_env_int("SUMMARY_CHUNK_TARGET_CHARS", SUMMARY_DEFAULTS.summary_chunk_target_chars),
        summary_chunk_hard_max_chars=_env_int("SUMMARY_CHUNK_HARD_MAX_CHARS", SUMMARY_DEFAULTS.summary_chunk_hard_max_chars),
        summary_chunk_max_tokens=_env_int("SUMMARY_CHUNK_MAX_TOKENS", SUMMARY_DEFAULTS.summary_chunk_max_tokens),
    )

def load_context_config() -> ContextConfig:
    return ContextConfig(
        max_tokens=_env_int("CONTEXT_MAX_TOKENS", CONTEXT_DEFAULTS.max_tokens),
        memory_pin_limit=_env_int("CONTEXT_MEMORY_LIMIT", CONTEXT_DEFAULTS.memory_pin_limit),
        history_limit=_env_int("CONTEXT_HISTORY_LIMIT", CONTEXT_DEFAULTS.history_limit),
        preview_limit=_env_int("CONTEXT_PREVIEW_LIMIT", CONTEXT_DEFAULTS.preview_limit),
        estimate_model=_env_str("CONTEXT_ESTIMATE_MODEL", CONTEXT_DEFAULTS.estimate_model),
    )

def load_query_config() -> QueryConfig:
    return QueryConfig(
        query_mode=_env_str("QUERY_MODE", QUERY_DEFAULTS.query_mode).upper(),
        query_global_artifacts=_env_bool("QUERY_GLOBAL_ARTIFACTS", QUERY_DEFAULTS.query_global_artifacts),
        max_terms=_env_int("QUERY_MAX_TERMS", QUERY_DEFAULTS.max_terms),
        max_phrase_words=_env_int("QUERY_MAX_PHRASE_WORDS", QUERY_DEFAULTS.max_phrase_words),
        max_phrase_chars=_env_int("QUERY_MAX_PHRASE_CHARS", QUERY_DEFAULTS.max_phrase_chars),
        filler_words_file=_env_str("QUERY_FILLER_WORDS_FILE", QUERY_DEFAULTS.filler_words_file),
        filler_words=_env_str("QUERY_FILLER_WORDS", QUERY_DEFAULTS.filler_words),
        long_query_chars=_env_int("QUERY_LONG_CHARS", QUERY_DEFAULTS.long_query_chars),
        max_query_slices=_env_int("QUERY_MAX_SLICES", QUERY_DEFAULTS.max_query_slices),

        llm_expand_enabled=_env_bool("QUERY_LLM_EXPAND", QUERY_DEFAULTS.llm_expand_enabled),
        llm_expand_prompt_file=_env_str("EXPAND_QUERY_PROMPT_FILE", QUERY_DEFAULTS.llm_expand_prompt_file),
        llm_expand_min_terms=_env_int("QUERY_LLM_MIN_TERMS", QUERY_DEFAULTS.llm_expand_min_terms),
        llm_expand_min_results=_env_int("QUERY_LLM_MIN_RESULTS", QUERY_DEFAULTS.llm_expand_min_results),
        llm_expand_max_keywords=_env_int("QUERY_LLM_MAX_KEYWORDS", QUERY_DEFAULTS.llm_expand_max_keywords),
        # This is the model we'll use if we need query optimization of user input    
        llm_expand_model=_env_str("QUERY_LLM_EXPAND_MODEL", QUERY_DEFAULTS.llm_expand_model),
        llm_expand_max_tokens=_env_int("QUERY_LLM_EXPAND_MAX_TOKENS", QUERY_DEFAULTS.llm_expand_max_tokens),

        retrieval_cache_ttl_sec=_env_float("QUERY_CACHE_TTL_SEC", QUERY_DEFAULTS.retrieval_cache_ttl_sec),
        retrieval_cache_max_entries=_env_int("QUERY_CACHE_MAX", QUERY_DEFAULTS.retrieval_cache_max_entries),

        query_include_project_conversation_transcripts=_env_bool(
            "QUERY_INCLUDE_PROJECT_CONVERSATION_TRANSCRIPTS",
            QUERY_DEFAULTS.query_include_project_conversation_transcripts,
        ),
        query_include_global_conversation_transcripts=_env_bool(
            "QUERY_INCLUDE_GLOBAL_CONVERSATION_TRANSCRIPTS",
            QUERY_DEFAULTS.query_include_global_conversation_transcripts,
        ),
        query_include_recent_conversation_transcripts=_env_bool(
            "QUERY_INCLUDE_RECENT_CONVERSATION_TRANSCRIPTS",
            QUERY_DEFAULTS.query_include_recent_conversation_transcripts,
        ),
        recent_conversation_transcript_limit=_env_int(
            "QUERY_RECENT_CONVERSATION_TRANSCRIPT_LIMIT",
            QUERY_DEFAULTS.recent_conversation_transcript_limit,
        ),
    )
