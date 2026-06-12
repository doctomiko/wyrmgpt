import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 29

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SQL_DIR = DATA_DIR / "sql"
DB_PATH = SQL_DIR / "wyrmgpt.sqlite3"

_VALID_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()

def _audit_metadata_json(metadata: Any | None) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, str):
        value = metadata.strip()
        return value or None
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)

def _audit_json(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

def ensure_audit_events_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            event_type TEXT NOT NULL,
            actor_principal_type TEXT,
            actor_principal_id TEXT,
            resource_type TEXT,
            resource_id TEXT,
            target_principal_type TEXT,
            target_principal_id TEXT,
            action TEXT,
            decision TEXT,
            reason TEXT,
            summary TEXT,
            before_json TEXT,
            after_json TEXT,
            request_id TEXT,
            source_ip TEXT,
            user_agent TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_created
            ON audit_events(tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_resource
            ON audit_events(resource_type, resource_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_actor
            ON audit_events(actor_principal_type, actor_principal_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
            ON audit_events(event_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_request_id
            ON audit_events(request_id);
        """
    )
    _add_column_if_missing(conn, "audit_events", "target_principal_type", "TEXT")
    _add_column_if_missing(conn, "audit_events", "target_principal_id", "TEXT")
    _add_column_if_missing(conn, "audit_events", "summary", "TEXT")
    _add_column_if_missing(conn, "audit_events", "before_json", "TEXT")
    _add_column_if_missing(conn, "audit_events", "after_json", "TEXT")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_audit_events_target
            ON audit_events(target_principal_type, target_principal_id, created_at)
        """
    )

def log_audit_event(
    *,
    event_type: str,
    tenant_id: str = "default",
    actor_principal_type: str | None = None,
    actor_principal_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    target_principal_type: str | None = None,
    target_principal_id: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
    summary: str | None = None,
    before: Any | None = None,
    after: Any | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    metadata: Any | None = None,
    conn: sqlite3.Connection | None = None,
    raise_on_error: bool = False,
) -> str | None:
    event_type = (event_type or "").strip()
    if not event_type:
        raise ValueError("event_type is required")

    audit_id = new_uuid()
    values = (
        audit_id,
        (tenant_id or "default").strip() or "default",
        event_type,
        (actor_principal_type or "").strip() or None,
        (actor_principal_id or "").strip() or None,
        (resource_type or "").strip() or None,
        (resource_id or "").strip() or None,
        (target_principal_type or "").strip() or None,
        (target_principal_id or "").strip() or None,
        (action or "").strip() or None,
        (decision or "").strip() or None,
        (reason or "").strip() or None,
        (summary or "").strip() or None,
        _audit_json(before),
        _audit_json(after),
        (request_id or "").strip() or None,
        (source_ip or "").strip() or None,
        (user_agent or "").strip() or None,
        _audit_metadata_json(metadata),
        _utc_now_iso(),
    )

    def _insert(target: sqlite3.Connection) -> None:
        target.execute(
            """
            INSERT INTO audit_events (
                id, tenant_id, event_type, actor_principal_type, actor_principal_id,
                resource_type, resource_id, target_principal_type, target_principal_id,
                action, decision, reason, summary, before_json, after_json, request_id,
                source_ip, user_agent, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    try:
        if conn is not None:
            _insert(conn)
        else:
            with db_session() as sconn:
                _insert(sconn)
    except sqlite3.Error:
        if raise_on_error:
            raise
        return None

    return audit_id

def get_audit_event(audit_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    audit_id = (audit_id or "").strip()
    if not audit_id:
        return None

    def _fetch(target: sqlite3.Connection) -> dict | None:
        row = target.execute("SELECT * FROM audit_events WHERE id = ?", (audit_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _fetch(conn)
    with db_session() as sconn:
        return _fetch(sconn)

_OWNED_RESOURCE_TABLES = (
    "projects",
    "conversations",
    "memories",
    "files",
    "artifacts",
    "personas",
    "user_profiles",
)

_MESSAGE_IDENTITY_TABLES = ("messages",)

_OWNED_RESOURCE_ID_COLUMNS = {
    "projects": "id",
    "conversations": "id",
    "memories": "id",
    "files": "id",
    "artifacts": "id",
    "personas": "id",
    "user_profiles": "id",
}


def ensure_identity_resource_tables(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            display_name TEXT NOT NULL,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_profiles (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            user_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            profile_json TEXT,
            about_text TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(tenant_id, user_id)
        );
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO personas (id, tenant_id, display_name, description, created_at, updated_at)
        VALUES ('assistant', 'default', 'Doc Tomiko', 'Default local assistant persona', ?, ?)
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO user_profiles (id, tenant_id, user_id, display_name, profile_json, about_text, created_at, updated_at)
        VALUES ('local', 'default', 'local', 'Doc', NULL, NULL, ?, ?)
        """,
        (now, now),
    )

def ensure_resource_ownership_columns(
    conn: sqlite3.Connection,
    tables: Iterable[str] = _OWNED_RESOURCE_TABLES,
) -> None:
    ensure_identity_resource_tables(conn)
    for table in tables:
        if not table or not _VALID_TABLE.match(table):
            raise ValueError(f"Unsafe table name: {table!r}")
        if not _table_exists(conn, table):
            continue
        _add_column_if_missing(conn, table, "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing(conn, table, "owner_user_id", "TEXT NOT NULL DEFAULT 'local'")
        _add_column_if_missing(conn, table, "created_by_user_id", "TEXT NOT NULL DEFAULT 'local'")
        _add_column_if_missing(conn, table, "updated_by_user_id", "TEXT NOT NULL DEFAULT 'local'")
        _add_column_if_missing(conn, table, "owner_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "owner_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "created_by_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "created_by_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "visibility", "TEXT NOT NULL DEFAULT 'private'")
        _add_column_if_missing(conn, table, "sharing_mode", "TEXT NOT NULL DEFAULT 'owner'")
        _add_column_if_missing(conn, table, "provenance_json", "TEXT")

        conn.execute(
            f"""
            UPDATE {table}
            SET
                owner_user_id = COALESCE(NULLIF(TRIM(owner_user_id), ''), 'local'),
                created_by_user_id = COALESCE(NULLIF(TRIM(created_by_user_id), ''), 'local'),
                updated_by_user_id = COALESCE(NULLIF(TRIM(updated_by_user_id), ''), created_by_user_id, owner_user_id, 'local'),
                owner_principal_type = COALESCE(NULLIF(TRIM(owner_principal_type), ''), 'user'),
                owner_principal_id = COALESCE(NULLIF(TRIM(owner_principal_id), ''), owner_user_id, 'local'),
                created_by_principal_type = COALESCE(NULLIF(TRIM(created_by_principal_type), ''), 'user'),
                created_by_principal_id = COALESCE(NULLIF(TRIM(created_by_principal_id), ''), created_by_user_id, 'local')
            """
        )

        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_owner_user_id ON {table}(owner_user_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_created_by_user_id ON {table}(created_by_user_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_updated_by_user_id ON {table}(updated_by_user_id)"
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_owner_principal
                ON {table}(owner_principal_type, owner_principal_id)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_created_by_principal
                ON {table}(created_by_principal_type, created_by_principal_id)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_source_principal
                ON {table}(source_principal_type, source_principal_id)
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility)"
        )

    ensure_message_identity_columns(conn)


def ensure_message_identity_columns(conn: sqlite3.Connection) -> None:
    for table in _MESSAGE_IDENTITY_TABLES:
        if not _table_exists(conn, table):
            continue
        _add_column_if_missing(conn, table, "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing(conn, table, "created_by_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "created_by_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "visibility", "TEXT NOT NULL DEFAULT 'inherit'")
        _add_column_if_missing(conn, table, "sharing_mode", "TEXT NOT NULL DEFAULT 'inherit'")
        _add_column_if_missing(conn, table, "provenance_json", "TEXT")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id)")
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_source_principal
                ON {table}(source_principal_type, source_principal_id)
            """
        )

def transfer_resource_ownership(
    *,
    resource_type: str,
    resource_id: str,
    owner_user_id: str,
    updated_by_user_id: str = "local",
    tenant_id: str = "default",
    conn: sqlite3.Connection | None = None,
) -> bool:
    table = (resource_type or "").strip()
    if table == "project":
        table = "projects"
    elif table == "conversation":
        table = "conversations"
    elif table == "memory":
        table = "memories"
    elif table == "file":
        table = "files"
    elif table == "artifact":
        table = "artifacts"
    elif table == "persona":
        table = "personas"
    elif table == "user_profile":
        table = "user_profiles"

    if table not in _OWNED_RESOURCE_ID_COLUMNS:
        raise ValueError(f"Unsupported owned resource type: {resource_type}")
    owner_user_id = (owner_user_id or "").strip()
    if not owner_user_id:
        raise ValueError("owner_user_id is required")
    updated_by_user_id = (updated_by_user_id or "local").strip() or "local"
    id_column = _OWNED_RESOURCE_ID_COLUMNS[table]
    now = _utc_now_iso()

    def _transfer(target: sqlite3.Connection) -> bool:
        row = target.execute(
            f"SELECT * FROM {table} WHERE {id_column} = ?",
            (str(resource_id),),
        ).fetchone()
        if row is None and table == "projects":
            row = target.execute(
                f"SELECT * FROM {table} WHERE {id_column} = ?",
                (int(resource_id),),
            ).fetchone()
        if row is None:
            return False
        before = dict(row)
        target.execute(
            f"""
            UPDATE {table}
            SET
                owner_user_id = ?,
                updated_by_user_id = ?,
                owner_principal_type = 'user',
                owner_principal_id = ?,
                updated_at = COALESCE(?, updated_at)
            WHERE {id_column} = ?
            """,
            (owner_user_id, updated_by_user_id, owner_user_id, now, row[id_column]),
        )
        after = target.execute(
            f"SELECT * FROM {table} WHERE {id_column} = ?",
            (row[id_column],),
        ).fetchone()
        ensure_audit_events_schema(target)
        log_audit_event(
            event_type="ownership.transfer",
            tenant_id=tenant_id,
            actor_principal_type="user",
            actor_principal_id=updated_by_user_id,
            resource_type=resource_type,
            resource_id=str(resource_id),
            target_principal_type="user",
            target_principal_id=owner_user_id,
            action="transfer_ownership",
            summary=f"Transferred {resource_type} ownership to {owner_user_id}",
            before=before,
            after=dict(after) if after else None,
            conn=target,
            raise_on_error=True,
        )
        return True

    if conn is not None:
        return _transfer(conn)
    with db_session() as active_conn:
        return _transfer(active_conn)


def ensure_access_control_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS access_control_entries (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            resource_type TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            effect TEXT NOT NULL CHECK(effect IN ('allow', 'deny')),
            action TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'resource',
            inherited_from_type TEXT,
            inherited_from_id TEXT,
            reason TEXT,
            created_by_principal_type TEXT,
            created_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_ace_resource_action
            ON access_control_entries(tenant_id, resource_type, resource_id, action, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_ace_principal_action
            ON access_control_entries(tenant_id, principal_type, principal_id, action, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_ace_effect
            ON access_control_entries(effect, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_ace_inherited_from
            ON access_control_entries(inherited_from_type, inherited_from_id);
        CREATE INDEX IF NOT EXISTS idx_ace_expires_at
            ON access_control_entries(expires_at);
        """
    )

_VALID_ACE_EFFECTS = {"allow", "deny"}
_VALID_ACE_PRINCIPAL_TYPES = {
    "user",
    "group",
    "role",
    "persona",
    "tenant_users",
    "tenant_personas",
    "public",
    "service",
}
_VALID_ACE_ACTIONS = {
    "view",
    "edit",
    "archive",
    "soft_remove",
    "permanent_remove",
    "restore",
    "share",
    "manage",
    "use_in_context",
    # Compatibility aliases used by the first resolver implementation.
    "read",
    "write",
    "delete",
    "admin",
    "audit",
}


def _required_acl_value(name: str, value: str | None) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{name} is required")
    return cleaned


def _validate_ace_principal_type(value: str) -> str:
    principal_type = _required_acl_value("principal_type", value).lower()
    if principal_type not in _VALID_ACE_PRINCIPAL_TYPES:
        raise ValueError(f"principal_type must be one of {sorted(_VALID_ACE_PRINCIPAL_TYPES)}")
    return principal_type


def _validate_ace_action(value: str) -> str:
    action = _required_acl_value("action", value).lower()
    if action not in _VALID_ACE_ACTIONS:
        raise ValueError(f"action must be one of {sorted(_VALID_ACE_ACTIONS)}")
    return action

def create_access_control_entry(
    *,
    resource_type: str,
    resource_id: str,
    principal_type: str,
    principal_id: str,
    effect: str,
    action: str,
    tenant_id: str = "default",
    scope: str = "resource",
    inherited_from_type: str | None = None,
    inherited_from_id: str | None = None,
    reason: str | None = None,
    created_by_principal_type: str | None = None,
    created_by_principal_id: str | None = None,
    expires_at: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    normalized_effect = _required_acl_value("effect", effect).lower()
    if normalized_effect not in _VALID_ACE_EFFECTS:
        raise ValueError("effect must be 'allow' or 'deny'")
    normalized_principal_type = _validate_ace_principal_type(principal_type)
    normalized_action = _validate_ace_action(action)

    ace_id = new_uuid()
    values = (
        ace_id,
        (tenant_id or "default").strip() or "default",
        _required_acl_value("resource_type", resource_type),
        _required_acl_value("resource_id", resource_id),
        normalized_principal_type,
        _required_acl_value("principal_id", principal_id),
        normalized_effect,
        normalized_action,
        (scope or "resource").strip() or "resource",
        (inherited_from_type or "").strip() or None,
        (inherited_from_id or "").strip() or None,
        (reason or "").strip() or None,
        (created_by_principal_type or "").strip() or None,
        (created_by_principal_id or "").strip() or None,
        _utc_now_iso(),
        (expires_at or "").strip() or None,
    )

    def _insert(target: sqlite3.Connection) -> None:
        target.execute(
            """
            INSERT INTO access_control_entries (
                id, tenant_id, resource_type, resource_id, principal_type, principal_id,
                effect, action, scope, inherited_from_type, inherited_from_id, reason,
                created_by_principal_type, created_by_principal_id, created_at, expires_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        row = target.execute("SELECT * FROM access_control_entries WHERE id = ?", (ace_id,)).fetchone()
        ensure_audit_events_schema(target)
        log_audit_event(
            event_type="access_control_entry.create",
            tenant_id=values[1],
            actor_principal_type=values[12],
            actor_principal_id=values[13],
            resource_type=values[2],
            resource_id=values[3],
            target_principal_type=values[4],
            target_principal_id=values[5],
            action=values[7],
            decision=values[6],
            summary=f"Created {values[6]} ACE for {values[4]}:{values[5]}",
            after=dict(row) if row else None,
            conn=target,
            raise_on_error=True,
        )

    if conn is not None:
        _insert(conn)
    else:
        with db_session() as sconn:
            _insert(sconn)
    return ace_id

def remove_access_control_entry(
    ace_id: str,
    *,
    deleted_by_principal_type: str | None = None,
    deleted_by_principal_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> bool:
    ace_id = _required_acl_value("ace_id", ace_id)
    actor_type = (deleted_by_principal_type or "user").strip() or "user"
    actor_id = (deleted_by_principal_id or "local").strip() or "local"

    def _remove(target: sqlite3.Connection) -> bool:
        row = target.execute(
            "SELECT * FROM access_control_entries WHERE id = ?",
            (ace_id,),
        ).fetchone()
        if not row:
            return False
        before = dict(row)
        if int(row["is_deleted"] or 0):
            return True
        target.execute(
            "UPDATE access_control_entries SET is_deleted = 1 WHERE id = ?",
            (ace_id,),
        )
        after = target.execute(
            "SELECT * FROM access_control_entries WHERE id = ?",
            (ace_id,),
        ).fetchone()
        ensure_audit_events_schema(target)
        log_audit_event(
            event_type="access_control_entry.remove",
            tenant_id=row["tenant_id"] or "default",
            actor_principal_type=actor_type,
            actor_principal_id=actor_id,
            resource_type=row["resource_type"],
            resource_id=row["resource_id"],
            target_principal_type=row["principal_type"],
            target_principal_id=row["principal_id"],
            action=row["action"],
            decision=row["effect"],
            summary=f"Removed ACE {ace_id}",
            before=before,
            after=dict(after) if after else None,
            conn=target,
            raise_on_error=True,
        )
        return True

    if conn is not None:
        return _remove(conn)
    with db_session() as active_conn:
        return _remove(active_conn)


def list_access_control_entries(
    *,
    tenant_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    principal_type: str | None = None,
    principal_id: str | None = None,
    action: str | None = None,
    include_deleted: bool = False,
    conn: sqlite3.Connection | None = None,
) -> list[dict]:
    where: list[str] = []
    params: list[Any] = []

    for column, value in (
        ("tenant_id", tenant_id),
        ("resource_type", resource_type),
        ("resource_id", resource_id),
        ("principal_type", principal_type),
        ("principal_id", principal_id),
        ("action", action),
    ):
        cleaned = (value or "").strip()
        if cleaned:
            where.append(f"{column} = ?")
            params.append(cleaned)

    if not include_deleted:
        where.append("is_deleted = 0")

    sql = "SELECT * FROM access_control_entries"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC, id ASC"

    def _fetch(target: sqlite3.Connection) -> list[dict]:
        return [dict(row) for row in target.execute(sql, params).fetchall()]

    if conn is not None:
        return _fetch(conn)
    with db_session() as sconn:
        return _fetch(sconn)

BUILT_IN_ROLE_NAMES = {
    "global_admin",
    "tenant_admin",
    "tenant_member",
    "tenant_viewer",
    "persona_manager",
    "data_steward",
    "auditor",
}

_BUILT_IN_ROLE_PERMISSIONS = {
    "global_admin": ("manage", "share", "view", "edit", "archive", "soft_remove", "permanent_remove", "restore", "use_in_context", "audit"),
    "tenant_admin": ("manage", "share", "view", "edit", "archive", "soft_remove", "restore", "use_in_context", "audit"),
    "tenant_member": ("view", "edit", "use_in_context"),
    "tenant_viewer": ("view",),
    "persona_manager": ("view", "edit", "use_in_context", "manage"),
    "data_steward": ("view", "edit", "archive", "restore", "audit"),
    "auditor": ("view", "audit"),
}


def is_builtin_identity_role(name: str) -> bool:
    return (name or "").strip().lower() in BUILT_IN_ROLE_NAMES


def ensure_identity_group_role_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS identity_groups (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            created_by_principal_type TEXT,
            created_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            UNIQUE(tenant_id, name)
        );

        CREATE TABLE IF NOT EXISTS identity_group_members (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            group_id TEXT NOT NULL,
            member_principal_type TEXT NOT NULL,
            member_principal_id TEXT NOT NULL,
            added_by_principal_type TEXT,
            added_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(group_id) REFERENCES identity_groups(id) ON DELETE CASCADE,
            UNIQUE(tenant_id, group_id, member_principal_type, member_principal_id, is_deleted)
        );

        CREATE TABLE IF NOT EXISTS identity_roles (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            name TEXT NOT NULL,
            display_name TEXT,
            description TEXT,
            created_by_principal_type TEXT,
            created_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            UNIQUE(tenant_id, name)
        );

        CREATE TABLE IF NOT EXISTS identity_role_permissions (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            role_id TEXT NOT NULL,
            permission TEXT NOT NULL,
            effect TEXT NOT NULL DEFAULT 'allow' CHECK(effect IN ('allow', 'deny')),
            resource_type TEXT,
            created_by_principal_type TEXT,
            created_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(role_id) REFERENCES identity_roles(id) ON DELETE CASCADE,
            UNIQUE(tenant_id, role_id, permission, effect, resource_type, is_deleted)
        );

        CREATE TABLE IF NOT EXISTS identity_role_assignments (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            role_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            granted_by_principal_type TEXT,
            granted_by_principal_id TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(role_id) REFERENCES identity_roles(id) ON DELETE CASCADE,
            UNIQUE(tenant_id, role_id, principal_type, principal_id, is_deleted)
        );

        CREATE INDEX IF NOT EXISTS idx_identity_groups_tenant
            ON identity_groups(tenant_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_group_members_group
            ON identity_group_members(tenant_id, group_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_group_members_member
            ON identity_group_members(tenant_id, member_principal_type, member_principal_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_roles_tenant
            ON identity_roles(tenant_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_role_permissions_role
            ON identity_role_permissions(tenant_id, role_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_role_permissions_permission
            ON identity_role_permissions(tenant_id, permission, effect, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_role_assignments_role
            ON identity_role_assignments(tenant_id, role_id, is_deleted);
        CREATE INDEX IF NOT EXISTS idx_identity_role_assignments_principal
            ON identity_role_assignments(tenant_id, principal_type, principal_id, is_deleted);
        """
    )
    seed_builtin_identity_roles(conn)


def _identity_now() -> str:
    return _utc_now_iso()


def _identity_audit(
    conn: sqlite3.Connection,
    *,
    event_type: str,
    tenant_id: str,
    actor_principal_type: str | None,
    actor_principal_id: str | None,
    resource_type: str,
    resource_id: str,
    summary: str,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    ensure_audit_events_schema(conn)
    log_audit_event(
        event_type=event_type,
        tenant_id=tenant_id,
        actor_principal_type=actor_principal_type or "user",
        actor_principal_id=actor_principal_id or "local",
        resource_type=resource_type,
        resource_id=resource_id,
        action="manage_identity",
        summary=summary,
        before=before,
        after=after,
        conn=conn,
        raise_on_error=True,
    )


def seed_builtin_identity_roles(conn: sqlite3.Connection, tenant_id: str = "default") -> None:
    now = _identity_now()
    for name, permissions in _BUILT_IN_ROLE_PERMISSIONS.items():
        role_tenant = "global" if name == "global_admin" else (tenant_id or "default")
        role_id = f"builtin:{role_tenant}:{name}"
        conn.execute(
            """
            INSERT OR IGNORE INTO identity_roles (
                id, tenant_id, name, display_name, description,
                created_by_principal_type, created_by_principal_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'service', 'system', ?, ?)
            """,
            (role_id, role_tenant, name, name.replace("_", " ").title(), "Built-in role", now, now),
        )
        for permission in permissions:
            perm_id = f"builtin:{role_tenant}:{name}:{permission}"
            conn.execute(
                """
                INSERT OR IGNORE INTO identity_role_permissions (
                    id, tenant_id, role_id, permission, effect, resource_type,
                    created_by_principal_type, created_by_principal_id, created_at
                )
                VALUES (?, ?, ?, ?, 'allow', NULL, 'service', 'system', ?)
                """,
                (perm_id, role_tenant, role_id, permission, now),
            )


def create_identity_group(
    *,
    name: str,
    tenant_id: str = "default",
    display_name: str | None = None,
    description: str | None = None,
    created_by_principal_type: str | None = None,
    created_by_principal_id: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> str:
    def _create(target: sqlite3.Connection) -> str:
        ensure_identity_group_role_schema(target)
        group_id = new_uuid()
        now = _identity_now()
        values = (
            group_id, tenant_id or "default", _required_acl_value("name", name).lower(),
            (display_name or name).strip(), (description or "").strip() or None,
            (created_by_principal_type or "user").strip() or "user",
            (created_by_principal_id or "local").strip() or "local", now, now,
        )
        target.execute(
            """
            INSERT INTO identity_groups (
                id, tenant_id, name, display_name, description,
                created_by_principal_type, created_by_principal_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )
        row = target.execute("SELECT * FROM identity_groups WHERE id = ?", (group_id,)).fetchone()
        _identity_audit(target, event_type="identity_group.create", tenant_id=values[1], actor_principal_type=values[5], actor_principal_id=values[6], resource_type="identity_group", resource_id=group_id, summary=f"Created group {values[2]}", after=dict(row) if row else None)
        return group_id
    if conn is not None:
        return _create(conn)
    with db_session() as active_conn:
        return _create(active_conn)


def list_identity_groups(*, tenant_id: str | None = None, include_deleted: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _list(target: sqlite3.Connection) -> list[dict]:
        ensure_identity_group_role_schema(target)
        where = [] if include_deleted else ["is_deleted = 0"]
        params: list[Any] = []
        if tenant_id:
            where.append("tenant_id = ?")
            params.append(tenant_id)
        sql = "SELECT * FROM identity_groups" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY tenant_id, name"
        return [dict(r) for r in target.execute(sql, params).fetchall()]
    if conn is not None:
        return _list(conn)
    with db_session() as active_conn:
        return _list(active_conn)


def update_identity_group(group_id: str, *, display_name: str | None = None, description: str | None = None, is_deleted: bool | None = None, actor_principal_type: str | None = None, actor_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> bool:
    def _update(target: sqlite3.Connection) -> bool:
        before_row = target.execute("SELECT * FROM identity_groups WHERE id = ?", (group_id,)).fetchone()
        if not before_row:
            return False
        before = dict(before_row)
        target.execute(
            """
            UPDATE identity_groups
            SET display_name = COALESCE(?, display_name), description = COALESCE(?, description),
                is_deleted = COALESCE(?, is_deleted), updated_at = ?
            WHERE id = ?
            """,
            (display_name, description, None if is_deleted is None else int(is_deleted), _identity_now(), group_id),
        )
        after = dict(target.execute("SELECT * FROM identity_groups WHERE id = ?", (group_id,)).fetchone())
        _identity_audit(target, event_type="identity_group.update", tenant_id=after["tenant_id"], actor_principal_type=actor_principal_type, actor_principal_id=actor_principal_id, resource_type="identity_group", resource_id=group_id, summary=f"Updated group {after['name']}", before=before, after=after)
        return True
    if conn is not None:
        return _update(conn)
    with db_session() as active_conn:
        return _update(active_conn)


def add_identity_group_member(*, group_id: str, member_principal_type: str, member_principal_id: str, tenant_id: str = "default", added_by_principal_type: str | None = None, added_by_principal_id: str | None = None, expires_at: str | None = None, conn: sqlite3.Connection | None = None) -> str:
    def _add(target: sqlite3.Connection) -> str:
        ensure_identity_group_role_schema(target)
        member_type = _validate_ace_principal_type(member_principal_type)
        member_id = _required_acl_value("member_principal_id", member_principal_id)
        membership_id = new_uuid()
        now = _identity_now()
        target.execute(
            """
            INSERT INTO identity_group_members (
                id, tenant_id, group_id, member_principal_type, member_principal_id,
                added_by_principal_type, added_by_principal_id, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (membership_id, tenant_id or "default", group_id, member_type, member_id, added_by_principal_type or "user", added_by_principal_id or "local", now, expires_at),
        )
        row = target.execute("SELECT * FROM identity_group_members WHERE id = ?", (membership_id,)).fetchone()
        _identity_audit(target, event_type="identity_group_member.add", tenant_id=tenant_id or "default", actor_principal_type=added_by_principal_type, actor_principal_id=added_by_principal_id, resource_type="identity_group", resource_id=group_id, summary=f"Added {member_type}:{member_id} to group", after=dict(row) if row else None)
        return membership_id
    if conn is not None:
        return _add(conn)
    with db_session() as active_conn:
        return _add(active_conn)


def list_identity_group_members(*, group_id: str | None = None, tenant_id: str | None = None, member_principal_type: str | None = None, member_principal_id: str | None = None, include_deleted: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _list(target: sqlite3.Connection) -> list[dict]:
        ensure_identity_group_role_schema(target)
        where = [] if include_deleted else ["is_deleted = 0"]
        params: list[Any] = []
        for col, value in (("tenant_id", tenant_id), ("group_id", group_id), ("member_principal_type", member_principal_type), ("member_principal_id", member_principal_id)):
            if value:
                where.append(f"{col} = ?")
                params.append(value)
        sql = "SELECT * FROM identity_group_members" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at, id"
        return [dict(r) for r in target.execute(sql, params).fetchall()]
    if conn is not None:
        return _list(conn)
    with db_session() as active_conn:
        return _list(active_conn)


def create_identity_role(*, name: str, tenant_id: str = "default", display_name: str | None = None, description: str | None = None, created_by_principal_type: str | None = None, created_by_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> str:
    def _create(target: sqlite3.Connection) -> str:
        ensure_identity_group_role_schema(target)
        role_id = new_uuid()
        now = _identity_now()
        values = (role_id, tenant_id or "default", _required_acl_value("name", name).lower(), (display_name or name).strip(), (description or "").strip() or None, created_by_principal_type or "user", created_by_principal_id or "local", now, now)
        target.execute("""
            INSERT INTO identity_roles (id, tenant_id, name, display_name, description, created_by_principal_type, created_by_principal_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, values)
        row = target.execute("SELECT * FROM identity_roles WHERE id = ?", (role_id,)).fetchone()
        _identity_audit(target, event_type="identity_role.create", tenant_id=values[1], actor_principal_type=values[5], actor_principal_id=values[6], resource_type="identity_role", resource_id=role_id, summary=f"Created role {values[2]}", after=dict(row) if row else None)
        return role_id
    if conn is not None:
        return _create(conn)
    with db_session() as active_conn:
        return _create(active_conn)


def list_identity_roles(*, tenant_id: str | None = None, include_deleted: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _list(target: sqlite3.Connection) -> list[dict]:
        ensure_identity_group_role_schema(target)
        where = [] if include_deleted else ["is_deleted = 0"]
        params: list[Any] = []
        if tenant_id:
            where.append("tenant_id = ?")
            params.append(tenant_id)
        sql = "SELECT * FROM identity_roles" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY tenant_id, name"
        return [dict(r) for r in target.execute(sql, params).fetchall()]
    if conn is not None:
        return _list(conn)
    with db_session() as active_conn:
        return _list(active_conn)


def update_identity_role(role_id: str, *, display_name: str | None = None, description: str | None = None, is_deleted: bool | None = None, actor_principal_type: str | None = None, actor_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> bool:
    def _update(target: sqlite3.Connection) -> bool:
        before_row = target.execute("SELECT * FROM identity_roles WHERE id = ?", (role_id,)).fetchone()
        if not before_row:
            return False
        before = dict(before_row)
        target.execute("""
            UPDATE identity_roles
            SET display_name = COALESCE(?, display_name), description = COALESCE(?, description), is_deleted = COALESCE(?, is_deleted), updated_at = ?
            WHERE id = ?
        """, (display_name, description, None if is_deleted is None else int(is_deleted), _identity_now(), role_id))
        after = dict(target.execute("SELECT * FROM identity_roles WHERE id = ?", (role_id,)).fetchone())
        _identity_audit(target, event_type="identity_role.update", tenant_id=after["tenant_id"], actor_principal_type=actor_principal_type, actor_principal_id=actor_principal_id, resource_type="identity_role", resource_id=role_id, summary=f"Updated role {after['name']}", before=before, after=after)
        return True
    if conn is not None:
        return _update(conn)
    with db_session() as active_conn:
        return _update(active_conn)


def add_identity_role_permission(*, role_id: str, permission: str, tenant_id: str = "default", effect: str = "allow", resource_type: str | None = None, created_by_principal_type: str | None = None, created_by_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> str:
    def _add(target: sqlite3.Connection) -> str:
        ensure_identity_group_role_schema(target)
        perm = _validate_ace_action(permission)
        normalized_effect = _required_acl_value("effect", effect).lower()
        if normalized_effect not in _VALID_ACE_EFFECTS:
            raise ValueError("effect must be 'allow' or 'deny'")
        permission_id = new_uuid()
        now = _identity_now()
        target.execute("""
            INSERT INTO identity_role_permissions (id, tenant_id, role_id, permission, effect, resource_type, created_by_principal_type, created_by_principal_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (permission_id, tenant_id or "default", role_id, perm, normalized_effect, (resource_type or "").strip() or None, created_by_principal_type or "user", created_by_principal_id or "local", now))
        row = target.execute("SELECT * FROM identity_role_permissions WHERE id = ?", (permission_id,)).fetchone()
        _identity_audit(target, event_type="identity_role_permission.add", tenant_id=tenant_id or "default", actor_principal_type=created_by_principal_type, actor_principal_id=created_by_principal_id, resource_type="identity_role", resource_id=role_id, summary=f"Added {normalized_effect} {perm} role permission", after=dict(row) if row else None)
        return permission_id
    if conn is not None:
        return _add(conn)
    with db_session() as active_conn:
        return _add(active_conn)


def list_identity_role_permissions(*, role_id: str | None = None, tenant_id: str | None = None, include_deleted: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _list(target: sqlite3.Connection) -> list[dict]:
        ensure_identity_group_role_schema(target)
        where = [] if include_deleted else ["is_deleted = 0"]
        params: list[Any] = []
        for col, value in (("tenant_id", tenant_id), ("role_id", role_id)):
            if value:
                where.append(f"{col} = ?")
                params.append(value)
        sql = "SELECT * FROM identity_role_permissions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at, id"
        return [dict(r) for r in target.execute(sql, params).fetchall()]
    if conn is not None:
        return _list(conn)
    with db_session() as active_conn:
        return _list(active_conn)


def assign_identity_role(*, role_id: str, principal_type: str, principal_id: str, tenant_id: str = "default", granted_by_principal_type: str | None = None, granted_by_principal_id: str | None = None, expires_at: str | None = None, conn: sqlite3.Connection | None = None) -> str:
    def _assign(target: sqlite3.Connection) -> str:
        ensure_identity_group_role_schema(target)
        normalized_type = _validate_ace_principal_type(principal_type)
        assignment_id = new_uuid()
        now = _identity_now()
        target.execute("""
            INSERT INTO identity_role_assignments (id, tenant_id, role_id, principal_type, principal_id, granted_by_principal_type, granted_by_principal_id, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (assignment_id, tenant_id or "default", role_id, normalized_type, _required_acl_value("principal_id", principal_id), granted_by_principal_type or "user", granted_by_principal_id or "local", now, expires_at))
        row = target.execute("SELECT * FROM identity_role_assignments WHERE id = ?", (assignment_id,)).fetchone()
        _identity_audit(target, event_type="identity_role_assignment.add", tenant_id=tenant_id or "default", actor_principal_type=granted_by_principal_type, actor_principal_id=granted_by_principal_id, resource_type="identity_role", resource_id=role_id, summary=f"Assigned role to {normalized_type}:{principal_id}", after=dict(row) if row else None)
        return assignment_id
    if conn is not None:
        return _assign(conn)
    with db_session() as active_conn:
        return _assign(active_conn)


def list_identity_role_assignments(*, role_id: str | None = None, tenant_id: str | None = None, principal_type: str | None = None, principal_id: str | None = None, include_deleted: bool = False, conn: sqlite3.Connection | None = None) -> list[dict]:
    def _list(target: sqlite3.Connection) -> list[dict]:
        ensure_identity_group_role_schema(target)
        where = [] if include_deleted else ["is_deleted = 0"]
        params: list[Any] = []
        for col, value in (("tenant_id", tenant_id), ("role_id", role_id), ("principal_type", principal_type), ("principal_id", principal_id)):
            if value:
                where.append(f"{col} = ?")
                params.append(value)
        sql = "SELECT * FROM identity_role_assignments" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at, id"
        return [dict(r) for r in target.execute(sql, params).fetchall()]
    if conn is not None:
        return _list(conn)
    with db_session() as active_conn:
        return _list(active_conn)


def update_identity_group_member(membership_id: str, *, expires_at: str | None = None, is_deleted: bool | None = None, actor_principal_type: str | None = None, actor_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> bool:
    def _update(target: sqlite3.Connection) -> bool:
        before_row = target.execute("SELECT * FROM identity_group_members WHERE id = ?", (membership_id,)).fetchone()
        if not before_row:
            return False
        before = dict(before_row)
        target.execute("""
            UPDATE identity_group_members
            SET expires_at = COALESCE(?, expires_at), is_deleted = COALESCE(?, is_deleted)
            WHERE id = ?
        """, (expires_at, None if is_deleted is None else int(is_deleted), membership_id))
        after = dict(target.execute("SELECT * FROM identity_group_members WHERE id = ?", (membership_id,)).fetchone())
        _identity_audit(target, event_type="identity_group_member.update", tenant_id=after["tenant_id"], actor_principal_type=actor_principal_type, actor_principal_id=actor_principal_id, resource_type="identity_group", resource_id=after["group_id"], summary=f"Updated group membership {membership_id}", before=before, after=after)
        return True
    if conn is not None:
        return _update(conn)
    with db_session() as active_conn:
        return _update(active_conn)


def update_identity_role_permission(permission_id: str, *, effect: str | None = None, resource_type: str | None = None, is_deleted: bool | None = None, actor_principal_type: str | None = None, actor_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> bool:
    def _update(target: sqlite3.Connection) -> bool:
        before_row = target.execute("SELECT * FROM identity_role_permissions WHERE id = ?", (permission_id,)).fetchone()
        if not before_row:
            return False
        before = dict(before_row)
        normalized_effect = None
        if effect is not None:
            normalized_effect = _required_acl_value("effect", effect).lower()
            if normalized_effect not in _VALID_ACE_EFFECTS:
                raise ValueError("effect must be 'allow' or 'deny'")
        target.execute("""
            UPDATE identity_role_permissions
            SET effect = COALESCE(?, effect), resource_type = COALESCE(?, resource_type), is_deleted = COALESCE(?, is_deleted)
            WHERE id = ?
        """, (normalized_effect, (resource_type or "").strip() or None, None if is_deleted is None else int(is_deleted), permission_id))
        after = dict(target.execute("SELECT * FROM identity_role_permissions WHERE id = ?", (permission_id,)).fetchone())
        _identity_audit(target, event_type="identity_role_permission.update", tenant_id=after["tenant_id"], actor_principal_type=actor_principal_type, actor_principal_id=actor_principal_id, resource_type="identity_role", resource_id=after["role_id"], summary=f"Updated role permission {permission_id}", before=before, after=after)
        return True
    if conn is not None:
        return _update(conn)
    with db_session() as active_conn:
        return _update(active_conn)


def update_identity_role_assignment(assignment_id: str, *, expires_at: str | None = None, is_deleted: bool | None = None, actor_principal_type: str | None = None, actor_principal_id: str | None = None, conn: sqlite3.Connection | None = None) -> bool:
    def _update(target: sqlite3.Connection) -> bool:
        before_row = target.execute("SELECT * FROM identity_role_assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not before_row:
            return False
        before = dict(before_row)
        target.execute("""
            UPDATE identity_role_assignments
            SET expires_at = COALESCE(?, expires_at), is_deleted = COALESCE(?, is_deleted)
            WHERE id = ?
        """, (expires_at, None if is_deleted is None else int(is_deleted), assignment_id))
        after = dict(target.execute("SELECT * FROM identity_role_assignments WHERE id = ?", (assignment_id,)).fetchone())
        _identity_audit(target, event_type="identity_role_assignment.update", tenant_id=after["tenant_id"], actor_principal_type=actor_principal_type, actor_principal_id=actor_principal_id, resource_type="identity_role", resource_id=after["role_id"], summary=f"Updated role assignment {assignment_id}", before=before, after=after)
        return True
    if conn is not None:
        return _update(conn)
    with db_session() as active_conn:
        return _update(active_conn)


def ensure_parent_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def new_uuid() -> str:
    return str(uuid.uuid4())

def _normalize_tags(tags: Any) -> str | None:
    """
    Store tags as JSON text (recommended), but accept None/str/list.
    """
    if tags is None:
        return None
    if isinstance(tags, str):
        t = tags.strip()
        return t if t else None
    if isinstance(tags, (list, tuple)):
        cleaned = [str(x).strip() for x in tags if str(x).strip()]
        return json.dumps(cleaned) if cleaned else None
    # last resort: stringify
    t = str(tags).strip()
    return t if t else None

@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30.0,   # <- important
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")   # <- wait for locks instead of failing immediately
        conn.execute("PRAGMA journal_mode = WAL;")     # <- better concurrency
        conn.execute("PRAGMA synchronous = NORMAL;")   # <- reasonable for dev
        yield conn
        conn.commit()
    finally:
        conn.close()


# region Migration helpers

def db_debug_info(conn: sqlite3.Connection | None = None) -> dict:
    if conn is None:
        with db_session() as sconn:
            return db_debug_info(sconn)
    else:
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        # conn.close()
        return {
            "db_path": str(DB_PATH),
            "tables": tables,
        }

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None

def _table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    if not _table_exists(conn, table):
        return False
    try:
        row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False

def _db_has_user_data(conn: sqlite3.Connection) -> bool:
    # If any of these have rows, we treat it as “real data exists.”
    for t in ("messages", "conversations", "projects", "memories", "files", "artifacts"):
        if _table_has_rows(conn, t):
            return True
    return False

def _drop_all_tables(conn: sqlite3.Connection) -> None:
    # Drop in dependency order.
    for t in (
        "project_imports",
        "memory_conversations",
        "memory_projects",
        "project_files",
        "project_conversations",
        "artifacts",
        "files",
        "memories",
        "conversation_settings",
        "messages",
        "conversations",
        "projects",
        "memory_pins",
        "schema_meta",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {t}")

def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, coldef: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")

def drop_empty_tables(tables: Iterable[str], conn: sqlite3.Connection | None = None) -> list[str]:
    """
    Drop tables that exist and have 0 rows.
    Returns a list of table names that were dropped.

    NOTE: If you drop a table here, your app must not reference it later
    unless you recreate it in init_schema().
    """
    dropped: list[str] = []
    def _do(conn: sqlite3.Connection) -> list[str]:
        # Be permissive about drops; we’re explicitly choosing to prune.
        conn.execute("PRAGMA foreign_keys = OFF;")
        for t in tables:
            if not t or not _VALID_TABLE.match(t):
                raise ValueError(f"Unsafe table name: {t!r}")
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (t,),
            ).fetchone()
            if not exists:
                continue
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()
            count = int(row["c"]) if row and row["c"] is not None else 0
            if count == 0:
                conn.execute(f"DROP TABLE {t}")
                dropped.append(t)
        conn.execute("PRAGMA foreign_keys = ON;")
        return dropped

    if conn is not None:
        return _do(conn)
    with db_session() as sconn:
        return _do(sconn)

def drop_empty_satellite_tables(conn: sqlite3.Connection | None = None) -> list[str]:
    """
    Your “satellite”/optional tables: join tables + imports.
    Adjust this list to taste.
    """
    return drop_empty_tables(
        [
            #"projects",
            "project_conversations",
            "project_files",
            "memory_projects",
            "memory_conversations",
            "project_imports",
            "conversation_settings",
            "artifacts",
            "files",
        ],
        conn
    )

# endregion

# region Schema Init

def _force_schema_regression_if_table_missing(
    target_version: int,
    required_table: str,
) -> None:
    target = int(target_version)
    table = (required_table or "").strip()
    if target < 0:
        raise ValueError("target_version must be >= 0")
    if not table:
        raise ValueError("required_table is required")

    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

        table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()

        if table_row:
            print(f"Regression skipped: table {table!r} already exists; schema_version={current}")
            return

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(target),),
        )
        print(f"Forced schema regression because {table!r} is missing: {current} -> {target}")

def _force_schema_regression(target_version: int) -> None:
    """
    TEMPORARY REPAIR TOOL.

    Force schema_meta.schema_version backward so init_schema() will re-run
    later migrations. This does NOT drop tables. It only rewinds the version
    marker.

    Comment out/remove call sites when done.
    """
    target = int(target_version)
    if target < 0:
        raise ValueError("target_version must be >= 0")

    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(target),),
        )

        print(f"Forced schema regression: {current} -> {target}")

def _start_schema_init(conn: sqlite3.Connection) -> int:
    """
    Returns the current schema version, or 0 if not set. This also ensures the schema_meta table exists.
    """
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    current = int(row["value"]) if row and str(row["value"]).isdigit() else 0
    return current

_SCHEMA_INIT_LOGGED = False

def _end_schema_init(conn: sqlite3.Connection, original: int, current: int = SCHEMA_VERSION) -> None:
    global _SCHEMA_INIT_LOGGED
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(current),),
    )

    if not _SCHEMA_INIT_LOGGED or original != current:
        print(f"DB initialized with schema version {current} (was {original})")
        _SCHEMA_INIT_LOGGED = True
        # TODO implement seperate log file and log there as well.
        #log.logger.info(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")

# endregion