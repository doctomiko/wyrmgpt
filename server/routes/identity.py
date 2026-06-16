# server/routes/identity.py
"""Tenant, user, and persona management routes."""

from __future__ import annotations

import json
from pathlib import Path
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
    user_is_global_admin,
)
from server.identity_delete import annotate_delete_flags, hard_delete_identity


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
.identityCheckboxRow { display: flex; gap: 6px; align-items: center; }
.identityCheckboxRow input { width: auto; }
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
              <button id="identityCancelTenantEdit" class="hidden">Cancel Update</button>
            </div>
            <div id="identityTenantList" class="identityList"></div>
          </section>
          <section class="identityManagerCol">
            <h3>Users</h3>
            <div class="identityFormStack">
              <select id="identityNewUserTenant"></select>
              <label class="identityCheckboxRow"><input id="identityNewUserGlobalAdmin" type="checkbox" /> Global admin</label>
              <input id="identityNewUserName" placeholder="Display name" />
              <input id="identityNewUserSlug" placeholder="slug / short name" />
              <button id="identityCreateUser">Create User</button>
              <button id="identityCancelUserEdit" class="hidden">Cancel Update</button>
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
              <select id="identityNewPersonaPromptFile"></select>
              <textarea id="identityNewPersonaPrompt" rows="5" placeholder="Optional custom persona system prompt"></textarea>
              <button id="identityCreatePersona">Create Persona</button>
              <button id="identityCancelPersonaEdit" class="hidden">Cancel Update</button>
            </div>
            <div id="identityPersonaList" class="identityList"></div>
          </section>
        </div>
      </div>
      <div class="modalActions"><button id="identityCloseBottom">Close</button></div>
    </div>
  </div>
""".rstrip()


def _annotated_payload(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data or {})
    out["tenants"] = annotate_delete_flags("tenant", out.get("tenants") or [])
    out["users"] = annotate_delete_flags("user", out.get("users") or [])
    out["all_users"] = annotate_delete_flags("user", out.get("all_users") or [])
    out["personas"] = annotate_delete_flags("persona", out.get("personas") or [])
    return out


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
    html = html.replace('  <script src="/static/app.events.js"></script>', '  <script src="/static/app.identity.js"></script>\n  <script src="/static/app.user_profiles.js"></script>\n  <script src="/static/app.events.js"></script>\n  <script src="/static/app.user_profiles_late.js"></script>')
    return html


def _headers_identity_payload(request: Request) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for header_name, key in (
        ("x-wyrmgpt-tenant-id", "tenant_id"),
        ("x-wyrmgpt-user-id", "user_id"),
        ("x-wyrmgpt-persona-id", "persona_id"),
        ("x-wyrmgpt-persona-slug", "persona_slug"),
    ):
        value = request.headers.get(header_name)
        if value is not None and str(value).strip() != "":
            payload[key] = value
    return payload


def _prompt_files_payload() -> list[dict[str, str]]:
    root = STATIC_DIR.parent.parent
    prompt_dir = root / "prompts"
    out: list[dict[str, str]] = []
    try:
        if prompt_dir.exists() and prompt_dir.is_dir():
            for p in sorted(prompt_dir.glob("*.txt"), key=lambda x: x.name.lower()):
                out.append({"name": p.name, "path": str(Path("prompts") / p.name)})
    except Exception:
        return []
    return out


def _require_admin_for_user_scope_change(payload: dict[str, Any]) -> None:
    guarded = {"tenant_id", "is_global", "is_global_admin", "role"}
    if not any(k in payload for k in guarded):
        return
    acting_user_id = payload.get("acting_user_id")
    if not user_is_global_admin(acting_user_id):
        raise HTTPException(status_code=403, detail="Only a global admin can change user tenant/global/admin status.")


def _require_global_admin(payload: dict[str, Any]) -> None:
    if not user_is_global_admin((payload or {}).get("acting_user_id")):
        raise HTTPException(status_code=403, detail="Only a global admin can perform this action.")


@app.middleware("http")
async def identity_context_middleware(request: Request, call_next):
    token = None
    try:
        if request.method.upper() == "GET" and request.url.path == "/":
            raw = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(_inject_identity_ui(raw))
        if request.method.upper() == "POST" and request.url.path in {"/api/chat", "/api/chat_ab"}:
            payload = _headers_identity_payload(request)
            if not payload:
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
    data = _annotated_payload(bootstrap_identity())
    data["prompt_files"] = _prompt_files_payload()
    return JSONResponse(data)


@app.get("/api/identity/defaults")
def api_identity_defaults():
    return JSONResponse(get_identity_defaults())


@app.get("/api/identity/prompt_files")
def api_identity_prompt_files():
    return JSONResponse({"prompt_files": _prompt_files_payload()})


@app.get("/api/tenants")
def api_list_tenants():
    return JSONResponse({"tenants": annotate_delete_flags("tenant", list_tenants())})


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


@app.delete("/api/tenants/{tenant_id}")
def api_delete_tenant(tenant_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_global_admin(payload)
        return JSONResponse(hard_delete_identity("tenant", tenant_id))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/users")
def api_list_users(tenant_id: int | None = None, include_disabled: bool = True):
    return JSONResponse({"users": annotate_delete_flags("user", list_users(tenant_id, include_disabled=include_disabled))})


@app.post("/api/users")
def api_create_user(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        wants_global = bool(payload.get("is_global") or payload.get("is_global_admin"))
        if wants_global and not user_is_global_admin(payload.get("acting_user_id")):
            raise HTTPException(status_code=403, detail="Only a global admin can create global users or global admins.")
        if not wants_global and payload.get("tenant_id") in (None, ""):
            raise HTTPException(status_code=400, detail="Tenant-scoped users require tenant_id.")
        return JSONResponse(create_user(display_name=str(payload.get("display_name") or payload.get("name") or "").strip(), handle=payload.get("slug") or payload.get("handle"), slug=payload.get("slug"), email=payload.get("email"), discord_user_id=payload.get("discord_user_id"), is_pk_identity=bool(payload.get("is_pk_identity")), tenant_id=payload.get("tenant_id"), is_global=bool(payload.get("is_global")), is_global_admin=bool(payload.get("is_global_admin")), role=str(payload.get("role") or "member"), meta_json=payload.get("meta_json")))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/users/{user_id}")
def api_update_user(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_admin_for_user_scope_change(payload)
        return JSONResponse(update_user(user_id, payload))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/users/{user_id}")
def api_delete_user(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_global_admin(payload)
        return JSONResponse(hard_delete_identity("user", user_id))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/tenants/{tenant_id}/users/{user_id}")
def api_add_user_to_tenant(tenant_id: int, user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        if not user_is_global_admin(payload.get("acting_user_id")):
            raise HTTPException(status_code=403, detail="Only a global admin can reassign users to tenants.")
        add_user_to_tenant(user_id=user_id, tenant_id=tenant_id, role=str(payload.get("role") or "member"))
        return JSONResponse({"ok": True})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/personas")
def api_list_personas(tenant_id: int | None = None, include_disabled: bool = True):
    return JSONResponse({"personas": annotate_delete_flags("persona", list_personas(tenant_id, include_disabled=include_disabled))})


@app.post("/api/personas")
def api_create_persona(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(create_persona(name=str(payload.get("name") or "").strip(), slug=payload.get("slug"), tenant_id=payload.get("tenant_id"), description=payload.get("description"), system_prompt=payload.get("system_prompt"), prompt_file=payload.get("prompt_file"), default_model_deployment_id=payload.get("default_model_deployment_id"), meta_json=payload.get("meta_json")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/personas/{persona_id}")
def api_update_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(update_persona(persona_id, payload))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/personas/{persona_id}")
def api_delete_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return JSONResponse(hard_delete_identity("persona", persona_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
