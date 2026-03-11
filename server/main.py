import hashlib
import anyio
import asyncio
import os
import re
import uuid
import json
import time
import traceback
from pathlib import Path
from typing import Optional, cast, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, status, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from functools import partial
from openai import OpenAI, APIStatusError
from openai.types.responses import ResponseInputParam
# From openai/types/responses/response_create_params.py
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import BaseModel

from .logging_helper import log_warn
from .context import _get_prompt, build_context, build_context_panel_payload, build_model_input, estimate_context_tokens
from .markdown_helper import apply_house_markdown_normalization, autolink_text
from .summary_helper import summarize_conversation_text
from .query_retrieval import retrieve_chunks_for_message
# Big Include Blocks for config and db
from .config import (
    CoreConfig, load_core_config,
    ContextConfig, load_context_config,
    OpenAIConfig, load_openai_config,
    QueryConfig, load_query_config,
    SummaryConfig, load_summary_config,
    UIConfig, load_ui_config,
    # app_settings access
    APP_KEYS, load_app_config,
    # Other helpers and vars
    QUERY_INCLUDE_ALLOWED, QUERY_EXPAND_ALLOWED,
    _normalize_csv_set,
)
from .db import (
    # Schema and connection
    init_schema, db_debug_info,
    # Shared paths
    DATA_DIR,
    # this is the reverse end of AppConfig
    set_app_setting,
    # Chat Messages
    add_message, get_messages,
    get_messages_raw, scope_rank,
    save_conversation_summary_artifact,
    update_ab_canonical,
    # Converstaions
    list_conversations, create_conversation,
    delete_conversation, set_conversation_archived,
    get_conversation_title, update_conversation_title,
    get_conversation_context,
    # Projects and subordinate entities
    list_projects, get_or_create_project,
    get_or_create_project as db_get_or_create_project,  # optional convenience endpoint
    project_add_conversation as db_project_add_conversation,
    project_import as db_project_import,
    set_conversation_project,  # assign_conversation_project,
    update_project,
    # Files
    list_files_by_sha256, list_files_same_name_any_scope,
    replace_file_in_place,
    register_file as db_register_file,
    project_add_file as db_project_add_file,
    register_scoped_file, update_file_description,
    conversation_link_file, list_files_for_conversation,
    list_files_for_project, list_all_files,
    get_files_summary, list_global_files,
    FileDeleteAction, delete_file_cascade,
    move_file_scope, find_same_scope_same_name_file,
    # Artifacts
    get_scoped_artifact_debug,
    # File Artifacts
    artifact_file, ensure_files_artifacted_for_conversation,
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

# TODO move me into config.py
DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"

load_dotenv()

# Replaces the old @app.on_event("startup") and @app.on_event("shutdown") handlers with a single async context manager that can do both setup and teardown.
#@app.on_event("startup")
#def _startup():
#    init_db()
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    global MODEL_CATALOG
    print("[DB]", db_debug_info())
    init_schema()   # Call your DB migration/creation logic here
    MODEL_CATALOG = load_model_catalog()

    # If you need anything else (loading model lists, warm caches…)
    # you put it here.

    yield  # <-- the app runs after this line

    # --- SHUTDOWN ---
    # Cleanup if you ever need it

app = FastAPI(lifespan=lifespan)
client = OpenAI()

# -------------------------
# Global Vars
# -------------------------

# start from root folder above ./server
HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
# This is where uploaded files are stored; you can change this or add subdirs as needed
SOURCES_ROOT = DATA_DIR / "sources"
# This is where APIs for supported toools (retrievers, file parsers, etc.) would live; you can add subdirs as needed
TOOLS_DIR = HERE / "tools"

# load from OpenAIConfig
oai_cfg = load_openai_config()
MODEL = oai_cfg.open_ai_model
# TODO decide if TITLE_MODEL should have its own setting
TITLE_MODEL = oai_cfg.summary_model

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

class FileMoveScopeRequest(BaseModel):
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
if (False):
    ZEIT_PREFIX_RE = re.compile(r"^\s*⟂ts=\d+\s*\n")
    ZEIT_PREFIX_RE = re.compile(
        r"^\s*(?:"
        r"⟂ts=\d+"                                # old: ⟂ts=1709...
        r"|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=\d+)?"       # new: ⟂t=20260228T231512Z ⟂age=37
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

# region Model Catalog and Caching

# TODO refactor to include many providers
# Support checking for models
_MODELS_CACHE: dict[str, Any] | None = None
MODEL_CATALOG: dict[str, dict] = {}

# TODO make these part of config.py
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes
# TODO make this part of OpenAIConfig
_ALLOWED_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")

# endregion

# region Misc Helper functions

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

def load_model_catalog() -> dict[str, dict]:
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

def _extract_output_text(resp) -> str:
    # SDKs vary; try the obvious fields first
    t = getattr(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t.strip()

    # fallback: walk resp.output items if present
    out = getattr(resp, "output", None)
    if isinstance(out, list):
        chunks = []
        for item in out:
            content = getattr(item, "content", None)
            if isinstance(content, list):
                for c in content:
                    if getattr(c, "type", None) == "output_text":
                        chunks.append(getattr(c, "text", ""))
        joined = "".join(chunks).strip()
        if joined:
            return joined
    return ""

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
    return JSONResponse({"ok": True, "model": MODEL})

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

    qcfg = load_query_config()

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

@app.post("/api/chat")
def chat(req: ChatRequest, model: str | None = None):
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        create_conversation(cid)
    # Call before build_model_input to ensure that we use it to search RAG
    heal = ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)
    full = postprocess_text(req.message)
    if full:
        add_message(cid, "user", full)
    # End to "Call" above.
    raw_input = build_model_input(cid, full)
    model_input = cast(ResponseInputParam, raw_input)
    print("[debug] model_input:", json.dumps(model_input, indent=2)[:5000])
    model = (req.model or model or MODEL).strip()
    def gen():
        parts: list[str] = []
        try:
            with client.responses.stream(
                model=model,
                input=model_input,
            ) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        parts.append(event.delta)
                        yield event.delta
                    elif event.type == "response.refusal.delta":
                        parts.append(event.delta)
                        yield event.delta
                    elif event.type == "response.error":
                        yield "\n[error]\n"

                full = postprocess_text("".join(parts))
                if full:
                    add_message(cid, "assistant", full, meta={"model": model})
        except Exception as e:
            yield f"\n[server exception: {type(e).__name__}]"

    resp = StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    return resp

def _openai_error_payload(e: APIStatusError) -> dict:
    # Pull out useful fields safely
    status = getattr(e, "status_code", None)
    req_id = None
    err_json = None
    try:
        err_json = e.response.json()
        req_id = err_json.get("error", {}).get("request_id") or err_json.get("request_id")
    except Exception:
        try:
            err_json = {"raw": e.response.text}
        except Exception:
            err_json = {"raw": repr(getattr(e, "response", None))}
    return {
        "status_code": status,
        "request_id": req_id,
        "body": err_json,
    }

if (False):
    def _openai_error_payload(e: APIStatusError) -> dict:
        status = getattr(e, "status_code", None)
        req_id = None
        body = None
        try:
            body = e.response.json()
            req_id = (body.get("error") or {}).get("request_id") or body.get("request_id")
        except Exception:
            try:
                body = {"raw": e.response.text}
            except Exception:
                body = {"raw": repr(getattr(e, "response", None))}
        return {"status_code": status, "request_id": req_id, "body": body}

def _extract_err_msg(payload: dict) -> str:
    body = payload.get("body") or {}
    if isinstance(body, dict):
        return (body.get("error") or {}).get("message") or body.get("message") or "OpenAI API error"
    return "OpenAI API error"

if (False):
    def _sync_call():
        return client.responses.create(model=model_name, input=model_input)

async def _call_model(model_name: str, model_input):
    loop = asyncio.get_running_loop()
    fn = partial(client.responses.create, model=model_name, input=model_input)
    return await loop.run_in_executor(None, fn)

if (False):
    async def _call_model(model_name: str, model_input):
        # OpenAI SDK call is blocking; run in worker thread
        if (False): #older model of Anyio
            return await anyio.to_thread.run_sync(
                lambda: client.responses.create(model=model_name, input=model_input)
            )
        else:
            return await anyio.to_thread.run_sync(_sync_call)

import asyncio
from typing import Any, Callable

async def _sleep_ms(ms: int) -> None:
    await asyncio.sleep(ms / 1000.0)

def _strip_images(model_input: list[dict]) -> list[dict]:
    out = []
    for msg in model_input:
        c = msg.get("content")
        if isinstance(c, list):
            c = [p for p in c if isinstance(p, dict) and p.get("type") != "input_image"]
        out.append({**msg, "content": c})
    return out

def _strip_file_messages(model_input: list[dict]) -> list[dict]:
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

def _trim_history(model_input: list[dict], keep_last_n: int = 30) -> list[dict]:
    # Keep system message(s) at front, keep last N non-system messages.
    system = [m for m in model_input if m.get("role") == "system"]
    non_system = [m for m in model_input if m.get("role") != "system"]
    return system + non_system[-keep_last_n:]

async def call_model_with_recovery(model: str, model_input: list[dict]) -> dict:
    """
    Returns either {"ok": True, "text": "..."} or {"ok": False, "error": {...}}.
    """
    attempts: list[tuple[str, list[dict], int]] = []

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
            resp = await _call_model(model, mi)  # uses your run_in_executor helper
            text = strip_zeitgeber_prefix(_extract_output_text(resp) or "")
            return {"ok": True, "text": text, "recovery": label}
        except APIStatusError as e:
            payload = _openai_error_payload(e)
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
      - returns structured {a:{ok,text|error}, b:{ok,text|error}}
    """
    cid = req.conversation_id or str(uuid.uuid4())
    if req.conversation_id is None:
        create_conversation(cid)

    heal = ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=False)
    if heal["created"]:
        print("self-heal artifacts: cid=%s heal=%s", cid, heal)

    full = postprocess_text(req.message)
    if full:
        add_message(cid, "user", full)

    model_input = build_model_input(cid, req.message)
    model_a = (req.model_a or MODEL).strip()
    model_b = (req.model_b or model_a).strip()

    ab_group = str(uuid.uuid4())

    async def run_one(slot: str, model_name: str):
        try:
            resp = await _call_model(model_name, model_input)
            text = strip_zeitgeber_prefix(_extract_output_text(resp) or "")
            return {"ok": True, "text": text}
        except APIStatusError as e:
            payload = _openai_error_payload(e)
            return {"ok": False, "error": payload}

    if (False):
        # This is the different/older version of Anyio
        a_res, b_res = await anyio.gather(
            run_one("A", model_a),
            run_one("B", model_b),
        )
    else:
        a_res = None
        b_res = None
        async with anyio.create_task_group() as tg:
            # tg.start_soon(lambda: None)  # harmless; avoids lint complaining about empty group in some editors
            async def run_a():
                nonlocal a_res
                #a_res = await run_one("A", model_a)
                a_res = await call_model_with_recovery(model_a, model_input)                
            async def run_b():
                nonlocal b_res
                #b_res = await run_one("B", model_b)
                b_res = await call_model_with_recovery(model_b, model_input)                
            tg.start_soon(run_a)
            tg.start_soon(run_b)
        # At this point, both are done
        assert a_res is not None and b_res is not None

    # Store results as messages; store errors as assistant messages with meta.kind="error"
    def store(slot: str, model_name: str, res: dict):
        if res.get("ok"):
            text = res.get("text") or ""
            full = postprocess_text(text)
            if full:
                add_message(cid, "assistant", full, meta={"ab_group": ab_group, "slot": slot, "model": model_name, "kind": "ab", "recovery": res.get("recovery")})
        else:
            payload = res.get("error") or {}
            msg = _extract_err_msg(payload)
            status = payload.get("status_code")
            req_id = payload.get("request_id")
            bubble = f"[Model {slot} error] {status or ''} {msg}".strip()
            full = postprocess_text(bubble)
            if full:
                add_message(
                    cid,
                    "assistant",
                    full,
                    meta={"ab_group": ab_group, "slot": slot, "model": model_name, "kind": "error", 
                    "recovery_step": res["error"].get("recovery_step"),
                    **payload},
                )

    store("A", model_a, a_res)
    store("B", model_b, b_res)

    return JSONResponse(
        {
            "conversation_id": cid,
            "model_a": model_a,
            "model_b": model_b,
            "ab_group": ab_group,
            "a": a_res,
            "b": b_res,
        }
    )

if (False):
    @app.post("/api/chat_ab")
    def chat_ab(req: ABChatRequest):
        cid = req.conversation_id or str(uuid.uuid4())
        if req.conversation_id is None:
            create_conversation(cid)

        add_message(cid, "user", req.message)

        model_input = build_model_input(cid, history_limit=200)

        model_a = (req.model_a or MODEL).strip()
        model_b = (req.model_b or model_a).strip()

        ab_group = str(uuid.uuid4())

        result = {
            "ok": True,
            "conversation_id": cid,
            "ab_group": ab_group,
            "model_a": model_a,
            "model_b": model_b,
            "a": None,
            "b": None,
        }

        # A
        try:
            resp_a = client.responses.create(model=model_a, input=model_input)
            text_a = strip_zeitgeber_prefix(_extract_output_text(resp_a) or "")
            result["a"] = {"ok": True, "text": text_a}
            if text_a:
                add_message(cid, "assistant", text_a, meta={"ab_group": ab_group, "slot": "A", "model": model_a})
        except APIStatusError as e:
            payload = _openai_error_payload(e)
            result["a"] = {"ok": False, "error": payload}
            # Optional: store an error bubble as an assistant message
            add_message(
                cid,
                "assistant",
                f"[Model A error] {payload.get('status_code')} {payload.get('body', {}).get('error', {}).get('message', '')}",
                meta={"ab_group": ab_group, "slot": "A", "model": model_a, "kind": "error", **payload},
            )

        # B
        try:
            resp_b = client.responses.create(model=model_b, input=model_input)
            text_b = strip_zeitgeber_prefix(_extract_output_text(resp_b) or "")
            result["b"] = {"ok": True, "text": text_b}
            if text_b:
                add_message(cid, "assistant", text_b, meta={"ab_group": ab_group, "slot": "B", "model": model_b})
        except APIStatusError as e:
            payload = _openai_error_payload(e)
            result["b"] = {"ok": False, "error": payload}
            add_message(
                cid,
                "assistant",
                f"[Model B error] {payload.get('status_code')} {payload.get('body', {}).get('error', {}).get('message', '')}",
                meta={"ab_group": ab_group, "slot": "B", "model": model_b, "kind": "error", **payload},
            )

        return JSONResponse(result)

if (False):
    @app.post("/api/chat_ab")
    def chat_ab(req: ABChatRequest):
        """
        Non-streaming A/B chat endpoint:
        - stores the user message once
        - produces two assistant variants (A and B)
        - stores both variants with A/B metadata
        """
        from openai import APIStatusError
        import json

        def _strip_images_from_input(inp: list[dict]) -> list[dict]:
            out: list[dict] = []
            for msg in inp:
                content = msg.get("content")
                if isinstance(content, list):
                    content = [p for p in content if (p.get("type") != "input_image")]
                out.append({**msg, "content": content})
            return out

        def _log_openai_status_error(label: str, e: APIStatusError, model_name: str) -> None:
            print(f"\n[openai] APIStatusError during chat_ab ({label}) model={model_name}")
            print("status_code:", getattr(e, "status_code", None))
            try:
                print("response:", json.dumps(e.response.json(), indent=2))
            except Exception:
                try:
                    print("response_text:", e.response.text)
                except Exception:
                    print("response_repr:", repr(getattr(e, "response", None)))

        cid = req.conversation_id or str(uuid.uuid4())
        if req.conversation_id is None:
            create_conversation(cid)

        add_message(cid, "user", req.message)

        raw_input = build_model_input(cid, history_limit=200)
        model_input = cast(ResponseInputParam, raw_input)

        model_a = (req.model_a or MODEL).strip()
        model_b = (req.model_b or model_a).strip()

        # Run A
        try:
            resp_a = client.responses.create(model=model_a, input=model_input)
        except APIStatusError as e:
            _log_openai_status_error("A", e, model_a)
            return JSONResponse(
                {"ok": False, "where": "A", "model": model_a, "error": "OpenAI API error (see server log)"},
                status_code=500,
            )

        # Run B (retry without images if needed)
        try:
            resp_b = client.responses.create(model=model_b, input=model_input)
        except APIStatusError as e:
            _log_openai_status_error("B", e, model_b)

            # Common case: model B doesn't support vision / input_image parts.
            # Retry with images stripped.
            try:
                model_input_b = cast(ResponseInputParam, _strip_images_from_input(raw_input))
                resp_b = client.responses.create(model=model_b, input=model_input_b)
                print("[openai] retry B without images: success")
            except APIStatusError as e2:
                _log_openai_status_error("B(retry_no_images)", e2, model_b)
                return JSONResponse(
                    {"ok": False, "where": "B", "model": model_b, "error": "OpenAI API error (see server log)"},
                    status_code=500,
                )

        text_a = strip_zeitgeber_prefix(_extract_output_text(resp_a) or "")
        text_b = strip_zeitgeber_prefix(_extract_output_text(resp_b) or "")

        ab_group = str(uuid.uuid4())
        meta_a = {"ab_group": ab_group, "slot": "A", "canonical": True, "model": model_a}
        meta_b = {"ab_group": ab_group, "slot": "B", "canonical": False, "model": model_b}

        if text_a:
            add_message(cid, "assistant", text_a, meta=meta_a)
        if text_b:
            add_message(cid, "assistant", text_b, meta=meta_b)

        return JSONResponse(
            {
                "ok": True,
                "conversation_id": cid,
                "model_a": model_a,
                "model_b": model_b,
                "a": text_a,
                "b": text_b,
                "ab_group": ab_group,
            }
        )

if (False): # Better error handling
    @app.post("/api/chat_ab")
    def chat_ab(req: ABChatRequest):
        """
        Non-streaming A/B chat endpoint:
        - stores the user message once
        - produces two assistant variants (A and B) using potentially different models
        - stores both variants with A/B metadata
        """
        cid = req.conversation_id or str(uuid.uuid4())
        if req.conversation_id is None:
            create_conversation(cid)

        # One user turn for both branches
        add_message(cid, "user", req.message)

        raw_input = build_model_input(cid, history_limit=200)
        model_input = cast(ResponseInputParam, raw_input)
        print("[debug] model_input:", json.dumps(model_input, indent=2)[:5000])

        model_a = (req.model_a or MODEL).strip()
        model_b = (req.model_b or model_a).strip()

        # Run the two models sequentially; simple but robust
        resp_a = client.responses.create(model=model_a, input=model_input)
        resp_b = client.responses.create(model=model_b, input=model_input)
        text_a = strip_zeitgeber_prefix(_extract_output_text(resp_a) or "")
        text_b = strip_zeitgeber_prefix(_extract_output_text(resp_b) or "")

        # Tag both variants as part of the same A/B group
        ab_group = str(uuid.uuid4())
        meta_a = {
            "ab_group": ab_group,
            "slot": "A",
            "canonical": True,
            "model": model_a,
        }
        meta_b = {
            "ab_group": ab_group,
            "slot": "B",
            "canonical": False,
            "model": model_b,
        }

        if text_a:
            add_message(cid, "assistant", text_a, meta=meta_a)
        if text_b:
            add_message(cid, "assistant", text_b, meta=meta_b)

        return JSONResponse(
            {
                "conversation_id": cid,
                "model_a": model_a,
                "model_b": model_b,
                "a": text_a,
                "b": text_b,
                "ab_group": ab_group,
            }
        )

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
def api_conversations(include_archived: bool = False):
    return JSONResponse(list_conversations(limit=200, include_archived=include_archived))

@app.get("/api/conversation/{conversation_id}/messages")
def api_conversation_messages(
    conversation_id: str,
    limit: int = 500,
    mode: str = "raw",   # "raw" (default, what app.js wants) or "canonical"
):
    """
    app.js calls this as: GET /api/conversation/{cid}/messages

    mode=raw       -> returns rows with meta (A/B grouping, timestamps, etc.)
    mode=canonical -> returns condensed role/content list (A/B canonical only)
    """
    if mode == "canonical":
        return JSONResponse(get_messages(conversation_id, limit=limit))
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
    oai_cfg = load_openai_config()
    try:
        title, transcript = get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    system_prompt = _get_prompt(
        default_prompt=sum_cfg.summary_conversation_prompt,
        filepath=sum_cfg.summary_conversation_prompt_file,
        cfg_default="SUMMARY_CONVO_PROMPT",
        cfg_filepath="SUMMARY_CONVO_PROMPT_FILE",
    )
    # TODO phase out MODEL completely
    model = oai_cfg.summary_model or MODEL
    if (False):
        try:
            resp = client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Title: {title}\n\nFull transcript:\n\n{transcript}"},
                ],
                max_output_tokens=sum_cfg.summary_max_tokens,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")

    try:
        summary_text = summarize_conversation_text(
            client=client,
            model=model,
            title=title,
            transcript=transcript,
            cfg=sum_cfg,
            system_prompt=system_prompt,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")
    # summary_text = (_extract_output_text(resp) or "").strip()
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
            meta={"summary": True, "model": model},
        )
        save_conversation_summary_artifact(conversation_id, summary_text, model)
        # save_conversation_summary(conversation_id, full, model)

    return {"conversation_id": conversation_id, "summary": summary_text, "model": model}

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
    )
    return JSONResponse(payload)

if (False):
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

        ctx = build_context(
            conversation_id=conversation_id,
            user_text=user_text or "",
            ctx_cfg=ctx_cfg,
        )
        return JSONResponse(ctx)

@app.get("/api/conversation/{conversation_id}/artifacts/debug")
def api_conversation_artifacts_debug(conversation_id: str):
    query_cfg = load_query_config()
    data = get_scoped_artifact_debug(
        conversation_id,
        include_global=query_cfg.query_global_artifacts,
        preview_chars=180,
    )
    return JSONResponse(data)

if (False): # new version accepts user input
    @app.get("/api/conversation/{conversation_id}/context")
    def api_conversation_context(conversation_id: str):
        # You know what's even better? One function to rule them all!
        # Note that build_context does do RAG but doesn't expand files and stuff

        # Do not bother, they will be lazy loaded
        # ctx_cfg = load_context_config()
        # query_cfg = load_query_config()
        user_text: str = "" # We don't have a user text in this call

        ctx = build_context(conversation_id, user_text) # , ctx_cfg, query_cfg
        if (False):
            # we no longer need model input or assembled_input becuase everything we want to have comes in build_context now
            model_input = build_model_input(conversation_id, user_text, ctx_cfg, query_cfg, ctx=ctx)
            assembled_input = [{"role": m.get("role"), "content": _preview_content(m.get("content"))} for m in model_input]
            preview = assembled_input[-ctx_cfg.preview_limit:] if ctx_cfg.preview_limit > 0 else assembled_input
            ctx["assembled_input_preview"] = preview
            ctx["assembled_input_count"] = len(assembled)
            ctx["assembled_input_preview_limit"] = ctx_cfg.preview_limit
            ctx["assembled_input_preview_truncated"] = len(preview) < len(assembled)
            token_stats = estimate_context_tokens(conversation_id, ctx_cfg, user_text, model=ctx_cfg.estimate_model)
            ctx["token_stats"] = token_stats

        return JSONResponse(ctx)

if (False):
    @app.get("/api/conversation/{conversation_id}/context")
    def api_conversation_context(conversation_id: str):
        ctx_cfg = load_context_config()
        user_text: str = "" # we don't know the user's text so we make whatever we can
        ctx = build_context(conversation_id, user_text)
        model_input = build_model_input(conversation_id, user_text)

        assembled = [{"role": m.get("role"), "content": _preview_content(m.get("content"))} for m in model_input]

        preview = assembled[-ctx_cfg.preview_limit:] if ctx_cfg.preview_limit > 0 else assembled
        ctx["assembled_input_preview"] = preview
        ctx["assembled_input_count"] = len(assembled)
        ctx["assembled_input_preview_limit"] = ctx_cfg.preview_limit
        ctx["assembled_input_preview_truncated"] = len(preview) < len(assembled)

        # Get the estimated token count for this context; useful for cost management, debugging, and deciding when to trim or summarize.
        token_stats = estimate_context_tokens(conversation_id, ctx_cfg, user_text, model="gpt-4.1-mini")
        # You can either embed into ctx or return a wrapper. I’d embed; it’s simpler.
        ctx["token_stats"] = token_stats
        try:
            return JSONResponse(ctx)
        except KeyError:
            raise HTTPException(status_code=404, detail="Not Found")

# endregion

# region Memory Endpoints

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

if (False):
    @app.post("/api/memories")
    def api_create_memory(req: MemoryCreate):
        try:
            mem = db_create_memory(
                req.content,
                importance=req.importance,
                tags=req.tags,
                created_by=req.created_by,
                origin_kind=req.origin_kind,
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

if (False):
    @app.put("/api/projects/{project_id}")
    def api_update_project(project_id: int, req: ProjectUpdateRequest):
        try:
            return JSONResponse(update_project(project_id, name=req.name, visibility=req.visibility, description=req.description))
        except ValueError as e:
            _http_from_value_error(e)

@app.get("/api/projects")
def api_get_projects():
    return {"projects": list_projects()}

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

if (False):  # Disabled for now - was not in use
    #@app.post("/api/projects/{project_id}/artifacts")
    def api_create_artifact(project_id: int, req: ArtifactCreate):
        try:
            # had been removed in favor of upserts with data
            out = create_artifact(project_id, req.name, req.content, req.tags)
            return JSONResponse(out)
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

    results: list[dict] = []

    for upload in files:
        if not upload.filename:
            continue
        orig_name = Path(upload.filename).name

        if (False): # Old methodology replaced by sha256 de-dupe w/ warnings
            # avoid overwriting existing files
            dest_path = dest_root / orig_name
            counter = 1
            while dest_path.exists():
                dest_path = dest_root / f"{dest_path.stem}_{counter}{dest_path.suffix}"
                counter += 1

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

            if (False):
                # move temp into final canonical filename
                if final_path.exists():
                    try:
                        final_path.unlink()
                    except Exception:
                        pass
                temp_path.replace(final_path)

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
            artifact_file(file_row)
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
            artifact_file(file_row)        

        # stream the file to disk
        if (False):
            with dest_path.open("wb") as out_f:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)

            await upload.close()

            # register in DB with scoped metadata
            file_row = register_scoped_file(
                name=orig_name,
                path=str(dest_path),
                mime_type=upload.content_type,
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
            # kick off artifacting for this file (best-effort; logs on failure)
            artifact_file(file_row)

        results.append({"id": fid, "name": orig_name, "path": str(final_path)}) # dest_path

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

# region LLM Model Endpoints

@app.get("/api/models")
def api_models():
    #from .db import get_conn  # if you need it; otherwise ignore
    global _MODELS_CACHE, _MODELS_CACHE_TS
    now = time.time()
    if _MODELS_CACHE and (now - _MODELS_CACHE_TS) < _MODELS_TTL_SECONDS:
        return _MODELS_CACHE
    try:
        model_objs = client.models.list()
        items: list[dict] = []
        for m in model_objs:
            mid = getattr(m, "id", None)
            if not mid:
                continue

            if _ALLOWED_MODEL_PREFIXES and not mid.startswith(_ALLOWED_MODEL_PREFIXES):
                continue

            meta = MODEL_CATALOG.get(mid, {})

            created = getattr(m, "created", None)
            owned_by = getattr(m, "owned_by", None)
            vendor = meta.get("vendor", "OpenAI")
            display_name = meta.get("display_name", mid)
            description = meta.get("description", "")
            input_cost = meta.get("input_cost_per_million")
            output_cost = meta.get("output_cost_per_million")
            context_window = meta.get("context_window")
            tags = meta.get("tags", [])

            items.append(
                {
                    "id": mid,
                    "created": created,
                    "owned_by": owned_by,
                    "vendor": vendor,
                    "display_name": display_name,
                    "description": description,
                    "input_cost_per_million": input_cost,
                    "output_cost_per_million": output_cost,
                    "context_window": context_window,
                    "tags": tags,
                }
            )

        # Sort by display_name to keep dropdowns stable
        items.sort(key=lambda m: m["display_name"].lower())
        # Save to cache to prevent constant re-query
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
    cfg: QueryConfig = load_query_config()
    include_global=req.include_global
    if req.include_global:
        include_global=req.include_global
        log_warn("corpus_search is using req.include_global which may override cfg.query_global_artifacts, but only for healing functions.")
    else:
        include_global=cfg.query_global_artifacts
    # Optional: self-heal missing artifacts before searching
    ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=5, include_global=include_global)
    # 3A lazy repair for conversation transcript artifacts
    ensure_conversation_transcript_artifact_fresh(cid, force_full=False, reason="corpus_search")

    rows = search_corpus_for_conversation(
        conversation_id=cid,
        query=q,
        limit=req.limit,
        cfg=cfg,
        #include_global=req.include_global,
    )
    return {"ok": True, "results": rows}

# endregion
