# server/identity_delete.py
"""Reference checks and safe hard-delete helpers for identity rows."""

from __future__ import annotations

import json
from typing import Any

from .db_helpers import db_session


_REFERENCE_MAP: dict[str, list[tuple[str, str]]] = {
    "tenant": [
        ("users", "tenant_id"),
        ("tenant_users", "tenant_id"),
        ("user_profiles", "tenant_id"),
        ("chat_personas", "tenant_id"),
        ("conversations", "tenant_id"),
        ("messages", "tenant_id"),
    ],
    "user": [
        ("tenant_users", "user_id"),
        ("user_profiles", "user_id"),
        ("chat_personas", "owner_user_id"),
        ("conversations", "active_user_id"),
        ("messages", "user_id"),
    ],
    "persona": [
        ("conversations", "default_persona_id"),
        ("messages", "persona_id"),
    ],
}

_TABLES = {
    "tenant": "tenants",
    "user": "users",
    "persona": "chat_personas",
}

_PROTECTED_SLUGS = {"@global-admin", "global-admin"}


def _table_exists(conn, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _column_exists(conn, table: str, column: str) -> bool:
    if not _table_exists(conn, table):
        return False
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r["name"]) == column for r in rows)


def _count_refs(conn, table: str, column: str, row_id: int) -> int:
    if not _column_exists(conn, table, column):
        return 0
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=?", (int(row_id),)).fetchone()
    return int(row["n"] or 0) if row else 0


def _exec_if_column(conn, table: str, column: str, sql: str, params: tuple[Any, ...]) -> int:
    if not _column_exists(conn, table, column):
        return 0
    cur = conn.execute(sql, params)
    return int(cur.rowcount or 0)


def _delete_if_column(conn, table: str, column: str, row_id: int) -> int:
    if not _column_exists(conn, table, column):
        return 0
    cur = conn.execute(f"DELETE FROM {table} WHERE {column}=?", (int(row_id),))
    return int(cur.rowcount or 0)


def _json_dict(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _force_action_for_reference(entity_type: str, table: str, column: str) -> str:
    if entity_type == "user":
        if (table, column) in {("tenant_users", "user_id"), ("user_profiles", "user_id")}:
            return "cascade_delete"
        return "assign_global_admin"
    if entity_type == "tenant":
        if table == "tenant_users":
            return "cascade_delete"
        return "clear_tenant_scope"
    if entity_type == "persona":
        return "assign_fallback_persona"
    return "unknown"


def _is_protected_identity(conn, entity_type: str, row_id: int) -> bool:
    table = _TABLES.get(entity_type)
    if not table or not _table_exists(conn, table):
        return False
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (int(row_id),)).fetchone()
    if not row:
        return False
    meta = _json_dict(row["meta_json"] if "meta_json" in row.keys() else None)
    if meta.get("protected") or meta.get("system_default"):
        return True
    slug = str(row["slug"] if "slug" in row.keys() else "").strip().lower()
    if entity_type in {"user", "persona"} and slug in _PROTECTED_SLUGS:
        return True
    return False


def _global_admin_user_id(conn) -> int:
    row = conn.execute(
        """
        SELECT id FROM users
        WHERE is_enabled=1 AND is_global_admin=1
        ORDER BY CASE WHEN slug='@global-admin' THEN 0 WHEN slug='global-admin' THEN 1 ELSE 2 END, id
        LIMIT 1
        """
    ).fetchone()
    if not row:
        raise ValueError("No enabled global admin user exists to receive reassigned references.")
    return int(row["id"])


def _default_persona_id(conn, deleted_persona_id: int) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM chat_personas
        WHERE id<>? AND is_enabled=1
        ORDER BY CASE WHEN slug='callie' THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (int(deleted_persona_id),),
    ).fetchone()
    return int(row["id"]) if row else None


def identity_reference_report(entity_type: str, row_id: int) -> dict[str, Any]:
    entity_type = str(entity_type or "").strip().lower()
    if entity_type not in _REFERENCE_MAP:
        raise ValueError(f"Unsupported identity entity type: {entity_type}")

    details: list[dict[str, Any]] = []
    total = 0
    protected = False
    with db_session() as conn:
        protected = _is_protected_identity(conn, entity_type, int(row_id))
        for table, column in _REFERENCE_MAP[entity_type]:
            count = _count_refs(conn, table, column, int(row_id))
            if count:
                details.append({
                    "table": table,
                    "column": column,
                    "count": count,
                    "force_action": _force_action_for_reference(entity_type, table, column),
                })
                total += count
    return {
        "entity_type": entity_type,
        "id": int(row_id),
        "reference_count": total,
        "reference_details": details,
        "protected": protected,
        "can_delete": total == 0 and not protected,
        "can_force_delete": total > 0 and not protected,
    }


def annotate_delete_flags(entity_type: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        item = dict(row)
        try:
            report = identity_reference_report(entity_type, int(item.get("id")))
            item.update({
                "can_delete": bool(report["can_delete"]),
                "can_force_delete": bool(report.get("can_force_delete")),
                "reference_count": int(report["reference_count"]),
                "reference_details": report["reference_details"],
                "protected": bool(report.get("protected")),
            })
        except Exception:
            item.update({"can_delete": False, "can_force_delete": False, "reference_count": None, "reference_details": [], "protected": False})
        out.append(item)
    return out


def hard_delete_identity(entity_type: str, row_id: int) -> dict[str, Any]:
    entity_type = str(entity_type or "").strip().lower()
    table = _TABLES.get(entity_type)
    if not table:
        raise ValueError(f"Unsupported identity entity type: {entity_type}")

    report = identity_reference_report(entity_type, int(row_id))
    if report.get("protected"):
        raise ValueError(f"Cannot delete protected {entity_type} {row_id}.")
    if not report["can_delete"]:
        raise ValueError(f"Cannot delete {entity_type} {row_id}; it is still referenced by other tables.")

    with db_session() as conn:
        cur = conn.execute(f"DELETE FROM {table} WHERE id=?", (int(row_id),))
        deleted = int(cur.rowcount or 0)
    return {**report, "deleted": deleted}


def force_delete_identity(entity_type: str, row_id: int) -> dict[str, Any]:
    entity_type = str(entity_type or "").strip().lower()
    table = _TABLES.get(entity_type)
    if not table:
        raise ValueError(f"Unsupported identity entity type: {entity_type}")

    before = identity_reference_report(entity_type, int(row_id))
    if before.get("protected"):
        raise ValueError(f"Cannot force-delete protected {entity_type} {row_id}.")

    reassignments: list[dict[str, Any]] = []
    with db_session() as conn:
        if entity_type == "user":
            fallback_user_id = _global_admin_user_id(conn)
            if int(fallback_user_id) == int(row_id):
                raise ValueError("Cannot force-delete the fallback global admin user.")
            reassignments.append({"target": "global_admin_user", "id": fallback_user_id})
            if _table_exists(conn, "tenant_users"):
                cur = conn.execute("DELETE FROM tenant_users WHERE user_id=?", (int(row_id),))
                reassignments.append({"table": "tenant_users", "column": "user_id", "action": "cascade_delete", "count": int(cur.rowcount or 0)})
            count = _delete_if_column(conn, "user_profiles", "user_id", int(row_id))
            reassignments.append({"table": "user_profiles", "column": "user_id", "action": "cascade_delete", "count": count})
            for table, column in (("chat_personas", "owner_user_id"), ("conversations", "active_user_id"), ("messages", "user_id")):
                count = _exec_if_column(conn, table, column, f"UPDATE {table} SET {column}=? WHERE {column}=?", (fallback_user_id, int(row_id)))
                reassignments.append({"table": table, "column": column, "action": "assign_global_admin", "count": count})
        elif entity_type == "persona":
            fallback_persona_id = _default_persona_id(conn, int(row_id))
            if fallback_persona_id is None:
                raise ValueError("No fallback persona exists to receive reassigned persona references.")
            reassignments.append({"target": "fallback_persona", "id": fallback_persona_id})
            for table, column in (("conversations", "default_persona_id"), ("messages", "persona_id")):
                count = _exec_if_column(conn, table, column, f"UPDATE {table} SET {column}=? WHERE {column}=?", (fallback_persona_id, int(row_id)))
                reassignments.append({"table": table, "column": column, "action": "assign_fallback_persona", "count": count})
        elif entity_type == "tenant":
            for table, column in (("users", "tenant_id"), ("user_profiles", "tenant_id"), ("chat_personas", "tenant_id"), ("conversations", "tenant_id"), ("messages", "tenant_id")):
                count = _exec_if_column(conn, table, column, f"UPDATE {table} SET {column}=NULL WHERE {column}=?", (int(row_id),))
                reassignments.append({"table": table, "column": column, "action": "clear_tenant_scope", "count": count})
            if _table_exists(conn, "tenant_users"):
                cur = conn.execute("DELETE FROM tenant_users WHERE tenant_id=?", (int(row_id),))
                reassignments.append({"table": "tenant_users", "column": "tenant_id", "action": "cascade_delete", "count": int(cur.rowcount or 0)})
        cur = conn.execute(f"DELETE FROM {table} WHERE id=?", (int(row_id),))
        deleted = int(cur.rowcount or 0)

    after = identity_reference_report(entity_type, int(row_id))
    return {**before, "deleted": deleted, "forced": True, "reassignments": reassignments, "after": after}
