# server/identity_db.py
"""Identity helpers for tenants, users, and chat personas.

First-pass design goals:
- Keep tenant/user/persona storage separate from retrieval/corpus work.
- Seed safe local defaults so the UI can always select something.
- Stamp chat messages with active identity without forcing large chat-route surgery.
"""

from __future__ import annotations

import contextvars
import json
import re
import sqlite3
from typing import Any

from .db_helpers import db_session, new_uuid, _utc_now_iso, _add_column_if_missing, _table_exists


_ACTIVE_IDENTITY: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "wyrmgpt_active_identity",
    default=None,
)

_PATCH_INSTALLED = False


_SLUG_RE = re.compile(r"[^a-z0-9._-]+")


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text if text else default


def _clean_slug(value: Any, default: str = "persona") -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        raw = default
    raw = _SLUG_RE.sub("-", raw).strip("-._")
    return raw or default


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            json.loads(stripped)
            return stripped
        except Exception:
            return json.dumps({"value": stripped}, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def ensure_identity_schema() -> None:
    """Create identity tables and additive message/conversation columns."""
    with db_session() as conn:
        conn.executescript(
            """
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
                PRIMARY KEY (tenant_id, user_id),
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
                meta_json TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
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
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                UNIQUE(tenant_id, slug)
            );

            CREATE INDEX IF NOT EXISTS idx_tenant_users_user ON tenant_users(user_id);
            CREATE INDEX IF NOT EXISTS idx_chat_personas_tenant ON chat_personas(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_user_profiles_user ON user_profiles(user_id);
            """
        )

        # Additive first-pass identity columns. We intentionally keep these nullable.
        _add_column_if_missing(conn, "conversations", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "active_user_id", "INTEGER")
        _add_column_if_missing(conn, "conversations", "default_persona_id", "INTEGER")

        _add_column_if_missing(conn, "messages", "tenant_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "user_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "persona_id", "INTEGER")
        _add_column_if_missing(conn, "messages", "identity_json", "TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_identity_tenant ON messages(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_identity_user ON messages(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_identity_persona ON messages(persona_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_identity_tenant ON conversations(tenant_id)")

        _seed_defaults(conn)


def _seed_defaults(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()

    tenant = conn.execute(
        "SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1"
    ).fetchone()
    if tenant is None:
        conn.execute(
            """
            INSERT INTO tenants(uuid, name, kind, source_system, external_id, created_at, updated_at)
            VALUES (?, 'Local', 'local', 'wyrmgpt', 'local', ?, ?)
            """,
            (new_uuid(), now, now),
        )
        tenant = conn.execute(
            "SELECT id FROM tenants WHERE source_system='wyrmgpt' AND external_id='local' LIMIT 1"
        ).fetchone()
    tenant_id = int(tenant["id"])

    user = conn.execute(
        "SELECT id FROM users WHERE handle='local-user' LIMIT 1"
    ).fetchone()
    if user is None:
        conn.execute(
            """
            INSERT INTO users(uuid, display_name, handle, created_at, updated_at)
            VALUES (?, 'Local User', 'local-user', ?, ?)
            """,
            (new_uuid(), now, now),
        )
        user = conn.execute("SELECT id FROM users WHERE handle='local-user' LIMIT 1").fetchone()
    user_id = int(user["id"])

    conn.execute(
        """
        INSERT OR IGNORE INTO tenant_users(tenant_id, user_id, role, created_at, updated_at)
        VALUES (?, ?, 'owner', ?, ?)
        """,
        (tenant_id, user_id, now, now),
    )

    persona = conn.execute(
        "SELECT id FROM chat_personas WHERE tenant_id=? AND slug='callie' LIMIT 1",
        (tenant_id,),
    ).fetchone()
    if persona is None:
        conn.execute(
            """
            INSERT INTO chat_personas(
                uuid, tenant_id, name, slug, description,
                system_prompt, created_at, updated_at
            )
            VALUES (?, ?, 'Callie', 'callie', 'Default WyrmGPT assistant persona.', NULL, ?, ?)
            """,
            (new_uuid(), tenant_id, now, now),
        )


def set_active_identity(identity: dict[str, Any] | None) -> contextvars.Token:
    normalized = normalize_identity_payload(identity or {})
    return _ACTIVE_IDENTITY.set(normalized)


def reset_active_identity(token: contextvars.Token) -> None:
    _ACTIVE_IDENTITY.reset(token)


def get_active_identity() -> dict[str, Any] | None:
    return _ACTIVE_IDENTITY.get()


def normalize_identity_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema()
    defaults = get_identity_defaults()

    def _int_or_default(value: Any, default: int | None) -> int | None:
        if value is None or value == "":
            return default
        try:
            return int(value)
        except Exception:
            return default

    tenant_id = _int_or_default(payload.get("tenant_id"), defaults.get("tenant_id"))
    user_id = _int_or_default(payload.get("user_id"), defaults.get("user_id"))
    persona_id = _int_or_default(payload.get("persona_id"), defaults.get("persona_id"))

    persona_slug = _clean_text(payload.get("persona_slug"), "")
    if persona_slug and not persona_id:
        found = get_persona_by_slug(persona_slug, tenant_id=tenant_id)
        if found:
            persona_id = int(found["id"])

    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "persona_id": persona_id,
        "persona_slug": persona_slug or None,
    }


def get_identity_defaults() -> dict[str, Any]:
    ensure_identity_schema()
    with db_session() as conn:
        tenant = conn.execute(
            "SELECT id FROM tenants WHERE is_enabled=1 ORDER BY CASE WHEN source_system='wyrmgpt' AND external_id='local' THEN 0 ELSE 1 END, id LIMIT 1"
        ).fetchone()
        tenant_id = int(tenant["id"]) if tenant else None
        user = conn.execute(
            """
            SELECT u.id
            FROM users u
            LEFT JOIN tenant_users tu ON tu.user_id = u.id
            WHERE u.is_enabled=1 AND (? IS NULL OR tu.tenant_id = ?)
            ORDER BY CASE WHEN u.handle='local-user' THEN 0 ELSE 1 END, u.id
            LIMIT 1
            """,
            (tenant_id, tenant_id),
        ).fetchone()
        user_id = int(user["id"]) if user else None
        persona = conn.execute(
            """
            SELECT id
            FROM chat_personas
            WHERE is_enabled=1 AND (? IS NULL OR tenant_id IS NULL OR tenant_id = ?)
            ORDER BY CASE WHEN slug='callie' THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (tenant_id, tenant_id),
        ).fetchone()
        persona_id = int(persona["id"]) if persona else None
    return {"tenant_id": tenant_id, "user_id": user_id, "persona_id": persona_id}


def list_tenants() -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM tenants ORDER BY is_enabled DESC, name COLLATE NOCASE, id"
        ).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]


def create_tenant(name: str, kind: str = "local", source_system: str | None = None, external_id: str | None = None, meta_json: Any = None) -> dict[str, Any]:
    ensure_identity_schema()
    name = _clean_text(name)
    if not name:
        raise ValueError("Tenant name is required.")
    kind = _clean_slug(kind, "local")
    now = _utc_now_iso()
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO tenants(uuid, name, kind, source_system, external_id, created_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_uuid(), name, kind, source_system, external_id, now, now, _json_or_none(meta_json)),
        )
        tenant_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (tenant_id,)).fetchone()
    return _row_to_dict(row) or {}


def update_tenant(tenant_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema()
    allowed = {"name", "kind", "source_system", "external_id", "is_enabled", "meta_json"}
    sets: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in patch:
            continue
        value = patch[key]
        if key == "name":
            value = _clean_text(value)
            if not value:
                raise ValueError("Tenant name cannot be empty.")
        elif key == "kind":
            value = _clean_slug(value, "local")
        elif key == "is_enabled":
            value = 1 if value else 0
        elif key == "meta_json":
            value = _json_or_none(value)
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return get_tenant(tenant_id) or {}
    sets.append("updated_at=?")
    params.append(_utc_now_iso())
    params.append(int(tenant_id))
    with db_session() as conn:
        conn.execute(f"UPDATE tenants SET {', '.join(sets)} WHERE id=?", tuple(params))
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (int(tenant_id),)).fetchone()
    return _row_to_dict(row) or {}


def get_tenant(tenant_id: int) -> dict[str, Any] | None:
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM tenants WHERE id=?", (int(tenant_id),)).fetchone()
    return _row_to_dict(row)


def list_users(tenant_id: int | None = None) -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        if tenant_id is None:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY is_enabled DESC, display_name COLLATE NOCASE, id"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT u.*, tu.tenant_id, tu.role AS tenant_role
                FROM users u
                JOIN tenant_users tu ON tu.user_id = u.id
                WHERE tu.tenant_id = ?
                ORDER BY u.is_enabled DESC, u.display_name COLLATE NOCASE, u.id
                """,
                (int(tenant_id),),
            ).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]


def create_user(display_name: str, handle: str | None = None, tenant_id: int | None = None, role: str = "member", meta_json: Any = None) -> dict[str, Any]:
    ensure_identity_schema()
    display_name = _clean_text(display_name)
    if not display_name:
        raise ValueError("User display name is required.")
    handle = _clean_slug(handle or display_name, "user")
    now = _utc_now_iso()
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO users(uuid, display_name, handle, created_at, updated_at, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_uuid(), display_name, handle, now, now, _json_or_none(meta_json)),
        )
        user_id = int(cur.lastrowid)
        if tenant_id is not None:
            conn.execute(
                """
                INSERT OR IGNORE INTO tenant_users(tenant_id, user_id, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(tenant_id), user_id, _clean_slug(role, "member"), now, now),
            )
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _row_to_dict(row) or {}


def update_user(user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema()
    allowed = {"display_name", "handle", "is_enabled", "meta_json"}
    sets: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in patch:
            continue
        value = patch[key]
        if key == "display_name":
            value = _clean_text(value)
            if not value:
                raise ValueError("User display name cannot be empty.")
        elif key == "handle":
            value = _clean_slug(value, "user")
        elif key == "is_enabled":
            value = 1 if value else 0
        elif key == "meta_json":
            value = _json_or_none(value)
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return get_user(user_id) or {}
    sets.append("updated_at=?")
    params.append(_utc_now_iso())
    params.append(int(user_id))
    with db_session() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", tuple(params))
        row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    return _row_to_dict(row) or {}


def get_user(user_id: int) -> dict[str, Any] | None:
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (int(user_id),)).fetchone()
    return _row_to_dict(row)


def add_user_to_tenant(user_id: int, tenant_id: int, role: str = "member") -> None:
    ensure_identity_schema()
    now = _utc_now_iso()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO tenant_users(tenant_id, user_id, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, user_id) DO UPDATE SET role=excluded.role, updated_at=excluded.updated_at
            """,
            (int(tenant_id), int(user_id), _clean_slug(role, "member"), now, now),
        )


def list_personas(tenant_id: int | None = None, include_disabled: bool = False) -> list[dict[str, Any]]:
    ensure_identity_schema()
    with db_session() as conn:
        where = [] if include_disabled else ["p.is_enabled=1"]
        params: list[Any] = []
        if tenant_id is not None:
            where.append("(p.tenant_id IS NULL OR p.tenant_id = ?)")
            params.append(int(tenant_id))
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = conn.execute(
            f"""
            SELECT p.*, t.name AS tenant_name
            FROM chat_personas p
            LEFT JOIN tenants t ON t.id = p.tenant_id
            {where_sql}
            ORDER BY p.is_enabled DESC, COALESCE(t.name, 'Global') COLLATE NOCASE, p.name COLLATE NOCASE, p.id
            """,
            tuple(params),
        ).fetchall()
    return [_row_to_dict(r) for r in rows if r is not None]


def get_persona(persona_id: int) -> dict[str, Any] | None:
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute(
            "SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?",
            (int(persona_id),),
        ).fetchone()
    return _row_to_dict(row)


def get_persona_by_slug(slug: str, tenant_id: int | None = None) -> dict[str, Any] | None:
    ensure_identity_schema()
    slug = _clean_slug(slug, "")
    if not slug:
        return None
    with db_session() as conn:
        if tenant_id is None:
            row = conn.execute(
                "SELECT * FROM chat_personas WHERE slug=? AND is_enabled=1 ORDER BY tenant_id IS NOT NULL, id LIMIT 1",
                (slug,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM chat_personas
                WHERE slug=? AND is_enabled=1 AND (tenant_id IS NULL OR tenant_id=?)
                ORDER BY CASE WHEN tenant_id=? THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (slug, int(tenant_id), int(tenant_id)),
            ).fetchone()
    return _row_to_dict(row)


def create_persona(
    name: str,
    slug: str | None = None,
    tenant_id: int | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    default_model_deployment_id: str | None = None,
    meta_json: Any = None,
) -> dict[str, Any]:
    ensure_identity_schema()
    name = _clean_text(name)
    if not name:
        raise ValueError("Persona name is required.")
    slug = _clean_slug(slug or name, "persona")
    now = _utc_now_iso()
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO chat_personas(
                uuid, tenant_id, name, slug, description, system_prompt,
                default_model_deployment_id, created_at, updated_at, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_uuid(),
                int(tenant_id) if tenant_id is not None else None,
                name,
                slug,
                description,
                system_prompt,
                default_model_deployment_id,
                now,
                now,
                _json_or_none(meta_json),
            ),
        )
        persona_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?",
            (persona_id,),
        ).fetchone()
    return _row_to_dict(row) or {}


def update_persona(persona_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    ensure_identity_schema()
    allowed = {
        "tenant_id", "name", "slug", "description", "system_prompt", "system_prompt_artifact_id",
        "default_model_deployment_id", "is_enabled", "meta_json",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key in allowed:
        if key not in patch:
            continue
        value = patch[key]
        if key == "name":
            value = _clean_text(value)
            if not value:
                raise ValueError("Persona name cannot be empty.")
        elif key == "slug":
            value = _clean_slug(value, "persona")
        elif key == "tenant_id":
            value = int(value) if value not in (None, "") else None
        elif key == "is_enabled":
            value = 1 if value else 0
        elif key == "meta_json":
            value = _json_or_none(value)
        sets.append(f"{key}=?")
        params.append(value)
    if not sets:
        return get_persona(persona_id) or {}
    sets.append("updated_at=?")
    params.append(_utc_now_iso())
    params.append(int(persona_id))
    with db_session() as conn:
        conn.execute(f"UPDATE chat_personas SET {', '.join(sets)} WHERE id=?", tuple(params))
        row = conn.execute(
            "SELECT p.*, t.name AS tenant_name FROM chat_personas p LEFT JOIN tenants t ON t.id=p.tenant_id WHERE p.id=?",
            (int(persona_id),),
        ).fetchone()
    return _row_to_dict(row) or {}


def get_conversation_identity(conversation_id: str) -> dict[str, Any] | None:
    ensure_identity_schema()
    with db_session() as conn:
        row = conn.execute(
            "SELECT tenant_id, active_user_id AS user_id, default_persona_id AS persona_id FROM conversations WHERE id=?",
            (conversation_id,),
        ).fetchone()
    if not row:
        return None
    result = _row_to_dict(row) or {}
    if not any(result.values()):
        return None
    return result


def stamp_message_identity(message_id: int, conversation_id: str, role: str, identity: dict[str, Any]) -> None:
    ensure_identity_schema()
    if not message_id:
        return
    tenant_id = identity.get("tenant_id")
    user_id = identity.get("user_id")
    persona_id = identity.get("persona_id")
    identity_json = json.dumps(identity, ensure_ascii=False, sort_keys=True)
    now = _utc_now_iso()
    with db_session() as conn:
        conn.execute(
            """
            UPDATE messages
            SET tenant_id=?, user_id=?, persona_id=?, identity_json=?
            WHERE id=?
            """,
            (tenant_id, user_id if role == "user" else None, persona_id, identity_json, int(message_id)),
        )
        conn.execute(
            """
            UPDATE conversations
            SET
              tenant_id = COALESCE(tenant_id, ?),
              active_user_id = COALESCE(active_user_id, ?),
              default_persona_id = COALESCE(default_persona_id, ?),
              updated_at = ?
            WHERE id=?
            """,
            (tenant_id, user_id, persona_id, now, conversation_id),
        )


def install_identity_message_patch() -> None:
    """Patch server.db.db_add_message before route modules import it.

    This keeps the first pass small: chat routes do not need to understand identity yet,
    but messages still get metadata/columns when requests include tenant/user/persona.
    """
    global _PATCH_INSTALLED
    if _PATCH_INSTALLED:
        return

    import server.db as db_mod

    original = db_mod.db_add_message
    if getattr(original, "_identity_wrapped", False):
        _PATCH_INSTALLED = True
        return

    def wrapped_db_add_message(
        conversation_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
        author_meta: dict | None = None,
    ) -> int:
        active = get_active_identity()
        if not active:
            active = get_conversation_identity(conversation_id)
        if not active:
            active = get_identity_defaults()

        meta_obj = dict(meta or {})
        author_obj = dict(author_meta or {})
        if active:
            identity_public = {
                "tenant_id": active.get("tenant_id"),
                "user_id": active.get("user_id"),
                "persona_id": active.get("persona_id"),
                "persona_slug": active.get("persona_slug"),
            }
            meta_obj.setdefault("identity", identity_public)
            if role == "user":
                author_obj.setdefault("identity", identity_public)
            elif role == "assistant":
                meta_obj.setdefault("responder_persona_id", active.get("persona_id"))

        message_id = original(conversation_id, role, content, meta=meta_obj or None, author_meta=author_obj or None)
        try:
            if active:
                stamp_message_identity(message_id, conversation_id, role, active)
        except Exception:
            # Identity stamping must never break chat persistence.
            pass
        return message_id

    wrapped_db_add_message._identity_wrapped = True  # type: ignore[attr-defined]
    db_mod.db_add_message = wrapped_db_add_message
    _PATCH_INSTALLED = True


def bootstrap_identity() -> dict[str, Any]:
    ensure_identity_schema()
    defaults = get_identity_defaults()
    return {
        "defaults": defaults,
        "tenants": list_tenants(),
        "users": list_users(defaults.get("tenant_id")),
        "all_users": list_users(),
        "personas": list_personas(defaults.get("tenant_id"), include_disabled=True),
    }
