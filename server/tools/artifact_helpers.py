from __future__ import annotations

import re
from typing import Any

from ..artifact_reading_planner import get_artifact_readiness
from ..chunking import chunk_markdown, chunk_prose
from ..db import db_session, list_artifact_chunks, load_artifact_row_for_context


_ROMAN_RE = re.compile(r"\b([ivxlcdm]+)\b", re.IGNORECASE)
_INTEGER_RE = re.compile(r"\b(\d+)\b")


def _normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _roman_to_int(text: str) -> int | None:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    raw = (text or "").strip().lower()
    if not raw or any(ch not in values for ch in raw):
        return None
    total = 0
    prev = 0
    for ch in reversed(raw):
        val = values[ch]
        if val < prev:
            total -= val
        else:
            total += val
            prev = val
    return total if total > 0 else None


def _extract_requested_ordinal(section_ref: str) -> int | None:
    text = (section_ref or "").strip()
    if not text:
        return None

    m = _INTEGER_RE.search(text)
    if m:
        try:
            return max(1, int(m.group(1)))
        except Exception:
            return None

    rm = _ROMAN_RE.search(text)
    if rm:
        return _roman_to_int(rm.group(1))
    return None


def _normalize_source_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _has_meaningful_content(text: str, *, min_chars: int = 200) -> bool:
    t = _normalize_source_text(text)
    if len(t) < min_chars:
        return False
    alpha = sum(ch.isalpha() for ch in t)
    return alpha >= max(80, min_chars // 3)


def _synthesized_chunks_from_artifact_row(art: dict[str, Any]) -> list[dict[str, Any]]:
    body = _normalize_source_text(art.get("content_text") or "")
    if not _has_meaningful_content(body):
        return []

    title = (art.get("title") or "").lower()
    source_kind = (art.get("source_kind") or "").lower()
    if "markdown" in source_kind or body.lstrip().startswith("#") or ".md" in title:
        raw_chunks = chunk_markdown(body)
    else:
        raw_chunks = chunk_prose(body)

    out: list[dict[str, Any]] = []
    cursor = 0
    for idx, chunk in enumerate(raw_chunks):
        chunk_text = (chunk or "").strip()
        if not chunk_text:
            continue
        probe = chunk_text[:80]
        start = body.find(probe, cursor)
        if start < 0:
            start = cursor
        end = start + len(chunk_text)
        out.append({
            "id": None,
            "chunk_index": idx,
            "start_char": start,
            "end_char": end,
            "text": chunk_text,
            "synthetic": True,
        })
        cursor = max(cursor, end)
    return out


def load_or_synthesize_artifact_chunks(artifact_id: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    aid = (artifact_id or "").strip()
    if not aid:
        return None, []

    with db_session() as conn:
        art = load_artifact_row_for_context(conn, aid)
        if not art:
            return None, []

    chunks = list_artifact_chunks(aid)
    if chunks:
        return art, chunks
    return art, _synthesized_chunks_from_artifact_row(art)


def resolve_artifact_section_reference(
    artifact_id: str,
    section_ref: str,
    *,
    max_candidates: int = 5,
) -> dict[str, Any]:
    readiness = get_artifact_readiness(artifact_id)
    if not readiness:
        return {
            "ok": False,
            "artifact_id": (artifact_id or "").strip(),
            "section_ref": section_ref,
            "error": "artifact not found",
            "matched": None,
            "candidates": [],
        }

    ref_norm = _normalize_label(section_ref)
    sections = list(readiness.index_sections or [])
    candidates: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    requested_ordinal = _extract_requested_ordinal(section_ref)

    for sec in sections:
        label = (sec.get("label") or sec.get("section_kind") or "section").strip()
        label_norm = _normalize_label(label)
        ordinal = int(sec.get("ordinal") or 0) if sec.get("ordinal") is not None else 0
        score = 0

        if requested_ordinal and ordinal == requested_ordinal:
            score += 100
        if ref_norm and label_norm == ref_norm:
            score += 90
        if ref_norm and ref_norm in label_norm:
            score += 70
        if ref_norm and label_norm in ref_norm:
            score += 50
        if not score:
            continue

        candidate = dict(sec)
        candidate["label"] = label
        candidate["match_score"] = score
        candidates.append(candidate)

    candidates.sort(key=lambda s: (-int(s.get("match_score") or 0), int(s.get("ordinal") or 0), str(s.get("label") or "")))
    if candidates:
        matched = candidates[0]

    return {
        "ok": matched is not None,
        "artifact_id": readiness.artifact_id,
        "title": readiness.title,
        "section_ref": section_ref,
        "matched": matched,
        "candidates": candidates[: max(1, int(max_candidates))],
        "index_available": bool(sections),
        "summary_available": bool(readiness.summary_text),
        "error": None if matched is not None else "section not found in artifact index",
    }


def render_chunk_window(chunks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        idx = int(chunk.get("chunk_index") or 0)
        text = (chunk.get("text") or "").strip()
        if not text:
            continue
        parts.append(f"[Chunk {idx}]\n{text}")
    return "\n\n".join(parts).strip()
