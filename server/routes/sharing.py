from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.access_control import resolve_access
from server.db import (
    db_get_artifact_access_resource,
    db_get_conversation_access_resource,
    db_get_file_access_resource,
    db_get_memory_access_resource,
    db_get_message_access_resource,
    db_get_project_access_resource,
)
from server.db_helpers import db_session, list_access_control_entries
from server.routes.base import app


_RESOURCE_LOADERS = {
    "artifact": db_get_artifact_access_resource,
    "conversation": db_get_conversation_access_resource,
    "file": db_get_file_access_resource,
    "memory": db_get_memory_access_resource,
    "message": db_get_message_access_resource,
    "project": db_get_project_access_resource,
}


def _resource_for(resource_type: str, resource_id: str) -> dict:
    resource_type = (resource_type or "").strip().lower()
    resource_id = (resource_id or "").strip()
    loader = _RESOURCE_LOADERS.get(resource_type)
    if not loader:
        raise HTTPException(status_code=400, detail=f"Unsupported resource_type: {resource_type}")
    try:
        resource = loader(int(resource_id)) if resource_type in {"message", "project"} else loader(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


@app.get("/api/sharing/diagnostics")
def api_sharing_diagnostics(
    resource_type: str,
    resource_id: str,
    action: str = "read",
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str | None = None,
):
    resource = _resource_for(resource_type, resource_id)
    principal = {
        "principal_type": principal_type,
        "principal_id": principal_id,
        "tenant_id": tenant_id or resource.get("tenant_id") or "default",
    }

    with db_session() as conn:
        decision = resolve_access(principal, resource, action, explain=True, conn=conn)
        direct_entries = list_access_control_entries(
            conn=conn,
            tenant_id=resource.get("tenant_id") or "default",
            resource_type=resource["resource_type"],
            resource_id=resource["resource_id"],
            include_deleted=False,
        )
        inherited_entries = []
        for parent in resource.get("inherited_from") or []:
            inherited_entries.extend(
                list_access_control_entries(
                    conn=conn,
                    tenant_id=resource.get("tenant_id") or "default",
                    resource_type=parent.get("resource_type"),
                    resource_id=parent.get("resource_id"),
                    include_deleted=False,
                )
            )

    return JSONResponse(
        {
            "resource": resource,
            "principal": principal,
            "action": action,
            "decision": decision.to_dict(),
            "direct_access_control_entries": direct_entries,
            "inherited_access_control_entries": inherited_entries,
        }
    )
