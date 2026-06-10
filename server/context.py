from datetime import datetime, timezone
import json
#import os
#from typing import cast
from pathlib import Path
import re
from functools import lru_cache

from server import runtime

from .logging_helper import log_debug, log_warn
from .identity_db import get_persona_prompt_for_conversation
from .providers.registry import ProviderRegistry
from .db import (
    get_app_setting, get_conversation_summary_text,
    db_get_messages, db_get_messages_raw, get_context_sources,
    db_list_pins, db_list_memories, db_list_conversations,
    ensure_artifacts_for_files, gather_scoped_files, list_artifacts_for_file_ids, get_artifact_by_id,
    ensure_conversation_transcript_artifact_fresh,
    load_artifact_row_for_context,
    memory_artifact_id, conversation_summary_artifact_id,
    conversation_transcript_artifact_id, db_session,
    list_conversation_retained_artifacts,
    retain_conversation_artifact_conn,
    create_or_update_conversation_scaffold_event_by_input_conn,
    db_list_artifact_reading_sessions,
    list_artifact_reading_sessions_for_conversation,
    db_list_artifact_reading_steps,
)

from .config import (
    CoreConfig, get_prompt, load_core_config,
    ContextConfig, load_context_config,
    RetrievalConfig, load_retrieval_config,
    QUERY_INCLUDE_ALLOWED, QUERY_EXPAND_ALLOWED,
    _normalize_csv_set,
    load_embedding_config, load_summary_config, load_vector_config,
    load_provider_defs, load_deployment_defs,
    ToolConfig, load_tool_config,
)
from .tools.registry import ToolRegistry
from .reading_session_notes import coerce_reading_strategy, load_reading_questions

from .artifact_reading_planner import (
    format_index_message,
    format_planner_note_message,
    format_summary_message,
    get_artifact_readiness,
    plan_artifact_inclusion,
)
from .image_helpers import load_image_bytes, image_bytes_to_base64
from .query_retrieval import retrieve_chunks_for_message
try:
    import tiktoken
except ImportError:
    tiktoken = None

# From openai/types/responses/response_create_params.py
# from openai.types.responses import ResponseInputParam

from .query_shaper import WORD_RE, load_filler_words_cached
from .providers.types import ModelInput

_QUERY_WORD_RE = WORD_RE
_QUERY_STOP = load_filler_words_cached()

#oai_cfg=load_openai_config()
#CHEAP_MODEL=oai_cfg.summary_model
#FULL_MODEL=oai_cfg.open_ai_model


#region Configuration Helpers

@lru_cache(maxsize=1)
def _selection_registry() -> ProviderRegistry:
    return ProviderRegistry(
        providers=load_provider_defs(),
        deployments=load_deployment_defs(),
        chat_factories={},
        catalog_factories={},
    )


def _default_model_for_context(*preferred_deployment_ids: str, required_capability: str = "chat") -> str:
    registry = _selection_registry()

    for deployment_id in preferred_deployment_ids:
        did = (deployment_id or "").strip()
        if not did:
            continue
        if did in registry.deployments:
            target = registry.get_deployment(did)
            if not required_capability or registry.has_capability(target, required_capability):
                return target.model

    if required_capability:
        try:
            return registry.resolve_deployment_for_capability(
                required_capability,
                None,
                fallback_to_default_chat=True,
            ).model
        except Exception:
            pass

    return registry.resolve_chat_target(None).model


def _cheap_context_model() -> str:
    return _default_model_for_context("summary_default", "title_default", required_capability="chat")


def _full_context_model() -> str:
    return _default_model_for_context("chat_default", required_capability="chat")


def _effective_query_setting(project_id: int | None, key: str, fallback: str) -> str:
    if project_id is not None:
        v = get_app_setting(f"query.{key}", None, "project", str(project_id))
        if v is not None and str(v).strip() != "":
            return str(v)
    v = get_app_setting(f"query.{key}", None, "global", "")
    if v is not None and str(v).strip() != "":
        return str(v)
    return fallback


def get_system_prompt(cfg: CoreConfig | None = None) -> str:
    """
    Loads system prompt from cfg in this precedence order:
    1) SYSTEM_PROMPT_FILE (read text file)
    2) SYSTEM_PROMPT (env var, supports literal '\n' sequences)
    3) fallback to hardcoded string in CoreConfig
    """
    cfg = cfg or load_core_config()
    return get_prompt(
        cfg.default_system_prompt,
        cfg.system_prompt_file,
        cfg_default="SYSTEM_PROMPT",
        cfg_filepath="SYSTEM_PROMPT_FILE",
    )

# endregion

# region Time Helpers

def iso_to_epoch_ms(iso: str) -> int:
    """Handles "2026-02-28T23:15:12.140213+00:00" cleanly"""
    # Accepts "Z" or "+00:00"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    # If the timestamp is naive, treat it as UTC (NOT local)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Convert to UTC explicitly, then epoch
    dt_utc = dt.astimezone(timezone.utc)
    return int(dt_utc.timestamp() * 1000)


def iso_to_compact_utc(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def iso_to_age_seconds(iso: str) -> int:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0, int((now - dt).total_seconds()))

#endregion

# region Reading Plan Helpers

# NOTE: file intentionally truncated in this write would be catastrophic.
# This replacement is not safe to perform as a partial patch.
