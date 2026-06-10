# server/routes/identity.py
"""Tenant, user, and persona management routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from server.routes.base import app
from server.runtime import STATIC_DIR
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


_IDENTITY_STYLE = """
<style id="identityUiStyle">
.identityPicker { min-width: 180px; }
.identityPicker select { width: 100%; }
.identitySideGrid { display: grid; gap: 8px; }
.identitySideGrid label { display: grid; gap: 3px; font-size: 0.85rem; }
.identityBadge { margin-top: 8px; font-size: 0.78rem; opacity: 0.75; line-height: 1.25; }
.identityManagerGrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.identityManagerCol { border: 1px solid rgba(128,128,128,.25); border-radius: 8px; padding: 10px; }
.identityManagerCol h3 { margin: 0 0 8px 0; font-size: 1rem; }
.identityFormStack { display: grid; gap: 6px; margin-bottom: 10px; }
.identityFormStack input, .identityFormStack select, .identityFormStack textarea { width: 100%; box-sizing: border-box; }
.identityList { display: grid; gap: 5px; margin-top: 8px; max-height: 260px; overflow: auto; }
.identityListItem, .identityEmpty { padding: 6px 8px; border-radius: 6px; background: rgba(128,128,128,.10); font-size: .85rem; }
.identityEmpty { opacity: .65; font-style: italic; }
@media (max-width: 1100px) { .identityManagerGrid { grid-template-columns: 1fr; } }
</style>
""".strip()


_IDENTITY_SIDE_PANEL = """
      <div class="rightSideSection" id="identitySidePanel">
        <div class="contextHeaderRow">
          <div class="memTitle">Active Identity</div>
        </div>
        <div class="identitySideGrid">
          <label>Tenant<select id="identityTenantSelect"></select></label>
          <label>User<select id="identityUserSelect"></select></label>
        </div>
        <div id="identityBadge" class="identityBadge"></div>
      </div>
""".rstrip()


_PERSONA_PICKER = """
          <div class="modelPicker identityPicker">
            <label>Persona</label>
            <select id="identityPersonaSelect"></select>
            <div class="modelInfo">Assistant identity / prompt layer</div>
          </div>
""".rstrip()


_IDENTITY_MODAL = """
  <div id="identityModal" class="modal hidden">
    <div class="modalBackdrop"></div>
    <div class="modalPanel" style="max-width: 1080px;">
      <div class="modalHeader">
        <div class="modalTitle">Manage Identity</div>
        <button id="identityClose" class="iconButton" title="Close">&times;</button>
      </div>
      <div class="modalBody">
        <div class="memHint" style="margin-bottom: 12px;">
          Tenants define shared boundaries. Users define who is speaking. Personas define which assistant identity answers.
        </div>
        <div class="identityManagerGrid">
          <section class="identityManagerCol">
            <h3>Tenants</h3>
            <div class="identityFormStack">
              <input id="identityNewTenantName" placeholder="Tenant name" />
              <input id="identityNewTenantKind" placeholder="kind: local, household, discord_guild…" value="local" />
              <button id="identityCreateTenant">Create Tenant</button>
            </div>
            <div id="identityTenantList" class="identityList"></div>
          </section>
          <section class="identityManagerCol">
            <h3>Users</h3>
            <div class="identityFormStack">
              <select id="identityNewUserTenant"></select>
              <input id="identityNewUserName" placeholder="Display name" />
              <input id="identityNewUserHandle" placeholder="handle / short name" />
              <button id="identityCreateUser">Create User</button>
            </div>
            <div id="identityUserList" class="identityList"></div>
          </section>
          <section class="identityManagerCol">
            <h3>Personas</h3>
            <div class="identityFormStack">
              <select id="identityNewPersonaTenant"></select>
              <input id="identityNewPersonaName" placeholder="Persona name" />
              <input id="identityNewPersonaSlug" placeholder="slug, e.g. callie" />
              <input id="identityNewPersonaDescription" placeholder="Short description" />
              <textarea id="identityNewPersonaPrompt" rows="5" placeholder="Optional persona system prompt"></textarea>
              <button id="identityCreatePersona">Create Persona</button>
            </div>
            <div id="identityPersonaList" class="identityList"></div>
          </section>
        </div>
      </div>
      <div class="modalActions"><button id="identityCloseBottom">Close</button></div>
    </div>
  </div>
""".rstrip()


def _inject_identity_ui(html: str) -> str:
    if "app.identity.js" in html:
        return html
    html = html.replace("</head>", f"  {_IDENTITY_STYLE}\n</head>")
    html = html.replace('<button id="openMemory">Personalization…</button>', '<button id="openMemory">Personalization…</button>\n            <button id="manageIdentityTop">Manage Identity…</button>')
    advanced_block = """          <div id="advancedModelB" class="modelPicker">
            <label>Model B</label>
            <select id="modelSelectB"></select>
            <div id="modelInfoB" class="modelInfo"></div>
          </div>"""
    html = html.replace(advanced_block, advanced_block + "\n" + _PERSONA_PICKER)
    html = html.replace('    <aside id="rightSidePanel">\n', '    <aside id="rightSidePanel">\n' + _IDENTITY_SIDE_PANEL + "\n")
    html = html.replace('  <div id="memoryModal" class="modal hidden">', _IDENTITY_MODAL + '\n  <div id="memoryModal" class="modal hidden">')
    html = html.replace('  <script src="/static/app.events.js"></script>', '  <script src="/static/app.identity.js"></script>\n  <script src="/static/app.events.js"></script>')
    return html


@app.middleware("http")
async def identity_context_middleware(request: Request, call_next):
    """Inject identity UI and capture active identity for chat requests."""
    token = None
    try:
        if request.method.upper() == "GET" and request.url.path == "/":
            raw = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(_inject_identity_ui(raw))

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
        return JSONResponse(create_tenant(name=str(payload.get("name") or "").strip(), kind=str(payload.get("kind") or "local").strip(), source_system=payload.get("source_system"), external_id=payload.get("external_id"), meta_json=payload.get("meta_json")))
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
        return JSONResponse(create_user(display_name=str(payload.get("display_name") or payload.get("name") or "").strip(), handle=payload.get("handle"), tenant_id=payload.get("tenant_id"), role=str(payload.get("role") or "member"), meta_json=payload.get("meta_json")))
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
        return JSONResponse(create_persona(name=str(payload.get("name") or "").strip(), slug=payload.get("slug"), tenant_id=payload.get("tenant_id"), description=payload.get("description"), system_prompt=payload.get("system_prompt"), default_model_deployment_id=payload.get("default_model_deployment_id"), meta_json=payload.get("meta_json")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/personas/{persona_id}")
def api_update_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(update_persona(persona_id, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
