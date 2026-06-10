# server/identity_db.py
"""Tenant, user, and persona storage helpers for WyrmGPT."""
from __future__ import annotations

import contextvars
import json
import re
import sqlite3
from typing import Any

from .db_helpers import db_session, new_uuid, _utc_now_iso, _add_column_if_missing

_ACTIVE_IDENTITY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("wyrmgpt_active_identity", default=None)
_PATCH_INSTALLED = False
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _slug(value: Any, default: str = "item") -> str:
    raw = str(value or default).strip().lower()
    raw = _SLUG_RE.sub("-", raw).strip("-._")
    return raw or default


def _txt(value: Any) -> str:
    return str(value or "").strip()


def _json(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps({"value": value}, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return {k: row[k] for k in row.keys()} if row else None


def ensure_identity_schema() -> None:
    with db_session() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tenants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'local',
            source_system TEXT,
            external_id TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            meta_json TEXT,
            UNIQUE(source_system, external_id)
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            handle TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            meta_json TEXT
        );
        CREATE TABLE IF NOT EXISTS tenant_users (
            tenant_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id INTEGER,
            user_id INTEGER NOT NULL,
            profile_kind TEXT NOT NULL DEFAULT 'about_me',
            title TEXT,
            content_text TEXT NOT NULL,
            visibility TEXT NOT NULL DEFAULT 'tenant',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            meta_json TEXT
        );
        CREATE TABLE IF NOT EXISTS chat_personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT NOT NULL UNIQUE,
            tenant_id INTEGER,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            description TEXT,
            system_prompt TEXT,
            system_prompt_artifact_id TEXT,
            default_model_deployment_id TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            meta_json TEXT,
            UNIQUE(tenant_id, slug)
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_users_user ON tenant_users(user_id);
        CREATE INDEX IF NOT EXISTS idx_chat_personas_tenant ON chat_personas(tenant_id);
        """)
        _add_column_if_missing(conn, "conversations", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "active_user_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "default_persona_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "user_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "persona_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "identity_json", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_persona ON messages(persona_id)")
        _seed_defaults(conn)


def _seed_defaults(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    t = conn.execute("SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1").fetchone()
    if not t:
        conn.execute("INSERT INTO tenants(uuid,name,kind,source_system,external_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (new_uuid(), "Local", "local", "wyrmgpt", "local", now, now))
        t = conn.execute("SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1").fetchone()
    tenant_id = int(t["id"])
    u = conn.execute("SELECT id FROM users WHERE handle='local-user' LIMIT 1").fetchone()
    if not u:
        conn.execute("INSERT INTO users(uuid,display_name,handle,created_at,updated_at) VALUES(?,?,?,?,?)", (new_uuid(), "Local User", "local-user", now, now))
        u = conn.execute("SELECT id FROM users WHERE handle='local-user' LIMIT 1").fetchone()
    user_id = int(u["id"])
    conn.execute("INSERT OR IGNORE INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?)", (tenant_id, user_id, "owner", now, now))
    p = conn.execute("SELECT id FROM chat_personas WHERE tenant_id=? AND slug='callie' LIMIT 1", (tenant_id,)).fetchone()
    if not p:
        conn.execute("INSERT INTO chat_personas(uuid,tenant_id,name,slug,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (new_uuid(), tenant_id, "Callie", "callie", "Default WyrmGPT assistant persona.", now, now))


def set_active_identity(identity: dict[str, Any] | None) -> contextvars.Token:
    return _ACTIVE_IDENTITY.set(normalize_identity_payload(identity or {}))


def reset_active_identity(token: contextvars.Token) -> None:
    _ACTIVE_IDENTITY.reset(token)


def get_active_identity() -> dict[str, Any] | None:
    return _ACTIVE_IDENTITY.get()


def _int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except Exception:
        return default


def get_identity_defaults() -> dict[str, Any]:
    ensure_identity_schema()
    with db_session() as conn:
        t = conn.execute("SELECT id FROM tenants WHERE is_enabled=1 ORDER BY CASE WHEN source_system='wyrmgpt' AND external_id='local' THEN 0 ELSE 1 END, id LIMIT 1").fetchone()
        tenant_id = int(t["id"]) if t else None
        u = conn.execute("SELECT u.id FROM users u LEFT JOIN tenant_users tu ON tu.user_id=u.id WHERE u.is_enabled=1 AND (? IS NULL OR tu.tenant_id=?) ORDER BY CASE WHEN u.handle='local-user' THEN 0 ELSE 1 END, u.id LIMIT 1", (tenant_id, tenant_id)).fetchone()
        user_id = int(u["id"]) if u else None
        p = conn.execute("SELECT id FROM chat_personas WHERE is_enabled=1 AND (? IS NULL OR tenant_id IS NULL OR tenant_id=?) ORDER BY CASE WHEN slug='callie' THEN 0 ELSE 1 END, id LIMIT 1", (tenant_id, tenant_id)).fetchone()
        persona_id = int(p["id"]) if p else None
    return {"tenant_id": tenant_id, "user_id": user_id, "persona_id": persona_id}


def get_persona_by_slug(slug: str, tenant_id: int | None = None) -> dict[str, Any] | None:
    ensure_identity_schema()
    slug = _slug(slug, "")
    if not slug:
        return None
    with db_session() as conn:
        row = conn.execute("SELECT * FROM chat_personas WHERE slug=? AND is_enabled=1 AND (? IS NULL OR tenant_id IS NULL OR tenant_id=?) ORDER BY CASE WHEN tenant_id=? THEN 0 ELSE 1 END, id LIMIT 1", (slug, tenant_id, tenant_id, tenant_id)).fetchone()
    return _row(row)


def normalize_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    d = get_identity_defaults()
    tenant_id = _int(payload.get("tenant_id"), d.get("tenant_id"))
    user_id = _int(payload.get("user_id"), d.get("user_id"))
    persona_id = _int(payload.get("persona_id"), d.get("persona_id"))
    persona_slug = _txt(payload.get("persona_slug"))
    if persona_slug and not payload.get("persona_id"):
        p = get_persona_by_slug(persona_slug, tenant_id)
        if p:
            persona_id = int(p["id"])
    return {"tenant_id": tenant_id, "user_id": user_id, "persona_id": persona_id, "persona_slug": persona_slug or None}


def list_tenants() -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        rows = conn.execute("SELECT * FROM tenants ORDER BY is_enabled DESC, name COLLATE NOCASE, id").fetchall()
    return [_row(r) for r in rows]


def create_tenant(name: str, kind: str = "local", source_system: str | None = None, external_id: str | None = None, meta_json: Any = None) -> dict[str, Any]:
    ensure_identity_schema(); now = _utc_now_iso(); name = _txt(name)
    if not name: raise ValueError("Tenant name is required.")
    with db_session() as conn:
        cur = conn.execute("INSERT INTO tenants(uuid,name,kind,source_system,external_id,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?,?,?)", (new_uuid(), name, _slug(kind, "local"), source_system, external_id, now, now, _json(meta_json)))
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (cur.lastrowid,)).fetchone()
    return _row(row) or {}


def update_tenant(tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema(); allowed = {"name", "kind", "source_system", "external_id", "is_enabled", "meta_json"}; sets=[]; vals=[]
    for k, v in patch.items():
        if k not in allowed: continue
        if k == "name": v = _txt(v) or (_ for _ in ()).throw(ValueError("Tenant name cannot be empty."))
        if k == "kind": v = _slug(v, "local")
        if k == "is_enabled": v = 1 if v else 0
        if k == "meta_json": v = _json(v)
        sets.append(f"{k}=?"); vals.append(v)
    if sets:
        vals += [_utc_now_iso(), int(tenant_id)]
        with db_session() as conn:
            conn.execute(f"UPDATE tenants SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    with db_session() as conn: row = conn.execute("SELECT * FROM tenants WHERE id=?", (int(tenant_id),)).fetchone()
    return _row(row) or {}


def list_users(tenant_id: int | None = None) -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        if tenant_id is None:
            rows = conn.execute("SELECT * FROM users ORDER BY is_enabled DESC, display_name COLLATE NOCASE, id").fetchall()
        else:
            rows = conn.execute("SELECT u.*, tu.tenant_id, tu.role AS tenant_role FROM users u JOIN tenant_users tu ON tu.user_id=u.id WHERE tu.tenant_id=? ORDER BY u.is_enabled DESC, u.display_name COLLATE NOCASE, u.id", (int(tenant_id),)).fetchall()
    return [_row(r) for r in rows]


def create_user(display_name: str, handle: str | None = None, tenant_id: int | None = None, role: str = "member", meta_json: Any = None) -> dict[str, Any]:
    ensure_identity_schema(); now = _utc_now_iso(); display_name = _txt(display_name)
    if not display_name: raise ValueError("User display name is required.")
    with db_session() as conn:
        cur = conn.execute("INSERT INTO users(uuid,display_name,handle,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?)", (new_uuid(), display_name, _slug(handle or display_name, "user"), now, now, _json(meta_json)))
        user_id = int(cur.lastrowid)
        if tenant_id is not None:
            conn.execute("INSERT OR IGNORE INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?)", (int(tenant_id), user_id, _slug(role, "member"), now, now))
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row(row) or {}


def update_user(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema(); allowed={"display_name","handle","is_enabled","meta_json"}; sets=[]; vals=[]
    for k, v in patch.items():
        if k not in allowed: continue
        if k == "display_name": v = _txt(v) or (_ for _ in ()).throw(ValueError("User display name cannot be empty."))
        if k == "handle": v = _slug(v, "user")
        if k == "is_enabled": v = 1 if v else 0
        if k == "meta_json": v = _json(v)
        sets.append(f"{k}=?"); vals.append(v)
    if sets:
        vals += [_utc_now_iso(), int(user_id)]
        with db_session() as conn: conn.execute(f"UPDATE users SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    with db_session() as conn: row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    return _row(row) or {}


def add_user_to_tenant(user_id: int, tenant_id: int, role: str = "member") -> None:
    ensure_identity_schema(); now = _utc_now_iso()
    with db_session() as conn:
        conn.execute("INSERT INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,user_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at", (int(tenant_id), int(user_id), _slug(role, "member"), now, now))


def list_personas(tenant_id: int | None = None, include_disabled: bool = False) -> list[dict[str, Any]]:
    ensure_identity_schema(); where=[]; vals=[]
    if not include_disabled: where.append("p.is_enabled=1")
    if tenant_id is not None: where.append("(p.tenant_id IS NULL OR p.tenant_id=?)"); vals.append(int(tenant_id))
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    with db_session() as conn:
        rows = conn.execute(f"SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id {sql_where} ORDER BY p.is_enabled DESC, COALESCE(t.name,'Global') COLLATE NOCASE, p.name COLLATE NOCASE, p.id", vals).fetchall()
    return [_row(r) for r in rows]


def create_persona(name: str, slug: str | None = None, tenant_id: int | None = None, description: str | None = None, system_prompt: str | None = None, default_model_deployment_id: str | None = None, meta_json: Any = None) -> dict[str, Any]:
    ensure_identity_schema(); now = _utc_now_iso(); name = _txt(name)
    if not name: raise ValueError("Persona name is required.")
    with db_session() as conn:
        cur = conn.execute("INSERT INTO chat_personas(uuid,tenant_id,name,slug,description,system_prompt,default_model_deployment_id,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?,?,?,?,?)", (new_uuid(), int(tenant_id) if tenant_id is not None else None, name, _slug(slug or name, "persona"), description, system_prompt, default_model_deployment_id, now, now, _json(meta_json)))
        row = conn.execute("SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?", (cur.lastrowid,)).fetchone()
    return _row(row) or {}


def update_persona(persona_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema(); allowed={"tenant_id","name","slug","description","system_prompt","system_prompt_artifact_id","default_model_deployment_id","is_enabled","meta_json"}; sets=[]; vals=[]
    for k, v in patch.items():
        if k not in allowed: continue
        if k == "name": v = _txt(v) or (_ for _ in ()).throw(ValueError("Persona name cannot be empty."))
        if k == "slug": v = _slug(v, "persona")
        if k == "tenant_id": v = int(v) if v not in (None, "") else None
        if k == "is_enabled": v = 1 if v else 0
        if k == "meta_json": v = _json(v)
        sets.append(f"{k}=?"); vals.append(v)
    if sets:
        vals += [_utc_now_iso(), int(persona_id)]
        with db_session() as conn: conn.execute(f"UPDATE chat_personas SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    with db_session() as conn: row = conn.execute("SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?", (int(persona_id),)).fetchone()
    return _row(row) or {}


def get_conversation_identity(conversation_id: str) -> dict[str, Any] | None:
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute("SELECT tenant_id, active_user_id AS user_id, default_persona_id AS persona_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    d = _row(row)
    return d if d and any(d.values()) else None


def stamp_message_identity(message_id: int, conversation_id: str, role: str, identity: dict[str, Any]) -> None:
    if not message_id: return
    ensure_identity_schema(); now = _utc_now_iso(); tenant_id=identity.get("tenant_id"); user_id=identity.get("user_id"); persona_id=identity.get("persona_id")
    with db_session() as conn:
        conn.execute("UPDATE messages SET tenant_id=?, user_id=?, persona_id=?, identity_json=? WHERE id=?", (tenant_id, user_id if role == "user" else None, persona_id, json.dumps(identity, ensure_ascii=False, sort_keys=True), int(message_id)))
        conn.execute("UPDATE conversations SET tenant_id=COALESCE(tenant_id,?), active_user_id=COALESCE(active_user_id,?), default_persona_id=COALESCE(default_persona_id,?), updated_at=? WHERE id=?", (tenant_id, user_id, persona_id, now, conversation_id))


def install_identity_message_patch() -> None:
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED: return
    import server.db as db_mod
    original = db_mod.db_add_message
    if getattr(original, "_identity_wrapped", False): _PATCH_INSTALLED = True; return
    def wrapped(conversation_id: str, role: str, content: str, meta: dict | None = None, author_meta: dict | None = None) -> int:
        active = get_active_identity() or get_conversation_identity(conversation_id) or get_identity_defaults()
        meta_obj = dict(meta or {}); author_obj = dict(author_meta or {})
        public = {"tenant_id": active.get("tenant_id"), "user_id": active.get("user_id"), "persona_id": active.get("persona_id"), "persona_slug": active.get("persona_slug")}
        meta_obj.setdefault("identity", public)
        if role == "user": author_obj.setdefault("identity", public)
        if role == "assistant": meta_obj.setdefault("responder_persona_id", active.get("persona_id"))
        mid = original(conversation_id, role, content, meta=meta_obj or None, author_meta=author_obj or None)
        try: stamp_message_identity(mid, conversation_id, role, active)
        except Exception: pass
        return mid
    wrapped._identity_wrapped = True  # type: ignore[attr-defined]
    db_mod.db_add_message = wrapped
    _PATCH_INSTALLED = True


def bootstrap_identity() -> dict[str, Any]:
    defaults = get_identity_defaults()
    return {"defaults": defaults, "tenants": list_tenants(), "users": list_users(defaults.get("tenant_id")), "all_users": list_users(), "personas": list_personas(defaults.get("tenant_id"), include_disabled=True)}
