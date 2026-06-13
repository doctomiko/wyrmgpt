#!/usr/bin/env python3
"""Bulk repair ownership, sharing, provenance, and persona access metadata."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db_helpers import (  # noqa: E402
    DB_PATH,
    create_access_control_entry,
    ensure_access_control_schema,
    ensure_audit_events_schema,
    ensure_resource_ownership_columns,
    log_audit_event,
)


OWNED_TABLES: dict[str, tuple[str, str]] = {
    "project": ("projects", "id"),
    "conversation": ("conversations", "id"),
    "file": ("files", "id"),
    "artifact": ("artifacts", "id"),
    "memory": ("memories", "id"),
    "persona": ("personas", "id"),
    "user_profile": ("user_profiles", "id"),
}

MESSAGE_TABLES: dict[str, tuple[str, str]] = {
    "message": ("messages", "id"),
}

VISIBILITIES = {"private", "tenant", "public", "inherit"}
SHARING_MODES = {"owner", "inherit", "tenant", "public", "custom"}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_principal(value: str | None, *, default_type: str = "user") -> tuple[str, str] | None:
    value = _clean(value)
    if not value:
        return None
    if ":" in value:
        principal_type, principal_id = value.split(":", 1)
        principal_type = principal_type.strip() or default_type
        principal_id = principal_id.strip()
    else:
        principal_type = default_type
        principal_id = value
    if not principal_id:
        raise ValueError(f"Principal id is required in {value!r}")
    return principal_type, principal_id


def _parse_grant(value: str) -> tuple[str, str, str, str]:
    parts = [part.strip() for part in value.split(":")]
    if len(parts) != 4:
        raise ValueError("--grant must be EFFECT:PRINCIPAL_TYPE:PRINCIPAL_ID:ACTION")
    effect, principal_type, principal_id, action = parts
    if effect not in {"allow", "deny"}:
        raise ValueError("--grant effect must be allow or deny")
    if not principal_type or not principal_id or not action:
        raise ValueError("--grant requires principal type, principal id, and action")
    return effect, principal_type, principal_id, action


def _parse_kv(values: Iterable[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in values:
        key, sep, raw = value.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"Expected KEY=VALUE, got {value!r}")
        out[key.strip()] = raw.strip()
    return out


def _load_json(value: str | None) -> dict[str, Any]:
    value = _clean(value)
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON value must be an object")
    return parsed


def _dump_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_id(row: sqlite3.Row, id_column: str) -> str:
    return str(row[id_column])


def _select_owned(conn: sqlite3.Connection, resource_type: str, args: argparse.Namespace) -> list[sqlite3.Row]:
    table, id_column = OWNED_TABLES[resource_type]
    cols = _columns(conn, table)
    if not cols:
        return []

    where: list[str] = []
    params: list[Any] = []

    if args.resource_type and args.resource_type != resource_type:
        return []
    if args.resource_id:
        where.append(f"{id_column} = ?")
        params.append(args.resource_id)
    if args.from_tenant and "tenant_id" in cols:
        where.append("tenant_id = ?")
        params.append(args.from_tenant)
    if args.from_owner and {"owner_principal_type", "owner_principal_id"} <= cols:
        principal_type, principal_id = _parse_principal(args.from_owner) or ("user", args.from_owner)
        where.append("owner_principal_type = ? AND owner_principal_id = ?")
        params.extend([principal_type, principal_id])

    if args.conversation_id:
        if resource_type == "conversation":
            where.append(f"{id_column} = ?")
            params.append(args.conversation_id)
        elif resource_type == "file":
            where.append(
                """
                (
                    scope_uuid = ?
                    OR EXISTS (
                        SELECT 1 FROM conversation_files cf
                        WHERE cf.file_id = files.id AND cf.conversation_id = ?
                    )
                )
                """
            )
            params.extend([args.conversation_id, args.conversation_id])
        elif resource_type == "artifact":
            where.append(
                """
                (
                    scope_uuid = ?
                    OR EXISTS (
                        SELECT 1 FROM conversation_artifacts ca
                        WHERE ca.artifact_id = artifacts.id AND ca.conversation_id = ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM conversation_files cf
                        WHERE cf.conversation_id = ?
                          AND cf.file_id = artifacts.source_id
                    )
                )
                """
            )
            params.extend([args.conversation_id, args.conversation_id, args.conversation_id])
        elif resource_type == "memory":
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM memory_conversations mc
                    WHERE mc.memory_id = memories.id AND mc.conversation_id = ?
                )
                """
            )
            params.append(args.conversation_id)
        else:
            return []

    if args.project_id is not None:
        if resource_type == "project":
            where.append(f"{id_column} = ?")
            params.append(args.project_id)
        elif resource_type == "conversation":
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM project_conversations pc
                    WHERE pc.conversation_id = conversations.id AND pc.project_id = ?
                )
                """
            )
            params.append(args.project_id)
        elif resource_type == "file":
            where.append(
                """
                (
                    scope_id = ?
                    OR EXISTS (
                        SELECT 1 FROM project_files pf
                        WHERE pf.file_id = files.id AND pf.project_id = ?
                    )
                )
                """
            )
            params.extend([args.project_id, args.project_id])
        elif resource_type == "artifact":
            where.append("(project_id = ? OR scope_id = ?)")
            params.extend([args.project_id, args.project_id])
        elif resource_type == "memory":
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM memory_projects mp
                    WHERE mp.memory_id = memories.id AND mp.project_id = ?
                )
                """
            )
            params.append(args.project_id)
        else:
            return []

    if not where and args.match != "all":
        return []

    sql = f"SELECT * FROM {table}"
    if where:
        sql += " WHERE " + " AND ".join(f"({clause})" for clause in where)
    sql += f" ORDER BY {id_column}"
    return conn.execute(sql, params).fetchall()


def _select_messages(conn: sqlite3.Connection, args: argparse.Namespace) -> list[sqlite3.Row]:
    if not _table_exists(conn, "messages"):
        return []
    if args.resource_type and args.resource_type != "message":
        return []
    where: list[str] = []
    params: list[Any] = []
    if args.resource_id:
        where.append("id = ?")
        params.append(args.resource_id)
    if args.conversation_id:
        where.append("conversation_id = ?")
        params.append(args.conversation_id)
    if args.from_tenant and "tenant_id" in _columns(conn, "messages"):
        where.append("tenant_id = ?")
        params.append(args.from_tenant)
    if not where and args.match != "all":
        return []
    sql = "SELECT * FROM messages"
    if where:
        sql += " WHERE " + " AND ".join(f"({clause})" for clause in where)
    sql += " ORDER BY id"
    return conn.execute(sql, params).fetchall()


def _selected_resources(conn: sqlite3.Connection, args: argparse.Namespace) -> list[tuple[str, str, str, sqlite3.Row]]:
    resources: list[tuple[str, str, str, sqlite3.Row]] = []
    for resource_type, (table, id_column) in OWNED_TABLES.items():
        for row in _select_owned(conn, resource_type, args):
            resources.append((resource_type, table, id_column, row))
    for row in _select_messages(conn, args):
        resources.append(("message", "messages", "id", row))
    return resources


def _apply_owned_update(
    conn: sqlite3.Connection,
    resource_type: str,
    table: str,
    id_column: str,
    row: sqlite3.Row,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cols = _columns(conn, table)
    before = dict(row)
    updates: dict[str, Any] = {}
    owner = _parse_principal(args.set_owner)
    source = _parse_principal(args.set_source)
    creator = _parse_principal(args.set_creator)
    updater = _parse_principal(args.actor, default_type="user") or ("user", "local")

    if args.set_tenant_id and "tenant_id" in cols:
        updates["tenant_id"] = args.set_tenant_id
    if owner and {"owner_principal_type", "owner_principal_id"} <= cols:
        updates["owner_principal_type"] = owner[0]
        updates["owner_principal_id"] = owner[1]
        if owner[0] == "user" and "owner_user_id" in cols:
            updates["owner_user_id"] = owner[1]
    if creator and {"created_by_principal_type", "created_by_principal_id"} <= cols:
        updates["created_by_principal_type"] = creator[0]
        updates["created_by_principal_id"] = creator[1]
        if creator[0] == "user" and "created_by_user_id" in cols:
            updates["created_by_user_id"] = creator[1]
    if source and {"source_principal_type", "source_principal_id"} <= cols:
        updates["source_principal_type"] = source[0]
        updates["source_principal_id"] = source[1]
    if args.visibility and "visibility" in cols:
        updates["visibility"] = args.visibility
    if args.sharing_mode and "sharing_mode" in cols:
        updates["sharing_mode"] = args.sharing_mode
    if "updated_by_principal_type" in cols:
        updates["updated_by_principal_type"] = updater[0]
    if "updated_by_principal_id" in cols:
        updates["updated_by_principal_id"] = updater[1]
    if updater[0] == "user" and "updated_by_user_id" in cols:
        updates["updated_by_user_id"] = updater[1]

    provenance = _load_json(row["provenance_json"] if "provenance_json" in cols else None)
    if args.set_provenance_json:
        provenance = _load_json(args.set_provenance_json)
    if args.provenance:
        provenance.update(_parse_kv(args.provenance))
    if provenance and "provenance_json" in cols:
        updates["provenance_json"] = _dump_json(provenance)

    if not updates:
        return {"changed": False, "before": before, "after": before}

    assignments = ", ".join(f"{col} = ?" for col in updates)
    params = list(updates.values()) + [row[id_column]]
    conn.execute(f"UPDATE {table} SET {assignments} WHERE {id_column} = ?", params)
    after = dict(conn.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (row[id_column],)).fetchone())
    log_audit_event(
        event_type="admin.bulk_reassign",
        tenant_id=after.get("tenant_id") or before.get("tenant_id") or "default",
        actor_principal_type=updater[0],
        actor_principal_id=updater[1],
        resource_type=resource_type,
        resource_id=str(row[id_column]),
        action="bulk_reassign",
        summary=f"Bulk reassigned {resource_type} {row[id_column]}",
        before=before,
        after=after,
        metadata={"updated_fields": sorted(updates)},
        conn=conn,
        raise_on_error=True,
    )
    return {"changed": True, "before": before, "after": after}


def _apply_grants(
    conn: sqlite3.Connection,
    resource_type: str,
    resource_id: str,
    tenant_id: str,
    args: argparse.Namespace,
) -> list[str]:
    actor = _parse_principal(args.actor, default_type="user") or ("user", "local")
    grant_ids: list[str] = []
    for grant in args.grant or []:
        effect, principal_type, principal_id, action = _parse_grant(grant)
        grant_ids.append(
            create_access_control_entry(
                conn=conn,
                tenant_id=tenant_id or "default",
                resource_type=resource_type,
                resource_id=resource_id,
                principal_type=principal_type,
                principal_id=principal_id,
                effect=effect,
                action=action,
                reason=args.reason or "bulk reassignment",
                created_by_principal_type=actor[0],
                created_by_principal_id=actor[1],
            )
        )
    return grant_ids


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk reassign WyrmGPT ownership, provenance, sharing, and persona access metadata.",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help=f"SQLite DB path. Default: {DB_PATH}")
    parser.add_argument("--apply", action="store_true", help="Apply changes. Default is dry-run.")
    parser.add_argument("--match", choices=["all", "conversation", "project", "owner", "tenant", "resource"], default="resource")
    parser.add_argument("--conversation-id")
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--from-owner", help="Only resources currently owned by TYPE:ID, or user ID.")
    parser.add_argument("--from-tenant")
    parser.add_argument("--resource-type", choices=sorted([*OWNED_TABLES, *MESSAGE_TABLES]))
    parser.add_argument("--resource-id")
    parser.add_argument("--set-owner", help="Set owner to TYPE:ID, or user ID.")
    parser.add_argument("--set-creator", help="Set created-by principal to TYPE:ID.")
    parser.add_argument("--set-source", help="Set source principal to TYPE:ID.")
    parser.add_argument("--set-tenant-id")
    parser.add_argument("--visibility", choices=sorted(VISIBILITIES))
    parser.add_argument("--sharing-mode", choices=sorted(SHARING_MODES))
    parser.add_argument("--set-provenance-json", help="Replace provenance_json with a JSON object.")
    parser.add_argument("--provenance", action="append", default=[], help="Merge provenance KEY=VALUE. Repeatable.")
    parser.add_argument("--grant", action="append", default=[], help="Add ACE as EFFECT:PRINCIPAL_TYPE:PRINCIPAL_ID:ACTION. Repeatable.")
    parser.add_argument("--actor", default="user:local", help="Actor principal for audit rows. Default: user:local")
    parser.add_argument("--reason", default="bulk reassignment")
    parser.add_argument("--limit", type=int, default=0, help="Maximum selected resources to process.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.match == "conversation" and not args.conversation_id:
        raise ValueError("--match conversation requires --conversation-id")
    if args.match == "project" and args.project_id is None:
        raise ValueError("--match project requires --project-id")
    if args.match == "owner" and not args.from_owner:
        raise ValueError("--match owner requires --from-owner")
    if args.match == "tenant" and not args.from_tenant:
        raise ValueError("--match tenant requires --from-tenant")
    if args.match == "resource" and not (args.resource_type and args.resource_id):
        raise ValueError("--match resource requires --resource-type and --resource-id")
    if not any([
        args.set_owner,
        args.set_creator,
        args.set_source,
        args.set_tenant_id,
        args.visibility,
        args.sharing_mode,
        args.set_provenance_json,
        args.provenance,
        args.grant,
    ]):
        raise ValueError("No changes requested.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        validate_args(args)
        if args.set_provenance_json:
            _load_json(args.set_provenance_json)
        _parse_kv(args.provenance)
        for grant in args.grant or []:
            _parse_grant(grant)
    except Exception as exc:
        parser.error(str(exc))

    conn = _connect(args.db)
    try:
        ensure_audit_events_schema(conn)
        ensure_access_control_schema(conn)
        ensure_resource_ownership_columns(conn)
        resources = _selected_resources(conn, args)
        if args.limit and args.limit > 0:
            resources = resources[: args.limit]

        summary: dict[str, Any] = {
            "db": str(args.db),
            "dry_run": not args.apply,
            "selected_count": len(resources),
            "changed_count": 0,
            "grant_count": 0,
            "resources": [],
        }

        if not args.apply:
            for resource_type, table, id_column, row in resources:
                summary["resources"].append({
                    "resource_type": resource_type,
                    "resource_id": _row_id(row, id_column),
                    "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else None,
                    "owner": (
                        f"{row['owner_principal_type']}:{row['owner_principal_id']}"
                        if "owner_principal_type" in row.keys() and row["owner_principal_type"]
                        else None
                    ),
                })
        else:
            with conn:
                for resource_type, table, id_column, row in resources:
                    result = _apply_owned_update(conn, resource_type, table, id_column, row, args)
                    tenant_id = result["after"].get("tenant_id") or row["tenant_id"] if "tenant_id" in row.keys() else "default"
                    grant_ids = _apply_grants(conn, resource_type, _row_id(row, id_column), tenant_id or "default", args)
                    if result["changed"]:
                        summary["changed_count"] += 1
                    summary["grant_count"] += len(grant_ids)
                    summary["resources"].append({
                        "resource_type": resource_type,
                        "resource_id": _row_id(row, id_column),
                        "changed": result["changed"],
                        "grant_ids": grant_ids,
                    })

        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            mode = "DRY RUN" if summary["dry_run"] else "APPLIED"
            print(f"{mode}: selected {summary['selected_count']} resource(s); changed {summary['changed_count']}; grants {summary['grant_count']}")
            for item in summary["resources"][:50]:
                print(f"- {item['resource_type']}:{item['resource_id']}")
            if len(summary["resources"]) > 50:
                print(f"... {len(summary['resources']) - 50} more")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
