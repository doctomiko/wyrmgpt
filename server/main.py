import os
import uuid
from pathlib import Path
from typing import Optional, cast, Any
from dotenv import load_dotenv
from fastapi import Request, FastAPI, HTTPException
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

DEBUG_ERRORS = os.getenv("DEBUG_ERRORS", "1") == "1"

MODEL_CATALOG: dict[str, dict] = {}

# add near your OpenAI client init (or near globals)
_MODELS_CACHE: dict[str, Any] | None = None
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes

_ALLOWED_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4")

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
    set_conversation_project, # assign_conversation_project,
    update_project,
    # Files and Artifacts
    register_file as db_register_file,
    project_add_file as db_project_add_file,
    create_artifact as db_create_artifact,
    # Memory 
    add_memory_pin,
    list_memory_pins,
    delete_memory_pin,
    # Memories
    create_memory as db_create_memory,
    memory_link_project as db_memory_link_project,
    memory_link_conversation as db_memory_link_conversation,
)

# endregion

from .context import build_context, build_model_input

# DB_PATH = Path(__file__).parent / "state.db"

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

# Support checking for models
_MODELS_CACHE: dict[str, Any] | None = None
_MODELS_CACHE_TS: float = 0.0
_MODELS_TTL_SECONDS = 300  # 5 minutes

# region API Contracts (class definitions)

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

"""
class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str | None = None
    override_core_prompt: bool = False
    default_advanced_mode: bool = False
"""

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
    
"""
@app.get("/api/conversations")
def api_conversations():
    return JSONResponse(list_conversations(limit=200))

@app.get("/api/conversation/{conversation_id}/messages")
def api_conversation_messages(conversation_id: str):
    # Full raw history with metadata for UI (A/B pairs, timestamps, etc.)
    # Raw rows: id, role, content, created_at, meta (parsed JSON or None)
    return JSONResponse(get_messages_raw(conversation_id, limit=500))

@app.get("/api/conversation/{conversation_id}/context")
def api_conversation_context(conversation_id: str, preview_limit: int = 20):
    return JSONResponse(build_context(conversation_id, preview_limit=preview_limit))

@app.put("/api/conversation/{conversation_id}/title")
def api_set_title(conversation_id: str, req: TitleRequest):
    title = (req.title or "").strip()
    if not title:
        title = "New chat"
    update_conversation_title(conversation_id, title)
    return JSONResponse({"ok": True, "title": title})

@app.post("/api/conversation/{conversation_id}/suggest_title")
def api_suggest_title(conversation_id: str):
    msgs = get_messages(conversation_id, limit=80)

    # Flatten convo for a title prompt (keeps the model from “continuing” the chat)
    flat = []
    for m in msgs:
        role = m["role"]
        if role not in ("user", "assistant"):
            continue
        flat.append(f"{role.upper()}: {m['content']}")
    convo_text = "\n\n".join(flat)
    if len(convo_text) > 6000:
        convo_text = convo_text[-6000:]  # keep the tail

    instruction = (
        "Generate a short, specific chat title (3–8 words). "
        "No quotes. No punctuation unless necessary. "
        "Return ONLY the title."
    )

    resp = client.responses.create(
        model=TITLE_MODEL,
        input=[
            {"role": "system", "content": instruction},
            {"role": "user", "content": "Conversation:\n\n" + convo_text},
        ],
        max_output_tokens=30,
    )

    title = _extract_output_text(resp).strip()
    title = title.replace("\n", " ").strip().strip('"').strip("'")
    if len(title) > 80:
        title = title[:77] + "…"
    if not title:
        title = "New chat"

    update_conversation_title(conversation_id, title)
    return JSONResponse({"ok": True, "title": title})

@app.post("/api/conversations/{conversation_id}/project")
def api_move_conversation_project(conversation_id: str, req: MoveProjectRequest):
    conn = get_conn()

    project_id = None
    if req.project_id is not None:
        project_id = req.project_id
    elif req.project_name:
        project_id = get_or_create_project(conn, req.project_name)

    assign_conversation_project(conn, conversation_id, project_id)
    return {"conversation_id": conversation_id, "project_id": project_id}

@app.post("/api/conversations/{conversation_id}/archive")
def api_archive_conversation(conversation_id: str, req: ArchiveRequest):
    conn = get_conn()
    set_conversation_archived(conn, conversation_id, req.archived)
    return {"conversation_id": conversation_id, "archived": req.archived}

@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: str):
    conn = get_conn()
    delete_conversation(conn, conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}

@app.post("/api/conversations/{conversation_id}/summarize")
def api_summarize_conversation(conversation_id: str):
    conn = get_conn()

    cur = conn.execute(
        "SELECT title FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    title = row["title"]

    cur = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation_id,),
    )
    msgs = cur.fetchall()
    if not msgs:
        raise HTTPException(status_code=400, detail="Conversation is empty.")

    # crude transcript; you can refine later
    transcript_lines = []
    for m in msgs:
        transcript_lines.append(f"{m['role']}: {m['content']}")
    transcript = "\n\n".join(transcript_lines)

    system_prompt = (
        "You are a helpful assistant that summarizes chat conversations for later review. "
        "Write a concise summary (1–3 short paragraphs) capturing key decisions, questions, and outcomes. "
        "Do NOT add new advice – only summarize what was actually said."
    )

    # use your default model or a specific summary model
    model = MODEL  # or SUMMARY_MODEL if you define one

    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Title: {title}\n\nFull transcript:\n\n{transcript}",
                },
            ],
            max_output_tokens=400,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")

    # Safely extract text from varied SDK response shapes
    summary_text = _extract_output_text(resp)
    if not summary_text:
        # guarded fallback for unexpected structures
        try:
            out = getattr(resp, "output", None)
            if isinstance(out, list) and out:
                first = out[0]
                content = getattr(first, "content", None)
                if isinstance(content, list) and content:
                    text = getattr(content[0], "text", None)
                    if isinstance(text, str):
                        summary_text = text
        except Exception:
            pass
    if not summary_text:
        summary_text = ""

    # message content
    summary_message = f"Summary of “{title}”:\n\n{summary_text}"

    from .db import add_message  # assuming you already have this

    add_message(
        conversation_id,
        "assistant",
        summary_message,
        meta={"summary": True, "model": model},
    )

    save_conversation_summary(conn, conversation_id, summary_text, model)

    return {
        "conversation_id": conversation_id,
        "summary": summary_text,
        "model": model,
    }
"""

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

"""
@app.post("/api/memories")
def create_memory(req: MemoryCreate):
    mid = str(uuid.uuid4())
    db_write("" "
        INSERT INTO memories (id, content, importance, tags)
        VALUES (?, ?, ?, ?)
    "" ", (mid, req.content, req.importance, req.tags))
    return {"id": mid}

@app.post("/api/memories/{memory_id}/link_project/{project_id}")
def memory_link_project(memory_id: str, project_id: str):
    db_write("INSERT OR IGNORE INTO memory_projects VALUES (?,?)", (memory_id, project_id))
    return {"ok": True}

@app.post("/api/memories/{memory_id}/link_conversation/{conversation_id}")
def memory_link_conversation(memory_id: str, conversation_id: str):
    db_write("INSERT OR IGNORE INTO memory_conversations VALUES (?,?)", (memory_id, conversation_id))
    return {"ok": True}
"""        
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

"""
@app.get("/api/projects")
def api_get_projects():
    # rows = db_read("SELECT * FROM projects")
    # return [dict(r) for r in rows]
    conn = get_conn()
    projects = get_projects(conn)
    return {"projects": projects}

@app.post("/api/projects")
def api_create_project(req: ProjectCreateRequest):
    # pid = str(uuid.uuid4())
    # db_write("" "
    #    INSERT INTO projects (id, name, description, system_prompt, override_core_prompt, default_advanced_mode)
    #    VALUES (?, ?, ?, ?, ?, ?)
    #"" ", (pid, req.name, req.description, req.system_prompt, int(req.override_core_prompt), int(req.default_advanced_mode)))
    #return {"id": pid}
    conn = get_conn()
    try:
        pid = get_or_create_project(conn, req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # TODO move to db.py
    cur = conn.execute(
        "SELECT id, name, description, system_prompt, override_core_prompt, default_advanced_mode, created_at, updated_at FROM projects WHERE id = ?",
        (pid,),
    )
    row = cur.fetchone()
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] if "description" in row else None,
        "system_prompt": row["system_prompt"] if "system_prompt" in row else None,
        "override_core_prompt": bool(row["override_core_prompt"]) if "override_core_prompt" in row else False,
        "default_advanced_mode": bool(row["default_advanced_mode"]) if "default_advanced_mode" in row else False,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

@app.post("/api/projects/{project_id}/assign_conversation/{conversation_id}")
def project_add_conversation(project_id: str, conversation_id: str):
    db_write("INSERT OR IGNORE INTO project_conversations VALUES (?,?)", (project_id, conversation_id))
    return {"ok": True}

@app.post("/api/projects/{project_id}/files/{file_id}")
def project_add_file(project_id: str, file_id: str):
    db_write("INSERT OR IGNORE INTO project_files VALUES (?,?)", (project_id, file_id))
    return {"ok": True}

@app.post("/api/projects/{project_id}/artifacts")
def create_artifact(project_id: str, req: ArtifactCreate):
    aid = str(uuid.uuid4())
    db_write("" "
        INSERT INTO artifacts (id, project_id, name, content, tags)
        VALUES (?, ?, ?, ?, ?)
    "" ", (aid, project_id, req.name, req.content, req.tags))
    return {"id": aid}

@app.post("/api/projects/{project_id}/import_from/{source_id}")
def project_import(project_id: str, source_id: str, req: ImportRule):
    db_write("" "
        INSERT OR REPLACE INTO project_imports
        (project_id, source_project_id, include_tags, exclude_tags, include_artifact_ids)
        VALUES (?, ?, ?, ?, ?)
    " "", (project_id, source_id, req.include_tags, req.exclude_tags, req.include_artifact_ids))
    return {"ok": True}
"""
    
# endregion

# region File Endpoints

@app.post("/api/files")
def api_register_file(req: FileRegister):
    try:
        out = db_register_file(req.name, req.path, req.mime_type)
        return JSONResponse(out)
    except ValueError as e:
        _http_from_value_error(e)

"""
@app.post("/api/files")
def register_file(req: FileRegister):
    fid = str(uuid.uuid4())
    db_write("" "
        INSERT INTO files (id, name, path, mime_type)
        VALUES (?, ?, ?, ?)
    "" ", (fid, req.name, req.path, req.mime_type))
    return {"id": fid}
"""

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
