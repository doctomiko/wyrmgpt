# server/identity_db.py
"""Tenant, user, and persona storage helpers for WyrmGPT."""
from __future__ import annotations

import contextvars
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .db_helpers import db_session, new_uuid, _utc_now_iso, _add_column_if_missing

_ACTIVE_IDENTITY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("wyrmgpt_active_identity", default=None)
_PATCH_INSTALLED = False
_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_ROOT = Path(__file__).resolve().parents[1]


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


def _meta_dict(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        decoded = json.loads(str(value))
        return decoded if isinstance(decoded, dict) else {}
    except Exception:
        return {}


def _decorate_user(row: dict[str, Any]) -> dict[str, Any]:
    meta = _meta_dict(row.get("meta_json"))
    row["meta"] = meta
    avatar_path = str(meta.get("avatar_path") or "").strip()
    if avatar_path:
        rev = str(meta.get("avatar_updated_at") or row.get("updated_at") or "").strip()
        suffix = f"?v={rev}" if rev else ""
        row["avatar_url"] = f"/api/identity/scope/users/{row['id']}/avatar{suffix}"
    else:
        row["avatar_url"] = None
    return row


def _int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except Exception:
        return default


def _bool_int(value: Any) -> int:
    if isinstance(value, str):
        return 1 if value.strip().lower() in {"1", "true", "yes", "on", "global_admin"} else 0
    return 1 if value else 0


def _read_prompt_file(path_value: str | None) -> str:
    raw_value = _txt(path_value)
    if not raw_value:
        return ""
    raw = Path(raw_value)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(_ROOT / raw)
        candidates.append(Path.cwd() / raw)
        candidates.append(raw)
    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return ""


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
            email TEXT,
            discord_user_id TEXT,
            is_pk_identity INTEGER NOT NULL DEFAULT 0,
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

        _add_column_if_missing(conn, "users", "slug", "TEXT")
        _add_column_if_missing(conn, "users", "email", "TEXT")
        _add_column_if_missing(conn, "users", "discord_user_id", "TEXT")
        _add_column_if_missing(conn, "users", "is_pk_identity", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "users", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "users", "is_global", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "users", "is_global_admin", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "users", "role", "TEXT NOT NULL DEFAULT 'member'")
        _add_column_if_missing(conn, "chat_personas", "prompt_file", "TEXT")

        _add_column_if_missing(conn, "conversations", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "active_user_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "default_persona_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "user_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "persona_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "identity_json", "TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_global ON users(is_global)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_slug ON users(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_tenant ON messages(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_persona ON messages(persona_id)")

        _seed_defaults(conn)
        _backfill_user_scope(conn)


def _seed_defaults(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    t = conn.execute("SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1").fetchone()
    if not t:
        conn.execute(
            "INSERT INTO tenants(uuid,name,kind,source_system,external_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (new_uuid(), "Local", "local", "wyrmgpt", "local", now, now),
        )
        t = conn.execute("SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1").fetchone()
    tenant_id = int(t["id"])

    u = conn.execute("SELECT id FROM users WHERE handle='local-user' OR slug='local-user' LIMIT 1").fetchone()
    if not u:
        conn.execute(
            """
            INSERT INTO users(uuid,display_name,handle,slug,is_global,is_global_admin,role,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (new_uuid(), "Local User", "local-user", "local-user", 1, 1, "global_admin", now, now),
        )
        u = conn.execute("SELECT id FROM users WHERE slug='local-user' LIMIT 1").fetchone()
    user_id = int(u["id"])
    conn.execute(
        """
        UPDATE users
        SET slug='local-user', handle='local-user', is_global=1, is_global_admin=1, role='global_admin', tenant_id=NULL, updated_at=?
        WHERE id=?
        """,
        (now, user_id),
    )
    conn.execute("INSERT OR IGNORE INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?)", (tenant_id, user_id, "owner", now, now))

    p = conn.execute("SELECT id FROM chat_personas WHERE tenant_id=? AND slug='callie' LIMIT 1", (tenant_id,)).fetchone()
    if not p:
        conn.execute(
            "INSERT INTO chat_personas(uuid,tenant_id,name,slug,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (new_uuid(), tenant_id, "Callie", "callie", "Default WyrmGPT assistant persona.", now, now),
        )


def _backfill_user_scope(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    conn.execute("UPDATE users SET slug = COALESCE(NULLIF(slug,''), NULLIF(handle,''), 'user-' || id)")
    conn.execute("UPDATE users SET handle = COALESCE(NULLIF(handle,''), slug)")
    rows = conn.execute(
        """
        SELECT u.id AS user_id, MIN(tu.tenant_id) AS tenant_id, MAX(CASE WHEN tu.role IN ('owner','admin') THEN tu.role ELSE '' END) AS role
        FROM users u
        JOIN tenant_users tu ON tu.user_id = u.id
        WHERE COALESCE(u.is_global,0) = 0 AND u.tenant_id IS NULL
        GROUP BY u.id
        """
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE users SET tenant_id=?, role=COALESCE(NULLIF(?,''), role), updated_at=? WHERE id=?",
            (r["tenant_id"], r["role"], now, r["user_id"]),
        )


def set_active_identity(identity: dict[str, Any] | None) -> contextvars.Token:
    return _ACTIVE_IDENTITY.set(normalize_identity_payload(identity or {}))


def reset_active_identity(token: contextvars.Token) -> None:
    _ACTIVE_IDENTITY.reset(token)


def get_active_identity() -> dict[str, Any] | None:
    return _ACTIVE_IDENTITY.get()


def user_is_global_admin(user_id: int | None) -> bool:
    if user_id is None:
        return False
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute("SELECT is_global_admin FROM users WHERE id=? AND is_enabled=1", (int(user_id),)).fetchone()
    return bool(row and int(row["is_global_admin"] or 0) == 1)


def get_identity_defaults() -> dict[str, Any]:
    ensure_identity_schema()
    with db_session() as conn:
        t = conn.execute("SELECT id FROM tenants WHERE is_enabled=1 ORDER BY CASE WHEN source_system='wyrmgpt' AND external_id='local' THEN 0 ELSE 1 END, id LIMIT 1").fetchone()
        tenant_id = int(t["id"]) if t else None
        u = conn.execute("SELECT id FROM users WHERE is_enabled=1 AND is_global_admin=1 ORDER BY CASE WHEN slug='local-user' THEN 0 ELSE 1 END, id LIMIT 1").fetchone()
        if not u:
            u = conn.execute("SELECT id FROM users WHERE is_enabled=1 AND (is_global=1 OR tenant_id=?) ORDER BY is_global DESC, id LIMIT 1", (tenant_id,)).fetchone()
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
        row = conn.execute(
            """
            SELECT * FROM chat_personas
            WHERE slug=? AND is_enabled=1 AND (? IS NULL OR tenant_id IS NULL OR tenant_id=?)
            ORDER BY CASE WHEN tenant_id=? THEN 0 ELSE 1 END, id LIMIT 1
            """,
            (slug, tenant_id, tenant_id, tenant_id),
        ).fetchone()
    return _row(row)


def get_persona_prompt_for_conversation(conversation_id: str) -> dict[str, Any] | None:
    ensure_identity_schema()
    active = get_active_identity() or {}
    persona_id = _int(active.get("persona_id"))
    with db_session() as conn:
        if persona_id is None:
            conv = conn.execute("SELECT default_persona_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
            if conv:
                persona_id = _int(conv["default_persona_id"])
        if persona_id is None:
            return None
        row = conn.execute("SELECT * FROM chat_personas WHERE id=? AND is_enabled=1", (persona_id,)).fetchone()
    persona = _row(row)
    if not persona:
        return None
    prompt_file = _txt(persona.get("prompt_file"))
    prompt_text = _read_prompt_file(prompt_file)
    source = "file" if prompt_text else "custom"
    if not prompt_text:
        prompt_text = _txt(persona.get("system_prompt"))
    if not prompt_text:
        return None
    return {
        "persona_id": persona.get("id"),
        "name": persona.get("name"),
        "slug": persona.get("slug"),
        "prompt_file": prompt_file,
        "source": source,
        "text": prompt_text,
    }


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


def list_users(tenant_id: int | None = None, include_disabled: bool = True) -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        where = [] if include_disabled else ["u.is_enabled=1"]
        params: list[Any] = []
        if tenant_id is not None:
            where.append("(u.is_global=1 OR u.tenant_id=?)")
            params.append(int(tenant_id))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"""
            SELECT u.*, t.name AS tenant_name
            FROM users u
            LEFT JOIN tenants t ON t.id = u.tenant_id
            {where_sql}
            ORDER BY u.is_enabled DESC, u.is_global_admin DESC, u.is_global DESC, u.display_name COLLATE NOCASE, u.id
            """,
            params,
        ).fetchall()
    return [_decorate_user(_row(r) or {}) for r in rows]


def create_user(display_name: str, handle: str | None = None, tenant_id: int | None = None, role: str = "member", meta_json: Any = None, is_global: bool = False, is_global_admin: bool = False, slug: str | None = None, email: str | None = None, discord_user_id: str | None = None, is_pk_identity: bool = False) -> dict[str, Any]:
    ensure_identity_schema(); now = _utc_now_iso(); display_name = _txt(display_name)
    if not display_name: raise ValueError("User display name is required.")
    user_slug = _slug(slug or handle or display_name, "user")
    email_value = _txt(email) or None
    discord_value = _txt(discord_user_id) or user_slug
    global_flag = 1 if is_global or tenant_id is None else 0
    admin_flag = 1 if is_global_admin else 0
    tenant_value = None if global_flag else int(tenant_id)
    role_value = "global_admin" if admin_flag else _slug(role, "member")
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO users(uuid,display_name,handle,slug,email,discord_user_id,is_pk_identity,tenant_id,is_global,is_global_admin,role,created_at,updated_at,meta_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (new_uuid(), display_name, user_slug, user_slug, email_value, discord_value, _bool_int(is_pk_identity), tenant_value, global_flag, admin_flag, role_value, now, now, _json(meta_json)),
        )
        user_id = int(cur.lastrowid)
        if tenant_value is not None:
            conn.execute("INSERT OR IGNORE INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?)", (tenant_value, user_id, role_value, now, now))
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row(row) or {}


def update_user(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema(); allowed={"display_name","handle","slug","email","discord_user_id","is_pk_identity","tenant_id","is_global","is_global_admin","role","is_enabled","meta_json"}; sets=[]; vals=[]
    patch = dict(patch or {})
    if "slug" in patch and "handle" not in patch:
        patch["handle"] = patch["slug"]
    if patch.get("is_global_admin"):
        patch["is_global"] = True
        patch["tenant_id"] = None
        patch["role"] = "global_admin"
    elif patch.get("is_global"):
        patch["tenant_id"] = None
    for k, v in patch.items():
        if k not in allowed: continue
        if k == "display_name": v = _txt(v) or (_ for _ in ()).throw(ValueError("User display name cannot be empty."))
        if k in {"handle", "slug"}: v = _slug(v, "user")
        if k == "email": v = _txt(v) or None
        if k == "discord_user_id": v = _txt(v) or _slug(patch.get("slug") or patch.get("handle"), "user")
        if k == "tenant_id": v = int(v) if v not in (None, "") else None
        if k in {"is_global", "is_global_admin", "is_enabled", "is_pk_identity"}: v = _bool_int(v)
        if k == "role": v = _slug(v, "member")
        if k == "meta_json": v = _json(v)
        sets.append(f"{k}=?"); vals.append(v)
    if sets:
        vals += [_utc_now_iso(), int(user_id)]
        with db_session() as conn:
            conn.execute(f"UPDATE users SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
            row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
            if row and row["tenant_id"] is not None and int(row["is_global"] or 0) == 0:
                conn.execute("INSERT OR IGNORE INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?)", (int(row["tenant_id"]), int(user_id), row["role"] or "member", _utc_now_iso(), _utc_now_iso()))
    with db_session() as conn: row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    return _row(row) or {}


def add_user_to_tenant(user_id: int, tenant_id: int, role: str = "member") -> None:
    ensure_identity_schema(); now = _utc_now_iso(); role = _slug(role, "member")
    with db_session() as conn:
        conn.execute("UPDATE users SET tenant_id=?, is_global=0, role=?, updated_at=? WHERE id=?", (int(tenant_id), role, now, int(user_id)))
        conn.execute("INSERT INTO tenant_users(tenant_id,user_id,role,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,user_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at", (int(tenant_id), int(user_id), role, now, now))


def list_personas(tenant_id: int | None = None, include_disabled: bool = False) -> list[dict[str, Any]]:
    ensure_identity_schema(); where=[]; vals=[]
    if not include_disabled: where.append("p.is_enabled=1")
    if tenant_id is not None: where.append("(p.tenant_id IS NULL OR p.tenant_id=?)"); vals.append(int(tenant_id))
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    with db_session() as conn:
        rows = conn.execute(f"SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id {sql_where} ORDER BY p.is_enabled DESC, COALESCE(t.name,'Global') COLLATE NOCASE, p.name COLLATE NOCASE, p.id", vals).fetchall()
    return [_row(r) for r in rows]


def create_persona(name: str, slug: str | None = None, tenant_id: int | None = None, description: str | None = None, system_prompt: str | None = None, default_model_deployment_id: str | None = None, meta_json: Any = None, prompt_file: str | None = None) -> dict[str, Any]:
    ensure_identity_schema(); now = _utc_now_iso(); name = _txt(name)
    if not name: raise ValueError("Persona name is required.")
    with db_session() as conn:
        cur = conn.execute("INSERT INTO chat_personas(uuid,tenant_id,name,slug,description,system_prompt,prompt_file,default_model_deployment_id,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (new_uuid(), int(tenant_id) if tenant_id is not None else None, name, _slug(slug or name, "persona"), description, system_prompt, prompt_file, default_model_deployment_id, now, now, _json(meta_json)))
        row = conn.execute("SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?", (cur.lastrowid,)).fetchone()
    return _row(row) or {}


def update_persona(persona_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema(); allowed={"tenant_id","name","slug","description","system_prompt","prompt_file","system_prompt_artifact_id","default_model_deployment_id","is_enabled","meta_json"}; sets=[]; vals=[]
    for k, v in (patch or {}).items():
        if k not in allowed: continue
        if k == "name": v = _txt(v) or (_ for _ in ()).throw(ValueError("Persona name cannot be empty."))
        if k == "slug": v = _slug(v, "persona")
        if k == "tenant_id": v = int(v) if v not in (None, "") else None
        if k == "is_enabled": v = _bool_int(v)
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
    return {"defaults": defaults, "tenants": list_tenants(), "users": list_users(defaults.get("tenant_id"), include_disabled=True), "all_users": list_users(None, include_disabled=True), "personas": list_personas(defaults.get("tenant_id"), include_disabled=True)}
