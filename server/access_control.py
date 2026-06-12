from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import TenantPolicyConfig, resolve_tenant_policy
from .db_helpers import db_session, list_access_control_entries

_ACTION_ALIASES = {
    "read": ("read", "view"),
    "view": ("view", "read"),
    "write": ("write", "edit"),
    "edit": ("edit", "write"),
    "delete": ("delete", "soft_remove"),
    "soft_remove": ("soft_remove", "delete"),
    "admin": ("admin", "manage"),
    "manage": ("manage", "admin"),
    "use_in_context": ("use_in_context",),
}


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
    if principal.principal_type == "user":
        targets.add(("tenant_users", "*"))
    if principal.principal_type == "persona":
        targets.add(("tenant_personas", "*"))
    targets.update(("group", group_id) for group_id in principal.groups)
    targets.update(("role", role_id) for role_id in principal.roles)
    return targets


def _action_candidates(action: str) -> tuple[str, ...]:
    cleaned = _clean(action, "read").lower()
    return _ACTION_ALIASES.get(cleaned, (cleaned,))


def _role_matches(principal: PrincipalContext, role_name: str) -> bool:
    role_name = role_name.strip().lower()
    for role in principal.roles:
        cleaned = role.strip().lower()
        if cleaned == role_name or cleaned.endswith(f":{role_name}"):
            return True
    return False


def _with_derived_memberships(conn, principal: PrincipalContext) -> PrincipalContext:
    groups = set(principal.groups)
    roles = set(principal.roles)
    try:
        group_rows = conn.execute(
            """
            SELECT group_id
            FROM identity_group_members
            WHERE tenant_id = ?
              AND member_principal_type = ?
              AND member_principal_id = ?
              AND is_deleted = 0
              AND (expires_at IS NULL OR TRIM(expires_at) = '' OR expires_at > CURRENT_TIMESTAMP)
            """,
            (principal.tenant_id, principal.principal_type, principal.principal_id),
        ).fetchall()
        groups.update(str(row["group_id"]) for row in group_rows)

        role_rows = conn.execute(
            """
            SELECT ra.role_id, r.name
            FROM identity_role_assignments ra
            LEFT JOIN identity_roles r ON r.id = ra.role_id
            WHERE ra.tenant_id IN (?, 'global')
              AND ra.is_deleted = 0
              AND (ra.expires_at IS NULL OR TRIM(ra.expires_at) = '' OR ra.expires_at > CURRENT_TIMESTAMP)
              AND (
                (ra.principal_type = ? AND ra.principal_id = ?)
                OR (ra.principal_type = 'group' AND ra.principal_id IN (%s))
              )
            """ % (",".join("?" for _ in groups) or "''"),
            (principal.tenant_id, principal.principal_type, principal.principal_id, *groups),
        ).fetchall()
        for row in role_rows:
            roles.add(str(row["role_id"]))
            if row["name"]:
                roles.add(str(row["name"]))
    except Exception:
        return principal
    return PrincipalContext(
        principal_type=principal.principal_type,
        principal_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        groups=tuple(sorted(groups)),
        roles=tuple(sorted(roles)),
    )


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
    entries: list[dict] = []
    seen: set[str] = set()
    for candidate in _action_candidates(action):
        for row in list_access_control_entries(
            conn=conn,
            tenant_id=resource.tenant_id,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            action=candidate,
        ):
            row_id = _clean(row.get("id"))
            if row_id in seen:
                continue
            seen.add(row_id)
            row["_inherited"] = inherited
            entries.append(row)
    return entries


def _admin_decision(principal: PrincipalContext, action: str, policy: TenantPolicyConfig, notes: list[str]) -> AccessDecision | None:
    action = _clean(action, "read").lower()
    if _role_matches(principal, "global_admin") and policy.global_admin_manage_all:
        notes.append("global_admin policy matched")
        return AccessDecision(True, "allow", "global admin policy", [], [], _policy_dict(policy), notes)
    if _role_matches(principal, "tenant_admin") and policy.tenant_admin_manage_all:
        if action == "permanent_remove" and not policy.tenant_admin_can_permanent_remove:
            notes.append("tenant_admin permanent_remove denied by policy")
            return AccessDecision(False, "deny", "tenant admin permanent remove disabled", [], [], _policy_dict(policy), notes)
        notes.append("tenant_admin policy matched")
        return AccessDecision(True, "allow", "tenant admin policy", [], [], _policy_dict(policy), notes)
    return None


def _owner_policy_denial(action: str, policy: TenantPolicyConfig) -> str | None:
    action = _clean(action, "read").lower()
    if action == "archive" and not policy.owner_can_archive:
        return "owner archive disabled by tenant policy"
    if action in {"soft_remove", "delete"} and not policy.owner_can_soft_remove:
        return "owner soft remove disabled by tenant policy"
    if action == "permanent_remove" and not policy.owner_can_permanent_remove:
        return "owner permanent remove disabled by tenant policy"
    return None


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
    action = _clean(action, "read").lower()
    if principal_ctx.principal_type == "persona" and action == "read" and resource_ref.resource_type in {"memory", "user_profile"}:
        action = "use_in_context"
    tenant_id = resource_ref.tenant_id or principal_ctx.tenant_id or "default"
    resource_ref = ResourceRef(**{**asdict(resource_ref), "tenant_id": tenant_id})
    policy = tenant_policy or resolve_tenant_policy(tenant_id)
    notes: list[str] = []

    def note(message: str) -> None:
        if explain:
            notes.append(message)

    note(f"resource: {resource_ref.resource_type}:{resource_ref.resource_id} action={action} tenant={tenant_id}")

    def _resolve(active_conn) -> AccessDecision:
        nonlocal principal_ctx
        principal_ctx = _with_derived_memberships(active_conn, principal_ctx)
        targets = _principal_targets(principal_ctx)
        note(f"principal targets: {sorted(targets)}")
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

        admin = _admin_decision(principal_ctx, action, policy, notes)
        if admin is not None:
            return admin

        owner_denial = _owner_policy_denial(action, policy)
        if owner_denial and (
            resource_ref.owner_principal_type
            and resource_ref.owner_principal_id
            and (resource_ref.owner_principal_type, resource_ref.owner_principal_id) in targets
        ):
            note(owner_denial)
            return AccessDecision(False, "deny", owner_denial, [], [], _policy_dict(policy), notes)

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
        if action in {"read", "view"} and visibility == "public" and policy.public_sharing_enabled:
            return AccessDecision(True, "allow", "public visibility", [], [], _policy_dict(policy), notes)
        if action in {"read", "view"} and visibility == "tenant" and principal_ctx.tenant_id == tenant_id:
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
