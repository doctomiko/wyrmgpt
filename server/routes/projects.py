


# region Project Endpoints

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.access_filtering import filter_rows_for_access, principal_from_request
from server.api_helpers import coerce_optional_int, http_from_value_error
from server.api_models import ArchiveRequest, ImportRule, ProjectCreateRequest, ProjectUpdateRequest
from server.db import (
    # Project CRUD
    db_list_projects, db_get_or_create_project, 
    db_update_project, db_set_project_hidden,
    db_get_project_delete_preview, db_delete_project, 
    # Special gettters
    db_list_citation_scope_cards_for_project, 
    # Special joins
    db_project_add_conversation, 
    db_project_add_file,
    # Special creators
    db_project_import,     
)


from server.db_helpers import db_session
from server.routes.base import app


# region Project helpers

def get_project_title_any(project_id: Any) -> str | None:
    pid = coerce_optional_int(project_id)
    if pid is None:
        return None
    with db_session() as conn:
        row = conn.execute("SELECT name FROM projects WHERE id = ? LIMIT 1", (pid,)).fetchone()
    return (row["name"] or "").strip() if row and row["name"] else None

# endregion

# region Project endpoints


@app.put("/api/projects/{project_id}")
def api_update_project(project_id: int, req: ProjectUpdateRequest):
    try:
        return JSONResponse(db_update_project(
            project_id,
            name=req.name,
            visibility=req.visibility,
            description=req.description,
            system_prompt=req.system_prompt,
            override_core_prompt=req.override_core_prompt,
            default_advanced_mode=req.default_advanced_mode,
        ))
    except ValueError as e:
        http_from_value_error(e)


@app.get("/api/projects")
def api_get_projects(
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    projects = filter_rows_for_access(db_list_projects(), "project", principal=principal)
    return {"projects": projects}


@app.post("/api/projects/{project_id}/archive")
def api_archive_project(project_id: int, req: ArchiveRequest):
    try:
        db_set_project_hidden(project_id, req.archived)
        return {"project_id": project_id, "archived": bool(req.archived)}
    except ValueError as e:
        http_from_value_error(e)


@app.get("/api/projects/{project_id}/delete_preview")
def api_project_delete_preview(project_id: int):
    try:
        return JSONResponse(db_get_project_delete_preview(project_id))
    except ValueError as e:
        http_from_value_error(e)


@app.delete("/api/projects/{project_id}")
def api_delete_project(project_id: int):
    try:
        return JSONResponse(db_delete_project(project_id))
    except ValueError as e:
        http_from_value_error(e)

@app.post("/api/projects")
def api_create_project(req: ProjectCreateRequest):
    try:
        # TODO add description
        proj = db_get_or_create_project(req.name, req.visibility)
        return proj
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/projects/{project_id}/assign_conversation/{conversation_id}")
def api_project_add_conversation(project_id: int, conversation_id: str):
    try:
        db_project_add_conversation(project_id, conversation_id, set_primary=True)
        return JSONResponse({"ok": True})
    except ValueError as e:
        http_from_value_error(e)


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
        http_from_value_error(e)

@app.post("/api/projects/{project_id}/files/{file_id}")
def api_project_add_file(project_id: int, file_id: str):
    try:
        db_project_add_file(project_id, file_id)
        return JSONResponse({"ok": True})
    except ValueError as e:
        http_from_value_error(e)
    
# endregion
