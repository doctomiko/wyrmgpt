from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .artifact_reading_planner import ArtifactReadiness, get_artifact_readiness
from .chunking import chunk_markdown, chunk_prose
from .config import load_deployment_defs, load_provider_defs, load_summary_config
from .db import (
    db_session,
    get_artifact_derivative,
    get_artifact_summary,
    load_artifact_row_for_context,
    replace_artifact_derivative_sections_conn,
    set_artifact_summary,
    upsert_artifact_derivative_conn,
)
from .providers.base import ChatProvider, ModelCatalogProvider
from .providers.openai_provider import OpenAIProvider
from .providers.registry import ProviderRegistry
from .providers.types import ModelCatalog, ModelInput, ProviderDef, ResolvedDeployment
from .summary_helper import _call_summary_model, _chunk_transcript, cleanup_summary_text

ROOT = Path(__file__).resolve().parents[1]

_HEADING_MARKERS = (
    "chapter",
    "scene",
    "section",
    "part",
    "book",
    "act",
    "appendix",
    "prologue",
    "epilogue",
    "introduction",
    "conclusion",
)


def _load_model_catalog() -> ModelCatalog:
    path = ROOT / "server" / "model_catalog.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_provider_registry(model_catalog: ModelCatalog) -> ProviderRegistry:
    providers = load_provider_defs()
    deployments = load_deployment_defs()

    compat_factory = lambda provider_def: OpenAIProvider(provider_def, model_catalog=model_catalog)

    chat_factories: dict[str, Callable[[ProviderDef], ChatProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }
    catalog_factories: dict[str, Callable[[ProviderDef], ModelCatalogProvider]] = {
        "openai": compat_factory,
        "ollama": compat_factory,
        "lmstudio": compat_factory,
        "openai_compat": compat_factory,
    }
    return ProviderRegistry(
        providers=providers,
        deployments=deployments,
        chat_factories=chat_factories,
        catalog_factories=catalog_factories,
    )


# TODO move this to config.py and/or replace it with what is already there
def _read_prompt_file(path_text: str, default_value: str = "") -> str:
    raw = Path(path_text)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(raw)
        candidates.append(Path.cwd() / raw)
        candidates.append(ROOT / raw)

    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return default_value.strip()

def _resolve_summary_runtime(requested_deployment_id: str = "summary_default") -> tuple[ResolvedDeployment, ChatProvider, Any]:
    model_catalog = _load_model_catalog()
    registry = _build_provider_registry(model_catalog)
    requested = (requested_deployment_id or "summary_default").strip() or "summary_default"
    if requested not in registry.deployments:
        if requested != "summary_default" and "summary_default" in registry.deployments:
            # TODO WARN that the model has been swapped!
            requested = "summary_default"
        else:
            raise RuntimeError(
                "Summary deployment 'summary_default' is not configured. "
                "Add it under [deployments] before generating artifact derivatives."
            )
    target = registry.resolve_deployment_for_capability(
        "chat",
        requested,
        fallback_to_default_chat=False,
    )
    provider = registry.get_chat_provider(target)
    return target, provider, load_summary_config()


def _complete_via_provider(
    provider: ChatProvider,
    target: ResolvedDeployment,
    *,
    system_prompt_text: str,
    user_prompt_text: str,
    max_output_tokens: int,
) -> str:
    model_input: ModelInput = [
        {"role": "system", "content": system_prompt_text},
        {"role": "user", "content": user_prompt_text},
    ]
    result = provider.complete(
        target,
        model_input,
        request_options={"max_output_tokens": max_output_tokens},
    )
    return (result.text or "").strip()


def _looks_like_title_only_text(title: str, text: str) -> bool:
    body = _normalize_source_text(text)
    heading = _normalize_source_text(title)
    if not body:
        return True
    if not heading:
        return False

    body_low = body.lower()
    heading_low = heading.lower()
    if body_low == heading_low:
        return True
    if body_low.startswith(f"# {heading_low}"):
        remainder = body[len(heading) + 2 :].strip(" :-–—")
        return len(remainder) < 80
    if body_low.startswith(heading_low):
        remainder = body[len(heading) :].strip(" :-–—")
        return len(remainder) < 80
    return False


def _trustworthy_artifact_text(title: str, text: str) -> str:
    body = _normalize_source_text(text)
    if not _has_meaningful_content(body, min_chars=300):
        return ""
    if _looks_like_title_only_text(title, body):
        return ""
    return body


def _summarize_artifact_text(*, title: str, artifact_text: str) -> tuple[str, str]:
    transcript = _trustworthy_artifact_text(title, artifact_text)
    if not transcript:
        return "", ""

    sum_cfg = load_summary_config()
    requested_deployment = "summary_default"
    if len(transcript) > max(sum_cfg.summary_reduce_threshold_chars, 12000):
        requested_deployment = "chat_default"
    # TODO we no longer get the summary configuration back from this function so remove that
    target, provider, _ = _resolve_summary_runtime(requested_deployment)

    system_prompt = _read_prompt_file(
        sum_cfg.summary_artifact_prompt_file,
        sum_cfg.summary_artifact_prompt
    ).strip()

    def call(system_prompt_text: str, user_prompt_text: str, max_output_tokens: int) -> str:
        return _complete_via_provider(
            provider,
            target,
            system_prompt_text=system_prompt_text,
            user_prompt_text=user_prompt_text,
            max_output_tokens=max_output_tokens,
        )

    if len(transcript) <= sum_cfg.summary_reduce_threshold_chars:
        user_prompt = (
            f"Title: {title}\n\n"
            f"Artifact text follows. Read all of it before writing.\n\n"
            f"Return only the summary text.\n\n"
            f"{transcript}"
        )
        text = cleanup_summary_text(
            _call_summary_model(
                model=target.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_output_tokens=sum_cfg.summary_max_tokens,
                complete_fn=call,
            )
        )
        return text, target.model

    chunks = _chunk_transcript(
        transcript,
        target_chars=sum_cfg.summary_chunk_target_chars,
        hard_max_chars=sum_cfg.summary_chunk_hard_max_chars,
    )
    partials: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_prompt = (
            f"Title: {title}\n"
            f"Chunk {idx} of {len(chunks)}.\n\n"
            f"Return only a compact prose summary of this chunk.\n"
            f"Mention major changes in topic, plot, setting, characters, tone, or argumentative stance when they matter.\n\n"
            f"{chunk}"
        )
        partial = cleanup_summary_text(
            _call_summary_model(
                model=target.model,
                system_prompt=system_prompt,
                user_prompt=chunk_prompt,
                max_output_tokens=sum_cfg.summary_chunk_max_tokens,
                complete_fn=call,
            )
        )
        if partial:
            partials.append(f"Chunk {idx}: {partial}")

    if not partials:
        return "", target.model

    reduce_system_prompt = _read_prompt_file(
        sum_cfg.summary_artifact_reduce_prompt_file,
        sum_cfg.summary_artifact_reduce_prompt
    ).strip()
    reduce_user_prompt = (
        f"Title: {title}\n\n"
        f"The following are chunk summaries for one artifact. Combine them into a coherent summary of the full artifact.\n\n"
        + "\n\n".join(partials)
    )
    reduced = cleanup_summary_text(
        _call_summary_model(
            model=target.model,
            system_prompt=reduce_system_prompt,
            user_prompt=reduce_user_prompt,
            max_output_tokens=sum_cfg.summary_max_tokens,
            complete_fn=call,
        )
    )
    return reduced, target.model


def _artifact_chunks(conn, artifact_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, chunk_index, start_char, end_char, text
        FROM corpus_chunks
        WHERE artifact_id = ?
        ORDER BY chunk_index ASC, id ASC
        """,
        ((artifact_id or "").strip(),),
    ).fetchall()
    return [dict(r) for r in rows]


def _normalize_source_text(text: str) -> str:
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _has_meaningful_content(text: str, *, min_chars: int = 200) -> bool:
    t = _normalize_source_text(text)
    if len(t) < min_chars:
        return False
    alpha = sum(ch.isalpha() for ch in t)
    return alpha >= max(80, min_chars // 3)


def _synthesized_chunks_from_text(art: dict) -> list[dict]:
    body = _normalize_source_text(art.get("content_text") or "")
    if not _has_meaningful_content(body):
        return []

    title = (art.get("title") or "").lower()
    source_kind = (art.get("source_kind") or "").lower()
    if "markdown" in source_kind or body.lstrip().startswith("#") or ".md" in title:
        raw_chunks = chunk_markdown(body)
    else:
        raw_chunks = chunk_prose(body)

    out: list[dict] = []
    cursor = 0
    for idx, chunk in enumerate(raw_chunks):
        chunk_text = (chunk or "").strip()
        if not chunk_text:
            continue
        start = body.find(chunk_text[:80], cursor)
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


def _headingish_lines(text: str) -> list[str]:
    lines = []
    for raw in (text or "").splitlines():
        line = (raw or "").strip()
        if not line:
            continue
        if len(line) > 120:
            continue
        lines.append(line)
    return lines


def _cleanup_heading(line: str) -> str:
    s = (line or "").strip().strip("#>*- ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\[(]+", "", s)
    s = re.sub(r"[\])]+$", "", s)
    return s[:120].strip()


def _looks_like_heading(line: str) -> bool:
    s = _cleanup_heading(line)
    if not s:
        return False
    low = s.lower()
    if low.startswith(_HEADING_MARKERS):
        return True
    if re.match(r"^(?:chapter|scene|section|part|book|act|appendix|prologue|epilogue)\b", low):
        return True
    if re.match(r"^(?:[ivxlcdm]+|\d+|[a-z])(?:[.):-]|\s+-)\s+", low, re.IGNORECASE):
        return True
    if line.lstrip().startswith("#"):
        return True
    words = s.split()
    if 1 <= len(words) <= 10 and s.isupper() and any(ch.isalpha() for ch in s):
        return True
    if len(words) <= 12 and s.endswith(":"):
        return True
    return False


def _extract_heading_sections(chunk_text: str) -> list[tuple[str, str]]:
    raw_lines = (chunk_text or "").splitlines()
    cleaned_lines = [(raw or "").strip() for raw in raw_lines]

    heading_positions: list[tuple[int, str]] = []
    for idx, line in enumerate(cleaned_lines):
        if not line:
            continue
        if len(line) > 120:
            continue
        if _looks_like_heading(line):
            label = _cleanup_heading(line).rstrip(":")
            if label:
                heading_positions.append((idx, label))

    if not heading_positions:
        return []

    sections: list[tuple[str, str]] = []
    for pos, (line_idx, label) in enumerate(heading_positions):
        next_line_idx = heading_positions[pos + 1][0] if pos + 1 < len(heading_positions) else len(cleaned_lines)
        body_lines = [
            line
            for line in cleaned_lines[line_idx + 1 : next_line_idx]
            if line and not _looks_like_heading(line)
        ]
        body_text = "".join(body_lines).strip()
        summary = _excerpt_sentence(body_text) if body_text else ""
        sections.append((label, summary))

    return sections


def _detect_heading_labels(chunk_text: str) -> list[str]:
    return [label for label, _summary in _extract_heading_sections(chunk_text)]


def _detect_heading_label(chunk_text: str) -> str | None:
    labels = _detect_heading_labels(chunk_text)
    if labels:
        return labels[0]
    return None


def _excerpt_sentence(text: str, *, max_chars: int = 180) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return ""
    m = re.search(r"(.{1,%d}?[.!?])(?:\s|$)" % max_chars, t)
    if m:
        return m.group(1).strip()
    return t[:max_chars].rstrip()


def _build_index_payload(title: str, chunks: list[dict]) -> tuple[str, dict, list[dict]]:
    if not chunks:
        return "", {
            "title": title,
            "sections": [],
            "needs_llm_outline": True,
            "reason": "no_content_available",
         }, []

    labels_detected = any(_detect_heading_label(c.get("text") or "") for c in chunks)
    if not labels_detected:
        first_idx = int(chunks[0].get("chunk_index") or 0)
        last_idx = int(chunks[-1].get("chunk_index") or first_idx)
        sections = [
            {
                "ordinal": 1,
                "section_kind": "outline_placeholder",
                "source_mode": "needs_llm_outline",
                "label": "Structure inference pending",
                "summary_text": (
                    "No stable headings detected. Next step: summarize chunks and infer section boundaries "
                    "from changes in plot, setting, characters, tone, or argument style."
                ),
                "chunk_start": first_idx,
                "chunk_end": last_idx,
            }
        ]
        payload = {
            "title": title,
            "needs_llm_outline": True,
            "reason": "no_heading_cues_detected",
            "sections": sections,
        }
        text = (
            "ARTIFACT INDEX PLACEHOLDER\n"
            "No stable heading cues were detected in this artifact.\n"
            "Future step: generate per-chunk summaries and infer an outline from shifts in plot, setting, "
            "characters, tone, or argument style."
        )
        return text, payload, sections

    sections: list[dict] = []
    current: dict[str, Any] | None = None

    for chunk in chunks:
        idx = int(chunk.get("chunk_index") or 0)
        chunk_text = (chunk.get("text") or "").strip()
        heading_sections = _extract_heading_sections(chunk_text)
        if heading_sections:
            if current is not None:
                sections.append(current)
                current = None

            for heading, summary_text in heading_sections[:-1]:
                sections.append({
                    "ordinal": len(sections) + 1,
                    "section_kind": "heading",
                    "source_mode": "heading",
                    "label": heading,
                    "summary_text": summary_text or _excerpt_sentence(chunk_text),
                    "chunk_start": idx,
                    "chunk_end": idx,
                })

            last_heading, last_summary_text = heading_sections[-1]
            current = {
                "ordinal": len(sections) + 1,
                "section_kind": "heading",
                "source_mode": "heading",
                "label": last_heading,
                "summary_text": last_summary_text or _excerpt_sentence(chunk_text),
                "chunk_start": idx,
                "chunk_end": idx,
            }
            continue

        if current is None:
            current = {
                "ordinal": 1,
                "section_kind": "section",
                "source_mode": "inferred_scene",
                "label": "Opening matter",
                "summary_text": _excerpt_sentence(chunk_text),
                "chunk_start": idx,
                "chunk_end": idx,
            }
        else:
            current["chunk_end"] = idx
            if not current.get("summary_text"):
                current["summary_text"] = _excerpt_sentence(chunk_text)

    if current is not None:
        sections.append(current)

    lines = ["ARTIFACT INDEX", f"Title: {title}", ""]
    for sec in sections:
        label = (sec.get("label") or sec.get("section_kind") or "section").strip()
        c0 = sec.get("chunk_start")
        c1 = sec.get("chunk_end")
        summary = (sec.get("summary_text") or "").strip()
        line = f"- {label} (chunks {c0}–{c1})"
        if summary:
            line += f": {summary}"
        lines.append(line)

    payload = {
        "title": title,
        "needs_llm_outline": False,
        "reason": "heading_outline_available",
        "sections": sections,
    }
    return "\n".join(lines).strip(), payload, sections


def _clear_index_derivatives(conn, artifact_id: str) -> None:
    rows = conn.execute(
        """
        SELECT id
        FROM artifact_derivatives
        WHERE artifact_id = ?
          AND derivative_kind = 'index'
          AND focus_kind = 'general'
        """,
        ((artifact_id or "").strip(),),
    ).fetchall()
    for r in rows:
        did = int(r["id"])
        conn.execute("DELETE FROM artifact_derivative_sections WHERE artifact_derivative_id = ?", (did,))
        conn.execute("DELETE FROM artifact_derivatives WHERE id = ?", (did,))


def ensure_artifact_reading_derivatives(
    artifact_id: str,
    *,
    force: bool = False,
    clear_invalid: bool = False,
) -> ArtifactReadiness | None:
    aid = (artifact_id or "").strip()
    if not aid:
        return None

    with db_session() as conn:
        art = load_artifact_row_for_context(conn, aid)
        if not art:
            return None

        title = (art.get("title") or aid).strip()
        content_text = _normalize_source_text(art.get("content_text") or "")
        source_hash = (art.get("content_hash") or "").strip() or None

        chunks = _artifact_chunks(conn, aid)
        synthetic_chunks_used = False
        trusted_content_text = _trustworthy_artifact_text(title, content_text)
        if not chunks and _has_meaningful_content(content_text):
            chunks = _synthesized_chunks_from_text(art)
            synthetic_chunks_used = bool(chunks)

        if not chunks and trusted_content_text:
            chunks = _synthesized_chunks_from_text({**art, "content_text": trusted_content_text})
        summary_info = get_artifact_summary(conn, aid, include_stale=True)
        has_content_evidence = bool(trusted_content_text) or bool(chunks)
        existing_summary_text = ""
        if summary_info:
            existing_summary_text = (summary_info.get("summary_text") or "").strip()
        needs_summary = (
            bool(force)
            or not summary_info
            or not existing_summary_text
            or bool(summary_info.get("is_stale"))
        )

        if not has_content_evidence:
            if clear_invalid:
                if summary_info and (summary_info.get("summary_text") or "").strip():
                    set_artifact_summary(conn, aid, "", "artifact_derivative_builder")
                _clear_index_derivatives(conn, aid)
        elif needs_summary:
            summary_text, summary_model = _summarize_artifact_text(
                title=title,
                artifact_text=trusted_content_text,
            )
            if summary_text:
                set_artifact_summary(conn, aid, summary_text, summary_model)
                
        index_der = get_artifact_derivative(
            aid,
            derivative_kind="index",
            focus_kind="general",
            format_kind="json",
        )
        if not index_der:
            index_der = get_artifact_derivative(
                aid,
                derivative_kind="index",
                focus_kind="general",
                format_kind="text",
            )

        needs_index = bool(force)
        if not needs_index:
            if not index_der:
                needs_index = True
            else:
                existing_hash = (index_der.get("source_artifact_content_hash") or "").strip() or None
                existing_status = (index_der.get("status") or "").strip().lower()
                needs_index = existing_hash != source_hash or existing_status != "ready"

        if not has_content_evidence:
            if clear_invalid and index_der:
                _clear_index_derivatives(conn, aid)
        elif needs_index:
            index_text, index_payload, sections = _build_index_payload(title, chunks)
            if index_text or sections:
                derivative_id = upsert_artifact_derivative_conn(
                    conn,
                    artifact_id=aid,
                    derivative_kind="index",
                    focus_kind="general",
                    format_kind="json",
                    title=f"{title} — Reading index",
                    content_text=index_text,
                    content_json=index_payload,
                    source_artifact_content_hash=source_hash,
                    model_deployment_id=None,
                    model_name=None,
                    generator_kind="deterministic_outline" if not synthetic_chunks_used else "deterministic_outline_from_content",
                    status="ready",
                )
                replace_artifact_derivative_sections_conn(
                    conn,
                    artifact_derivative_id=int(derivative_id),
                    sections=sections,
                )

    return get_artifact_readiness(aid)
