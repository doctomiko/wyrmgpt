from __future__ import annotations

from typing import Any

from .access_control import resolve_access
from .db import (
    db_get_artifact_access_resource,
    db_get_conversation_access_resource,
    db_get_file_access_resource,
    db_get_memory_access_resource,
)
from .db_helpers import db_session


def principal_from_request(
    *,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
) -> dict[str, Any]:
    principal = {
        "principal_type": (principal_type or "user").strip() or "user",
        "principal_id": (principal_id or "local").strip() or "local",
        "tenant_id": (tenant_id or "default").strip() or "default",
        "roles": [],
    }
    mode = (admin_view or "").strip().lower()
    if mode in {"tenant", "tenant_admin", "true", "1"}:
        principal["roles"] = ["tenant_admin"]
    elif mode in {"global", "global_admin"}:
        principal["roles"] = ["global_admin"]
    return principal


def resource_from_row(row: dict[str, Any], resource_type: str) -> dict[str, Any]:
    inherited: list[dict[str, str]] = []
    if resource_type == "memory":
        inherited.extend(
            {"resource_type": "project", "resource_id": str(project_id)}
            for project_id in (row.get("project_ids") or [])
        )
        inherited.extend(
            {"resource_type": "conversation", "resource_id": str(conversation_id)}
            for conversation_id in (row.get("conversation_ids") or [])
        )
    return {
        "resource_type": resource_type,
        "resource_id": str(row.get("id")),
        "tenant_id": (row.get("tenant_id") or "default").strip() or "default",
        "owner_principal_type": row.get("owner_principal_type"),
        "owner_principal_id": row.get("owner_principal_id"),
        "visibility": row.get("visibility"),
        "inherited_from": inherited,
    }


def resource_from_corpus_row(row: dict[str, Any]) -> dict[str, Any] | None:
    source_kind = (row.get("source_kind") or "").strip()
    source_id = str(row.get("source_id") or "").strip()
    artifact_id = str(row.get("artifact_id") or "").strip()
    file_id = str(row.get("file_id") or "").strip()

    if source_kind == "memory" and source_id:
        return db_get_memory_access_resource(source_id)
    if source_kind == "conversation:transcript" and source_id:
        return db_get_conversation_access_resource(source_id)
    if artifact_id:
        return db_get_artifact_access_resource(artifact_id)
    if file_id:
        return db_get_file_access_resource(file_id)
    return None


def filter_rows_for_access(
    rows: list[dict[str, Any]],
    resource_type: str,
    *,
    principal: dict[str, Any],
    action: str = "read",
    include_access_meta: bool = True,
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    with db_session() as conn:
        for row in rows:
            resource = resource_from_row(row, resource_type)
            decision = resolve_access(principal, resource, action, conn=conn, explain=True)
            if not decision.allowed:
                continue
            item = dict(row)
            if include_access_meta:
                item["effective_access"] = decision.to_dict()
                item["admin_visible"] = decision.reason in {
                    "global admin policy",
                    "tenant admin policy",
                }
            visible.append(item)
    return visible


def filter_corpus_rows_for_access(
    rows: list[dict[str, Any]],
    *,
    principal: dict[str, Any],
    action: str = "read",
    include_access_meta: bool = True,
) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    with db_session() as conn:
        for row in rows:
            resource = resource_from_corpus_row(row)
            if resource is None:
                continue
            decision = resolve_access(principal, resource, action, conn=conn, explain=True)
            if not decision.allowed:
                continue
            item = dict(row)
            if include_access_meta:
                item["effective_access"] = decision.to_dict()
                item["access_resource"] = {
                    "resource_type": resource.get("resource_type"),
                    "resource_id": resource.get("resource_id"),
                }
                item["admin_visible"] = decision.reason in {
                    "global admin policy",
                    "tenant admin policy",
                }
            visible.append(item)
    return visible


def filter_items_by_resource_access(
    items: list[dict[str, Any]],
    resource_type: str,
    *,
    id_key: str = "id",
    principal: dict[str, Any],
    action: str = "read",
    include_access_meta: bool = True,
) -> list[dict[str, Any]]:
    loaders = {
        "artifact": db_get_artifact_access_resource,
        "conversation": db_get_conversation_access_resource,
        "file": db_get_file_access_resource,
        "memory": db_get_memory_access_resource,
    }
    loader = loaders.get((resource_type or "").strip().lower())
    if loader is None:
        raise ValueError(f"Unsupported resource_type: {resource_type}")

    visible: list[dict[str, Any]] = []
    with db_session() as conn:
        for item in items:
            resource_id = str(item.get(id_key) or "").strip()
            if not resource_id:
                continue
            resource = loader(resource_id)
            if resource is None:
                continue
            decision = resolve_access(principal, resource, action, conn=conn, explain=True)
            if not decision.allowed:
                continue
            out = dict(item)
            if include_access_meta:
                out["effective_access"] = decision.to_dict()
                out["admin_visible"] = decision.reason in {
                    "global admin policy",
                    "tenant admin policy",
                }
            visible.append(out)
    return visible
