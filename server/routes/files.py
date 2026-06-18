import hashlib
import mimetypes
import re
import uuid
from pathlib import Path
from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from typing import Any

from server.access_filtering import filter_rows_for_access, principal_from_request
from server.api_helpers import RowDict, coerce_optional_int, http_from_value_error, load_json_object, normalize_scope_type
from server.api_models import BulkFileDeleteRequest, BulkFileMoveScopeRequest, FileDescriptionUpdate, FileImageDescribeRequest, FileImageOcrRequest, FileMoveScopeRequest, FilePreflightRequest, FileRegister, FileRenameRequest
from server.db import (
    # Finders and getters
    db_find_same_scope_same_name_file, 
    db_list_files_by_sha256,
    db_list_files_for_conversation,
    db_list_files_for_project, 
    db_list_files_same_name_any_scope, 
    db_get_file_by_id, db_get_files_summary,    
    db_list_all_files, db_list_global_files,
    db_list_projects,
    # Other file CRUD
    db_register_file, db_register_scoped_file, 
    db_rename_file, db_replace_file_in_place, 
    db_move_file_scope, db_update_file_description, 
    db_set_file_image_caption, db_set_file_image_ocr_text,
    FileDeleteAction, db_delete_file_cascade, 
    # File artifact helpers
    db_list_artifacts_for_file, db_artifact_file, 
    # Helpers related to conversation based files
    db_conversation_link_file, 
    db_create_conversation_scaffold_event,
    db_get_conversation_title, 
    db_retain_conversation_artifact, 
    # Helpers related to project based files
    db_project_add_file, 
    db_invalidate_context_cache_for_conversation, 
    db_invalidate_context_cache_for_project, 
    # Related to RAG searches
    db_scope_rank,
    db_get_conversation_context,
)
from server.image_helpers import image_bytes_to_base64, is_image_file, load_image_bytes
from server.logging_helper import log_warn
from server.providers.openai_provider import ProviderExecutionError
from server.providers.registry import ProviderRegistry
from server.providers.types import ModelInput
from server.routes.projects import get_project_title_any
from server.routes.deployments import resolve_utility_target
from server.runtime import SOURCES_ROOT
from server import runtime

from server.routes.base import app

# region Misc. File helpers

def _create_upload_scaffold_event(
    *,
    conversation_id: str | None,
    scope_type: str,
    files: list[dict[str, Any]],
) -> None:
    cid = (conversation_id or "").strip()
    if not cid or not files:
        return

    scope_label = (scope_type or "global").strip().lower() or "global"
    body_lines = [f"Uploaded {len(files)} file(s) to {scope_label} scope.", ""]
    output_rows: list[dict[str, Any]] = []
    for row in files:
        name = (row.get("name") or row.get("original_name") or "(file)").strip()
        artifact_id = (row.get("artifact_id") or "").strip()
        source_kind = (row.get("source_kind") or "").strip()
        status_bits = []
        if artifact_id:
            status_bits.append(f"artifact_id={artifact_id}")
        if source_kind:
            status_bits.append(f"source_kind={source_kind}")
        suffix = f" [{' ; '.join(status_bits)}]" if status_bits else ""
        body_lines.append(f"- {name}{suffix}")
        output_rows.append({
            "file_id": row.get("id"),
            "name": name,
            "artifact_id": artifact_id or None,
            "source_kind": source_kind or None,
            "scope_type": scope_label,
        })

    db_create_conversation_scaffold_event(
        conversation_id=cid,
        message_id=None,
        event_kind="file_upload",
        title="File upload",
        body_text="\n".join(body_lines).strip(),
        input_json={"scope_type": scope_label, "file_count": len(files)},
        output_json={"files": output_rows},
        status="ok",
    )


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def strip_images(model_input: ModelInput) -> ModelInput:
    out = []
    for msg in model_input:
        c = msg.get("content")
        if isinstance(c, list):
            c = [p for p in c if isinstance(p, dict) and p.get("type") != "input_image"]
        out.append({**msg, "content": c})
    return out


def strip_file_messages(model_input: ModelInput) -> ModelInput:
    # Your file messages are user-role messages with big “FILES:” text or image parts.
    # Easiest heuristic: drop any message whose content includes "FILES:" header,
    # OR has any input_image part.
    out = []
    for msg in model_input:
        c = msg.get("content")
        if isinstance(c, str) and c.startswith("FILES:"):
            continue
        if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "input_image" for p in c):
            continue
        out.append(msg)
    return out


def _augment_file_row_for_ui(file_row: RowDict) -> RowDict:
    out = dict(file_row)
    scope_type = normalize_scope_type(out.get("scope_type"))
    scope_id = coerce_optional_int(out.get("scope_id"))
    scope_uuid = (out.get("scope_uuid") or "").strip() or None

    scope_label = None
    if scope_type == "project":
        scope_label = get_project_title_any(scope_id)
    elif scope_type == "conversation" and scope_uuid:
        scope_label = db_get_conversation_title(scope_uuid)

    if scope_label:
        out["scope_label"] = scope_label

    try:
        arts = db_list_artifacts_for_file(out["id"], include_deleted=False)
    except Exception:
        arts = []

    if arts:
        art = arts[0]
        out["artifact_id"] = art.get("id")
        out["artifact_title"] = art.get("title")
        out["artifact_source_kind"] = art.get("source_kind")
        out["artifact_updated_at"] = art.get("updated_at")
        out["artifact_summary_present"] = bool(art.get("summary_text"))
        out["artifact_index_present"] = bool(art.get("index_text"))

    return out

# endregion

# region Image Processing helpers - Descriptions and OCR

def _stored_file_path(file_row: RowDict) -> Path:
    return Path(str(file_row.get("path") or "")).expanduser()


def _safe_is_existing_file(path: Path, *, file_id: str | None = None) -> bool:
    try:
        return path.exists() and path.is_file()
    except OSError as e:
        log_warn(
            "Stored file path could not be stat'ed. file_id=%s path_prefix=%s errno=%s error_type=%s",
            file_id or "",
            str(path)[:500],
            getattr(e, "errno", ""),
            type(e).__name__,
        )
        return False


def _require_existing_file_path(file_row: RowDict, *, not_found_message: str = "File content not found on disk.") -> Path:
    path = _stored_file_path(file_row)
    if not _safe_is_existing_file(path, file_id=str(file_row.get("id") or "")):
        raise ValueError(not_found_message)
    return path


def _generate_image_caption_for_file(
    file_row: RowDict,
    *,
    deployment_id: str | None = None,
    providers: ProviderRegistry | None = None,
) -> tuple[str, str]:
    providers = providers or runtime.PROVIDER_REGISTRY
    mime_type = (file_row.get("mime_type") or "").strip() or None
    path = _require_existing_file_path(file_row, not_found_message="Image file content was not found on disk.")
    if not is_image_file(path, mime_type):
        raise ValueError("Only image files can be described.")

    def _fallback_caption() -> str:
        file_name = (file_row.get("name") or file_row.get("id") or "image").strip()
        hint_description = (file_row.get("description") or "").strip()
        if hint_description:
            return hint_description
        return f"Image file: {file_name}. Automatic visual summary was unavailable."

    data = load_image_bytes(path)
    if not data:
        raise ValueError("Image bytes could not be loaded.")

    mime_for_data_url = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data_url = f"data:{mime_for_data_url};base64,{image_bytes_to_base64(data)}"

    target = resolve_utility_target(
        deployment_id or "image_default",
        "summary_default",
        "chat_default",
        required_capability="chat",
    )
    if providers is None:
        raise RuntimeError("Provider registry is not initialized.")
    provider = providers.get_chat_provider(target)

    hint_description = (file_row.get("description") or "").strip()
    hint_text = (
        f"Existing file description (treat as a hint, not ground truth): {hint_description}\n\n"
        if hint_description else ""
    )

    model_input: ModelInput = [
        {
            "role": "system",
            "content": "You describe user-supplied images for retrieval and context assembly. Return only a compact factual description of what is visibly present. Mention notable text if it is clear and legible. Avoid speculation, named-entity guesses, or story-like flourishes.",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        f"File name: {file_row.get('name') or file_row.get('id') or 'image'}\n\n"
                        f"{hint_text}"
                        "Describe what is shown in this image in 2-4 concise sentences suitable for future LLM context."
                    ),
                },
                {"type": "input_image", "image_url": data_url},
            ],
        },
    ]
    result = provider.complete(target, model_input, request_options={"max_output_tokens": 220})
    raw_text = (result.text or "")
    caption = re.sub(r"\n{3,}", "\n\n", raw_text.strip())
    if not caption:
        log_warn(
            "Image description came back empty; using fallback. file_id=%s file_name=%s model=%s raw_len=%s",
            file_row.get("id"), file_row.get("name"), target.model, len(raw_text),
        )
        caption = _fallback_caption()
    return caption, target.model


def _generate_image_ocr_for_file(
    file_row: RowDict,
    *,
    deployment_id: str | None = None,
    providers: ProviderRegistry | None = None,
) -> tuple[str | None, str]:
    providers = providers or runtime.PROVIDER_REGISTRY
    mime_type = (file_row.get("mime_type") or "").strip() or None
    path = _require_existing_file_path(file_row, not_found_message="Image file content was not found on disk.")
    if not is_image_file(path, mime_type):
        raise ValueError("Only image files can be OCR'd.")

    def _fallback_ocr() -> tuple[str | None, str]:
        return None, target.model

    data = load_image_bytes(path)
    if not data:
        raise ValueError("Image bytes could not be loaded.")

    mime_for_data_url = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    data_url = f"data:{mime_for_data_url};base64,{image_bytes_to_base64(data)}"

    target = resolve_utility_target(
        deployment_id or "image_default",
        "summary_default",
        "chat_default",
        required_capability="chat",
    )
    if providers is None:
        raise RuntimeError("Provider registry is not initialized.")
    provider = providers.get_chat_provider(target)

    model_input: ModelInput = [
        {
            "role": "system",
            "content": (
                "You perform OCR on user-supplied images. Return only the visible text, with sensible line breaks. "
                "Do not summarize, explain, or guess. If there is no clearly legible text, return exactly: [no legible text]"
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        f"File name: {file_row.get('name') or file_row.get('id') or 'image'}\n\n"
                        "Read and transcribe any visible text in this image. Preserve line breaks where practical."
                    ),
                },
                {"type": "input_image", "image_url": data_url},
            ],
        },
    ]
    result = provider.complete(target, model_input, request_options={"max_output_tokens": 500})
    raw_text = (result.text or "")
    text = re.sub(r"\n{3,}", "\n\n", raw_text.strip())
    if not text:
        log_warn(
            "Image OCR came back empty. file_id=%s file_name=%s model=%s raw_len=%s",
            file_row.get("id"), file_row.get("name"), target.model, len(raw_text),
        )
        return _fallback_ocr()
    if text.strip().lower() == "[no legible text]":
        return None, target.model
    return text, target.model

# endregion

# region File Upload Endpoints

@app.post("/api/files/preflight_upload")
def api_preflight_upload(req: FilePreflightRequest):
    out = []

    for item in req.files:
        dupes = db_list_files_by_sha256(item.sha256, include_deleted=False)
        same_name = db_list_files_same_name_any_scope(item.name, include_deleted=False)

        out.append({
            "name": item.name,
            "sha256": item.sha256,
            "duplicate_count": len(dupes),
            "duplicates": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "scope_type": f.get("scope_type"),
                    "scope_id": f.get("scope_id"),
                    "scope_uuid": f.get("scope_uuid"),
                    "path": f.get("path"),
                }
                for f in dupes
            ],
            "same_name_count": len(same_name),
            "same_name_conflicts": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "scope_type": f.get("scope_type"),
                    "scope_id": f.get("scope_id"),
                    "scope_uuid": f.get("scope_uuid"),
                    "sha256": f.get("sha256"),
                    "same_hash": (f.get("sha256") or "").lower() == item.sha256.lower(),
                }
                for f in same_name
            ],            
        })

    return JSONResponse({"files": out})


@app.post("/api/upload_file")
async def api_upload_file(
    scope_type: str,
    conversation_id: str | None = None,
    project_id: int | None = None,
    files: list[UploadFile] = File(...),
):
    """
    Handle file uploads and register them with scoped metadata.

    scope_type: conversation / project / global
    conversation_id: required for conversation scope
    project_id: required for project scope
    """
    scope_type_norm = (scope_type or "").strip().lower()
    if not scope_type_norm:
        raise HTTPException(status_code=400, detail="scope_type is required")
    if scope_type_norm not in ("conversation", "project", "global"):
        raise HTTPException(status_code=400, detail=f"Invalid scope_type: {scope_type}")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    conv_id = (conversation_id or "").strip() or None
    proj_id = None
    if project_id not in (None, ""):
        try:
            proj_id = int(project_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="project_id must be an integer")

    if scope_type_norm == "conversation" and not conv_id:
        raise HTTPException(
            status_code=400,
            detail="conversation_id is required for conversation scope",
        )
    if scope_type_norm == "project" and proj_id is None:
        raise HTTPException(
            status_code=400,
            detail="project_id is required for project scope",
        )

    base_sources = SOURCES_ROOT
    if scope_type_norm == "conversation":
        dest_root = base_sources / "chats" / (conv_id or "unknown_conversation")
    elif scope_type_norm == "project":
        dest_root = base_sources / "projects" / str(proj_id or "unknown_project")
    else:
        dest_root = base_sources / "global"

    dest_root.mkdir(parents=True, exist_ok=True)

    results: list[RowDict] = []

    for upload in files:
        if not upload.filename:
            continue
        orig_name = Path(upload.filename).name

        final_path = dest_root / orig_name
        temp_path = dest_root / f".{orig_name}.uploading.{uuid.uuid4().hex}.tmp"

        # stream upload to TEMP file first
        with temp_path.open("wb") as out_f:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                out_f.write(chunk)
        await upload.close()

        file_sha256 = _sha256_file(temp_path)

        existing_same_scope = db_find_same_scope_same_name_file(
            name=orig_name,
            scope_type=scope_type_norm,
            scope_id=proj_id if scope_type_norm == "project" else None,
            scope_uuid=conv_id if scope_type_norm == "conversation" else None,
            include_deleted=False,
        )

        same_name_any_scope = db_list_files_same_name_any_scope(orig_name, include_deleted=False)
        higher_scope_same_hash = None
        for f in same_name_any_scope:
            if (f.get("sha256") or "").lower() != file_sha256.lower():
                continue
            if db_scope_rank(scope_type_norm) > db_scope_rank(f.get("scope_type")):
                higher_scope_same_hash = f
                break
        if higher_scope_same_hash:
            db_delete_file_cascade(higher_scope_same_hash["id"])        

        if existing_same_scope:
            #old_path = Path(existing_same_scope["path"])

            # safer replacement: move old canonical aside first, then swap temp into place
            backup_old = None
            if final_path.exists():
                backup_old = final_path.with_name(f".{final_path.name}.replaced.{uuid.uuid4().hex}.bak")
                final_path.replace(backup_old)

            try:
                temp_path.replace(final_path)
            except Exception:
                # rollback: restore original file if replacement failed
                if backup_old and backup_old.exists():
                    try:
                        backup_old.replace(final_path)
                    except Exception:
                        pass
                raise
            else:
                # replacement succeeded; remove old backup
                if backup_old and backup_old.exists():
                    try:
                        backup_old.unlink()
                    except Exception:
                        pass
            file_row = db_replace_file_in_place(
                existing_same_scope["id"],
                path=str(final_path),
                mime_type=upload.content_type,
                sha256=file_sha256,
            )
            fid = file_row["id"]

            # keep scope links alive / idempotent
            if scope_type_norm == "conversation" and conv_id:
                db_conversation_link_file(conv_id, fid)
                db_invalidate_context_cache_for_conversation(conv_id)
            elif scope_type_norm == "project" and proj_id is not None:
                db_project_add_file(proj_id, fid)
                db_invalidate_context_cache_for_project(proj_id)

            # re-artifact / reindex through normal path
            artifact_id = db_artifact_file(file_row)
            try:
                file_row["artifact_id"] = artifact_id
                arts = db_list_artifacts_for_file(fid, include_deleted=False)
                if arts:
                    file_row["source_kind"] = arts[0].get("source_kind")
            except Exception:
                pass
        else:
            if final_path.exists():
                # if some stray file exists on disk but no live DB row owns it, keep temp unique
                final_path = dest_root / f"{final_path.stem}.{uuid.uuid4().hex}{final_path.suffix}"

            temp_path.replace(final_path)

            file_row = db_register_scoped_file(
                name=orig_name,
                path=str(final_path),
                mime_type=upload.content_type,
                sha256=file_sha256,
                scope_type=scope_type_norm,
                scope_id=proj_id if scope_type_norm == "project" else None,
                scope_uuid=conv_id if scope_type_norm == "conversation" else None,
                source_kind="upload",
                url=None,
                provenance=f"upload:{scope_type_norm}",
            )
            fid = file_row["id"]

            if scope_type_norm == "conversation" and conv_id:
                db_conversation_link_file(conv_id, fid)
                db_invalidate_context_cache_for_conversation(conv_id)
            elif scope_type_norm == "project" and proj_id is not None:
                db_project_add_file(proj_id, fid)
                db_invalidate_context_cache_for_project(proj_id)
            artifact_id = db_artifact_file(file_row)
            try:
                file_row["artifact_id"] = artifact_id
                arts = db_list_artifacts_for_file(fid, include_deleted=False)
                if arts:
                    file_row["source_kind"] = arts[0].get("source_kind")
            except Exception:
                pass

        # stream the file to disk
        results.append({
            "id": fid,
            "name": orig_name,
            "path": str(final_path),
            "artifact_id": file_row.get("artifact_id"),
            "source_kind": file_row.get("source_kind"),
            "scope_type": scope_type_norm,
        })

        if conv_id and file_row.get("artifact_id"):
            try:
                db_retain_conversation_artifact(
                    conversation_id=conv_id,
                    artifact_id=str(file_row.get("artifact_id") or "").strip(),
                    origin_kind="file_upload",
                    retention_state="forced",
                    carry_summary_text=None,
                    inclusion_kind="whole",
                    retrieval_channel="upload",
                    message_id=None,
                    note_text="Uploaded file retained for conversation continuity",
                    meta_json={"file_id": fid, "scope_type": scope_type_norm},
                    increment_include_count=False,
                )
            except Exception as exc:
                print(f"[upload] failed to retain uploaded artifact {file_row.get('artifact_id')}: {exc}")

    if conv_id and results:
        _create_upload_scaffold_event(
            conversation_id=conv_id,
            scope_type=scope_type_norm,
            files=results,
        )

    return {"files": results}

# endregion

# region File Endpoints

@app.get("/api/files")
def api_list_files(
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    """
    List all non-deleted files in the system.
    Used by the top-level Manage Files button for the 'all' view.
    """
    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    rows = filter_rows_for_access(db_list_all_files(), "file", principal=principal)
    files = [_augment_file_row_for_ui(f) for f in rows]
    return JSONResponse({"files": files})


@app.get("/api/files/global")
def api_list_global_files(
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    rows = filter_rows_for_access(db_list_global_files(), "file", principal=principal)
    files = [_augment_file_row_for_ui(f) for f in rows]
    return JSONResponse({"files": files})


@app.get("/api/files/{file_id}/thumbnail")
def api_file_thumbnail(file_id: str):
    try:
        file_row = db_get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = _stored_file_path(file_row)
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not _safe_is_existing_file(path, file_id=file_id):
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files support thumbnail preview.")

    media_type = mime_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.get("/api/files/summary")
def api_files_summary():
    """
    Return counts of files by scope, plus total.
    Used to enable/disable Manage Files buttons.
    """
    summary = db_get_files_summary()
    return JSONResponse(summary)


@app.post("/api/files/{file_id}/description")
def api_update_file_description(file_id: str, body: FileDescriptionUpdate):
    try:
        db_update_file_description(file_id, body.description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse(
        {
            "id": file_id,
            "description": body.description or "",
        }
    )


@app.post("/api/files/{file_id}/rename")
def api_rename_file(file_id: str, body: FileRenameRequest):
    try:
        out = db_rename_file(file_id, body.name)
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/files/{file_id}/describe_image")
def api_describe_image_file(file_id: str, body: FileImageDescribeRequest | None = None):
    try:
        file_row = db_get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = _stored_file_path(file_row)
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not _safe_is_existing_file(path, file_id=file_id):
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files can be described.")

    try:
        meta = load_json_object(file_row.get("meta_json"))
        existing_caption = (meta.get("image_caption") or "").strip()
        if existing_caption and not (body.overwrite if body is not None else True):
            return JSONResponse({
                "file_id": file_id,
                "caption": existing_caption,
                "model": meta.get("image_caption_model"),
                "reused": True,
            })

        caption, model_name = _generate_image_caption_for_file(
            file_row,
            deployment_id=(body.deployment_id if body is not None else None),
        )
        updated = db_set_file_image_caption(
            file_id,
            caption,
            caption_model=model_name,
            generator_kind="llm_image_caption",
        )
        return JSONResponse({"file_id": file_id, "caption": caption, "model": model_name, "file": updated})
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProviderExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/files/{file_id}/ocr_image")
def api_ocr_image_file(file_id: str, body: FileImageOcrRequest | None = None):
    try:
        file_row = db_get_file_by_id(file_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    path = _stored_file_path(file_row)
    mime_type = (file_row.get("mime_type") or "").strip() or None
    if not _safe_is_existing_file(path, file_id=file_id):
        raise HTTPException(status_code=404, detail="File content not found on disk.")
    if not is_image_file(path, mime_type):
        raise HTTPException(status_code=400, detail="Only image files can be OCR'd.")

    try:
        meta = load_json_object(file_row.get("meta_json"))
        existing_ocr_text = (meta.get("image_ocr_text") or "").strip()
        if existing_ocr_text and not (body.overwrite if body is not None else True):
            return JSONResponse({
                "file_id": file_id,
                "ocr_text": existing_ocr_text,
                "model": meta.get("image_ocr_model"),
                "reused": True,
            })

        ocr_text, model_name = _generate_image_ocr_for_file(
            file_row,
            deployment_id=(body.deployment_id if body is not None else None),
        )
        updated = db_set_file_image_ocr_text(
            file_id,
            ocr_text,
            ocr_model=model_name,
            generator_kind="llm_image_ocr",
        )
        return JSONResponse({"file_id": file_id, "ocr_text": ocr_text, "model": model_name, "file": updated})
    except (ValueError, RuntimeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ProviderExecutionError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/files/{file_id}/move_scope")
def api_move_file_scope(file_id: str, body: FileMoveScopeRequest):
    try:
        out = db_move_file_scope(
            file_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            scope_uuid=body.scope_uuid,
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/files/bulk_move_scope")
def api_bulk_move_file_scope(body: BulkFileMoveScopeRequest):
    file_ids = []
    seen = set()
    for raw in body.file_ids or []:
        fid = str(raw or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            file_ids.append(fid)

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids is required.")

    results = []
    moved = 0
    failed = 0
    for fid in file_ids:
        try:
            out = db_move_file_scope(
                fid,
                scope_type=body.scope_type,
                scope_id=body.scope_id,
                scope_uuid=body.scope_uuid,
            )
            results.append({"id": fid, "ok": True, "result": out})
            moved += 1
        except ValueError as e:
            results.append({"id": fid, "ok": False, "error": str(e)})
            failed += 1

    return JSONResponse({"moved": moved, "failed": failed, "results": results})


@app.post("/api/files/bulk_delete")
def api_bulk_delete_files(body: BulkFileDeleteRequest):
    file_ids = []
    seen = set()
    for raw in body.file_ids or []:
        fid = str(raw or "").strip()
        if fid and fid not in seen:
            seen.add(fid)
            file_ids.append(fid)

    if not file_ids:
        raise HTTPException(status_code=400, detail="file_ids is required.")

    results = []
    deleted = 0
    failed = 0
    for fid in file_ids:
        try:
            out = db_delete_file_cascade(fid, delete_disk_action=FileDeleteAction.MOVE)
            results.append({"id": fid, "ok": True, "result": out})
            deleted += 1
        except ValueError as e:
            results.append({"id": fid, "ok": False, "error": str(e)})
            failed += 1

    return JSONResponse({"deleted": deleted, "failed": failed, "results": results})


@app.post("/api/files")
def api_register_file(req: FileRegister):
    try:
        out = db_register_file(req.name, req.path, req.mime_type)
        return JSONResponse(out)
    except ValueError as e:
        http_from_value_error(e)


@app.delete("/api/files/{file_id}")
def api_delete_file(file_id: str):
    try:
        out = db_delete_file_cascade(
            file_id,
            delete_disk_action=FileDeleteAction.MOVE
        )
        return JSONResponse(out)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# endregion

# region File Endpoints for Conversations and Projects

@app.post("/api/conversations/{conversation_id}/files/upload")
async def api_upload_conversation_file(conversation_id: str, file: UploadFile = File(...)):
    """
    Upload a file scoped to a conversation.

    - Stored under DATA_DIR / "sources" / "chats" / {conversation_id} / {filename}
    - Registered in files with scope_type="chat", scope_uuid={conversation_id}
    - Linked to the conversation (conversation_files)
    - Linked to the project via project_files if the conversation has a project_id
    - Invalidates the context cache for this conversation
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    # Ensure conversation exists and grab its project
    try:
        ctx = db_get_conversation_context(conversation_id, preview_limit=0)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found")

    project_id = ctx.get("project_id")

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Uploaded file must have a name")

    # Target path on disk
    chat_root = SOURCES_ROOT / "chats" / conversation_id
    chat_root.mkdir(parents=True, exist_ok=True)
    dest_path = chat_root / file.filename

    # Stream upload to disk
    try:
        with dest_path.open("wb") as out_f:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                out_f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    # Register and link
    try:
        file_row = db_register_scoped_file(
            name=file.filename,
            path=str(dest_path),
            mime_type=file.content_type,
            scope_type="conversation",
            scope_id=None,
            scope_uuid=conversation_id,
            source_kind="upload",
            url=None,
            provenance=f"uploaded via chat {conversation_id}",
        )
        file_id = file_row["id"]

        db_conversation_link_file(conversation_id, file_id)
        if project_id is not None:
            db_project_add_file(project_id, file_id)

        artifact_id = db_artifact_file(file_row)
        source_kind = None
        try:
            arts = db_list_artifacts_for_file(file_id, include_deleted=False)
            if arts:
                source_kind = arts[0].get("source_kind")
        except Exception:
            pass

        try:
            db_retain_conversation_artifact(
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                origin_kind="file_upload",
                retention_state="forced",
                carry_summary_text=None,
                inclusion_kind="whole",
                retrieval_channel="upload",
                message_id=None,
                note_text="Uploaded file retained for conversation continuity",
                meta_json={"file_id": file_id, "scope_type": "conversation"},
                increment_include_count=False,
            )
        except Exception as exc:
            print(f"[upload] failed to retain uploaded artifact {artifact_id}: {exc}")

        _create_upload_scaffold_event(
            conversation_id=conversation_id,
            scope_type="conversation",
            files=[{
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "artifact_id": artifact_id,
                "source_kind": source_kind,
            }],
        )

        db_invalidate_context_cache_for_conversation(conversation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register upload: {e}")

    return JSONResponse(
        {
            "conversation_id": conversation_id,
            "project_id": project_id,
            "file": {
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "mime_type": file.content_type,
            },
        }
    )

@app.get("/api/conversations/{conversation_id}/files")
def api_list_conversation_files(
    conversation_id: str,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    """
    List files attached to a conversation via conversation_files.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise HTTPException(status_code=400, detail="conversation_id is required")

    try:
        principal = principal_from_request(
            principal_type=principal_type,
            principal_id=principal_id,
            tenant_id=tenant_id,
            admin_view=admin_view,
        )
        files = filter_rows_for_access(
            db_list_files_for_conversation(conversation_id),
            "file",
            principal=principal,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({"conversation_id": conversation_id, "files": files})

@app.post("/api/projects/{project_id}/files/upload")
async def api_upload_project_file(project_id: int, file: UploadFile = File(...)):
    """
    Upload a file scoped to a project.

    - Stored under DATA_DIR / "sources" / "projects" / {project_id} / {filename}
    - Registered in files with scope_type="project", scope_id={project_id}
    - Linked to the project via project_files
    - Invalidates context cache for all conversations in this project
    """
    # Make sure the project exists
    projects = db_list_projects()
    if not any(int(p["id"]) == int(project_id) for p in projects):
        raise HTTPException(status_code=404, detail="Project not found")

    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Uploaded file must have a name")

    proj_root = SOURCES_ROOT / "projects" / str(project_id)
    proj_root.mkdir(parents=True, exist_ok=True)
    dest_path = proj_root / file.filename

    # Stream upload to disk
    try:
        with dest_path.open("wb") as out_f:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                out_f.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store upload: {e}")

    # Register and link
    try:
        file_row = db_register_scoped_file(
            name=file.filename,
            path=str(dest_path),
            mime_type=file.content_type,
            scope_type="project",
            scope_id=int(project_id),
            scope_uuid=None,
            source_kind="upload",
            url=None,
            provenance=f"uploaded via project {project_id}",
        )
        file_id = file_row["id"]

        db_project_add_file(project_id, file_id)

        db_invalidate_context_cache_for_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register upload: {e}")

    return JSONResponse(
        {
            "project_id": project_id,
            "file": {
                "id": file_id,
                "name": file.filename,
                "path": str(dest_path),
                "mime_type": file.content_type,
            },
        }
    )

@app.get("/api/projects/{project_id}/files")
def api_list_project_files(
    project_id: int,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    """
    List files attached to a project via project_files.
    """
    try:
        principal = principal_from_request(
            principal_type=principal_type,
            principal_id=principal_id,
            tenant_id=tenant_id,
            admin_view=admin_view,
        )
        files = filter_rows_for_access(
            db_list_files_for_project(project_id),
            "file",
            principal=principal,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return JSONResponse({"project_id": project_id, "files": files})

# endregion
