# server/routes/identity.py
"""Tenant, user, and persona management routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from server.routes.base import app
from server.identity_db import (
    add_user_to_tenant,
    bootstrap_identity,
    create_persona,
    create_tenant,
    create_user,
    get_identity_defaults,
    list_personas,
    list_tenants,
    list_users,
    normalize_identity_payload,
    reset_active_identity,
    set_active_identity,
    update_persona,
    update_tenant,
    update_user,
)


@app.middleware("http")
async def identity_context_middleware(request: Request, call_next):
    """Capture active identity for chat requests without invasive chat-route edits.

    The UI/API may pass tenant_id, user_id, persona_id, or persona_slug in JSON bodies for
    /api/chat and /api/chat_ab. We bind that to a contextvar so db_add_message can stamp
    persisted rows. For non-chat requests this middleware is effectively inert.
    """
    token = None
    try:
        if request.method.upper() == "POST" and request.url.path in {"/api/chat", "/api/chat_ab"}:
            payload: dict[str, Any] = {}
            try:
                raw = await request.body()
                if raw:
                    parsed = json.loads(raw.decode("utf-8"))
                    if isinstance(parsed, dict):
                        payload = parsed
            except Exception:
                payload = {}
            token = set_active_identity(normalize_identity_payload(payload))
        response = await call_next(request)
        return response
    finally:
        if token is not None:
            # Starlette generally keeps the context for the streaming iterator once created.
            # Reset here to avoid accidental leakage in non-streaming request paths.
            try:
                reset_active_identity(token)
            except Exception:
                pass


@app.get("/api/identity/bootstrap")
def api_identity_bootstrap():
    return JSONResponse(bootstrap_identity())


@app.get("/api/identity/defaults")
def api_identity_defaults():
    return JSONResponse(get_identity_defaults())


@app.get("/api/tenants")
def api_list_tenants():
    return JSONResponse({"tenants": list_tenants()})


@app.post("/api/tenants")
def api_create_tenant(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        tenant = create_tenant(
            name=str(payload.get("name") or "").strip(),
            kind=str(payload.get("kind") or "local").strip(),
            source_system=payload.get("source_system"),
            external_id=payload.get("external_id"),
            meta_json=payload.get("meta_json"),
        )
        return JSONResponse(tenant)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/tenants/{tenant_id}")
def api_update_tenant(tenant_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(update_tenant(tenant_id, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/users")
def api_list_users(tenant_id: int | None = None):
    return JSONResponse({"users": list_users(tenant_id)})


@app.post("/api/users")
def api_create_user(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        user = create_user(
            display_name=str(payload.get("display_name") or payload.get("name") or "").strip(),
            handle=payload.get("handle"),
            tenant_id=payload.get("tenant_id"),
            role=str(payload.get("role") or "member"),
            meta_json=payload.get("meta_json"),
        )
        return JSONResponse(user)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/users/{user_id}")
def api_update_user(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(update_user(user_id, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tenants/{tenant_id}/users/{user_id}")
def api_add_user_to_tenant(tenant_id: int, user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        add_user_to_tenant(user_id=user_id, tenant_id=tenant_id, role=str(payload.get("role") or "member"))
        return JSONResponse({"ok": True})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/personas")
def api_list_personas(tenant_id: int | None = None, include_disabled: bool = True):
    return JSONResponse({"personas": list_personas(tenant_id, include_disabled=include_disabled)})


@app.post("/api/personas")
def api_create_persona(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        persona = create_persona(
            name=str(payload.get("name") or "").strip(),
            slug=payload.get("slug"),
            tenant_id=payload.get("tenant_id"),
            description=payload.get("description"),
            system_prompt=payload.get("system_prompt"),
            default_model_deployment_id=payload.get("default_model_deployment_id"),
            meta_json=payload.get("meta_json"),
        )
        return JSONResponse(persona)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/personas/{persona_id}")
def api_update_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(update_persona(persona_id, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
