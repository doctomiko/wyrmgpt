import json
from typing import Any

from server.artifact_reading_planner import get_artifact_readiness
from server.config import load_summary_config
from server.db import db_create_conversation_scaffold_event, db_update_artifact_reading_session, db_update_artifact_reading_step, db_list_artifact_reading_steps, db_get_artifact_reading_step, db_get_artifact_reading_session
from server.logging_helper import log_warn
from server.reading_session_notes import build_reading_notes_prompts, coerce_reading_strategy, load_reading_questions, parse_reading_notes_output
from server.routes.deployments import make_utility_completion
from server.tools.base import ToolInvocationRequest, ToolResult


# region Reading Plan helpers

def _stringify_recent_notes(notes: Any) -> str:
    if notes is None:
        return ""
    if isinstance(notes, str):
        return notes.strip()
    try:
        return json.dumps(notes, ensure_ascii=False)
    except Exception:
        return str(notes).strip()


def maybe_capture_reading_notes_for_result(
    *,
    target,
    conversation_id: str,
    user_text: str,
    request: ToolInvocationRequest,
    result: ToolResult,
) -> ToolResult:
    if not result.ok or request.tool not in {"artifact.read_section", "artifact.read_next"}:
        return result

    payload = dict(result.result or {})
    section = payload.get("section") or {}
    session = payload.get("session") or {}

    session_id = payload.get("session_id") or session.get("id") or request.arguments.get("session_id")
    ordinal = section.get("ordinal") or request.arguments.get("ordinal") or (payload.get("next_step") or {}).get("ordinal")
    artifact_id = str(payload.get("artifact_id") or session.get("artifact_id") or request.arguments.get("artifact_id") or "").strip()
    current_text = str(payload.get("text") or "").strip()

    if not session_id or not ordinal or not artifact_id or not current_text:
        return result

    try:
        session_id = int(session_id)
        ordinal = int(ordinal)
    except Exception:
        return result

    session_row = db_get_artifact_reading_session(session_id)
    step_row = db_get_artifact_reading_step(session_id, ordinal)
    steps = db_list_artifact_reading_steps(session_id)
    if not session_row or not step_row or not steps:
        return result

    question_sets = load_reading_questions()
    readiness = get_artifact_readiness(artifact_id)
    strategy = coerce_reading_strategy(
        session_row.get("strategy_json"),
        source_kind=(payload.get("source_kind") or (readiness.source_kind if readiness else "")),
        title=(payload.get("title") or (readiness.title if readiness else artifact_id)),
        user_text=user_text,
        available_modes=sorted(question_sets.keys()),
    )
    selected_modes = strategy.get("modes") or ["core", "reader_experience", "meta"]

    recent_done = [s for s in steps if int(s.get("ordinal") or 0) < ordinal and s.get("notes")]
    recent_done = recent_done[-3:]
    recent_notes_text = "".join(
        f"Section {int(s.get('ordinal') or 0)} notes: {_stringify_recent_notes(s.get('notes'))}"
        for s in recent_done
        if _stringify_recent_notes(s.get("notes"))
    )

    is_final_step = ordinal >= max(int(s.get("ordinal") or 0) for s in steps)
    artifact_summary_text = (readiness.summary_text if (is_final_step and readiness and readiness.summary_text) else None)

    system_prompt, user_prompt = build_reading_notes_prompts(
        title=str(payload.get("title") or (readiness.title if readiness else artifact_id)),
        artifact_id=artifact_id,
        source_kind=str(payload.get("source_kind") or (readiness.source_kind if readiness else "")),
        section_label=str(section.get("label") or f"Section {ordinal}"),
        section_ordinal=ordinal,
        step_count=len(steps),
        selected_modes=selected_modes,
        question_sets=question_sets,
        current_text=current_text,
        summary_so_far=str(session_row.get("summary_so_far") or ""),
        recent_notes_text=recent_notes_text or None,
        artifact_summary_text=artifact_summary_text,
    )

    sum_cfg = load_summary_config()
    try:
        complete_fn, _analysis_target = make_utility_completion(target.id)
        raw = complete_fn(system_prompt, user_prompt, int(sum_cfg.reading_notes_max_tokens or 1400))
        parsed = parse_reading_notes_output(raw) or {}
        notes = parsed.get("notes") or {"raw_text": raw.strip()}
        summary_so_far = str(parsed.get("summary_so_far") or "").strip() or str(session_row.get("summary_so_far") or "").strip()

        updated_step = db_update_artifact_reading_step(session_id, ordinal, status="done", notes=notes)
        updated_session = db_update_artifact_reading_session(
            session_id,
            current_section_ordinal=ordinal,
            current_chunk_position=int(step_row.get("chunk_end") or 0),
            summary_so_far=summary_so_far,
            status=("complete" if is_final_step else "active"),
        )

        try:
            db_create_conversation_scaffold_event(
                conversation_id=conversation_id,
                message_id=None,
                event_kind="artifact_reading_notes",
                status="ready",
                title=f"Reading notes · {artifact_id}",
                body_text=f"Captured reading notes for section {ordinal}.",
                input_json={"tool": request.tool, "artifact_id": artifact_id, "session_id": session_id, "ordinal": ordinal},
                output_json={
                    "summary_so_far": summary_so_far,
                    "notes": notes,
                    "modes": selected_modes,
                    "is_final_step": is_final_step,
                },
            )
        except Exception as exc:
            log_warn(f"Reading notes scaffold event persistence failed for session {session_id}: {exc}")

        payload["session"] = updated_session
        payload["session_id"] = session_id
        payload["section"] = dict(section)
        payload["section"]["ordinal"] = ordinal
        payload["session_notes"] = {
            "summary_so_far": summary_so_far,
            "notes": notes,
            "modes": selected_modes,
            "is_final_step": is_final_step,
        }
        return ToolResult(
            ok=True,
            tool=result.tool,
            result=payload,
            error=None,
            display_text=((result.display_text or "").rstrip('.') + '. Captured reading notes.').strip(),
            event_kind=result.event_kind,
        )
    except Exception as exc:
        log_warn(f"Reading notes capture failed for session {session_id}: {exc}")
        return result




# endregion