# server/routes/user_profiles.py
"""Per-user profile routes, including About You."""

from __future__ import annotations

from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from server.routes.base import app
from server.identity_scope import user_is_global_admin, user_is_tenant_admin
from server.user_profiles import ensure_user_profile_schema, get_user_about_you, upsert_user_about_you
from server.identity_db import list_users
from server.db import invalidate_all_context_cache


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _user_row(user_id: int | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    for row in list_users(None, include_disabled=True):
        if int(row.get("id") or 0) == int(user_id):
            return row
    return None


def _can_edit_profile(acting_user_id: int | None, target_user_id: int | None) -> bool:
    if acting_user_id is None or target_user_id is None:
        return False
    if int(acting_user_id) == int(target_user_id):
        return True
    if user_is_global_admin(acting_user_id):
        return True
    target = _user_row(target_user_id)
    tenant_id = target.get("tenant_id") if target else None
    return user_is_tenant_admin(acting_user_id, tenant_id)


@app.get("/api/user_profiles/{user_id}/about_you")
def api_get_user_about_you(user_id: int, acting_user_id: int | None = None):
    ensure_user_profile_schema()
    actor = acting_user_id if acting_user_id is not None else user_id
    if not _can_edit_profile(actor, user_id):
        raise HTTPException(status_code=403, detail="You cannot view this user's About You profile.")
    return JSONResponse(get_user_about_you(user_id))


@app.post("/api/user_profiles/{user_id}/about_you")
def api_save_user_about_you(user_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    ensure_user_profile_schema()
    acting_user_id = _int_or_none(payload.get("acting_user_id")) or user_id
    if not _can_edit_profile(acting_user_id, user_id):
        raise HTTPException(status_code=403, detail="You cannot edit this user's About You profile.")
    row = upsert_user_about_you(user_id, payload)
    invalidate_all_context_cache()
    return JSONResponse(row)
