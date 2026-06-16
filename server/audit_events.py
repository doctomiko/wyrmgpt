# server/audit_events.py
"""Append-only audit/event helpers.

This module provides the first reusable audit layer for identity, ownership,
sharing, and policy work. It intentionally avoids route-specific assumptions:
callers supply the actor, resource, target, and before/after payloads they know.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db_helpers import _utc_now_iso, db_session, new_uuid
from .logging_helper import log_warn


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uuid TEXT NOT NULL UNIQUE,
    tenant_id INTEGER,
    actor_user_id INTEGER,
    actor_persona_id INTEGER,
    event_type TEXT NOT NULL,
    resource_kind TEXT,
    resource_id TEXT,
    target_user_id INTEGER,
    target_persona_id INTEGER,
    summary TEXT,
    before_json TEXT,
    after_json TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL
)
"""

_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_created ON audit_events(tenant_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_resource ON audit_events(resource_kind, resource_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_actor_user ON audit_events(actor_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_events_event_type ON audit_events(event_type, created_at)",
)


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def ensure_audit_events_schema(conn: sqlite3.Connection | None = None) -> None:
    """Create the audit_events table and indexes if they do not already exist."""
    if conn is not None:
        conn.execute(_SCHEMA_SQL)
        for sql in _INDEX_SQL:
            conn.execute(sql)
        return
    with db_session() as sconn:
        ensure_audit_events_schema(sconn)


def record_audit_event(
    *,
    event_type: str,
    tenant_id: int | None = None,
    actor_user_id: int | None = None,
    actor_persona_id: int | None = None,
    resource_kind: str | None = None,
    resource_id: str | int | None = None,
    target_user_id: int | None = None,
    target_persona_id: int | None = None,
    summary: str | None = None,
    before: Any = None,
    after: Any = None,
    metadata: Any = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Append one audit event and return the inserted event row as a dict."""
    event_type = str(event_type or "").strip()
    if not event_type:
        raise ValueError("event_type is required")

    event_uuid = new_uuid()
    created_at = _utc_now_iso()
    params = {
        "event_uuid": event_uuid,
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "actor_persona_id": actor_persona_id,
        "event_type": event_type,
        "resource_kind": str(resource_kind).strip() if resource_kind is not None else None,
        "resource_id": str(resource_id).strip() if resource_id is not None else None,
        "target_user_id": target_user_id,
        "target_persona_id": target_persona_id,
        "summary": str(summary).strip() if summary else None,
        "before_json": _json_text(before),
        "after_json": _json_text(after),
        "metadata_json": _json_text(metadata),
        "created_at": created_at,
    }

    def _insert(active_conn: sqlite3.Connection) -> dict[str, Any]:
        ensure_audit_events_schema(active_conn)
        cur = active_conn.execute(
            """
            INSERT INTO audit_events(
                event_uuid, tenant_id, actor_user_id, actor_persona_id,
                event_type, resource_kind, resource_id,
                target_user_id, target_persona_id, summary,
                before_json, after_json, metadata_json, created_at
            ) VALUES (
                :event_uuid, :tenant_id, :actor_user_id, :actor_persona_id,
                :event_type, :resource_kind, :resource_id,
                :target_user_id, :target_persona_id, :summary,
                :before_json, :after_json, :metadata_json, :created_at
            )
            """,
            params,
        )
        return {"id": int(cur.lastrowid), **params}

    if conn is not None:
        return _insert(conn)
    with db_session() as sconn:
        return _insert(sconn)


def safe_record_audit_event(**kwargs: Any) -> dict[str, Any] | None:
    """Best-effort audit write for callers that must not fail the main action."""
    try:
        return record_audit_event(**kwargs)
    except Exception as exc:
        log_warn(f"Audit event write failed: {exc}")
        return None


def list_audit_events(
    *,
    tenant_id: int | None = None,
    resource_kind: str | None = None,
    resource_id: str | int | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent audit events for diagnostics and smoke checks."""
    ensure_audit_events_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        clauses.append("tenant_id=?")
        params.append(int(tenant_id))
    if resource_kind:
        clauses.append("resource_kind=?")
        params.append(str(resource_kind).strip())
    if resource_id is not None:
        clauses.append("resource_id=?")
        params.append(str(resource_id).strip())
    if event_type:
        clauses.append("event_type=?")
        params.append(str(event_type).strip())
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM audit_events {where} ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, min(int(limit or 100), 500)))
    with db_session() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(row) for row in rows]
