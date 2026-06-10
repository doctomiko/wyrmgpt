# server/identity_scope.py
"""Scope and role helpers for tenants, users, and personas."""

from __future__ import annotations

from typing import Any

from .db_helpers import db_session, _add_column_if_missing, _utc_now_iso


def ensure_identity_scope_schema() -> None:
    with db_session() as conn:
        _add_column_if_missing(conn, "users", "is_tenant_admin", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "chat_personas", "persona_scope", "TEXT NOT NULL DEFAULT 'tenant'")
        _add_column_if_missing(conn, "chat_personas", "owner_user_id", "INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant_admin ON users(is_tenant_admin)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_personas_scope ON chat_personas(persona_scope)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_personas_owner ON chat_personas(owner_user_id)")
        conn.execute("UPDATE users SET is_tenant_admin=1 WHERE role='tenant_admin'")
        conn.execute("UPDATE chat_personas SET persona_scope='tenant' WHERE persona_scope IS NULL OR persona_scope='' OR persona_scope NOT IN ('user','tenant','global')")


def user_is_global_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    ensure_identity_scope_schema()
    with db_session() as conn:
        row = conn.execute("SELECT is_global_admin FROM users WHERE id=? AND is_enabled=1", (int(user_id),)).fetchone()
    return bool(row and int(row["is_global_admin"] or 0) == 1)


def user_is_tenant_admin(user_id: int | None, tenant_id: int | None = None) -> bool:
    if user_id is None:
        return False
    ensure_identity_scope_schema()
    if user_is_global_admin(user_id):
        return True
    with db_session() as conn:
        row = conn.execute("SELECT tenant_id, is_tenant_admin FROM users WHERE id=? AND is_enabled=1", (int(user_id),)).fetchone()
    if not row or int(row["is_tenant_admin"] or 0) != 1:
        return False
    if tenant_id is None:
        return True
    return row["tenant_id"] is not None and int(row["tenant_id"]) == int(tenant_id)


def user_can_manage_users(user_id: int | None, tenant_id: int | None = None) -> bool:
    return user_is_global_admin(user_id) or user_is_tenant_admin(user_id, tenant_id)


def set_user_scope_flags(
    user_id: int,
    *,
    is_tenant_admin: bool | None = None,
    is_global_admin: bool | None = None,
    tenant_id: int | None | object = None,
    is_global: bool | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    ensure_identity_scope_schema()
    sets: list[str] = []
    vals: list[Any] = []
    if is_tenant_admin is not None:
        sets.append("is_tenant_admin=?")
        vals.append(1 if is_tenant_admin else 0)
    if is_global_admin is not None:
        sets.append("is_global_admin=?")
        vals.append(1 if is_global_admin else 0)
    if is_global is not None:
        sets.append("is_global=?")
        vals.append(1 if is_global else 0)
    if tenant_id is not None:
        sets.append("tenant_id=?")
        vals.append(None if tenant_id == "" else tenant_id)
    if role is not None:
        sets.append("role=?")
        vals.append(role)
    if sets:
        sets.append("updated_at=?")
        vals.append(_utc_now_iso())
        vals.append(int(user_id))
        with db_session() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", vals)
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    return dict(row) if row else {}


def set_persona_scope(
    persona_id: int,
    *,
    persona_scope: str = "tenant",
    owner_user_id: int | None = None,
    tenant_id: int | None = None,
) -> dict[str, Any]:
    ensure_identity_scope_schema()
    scope = str(persona_scope or "tenant").strip().lower()
    if scope not in {"user", "tenant", "global"}:
        scope = "tenant"
    if scope == "user" and owner_user_id is None:
        raise ValueError("User-scoped personas require owner_user_id.")
    with db_session() as conn:
        conn.execute(
            "UPDATE chat_personas SET persona_scope=?, owner_user_id=?, tenant_id=?, updated_at=? WHERE id=?",
            (scope, owner_user_id if scope == "user" else None, tenant_id, _utc_now_iso(), int(persona_id)),
        )
        row = conn.execute("SELECT * FROM chat_personas WHERE id=?", (int(persona_id),)).fetchone()
    return dict(row) if row else {}


def filter_personas_for_user(
    rows: list[dict[str, Any]],
    *,
    tenant_id: int | None,
    user_id: int | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    can_tenant = user_is_tenant_admin(user_id, tenant_id)
    for row in rows or []:
        scope = str(row.get("persona_scope") or "tenant").strip().lower()
        row_tenant = row.get("tenant_id")
        owner = row.get("owner_user_id")
        if scope == "global":
            out.append(row)
        elif scope == "user":
            if user_id is not None and owner is not None and int(owner) == int(user_id):
                out.append(row)
            elif can_tenant and tenant_id is not None and row_tenant is not None and int(row_tenant) == int(tenant_id):
                out.append(row)
        else:
            if tenant_id is None or row_tenant is None or int(row_tenant) == int(tenant_id):
                out.append(row)
    return out


def get_persona_row(persona_id: int) -> dict[str, Any] | None:
    ensure_identity_scope_schema()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM chat_personas WHERE id=?", (int(persona_id),)).fetchone()
    return dict(row) if row else None


def user_can_manage_persona(user_id: int | None, persona_id: int) -> bool:
    persona = get_persona_row(persona_id)
    if not persona:
        return False
    scope = str(persona.get("persona_scope") or "tenant").strip().lower()
    tenant_id = persona.get("tenant_id")
    if user_is_global_admin(user_id):
        return True
    if scope == "user":
        owner = persona.get("owner_user_id")
        return user_id is not None and owner is not None and int(owner) == int(user_id)
    return user_is_tenant_admin(user_id, tenant_id)


def user_can_set_persona_scope(user_id: int | None, *, persona_scope: str, tenant_id: int | None) -> bool:
    scope = str(persona_scope or "tenant").strip().lower()
    if scope == "user":
        return user_id is not None
    return user_is_tenant_admin(user_id, tenant_id)
