import hashlib
import anyio
import asyncio
import mimetypes
import re
import json
import uuid
import time
import traceback
from pathlib import Path
from typing import Optional, cast, Any, Callable
from fastapi import FastAPI, HTTPException, Request, Response, status, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from functools import partial

from contextlib import asynccontextmanager
from pydantic import BaseModel

from .logging_helper import log_warn
from .context import build_context, build_context_panel_payload, build_model_input
from .markdown_helper import apply_house_markdown_normalization, autolink_text, extract_explicit_urls
from .query_retrieval import retrieve_chunks_for_message
from .summary_helper import summarize_conversation_text, suggest_conversation_title_from_transcript
from .artifact_reading_planner import get_artifact_readiness
from .reading_session_notes import build_reading_notes_prompts, coerce_reading_strategy, load_reading_questions, parse_reading_notes_output
from .web_ingest import ingest_urls_from_user_message
from .image_helpers import is_image_file, load_image_bytes, image_bytes_to_base64

# Big Include Blocks for config and db
from .providers.registry import ProviderRegistry
from .providers.base import ChatProvider, ModelCatalogProvider
from .providers.openai_provider import OpenAIProvider, ProviderExecutionError, extract_error_message
from .providers.types import ModelCatalog, ModelInput, ProviderDef
from .config import (
    load_provider_defs, load_deployment_defs,
    load_core_config, load_tool_config, load_ui_config,
    ContextConfig, load_context_config,
    RetrievalConfig, load_retrieval_config,
    SummaryConfig, load_summary_config,
    # app_settings access
    APP_KEYS, load_app_config,
    # Other helpers and vars
    QUERY_INCLUDE_ALLOWED, QUERY_EXPAND_ALLOWED,
    _normalize_csv_set, get_prompt
)
from .db import (
    # Schema and connection
    init_schema, db_debug_info, db_session,
    # Shared paths
    DATA_DIR,
    # this is the reverse end of AppConfig
    set_app_setting,
    # Chat Messages
    add_message, get_messages,
    get_messages_raw, scope_rank,
    list_conversation_history_with_scaffold_events,
    list_citation_scope_cards_for_conversation,
    list_citation_scope_cards_for_project,
    replace_citations_for_message,
    create_conversation_scaffold_event,
    update_conversation_scaffold_event,
    save_conversation_summary_artifact,
    update_ab_canonical,
    get_artifact_reading_session, get_artifact_reading_step, list_artifact_reading_steps,
    update_artifact_reading_session, update_artifact_reading_step,
    retain_conversation_artifact,
    # Converstaions
    list_conversations, create_conversation,
    delete_conversation, set_conversation_archived,
    get_conversation_title, update_conversation_title,
    get_conversation_context, get_conversation_project_id,
    # Projects and subordinate entities
    list_projects, get_or_create_project,
    get_or_create_project as db_get_or_create_project,  # optional convenience endpoint
    project_add_conversation as db_project_add_conversation,
    project_import as db_project_import,
    set_conversation_project,  # assign_conversation_project,
    update_project, set_project_hidden, delete_project, get_project_delete_preview,
    # Files
    list_files_by_sha256, list_files_same_name_any_scope,
    replace_file_in_place,
    register_file as db_register_file,
    project_add_file as db_project_add_file,
    register_scoped_file, update_file_description, rename_file, set_file_image_caption, set_file_image_ocr_text,
    conversation_link_file, list_files_for_conversation,
    list_files_for_project, list_all_files, get_file_by_id,
    get_files_summary, list_global_files,
    FileDeleteAction, delete_file_cascade, move_artifact_scope,
    move_file_scope, find_same_scope_same_name_file,
    # Artifacts
    get_scoped_artifact_debug, list_artifacts_for_conversation, 
    list_artifacts_for_project, list_global_artifacts, list_artifact_reading_sessions,
    # File Artifacts
    artifact_file, ensure_files_artifacted_for_conversation,
    list_artifacts_for_file,
    # Conversation Artifacts - Transcripts and Summaries
    get_transcript_for_summary, # save_conversation_summary,
    ensure_conversation_transcript_artifact_fresh,
    refresh_conversation_transcript_artifact,
    export_conversation_transcript_markdown,
    # Artifacts for Memories TBD
    # Context cache
    invalidate_context_cache_for_conversation,
    invalidate_context_cache_for_project,
    # Pinned Instructions / Personalization
    add_memory_pin, list_memory_pins,
    delete_memory_pin, invalidate_all_context_cache,
    upsert_about_you_pin, get_about_you_pin,
    update_memory_pin as db_update_memory_pin,
    # Memories
    create_memory as db_create_memory,
    memory_link_project as db_memory_link_project,
    memory_link_conversation as db_memory_link_conversation,
    list_memories as db_list_memories,
    update_memory as db_update_memory,
    delete_memory as db_delete_memory,    
)
from .tools.base import ToolExecutionContext, ToolInvocationRequest, ToolResult
from .tools.registry import ToolRegistry, load_tool_registry

core_cfg = load_core_config()
TOOL_CFG = load_tool_config()

DEBUG_ERRORS = core_cfg.debug_errors
RowDict = dict[str, Any]


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _load_json_object(value: Any) -> RowDict:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            loaded = json.loads(text)
        except Exception:
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    if isinstance(value, dict):
        return dict(value)
    return {}

# Replaces the old @app.on_event("startup") and @app.on_event("shutdown") handlers with a single async context manager that can do both setup and teardown.
#@app.on_event("startup")
#def _startup():
#    init_db()
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    global MODEL_CATALOG, PROVIDER_REGISTRY, TOOL_REGISTRY
    print("[DB]", db_debug_info())
    init_schema()
    MODEL_CATALOG = load_model_catalog()
    PROVIDER_REGISTRY = build_provider_registry(MODEL_CATALOG)
    TOOL_REGISTRY = load_tool_registry(TOOL_CFG)

    # If you need anything else (loading model lists, warm caches…)
    # you put it here.

    yield  # <-- the app runs after this line

    # --- SHUTDOWN ---
    # Cleanup if you ever need it

app = FastAPI(lifespan=lifespan)

# -------------------------
# Global Vars
# -------------------------

# New abstract model for providers
PROVIDER_REGISTRY: ProviderRegistry | None = None
TOOL_REGISTRY: ToolRegistry | None = None

# start from root folder above ./server
HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
# This is where uploaded files are stored; you can change this or add subdirs as needed
SOURCES_ROOT = DATA_DIR / "sources"
# This is where APIs for supported toools (retrievers, file parsers, etc.) would live; you can add subdirs as needed
TOOLS_DIR = HERE / "tools"

# -------------------------
# API Contracts
# -------------------------

# region API Contracts (class definitions)

class AppConfigUpdateRequest(BaseModel):
    search_chat_history: Optional[bool] = None

class QuerySettingsUpdateRequest(BaseModel):
    scope_type: str = "global"
    scope_id: str = ""
    query_include: str | None = None
    query_expand_results: str | None = None
    query_max_full_files: int | None = None
    query_max_full_memories: int | None = None
    query_max_full_chats: int | None = None
    query_expand_min_artifact_hits: int | None = None
    query_expand_chat_window_before: int | None = None
    query_expand_chat_window_after: int | None = None

class FileDescriptionUpdate(BaseModel):
    description: str | None = None

class FileRenameRequest(BaseModel):
    name: str

class FileImageDescribeRequest(BaseModel):
    deployment_id: str | None = None
    overwrite: bool = True


class FileImageOcrRequest(BaseModel):
    deployment_id: str | None = None
    overwrite: bool = True

class FileMoveScopeRequest(BaseModel):
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None

class BulkFileMoveScopeRequest(BaseModel):
    file_ids: list[str]
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None

class BulkFileDeleteRequest(BaseModel):
    file_ids: list[str]


class ArtifactMoveScopeRequest(BaseModel):
    scope_type: str
    scope_id: int | None = None
    scope_uuid: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    visibility: str | None = None
    system_prompt: str | None = None
    override_core_prompt: bool | None = None
    default_advanced_mode: bool | None = None

class TitleRequest(BaseModel):
    title: str

class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    model: Optional[str] = None
    message: str

class ABChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    model_a: Optional[str] = None
    model_b: Optional[str] = None
    message: str

class ABCanonicalRequest(BaseModel):
    conversation_id: str
    ab_group: str
    slot: str  # "A" or "B"

class MemoryCreate(BaseModel):
    content: str
    importance: int = 0
    tags: str | None = None
    created_by: str = "user"
    origin_kind: str = "user_asserted"
    scope_type: str = "global"
    scope_id: int | None = None

class MemoryUpdate(BaseModel):
    content: str
    importance: int = 0
    tags: str | None = None
    created_by: str = "user"
    origin_kind: str = "user_asserted"
    scope_type: str | None = None
    scope_id: int | None = None

class PinRequest(BaseModel):
    text: str
    pin_kind: str | None = None
    title: str | None = None
    scope_type: str | None = None
    scope_id: int | None = None

class AboutYouRequest(BaseModel):
    nickname: str = ""
    age: str = ""
    occupation: str = ""
    more_about_you: str = ""

class FileRegister(BaseModel):
    name: str
    path: str
    mime_type: str | None

class ArtifactCreate(BaseModel):
    name: str
    content: str
    tags: str | None = None

class ImportRule(BaseModel):
    include_tags: str | None = None
    exclude_tags: str | None = None
    include_artifact_ids: str | None = None  # JSON

class NewChatResponse(BaseModel):
    conversation_id: str

class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str | None = None
    visibility: str = "private"
    override_core_prompt: bool = False
    default_advanced_mode: bool = False

class MoveProjectRequest(BaseModel):
    project_id: Optional[int] = None
    project_name: Optional[str] = None

class MemoryLinkProjectRequest(BaseModel):
    project_id: Optional[int] = None
    project_name: Optional[str] = None

class ArchiveRequest(BaseModel):
    archived: bool = True

class CorpusSearchRequest(BaseModel):
    conversation_id: str
    query: str
    limit: int = 10
    include_global: bool = False

class FilePreflightItem(BaseModel):
    name: str
    sha256: str
    scope_type: str
    conversation_id: str | None = None
    project_id: int | None = None

class FilePreflightRequest(BaseModel):
    files: list[FilePreflightItem]

# endregion

# -------------------------
# Helper Functions
# -------------------------

# region Zeitgeber Helpers

ZEIT_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"⟂ts=\d+"
    r"|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=-?\d+)?"
    r")\s*\n",
    re.UNICODE
)
LEGACY_BRACKET_RE = re.compile(r"^\s*\[20\d\d-[^\]]+\]\s*\n")

def strip_zeitgeber_prefix(text: str) -> str:
    if not text:
        return text
    text = ZEIT_PREFIX_RE.sub("", text, count=1)
    text = LEGACY_BRACKET_RE.sub("", text, count=1)  # safety for old runs
    return text.lstrip("\ufeff")  # optional: strip BOM weirdness

# endregion

# region Model / Deployment Catalog and Caching

# Legacy support checking for models
_MODELS_CACHE: dict[str, Any] | None = None
MODEL_CATALOG: ModelCatalog = {}


# TODO make these part of provider registry settings
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes
# Newer deployment cache settings
_DEPLOYMENTS_CACHE: dict[str, Any] | None = None
_DEPLOYMENTS_CACHE_TS: float = 0.0

# endregion

# region Misc Helper functions

# TODO why isn't this moved to someplace like register.py?
def build_provider_registry(model_catalog: ModelCatalog) -> ProviderRegistry:
    providers = load_provider_defs()
    deployments = load_deployment_defs()

    compat_factory = lambda provider_def: OpenAIProvider(provider_def, model_catalog=model_catalog)

    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }

    return ProviderRegistry(
        providers=providers,
        deployments=deployments,
        chat_factories=chat_factories,
        catalog_factories=catalog_factories,
    )


def postprocess_text(text: str) -> str:
    """
    House normalization for output before storing in DB or displaying on screen.
    - strip zeitgeber prefix
    - normalize markdown dialect
    - autolink URLs/domains
    """
    if not text:
        return text
    text = text.strip()
    text = strip_zeitgeber_prefix(text)
    text = apply_house_markdown_normalization(text)
    text = autolink_text(text)
    return text


def _get_default_chat_target():
    registry = PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")
    return registry.resolve_chat_target(None)


def _get_default_chat_selector() -> str:
    """
    Returns the default deployment id if available.
    Falls back to the resolved target id.
    """
    target = _get_default_chat_target()
    return target.id


def _resolve_utility_target(
    *preferred_deployment_ids: str,
    fallback_model: str | None = None,
    required_capability: str = "chat",
):
    registry = PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")

    # First: explicitly preferred deployment ids, in order.
    for deployment_id in preferred_deployment_ids:
        did = (deployment_id or "").strip()
        if not did:
            continue
        if did in registry.deployments:
            target = registry.get_deployment(did)
            if required_capability and not registry.has_capability(target, required_capability):
                continue
            return target

    # Second: backward-compatible raw model / explicit selector fallback.
    requested = (fallback_model or "").strip()
    if requested:
        if requested in registry.deployments:
            target = registry.get_deployment(requested)
            if not required_capability or registry.has_capability(target, required_capability):
                return target
        else:
            target = registry.resolve_chat_target(requested)
            if not required_capability or registry.has_capability(target, required_capability):
                return target

    # Third: pick the first enabled deployment that supports the requested capability.
    if required_capability:
        return registry.resolve_deployment_for_capability(
            required_capability,
            None,
            fallback_to_default_chat=True,
        )

    # Last resort: default chat deployment.
    return registry.resolve_chat_target(None)


def _make_utility_completion(
    *preferred_deployment_ids: str,
    fallback_model: str | None = None,
    required_capability: str = "chat",
):
    registry = PROVIDER_REGISTRY
    if registry is None:
        raise RuntimeError("Provider registry is not initialized.")

    target = _resolve_utility_target(
        *preferred_deployment_ids,
        fallback_model=fallback_model,
        required_capability=required_capability,
    )
    provider = registry.get_chat_provider(target)

    def complete_fn(system_prompt: str, user_prompt: str, max_output_tokens: int) -> str:
        model_input: ModelInput = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        request_options = {"max_output_tokens": max(1, int(max_output_tokens or 0))} if max_output_tokens else None
        result = provider.complete(target, model_input, request_options=request_options)
        return (result.text or "").strip()

    return complete_fn, target


def _generate_image_caption_for_file(
    file_row: RowDict,
    *,
    deployment_id: str | None = None,
) -> tuple[str, str]:
    mime_type = (file_row.get("mime_type") or "").strip() or None
    path = Path(str(file_row.get("path") or "")).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError("Image file content was not found on disk.")
    if not is_image_file(path, mime_type):
        raise ValueError("Only image files can be described.")

    data = load_image_bytes(path)
    if not data:
        raise ValueError("Image bytes could not be loaded.")

    mime_for_data_url = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data_url = f"data:{mime_for_data_url};base64,{image_bytes_to_base64(data)}"

    target = _resolve_utility_target(
        deployment_id or "summary_default",
        "chat_default",
        required_capability="chat",
    )
    if PROVIDER_REGISTRY is None:
        raise RuntimeError("Provider registry is not initialized.")
    provider = PROVIDER_REGISTRY.get_chat_provider(target)

    hint_description = (file_row.get("description") or "").strip()
    hint_text = (
        f"Existing file description (treat as a hint, not ground truth): {hint_description}"
        if hint_description else ""
    )

    model_input: ModelInput = [
        {
            "role": "system",
            "content": "You describe user-supplied images for retrieval and context assembly. Return only a compact factual description of what is visibly present. Mention notable text if it is clear and legible. Avoid speculation, named-entity guesses, or story-like flourishes.",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        f"File name: {file_row.get('name') or file_row.get('id') or 'image'}"
                        f"{hint_text}"
                        "Describe what is shown in this image in 2-4 concise sentences suitable for future LLM context."
                    ),
                },
                {"type": "input_image", "image_url": data_url},
            ],
        },
    ]
    result = provider.complete(target, model_input, request_options={"max_output_tokens": 220})
    caption = re.sub(r"{3,}", "", (result.text or "").strip())
    if not caption:
        raise ValueError("The model returned an empty image description.")
    return caption, target.model


def _generate_image_ocr_for_file(
    file_row: RowDict,
    *,
    deployment_id: str | None = None,
) -> tuple[str | None, str]:
    mime_type = (file_row.get("mime_type") or "").strip() or None
    path = Path(str(file_row.get("path") or "")).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError("Image file content was not found on disk.")
    if not is_image_file(path, mime_type):
        raise ValueError("Only image files can be OCR'd.")

    data = load_image_bytes(path)
    if not data:
        raise ValueError("Image bytes could not be loaded.")

    mime_for_data_url = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data_url = f"data:{mime_for_data_url};base64,{image_bytes_to_base64(data)}"

    target = _resolve_utility_target(
        deployment_id or "summary_default",
        "chat_default",
        required_capability="chat",
    )
    if PROVIDER_REGISTRY is None:
        raise RuntimeError("Provider registry is not initialized.")
    provider = PROVIDER_REGISTRY.get_chat_provider(target)

    model_input: ModelInput = [
        {
            "role": "system",
            "content": (
                "You perform OCR on user-supplied images. Return only the visible text, with sensible line breaks. "
                "Do not summarize, explain, or guess. If there is no clearly legible text, return exactly: [no legible text]"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        f"File name: {file_row.get('name') or file_row.get('id') or 'image'}"
                        "Read and transcribe any visible text in this image. Preserve line breaks where practical."
                    ),
                },
                {"type": "input_image", "image_url": data_url},
            ],
        },
    ]
    result = provider.complete(target, model_input, request_options={"max_output_tokens": 500})
    text = re.sub(r"{3,}", "", (result.text or "").strip())
    if not text:
        raise ValueError("The model returned an empty OCR response.")
    if text.strip().lower() == "[no legible text]":
        return None, target.model
    return text, target.model


def _preview_content(c):
    if c is None:
        return ""
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for p in c:
            t = (p.get("type") or "").strip()
            if t == "input_text":
                parts.append(p.get("text") or "")
            elif t == "input_image":
                url = p.get("image_url") or ""
                parts.append(f"[input_image data_url len={len(url)}]")
            else:
                parts.append(json.dumps(p, ensure_ascii=False))
        return "\n".join(parts)
    return str(c)

def _http_from_value_error(e: ValueError) -> None:
    msg = str(e).strip() or "Invalid request."
    # crude but effective for now; tighten later if you want
    if "not found" in msg.lower():
        raise HTTPException(status_code=404, detail=msg)
    raise HTTPException(status_code=400, detail=msg)

def load_model_catalog() -> ModelCatalog:
    path = Path(__file__).parent / "model_catalog.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print("Failed to load model_catalog.json:", e)
    return {}

# endregion

# region Base API stuffs

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"\n[ERROR] {request.method} {request.url.path} -> {type(exc).__name__}: {exc}")
    print(tb)

    payload: dict[str, Any] = {
        "detail": "Internal Server Error",
        "path": request.url.path,
    }
    if DEBUG_ERRORS:
        payload["error"] = f"{type(exc).__name__}: {exc}"
        # Keep it readable; last 30 lines is usually enough
        payload["traceback_tail"] = tb.splitlines()[-30:]

    return JSONResponse(payload, status_code=500)

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/debug/routes")
def api_debug_routes():
    return [getattr(r, "path", None) for r in app.router.routes]

@app.get("/api/debug/db")
def api_debug_db():
    return JSONResponse(db_debug_info())

@app.get("/api/health")
def health():
    target = _get_default_chat_target()
    return JSONResponse(
        {
            "ok": True,
            "default_chat_deployment": target.id,
            "provider": target.provider_id,
            "model": target.model,
        }
    )

#endregion

# region Query Config Helpers

def _query_setting_key(key: str) -> str:
    return f"query.{key}"

def _get_effective_query_setting(project_id: int | None, key: str, env_default: str) -> str:
    from .db import get_app_setting
    if project_id is not None:
        v = get_app_setting(_query_setting_key(key), None, "project", str(project_id))
        if v is not None and str(v).strip() != "":
            return str(v)
    v = get_app_setting(_query_setting_key(key), None, "global", "")
    if v is not None and str(v).strip() != "":
        return str(v)
    return env_default

#endregion

# -------------------------
# API Endpoints
# -------------------------

# region App Config Endpoints

@app.get("/api/ui_config")
def api_ui_config():
    cfg = load_ui_config()
    return JSONResponse(
        {
            "local_timezone": cfg.local_timezone,
            "context_preview_limit_min": cfg.context_preview_limit_min,
            "context_preview_limit_max": cfg.context_preview_limit_max,
            "min_rag_query_text_len": cfg.min_rag_query_text_len,
            "context_idle_ms": cfg.context_idle_ms,
            "transcript_idle_ms": cfg.transcript_idle_ms,
            "debug_boot": cfg.debug_boot,
        }
    )

@app.get("/api/app_config")
def api_app_config():
    cfg = load_app_config()
    return JSONResponse(
        {
            "search_chat_history": cfg.search_chat_history,
        }
    )

@app.post("/api/app_config")
def api_update_app_config(req: AppConfigUpdateRequest):
    if req.search_chat_history is not None:
        set_app_setting(
            APP_KEYS.search_chat_history,
            "1" if req.search_chat_history else "0",
        )

    cfg = load_app_config()
    return JSONResponse(
        {
            "ok": True,
            "search_chat_history": cfg.search_chat_history,
        }
    )

@app.get("/api/query_settings")
def api_get_query_settings(scope_type: str = "global", scope_id: str = ""):
    from .db import get_app_setting

    qcfg = load_retrieval_config()

    scope_type = (scope_type or "global").strip().lower()
    scope_id = (scope_id or "").strip()

    if scope_type == "project" and scope_id:
        project_id = int(scope_id)
    else:
        project_id = None
        scope_type = "global"
        scope_id = ""

    effective_query_include = _get_effective_query_setting(project_id, "include", qcfg.query_include)
    effective_query_expand = _get_effective_query_setting(project_id, "expand_results", qcfg.query_expand_results)
    effective_max_files = _get_effective_query_setting(project_id, "max_full_files", str(qcfg.query_max_full_files))
    effective_max_memories = _get_effective_query_setting(project_id, "max_full_memories", str(qcfg.query_max_full_memories))
    effective_max_chats = _get_effective_query_setting(project_id, "max_full_chats", str(qcfg.query_max_full_chats))

    local_query_include = get_app_setting(_query_setting_key("include"), None, scope_type, scope_id)
    local_query_expand = get_app_setting(_query_setting_key("expand_results"), None, scope_type, scope_id)
    local_max_files = get_app_setting(_query_setting_key("max_full_files"), None, scope_type, scope_id)
    local_max_memories = get_app_setting(_query_setting_key("max_full_memories"), None, scope_type, scope_id)
    local_max_chats = get_app_setting(_query_setting_key("max_full_chats"), None, scope_type, scope_id)

    effective_expand_min_hits = _get_effective_query_setting(
        project_id,
        "expand_min_artifact_hits",
        str(qcfg.query_expand_min_artifact_hits),
    )
    effective_chat_window_before = _get_effective_query_setting(
        project_id,
        "expand_chat_window_before",
        str(qcfg.query_expand_chat_window_before),
    )
    effective_chat_window_after = _get_effective_query_setting(
        project_id,
        "expand_chat_window_after",
        str(qcfg.query_expand_chat_window_after),
    )    

    local_expand_min_hits = get_app_setting(
        _query_setting_key("expand_min_artifact_hits"),
        None,
        scope_type,
        scope_id,
    )
    local_chat_window_before = get_app_setting(
        _query_setting_key("expand_chat_window_before"),
        None,
        scope_type,
        scope_id,
    )
    local_chat_window_after = get_app_setting(
        _query_setting_key("expand_chat_window_after"),
        None,
        scope_type,
        scope_id,
    )
    return JSONResponse({
        "scope_type": scope_type,
        "scope_id": scope_id,
        "query_include": local_query_include,
        "query_expand_results": local_query_expand,
        "query_max_full_files": int(local_max_files) if local_max_files not in (None, "") else None,
        "query_max_full_memories": int(local_max_memories) if local_max_memories not in (None, "") else None,
        "query_max_full_chats": int(local_max_chats) if local_max_chats not in (None, "") else None,
        "query_expand_min_artifact_hits": int(local_expand_min_hits) if local_expand_min_hits not in (None, "") else None,
        "query_expand_chat_window_before": int(local_chat_window_before) if local_chat_window_before not in (None, "") else None,
        "query_expand_chat_window_after": int(local_chat_window_after) if local_chat_window_after not in (None, "") else None,

        "effective_query_include": _normalize_csv_set(effective_query_include, QUERY_INCLUDE_ALLOWED),
        "effective_query_expand_results": _normalize_csv_set(effective_query_expand, QUERY_EXPAND_ALLOWED),
        "effective_query_max_full_files": int(effective_max_files),
        "effective_query_max_full_memories": int(effective_max_memories),
        "effective_query_max_full_chats": int(effective_max_chats),
        "effective_query_expand_min_artifact_hits": int(effective_expand_min_hits),
        "effective_query_expand_chat_window_before": int(effective_chat_window_before),
        "effective_query_expand_chat_window_after": int(effective_chat_window_after),
    })

@app.post("/api/query_settings")
def api_update_query_settings(req: QuerySettingsUpdateRequest):
    scope_type = (req.scope_type or "global").strip().lower()
    scope_id = (req.scope_id or "").strip()

    if scope_type not in ("global", "project"):
        raise HTTPException(status_code=400, detail="scope_type must be global or project")

    if scope_type == "global":
        scope_id = ""

    if req.query_include is not None:
        set_app_setting(
            _query_setting_key("include"),
            _normalize_csv_set(req.query_include, QUERY_INCLUDE_ALLOWED),
            scope_type,
            scope_id,
        )

    if req.query_expand_results is not None:
        set_app_setting(
            _query_setting_key("expand_results"),
            _normalize_csv_set(req.query_expand_results, QUERY_EXPAND_ALLOWED),
            scope_type,
            scope_id,
        )

    if req.query_max_full_files is not None:
        set_app_setting(_query_setting_key("max_full_files"), str(int(req.query_max_full_files)), scope_type, scope_id)

    if req.query_max_full_memories is not None:
        set_app_setting(_query_setting_key("max_full_memories"), str(int(req.query_max_full_memories)), scope_type, scope_id)

    if req.query_max_full_chats is not None:
        set_app_setting(_query_setting_key("max_full_chats"), str(int(req.query_max_full_chats)), scope_type, scope_id)

    if req.query_expand_min_artifact_hits is not None:
        if req.query_expand_min_artifact_hits is not None:
            min_hits = max(1, int(req.query_expand_min_artifact_hits))
        set_app_setting(
            _query_setting_key("expand_min_artifact_hits"),
            str(min_hits),
            scope_type,
            scope_id,
        )

    if req.query_expand_chat_window_before is not None:
        set_app_setting(
            _query_setting_key("expand_chat_window_before"),
            str(max(0, int(req.query_expand_chat_window_before))),
            scope_type,
            scope_id,
        )

    if req.query_expand_chat_window_after is not None:
        set_app_setting(
            _query_setting_key("expand_chat_window_after"),
            str(max(0, int(req.query_expand_chat_window_after))),
            scope_type,
            scope_id,
        )
                
    invalidate_all_context_cache()
    return api_get_query_settings(scope_type=scope_type, scope_id=scope_id)

# endregion

# region Chat Endpoints

@app.post("/api/new", response_model=NewChatResponse)
def new_chat():
    cid = str(uuid.uuid4())
    create_conversation(cid)
    return {"conversation_id": cid}


def _build_citation_rows_from_context(ctx: RowDict | None) -> list[RowDict]:
    if not ctx:
        return []

    retrieved_meta = ctx.get("retrieved_chunk_meta") or []
    if not retrieved_meta:
        return []

    rows_by_chunk_id: dict[int, RowDict] = {}
    for row in (ctx.get("retrieved_chunks_final") or []):
        chunk_id = row.get("chunk_id")
        if chunk_id is None:
            continue
        try:
            rows_by_chunk_id[int(chunk_id)] = row
        except Exception:
            continue

    citations: list[RowDict] = []
    for rank, meta in enumerate(retrieved_meta, start=1):
        chunk_id = meta.get("chunk_id")
        if chunk_id is None:
            continue

        try:
            chunk_id_int = int(chunk_id)
        except Exception:
            continue

        row = rows_by_chunk_id.get(chunk_id_int) or {}
        retrieval_channels = row.get("retrieval_channels") or []
        retrieval_channel = "+".join(
            str(ch).strip()
            for ch in retrieval_channels
            if str(ch).strip()
        ) or None

        citations.append({
            "corpus_chunk_id": chunk_id_int,
            "artifact_id": meta.get("artifact_id"),
            "source_kind": meta.get("source_kind"),
            "source_id": meta.get("source_id"),
            "retrieval_channel": retrieval_channel,
            "retrieval_rank": rank,
            "retrieval_score": meta.get("score"),
            "matched_text": meta.get("preview_text"),
        })

    return citations


def _persist_citations_for_assistant_message(assistant_message_id: int, ctx: RowDict | None) -> None:
    if not assistant_message_id:
        return

    citations = _build_citation_rows_from_context(ctx)
    if not citations:
        return

    try:
        replace_citations_for_message(
            assistant_message_id=assistant_message_id,
            citations=citations,
        )
    except Exception as e:
        log_warn(f"Citation persistence failed for assistant message {assistant_message_id}: {e}")



_TOOL_BLOCK_FENCE_RE = re.compile(r"```tool\s*\{.*?\}\s*```", re.DOTALL | re.IGNORECASE)
_TOOL_TRIGGER_RE = re.compile(r"\b(read|reading|continue|section|chapter|page|passage|chunk|artifact|resume|next)\b", re.IGNORECASE)
_TRIVIAL_TOOL_WRAPPER_RE = re.compile(
    r"^(?:[\s\-–—:,.!]*|(?:okay|ok|sure|certainly|i(?:'ll| will)|let me|using|calling|requesting|fetching|loading)\b[\s\-–—:,.!]*)*$",
    re.IGNORECASE,
)


def _tooling_enabled(tool_cfg, tool_registry) -> bool:
    return bool(
        tool_cfg
        and tool_cfg.enabled
        and tool_cfg.allow_assistant_tool_blocks
        and tool_registry is not None
        and tool_registry.list_enabled()
    )


def _tool_text_without_blocks(text: str) -> str:
    return _TOOL_BLOCK_FENCE_RE.sub("", text or "").strip()


def _tool_wrapper_text(text: str) -> str:
    return _tool_text_without_blocks(text or "")


def _tool_remainder_is_trivial(text: str) -> bool:
    remainder = _tool_wrapper_text(text or "")
    if not remainder:
        return True
    if len(remainder) <= 80 and _TRIVIAL_TOOL_WRAPPER_RE.match(remainder):
        return True
    return False


def _response_requests_tool_execution(text: str, tool_registry: ToolRegistry | None) -> bool:
    if not tool_registry:
        return False
    requests = tool_registry.extract_requests_from_text(text or "")
    if not requests:
        return False
    remainder = _tool_wrapper_text(text or "")
    if not remainder:
        return True
    if len(remainder) <= 400:
        return True
    return _tool_remainder_is_trivial(text or "")


def _is_tool_prompt_message(msg: dict[str, Any]) -> bool:
    if (msg.get("role") or "") != "system":
        return False
    content = msg.get("content")
    return isinstance(content, str) and content.lstrip().startswith("TOOL USE")


def _remove_tool_prompt_messages(model_input: ModelInput) -> ModelInput:
    return [msg for msg in model_input if not _is_tool_prompt_message(msg)]


def _create_upload_scaffold_event(
    *,
    conversation_id: str | None,
    scope_type: str,
    files: list[dict[str, Any]],
) -> None:
    cid = (conversation_id or "").strip()
    if not cid or not files:
        return

    scope_label = (scope_type or "global").strip().lower() or "global"
    body_lines = [f"Uploaded {len(files)} file(s) to {scope_label} scope.", ""]
    output_rows: list[dict[str, Any]] = []
    for row in files:
        name = (row.get("name") or row.get("original_name") or "(file)").strip()
        artifact_id = (row.get("artifact_id") or "").strip()
        source_kind = (row.get("source_kind") or "").strip()
        status_bits = []
        if artifact_id:
            status_bits.append(f"artifact_id={artifact_id}")
        if source_kind:
            status_bits.append(f"source_kind={source_kind}")
        suffix = f" [{' ; '.join(status_bits)}]" if status_bits else ""
        body_lines.append(f"- {name}{suffix}")
        output_rows.append({
            "file_id": row.get("id"),
            "name": name,
            "artifact_id": artifact_id or None,
            "source_kind": source_kind or None,
            "scope_type": scope_label,
        })

    create_conversation_scaffold_event(
        conversation_id=cid,
        message_id=None,
        event_kind="file_upload",
        title="File upload",
        body_text="\n".join(body_lines).strip(),
        input_json={"scope_type": scope_label, "file_count": len(files)},
        output_json={"files": output_rows},
        status="ok",
    )


def _tool_result_to_input_message(result: ToolResult) -> dict[str, Any]:
    payload = {
        "ok": result.ok,
        "tool": result.tool,
        "result": result.result,
        "error": result.error,
    }
    body = [
        "TOOL RESULT",
        f"Tool: {result.tool}",
        f"OK: {'true' if result.ok else 'false'}",
        "",
        "JSON:",
        json.dumps(payload, ensure_ascii=False, indent=2),
    ]
    return {"role": "user", "content": "\n".join(body).strip()}


def _persist_tool_event(
    *,
    conversation_id: str,
    message_id: int | None,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> int | None:
    try:
        body_lines = [
            f"Tool: {request.tool}",
            f"Status: {'ok' if result.ok else 'error'}",
        ]
        if result.display_text:
            body_lines.extend(["", result.display_text.strip()])
        elif result.error:
            body_lines.extend(["", result.error.strip()])
        return create_conversation_scaffold_event(
            conversation_id=conversation_id,
            message_id=message_id,
            event_kind=result.event_kind or "tool_result",
            status="ready" if result.ok else "error",
            title=f"Tool · {request.tool}",
            body_text="\n".join(body_lines).strip(),
            input_json={"tool": request.tool, "arguments": request.arguments},
            output_json=result.as_dict(),
        )
    except Exception as exc:
        log_warn(f"Tool scaffold event persistence failed for {request.tool}: {exc}")
        return None


def _attach_scaffold_events_to_message(event_ids: list[int], message_id: int | None) -> None:
    if not message_id:
        return
    for event_id in event_ids:
        try:
            update_conversation_scaffold_event(event_id=event_id, message_id=message_id)
        except Exception as exc:
            log_warn(f"Tool scaffold event attachment failed for event {event_id}: {exc}")


def _stringify_recent_notes(notes: Any) -> str:
    if notes is None:
        return ""
    if isinstance(notes, str):
        return notes.strip()
    try:
        return json.dumps(notes, ensure_ascii=False)
    except Exception:
        return str(notes).strip()


def _maybe_capture_reading_notes_for_result(
    *,
    target,
    conversation_id: str,
    user_text: str,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> ToolResult:
    if not result.ok or request.tool not in {"artifact.read_section", "artifact.read_next"}:
        return result

    payload = dict(result.result or {})
    section = payload.get("section") or {}
    session = payload.get("session") or {}

    session_id = payload.get("session_id") or session.get("id") or request.arguments.get("session_id")
    ordinal = section.get("ordinal") or request.arguments.get("ordinal") or (payload.get("next_step") or {}).get("ordinal")
    artifact_id = str(payload.get("artifact_id") or session.get("artifact_id") or request.arguments.get("artifact_id") or "").strip()
    current_text = str(payload.get("text") or "").strip()

    if not session_id or not ordinal or not artifact_id or not current_text:
        return result

    try:
        session_id = int(session_id)
        ordinal = int(ordinal)
    except Exception:
        return result

    session_row = get_artifact_reading_session(session_id)
    step_row = get_artifact_reading_step(session_id, ordinal)
    steps = list_artifact_reading_steps(session_id)
    if not session_row or not step_row or not steps:
        return result

    question_sets = load_reading_questions()
    readiness = get_artifact_readiness(artifact_id)
    strategy = coerce_reading_strategy(
        session_row.get("strategy_json"),
        source_kind=(payload.get("source_kind") or (readiness.source_kind if readiness else "")),
        title=(payload.get("title") or (readiness.title if readiness else artifact_id)),
        user_text=user_text,
        available_modes=sorted(question_sets.keys()),
    )
    selected_modes = strategy.get("modes") or ["core", "reader_experience", "meta"]

    recent_done = [s for s in steps if int(s.get("ordinal") or 0) < ordinal and s.get("notes")]
    recent_done = recent_done[-3:]
    recent_notes_text = "".join(
        f"Section {int(s.get('ordinal') or 0)} notes: {_stringify_recent_notes(s.get('notes'))}"
        for s in recent_done
        if _stringify_recent_notes(s.get("notes"))
    )

    is_final_step = ordinal >= max(int(s.get("ordinal") or 0) for s in steps)
    artifact_summary_text = (readiness.summary_text if (is_final_step and readiness and readiness.summary_text) else None)

    system_prompt, user_prompt = build_reading_notes_prompts(
        title=str(payload.get("title") or (readiness.title if readiness else artifact_id)),
        artifact_id=artifact_id,
        source_kind=str(payload.get("source_kind") or (readiness.source_kind if readiness else "")),
        section_label=str(section.get("label") or f"Section {ordinal}"),
        section_ordinal=ordinal,
        step_count=len(steps),
        selected_modes=selected_modes,
        question_sets=question_sets,
        current_text=current_text,
        summary_so_far=str(session_row.get("summary_so_far") or ""),
        recent_notes_text=recent_notes_text or None,
        artifact_summary_text=artifact_summary_text,
    )

    sum_cfg = load_summary_config()
    try:
        complete_fn, _analysis_target = _make_utility_completion(target.id)
        raw = complete_fn(system_prompt, user_prompt, int(sum_cfg.reading_notes_max_tokens or 1400))
        parsed = parse_reading_notes_output(raw) or {}
        notes = parsed.get("notes") or {"raw_text": raw.strip()}
        summary_so_far = str(parsed.get("summary_so_far") or "").strip() or str(session_row.get("summary_so_far") or "").strip()

        updated_step = update_artifact_reading_step(session_id, ordinal, status="done", notes=notes)
        updated_session = update_artifact_reading_session(
            session_id,
            current_section_ordinal=ordinal,
            current_chunk_position=int(step_row.get("chunk_end") or 0),
            summary_so_far=summary_so_far,
            status=("complete" if is_final_step else "active"),
        )

        try:
            create_conversation_scaffold_event(
                conversation_id=conversation_id,
                message_id=None,
                event_kind="artifact_reading_notes",
                status="ready",
                title=f"Reading notes · {artifact_id}",
                body_text=f"Captured reading notes for section {ordinal}.",
                input_json={"tool": request.tool, "artifact_id": artifact_id, "session_id": session_id, "ordinal": ordinal},
                output_json={
                    "summary_so_far": summary_so_far,
                    "notes": notes,
                    "modes": selected_modes,
                    "is_final_step": is_final_step,
                },
            )
        except Exception as exc:
            log_warn(f"Reading notes scaffold event persistence failed for session {session_id}: {exc}")

        payload["session"] = updated_session
        payload["session_id"] = session_id
        payload["section"] = dict(section)
        payload["section"]["ordinal"] = ordinal
        payload["session_notes"] = {
            "summary_so_far": summary_so_far,
            "notes": notes,
            "modes": selected_modes,
            "is_final_step": is_final_step,
        }
        return ToolResult(
            ok=True,
            tool=result.tool,
            result=payload,
            error=None,
            display_text=((result.display_text or "").rstrip('.') + '. Captured reading notes.').strip(),
            event_kind=result.event_kind,
        )
    except Exception as exc:
        log_warn(f"Reading notes capture failed for session {session_id}: {exc}")
        return result


def _execute_tool_requests(
    *,
    target,
    tool_registry: ToolRegistry,
    conversation_id: str,
    user_text: str,
    requests: list[ToolInvocationRequest],
) -> tuple[list[ToolResult], list[int]]:
    project_id = None
    if conversation_id:
        try:
            with db_session() as conn:
                project_id = get_conversation_project_id(conn, conversation_id)
        except Exception as exc:
            log_warn(f"Tool execution could not resolve project for conversation {conversation_id}: {exc}")

    exec_ctx = ToolExecutionContext(
        conversation_id=conversation_id,
        project_id=project_id,
        user_text=user_text,
    )
    out: list[ToolResult] = []
    event_ids: list[int] = []
    for request in requests:
        try:
            result = tool_registry.execute(request, ctx=exec_ctx)
            result = _maybe_capture_reading_notes_for_result(
                target=target,
                conversation_id=conversation_id,
                user_text=user_text,
                request=request,
                result=result,
            )
        except Exception as exc:
            result = ToolResult(
                ok=False,
                tool=request.tool,
                error=f"{type(exc).__name__}: {exc}",
            )
        event_id = _persist_tool_event(
            conversation_id=conversation_id,
            message_id=None,
            request=request,
            result=result,
        )
        if event_id:
            event_ids.append(int(event_id))
        out.append(result)
    return out, event_ids


def _should_attempt_tool_preflight(
    *,
    user_text: str,
    ctx: RowDict | None,
    tool_cfg,
    tool_registry: ToolRegistry | None,
) -> bool:
    if not _tooling_enabled(tool_cfg, tool_registry):
        return False

    if _TOOL_TRIGGER_RE.search(user_text or ""):
        return True

    for msg in (ctx or {}).get("whole_artifact_messages") or []:
        content = msg.get("content")
        if not isinstance(content, str):
            continue
        first = (content.splitlines() or [""])[0].strip()
        if first in {"ARTIFACT READING PLAN", "ARTIFACT INDEX", "ARTIFACT SUMMARY"}:
            return True
    return False


def _expand_input_with_tool_requests(
    *,
    target,
    base_input: ModelInput,
    conversation_id: str,
    user_text: str,
    tool_cfg,
    tool_registry: ToolRegistry | None,
    user_message_id: int | None = None,
    initial_assistant_text: str | None = None,
) -> tuple[ModelInput, str | None, bool, list[int]]:
    if not _tooling_enabled(tool_cfg, tool_registry):
        return list(base_input), initial_assistant_text, False, []
    if PROVIDER_REGISTRY is None:
        raise RuntimeError("Provider registry is not initialized.")
    assert tool_registry is not None

    provider = PROVIDER_REGISTRY.get_chat_provider(target)
    working_input: ModelInput = list(base_input)
    remaining_calls = max(1, int(tool_cfg.max_calls_per_message))
    used_tools = False
    pending_text = initial_assistant_text
    event_ids: list[int] = []

    while remaining_calls > 0:
        if pending_text is None:
            result = provider.complete(target, working_input)
            pending_text = strip_zeitgeber_prefix(result.text or "")

        requests = tool_registry.extract_requests_from_text(pending_text or "")
        if not _response_requests_tool_execution(pending_text or "", tool_registry):
            return working_input, pending_text, used_tools, event_ids

        working_input.append({"role": "assistant", "content": pending_text or ""})
        allowed = requests[:remaining_calls]
        remaining_calls -= len(allowed)
        tool_results, new_event_ids = _execute_tool_requests(
            target=target,
            tool_registry=tool_registry,
            conversation_id=conversation_id,
            user_text=user_text,
            requests=allowed,
        )
        event_ids.extend(new_event_ids)
        for result in tool_results:
            working_input.append(_tool_result_to_input_message(result))

        used_tools = True
        pending_text = None

    return working_input, None, used_tools, event_ids


async def _expand_input_with_tool_requests_async(**kwargs):
    loop = asyncio.get_running_loop()
    fn = partial(_expand_input_with_tool_requests, **kwargs)
    return await loop.run_in_executor(None, fn)

@app.post("/api/chat")
def chat(req: ChatRequest, model: str | None = None):
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        create_conversation(cid)
    # Call before build_model_input to ensure that we use it to search RAG
    heal = ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    raw_user_message = req.message or ""
    full = postprocess_text(raw_user_message)
    user_message_id: int | None = None
    if full:
        user_message_id = add_message(cid, "user", full)
    try:
        ingest_urls_from_user_message(
            conversation_id=cid,
            request_message_id=user_message_id,
            raw_message=raw_user_message,
            max_urls=3,
            fetch_method="python",
        )
    except Exception as e:
        log_warn(f"URL ingest failed for conversation {cid}: {e}")

    ctx = build_context(cid, full, include_preview=False)
    raw_input = build_model_input(
        cid,
        full,
        ctx=ctx,
        tool_cfg=tool_cfg,
        tool_registry=TOOL_REGISTRY,
    )

    requested_model = (req.model or model or "").strip()
    if PROVIDER_REGISTRY is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    target = PROVIDER_REGISTRY.resolve_chat_target(requested_model or None)
    provider = PROVIDER_REGISTRY.get_chat_provider(target)

    preflight_input = raw_input
    preflight_terminal_text: str | None = None
    used_preflight_tools = False
    pending_tool_event_ids: list[int] = []

    if _should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=TOOL_REGISTRY):
        try:
            preflight_input, preflight_terminal_text, used_preflight_tools, pending_tool_event_ids = _expand_input_with_tool_requests(
                target=target,
                base_input=raw_input,
                conversation_id=cid,
                user_text=full,
                tool_cfg=tool_cfg,
                tool_registry=TOOL_REGISTRY,
                user_message_id=user_message_id,
            )
        except Exception as exc:
            log_warn(f"Tool preflight failed for conversation {cid}: {exc}")
            preflight_input = raw_input
            preflight_terminal_text = None
            used_preflight_tools = False
            pending_tool_event_ids = []

    def gen():
        final_text = ""
        try:
            if used_preflight_tools:
                wrapper_text = _tool_wrapper_text(preflight_terminal_text or "")
                if wrapper_text:
                    yield wrapper_text + ""
                follow_input = _remove_tool_prompt_messages(preflight_input)
                parts: list[str] = []
                for delta in provider.stream_text(target, follow_input):
                    parts.append(delta)
                    yield delta
                final_text = postprocess_text((wrapper_text + "" if wrapper_text else "") + "".join(parts))
            elif preflight_terminal_text is not None:
                final_text = postprocess_text(preflight_terminal_text)
                if final_text:
                    yield final_text
            else:
                parts: list[str] = []
                for delta in provider.stream_text(target, raw_input):
                    parts.append(delta)
                    yield delta

                streamed_text = strip_zeitgeber_prefix("".join(parts))
                if _response_requests_tool_execution(streamed_text, TOOL_REGISTRY):
                    expanded_input, terminal_text, used_tools, stream_tool_event_ids = _expand_input_with_tool_requests(
                        target=target,
                        base_input=raw_input,
                        conversation_id=cid,
                        user_text=full,
                        tool_cfg=tool_cfg,
                        tool_registry=TOOL_REGISTRY,
                        user_message_id=user_message_id,
                        initial_assistant_text=streamed_text,
                    )
                    if used_tools:
                        pending_tool_event_ids.extend(stream_tool_event_ids)
                        if terminal_text is None:
                            follow_input = _remove_tool_prompt_messages(expanded_input)
                            follow_parts: list[str] = []
                            for delta in provider.stream_text(target, follow_input):
                                follow_parts.append(delta)
                                yield delta
                            final_text = postprocess_text("".join(follow_parts))
                        else:
                            final_text = postprocess_text(terminal_text)
                            if final_text:
                                yield final_text
                    else:
                        final_text = postprocess_text(streamed_text)
                else:
                    final_text = postprocess_text(streamed_text)

            if final_text:
                assistant_message_id = add_message(
                    cid,
                    "assistant",
                    final_text,
                    meta={
                        "model": target.model,
                        "provider": target.provider_id,
                        "deployment_id": target.id,
                    },
                )
                _attach_scaffold_events_to_message(pending_tool_event_ids, assistant_message_id)
                _persist_citations_for_assistant_message(assistant_message_id, ctx)
        except ProviderExecutionError as e:
            yield f"\n[server exception: {type(e).__name__}]"
        except Exception as e:
            yield f"\n[server exception: {type(e).__name__}]"

    resp = StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    return resp


async def _call_model(target, model_input):
    if PROVIDER_REGISTRY is None:
        raise RuntimeError("Provider registry is not initialized.")

    provider = PROVIDER_REGISTRY.get_chat_provider(target)
    loop = asyncio.get_running_loop()
    fn = partial(provider.complete, target, model_input)
    return await loop.run_in_executor(None, fn)


async def _sleep_ms(ms: int) -> None:
    await asyncio.sleep(ms / 1000.0)

def _strip_images(model_input: ModelInput) -> ModelInput:
    out = []
    for msg in model_input:
        c = msg.get("content")
        if isinstance(c, list):
            c = [p for p in c if isinstance(p, dict) and p.get("type") != "input_image"]
        out.append({**msg, "content": c})
    return out

def _strip_file_messages(model_input: ModelInput) -> ModelInput:
    # Your file messages are user-role messages with big “FILES:” text or image parts.
    # Easiest heuristic: drop any message whose content includes "FILES:" header,
    # OR has any input_image part.
    out = []
    for msg in model_input:
        c = msg.get("content")
        if isinstance(c, str) and c.startswith("FILES:"):
            continue
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "input_image" for p in c):
            continue
        out.append(msg)
    return out

def _trim_history(model_input: ModelInput, keep_last_n: int = 30) -> ModelInput:
    # Keep system message(s) at front, keep last N non-system messages.
    system = [m for m in model_input if m.get("role") == "system"]
    non_system = [m for m in model_input if m.get("role") != "system"]
    return system + non_system[-keep_last_n:]

async def call_model_with_recovery(target, model_input: ModelInput) -> RowDict:
    """
    Returns either {"ok": True, "text": "..."} or {"ok": False, "error": {...}}.
    """
    attempts: list[tuple[str, ModelInput, int]] = []

    # 1) Original input, retry once
    attempts.append(("original", model_input, 0))
    attempts.append(("original_retry", model_input, 250))

    # 2) Strip images, retry once
    mi_noimg = _strip_images(model_input)
    attempts.append(("no_images", mi_noimg, 0))
    attempts.append(("no_images_retry", mi_noimg, 250))

    # 3) Strip file messages (more aggressive)
    mi_textonly = _strip_file_messages(mi_noimg)
    attempts.append(("text_only", mi_textonly, 0))

    # 4) Trim history hard
    mi_trim = _trim_history(mi_textonly, keep_last_n=30)
    attempts.append(("trim30", mi_trim, 0))

    last_err_payload = None

    for label, mi, backoff_ms in attempts:
        if backoff_ms:
            await _sleep_ms(backoff_ms)

        try:
            result = await _call_model(target, mi)
            text = strip_zeitgeber_prefix(result.text or "")
            return {"ok": True, "text": text, "recovery": label}
        except ProviderExecutionError as e:
            payload = dict(e.payload or {})
            payload["recovery_step"] = label
            last_err_payload = payload

            # Only ladder on 500s. If it’s a 400/422, don’t spam retries—just return it.
            if payload.get("status_code") and int(payload["status_code"]) < 500:
                return {"ok": False, "error": last_err_payload}

    return {"ok": False, "error": last_err_payload or {"status_code": 500, "body": {"error": {"message": "Unknown error"}}}}

@app.post("/api/chat_ab")
async def chat_ab(req: ABChatRequest):
    """
    A/B endpoint that:
      - never breaks the UI on OpenAI errors
      - runs A and B in parallel
      - uses slot A as the shared tool planner when tooling is needed
      - returns structured {a:{ok,text|error}, b:{ok,text|error}}
    """
    tool_cfg = load_tool_config()
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        create_conversation(cid)

    heal = ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    raw_user_message = req.message or ""
    full = postprocess_text(raw_user_message)

    user_message_id: int | None = None
    if full:
        user_message_id = add_message(cid, "user", full)

    try:
        ingest_urls_from_user_message(
            conversation_id=cid,
            request_message_id=user_message_id,
            raw_message=raw_user_message,
            max_urls=3,
            fetch_method="python",
        )
    except Exception as e:
        log_warn(f"URL ingest failed for conversation {cid}: {e}")

    ctx = build_context(cid, full, include_preview=False)
    raw_input = build_model_input(
        cid,
        full,
        ctx=ctx,
        tool_cfg=tool_cfg,
        tool_registry=TOOL_REGISTRY,
    )

    model_a = (req.model_a or "").strip()
    model_b = (req.model_b or model_a).strip()

    if PROVIDER_REGISTRY is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    target_a = PROVIDER_REGISTRY.resolve_chat_target(model_a or None)
    target_b = PROVIDER_REGISTRY.resolve_chat_target(model_b or None)

    planner_text_a: str | None = None
    used_shared_tools = False
    final_input = raw_input
    shared_tool_event_ids: list[int] = []

    if _should_attempt_tool_preflight(user_text=full, ctx=ctx, tool_cfg=tool_cfg, tool_registry=TOOL_REGISTRY):
        try:
            expanded_input, planner_text_a, used_shared_tools, shared_tool_event_ids = await _expand_input_with_tool_requests_async(
                target=target_a,
                base_input=raw_input,
                conversation_id=cid,
                user_text=full,
                tool_cfg=tool_cfg,
                tool_registry=TOOL_REGISTRY,
                user_message_id=user_message_id,
            )
            final_input = _remove_tool_prompt_messages(expanded_input if used_shared_tools else raw_input)
        except Exception as exc:
            log_warn(f"Shared tool planning failed for conversation {cid}: {exc}")
            planner_text_a = None
            used_shared_tools = False
            shared_tool_event_ids = []
            final_input = _remove_tool_prompt_messages(raw_input)
    else:
        final_input = _remove_tool_prompt_messages(raw_input)

    ab_group = str(uuid.uuid4())

    a_res = None
    b_res = None

    async def run_b():
        nonlocal b_res
        b_res = await call_model_with_recovery(target_b, final_input)

    if used_shared_tools:
        async with anyio.create_task_group() as tg:
            async def run_a():
                nonlocal a_res
                a_res = await call_model_with_recovery(target_a, final_input)
            tg.start_soon(run_a)
            tg.start_soon(run_b)
    else:
        async with anyio.create_task_group() as tg:
            tg.start_soon(run_b)
            if planner_text_a is not None:
                a_res = {"ok": True, "text": strip_zeitgeber_prefix(planner_text_a or ""), "recovery": None}
            else:
                async def run_a_direct():
                    nonlocal a_res
                    a_res = await call_model_with_recovery(target_a, final_input)
                tg.start_soon(run_a_direct)

    assert a_res is not None and b_res is not None

    attached_shared_tool_events = False

    def store(slot: str, target, requested_model_name: str, res: RowDict):
        nonlocal attached_shared_tool_events
        if res.get("ok"):
            text = res.get("text") or ""
            full = postprocess_text(text)
            if full:
                assistant_message_id = add_message(cid, "assistant", full, meta={
                    "ab_group": ab_group,
                    "slot": slot,
                    "model": target.model,
                    "provider": target.provider_id,
                    "deployment_id": target.id,
                    "requested_model": requested_model_name,
                    "kind": "ab",
                    "recovery": res.get("recovery"),
                })
                if shared_tool_event_ids and not attached_shared_tool_events:
                    _attach_scaffold_events_to_message(shared_tool_event_ids, assistant_message_id)
                    attached_shared_tool_events = True
                _persist_citations_for_assistant_message(assistant_message_id, ctx)
        else:
            payload = res.get("error") or {}
            msg = extract_error_message(payload)
            status = payload.get("status_code")
            bubble = f"[Model {slot} error] {status or ''} {msg}".strip()
            full = postprocess_text(bubble)
            if full:
                add_message(
                    cid,
                    "assistant",
                    full,
                    meta={
                        "ab_group": ab_group,
                        "slot": slot,
                        "model": target.model,
                        "provider": target.provider_id,
                        "deployment_id": target.id,
                        "requested_model": requested_model_name,
                        "kind": "error",
                        "recovery_step": res["error"].get("recovery_step"),
                        **payload,
                    },
                )
    store("A", target_a, model_a, a_res)
    store("B", target_b, model_b, b_res)

    return JSONResponse({
        "conversation_id": cid,
        "ab_group": ab_group,
        "model_a": target_a.model,
        "model_b": target_b.model,
        "deployment_a": target_a.id,
        "deployment_b": target_b.id,
        "provider_a": target_a.provider_id,
        "provider_b": target_b.provider_id,
        "requested_model_a": model_a,
        "requested_model_b": model_b,
        "tool_planner_slot": "A",
        "used_shared_tools": used_shared_tools,
        "a": a_res,
        "b": b_res,
    })


@app.post("/api/ab/canonical")
def api_ab_canonical(req: ABCanonicalRequest):
    """
    Flip which variant in an A/B pair is treated as canonical for context.
    """
    slot = (req.slot or "").upper()
    if slot not in ("A", "B"):
        return JSONResponse({"ok": False, "error": "slot must be 'A' or 'B'"}, status_code=400)

    update_ab_canonical(req.conversation_id, req.ab_group, slot)
    return JSONResponse({"ok": True})

# endregion

# region Conversation Endpoints

@app.get("/api/conversations")
def api_conversations(
    include_archived: bool = False,
    limit: int = core_cfg.limit_api_conversations
):
    return JSONResponse(list_conversations(
        limit=limit, 
        include_archived=include_archived))

@app.get("/api/conversation/{conversation_id}/messages")
def api_conversation_messages(
    conversation_id: str,
    limit: int = core_cfg.limit_api_conversation_messages,
    mode: str = "raw",   # "raw" | "thread" | "canonical"
):
    """
    app.js calls this as: GET /api/conversation/{cid}/messages

    mode=raw       -> returns rows with meta (A/B grouping, timestamps, etc.)
    mode=canonical -> returns condensed role/content list (A/B canonical only)
    """
    if mode == "canonical":
        return JSONResponse(get_messages(conversation_id, limit=limit))
    if mode == "thread":
        return JSONResponse(list_conversation_history_with_scaffold_events(conversation_id))
    return JSONResponse(get_messages_raw(conversation_id, limit=limit))

@app.post("/api/conversations/{conversation_id}/project")
def api_move_conversation_project(conversation_id: str, req: MoveProjectRequest):
    project_id: int | None = None

    if req.project_id is not None:
        project_id = req.project_id
    elif req.project_name:
        proj = get_or_create_project(req.project_name)
        project_id = int(proj["id"])

    set_conversation_project(conversation_id, project_id)
    return {"conversation_id": conversation_id, "project_id": project_id}

@app.post("/api/conversations/{conversation_id}/archive")
def api_archive_conversation(conversation_id: str, req: ArchiveRequest):
    set_conversation_archived(conversation_id, req.archived)
    return {"conversation_id": conversation_id, "archived": req.archived}

@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: str):
    delete_conversation(conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}

# region Conversation Title Endpoints
# generally used in left-hand nav

@app.put("/api/conversation/{conversation_id}/title")
def api_set_title(conversation_id: str, req: TitleRequest):
    """
    app.js calls this as: PUT /api/conversation/{cid}/title { "title": "..." }
    """
    title = (req.title or "").strip() or "New chat"
    updated = update_conversation_title(conversation_id, title)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return JSONResponse({"ok": True, "title": title})

# Optional but handy for debugging / sanity:
@app.get("/api/conversation/{conversation_id}/title")
def api_get_title(conversation_id: str):
    t = get_conversation_title(conversation_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return JSONResponse({"title": t})

# endregion


@app.post("/api/conversations/{conversation_id}/summarize")
def api_summarize_conversation(conversation_id: str, sum_cfg: SummaryConfig | None = None):
    sum_cfg = sum_cfg or load_summary_config()

    try:
        title, transcript = get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    system_prompt = get_prompt(
        default_prompt=sum_cfg.summary_conversation_prompt,
        filepath=sum_cfg.summary_conversation_prompt_file,
        cfg_default="SUMMARY_CONVO_PROMPT",
        cfg_filepath="SUMMARY_CONVO_PROMPT_FILE",
    )

    try:
        complete_fn, target = _make_utility_completion(
            "summary_default",
        )

        summary_text = summarize_conversation_text(
            model=target.model,
            title=title,
            transcript=transcript,
            cfg=sum_cfg,
            system_prompt=system_prompt,
            complete_fn=complete_fn,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")

    summary_text = (summary_text or "").strip()
    if not summary_text:
        raise HTTPException(status_code=502, detail="Summarizer returned empty output.")

    summary_message = f"Summary of “{title}”:\n\n{summary_text}"
    full = postprocess_text(summary_message)

    if full:
        add_message(
            conversation_id,
            "assistant",
            full,
            meta={
                "summary": True,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
            },
        )
        save_conversation_summary_artifact(conversation_id, summary_text, target.model)

    return {
        "conversation_id": conversation_id,
        "summary": summary_text,
        "model": target.model,
        "provider": target.provider_id,
        "deployment_id": target.id,
    }

# region Conversation Transcript Endpoints

@app.post("/api/conversation/{conversation_id}/refresh_transcript_artifact")
def api_refresh_transcript_artifact(
    conversation_id: str,
    force_full: bool = False,
    reason: str = "manual",
):
    try:
        out = refresh_conversation_transcript_artifact(
            conversation_id,
            force_full=bool(force_full),
            reason=reason,
        )
        return JSONResponse(out)
    except ValueError as e:
        _http_from_value_error(e)


@app.get("/api/conversation/{conversation_id}/export_transcript")
def api_export_transcript(
    conversation_id: str,
    force_full: bool = False,
):
    try:
        # repair first so export reflects latest SQL state
        refresh_conversation_transcript_artifact(
            conversation_id,
            force_full=bool(force_full),
            reason="export",
        )

        title = get_conversation_title(conversation_id) or f"Conversation {conversation_id}"
        body = export_conversation_transcript_markdown(
            conversation_id,
            refresh_if_stale=False,
            force_full=False,
        )

        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_") or conversation_id
        filename = f"{safe_title}.transcript.md"

        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except ValueError as e:
        _http_from_value_error(e)



@app.post("/api/conversation/{conversation_id}/suggest_title")
def api_suggest_title(conversation_id: str):
    try:
        current_title, transcript = get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        complete_fn, target = _make_utility_completion(
            "title_default",
            "summary_default",
        )

        suggested = suggest_conversation_title_from_transcript(
            model=target.model,
            transcript=transcript,
            current_title=current_title or "New chat",
            complete_fn=complete_fn,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to suggest title: {e}")

    final_title = (suggested or "").strip() or "New chat"
    updated = update_conversation_title(conversation_id, final_title)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return JSONResponse(
        {
            "ok": True,
            "title": final_title,
            "model": target.model,
            "provider": target.provider_id,
            "deployment_id": target.id,
        }
    )


# endregion

@app.get("/api/conversation/{conversation_id}/context")
def api_conversation_context(
    conversation_id: str,
    user_text: str = "",
    preview_limit: int | None = None,
):
    ctx_cfg = load_context_config()
    if preview_limit is not None:
        ctx_cfg = ContextConfig(
            memory_pin_limit=ctx_cfg.memory_pin_limit,
            history_limit=ctx_cfg.history_limit,
            preview_limit=max(1, int(preview_limit)),
            estimate_model=ctx_cfg.estimate_model,
        )

    payload = build_context_panel_payload(
        conversation_id=conversation_id,
        user_text=user_text or "",
        ctx_cfg=ctx_cfg,
        tool_cfg=TOOL_CFG,
        tool_registry=TOOL_REGISTRY,
    )
    return JSONResponse(payload)


@app.get("/api/conversation/{conversation_id}/artifacts/debug")
def api_conversation_artifacts_debug(conversation_id: str):
    query_cfg = load_retrieval_config()
    data = get_scoped_artifact_debug(
        conversation_id,
        include_global=query_cfg.query_global_artifacts,
        preview_chars=180,
    )
    return JSONResponse(data)


def _normalize_scope_type(scope_type: str | None) -> str:
    st = (scope_type or "").strip().lower()
    if st in ("conversation", "chat"):
        return "conversation"
    if st == "project":
        return "project"
    return "global"


def _promote_targets_for_scope(scope_type: str, *, project_id: int | None = None) -> list[RowDict]:
    st = _normalize_scope_type(scope_type)
    targets: list[RowDict] = []
    if st == "conversation" and project_id is not None:
        targets.append({"label": "Promote to Project", "scope_type": "project", "scope_id": int(project_id), "scope_uuid": None})
    if st in ("conversation", "project"):
        targets.append({"label": "Promote to Global", "scope_type": "global", "scope_id": None, "scope_uuid": None})
    return targets


def _make_file_library_item(
    file_row: RowDict,
    *,
    inherited_from: str,
    project_id: int | None = None,
    project_title: str | None = None,
    conversation_title: str | None = None,
) -> RowDict:
    scope_type = _normalize_scope_type(file_row.get("scope_type"))
    mime_type = (file_row.get("mime_type") or "").strip() or None
    file_path = Path(str(file_row.get("path") or "")).expanduser()
    is_image = bool(file_path and is_image_file(file_path, mime_type))
    file_meta: RowDict = _load_json_object(file_row.get("meta_json"))

    import_note = (file_meta.get("import_note") or "").strip()
    image_caption = (file_meta.get("image_caption") or "").strip()
    image_ocr_text = (file_meta.get("image_ocr_text") or "").strip()
    file_scope_id = _coerce_optional_int(file_row.get("scope_id"))

    effective_project_title = project_title
    if not effective_project_title and scope_type == "project" and file_scope_id is not None:
        proj = next((p for p in list_projects(include_global=True) if _coerce_optional_int(p.get("id")) == file_scope_id), None)
        effective_project_title = proj.get("name") if proj else None

    effective_conversation_title = conversation_title
    if not effective_conversation_title and scope_type == "conversation" and file_row.get("scope_uuid"):
        effective_conversation_title = get_conversation_title(str(file_row.get("scope_uuid")))

    meta: list[str] = [f"MIME: {mime_type or 'unknown'}", f"Scope: {scope_type}"]
    if effective_project_title:
        meta.append(f"Project: {effective_project_title}")
    if effective_conversation_title:
        meta.append(f"Conversation: {effective_conversation_title}")
    if file_row.get("description"):
        meta.append(f"Description: {file_row.get('description')}")
    if image_caption:
        meta.append(f"Image summary: {image_caption}")
    if image_ocr_text:
        meta.append(f"OCR text: {image_ocr_text}")
    if import_note:
        meta.append(f"Import note: {import_note}")
    if file_row.get("provenance"):
        meta.append(f"Provenance: {file_row.get('provenance')}")

    badges: list[str] = []
    if is_image:
        badges.append("image")
    if image_caption:
        badges.append("captioned")
    if image_ocr_text:
        badges.append("ocr")

    return {
        "item_kind": "file",
        "id": file_row["id"],
        "title": file_row.get("name") or file_row["id"],
        "subtitle": file_row.get("description") or "",
        "description": file_row.get("description") or "",
        "meta": meta,
        "scope_type": scope_type,
        "scope_id": file_row.get("scope_id"),
        "scope_uuid": file_row.get("scope_uuid"),
        "scope_label": effective_conversation_title or effective_project_title,
        "updated_at": file_row.get("updated_at") or file_row.get("created_at"),
        "inherited_from": inherited_from,
        "badges": badges,
        "thumbnail_url": f"/api/files/{file_row['id']}/thumbnail" if is_image else None,
        "promote_targets": _promote_targets_for_scope(scope_type, project_id=project_id),
        "meta_json": file_meta,
        "provenance": file_row.get("provenance"),
    }


def _make_artifact_library_item(artifact_row: RowDict, *, inherited_from: str, project_id: int | None = None, conversation_title: str | None = None) -> RowDict:
    scope_type = _normalize_scope_type(artifact_row.get("scope_type"))
    source_kind = (artifact_row.get("source_kind") or "").strip()
    readiness = get_artifact_readiness(artifact_row["id"])
    badges: list[str] = []
    if readiness and readiness.has_summary:
        badges.append("summary")
    if readiness and readiness.has_index:
        badges.append("index")
    if source_kind in ("conversation:transcript", "conversation_transcript"):
        badges.append("reference-first transcript")

    meta: list[str] = [
        f"Source: {source_kind or 'artifact'}",
        f"Scope: {scope_type}",
    ]
    if conversation_title:
        meta.append(f"Conversation: {conversation_title}")
    if artifact_row.get("provenance"):
        meta.append(f"Provenance: {artifact_row.get('provenance')}")

    promote_targets: list[RowDict] = []
    promote_disabled_reason: str | None = None
    if source_kind == "file":
        promote_disabled_reason = "Promote the underlying file instead of the derived file artifact."
    else:
        promote_targets = _promote_targets_for_scope(scope_type, project_id=project_id)

    return {
        "item_kind": "artifact",
        "id": artifact_row["id"],
        "title": artifact_row.get("title") or artifact_row["id"],
        "subtitle": "",
        "meta": meta,
        "scope_type": scope_type,
        "updated_at": artifact_row.get("updated_at"),
        "inherited_from": inherited_from,
        "badges": badges,
        "promote_targets": promote_targets,
        "promote_disabled_reason": promote_disabled_reason,
    }


def _make_session_library_item(session_row: RowDict, *, inherited_from: str, conversation_title: str | None = None) -> RowDict:
    meta = [
        f"Mode: {session_row.get('mode') or 'reading'}",
        f"Status: {session_row.get('status') or 'active'}",
        f"Artifact: {session_row.get('artifact_title') or session_row.get('artifact_id')}",
    ]
    if conversation_title:
        meta.append(f"Conversation: {conversation_title}")
    return {
        "item_kind": "reading_session",
        "id": str(session_row.get("id")),
        "title": session_row.get("artifact_title") or f"Session {session_row.get('id')}",
        "subtitle": "",
        "meta": meta,
        "scope_type": "conversation",
        "updated_at": session_row.get("updated_at"),
        "inherited_from": inherited_from,
        "badges": [session_row.get("status") or "active"],
        "promote_targets": [],
    }


def _pack_library_section(key: str, title: str, groups: list[RowDict]) -> RowDict:
    live_groups = [g for g in groups if g.get("items")]
    return {"key": key, "title": title, "groups": live_groups}


@app.get("/api/conversation/{conversation_id}/library")
def api_conversation_library(conversation_id: str):
    conversation_title = get_conversation_title(conversation_id) or "Conversation"
    with db_session() as conn:
        project_id = get_conversation_project_id(conn=conn, conversation_id=conversation_id)

    project_label = None
    if project_id is not None:
        proj = next((p for p in list_projects(include_global=True) if int(p["id"]) == int(project_id)), None)
        project_label = proj.get("name") if proj else None

    files_groups = [
        {"key": "conversation", "title": "Conversation scope", "items": [_make_file_library_item(f, inherited_from="conversation", project_id=project_id, conversation_title=conversation_title) for f in list_files_for_conversation(conversation_id)]},
        {"key": "project", "title": "Inherited from project", "items": [_make_file_library_item(f, inherited_from="project", project_id=project_id, project_title=project_label) for f in (list_files_for_project(project_id) if project_id is not None else [])]},
        {"key": "global", "title": "Inherited from global", "items": [_make_file_library_item(f, inherited_from="global", project_id=project_id) for f in list_global_files()]},
    ]
    artifact_groups = [
        {"key": "conversation", "title": "Conversation scope", "items": [_make_artifact_library_item(a, inherited_from="conversation", project_id=project_id) for a in list_artifacts_for_conversation(conversation_id)]},
        {"key": "project", "title": "Inherited from project", "items": [_make_artifact_library_item(a, inherited_from="project", project_id=project_id) for a in (list_artifacts_for_project(project_id) if project_id is not None else [])]},
        {"key": "global", "title": "Inherited from global", "items": [_make_artifact_library_item(a, inherited_from="global", project_id=project_id) for a in list_global_artifacts()]},
    ]
    session_groups = [
        {"key": "conversation", "title": "Reading sessions in this conversation", "items": [_make_session_library_item(s, inherited_from="conversation") for s in list_artifact_reading_sessions(conversation_id=conversation_id, limit=200)]},
    ]
    return JSONResponse(
        {
            "scope_type": "conversation",
            "scope_id": conversation_id,
            "scope_label": conversation_title,
            "scope_note": "Showing items local to this conversation plus inherited project/global material. Reading plans are still derived live; reading-session state is durable and shown here.",
            "sections": [
                _pack_library_section("files", "Files", files_groups),
                _pack_library_section("artifacts", "Artifacts", artifact_groups),
                _pack_library_section("reading_sessions", "Reading Sessions", session_groups),
            ],
        }
    )


@app.get("/api/projects/{project_id}/library")
def api_project_library(project_id: int):
    projects = list_projects(include_global=True)
    project = next((p for p in projects if int(p["id"]) == int(project_id)), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    convs = [c for c in list_conversations(limit=1000000, include_archived=True) if int(c["project_id"]) == int(project_id)]
    conv_title_by_id = {c["id"]: (c.get("title") or c["id"]) for c in convs}

    descendant_files: list[RowDict] = []
    seen_files: set[str] = set()
    descendant_artifacts: list[RowDict] = []
    seen_artifacts: set[str] = set()
    for conv in convs:
        for f in list_files_for_conversation(conv["id"]):
            if f["id"] in seen_files:
                continue
            seen_files.add(f["id"])
            descendant_files.append(_make_file_library_item(f, inherited_from="conversation", project_id=project_id, conversation_title=conv_title_by_id.get(conv["id"])))
        for a in list_artifacts_for_conversation(conv["id"]):
            scope_type = _normalize_scope_type(a.get("scope_type"))
            if scope_type != "conversation":
                continue
            if a["id"] in seen_artifacts:
                continue
            seen_artifacts.add(a["id"])
            descendant_artifacts.append(_make_artifact_library_item(a, inherited_from="conversation", project_id=project_id, conversation_title=conv_title_by_id.get(conv["id"])))

    files_groups = [
        {"key": "project", "title": "Project scope", "items": [_make_file_library_item(f, inherited_from="project", project_id=project_id, project_title=(project.get("name") or f"Project {project_id}")) for f in list_files_for_project(project_id)]},
        {"key": "conversations", "title": "Conversation-scoped items in this project", "items": descendant_files},
        {"key": "global", "title": "Inherited from global", "items": [_make_file_library_item(f, inherited_from="global", project_id=project_id) for f in list_global_files()]},
    ]
    artifact_groups = [
        {"key": "project", "title": "Project scope", "items": [_make_artifact_library_item(a, inherited_from="project", project_id=project_id) for a in list_artifacts_for_project(project_id)]},
        {"key": "conversations", "title": "Conversation-scoped items in this project", "items": descendant_artifacts},
        {"key": "global", "title": "Inherited from global", "items": [_make_artifact_library_item(a, inherited_from="global", project_id=project_id) for a in list_global_artifacts()]},
    ]
    session_groups = [
        {"key": "project_sessions", "title": "Reading sessions across this project", "items": [_make_session_library_item(s, inherited_from="conversation", conversation_title=conv_title_by_id.get(s.get("conversation_id"))) for s in list_artifact_reading_sessions(project_id=project_id, limit=500)]},
    ]
    return JSONResponse(
        {
            "scope_type": "project",
            "scope_id": int(project_id),
            "scope_label": project.get("name") or f"Project {project_id}",
            "scope_note": "Showing project-scoped items, conversation-scoped descendants, and inherited global material. Reading plans are still derived live; durable reading-session state is shown here.",
            "sections": [
                _pack_library_section("files", "Files", files_groups),
                _pack_library_section("artifacts", "Artifacts", artifact_groups),
                _pack_library_section("reading_sessions", "Reading Sessions", session_groups),
            ],
        }
    )


@app.get("/api/library/global")
def api_global_library():
    return JSONResponse(
        {
            "scope_type": "global",
            "scope_id": "global",
            "scope_label": "Global Library",
            "scope_note": "Showing globally scoped files and artifacts. Reading sessions remain conversation-bound, so there is no global session bucket.",
            "sections": [
                _pack_library_section("files", "Files", [{"key": "global", "title": "Global scope", "items": [_make_file_library_item(f, inherited_from="global") for f in list_global_files()]}]),
                _pack_library_section("artifacts", "Artifacts", [{"key": "global", "title": "Global scope", "items": [_make_artifact_library_item(a, inherited_from="global") for a in list_global_artifacts()]}]),
                _pack_library_section("reading_sessions", "Reading Sessions", []),
            ],
        }
    )

# endregion

# region Memory Endpoints


@app.get("/api/conversation/{conversation_id}/citations")
def api_conversation_citations(conversation_id: str):
    title = get_conversation_title(conversation_id)
    items = list_citation_scope_cards_for_conversation(conversation_id)
    return JSONResponse(
        {
            "scope_type": "conversation",
            "scope_id": conversation_id,
            "scope_label": title or conversation_id,
            "items": items,
        }
    )


@app.get("/api/projects/{project_id}/citations")
def api_project_citations(project_id: int):
    projects = list_projects(include_global=True)
    project = next((p for p in projects if int(p["id"]) == int(project_id)), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    items = list_citation_scope_cards_for_project(project_id)
    return JSONResponse(
        {
            "scope_type": "project",
            "scope_id": int(project_id),
            "scope_label": project.get("name") or f"Project {project_id}",
            "items": items,
        }
    )

@app.get("/api/memories")
def api_list_memories(limit: int = 200):
    return JSONResponse(db_list_memories(limit=limit))

@app.post("/api/memories")
def api_create_memory(req: MemoryCreate):
    try:
        mem = db_create_memory(
            req.content,
            importance=req.importance,
            tags=req.tags,
            created_by=req.created_by,
            origin_kind=req.origin_kind,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
        )
        invalidate_all_context_cache()
        return JSONResponse(mem)
    except ValueError as e:
        _http_from_value_error(e)

@app.put("/api/memories/{memory_id}")
def api_update_memory(memory_id: str, req: MemoryUpdate):
    try:
        mem = db_update_memory(
            memory_id,
            req.content,
            importance=req.importance,
            tags=req.tags,
            created_by=req.created_by,
            origin_kind=req.origin_kind,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
        )
        invalidate_all_context_cache()
        return JSONResponse(mem)
    except ValueError as e:
        _http_from_value_error(e)


@app.delete("/api/memories/{memory_id}")
def api_delete_memory(memory_id: str):
    try:
        db_delete_memory(memory_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/memories/{memory_id}/link_project/{project_id}")
def api_memory_link_project(memory_id: str, project_id: int):
    try:
        db_memory_link_project(memory_id, project_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/memories/{memory_id}/link_project")
def api_memory_link_project_body(memory_id: str, req: MemoryLinkProjectRequest):
    try:
        pid: Optional[int] = None
        if req.project_id is not None:
            pid = int(req.project_id)
        elif req.project_name:
            proj = db_get_or_create_project(req.project_name)
            pid = int(proj["id"])
        else:
            raise ValueError("Provide project_id or project_name.")

        db_memory_link_project(memory_id, pid)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True, "project_id": pid})
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/memories/{memory_id}/link_conversation/{conversation_id}")
def api_memory_link_conversation(memory_id: str, conversation_id: str):
    try:
        db_memory_link_conversation(memory_id, conversation_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)

# endregion

# region Memory Pin Endpoints

@app.post("/api/memory/pins")
def api_add_memory_pin(req: PinRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    new_id = add_memory_pin(
        text,
        pin_kind=(req.pin_kind or "instruction"),
        title=req.title,
        scope_type=(req.scope_type or "global"),
        scope_id=req.scope_id,
    )   
    invalidate_all_context_cache()
    return JSONResponse({"ok": True, "id": new_id})

@app.delete("/api/memory/pins/{pin_id}")
def api_delete_memory_pin(pin_id: int):
    delete_memory_pin(pin_id)
    invalidate_all_context_cache()
    return JSONResponse({"ok": True})

@app.put("/api/memory/pins/{pin_id}")
def api_update_memory_pin(pin_id: int, req: PinRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    row = db_update_memory_pin(
        pin_id,
        text,
        pin_kind=req.pin_kind,
        title=req.title,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
    )
    invalidate_all_context_cache()
    return JSONResponse(row)

@app.post("/api/memory/pins/about_you")
def api_upsert_about_you_pin(req: AboutYouRequest):
    row = upsert_about_you_pin(
        nickname=req.nickname,
        age=req.age,
        occupation=req.occupation,
        more_about_you=req.more_about_you,
    )
    invalidate_all_context_cache()
    return JSONResponse(row)

@app.get("/api/memory/pins")
def api_memory_pins():
    return JSONResponse(list_memory_pins(limit=200))

@app.get("/api/memory/pins/about_you")
def api_get_about_you_pin():
    row = get_about_you_pin()
    if not row:
        return JSONResponse({
            "nickname": "",
            "age": "",
            "occupation": "",
            "more_about_you": "",
            "text": "",
        })
    value = row.get("value_json") or {}
    return JSONResponse({
        "nickname": value.get("nickname", ""),
        "age": value.get("age", ""),
        "occupation": value.get("occupation", ""),
        "more_about_you": value.get("more_about_you", ""),
        "text": row.get("text", ""),
        "id": row.get("id"),
    })

# endregion

# region Project Endpoints

@app.put("/api/projects/{project_id}")
def api_update_project(project_id: int, req: ProjectUpdateRequest):
    try:
        return JSONResponse(update_project(
            project_id,
            name=req.name,
            visibility=req.visibility,
            description=req.description,
            system_prompt=req.system_prompt,
            override_core_prompt=req.override_core_prompt,
            default_advanced_mode=req.default_advanced_mode,
        ))
    except ValueError as e:
        _http_from_value_error(e)


@app.get("/api/projects")
def api_get_projects():
    return {"projects": list_projects()}


@app.post("/api/projects/{project_id}/archive")
def api_archive_project(project_id: int, req: ArchiveRequest):
    try:
        set_project_hidden(project_id, req.archived)
        return {"project_id": project_id, "archived": bool(req.archived)}
    except ValueError as e:
        _http_from_value_error(e)


@app.get("/api/projects/{project_id}/delete_preview")
def api_project_delete_preview(project_id: int):
    try:
        return JSONResponse(get_project_delete_preview(project_id))
    except ValueError as e:
        _http_from_value_error(e)


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: int):
    try:
        return JSONResponse(delete_project(project_id))
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/projects")
def api_create_project(req: ProjectCreateRequest):
    try:
        # TODO add description
        proj = get_or_create_project(req.name, req.visibility)
        return proj
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/projects/{project_id}/assign_conversation/{conversation_id}")
def api_project_add_conversation(project_id: int, conversation_id: str):
    try:
        db_project_add_conversation(project_id, conversation_id, set_primary=True)
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)


@app.post("/api/projects/{project_id}/import_from/{source_id}")
def api_project_import(project_id: int, source_id: int, req: ImportRule):
    try:
        db_project_import(
            project_id=project_id,
            source_project_id=source_id,
            include_tags=req.include_tags,
            exclude_tags=req.exclude_tags,
            include_artifact_ids=req.include_artifact_ids,
        )
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/projects/{project_id}/files/{file_id}")
def api_project_add_file(project_id: int, file_id: str):
    try:
        db_project_add_file(project_id, file_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)
    
# endregion

# region File Endpoints

# region Upload Endpoints

@app.post("/api/files/preflight_upload")
def api_preflight_upload(req: FilePreflightRequest):
    out = []

    for item in req.files:
        dupes = list_files_by_sha256(item.sha256, include_deleted=False)
        same_name = list_files_same_name_any_scope(item.name, include_deleted=False)

        out.append({
            "name": item.name,
            "sha256": item.sha256,
            "duplicate_count": len(dupes),
            "duplicates": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "scope_type": f.get("scope_type"),
                    "scope_id": f.get("scope_id"),
                    "scope_uuid": f.get("scope_uuid"),
                    "path": f.get("path"),
                }
                for f in dupes
            ],
            "same_name_count": len(same_name),
            "same_name_conflicts": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "scope_type": f.get("scope_type"),
                    "scope_id": f.get("scope_id"),
                    "scope_uuid": f.get("scope_uuid"),
                    "sha256": f.get("sha256"),
                    "same_hash": (f.get("sha256") or "").lower() == item.sha256.lower(),
                }
                for f in same_name
            ],            
        })

    return JSONResponse({"files": out})

def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

@app.post("/api/upload_file")
async def api_upload_file(
    scope_type: str,
    conversation_id: str | None = None,
    project_id: int | None = None,
    files: list[UploadFile] = File(...),
):
    """
    Handle file uploads and register them with scoped metadata.

    scope_type: conversation / project / global
    conversation_id: required for conversation scope
    project_id: required for project scope
    """
    scope_type_norm = (scope_type or "").strip().lower()
    if not scope_type_norm:
        raise HTTPException(status_code=400, detail="scope_type is required")
    if scope_type_norm not in ("conversation", "project", "global"):
        raise HTTPException(status_code=400, detail=f"Invalid scope_type: {scope_type}")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    conv_id = (conversation_id or "").strip() or None
    proj_id = None
    if project_id not in (None, ""):
        try:
            proj_id = int(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="project_id must be an integer")

    if scope_type_norm == "conversation" and not conv_id:
        raise HTTPException(
            status_code=400,
            detail="conversation_id is required for conversation scope",
        )
    if scope_type_norm == "project" and proj_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id is required for project scope",
        )

    base_sources = SOURCES_ROOT
    if scope_type_norm == "conversation":
        dest_root = base_sources / "chats" / (conv_id or "unknown_conversation")
    elif scope_type_norm == "project":
        dest_root = base_sources / "projects" / str(proj_id or "unknown_project")
    else:
        dest_root = base_sources / "global"

    dest_root.mkdir(parents=True, exist_ok=True)

    results: list[RowDict] = []

    for upload in files:
        if not upload.filename:
            continue
        orig_name = Path(upload.filename).name

        final_path = dest_root / orig_name
        temp_path = dest_root / f".{orig_name}.uploading.{uuid.uuid4().hex}.tmp"

        # stream upload to TEMP file first
        with temp_path.open("wb") as out_f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
        await upload.close()

        file_sha256 = _sha256_file(temp_path)

        existing_same_scope = find_same_scope_same_name_file(
            name=orig_name,
            scope_type=scope_type_norm,
            scope_id=proj_id if scope_type_norm == "project" else None,
            scope_uuid=conv_id if scope_type_norm == "conversation" else None,
            include_deleted=False,
        )

        same_name_any_scope = list_files_same_name_any_scope(orig_name, include_deleted=False)
        higher_scope_same_hash = None
        for f in same_name_any_scope:
            if (f.get("sha256") or "").lower() != file_sha256.lower():
                continue
            if scope_rank(scope_type_norm) > scope_rank(f.get("scope_type")):
                higher_scope_same_hash = f
                break
        if higher_scope_same_hash:
            delete_file_cascade(higher_scope_same_hash["id"])        

        if existing_same_scope:
            #old_path = Path(existing_same_scope["path"])

            # safer replacement: move old canonical aside first, then swap temp into place
            backup_old = None
            if final_path.exists():
                backup_old = final_path.with_name(f".{final_path.name}.replaced.{uuid.uuid4().hex}.bak")
                final_path.replace(backup_old)

            try:
                temp_path.replace(final_path)
            except Exception:
                # rollback: restore original file if replacement failed
                if backup_old and backup_old.exists():
                    try:
                        backup_old.replace(final_path)
                    except Exception:
                        pass
                raise
            else:
                # replacement succeeded; remove old backup
                if backup_old and backup_old.exists():
                    try:
                        backup_old.unlink()
                    except Exception:
                        pass
            file_row = replace_file_in_place(
                existing_same_scope["id"],
                path=str(final_path),
                mime_type=upload.content_type,
                sha256=file_sha256,
            )
            fid = file_row["id"]

            # keep scope links alive / idempotent
            if scope_type_norm == "conversation" and conv_id:
                conversation_link_file(conv_id, fid)
                invalidate_context_cache_for_conversation(conv_id)
            elif scope_type_norm == "project" and proj_id is not None:
                db_project_add_file(proj_id, fid)
                invalidate_context_cache_for_project(proj_id)

            # re-artifact / reindex through normal path
            artifact_id = artifact_file(file_row)
            try:
                file_row["artifact_id"] = artifact_id
                arts = list_artifacts_for_file(fid, include_deleted=False)
                if arts:
                    file_row["source_kind"] = arts[0].get("source_kind")
            except Exception:
                pass
        else:
            if final_path.exists():
                # if some stray file exists on disk but no live DB row owns it, keep temp unique
                final_path = dest_root / f"{final_path.stem}.{uuid.uuid4().hex}{final_path.suffix}"

            temp_path.replace(final_path)

            file_row = register_scoped_file(
                name=orig_name,
                path=str(final_path),
                mime_type=upload.content_type,
                sha256=file_sha256,
                scope_type=scope_type_norm,
                scope_id=proj_id if scope_type_norm == "project" else None,
                scope_uuid=conv_id if scope_type_norm == "conversation" else None,
                source_kind="upload",
                url=None,
                provenance=f"upload:{scope_type_norm}",
            )
            fid = file_row["id"]

            if scope_type_norm == "conversation" and conv_id:
                conversation_link_file(conv_id, fid)
                invalidate_context_cache_for_conversation(conv_id)
            elif scope_type_norm == "project" and proj_id is not None:
                db_project_add_file(proj_id, fid)
                invalidate_context_cache_for_project(proj_id)
            artifact_id = artifact_file(file_row)
            try:
                file_row["artifact_id"] = artifact_id
                arts = list_artifacts_for_file(fid, include_deleted=False)
                if arts:
                    file_row["source_kind"] = arts[0].get("source_kind")
            except Exception:
                pass

        # stream the file to disk
        results.append({
            "id": fid,
            "name": orig_name,
            "path": str(final_path),
            "artifact_id": file_row.get("artifact_id"),
            "source_kind": file_row.get("source_kind"),
            "scope_type": scope_type_norm,
        })

        if conv_id and file_row.get("artifact_id"):
            try:
                retain_conversation_artifact(
                    conversation_id=conv_id,
                    artifact_id=str(file_row.get("artifact_id") or "").strip(),
                    origin_kind="file_upload",
                    retention_state="forced",
                    carry_summary_text=None,
                    inclusion_kind="whole",
                    retrieval_channel="upload",
                    message_id=None,
                    note_text="Uploaded file retained for conversation continuity",
                    meta_json={"file_id": fid, "scope_type": scope_type_norm},
                    increment_include_count=False,
                )
            except Exception as exc:
                print(f"[upload] failed to retain uploaded artifact {file_row.get('artifact_id')}: {exc}")

    if conv_id and results:
        _create_upload_scaffold_event(
            conversation_id=conv_id,
            scope_type=scope_type_norm,
            files=results,
        )

    return {"files": results}

# endregion

@app.get("/api/files")
def api_list_files():
    """
    List all non-deleted files in the system.
    Used by the top-level Manage Files button for the 'all' view.
    """
    files = list_all_files()
    return JSONResponse({"files": files})

@app.get("/api/files/global")
def api_list_global_files():
    return JSONResponse({"files": list_global_files()})


@app.get("/api/files/{file_id}/thumbnail")
def api_file_thumbnail(file_id: str):
    try:
        file_row = get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = Path(str(file_row.get("path") or "")).expanduser()
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files support thumbnail preview.")

    media_type = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )

@app.get("/api/files/summary")
def api_files_summary():
    """
    Return counts of files by scope, plus total.
    Used to enable/disable Manage Files buttons.
    """
    summary = get_files_summary()
    return JSONResponse(summary)

@app.post("/api/files/{file_id}/description")
def api_update_file_description(file_id: str, body: FileDescriptionUpdate):
    try:
        update_file_description(file_id, body.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        {
            "id": file_id,
            "description": body.description or "",
        }
    )

@app.post("/api/files/{file_id}/rename")
def api_rename_file(file_id: str, body: FileRenameRequest):
    try:
        out = rename_file(file_id, body.name)
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/files/{file_id}/describe_image")
def api_describe_image_file(file_id: str, body: FileImageDescribeRequest | None = None):
    try:
        file_row = get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = Path(str(file_row.get("path") or "")).expanduser()
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files can be described.")

    try:
        meta = _load_json_object(file_row.get("meta_json"))
        existing_caption = (meta.get("image_caption") or "").strip()
        if existing_caption and not (body.overwrite if body is not None else True):
            return JSONResponse({
                "file_id": file_id,
                "caption": existing_caption,
                "model": meta.get("image_caption_model"),
                "reused": True,
            })

        caption, model_name = _generate_image_caption_for_file(
            file_row,
            deployment_id=(body.deployment_id if body is not None else None),
        )
        updated = set_file_image_caption(
            file_id,
            caption,
            caption_model=model_name,
            generator_kind="llm_image_caption",
        )
        return JSONResponse({"file_id": file_id, "caption": caption, "model": model_name, "file": updated})
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProviderExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/files/{file_id}/ocr_image")
def api_ocr_image_file(file_id: str, body: FileImageOcrRequest | None = None):
    try:
        file_row = get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = Path(str(file_row.get("path") or "")).expanduser()
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files can be OCR'd.")

    try:
        meta = _load_json_object(file_row.get("meta_json"))
        existing_ocr_text = (meta.get("image_ocr_text") or "").strip()
        if existing_ocr_text and not (body.overwrite if body is not None else True):
            return JSONResponse({
                "file_id": file_id,
                "ocr_text": existing_ocr_text,
                "model": meta.get("image_ocr_model"),
                "reused": True,
            })

        ocr_text, model_name = _generate_image_ocr_for_file(
            file_row,
            deployment_id=(body.deployment_id if body is not None else None),
        )
        updated = set_file_image_ocr_text(
            file_id,
            ocr_text,
            ocr_model=model_name,
            generator_kind="llm_image_ocr",
        )
        return JSONResponse({"file_id": file_id, "ocr_text": ocr_text, "model": model_name, "file": updated})
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProviderExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/files/{file_id}/move_scope")
def api_move_file_scope(file_id: str, body: FileMoveScopeRequest):
    try:
        out = move_file_scope(
            file_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            scope_uuid=body.scope_uuid,
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/files/bulk_move_scope")
def api_bulk_move_file_scope(body: BulkFileMoveScopeRequest):
    file_ids = []
    seen = set()
    for raw in body.file_ids or []:
        fid = str(raw or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            file_ids.append(fid)

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids is required.")

    results = []
    moved = 0
    failed = 0
    for fid in file_ids:
        try:
            out = move_file_scope(
                fid,
                scope_type=body.scope_type,
                scope_id=body.scope_id,
                scope_uuid=body.scope_uuid,
            )
            results.append({"id": fid, "ok": True, "result": out})
            moved += 1
        except ValueError as e:
            results.append({"id": fid, "ok": False, "error": str(e)})
            failed += 1

    return JSONResponse({"moved": moved, "failed": failed, "results": results})

@app.post("/api/files/bulk_delete")
def api_bulk_delete_files(body: BulkFileDeleteRequest):
    file_ids = []
    seen = set()
    for raw in body.file_ids or []:
        fid = str(raw or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            file_ids.append(fid)

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids is required.")

    results = []
    deleted = 0
    failed = 0
    for fid in file_ids:
        try:
            out = delete_file_cascade(fid, delete_disk_action=FileDeleteAction.MOVE)
            results.append({"id": fid, "ok": True, "result": out})
            deleted += 1
        except ValueError as e:
            results.append({"id": fid, "ok": False, "error": str(e)})
            failed += 1

    return JSONResponse({"deleted": deleted, "failed": failed, "results": results})


@app.post("/api/artifacts/{artifact_id}/move_scope")
def api_move_artifact_scope(artifact_id: str, body: ArtifactMoveScopeRequest):
    try:
        out = move_artifact_scope(
            artifact_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            scope_uuid=body.scope_uuid,
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/files")
def api_register_file(req: FileRegister):
    try:
        out = db_register_file(req.name, req.path, req.mime_type)
        return JSONResponse(out)
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/conversations/{conversation_id}/files/upload")
async def api_upload_conversation_file(conversation_id: str, file: UploadFile = File(...)):
    """
    Upload a file scoped to a conversation.

    - Stored under DATA_DIR / "sources" / "chats" / {conversation_id} / {filename}
    - Registered in files with scope_type="chat", scope_uuid={conversation_id}
    - Linked to the conversation (conversation_files)
    - Linked to the project via project_files if the conversation has a project_id
    - Invalidates the context cache for this conversation
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    # Ensure conversation exists and grab its project
    try:
        ctx = get_conversation_context(conversation_id, preview_limit=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found")

    project_id = ctx.get("project_id")

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Uploaded file must have a name")

    # Target path on disk
    chat_root = SOURCES_ROOT / "chats" / conversation_id
    chat_root.mkdir(parents=True, exist_ok=True)
    dest_path = chat_root / file.filename

    # Stream upload to disk
    try:
        with dest_path.open("wb") as out_f:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                out_f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    # Register and link
    try:
        file_row = register_scoped_file(
            name=file.filename,
            path=str(dest_path),
            mime_type=file.content_type,
            scope_type="conversation",
            scope_id=None,
            scope_uuid=conversation_id,
            source_kind="upload",
            url=None,
            provenance=f"uploaded via chat {conversation_id}",
        )
        file_id = file_row["id"]

        conversation_link_file(conversation_id, file_id)
        if project_id is not None:
            db_project_add_file(project_id, file_id)

        artifact_id = artifact_file(file_row)
        source_kind = None
        try:
            arts = list_artifacts_for_file(file_id, include_deleted=False)
            if arts:
                source_kind = arts[0].get("source_kind")
        except Exception:
            pass

        try:
            retain_conversation_artifact(
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                origin_kind="file_upload",
                retention_state="forced",
                carry_summary_text=None,
                inclusion_kind="whole",
                retrieval_channel="upload",
                message_id=None,
                note_text="Uploaded file retained for conversation continuity",
                meta_json={"file_id": file_id, "scope_type": "conversation"},
                increment_include_count=False,
            )
        except Exception as exc:
            print(f"[upload] failed to retain uploaded artifact {artifact_id}: {exc}")

        _create_upload_scaffold_event(
            conversation_id=conversation_id,
            scope_type="conversation",
            files=[{
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "artifact_id": artifact_id,
                "source_kind": source_kind,
            }],
        )

        invalidate_context_cache_for_conversation(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register upload: {e}")

    return JSONResponse(
        {
            "conversation_id": conversation_id,
            "project_id": project_id,
            "file": {
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "mime_type": file.content_type,
            },
        }
    )

@app.get("/api/conversations/{conversation_id}/files")
def api_list_conversation_files(conversation_id: str):
    """
    List files attached to a conversation via conversation_files.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    try:
        files = list_files_for_conversation(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({"conversation_id": conversation_id, "files": files})

@app.post("/api/projects/{project_id}/files/upload")
async def api_upload_project_file(project_id: int, file: UploadFile = File(...)):
    """
    Upload a file scoped to a project.

    - Stored under DATA_DIR / "sources" / "projects" / {project_id} / {filename}
    - Registered in files with scope_type="project", scope_id={project_id}
    - Linked to the project via project_files
    - Invalidates context cache for all conversations in this project
    """
    # Make sure the project exists
    projects = list_projects()
    if not any(int(p["id"]) == int(project_id) for p in projects):
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Uploaded file must have a name")

    proj_root = SOURCES_ROOT / "projects" / str(project_id)
    proj_root.mkdir(parents=True, exist_ok=True)
    dest_path = proj_root / file.filename

    # Stream upload to disk
    try:
        with dest_path.open("wb") as out_f:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                out_f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    # Register and link
    try:
        file_row = register_scoped_file(
            name=file.filename,
            path=str(dest_path),
            mime_type=file.content_type,
            scope_type="project",
            scope_id=int(project_id),
            scope_uuid=None,
            source_kind="upload",
            url=None,
            provenance=f"uploaded via project {project_id}",
        )
        file_id = file_row["id"]

        db_project_add_file(project_id, file_id)

        invalidate_context_cache_for_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register upload: {e}")

    return JSONResponse(
        {
            "project_id": project_id,
            "file": {
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "mime_type": file.content_type,
            },
        }
    )

@app.get("/api/projects/{project_id}/files")
def api_list_project_files(project_id: int):
    """
    List files attached to a project via project_files.
    """
    try:
        files = list_files_for_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({"project_id": project_id, "files": files})

@app.delete("/api/files/{file_id}")
def api_delete_file(file_id: str):
    try:
        out = delete_file_cascade(
            file_id,
            delete_disk_action=FileDeleteAction.MOVE
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# endregion

# region Model Selection Endpoints


@app.get("/api/deployments")
def api_deployments(capability: str = "chat"):
    if PROVIDER_REGISTRY is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    try:
        cap = (capability or "").strip()
        deployments = (
            PROVIDER_REGISTRY.list_deployments(cap)
            if cap and cap.lower() != "all"
            else PROVIDER_REGISTRY.list_deployments(None)
        )

        items: list[dict[str, Any]] = []
        for d in deployments:
            meta = MODEL_CATALOG.get(d.model, {})

            items.append(
                {
                    "id": d.id,
                    "display_name": d.display_name,
                    "provider_id": d.provider_id,
                    "provider_type": d.provider_type,
                    "model": d.model,
                    "capabilities": list(d.capabilities),
                    "tags": list(d.tags),
                    "enabled": d.enabled,
                    "base_url": d.base_url,
                    "is_legacy": d.id.startswith("legacy:"),
                    "vendor": meta.get("vendor", d.provider_id),
                    "description": meta.get("description", ""),
                    "input_cost_per_million": meta.get("input_cost_per_million"),
                    "output_cost_per_million": meta.get("output_cost_per_million"),
                    "context_window": meta.get("context_window"),
                }
            )

        items.sort(key=lambda x: (x["provider_id"], x["display_name"].lower()))
        return {
            "deployments": items,
            "capability": cap or "all",
            "cached": False,
            "fetched_at": int(time.time()),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list deployments: {e}")


@app.get("/api/models")
def api_models():
    global _MODELS_CACHE, _MODELS_CACHE_TS
    now = time.time()
    if _MODELS_CACHE and (now - _MODELS_CACHE_TS) < _MODELS_TTL_SECONDS:
        return _MODELS_CACHE

    if PROVIDER_REGISTRY is None:
        raise HTTPException(status_code=500, detail="Provider registry is not initialized.")

    try:
        items: list[dict[str, Any]] = []

        for provider_id, provider_def in PROVIDER_REGISTRY.providers.items():
            if not provider_def.enabled:
                continue

            try:
                catalog = PROVIDER_REGISTRY.get_catalog_provider(provider_id)
                model_infos = catalog.list_models(provider_def)
            except Exception:
                continue

            for m in model_infos:
                mid = m.id

                items.append(
                    {
                        "id": m.id,
                        "provider_id": m.provider_id,
                        "provider_type": m.provider_type,
                        "created": m.created,
                        "owned_by": m.owned_by,
                        "vendor": m.vendor,
                        "display_name": m.display_name,
                        "description": m.description,
                        "input_cost_per_million": m.input_cost_per_million,
                        "output_cost_per_million": m.output_cost_per_million,
                        "context_window": m.context_window,
                        "tags": list(m.tags),
                    }
                )

        items.sort(key=lambda m: (m.get("vendor", ""), m["display_name"].lower()))
        payload = {"models": items, "cached": True, "fetched_at": int(now)}
        _MODELS_CACHE = payload
        _MODELS_CACHE_TS = now
        return payload
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to list models: {e}")

# endregion

# region Search Endpoints

@app.post("/api/corpus/search")
def corpus_search(req: CorpusSearchRequest):
    from .db import ensure_files_artifacted_for_conversation, search_corpus_for_conversation

    cid = (req.conversation_id or "").strip()
    q = (req.query or "").strip()

    # We normally would bother to load here, since function will load QueryConfig
    # but we need it anyway for healing function
    cfg: RetrievalConfig = load_retrieval_config()
    include_global=req.include_global
    if req.include_global:
        include_global=req.include_global
        log_warn("corpus_search is using req.include_global which may override cfg.query_global_artifacts, but only for healing functions.")
    else:
        include_global=cfg.query_global_artifacts
    # Optional: self-heal missing artifacts before searching
    ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=include_global)
    rows = search_corpus_for_conversation(
        conversation_id=cid,
        query=q,
        limit=req.limit,
        cfg=cfg,
        #include_global=req.include_global,
    )
    return {"ok": True, "results": rows}

# endregion
