import os
import uuid
from pathlib import Path
from typing import Optional, cast, Any
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response, status, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import traceback
from contextlib import asynccontextmanager
from pydantic import BaseModel
from openai import OpenAI
# From openai/types/responses/response_create_params.py
from openai.types.responses import ResponseInputParam
# Support checking for models
import time
from typing import Any, Optional
import json
from pathlib import Path

# region data layer imports

from .db import (
    # Schema and connection
    init_schema,
    db_debug_info,
    # Chat Messages
    add_message,
    get_messages,
    get_messages_raw,
    update_ab_canonical,
    # Converstaions
    list_conversations,
    create_conversation,
    delete_conversation,
    set_conversation_archived,
    get_conversation_title,
    update_conversation_title,
    get_conversation_context,
    get_transcript_for_summary,
    save_conversation_summary,
    # Projects and subordinate entities
    list_projects,
    get_or_create_project,
    get_or_create_project as db_get_or_create_project,  # optional convenience endpoint
    project_add_conversation as db_project_add_conversation,
    project_import as db_project_import,
    set_conversation_project,  # assign_conversation_project,
    update_project,
    # Files and Artifacts
    register_file as db_register_file,
    project_add_file as db_project_add_file,
    create_artifact as db_create_artifact,
    register_scoped_file,
    update_file_description,
    conversation_link_file,
    list_files_for_conversation,
    list_files_for_project,
    list_all_files,
    get_files_summary,
    # Context cache
    invalidate_context_cache_for_conversation,
    invalidate_context_cache_for_project,
    # Memory Pins
    add_memory_pin,
    list_memory_pins,
    delete_memory_pin,
    # Memories
    create_memory as db_create_memory,
    memory_link_project as db_memory_link_project,
    memory_link_conversation as db_memory_link_conversation,# Shared paths
    # Shared data dir
    DATA_DIR,
)

# endregion

from .artifactor import artifact_file
from .context import build_context, build_model_input

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"

MODEL_CATALOG: dict[str, dict] = {}

# add near your OpenAI client init (or near globals)
_MODELS_CACHE: dict[str, Any] | None = None
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes

_ALLOWED_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
TITLE_MODEL = os.getenv("OPENAI_TITLE_MODEL", MODEL)

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

HERE = Path(__file__).resolve().parent
STATIC_DIR = HERE / "static"
# This is where uploaded files are stored; you can change this or add subdirs as needed
SOURCES_ROOT = DATA_DIR / "sources"
# This is where APIs for supported toools (retrievers, file parsers, etc.) would live; you can add subdirs as needed
TOOLS_DIR = HERE / "tools"

# Support checking for models
_MODELS_CACHE: dict[str, Any] | None = None
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes

# region API Contracts (class definitions)

class FileDescriptionUpdate(BaseModel):
    description: str | None = None

class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

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

class PinRequest(BaseModel):
    text: str

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

# endregion

# region Helper functions

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

    add_message(cid, "user", req.message)

    raw_input = build_model_input(cid, history_limit=200)
    model_input = cast(ResponseInputParam, raw_input)
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
                full = "".join(parts).strip()
                if full:
                    add_message(cid, "assistant", full, meta={"model": model})
        except Exception as e:
            yield f"\n[server exception: {type(e).__name__}]"

    resp = StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
    resp.headers["X-Conversation-Id"] = cid
    return resp

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

    model_a = (req.model_a or MODEL).strip()
    model_b = (req.model_b or model_a).strip()

    # Run the two models sequentially; simple but robust
    resp_a = client.responses.create(model=model_a, input=model_input)
    text_a = _extract_output_text(resp_a)

    resp_b = client.responses.create(model=model_b, input=model_input)
    text_b = _extract_output_text(resp_b)

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

@app.post("/api/conversations/{conversation_id}/summarize")
def api_summarize_conversation(conversation_id: str):
    try:
        title, transcript = get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    system_prompt = (
        "You are a helpful assistant that summarizes chat conversations for later review. "
        "Write a concise summary (1–3 short paragraphs) capturing key decisions, questions, and outcomes. "
        "Do NOT add new advice – only summarize what was actually said."
    )

    model = MODEL
    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Title: {title}\n\nFull transcript:\n\n{transcript}"},
            ],
            max_output_tokens=400,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")

    summary_text = _extract_output_text(resp) or ""
    summary_message = f"Summary of “{title}”:\n\n{summary_text}"

    add_message(
        conversation_id,
        "assistant",
        summary_message,
        meta={"summary": True, "model": model},
    )
    save_conversation_summary(conversation_id, summary_text, model)

    return {"conversation_id": conversation_id, "summary": summary_text, "model": model}

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

@app.get("/api/conversation/{conversation_id}/context")
def api_conversation_context(conversation_id: str, preview_limit: int = 20):
    try:
        return JSONResponse(build_context(conversation_id, preview_limit=preview_limit))
    except KeyError:
        raise HTTPException(status_code=404, detail="Not Found")

# endregion

# region Memory Endpoints

@app.post("/api/memories")
def api_create_memory(req: MemoryCreate):
    try:
        mem = db_create_memory(req.content, importance=req.importance, tags=req.tags)
        # keep it simple + compatible
        return JSONResponse({"id": mem["id"]})
    except ValueError as e:
        _http_from_value_error(e)


# Compatibility endpoint (same URL you had before),
# but project_id is NOW an int, consistent with schema v2.
@app.post("/api/memories/{memory_id}/link_project/{project_id}")
def api_memory_link_project(memory_id: str, project_id: int):
    try:
        db_memory_link_project(memory_id, project_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)


# Optional convenience: link by project name or id without putting it in the URL.
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
        return JSONResponse({"ok": True, "project_id": pid})
    except ValueError as e:
        _http_from_value_error(e)

@app.post("/api/memories/{memory_id}/link_conversation/{conversation_id}")
def api_memory_link_conversation(memory_id: str, conversation_id: str):
    try:
        db_memory_link_conversation(memory_id, conversation_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        _http_from_value_error(e)

# endregion

# region Memory Pin Endpoints

@app.get("/api/memory/pins")
def api_memory_pins():
    return JSONResponse(list_memory_pins(limit=200))

@app.post("/api/memory/pins")
def api_add_memory_pin(req: PinRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    new_id = add_memory_pin(text)
    return JSONResponse({"ok": True, "id": new_id})

@app.delete("/api/memory/pins/{pin_id}")
def api_delete_memory_pin(pin_id: int):
    delete_memory_pin(pin_id)
    return JSONResponse({"ok": True})

# endregion

# region Project Endpoints

@app.put("/api/projects/{project_id}")
def api_update_project(project_id: int, req: ProjectUpdateRequest):
    try:
        return JSONResponse(update_project(project_id, name=req.name, description=req.description))
    except ValueError as e:
        _http_from_value_error(e)

@app.get("/api/projects")
def api_get_projects():
    return {"projects": list_projects()}

@app.post("/api/projects")
def api_create_project(req: ProjectCreateRequest):
    try:
        proj = get_or_create_project(req.name)
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

@app.post("/api/projects/{project_id}/artifacts")
def api_create_artifact(project_id: int, req: ArtifactCreate):
    try:
        out = db_create_artifact(project_id, req.name, req.content, req.tags)
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

        # avoid overwriting existing files
        dest_path = dest_root / orig_name
        counter = 1
        while dest_path.exists():
            dest_path = dest_root / f"{dest_path.stem}_{counter}{dest_path.suffix}"
            counter += 1

        # stream the file to disk
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

        results.append({"id": fid, "name": orig_name, "path": str(dest_path)})

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
            scope_type="chat",
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
