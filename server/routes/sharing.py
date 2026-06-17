from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse
import json

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
from server.db_helpers import (
    create_access_control_entry,
    db_session,
    list_access_control_entries,
    log_audit_event,
    remove_access_control_entry,
)
from server.routes.base import app


_RESOURCE_TABLES = {
    "artifact": ("artifacts", "id"),
    "conversation": ("conversations", "id"),
    "file": ("files", "id"),
    "memory": ("memories", "id"),
    "message": ("messages", "id"),
    "project": ("projects", "id"),
    "user_profile": ("user_profiles", "id"),
}

_RESOURCE_LOADERS = {
    "artifact": db_get_artifact_access_resource,
    "conversation": db_get_conversation_access_resource,
    "file": db_get_file_access_resource,
    "memory": db_get_memory_access_resource,
    "message": db_get_message_access_resource,
    "project": db_get_project_access_resource,
    "user_profile": db_get_user_profile_access_resource,
}

_VALID_VISIBILITIES = {"inherit", "private", "public", "tenant"}
_VALID_SHARING_MODES = {"custom", "inherit", "owner", "public", "tenant"}


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


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


def _requester_from_payload(payload: dict, resource: dict) -> dict:
    return principal_from_request(
        principal_type=_clean(payload.get("requester_type")) or "user",
        principal_id=_clean(payload.get("requester_id")) or "local",
        tenant_id=_clean(payload.get("requester_tenant_id")) or resource.get("tenant_id") or "default",
        admin_view=payload.get("admin_view"),
    )


def _require_share_access(conn, requester: dict, resource: dict) -> None:
    decision = resolve_access(requester, resource, "share", explain=True, conn=conn)
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="Sharing edits require share access.")


def _load_provenance(value: object) -> dict:
    text = _clean(value)
    if not text:
        return {}
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("provenance_json must be a JSON object")
    return parsed


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


@app.put("/api/sharing/resource")
def api_update_resource_sharing(payload: dict = Body(default_factory=dict)):
    resource_type = _clean(payload.get("resource_type")) or ""
    resource_id = _clean(payload.get("resource_id")) or ""
    resource = _resource_for(resource_type, resource_id)
    table_info = _RESOURCE_TABLES.get(resource["resource_type"])
    if not table_info:
        raise HTTPException(status_code=400, detail=f"Unsupported resource_type: {resource_type}")
    table, id_column = table_info

    visibility = _clean(payload.get("visibility"))
    sharing_mode = _clean(payload.get("sharing_mode"))
    if visibility and visibility not in _VALID_VISIBILITIES:
        raise HTTPException(status_code=400, detail=f"visibility must be one of {sorted(_VALID_VISIBILITIES)}")
    if sharing_mode and sharing_mode not in _VALID_SHARING_MODES:
        raise HTTPException(status_code=400, detail=f"sharing_mode must be one of {sorted(_VALID_SHARING_MODES)}")

    try:
        provenance_json = _load_provenance(payload.get("provenance_json")) if "provenance_json" in payload else None
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    requester = _requester_from_payload(payload, resource)
    with db_session() as conn:
        _require_share_access(conn, requester, resource)
        cols = _columns(conn, table)
        row = conn.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (resource["resource_id"],)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Resource not found.")

        before = dict(row)
        updates: dict[str, object] = {}
        if visibility and "visibility" in cols:
            updates["visibility"] = visibility
        if sharing_mode and "sharing_mode" in cols:
            updates["sharing_mode"] = sharing_mode
        if provenance_json is not None and "provenance_json" in cols:
            updates["provenance_json"] = json.dumps(provenance_json, ensure_ascii=False, sort_keys=True)

        if not updates:
            return JSONResponse({"ok": True, "changed": False, "updated_fields": []})

        assignments = ", ".join(f"{col} = ?" for col in updates)
        with conn:
            conn.execute(
                f"UPDATE {table} SET {assignments} WHERE {id_column} = ?",
                [*updates.values(), resource["resource_id"]],
            )
            after = conn.execute(f"SELECT * FROM {table} WHERE {id_column} = ?", (resource["resource_id"],)).fetchone()
            log_audit_event(
                event_type="sharing.resource.update",
                tenant_id=resource.get("tenant_id") or "default",
                actor_principal_type=requester.get("principal_type"),
                actor_principal_id=requester.get("principal_id"),
                resource_type=resource["resource_type"],
                resource_id=resource["resource_id"],
                action="share",
                summary=f"Updated sharing metadata for {resource['resource_type']} {resource['resource_id']}",
                before=before,
                after=dict(after) if after else None,
                metadata={"updated_fields": sorted(updates)},
                conn=conn,
                raise_on_error=True,
            )

    return JSONResponse({"ok": True, "changed": True, "updated_fields": sorted(updates)})


@app.post("/api/sharing/access-control")
def api_create_resource_access_control(payload: dict = Body(default_factory=dict)):
    resource_type = _clean(payload.get("resource_type")) or ""
    resource_id = _clean(payload.get("resource_id")) or ""
    resource = _resource_for(resource_type, resource_id)
    requester = _requester_from_payload(payload, resource)

    with db_session() as conn:
        _require_share_access(conn, requester, resource)
        try:
            ace_id = create_access_control_entry(
                conn=conn,
                tenant_id=resource.get("tenant_id") or "default",
                resource_type=resource["resource_type"],
                resource_id=resource["resource_id"],
                principal_type=_clean(payload.get("principal_type")) or "",
                principal_id=_clean(payload.get("principal_id")) or "",
                effect=_clean(payload.get("effect")) or "allow",
                action=_clean(payload.get("action")) or "read",
                reason=_clean(payload.get("reason")),
                expires_at=_clean(payload.get("expires_at")),
                created_by_principal_type=requester.get("principal_type"),
                created_by_principal_id=requester.get("principal_id"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return JSONResponse({"ok": True, "ace_id": ace_id})


@app.delete("/api/sharing/access-control/{ace_id}")
def api_remove_resource_access_control(ace_id: str, payload: dict = Body(default_factory=dict)):
    ace_id = _clean(ace_id) or ""
    with db_session() as conn:
        row = conn.execute("SELECT * FROM access_control_entries WHERE id = ?", (ace_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Access control entry not found.")
        resource = _resource_for(row["resource_type"], row["resource_id"])
        requester = _requester_from_payload(payload, resource)
        _require_share_access(conn, requester, resource)
        removed = remove_access_control_entry(
            ace_id,
            deleted_by_principal_type=requester.get("principal_type"),
            deleted_by_principal_id=requester.get("principal_id"),
            conn=conn,
        )
    return JSONResponse({"ok": True, "removed": removed})
