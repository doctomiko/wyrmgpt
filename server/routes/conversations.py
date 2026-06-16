# region Conversation Endpoints

import re
from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse

from server.access_filtering import filter_rows_for_access, principal_from_request
from server.api_helpers import http_from_value_error, postprocess_text
from server.api_models import ArchiveRequest, MoveProjectRequest, TitleRequest
from server.config import ContextConfig, SummaryConfig, get_prompt, load_context_config, load_summary_config
from server.context import build_context_panel_payload
from server.db import db_add_message, db_get_conversation_title, db_get_or_create_project, db_get_transcript_for_summary, db_export_conversation_transcript_markdown, db_list_conversations, db_refresh_conversation_transcript_artifact, db_save_conversation_summary_artifact, db_delete_conversation, db_set_conversation_archived, db_set_conversation_project, db_get_messages_raw, db_list_conversation_history_with_scaffold_events, db_get_messages, update_conversation_title
from server.routes.deployments import make_utility_completion
from server.summary_helper import suggest_conversation_title_from_transcript, summarize_conversation_text

from server.runtime import TOOL_CFG, CORE_CFG as core_cfg

from server.routes.base import app


@app.get("/api/conversations")
def api_conversations(
    include_archived: bool = False,
    limit: int = core_cfg.limit_api_conversations,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    rows = db_list_conversations(
        limit=limit,
        include_archived=include_archived)
    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    return JSONResponse(filter_rows_for_access(rows, "conversation", principal=principal))

@app.get("/api/conversation/{conversation_id}/messages")
def api_conversation_messages(
    conversation_id: str,
    limit: int = core_cfg.limit_api_conversation_messages,
    mode: str = "raw",   # "raw" | "thread" | "canonical"
):
    """
    app.js calls this as: GET /api/conversation/{cid}/messages

    mode=raw       -> returns rows with meta (A/B grouping, timestamps, etc.)
    mode=canonical -> returns condensed role/content list (A/B canonical only)
    """
    if mode == "canonical":
        return JSONResponse(db_get_messages(conversation_id, limit=limit))
    if mode == "thread":
        return JSONResponse(db_list_conversation_history_with_scaffold_events(conversation_id))
    return JSONResponse(db_get_messages_raw(conversation_id, limit=limit))

@app.post("/api/conversations/{conversation_id}/project")
def api_move_conversation_project(conversation_id: str, req: MoveProjectRequest):
    project_id: int | None = None

    if req.project_id is not None:
        project_id = req.project_id
    elif req.project_name:
        proj = db_get_or_create_project(req.project_name)
        project_id = int(proj["id"])

    db_set_conversation_project(conversation_id, project_id)
    return {"conversation_id": conversation_id, "project_id": project_id}

@app.post("/api/conversations/{conversation_id}/archive")
def api_archive_conversation(conversation_id: str, req: ArchiveRequest):
    db_set_conversation_archived(conversation_id, req.archived)
    return {"conversation_id": conversation_id, "archived": req.archived}

@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: str):
    db_delete_conversation(conversation_id)
    return {"deleted": True, "conversation_id": conversation_id}

# endregion

# region Conversation Title and Summary Endpoints

@app.put("/api/conversation/{conversation_id}/title")
def api_set_title(conversation_id: str, req: TitleRequest):
    """
    app.js calls this as: PUT /api/conversation/{cid}/title { "title": "..." }
    """
    title = (req.title or "").strip() or "New chat"
    updated = update_conversation_title(conversation_id, title)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return JSONResponse({"ok": True, "title": title})


# Optional but handy for debugging / sanity:
@app.get("/api/conversation/{conversation_id}/title")
def api_get_title(conversation_id: str):
    t = db_get_conversation_title(conversation_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return JSONResponse({"title": t})


@app.post("/api/conversations/{conversation_id}/summarize")
def api_summarize_conversation(
    conversation_id: str, 
):
    #sum_cfg: SummaryConfig | None = None
    sum_cfg = load_summary_config()

    try:
        title, transcript = db_get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    system_prompt = get_prompt(
        default_prompt=sum_cfg.summary_conversation_prompt,
        filepath=sum_cfg.summary_conversation_prompt_file,
        cfg_default="SUMMARY_CONVO_PROMPT",
        cfg_filepath="SUMMARY_CONVO_PROMPT_FILE",
    )

    try:
        complete_fn, target = make_utility_completion(
            "summary_default",
        )

        summary_text = summarize_conversation_text(
            model=target.model,
            title=title,
            transcript=transcript,
            cfg=sum_cfg,
            system_prompt=system_prompt,
            complete_fn=complete_fn,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to summarize: {e}")

    summary_text = (summary_text or "").strip()
    if not summary_text:
        raise HTTPException(status_code=502, detail="Summarizer returned empty output.")

    summary_message = f"Summary of “{title}”:\n\n{summary_text}"
    full = postprocess_text(summary_message)

    if full:
        db_add_message(
            conversation_id,
            "assistant",
            full,
            meta={
                "summary": True,
                "model": target.model,
                "provider": target.provider_id,
                "deployment_id": target.id,
            },
        )
        db_save_conversation_summary_artifact(conversation_id, summary_text, target.model)

    return {
        "conversation_id": conversation_id,
        "summary": summary_text,
        "model": target.model,
        "provider": target.provider_id,
        "deployment_id": target.id,
    }

# endregion

# region Conversation Transcript Endpoints

@app.post("/api/conversation/{conversation_id}/refresh_transcript_artifact")
def api_refresh_transcript_artifact(
    conversation_id: str,
    force_full: bool = False,
    reason: str = "manual",
):
    try:
        out = db_refresh_conversation_transcript_artifact(
            conversation_id,
            force_full=bool(force_full),
            reason=reason,
        )
        return JSONResponse(out)
    except ValueError as e:
        http_from_value_error(e)


@app.get("/api/conversation/{conversation_id}/export_transcript")
def api_export_transcript(
    conversation_id: str,
    force_full: bool = False,
):
    try:
        # repair first so export reflects latest SQL state
        db_refresh_conversation_transcript_artifact(
            conversation_id,
            force_full=bool(force_full),
            reason="export",
        )

        title = db_get_conversation_title(conversation_id) or f"Conversation {conversation_id}"
        body = db_export_conversation_transcript_markdown(
            conversation_id,
            refresh_if_stale=False,
            force_full=False,
        )

        safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_") or conversation_id
        filename = f"{safe_title}.transcript.md"

        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            },
        )
    except ValueError as e:
        http_from_value_error(e)


@app.post("/api/conversation/{conversation_id}/suggest_title")
def api_suggest_title(conversation_id: str):
    try:
        current_title, transcript = db_get_transcript_for_summary(conversation_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        complete_fn, target = make_utility_completion(
            "title_default",
            "summary_default",
        )

        suggested = suggest_conversation_title_from_transcript(
            model=target.model,
            transcript=transcript,
            current_title=current_title or "New chat",
            complete_fn=complete_fn,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to suggest title: {e}")

    final_title = (suggested or "").strip() or "New chat"
    updated = update_conversation_title(conversation_id, final_title)
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found.")

    return JSONResponse(
        {
            "ok": True,
            "title": final_title,
            "model": target.model,
            "provider": target.provider_id,
            "deployment_id": target.id,
        }
    )

# endregion

# region Context Endpoints

@app.get("/api/conversation/{conversation_id}/context")
def api_conversation_context(
    conversation_id: str,
    user_text: str = "",
    preview_limit: int | None = None,
    principal_type: str = "user",
    principal_id: str = "local",
    tenant_id: str = "default",
    admin_view: str | None = None,
):
    ctx_cfg = load_context_config()
    if preview_limit is not None:
        ctx_cfg = ContextConfig(
            memory_pin_limit=ctx_cfg.memory_pin_limit,
            history_limit=ctx_cfg.history_limit,
            preview_limit=max(1, int(preview_limit)),
            estimate_model=ctx_cfg.estimate_model,
        )

    principal = principal_from_request(
        principal_type=principal_type,
        principal_id=principal_id,
        tenant_id=tenant_id,
        admin_view=admin_view,
    )
    try:
        payload = build_context_panel_payload(
            conversation_id=conversation_id,
            user_text=user_text or "",
            ctx_cfg=ctx_cfg,
            tool_cfg=TOOL_CFG,
            principal=principal,
        )
    except KeyError as exc:
        if "Conversation not found" in str(exc):
            raise HTTPException(status_code=404, detail="conversation_not_found") from exc
        raise
    return JSONResponse(payload)

# endregion
