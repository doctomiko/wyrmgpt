from __future__ import annotations

from typing import Any

from .access_control import resolve_access
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
