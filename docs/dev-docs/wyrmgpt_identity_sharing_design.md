# WyrmGPT Identity, Sharing, and Access Control Design

## 1. Purpose

WyrmGPT is currently a local-first, mostly single-user application. The next schema stream adds the durable model needed for identity ownership, resource sharing, access checks, tenant policy, and auditability without turning the app into a SaaS control plane.

This document is the design anchor for issues #3 through #12. Implementation should stay incremental: add schema and helpers first, preserve current single-user behavior by default, then route resource-specific behavior through the shared resolver.

## 2. Design Goals

- Preserve existing local, single-user behavior when no explicit identity or policy is configured.
- Make ownership and provenance explicit on shareable resources.
- Support allow and deny access-control entries with deterministic precedence.
- Add tenant-scoped groups and roles without requiring multi-tenant hosting.
- Centralize policy and effective-access resolution so routes do not duplicate authorization logic.
- Record audit events for security-relevant decisions and mutations.
- Keep diagnostics explainable for UI and API consumers.

## 3. Core Concepts

### Tenant

A tenant is a policy and identity namespace. The default deployment should create or assume a `default` tenant. Tenant IDs should be stable text identifiers so imports, connectors, and future deployments can map external identity namespaces without relying on local integer IDs.

### Principal

A principal is the actor being evaluated. Principal kinds should include:

- `user`
- `persona`
- `service`
- `group`
- `role`
- `public`

The resolver should accept a principal context that includes the direct user or persona plus derived group and role memberships.

### Resource

A resource is anything that can be owned, shared, or inherited into context. Initial shareable resource types are:

- `conversation`
- `message`
- `memory`
- `file`
- `artifact`
- `project`

Resource IDs should be stored as text in generic access tables so integer and UUID primary keys can coexist.

### Owner

The owner is the principal with default administrative control of a resource. A resource may also have a tenant owner or project owner for inherited policy, but a single explicit `owner_principal_type` and `owner_principal_id` should be present on resources that can be shared directly.

### Provenance

Provenance records where a resource came from and who or what created it. Provenance should be queryable enough for diagnostics and audit trails, not just human prose.

Recommended fields on shareable resources:

- `tenant_id`
- `owner_principal_type`
- `owner_principal_id`
- `created_by_principal_type`
- `created_by_principal_id`
- `source_principal_type`
- `source_principal_id`
- `visibility`
- `sharing_mode`
- `provenance_json`

## 4. Access-Control Entries

Use a generic `access_control_entries` table for direct grants and denials.

Recommended shape:

- `id TEXT PRIMARY KEY`
- `tenant_id TEXT NOT NULL`
- `resource_type TEXT NOT NULL`
- `resource_id TEXT NOT NULL`
- `principal_type TEXT NOT NULL`
- `principal_id TEXT NOT NULL`
- `effect TEXT NOT NULL` with `allow` or `deny`
- `action TEXT NOT NULL` such as `read`, `write`, `share`, `admin`, `delete`, `audit`
- `scope TEXT NOT NULL DEFAULT 'resource'`
- `inherited_from_type TEXT`
- `inherited_from_id TEXT`
- `reason TEXT`
- `created_by_principal_type TEXT`
- `created_by_principal_id TEXT`
- `created_at TEXT NOT NULL`
- `expires_at TEXT`
- `is_deleted INTEGER NOT NULL DEFAULT 0`

Indexes should support lookup by resource, principal, tenant, and `(resource_type, resource_id, action)`.

## 5. Precedence Rules

Access resolution should be deterministic and explainable.

Recommended order:

1. Tenant policy hard deny.
2. Explicit resource deny for the principal, role, group, or public principal.
3. Owner administrative access.
4. Explicit resource allow for the principal, role, group, or public principal.
5. Inherited deny from project, conversation, or parent resource.
6. Inherited allow from project, conversation, or parent resource.
7. Resource visibility fallback.
8. Tenant policy default.

Deny should win over allow at the same or broader level unless tenant policy explicitly defines a narrower exception model later. Expired and soft-deleted entries do not participate.

## 6. Groups and Roles

Groups and roles are tenant-scoped.

Recommended tables:

- `identity_groups`
- `identity_group_members`
- `identity_roles`
- `identity_role_assignments`

Groups represent membership sets. Roles represent policy capabilities. A group may receive role assignments, and a user or persona may receive roles directly. Membership records should be soft-deletable and auditable.

## 7. Tenant Policy

Tenant policy should be loaded from TOML defaults, then resolved through a small policy API.

Initial policy keys:

- default tenant ID
- default visibility for new conversations, memories, files, artifacts, and projects
- whether public sharing is enabled
- whether persona-created resources are owned by the persona, the active user, or the tenant
- default action for missing access entries: allow local owner only, allow tenant members, or deny
- audit verbosity: off, mutations, decisions, or verbose

Configuration should be additive. Missing policy files must not break local startup.

## 8. Audit Events

Audit logging should be append-only for security-relevant events.

Recommended `audit_events` shape:

- `id TEXT PRIMARY KEY`
- `tenant_id TEXT NOT NULL`
- `event_type TEXT NOT NULL`
- `actor_principal_type TEXT`
- `actor_principal_id TEXT`
- `resource_type TEXT`
- `resource_id TEXT`
- `action TEXT`
- `decision TEXT`
- `reason TEXT`
- `request_id TEXT`
- `source_ip TEXT`
- `user_agent TEXT`
- `metadata_json TEXT`
- `created_at TEXT NOT NULL`

Helpers should make logging cheap and safe: failures to write low-risk audit events should not crash normal local operation, but schema failures during startup should still be visible.

## 9. Central Access Resolver

The resolver should expose one backend function that route and DB helpers can call:

```python
resolve_access(principal, resource, action, *, explain=False) -> AccessDecision
```

`AccessDecision` should include:

- `allowed: bool`
- `effect: "allow" | "deny"`
- `reason: str`
- `matched_entries: list[dict]`
- `inherited_from: list[dict]`
- `policy: dict`
- `explain: list[str]`

The first implementation can live near DB access helpers, but route code should only depend on the public resolver API.

## 10. Resource Inheritance

Initial inheritance rules:

- Messages inherit from their conversation.
- Conversation artifacts inherit from their conversation unless explicitly overridden.
- Project conversations, files, artifacts, and memories inherit from their project.
- File-derived artifacts inherit from the source file.
- Memories may be persona-scoped, project-scoped, conversation-scoped, global, or directly shared.

Resource tables should keep enough owner and provenance fields to explain why a resource appears in context.

## 11. Diagnostics API and UI

Diagnostics should answer: who can see this, why, and where did the access come from?

API output should include the effective decision, owner fields, visibility, direct ACEs, inherited ACEs, group and role membership used, tenant policy defaults, and audit event references when available.

The UI should present this as a compact inspection panel for a selected conversation, memory, file, artifact, or project. It should not require users to understand table internals.

## 12. Issue Mapping

- #3 adds `audit_events` schema and audit logging helpers.
- #4 adds owner and provenance fields to shareable resources.
- #5 adds generic access-control entries.
- #6 adds tenant-scoped groups and roles.
- #7 adds TOML policy defaults and resolver hooks.
- #8 adds the central access resolver with explain output.
- #9 updates conversations and messages for ownership, persona identity, and inherited access.
- #10 updates memories for persona assignment and persona-context access.
- #11 updates files, artifacts, and projects for inherited sharing and ownership metadata.
- #12 adds effective sharing diagnostics API and UI.

## 13. Compatibility Notes

Existing data should migrate into tenant `default` with owner fields unset or assigned to a local default principal. The resolver must treat legacy rows without owner fields as accessible under current single-user behavior until stricter policy is explicitly configured.

No migration in this stream should delete user data or require external identity services.
