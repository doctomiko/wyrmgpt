from fastapi import HTTPException
from fastapi.responses import JSONResponse

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
def api_conversation_artifacts_debug(conversation_id: str):
    query_cfg = load_retrieval_config()
    data = db_get_scoped_artifact_debug(
        conversation_id,
        include_global=query_cfg.query_global_artifacts,
        preview_chars=180,
    )
    return JSONResponse(data)
