from typing import Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.api_helpers import http_from_value_error
from server.api_models import AboutYouRequest, MemoryCreate, MemoryLinkProjectRequest, MemoryUpdate, PinRequest
from server.db import (
    # CRUD for pins (custom instructions) and memories
    db_list_pins, db_add_pin, db_update_pin, db_delete_pin, 
    db_list_memories, db_add_memory, db_update_memory, db_delete_memory, 
    # Special PINs
    db_get_about_you_pin, upsert_about_you_pin, 
    # Special join helpers
    db_memory_link_conversation, db_memory_link_project, 
    # Other helpers
    db_get_or_create_project, invalidate_all_context_cache,
)

from server.routes.base import app


# region Memory APIs

@app.get("/api/memories")
def api_list_memories(limit: int = 200):
    return JSONResponse(db_list_memories(limit=limit))


@app.post("/api/memories")
def api_create_memory(req: MemoryCreate):
    try:
        mem = db_add_memory(
            req.content,
            importance=req.importance,
            tags=req.tags,
            created_by=req.created_by,
            origin_kind=req.origin_kind,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
            persona_id=req.persona_id,
            persona_context_mode=req.persona_context_mode,
        )
        invalidate_all_context_cache()
        return JSONResponse(mem)
    except ValueError as e:
        http_from_value_error(e)


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
            persona_id=req.persona_id,
            persona_context_mode=req.persona_context_mode,
        )
        invalidate_all_context_cache()
        return JSONResponse(mem)
    except ValueError as e:
        http_from_value_error(e)


@app.delete("/api/memories/{memory_id}")
def api_delete_memory(memory_id: str):
    try:
        db_delete_memory(memory_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        http_from_value_error(e)


@app.post("/api/memories/{memory_id}/link_project/{project_id}")
def api_memory_link_project(memory_id: str, project_id: int):
    try:
        db_memory_link_project(memory_id, project_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        http_from_value_error(e)


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
        http_from_value_error(e)


@app.post("/api/memories/{memory_id}/link_conversation/{conversation_id}")
def api_memory_link_conversation(memory_id: str, conversation_id: str):
    try:
        db_memory_link_conversation(memory_id, conversation_id)
        invalidate_all_context_cache()
        return JSONResponse({"ok": True})
    except ValueError as e:
        http_from_value_error(e)

# endregion

# region Pin (custom instructions) Endpoints

@app.post("/api/memory/pins")
def api_add_memory_pin(req: PinRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    new_id = db_add_pin(
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
    db_delete_pin(pin_id)
    invalidate_all_context_cache()
    return JSONResponse({"ok": True})


@app.put("/api/memory/pins/{pin_id}")
def api_update_memory_pin(pin_id: int, req: PinRequest):
    text = (req.text or "").strip()
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    row = db_update_pin(
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
    return JSONResponse(db_list_pins(limit=200))


@app.get("/api/memory/pins/about_you")
def api_get_about_you_pin():
    row = db_get_about_you_pin()
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
