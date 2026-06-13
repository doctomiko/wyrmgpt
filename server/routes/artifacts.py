from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.access_filtering import filter_items_by_resource_access, principal_from_request
from server.api_models import ArtifactMoveScopeRequest
from server.config import load_retrieval_config
from server.db import db_move_artifact_scope, db_get_scoped_artifact_debug

from server.routes.base import app


@app.post("/api/artifacts/{artifact_id}/move_scope")
def api_move_artifact_scope(artifact_id: str, body: ArtifactMoveScopeRequest):
    try:
        out = db_move_artifact_scope(
            artifact_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            scope_uuid=body.scope_uuid,
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/conversation/{conversation_id}/artifacts/debug")
def api_conversation_artifacts_debug(
    conversation_id: str,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    query_cfg = load_retrieval_config()
    data = db_get_scoped_artifact_debug(
        conversation_id,
        include_global=query_cfg.query_global_artifacts,
        preview_chars=180,
    )
    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    artifacts = filter_items_by_resource_access(
        data.get("artifacts") or [],
        "artifact",
        id_key="artifact_id",
        principal=principal,
    )
    by_scope = {}
    for item in artifacts:
        scope_key = item.get("scope_key") or "unknown"
        by_scope.setdefault(scope_key, {"artifact_count": 0, "chunk_count": 0})
        by_scope[scope_key]["artifact_count"] += 1
        by_scope[scope_key]["chunk_count"] += int(item.get("chunk_count") or 0)
    data["artifacts"] = artifacts
    data["by_scope"] = by_scope
    return JSONResponse(data)
