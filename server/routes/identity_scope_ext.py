# server/routes/identity_scope_ext.py
"""Scoped identity management API.

This keeps tenant/user/persona permission logic out of the older compatibility
identity routes while the UI moves from one large Identity modal to three
separate management surfaces.
"""

from __future__ import annotations

import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from server.routes.base import app
from server.db_helpers import DATA_DIR, _utc_now_iso
from server.identity_db import (
    create_persona,
    create_tenant,
    create_user,
    list_personas,
    list_tenants,
    list_users,
    update_persona,
    update_tenant,
    update_user,
)
from server.identity_delete import annotate_delete_flags, force_delete_identity, hard_delete_identity
from server.identity_scope import (
    ensure_identity_scope_schema,
    filter_personas_for_user,
    set_persona_scope,
    set_user_scope_flags,
    user_can_manage_persona,
    user_can_manage_users,
    user_can_set_persona_scope,
    user_is_global_admin,
    user_is_tenant_admin,
)


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


_AVATAR_ROOT = DATA_DIR / "identity" / "avatars"
_AVATAR_MAX_BYTES = 5 * 1024 * 1024
_AVATAR_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _json_meta(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(str(value))
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _user_by_id(user_id: int) -> dict[str, Any] | None:
    rows = [u for u in list_users(None, include_disabled=True) if int(u.get("id") or 0) == int(user_id)]
    return rows[0] if rows else None


def _avatar_file_from_user(user: dict[str, Any]) -> Path | None:
    meta = _json_meta(user.get("meta_json"))
    rel = str(meta.get("avatar_path") or "").strip()
    if not rel:
        return None
    path = (DATA_DIR / rel).resolve()
    root = _AVATAR_ROOT.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def _capabilities(user_id: int | None, tenant_id: int | None) -> dict[str, bool]:
    ensure_identity_scope_schema()
    is_global_admin = user_is_global_admin(user_id)
    is_tenant_admin = user_is_tenant_admin(user_id, tenant_id)
    return {
        "is_global_admin": bool(is_global_admin),
        "is_tenant_admin": bool(is_tenant_admin),
        "can_manage_tenants": bool(is_global_admin),
        "can_manage_users": bool(is_global_admin or is_tenant_admin),
        "can_manage_personas": True,
        "can_set_user_global": bool(is_global_admin),
        "can_set_user_global_admin": bool(is_global_admin),
        "can_set_user_tenant_admin": bool(is_global_admin or is_tenant_admin),
        "can_set_persona_user": user_id is not None,
        "can_set_persona_tenant": bool(is_global_admin or is_tenant_admin),
        "can_set_persona_global": bool(is_global_admin),
        "can_force_delete_identity": bool(is_global_admin),
    }


def _require_global_admin(payload: dict[str, Any]) -> int:
    acting_user_id = _int_or_none((payload or {}).get("acting_user_id"))
    if not user_is_global_admin(acting_user_id):
        raise HTTPException(status_code=403, detail="Only a global admin can perform this action.")
    return int(acting_user_id)


def _require_user_manager(payload: dict[str, Any], tenant_id: int | None) -> int:
    acting_user_id = _int_or_none((payload or {}).get("acting_user_id"))
    if not user_can_manage_users(acting_user_id, tenant_id):
        raise HTTPException(status_code=403, detail="Only a global admin or tenant admin can manage users here.")
    return int(acting_user_id)


def _delete_or_force(entity_type: str, row_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if bool((payload or {}).get("force")):
        _require_global_admin(payload)
        return force_delete_identity(entity_type, row_id)
    return hard_delete_identity(entity_type, row_id)


def _persona_rows(tenant_id: int | None, user_id: int | None, include_disabled: bool = True) -> list[dict[str, Any]]:
    ensure_identity_scope_schema()
    rows = list_personas(tenant_id, include_disabled=include_disabled)
    rows = filter_personas_for_user(rows, tenant_id=tenant_id, user_id=user_id)
    return annotate_delete_flags("persona", rows)


@app.get("/api/identity/scope/bootstrap")
def api_scope_bootstrap(tenant_id: int | None = None, user_id: int | None = None):
    ensure_identity_scope_schema()
    caps = _capabilities(user_id, tenant_id)
    return JSONResponse({
        "capabilities": caps,
        "tenants": annotate_delete_flags("tenant", list_tenants()),
        "users": annotate_delete_flags("user", list_users(tenant_id, include_disabled=True)),
        "all_users": annotate_delete_flags("user", list_users(None, include_disabled=True)),
        "personas": _persona_rows(tenant_id, user_id, include_disabled=True),
    })


@app.get("/api/identity/scope/capabilities")
def api_scope_capabilities(tenant_id: int | None = None, user_id: int | None = None):
    return JSONResponse(_capabilities(user_id, tenant_id))


@app.post("/api/identity/scope/tenants")
def api_scope_create_tenant(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_global_admin(payload)
        row = create_tenant(
            name=str(payload.get("name") or "").strip(),
            kind=str(payload.get("kind") or "local").strip(),
            source_system=payload.get("source_system"),
            external_id=payload.get("external_id"),
            meta_json=payload.get("meta_json"),
        )
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/identity/scope/tenants/{tenant_id}")
def api_scope_update_tenant(tenant_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_global_admin(payload)
        return JSONResponse(update_tenant(tenant_id, payload))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/identity/scope/tenants/{tenant_id}")
def api_scope_delete_tenant(tenant_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        _require_global_admin(payload)
        return JSONResponse(_delete_or_force("tenant", tenant_id, payload))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/identity/scope/users")
def api_scope_create_user(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        tenant_id = _int_or_none(payload.get("tenant_id"))
        acting_user_id = _require_user_manager(payload, tenant_id)
        is_global = bool(payload.get("is_global"))
        is_global_admin = bool(payload.get("is_global_admin"))
        is_tenant_admin = bool(payload.get("is_tenant_admin"))
        if (is_global or is_global_admin) and not user_is_global_admin(acting_user_id):
            raise HTTPException(status_code=403, detail="Only a global admin can create global users or global admins.")
        if not is_global and tenant_id is None:
            raise HTTPException(status_code=400, detail="Tenant-scoped users require tenant_id.")
        if is_tenant_admin and not user_can_manage_users(acting_user_id, tenant_id):
            raise HTTPException(status_code=403, detail="Only a global admin or tenant admin can grant tenant-admin status here.")
        row = create_user(
            display_name=str(payload.get("display_name") or payload.get("name") or "").strip(),
            handle=payload.get("slug") or payload.get("handle"),
            slug=payload.get("slug"),
            email=payload.get("email"),
            discord_user_id=payload.get("discord_user_id"),
            tenant_id=tenant_id,
            is_global=is_global,
            is_global_admin=is_global_admin,
            role="global_admin" if is_global_admin else "tenant_admin" if is_tenant_admin else str(payload.get("role") or "member"),
            meta_json=payload.get("meta_json"),
        )
        if is_tenant_admin:
            row = set_user_scope_flags(int(row["id"]), is_tenant_admin=True, role="tenant_admin")
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/identity/scope/users/{user_id}")
def api_scope_update_user(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        tenant_id = _int_or_none(payload.get("tenant_id"))
        acting_user_id = _require_user_manager(payload, tenant_id)
        target_rows = [u for u in list_users(None, include_disabled=True) if int(u.get("id") or 0) == int(user_id)]
        target = target_rows[0] if target_rows else None
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")
        if not user_is_global_admin(acting_user_id):
            if int(target.get("is_global") or 0) == 1 or int(target.get("is_global_admin") or 0) == 1:
                raise HTTPException(status_code=403, detail="Tenant admins cannot edit global users.")
            target_tenant = target.get("tenant_id")
            if target_tenant is None or tenant_id is None or int(target_tenant) != int(tenant_id):
                raise HTTPException(status_code=403, detail="Tenant admins can only edit users in their own tenant.")
            if payload.get("is_global") or payload.get("is_global_admin"):
                raise HTTPException(status_code=403, detail="Only global admins can make users global.")
        patch = dict(payload)
        patch.pop("acting_user_id", None)
        is_tenant_admin = patch.pop("is_tenant_admin", None)
        row = update_user(user_id, patch)
        if is_tenant_admin is not None:
            row = set_user_scope_flags(user_id, is_tenant_admin=bool(is_tenant_admin), role="tenant_admin" if is_tenant_admin else row.get("role") or "member")
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/identity/scope/users/{user_id}/avatar")
async def api_scope_upload_user_avatar(
    user_id: int,
    acting_user_id: int | None = Form(default=None),
    file: UploadFile = File(...),
):
    try:
        target = _user_by_id(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found.")

        is_self_upload = acting_user_id is not None and int(acting_user_id) == int(user_id)
        target_tenant_id = _int_or_none(target.get("tenant_id"))
        if not is_self_upload:
            if int(target.get("is_global") or 0) == 1 or int(target.get("is_global_admin") or 0) == 1:
                if not user_is_global_admin(acting_user_id):
                    raise HTTPException(status_code=403, detail="Only a global admin can edit global user avatars.")
            else:
                _require_user_manager({"acting_user_id": acting_user_id}, target_tenant_id)

        original_name = Path(file.filename or "avatar").name
        content_type = (file.content_type or mimetypes.guess_type(original_name)[0] or "").split(";")[0].strip().lower()
        ext = _AVATAR_EXT_BY_MIME.get(content_type)
        if not ext:
            raise HTTPException(status_code=400, detail="Avatar must be a JPEG, PNG, GIF, or WebP image.")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _AVATAR_MAX_BYTES:
                raise HTTPException(status_code=400, detail="Avatar image must be 5 MB or smaller.")
            chunks.append(chunk)
        await file.close()
        if total <= 0:
            raise HTTPException(status_code=400, detail="Avatar image is empty.")

        _AVATAR_ROOT.mkdir(parents=True, exist_ok=True)
        filename = f"user-{int(user_id)}-{uuid.uuid4().hex}{ext}"
        dest = _AVATAR_ROOT / filename
        dest.write_bytes(b"".join(chunks))

        meta = _json_meta(target.get("meta_json"))
        old_path = _avatar_file_from_user(target)
        now = _utc_now_iso()
        meta.update({
            "avatar_path": str(Path("identity") / "avatars" / filename),
            "avatar_mime_type": content_type,
            "avatar_original_name": original_name,
            "avatar_updated_at": now,
        })
        update_user(user_id, {"meta_json": meta})
        if old_path and old_path != dest:
            try:
                old_path.unlink(missing_ok=True)
            except Exception:
                pass

        row = _user_by_id(user_id) or {}
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/identity/scope/users/{user_id}/avatar")
def api_scope_get_user_avatar(user_id: int):
    target = _user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    path = _avatar_file_from_user(target)
    if not path or not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found.")
    meta = _json_meta(target.get("meta_json"))
    media_type = str(meta.get("avatar_mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})


@app.delete("/api/identity/scope/users/{user_id}")
def api_scope_delete_user(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        if bool((payload or {}).get("force")):
            _require_global_admin(payload)
        else:
            _require_user_manager(payload, None)
        return JSONResponse(_delete_or_force("user", user_id, payload))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/identity/scope/personas")
def api_scope_create_persona(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        acting_user_id = _int_or_none(payload.get("acting_user_id"))
        tenant_id = _int_or_none(payload.get("tenant_id"))
        scope = str(payload.get("persona_scope") or "user").strip().lower()
        if scope not in {"user", "tenant", "global"}:
            scope = "user"
        if scope == "global" and not user_is_global_admin(acting_user_id):
            raise HTTPException(status_code=403, detail="Only a global admin can create global personas across all tenants.")
        if scope == "tenant" and not user_can_set_persona_scope(acting_user_id, persona_scope="tenant", tenant_id=tenant_id):
            raise HTTPException(status_code=403, detail="Only a tenant admin or global admin can create tenant-wide personas.")
        if scope == "user" and acting_user_id is None:
            raise HTTPException(status_code=400, detail="User-scoped personas require acting_user_id.")
        row = create_persona(
            name=str(payload.get("name") or "").strip(),
            slug=payload.get("slug"),
            tenant_id=tenant_id if scope in {"tenant", "user"} else None,
            description=payload.get("description"),
            system_prompt=payload.get("system_prompt"),
            prompt_file=payload.get("prompt_file"),
            default_model_deployment_id=payload.get("default_model_deployment_id"),
            meta_json=payload.get("meta_json"),
        )
        row = set_persona_scope(
            int(row["id"]),
            persona_scope=scope,
            owner_user_id=acting_user_id if scope == "user" else None,
            tenant_id=tenant_id if scope in {"tenant", "user"} else None,
        )
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.put("/api/identity/scope/personas/{persona_id}")
def api_scope_update_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        acting_user_id = _int_or_none(payload.get("acting_user_id"))
        tenant_id = _int_or_none(payload.get("tenant_id"))
        scope = str(payload.get("persona_scope") or "").strip().lower()
        if not user_can_manage_persona(acting_user_id, persona_id):
            raise HTTPException(status_code=403, detail="You cannot edit this persona.")
        if scope:
            if scope not in {"user", "tenant", "global"}:
                raise HTTPException(status_code=400, detail="Invalid persona scope.")
            if scope == "global" and not user_is_global_admin(acting_user_id):
                raise HTTPException(status_code=403, detail="Only a global admin can set a global persona across all tenants.")
            if scope == "tenant" and not user_can_set_persona_scope(acting_user_id, persona_scope="tenant", tenant_id=tenant_id):
                raise HTTPException(status_code=403, detail="Only a tenant admin or global admin can set tenant-wide personas.")
        patch = dict(payload)
        patch.pop("acting_user_id", None)
        patch.pop("persona_scope", None)
        patch.pop("owner_user_id", None)
        row = update_persona(persona_id, patch)
        if scope:
            row = set_persona_scope(
                persona_id,
                persona_scope=scope,
                owner_user_id=acting_user_id if scope == "user" else None,
                tenant_id=tenant_id if scope in {"tenant", "user"} else None,
            )
        return JSONResponse(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/identity/scope/personas/{persona_id}")
def api_scope_delete_persona(persona_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        acting_user_id = _int_or_none(payload.get("acting_user_id"))
        if bool((payload or {}).get("force")):
            _require_global_admin(payload)
        elif not user_can_manage_persona(acting_user_id, persona_id):
            raise HTTPException(status_code=403, detail="You cannot delete this persona.")
        return JSONResponse(_delete_or_force("persona", persona_id, payload))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
