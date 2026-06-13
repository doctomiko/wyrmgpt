
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from server.access_control import resolve_access
from server.api_helpers import RowDict, coerce_optional_int, load_json_object, normalize_scope_type, promote_targets_for_scope
from server.artifact_reading_planner import get_artifact_readiness
from server.db import (
    db_list_citation_scope_cards_for_project, 
    db_list_citation_scope_cards_for_conversation,
    # Supporting readers
    db_list_projects, db_get_conversation_title,
    db_list_conversations, db_get_conversation_project_id,
    # File reading helpers
    db_list_global_files,
    db_list_files_for_conversation,
    db_list_files_for_project,
    # Artifact reading helpers
    db_list_global_artifacts, 
    db_list_artifacts_for_conversation,
    db_list_artifacts_for_project,
    db_list_artifact_reading_sessions,
    db_replace_citations_for_message,
)

from server.db_helpers import db_session
from server.image_helpers import is_image_file
from server.logging_helper import log_warn
from server.routes.projects import get_project_title_any

from server.routes.base import app


# region Library helpers

def _pack_library_section(key: str, title: str, groups: list[RowDict]) -> RowDict:
    live_groups = [g for g in groups if g.get("items")]
    return {"key": key, "title": title, "groups": live_groups}


def _principal_label(row: RowDict, prefix: str) -> str | None:
    principal_type = (row.get(f"{prefix}_principal_type") or "").strip()
    principal_id = (row.get(f"{prefix}_principal_id") or "").strip()
    if not principal_type and not principal_id:
        return None
    if principal_type and principal_id:
        return f"{principal_type}:{principal_id}"
    return principal_id or principal_type


def _identity_summary(row: RowDict, resource_type: str) -> RowDict:
    tenant_id = (row.get("tenant_id") or "default").strip() or "default"
    owner = _principal_label(row, "owner")
    created_by = _principal_label(row, "created_by")
    source = _principal_label(row, "source")
    visibility = (row.get("visibility") or "").strip() or None
    sharing_mode = (row.get("sharing_mode") or "").strip() or None
    provenance_json = load_json_object(row.get("provenance_json"))
    return {
        "resource_type": resource_type,
        "tenant_id": tenant_id,
        "owner": owner,
        "created_by": created_by,
        "source": source,
        "visibility": visibility,
        "sharing_mode": sharing_mode,
        "provenance_json": provenance_json,
    }


def _append_identity_meta(meta: list[str], row: RowDict, resource_type: str) -> RowDict:
    identity = _identity_summary(row, resource_type)
    meta.append(f"Tenant: {identity['tenant_id']}")
    if identity.get("owner"):
        meta.append(f"Owner: {identity['owner']}")
    if identity.get("visibility"):
        meta.append(f"Visibility: {identity['visibility']}")
    if identity.get("sharing_mode"):
        meta.append(f"Sharing: {identity['sharing_mode']}")
    if identity.get("created_by"):
        meta.append(f"Created by: {identity['created_by']}")
    if identity.get("source"):
        meta.append(f"Source principal: {identity['source']}")
    return identity


def _library_principal(
    *,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
) -> RowDict:
    return {
        "principal_type": (principal_type or "user").strip() or "user",
        "principal_id": (principal_id or "local").strip() or "local",
        "tenant_id": (tenant_id or "default").strip() or "default",
    }


def _library_access_resource(row: RowDict, resource_type: str) -> RowDict:
    inherited_from: list[RowDict] = []
    scope_type = normalize_scope_type(row.get("scope_type"))
    if resource_type == "file":
        if scope_type == "project" and row.get("scope_id") is not None:
            inherited_from.append({"resource_type": "project", "resource_id": str(row.get("scope_id"))})
        if scope_type == "conversation" and row.get("scope_uuid"):
            inherited_from.append({"resource_type": "conversation", "resource_id": str(row.get("scope_uuid"))})
    elif resource_type == "artifact":
        source_kind = (row.get("source_kind") or "").strip()
        if source_kind.startswith("file") and row.get("source_id"):
            inherited_from.append({"resource_type": "file", "resource_id": str(row.get("source_id"))})
        elif scope_type == "project" and row.get("scope_id") is not None:
            inherited_from.append({"resource_type": "project", "resource_id": str(row.get("scope_id"))})
        elif scope_type == "conversation" and row.get("scope_uuid"):
            inherited_from.append({"resource_type": "conversation", "resource_id": str(row.get("scope_uuid"))})

    return {
        "resource_type": resource_type,
        "resource_id": str(row.get("id")),
        "tenant_id": (row.get("tenant_id") or "default").strip() or "default",
        "owner_principal_type": row.get("owner_principal_type"),
        "owner_principal_id": row.get("owner_principal_id"),
        "visibility": row.get("visibility") or "private",
        "inherited_from": inherited_from,
    }


def _visible_library_rows(
    rows: list[RowDict],
    resource_type: str,
    *,
    principal: RowDict,
    admin_view: bool,
) -> list[RowDict]:
    out: list[RowDict] = []
    with db_session() as conn:
        for row in rows:
            resource = _library_access_resource(row, resource_type)
            if not admin_view:
                owner_matches = (
                    resource.get("owner_principal_type") == principal["principal_type"]
                    and resource.get("owner_principal_id") == principal["principal_id"]
                )
                same_tenant = resource.get("tenant_id") == principal["tenant_id"]
                if owner_matches or (same_tenant and resource.get("visibility") in {"tenant", "public"}):
                    out.append(row)
                continue
            decision = resolve_access(principal, resource, "read", conn=conn)
            if decision.allowed:
                out.append(row)
    return out


def _make_session_library_item(session_row: RowDict, *, inherited_from: str, conversation_title: str | None = None) -> RowDict:
    meta = [
        f"Mode: {session_row.get('mode') or 'reading'}",
        f"Status: {session_row.get('status') or 'active'}",
        f"Artifact: {session_row.get('artifact_title') or session_row.get('artifact_id')}",
    ]
    if conversation_title:
        meta.append(f"Conversation: {conversation_title}")
    return {
        "item_kind": "reading_session",
        "id": str(session_row.get("id")),
        "title": session_row.get("artifact_title") or f"Session {session_row.get('id')}",
        "subtitle": "",
        "meta": meta,
        "scope_type": "conversation",
        "updated_at": session_row.get("updated_at"),
        "inherited_from": inherited_from,
        "badges": [session_row.get("status") or "active"],
        "promote_targets": [],
    }


def _make_artifact_library_item(
    artifact_row: RowDict,
    *,
    inherited_from: str,
    project_id: int | None = None,
    project_title: str | None = None,
    conversation_title: str | None = None,
) -> RowDict:
    scope_type = normalize_scope_type(artifact_row.get("scope_type"))
    source_kind = (artifact_row.get("source_kind") or "").strip()
    artifact_scope_id = coerce_optional_int(artifact_row.get("scope_id"))
    artifact_scope_uuid = (artifact_row.get("scope_uuid") or "").strip() or None
    effective_scope_label = conversation_title or project_title
    if not effective_scope_label and scope_type == "project":
        effective_scope_label = get_project_title_any(artifact_scope_id)
    if not effective_scope_label and scope_type == "conversation" and artifact_scope_uuid:
        effective_scope_label = db_get_conversation_title(artifact_scope_uuid)

    readiness = get_artifact_readiness(artifact_row["id"])
    badges: list[str] = []
    if readiness and readiness.has_summary:
        badges.append("summary")
    if readiness and readiness.has_index:
        badges.append("index")

    if source_kind in ("conversation:transcript", "conversation_transcript"):
        badges.append("reference-first transcript")

    meta: list[str] = [
        f"Source: {source_kind or 'artifact'}",
        f"Scope: {scope_type}",
    ]
    if scope_type == "project" and effective_scope_label:
        meta.append(f"Project: {effective_scope_label}")
    if scope_type == "conversation" and effective_scope_label:
        meta.append(f"Conversation: {effective_scope_label}")
    if conversation_title:
        meta.append(f"Conversation: {conversation_title}")
    if artifact_row.get("provenance"):
        meta.append(f"Provenance: {artifact_row.get('provenance')}")
    identity = _append_identity_meta(meta, artifact_row, "artifact")

    promote_targets: list[RowDict] = []
    promote_disabled_reason: str | None = None
    if source_kind == "file":
        promote_disabled_reason = "Promote the underlying file instead of the derived file artifact."
    else:
        promote_targets = promote_targets_for_scope(scope_type, project_id=project_id)

    return {
        "item_kind": "artifact",
        "id": artifact_row["id"],
        "title": artifact_row.get("title") or artifact_row["id"],
        "subtitle": "",
        "meta": meta,
        "scope_type": scope_type,
        "scope_label": effective_scope_label,
        "scope_id": artifact_row.get("scope_id"),
        "scope_uuid": artifact_row.get("scope_uuid"),
        "updated_at": artifact_row.get("updated_at"),
        "inherited_from": inherited_from,
        "badges": badges,
        "promote_targets": promote_targets,
        "promote_disabled_reason": promote_disabled_reason,
        "identity": identity,
        "sharing_resource_type": "artifact",
        "sharing_resource_id": artifact_row["id"],
    }


def _make_file_library_item(
    file_row: RowDict,
    *,
    inherited_from: str,
    project_id: int | None = None,
    project_title: str | None = None,
    conversation_title: str | None = None,
) -> RowDict:
    scope_type = normalize_scope_type(file_row.get("scope_type"))
    mime_type = (file_row.get("mime_type") or "").strip() or None
    file_path = Path(str(file_row.get("path") or "")).expanduser()
    is_image = bool(file_path and is_image_file(file_path, mime_type))
    file_meta: RowDict = load_json_object(file_row.get("meta_json"))

    import_note = (file_meta.get("import_note") or "").strip()
    image_caption = (file_meta.get("image_caption") or "").strip()
    image_ocr_text = (file_meta.get("image_ocr_text") or "").strip()
    file_scope_id = coerce_optional_int(file_row.get("scope_id"))

    effective_project_title = project_title
    if not effective_project_title and scope_type == "project" and file_scope_id is not None:
        proj = next((p for p in db_list_projects(include_global=True) if coerce_optional_int(p.get("id")) == file_scope_id), None)
        effective_project_title = proj.get("name") if proj else None

    effective_conversation_title = conversation_title
    if not effective_conversation_title and scope_type == "conversation" and file_row.get("scope_uuid"):
        effective_conversation_title = db_get_conversation_title(str(file_row.get("scope_uuid")))

    meta: list[str] = [f"MIME: {mime_type or 'unknown'}", f"Scope: {scope_type}"]
    if effective_project_title:
        meta.append(f"Project: {effective_project_title}")
    if effective_conversation_title:
        meta.append(f"Conversation: {effective_conversation_title}")
    if file_row.get("description"):
        meta.append(f"Description: {file_row.get('description')}")
    if image_caption:
        meta.append(f"Image summary: {image_caption}")
    if image_ocr_text:
        meta.append(f"OCR text: {image_ocr_text}")
    if import_note:
        meta.append(f"Import note: {import_note}")
    if file_row.get("provenance"):
        meta.append(f"Provenance: {file_row.get('provenance')}")
    identity = _append_identity_meta(meta, file_row, "file")

    badges: list[str] = []
    if is_image:
        badges.append("image")
    if image_caption:
        badges.append("captioned")
    if image_ocr_text:
        badges.append("ocr")

    return {
        "item_kind": "file",
        "id": file_row["id"],
        "title": file_row.get("name") or file_row["id"],
        "subtitle": file_row.get("description") or "",
        "description": file_row.get("description") or "",
        "meta": meta,
        "scope_type": scope_type,
        "scope_id": file_row.get("scope_id"),
        "scope_uuid": file_row.get("scope_uuid"),
        "scope_label": effective_conversation_title or effective_project_title,
        "updated_at": file_row.get("updated_at") or file_row.get("created_at"),
        "inherited_from": inherited_from,
        "badges": badges,
        "thumbnail_url": f"/api/files/{file_row['id']}/thumbnail" if is_image else None,
        "promote_targets": promote_targets_for_scope(scope_type, project_id=project_id),
        "meta_json": file_meta,
        "provenance": file_row.get("provenance"),
        "identity": identity,
        "sharing_resource_type": "file",
        "sharing_resource_id": file_row["id"],
    }

# endregion

# region Citation helpers

def _build_citation_rows_from_context(ctx: RowDict | None) -> list[RowDict]:
    if not ctx:
        return []

    retrieved_meta = ctx.get("retrieved_chunk_meta") or []
    if not retrieved_meta:
        return []

    rows_by_chunk_id: dict[int, RowDict] = {}
    for row in (ctx.get("retrieved_chunks_final") or []):
        chunk_id = row.get("chunk_id")
        if chunk_id is None:
            continue
        try:
            rows_by_chunk_id[int(chunk_id)] = row
        except Exception:
            continue

    citations: list[RowDict] = []
    for rank, meta in enumerate(retrieved_meta, start=1):
        chunk_id = meta.get("chunk_id")
        if chunk_id is None:
            continue

        try:
            chunk_id_int = int(chunk_id)
        except Exception:
            continue

        row = rows_by_chunk_id.get(chunk_id_int) or {}
        retrieval_channels = row.get("retrieval_channels") or []
        retrieval_channel = "+".join(
            str(ch).strip()
            for ch in retrieval_channels
            if str(ch).strip()
        ) or None

        citations.append({
            "corpus_chunk_id": chunk_id_int,
            "artifact_id": meta.get("artifact_id"),
            "source_kind": meta.get("source_kind"),
            "source_id": meta.get("source_id"),
            "retrieval_channel": retrieval_channel,
            "retrieval_rank": rank,
            "retrieval_score": meta.get("score"),
            "matched_text": meta.get("preview_text"),
        })

    return citations


def persist_citations_for_assistant_message(assistant_message_id: int, ctx: RowDict | None) -> None:
    if not assistant_message_id:
        return

    citations = _build_citation_rows_from_context(ctx)
    if not citations:
        return

    try:
        db_replace_citations_for_message(
            assistant_message_id=assistant_message_id,
            citations=citations,
        )
    except Exception as e:
        log_warn(f"Citation persistence failed for assistant message {assistant_message_id}: {e}")


# endregion

# region Library endpoints

@app.get("/api/conversation/{conversation_id}/library")
def api_conversation_library(
    conversation_id: str,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: bool = True,
):
    principal = _library_principal(principal_type=principal_type, principal_id=principal_id, tenant_id=tenant_id)
    conversation_title = db_get_conversation_title(conversation_id) or "Conversation"
    with db_session() as conn:
        project_id = db_get_conversation_project_id(conn=conn, conversation_id=conversation_id)

    project_label = None
    if project_id is not None:
        proj = next((p for p in db_list_projects(include_global=True) if int(p["id"]) == int(project_id)), None)
        project_label = proj.get("name") if proj else None

    files_groups = [
        {"key": "conversation", "title": "Conversation scope", "items": [_make_file_library_item(f, inherited_from="conversation", project_id=project_id, conversation_title=conversation_title) for f in _visible_library_rows(db_list_files_for_conversation(conversation_id), "file", principal=principal, admin_view=admin_view)]},
        {"key": "project", "title": "Inherited from project", "items": [_make_file_library_item(f, inherited_from="project", project_id=project_id, project_title=project_label) for f in _visible_library_rows((db_list_files_for_project(project_id) if project_id is not None else []), "file", principal=principal, admin_view=admin_view)]},
        {"key": "global", "title": "Inherited from global", "items": [_make_file_library_item(f, inherited_from="global", project_id=project_id) for f in _visible_library_rows(db_list_global_files(), "file", principal=principal, admin_view=admin_view)]},
    ]
    artifact_groups = [
        {"key": "conversation", "title": "Conversation scope", "items": [_make_artifact_library_item(a, inherited_from="conversation", project_id=project_id, conversation_title=conversation_title) for a in _visible_library_rows(db_list_artifacts_for_conversation(conversation_id), "artifact", principal=principal, admin_view=admin_view)]},
        {"key": "project", "title": "Inherited from project", "items": [_make_artifact_library_item(a, inherited_from="project", project_id=project_id, project_title=project_label) for a in _visible_library_rows((db_list_artifacts_for_project(project_id) if project_id is not None else []), "artifact", principal=principal, admin_view=admin_view)]},
        {"key": "global", "title": "Inherited from global", "items": [_make_artifact_library_item(a, inherited_from="global", project_id=project_id) for a in _visible_library_rows(db_list_global_artifacts(), "artifact", principal=principal, admin_view=admin_view)]},
    ]
    session_groups = [
        {"key": "conversation", "title": "Reading sessions in this conversation", "items": [_make_session_library_item(s, inherited_from="conversation") for s in db_list_artifact_reading_sessions(conversation_id=conversation_id, limit=200)]},
    ]
    return JSONResponse(
        {
            "scope_type": "conversation",
            "scope_id": conversation_id,
            "scope_label": conversation_title,
            "scope_note": "Showing items local to this conversation plus inherited project/global material. Reading plans are still derived live; reading-session state is durable and shown here.",
            "admin_view": admin_view,
            "sections": [
                _pack_library_section("files", "Files", files_groups),
                _pack_library_section("artifacts", "Artifacts", artifact_groups),
                _pack_library_section("reading_sessions", "Reading Sessions", session_groups),
            ],
        }
    )


@app.get("/api/projects/{project_id}/library")
def api_project_library(
    project_id: int,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: bool = True,
):
    principal = _library_principal(principal_type=principal_type, principal_id=principal_id, tenant_id=tenant_id)
    projects = db_list_projects(include_global=True)
    project = next((p for p in projects if int(p["id"]) == int(project_id)), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    convs = [c for c in db_list_conversations(limit=1000000, include_archived=True) if int(c["project_id"]) == int(project_id)]
    conv_title_by_id = {c["id"]: (c.get("title") or c["id"]) for c in convs}

    descendant_files: list[RowDict] = []
    seen_files: set[str] = set()
    descendant_artifacts: list[RowDict] = []
    seen_artifacts: set[str] = set()
    for conv in convs:
        for f in _visible_library_rows(db_list_files_for_conversation(conv["id"]), "file", principal=principal, admin_view=admin_view):
            if f["id"] in seen_files:
                continue
            seen_files.add(f["id"])
            descendant_files.append(_make_file_library_item(f, inherited_from="conversation", project_id=project_id, conversation_title=conv_title_by_id.get(conv["id"])))
        for a in _visible_library_rows(db_list_artifacts_for_conversation(conv["id"]), "artifact", principal=principal, admin_view=admin_view):
            scope_type = normalize_scope_type(a.get("scope_type"))
            if scope_type != "conversation":
                continue
            if a["id"] in seen_artifacts:
                continue
            seen_artifacts.add(a["id"])
            descendant_artifacts.append(_make_artifact_library_item(a, inherited_from="conversation", project_id=project_id, conversation_title=conv_title_by_id.get(conv["id"])))

    files_groups = [
        {"key": "project", "title": "Project scope", "items": [_make_file_library_item(f, inherited_from="project", project_id=project_id, project_title=(project.get("name") or f"Project {project_id}")) for f in _visible_library_rows(db_list_files_for_project(project_id), "file", principal=principal, admin_view=admin_view)]},
        {"key": "conversations", "title": "Conversation-scoped items in this project", "items": descendant_files},
        {"key": "global", "title": "Inherited from global", "items": [_make_file_library_item(f, inherited_from="global", project_id=project_id) for f in _visible_library_rows(db_list_global_files(), "file", principal=principal, admin_view=admin_view)]},
    ]
    artifact_groups = [
        {"key": "project", "title": "Project scope", "items": [_make_artifact_library_item(a, inherited_from="project", project_id=project_id, project_title=(project.get("name") or f"Project {project_id}")) for a in _visible_library_rows(db_list_artifacts_for_project(project_id), "artifact", principal=principal, admin_view=admin_view)]},
        {"key": "conversations", "title": "Conversation-scoped items in this project", "items": descendant_artifacts},
        {"key": "global", "title": "Inherited from global", "items": [_make_artifact_library_item(a, inherited_from="global", project_id=project_id) for a in _visible_library_rows(db_list_global_artifacts(), "artifact", principal=principal, admin_view=admin_view)]},
    ]
    session_groups = [
        {"key": "project_sessions", "title": "Reading sessions across this project", "items": [_make_session_library_item(s, inherited_from="conversation", conversation_title=conv_title_by_id.get(s.get("conversation_id"))) for s in db_list_artifact_reading_sessions(project_id=project_id, limit=500)]},
    ]
    return JSONResponse(
        {
            "scope_type": "project",
            "scope_id": int(project_id),
            "scope_label": project.get("name") or f"Project {project_id}",
            "scope_note": "Showing project-scoped items, conversation-scoped descendants, and inherited global material. Reading plans are still derived live; durable reading-session state is shown here.",
            "admin_view": admin_view,
            "sections": [
                _pack_library_section("files", "Files", files_groups),
                _pack_library_section("artifacts", "Artifacts", artifact_groups),
                _pack_library_section("reading_sessions", "Reading Sessions", session_groups),
            ],
        }
    )


@app.get("/api/library/global")
def api_global_library(
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: bool = True,
):
    principal = _library_principal(principal_type=principal_type, principal_id=principal_id, tenant_id=tenant_id)
    return JSONResponse(
        {
            "scope_type": "global",
            "scope_id": "global",
            "scope_label": "Global Library",
            "scope_note": "Showing globally scoped files and artifacts. Reading sessions remain conversation-bound, so there is no global session bucket.",
            "admin_view": admin_view,
            "sections": [
                _pack_library_section("files", "Files", [{"key": "global", "title": "Global scope", "items": [_make_file_library_item(f, inherited_from="global") for f in _visible_library_rows(db_list_global_files(), "file", principal=principal, admin_view=admin_view)]}]),
                _pack_library_section("artifacts", "Artifacts", [{"key": "global", "title": "Global scope", "items": [_make_artifact_library_item(a, inherited_from="global") for a in _visible_library_rows(db_list_global_artifacts(), "artifact", principal=principal, admin_view=admin_view)]}]),
                _pack_library_section("reading_sessions", "Reading Sessions", []),
            ],
        }
    )


# endregion

# region Citation endpoints

# These aren't strictly library functions, but they are libary adjacent.

@app.get("/api/projects/{project_id}/citations")
def api_project_citations(project_id: int):
    projects = db_list_projects(include_global=True)
    project = next((p for p in projects if int(p["id"]) == int(project_id)), None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")

    items = db_list_citation_scope_cards_for_project(project_id)
    return JSONResponse(
        {
            "scope_type": "project",
            "scope_id": int(project_id),
            "scope_label": project.get("name") or f"Project {project_id}",
            "items": items,
        }
    )


@app.get("/api/conversation/{conversation_id}/citations")
def api_conversation_citations(conversation_id: str):
    title = db_get_conversation_title(conversation_id)
    items = db_list_citation_scope_cards_for_conversation(conversation_id)
    return JSONResponse(
        {
            "scope_type": "conversation",
            "scope_id": conversation_id,
            "scope_label": title or conversation_id,
            "items": items,
        }
    )


# endregion
