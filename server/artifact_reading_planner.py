from __future__ import annotations

import json
import itertools
import re
from dataclasses import dataclass
from typing import Any

from .db import (
    db_session,
    get_artifact_derivative,
    get_artifact_summary,
    list_artifact_derivative_sections,
    load_artifact_row_for_context,
)


_READ_WORDS = {
    "read", "reading", "study", "learn", "analyze", "analyse", "digest",
    "understand", "review", "walk", "walkthrough", "go", "through",
    "chapter", "chapters", "page", "pages", "section", "sections",
    "document", "doc", "paper", "story", "transcript", "novel", "article",
}
_REFERENCE_WORDS = {
    "find", "lookup", "look", "reference", "cite", "citation", "where",
    "which", "what", "when", "who", "search", "retrieve", "rag", "quote",
}
_REFERENCE_FIRST_SOURCE_KINDS = {
    "conversation:transcript",
    "conversation_transcript",
}
_EXPLICIT_SEQUENTIAL_READING_PHRASES = (
    "read this transcript",
    "read the transcript",
    "walk through the transcript",
    "walk me through the transcript",
    "go through the transcript",
    "step through the transcript",
    "read it front to back",
    "read it from the top",
    "sequential read",
    "sequential reading",
    "continue reading",
    "resume reading",
    "start a reading session",
    "continue the reading session",
    "resume the reading session",
)


@dataclass
class ArtifactReadiness:
    artifact_id: str
    title: str
    source_kind: str
    content_chars: int
    estimated_message_chars: int
    has_summary: bool
    has_index: bool
    summary_text: str
    index_text: str
    index_sections: list[dict]
    summary_stale: bool
    summary_artifact_hash: str | None


def _safe_json_loads(raw: str | None) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def is_reference_first_artifact(source_kind: str | None) -> bool:
    sk = (source_kind or "").strip().lower()
    return sk in _REFERENCE_FIRST_SOURCE_KINDS


def user_explicitly_requests_sequential_reading(user_text: str) -> bool:
    text = (user_text or "").strip().lower()
    if not text:
        return False

    if any(phrase in text for phrase in _EXPLICIT_SEQUENTIAL_READING_PHRASES):
        return True

    words = set(re.findall(r"[a-z0-9_']+", text))
    has_transcript = "transcript" in words or "chatlog" in words or "chat" in words
    has_reading_verb = bool(words & {"read", "reading", "resume", "continue", "walk", "through", "sequential"})

    if has_transcript and has_reading_verb:
        return True

    if ("front to back" in text or "from the top" in text or "chunk by chunk" in text) and has_transcript:
        return True

    return False


def classify_reading_intent(user_text: str) -> str:
    text = (user_text or "").strip().lower()
    if not text:
        return "reference"

    words = set(re.findall(r"[a-z0-9_']+", text))
    read_hits = len(words & _READ_WORDS)
    ref_hits = len(words & _REFERENCE_WORDS)

    if read_hits >= ref_hits:
        return "reading"
    return "reference"


def get_artifact_readiness(artifact_id: str) -> ArtifactReadiness | None:
    aid = (artifact_id or "").strip()
    if not aid:
        return None

    with db_session() as conn:
        art = load_artifact_row_for_context(conn, aid)
        if not art:
            return None

        title = (art.get("title") or aid).strip()
        source_kind = (art.get("source_kind") or "").strip()
        body = (art.get("content_text") or "").strip()
        content_chars = len(body)

        # Same shape as context._artifact_to_input_message(), but without importing a private helper.
        estimated_message_chars = content_chars + len(title) + len(aid) + len(source_kind) + 80

        summary = get_artifact_summary(conn, aid, include_stale=True)
        summary_text = (summary.get("summary_text") or "").strip() if summary else ""
        summary_stale = bool(summary.get("is_stale")) if summary else False
        summary_artifact_hash = summary.get("current_input_hash") if summary else None

        index_der = get_artifact_derivative(
            aid,
            derivative_kind="index",
            focus_kind="general",
            format_kind="json",
        ) or get_artifact_derivative(
            aid,
            derivative_kind="index",
            focus_kind="general",
            format_kind="text",
        )

        index_sections: list[dict] = []
        index_text = ""
        if index_der:
            index_text = (index_der.get("content_text") or "").strip()
            parsed = _safe_json_loads(index_der.get("content_json"))
            if isinstance(parsed, dict):
                maybe_sections = parsed.get("sections")
                if isinstance(maybe_sections, list):
                    index_sections = [s for s in maybe_sections if isinstance(s, dict)]
            elif isinstance(parsed, list):
                index_sections = [s for s in parsed if isinstance(s, dict)]

            if not index_sections:
                try:
                    index_sections = list_artifact_derivative_sections(int(index_der["id"]))
                except Exception:
                    index_sections = []

        return ArtifactReadiness(
            artifact_id=aid,
            title=title,
            source_kind=source_kind,
            content_chars=content_chars,
            estimated_message_chars=estimated_message_chars,
            has_summary=bool(summary_text),
            has_index=bool(index_text or index_sections),
            summary_text=summary_text,
            index_text=index_text,
            index_sections=index_sections,
            summary_stale=summary_stale,
            summary_artifact_hash=summary_artifact_hash,
        )


def plan_artifact_inclusion(
    *,
    user_text: str,
    readiness: ArtifactReadiness,
    budget_remaining_chars: int,
    include_whole_budget_chars: int | None = None,
    whole_artifact_soft_cap_chars: int = 12000,
) -> dict[str, Any]:
    intent = classify_reading_intent(user_text)
    forced_reference_first = (
        is_reference_first_artifact(readiness.source_kind)
        and not user_explicitly_requests_sequential_reading(user_text)
    )
    if forced_reference_first:
        intent = "reference"

    est_chars = int(readiness.estimated_message_chars or 0)
    remaining = max(0, int(budget_remaining_chars or 0))
    whole_remaining = remaining if include_whole_budget_chars is None else max(0, int(include_whole_budget_chars or 0))
    soft_cap = max(1000, int(whole_artifact_soft_cap_chars or 12000))

    fits_whole = est_chars <= min(whole_remaining, soft_cap) if whole_remaining > 0 else est_chars <= soft_cap

    if fits_whole:
        strategies = ["include_whole"]
        if forced_reference_first:
            strategies.append("reference_first_transcript")
        return {
            "mode": intent,
            "artifact_id": readiness.artifact_id,
            "title": readiness.title,
            "action": "include_whole",
            "reason": (
                "Conversation transcripts default to reference mode unless the user explicitly asks for a sequential read. "
                f"Estimated whole-artifact size ({est_chars} chars) fits current budget."
                if forced_reference_first
                else f"Estimated whole-artifact size ({est_chars} chars) fits current budget."
            ),
            "strategies": strategies,
            "needs_derivatives": [],
            "budget_remaining_chars": remaining,
            "estimated_message_chars": est_chars,
            "forced_reference_first": forced_reference_first,
        }

    strategies: list[str] = []
    needs_derivatives: list[str] = []
    fallback_messages: list[str] = []

    if readiness.has_summary:
        strategies.append("use_summary")
    else:
        needs_derivatives.append("summary")
        fallback_messages.append("summary missing")

    if forced_reference_first:
        strategies.append("reference_first_transcript")

    if readiness.has_index:
        strategies.append("use_index")
    else:
        needs_derivatives.append("index")
        fallback_messages.append("index missing")

    if intent == "reading":
        strategies.extend(["focus_primary", "defer_full_read"])
    else:
        strategies.extend(["focus_reference", "selective_reference_rag"])

    if whole_remaining > 0:
        whole_reason = (
            f"Whole artifact estimated at {est_chars} chars exceeds current whole-artifact budget {whole_remaining}."
        )
    else:
        whole_reason = (
            f"Whole artifact estimated at {est_chars} chars exceeds current whole-artifact budget; "
            f"expansion budget is exhausted, using fallback planner reserve {remaining}."
        )
    reason_parts = [whole_reason]
    if forced_reference_first:
        reason_parts.append(
            "Conversation transcripts default to reference mode unless the user explicitly requests a sequential read."
        )
    if fallback_messages:
        reason_parts.append("Fallback metadata unavailable: " + ", ".join(fallback_messages) + ".")
    else:
        reason_parts.append("Using available summary/index fallback instead of whole expansion.")

    return {
        "mode": intent,
        "artifact_id": readiness.artifact_id,
        "title": readiness.title,
        "action": "fallback_derivatives",
        "reason": " ".join(reason_parts),
        "strategies": strategies,
        "needs_derivatives": needs_derivatives,
        "budget_remaining_chars": remaining,
        "estimated_message_chars": est_chars,
        "forced_reference_first": forced_reference_first,
    }


def format_summary_message(readiness: ArtifactReadiness) -> dict[str, str] | None:
    text = (readiness.summary_text or "").strip()
    if not text:
        return None

    lines = [
        "ARTIFACT SUMMARY",
        f"Title: {readiness.title}",
        f"Artifact ID: {readiness.artifact_id}",
    ]
    if readiness.source_kind:
        lines.append(f"Source kind: {readiness.source_kind}")
    if readiness.summary_stale:
        lines.append("Note: summary may be stale relative to latest artifact contents.")
    lines.append("")
    lines.append(text)
    return {"role": "user", "content": "\n".join(lines).strip()}


def format_index_message(readiness: ArtifactReadiness, *, max_sections: int = 24) -> dict[str, str] | None:
    if readiness.index_sections:
        lines = [
            "ARTIFACT INDEX",
            f"Title: {readiness.title}",
            f"Artifact ID: {readiness.artifact_id}",
            "",
        ]
        for sec in readiness.index_sections[: max(1, int(max_sections))]:
            label = (sec.get("label") or sec.get("section_kind") or "section").strip()
            c0 = sec.get("chunk_start")
            c1 = sec.get("chunk_end")
            summary = (sec.get("summary_text") or "").strip()
            range_text = f"chunks {c0}–{c1}" if c0 is not None and c1 is not None else "chunk range unknown"
            line = f"- {label} ({range_text})"
            if summary:
                line += f": {summary}"
            lines.append(line)
        return {"role": "user", "content": "\n".join(lines).strip()}

    text = (readiness.index_text or "").strip()
    if not text:
        return None

    lines = [
        "ARTIFACT INDEX",
        f"Title: {readiness.title}",
        f"Artifact ID: {readiness.artifact_id}",
        "",
        text,
    ]
    return {"role": "user", "content": "\n".join(lines).strip()}


def format_planner_note_message(plan: dict[str, Any]) -> dict[str, str]:
    needs = plan.get("needs_derivatives") or []
    strategies = plan.get("strategies") or []

    lines = [
        "ARTIFACT READING PLAN",
        f"Title: {plan.get('title') or plan.get('artifact_id') or 'Unknown artifact'}",
        f"Artifact ID: {plan.get('artifact_id') or ''}",
        f"Mode: {plan.get('mode') or 'reference'}",
        f"Action: {plan.get('action') or 'fallback_derivatives'}",
        "",
        (plan.get("reason") or "Reading-plan fallback triggered.").strip(),
    ]

    if strategies:
        lines.append("")
        lines.append("Strategies: " + ", ".join(str(s) for s in strategies))
    if needs:
        lines.append("Missing derivatives: " + ", ".join(str(n) for n in needs))

    return {"role": "user", "content": "\n".join(lines).strip()}

