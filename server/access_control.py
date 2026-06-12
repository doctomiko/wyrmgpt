from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import TenantPolicyConfig, resolve_tenant_policy
from .db_helpers import db_session, list_access_control_entries


@dataclass(frozen=True)
class PrincipalContext:
    principal_type: str
    principal_id: str
    tenant_id: str = "default"
    groups: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceRef:
    resource_type: str
    resource_id: str
    tenant_id: str = "default"
    owner_principal_type: str | None = None
    owner_principal_id: str | None = None
    visibility: str | None = None
    inherited_from: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    effect: str
    reason: str
    matched_entries: list[dict] = field(default_factory=list)
    inherited_from: list[dict] = field(default_factory=list)
    policy: dict = field(default_factory=dict)
    explain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _clean(value: Any, default: str = "") -> str:
    cleaned = str(value or "").strip()
    return cleaned or default


def _parse_principal(principal: PrincipalContext | dict[str, Any]) -> PrincipalContext:
    if isinstance(principal, PrincipalContext):
        return principal
    groups = principal.get("groups") or ()
    roles = principal.get("roles") or ()
    return PrincipalContext(
        principal_type=_clean(principal.get("principal_type") or principal.get("type"), "user"),
        principal_id=_clean(principal.get("principal_id") or principal.get("id"), "local"),
        tenant_id=_clean(principal.get("tenant_id"), "default"),
        groups=tuple(_clean(g) for g in groups if _clean(g)),
        roles=tuple(_clean(r) for r in roles if _clean(r)),
    )


def _parse_resource(resource: ResourceRef | dict[str, Any]) -> ResourceRef:
    if isinstance(resource, ResourceRef):
        return resource
    inherited = resource.get("inherited_from") or ()
    return ResourceRef(
        resource_type=_clean(resource.get("resource_type") or resource.get("type")),
        resource_id=_clean(resource.get("resource_id") or resource.get("id")),
        tenant_id=_clean(resource.get("tenant_id"), "default"),
        owner_principal_type=_clean(resource.get("owner_principal_type")) or None,
        owner_principal_id=_clean(resource.get("owner_principal_id")) or None,
        visibility=_clean(resource.get("visibility")) or None,
        inherited_from=tuple(
            {
                "resource_type": _clean(item.get("resource_type") or item.get("type")),
                "resource_id": _clean(item.get("resource_id") or item.get("id")),
            }
            for item in inherited
            if isinstance(item, dict) and _clean(item.get("resource_type") or item.get("type")) and _clean(item.get("resource_id") or item.get("id"))
        ),
    )


def _principal_targets(principal: PrincipalContext) -> set[tuple[str, str]]:
    targets = {(principal.principal_type, principal.principal_id), ("public", "*")}
    targets.update(("group", group_id) for group_id in principal.groups)
    targets.update(("role", role_id) for role_id in principal.roles)
    return targets


def _is_expired(row: dict, now: datetime) -> bool:
    raw = _clean(row.get("expires_at"))
    if not raw:
        return False
    try:
        expires = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= now


def _row_matches_principal(row: dict, targets: set[tuple[str, str]]) -> bool:
    return (_clean(row.get("principal_type")), _clean(row.get("principal_id"))) in targets


def _policy_dict(policy: TenantPolicyConfig) -> dict:
    return asdict(policy)


def _visibility_for(resource: ResourceRef, policy: TenantPolicyConfig) -> str:
    if resource.visibility:
        return resource.visibility
    field_name = f"{resource.resource_type}_visibility"
    return getattr(policy, field_name, "private")


def _fetch_entries(conn, resource: ResourceRef, action: str, inherited: bool) -> list[dict]:
    entries = list_access_control_entries(
        conn=conn,
        tenant_id=resource.tenant_id,
        resource_type=resource.resource_type,
        resource_id=resource.resource_id,
        action=action,
    )
    for row in entries:
        row["_inherited"] = inherited
    return entries


def resolve_access(
    principal: PrincipalContext | dict[str, Any],
    resource: ResourceRef | dict[str, Any],
    action: str,
    *,
    explain: bool = False,
    conn=None,
    tenant_policy: TenantPolicyConfig | None = None,
) -> AccessDecision:
    principal_ctx = _parse_principal(principal)
    resource_ref = _parse_resource(resource)
    action = _clean(action, "read")
    tenant_id = resource_ref.tenant_id or principal_ctx.tenant_id or "default"
    resource_ref = ResourceRef(**{**asdict(resource_ref), "tenant_id": tenant_id})
    policy = tenant_policy or resolve_tenant_policy(tenant_id)
    notes: list[str] = []

    def note(message: str) -> None:
        if explain:
            notes.append(message)

    targets = _principal_targets(principal_ctx)
    note(f"principal targets: {sorted(targets)}")
    note(f"resource: {resource_ref.resource_type}:{resource_ref.resource_id} action={action} tenant={tenant_id}")

    def _resolve(active_conn) -> AccessDecision:
        now = datetime.now(timezone.utc)
        direct_entries = _fetch_entries(active_conn, resource_ref, action, inherited=False)
        inherited_entries: list[dict] = []
        for parent in resource_ref.inherited_from:
            parent_ref = ResourceRef(
                resource_type=parent["resource_type"],
                resource_id=parent["resource_id"],
                tenant_id=tenant_id,
            )
            inherited_entries.extend(_fetch_entries(active_conn, parent_ref, action, inherited=True))

        entries = [row for row in direct_entries + inherited_entries if not _is_expired(row, now)]
        matching = [row for row in entries if _row_matches_principal(row, targets)]
        note(f"matched ACEs: {len(matching)}")

        denies = [row for row in matching if row.get("effect") == "deny"]
        if denies:
            note("deny ACE wins")
            return AccessDecision(
                allowed=False,
                effect="deny",
                reason="matched deny access-control entry",
                matched_entries=denies,
                inherited_from=[row for row in denies if row.get("_inherited")],
                policy=_policy_dict(policy),
                explain=notes,
            )

        if (
            resource_ref.owner_principal_type
            and resource_ref.owner_principal_id
            and (resource_ref.owner_principal_type, resource_ref.owner_principal_id) in targets
        ):
            note("owner principal matched")
            return AccessDecision(
                allowed=True,
                effect="allow",
                reason="resource owner",
                matched_entries=[],
                inherited_from=[],
                policy=_policy_dict(policy),
                explain=notes,
            )

        allows = [row for row in matching if row.get("effect") == "allow"]
        if allows:
            note("allow ACE matched")
            return AccessDecision(
                allowed=True,
                effect="allow",
                reason="matched allow access-control entry",
                matched_entries=allows,
                inherited_from=[row for row in allows if row.get("_inherited")],
                policy=_policy_dict(policy),
                explain=notes,
            )

        visibility = _visibility_for(resource_ref, policy)
        note(f"visibility fallback: {visibility}")
        if action == "read" and visibility == "public" and policy.public_sharing_enabled:
            return AccessDecision(True, "allow", "public visibility", [], [], _policy_dict(policy), notes)
        if action == "read" and visibility == "tenant" and principal_ctx.tenant_id == tenant_id:
            return AccessDecision(True, "allow", "tenant visibility", [], [], _policy_dict(policy), notes)
        if policy.missing_access_default == "single_user_compatible":
            return AccessDecision(True, "allow", "single-user compatibility default", [], [], _policy_dict(policy), notes)
        if policy.missing_access_default == "allow_tenant" and principal_ctx.tenant_id == tenant_id:
            return AccessDecision(True, "allow", "tenant policy default", [], [], _policy_dict(policy), notes)

        return AccessDecision(False, "deny", "no matching access rule", [], [], _policy_dict(policy), notes)

    if conn is not None:
        return _resolve(conn)
    with db_session() as active_conn:
        return _resolve(active_conn)
