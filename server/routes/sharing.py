from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.access_control import resolve_access
from server.access_filtering import principal_from_request
from server.db import (
    db_get_artifact_access_resource,
    db_get_conversation_access_resource,
    db_get_file_access_resource,
    db_get_memory_access_resource,
    db_get_message_access_resource,
    db_get_project_access_resource,
    db_get_user_profile_access_resource,
    db_get_effective_sharing_source,
)
from server.db_helpers import db_session, list_access_control_entries
from server.routes.base import app


_RESOURCE_LOADERS = {
    "artifact": db_get_artifact_access_resource,
    "conversation": db_get_conversation_access_resource,
    "file": db_get_file_access_resource,
    "memory": db_get_memory_access_resource,
    "message": db_get_message_access_resource,
    "project": db_get_project_access_resource,
    "user_profile": db_get_user_profile_access_resource,
}


def _principal_memberships(conn, principal: dict) -> dict:
    tenant_id = principal.get("tenant_id") or "default"
    principal_type = principal.get("principal_type") or "user"
    principal_id = principal.get("principal_id") or "local"
    groups = [
        dict(row)
        for row in conn.execute(
            """
            SELECT gm.*, g.name AS group_name
            FROM identity_group_members gm
            LEFT JOIN identity_groups g ON g.id = gm.group_id
            WHERE gm.tenant_id = ?
              AND gm.member_principal_type = ?
              AND gm.member_principal_id = ?
              AND gm.is_deleted = 0
            """,
            (tenant_id, principal_type, principal_id),
        ).fetchall()
    ]
    group_ids = [row["group_id"] for row in groups]
    params = [tenant_id, principal_type, principal_id, *group_ids]
    role_sql = """
        SELECT ra.*, r.name AS role_name
        FROM identity_role_assignments ra
        LEFT JOIN identity_roles r ON r.id = ra.role_id
        WHERE ra.tenant_id IN (?, 'global')
          AND ra.is_deleted = 0
          AND ((ra.principal_type = ? AND ra.principal_id = ?)
    """
    if group_ids:
        role_sql += " OR (ra.principal_type = 'group' AND ra.principal_id IN (" + ",".join("?" for _ in group_ids) + "))"
    role_sql += ")"
    roles = [dict(row) for row in conn.execute(role_sql, params).fetchall()]
    return {"groups": groups, "roles": roles}


def _resource_for(resource_type: str, resource_id: str) -> dict:
    resource_type = (resource_type or "").strip().lower()
    resource_id = (resource_id or "").strip()
    loader = _RESOURCE_LOADERS.get(resource_type)
    if not loader:
        raise HTTPException(status_code=400, detail=f"Unsupported resource_type: {resource_type}")
    try:
        resource = loader(int(resource_id)) if resource_type in {"message", "project"} else loader(resource_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found.")
    return resource


@app.get("/api/sharing/diagnostics")
def api_sharing_diagnostics(
    resource_type: str,
    resource_id: str,
    action: str = "read",
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str | None = None,
    requester_type: str = "user",
    requester_id: str = "local",
    requester_tenant_id: str | None = None,
    admin_view: str | None = None,
):
    resource = _resource_for(resource_type, resource_id)
    principal = {
        "principal_type": principal_type,
        "principal_id": principal_id,
        "tenant_id": tenant_id or resource.get("tenant_id") or "default",
    }

    with db_session() as conn:
        requester = principal_from_request(
            principal_type=requester_type,
            principal_id=requester_id,
            tenant_id=requester_tenant_id or principal["tenant_id"],
            admin_view=admin_view,
        )
        audit_decision = resolve_access(requester, resource, "audit", explain=True, conn=conn)
        if not audit_decision.allowed:
            raise HTTPException(status_code=403, detail="Sharing diagnostics require audit access.")
        decision = resolve_access(principal, resource, action, explain=True, conn=conn)
        memberships = _principal_memberships(conn, principal)
        effective_source = db_get_effective_sharing_source(resource["resource_type"], resource["resource_id"])
        persona_context_decision = None
        if resource["resource_type"] in {"memory", "user_profile"}:
            persona_principal = {
                "principal_type": "persona",
                "principal_id": principal_id if principal_type == "persona" else "assistant",
                "tenant_id": principal["tenant_id"],
            }
            persona_context_decision = resolve_access(
                persona_principal,
                resource,
                "use_in_context",
                explain=True,
                conn=conn,
            ).to_dict()
        direct_entries = list_access_control_entries(
            conn=conn,
            tenant_id=resource.get("tenant_id") or "default",
            resource_type=resource["resource_type"],
            resource_id=resource["resource_id"],
            include_deleted=False,
        )
        inherited_entries = []
        for parent in resource.get("inherited_from") or []:
            inherited_entries.extend(
                list_access_control_entries(
                    conn=conn,
                    tenant_id=resource.get("tenant_id") or "default",
                    resource_type=parent.get("resource_type"),
                    resource_id=parent.get("resource_id"),
                    include_deleted=False,
                )
            )

    return JSONResponse(
        {
            "resource": resource,
            "principal": principal,
            "action": action,
            "decision": decision.to_dict(),
            "persona_context_decision": persona_context_decision,
            "effective_sharing_source": effective_source,
            "principal_memberships": memberships,
            "default_chain": {
                "resource_visibility": resource.get("visibility"),
                "tenant_policy": decision.to_dict().get("policy"),
                "inherited_from": resource.get("inherited_from") or [],
            },
            "direct_access_control_entries": direct_entries,
            "inherited_access_control_entries": inherited_entries,
        }
    )
