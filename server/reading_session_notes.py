from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import SummaryConfig, load_summary_config

_FALLBACK_READING_QUESTIONS = """[core]
- What seems to have begun, ended, or shifted in this section?
- What changed in stakes, goals, leverage, or power balance here?
- Who or what is central in this section?
- What newly established, revised, or contradicted facts matter going forward?
- What is the single most load-bearing beat, sentence, image, or claim?
- What feels unresolved now, and what is the most urgent next question?

[meta]
- What do I currently think this piece is trying to do?
- What am I uncertain about but willing to keep watching?
- What is my current confidence in my interpretation?
- Have any earlier expectations been confirmed or overturned?
- Am I more or less engaged than I was one section ago?

[reader_experience]
- What emotional temperature did this section carry?
- Was it engaging or flat? Why?
- Did the pacing accelerate, stall, or pivot?
- What moment or line landed best?
- What do you most want to see next?
- What do you predict will happen next?
"""

_SECTION_RE = re.compile(r"^\s*\[([A-Za-z0-9_]+)\]\s*$")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*\S)\s*$")
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


ALL_OF_THE_ABOVE_TOKENS = {
    "all",
    "*",
    "everything",
    "option_d",
    "dealer's choice",
    "all_of_the_above",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _reading_questions_path(sum_cfg: SummaryConfig | None = None) -> Path:
    cfg = sum_cfg or load_summary_config()
    raw = (getattr(cfg, "reading_questions_file", "") or "").strip() or "./prompts/_reading_questions.txt"
    path = Path(raw)
    if not path.is_absolute():
        path = _repo_root() / path
    return path


def parse_reading_questions_text(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        sec = _SECTION_RE.match(line)
        if sec:
            current = sec.group(1).strip().lower()
            out.setdefault(current, [])
            continue
        if line.lstrip().startswith("##"):
            continue
        bullet = _BULLET_RE.match(line)
        if bullet and current:
            out.setdefault(current, []).append(bullet.group(1).strip())
    return {k: v for k, v in out.items() if v}


def load_reading_questions(sum_cfg: SummaryConfig | None = None) -> dict[str, list[str]]:
    path = _reading_questions_path(sum_cfg)
    if path.exists():
        try:
            return parse_reading_questions_text(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return parse_reading_questions_text(_FALLBACK_READING_QUESTIONS)


def _parse_strategy_blob(raw_strategy: Any) -> Any:
    if raw_strategy is None:
        return None
    if isinstance(raw_strategy, (dict, list)):
        return raw_strategy
    text = str(raw_strategy).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _keyword_hits(text: str, words: list[str]) -> bool:
    blob = f" {text.lower()} "
    return any(f" {w.lower()} " in blob or w.lower() in blob for w in words)


def choose_default_modes(
    *,
    source_kind: str = "",
    title: str = "",
    user_text: str = "",
    available_modes: list[str] | None = None,
) -> list[str]:
    available = set(available_modes or [])
    blob = " ".join(part for part in [source_kind, title, user_text] if part).lower()
    modes: list[str] = ["core"]

    if _keyword_hits(blob, ["developmental", "editor", "editing", "edit", "revise", "revision", "critique"]):
        modes.extend(["developmental_edit", "style"])
    if _keyword_hits(blob, ["argument", "argumentative", "essay", "rhetoric", "rhetorical", "persuade", "persuasive", "claim"]):
        modes.append("argument")
    if _keyword_hits(blob, ["scientific", "science", "study", "research", "paper", "journal", "hypothesis", "experiment", "dataset", "methodology"]):
        modes.append("scientific_research")
    if _keyword_hits(blob, ["technical", "architecture", "system", "systems", "design doc", "runbook", "api", "spec", "implementation", "operator", "admin", "engineering"]):
        modes.append("technical_systems")
    if _keyword_hits(blob, ["story", "novel", "fiction", "chapter", "character", "plot", "scene"]):
        modes.extend(["reader_experience", "narrative"])
        if _keyword_hits(blob, ["fantasy", "science fiction", "sci-fi", "setting", "worldbuilding"]):
            modes.append("worldbuilding")
    if len(modes) == 1:
        modes.extend(["reader_experience", "meta"])
    else:
        modes.append("meta")

    deduped: list[str] = []
    for mode in modes:
        if mode in deduped:
            continue
        if available and mode not in available:
            continue
        deduped.append(mode)
    if deduped:
        return deduped
    return [m for m in ["core", "reader_experience", "meta"] if not available or m in available] or ["core"]


def coerce_reading_strategy(
    raw_strategy: Any,
    *,
    source_kind: str = "",
    title: str = "",
    user_text: str = "",
    available_modes: list[str] | None = None,
) -> dict[str, Any]:
    available = list(available_modes or [])
    default_modes = choose_default_modes(
        source_kind=source_kind,
        title=title,
        user_text=user_text,
        available_modes=available,
    )
    parsed = _parse_strategy_blob(raw_strategy)
    source = "default"
    requested_modes: list[str] = []
    all_of_the_above = False

    if isinstance(parsed, dict):
        source = "explicit"
        mode_blob = parsed.get("modes", parsed.get("mode", parsed.get("analysis_modes")))
        if isinstance(mode_blob, list):
            requested_modes = [str(x).strip().lower() for x in mode_blob if str(x).strip()]
        elif mode_blob is not None:
            requested_modes = [p.strip().lower() for p in re.split(r"[,|;+]", str(mode_blob)) if p.strip()]
        all_of_the_above = bool(parsed.get("all_of_the_above") or parsed.get("all") or parsed.get("option_d"))
    elif isinstance(parsed, list):
        source = "explicit"
        requested_modes = [str(x).strip().lower() for x in parsed if str(x).strip()]
    elif isinstance(parsed, str) and parsed:
        source = "explicit"
        requested_modes = [p.strip().lower() for p in re.split(r"[,|;+]", parsed) if p.strip()]

    if any(tok in ALL_OF_THE_ABOVE_TOKENS for tok in requested_modes):
        all_of_the_above = True

    if all_of_the_above:
        modes = list(available) if available else list(default_modes)
    else:
        modes = []
        for mode in requested_modes:
            if mode in ALL_OF_THE_ABOVE_TOKENS:
                continue
            if available and mode not in available:
                continue
            if mode not in modes:
                modes.append(mode)
        if not modes:
            modes = list(default_modes)

    if (not available or "core" in available) and "core" not in modes:
        modes.insert(0, "core")
    if "meta" in default_modes and (not available or "meta" in available) and "meta" not in modes:
        modes.append("meta")

    return {
        "modes": modes,
        "all_of_the_above": bool(all_of_the_above),
        "source": source,
    }


def build_reading_notes_prompts(
    *,
    title: str,
    artifact_id: str,
    source_kind: str,
    section_label: str,
    section_ordinal: int | None,
    step_count: int | None,
    selected_modes: list[str],
    question_sets: dict[str, list[str]],
    current_text: str,
    summary_so_far: str | None,
    recent_notes_text: str | None,
    artifact_summary_text: str | None,
) -> tuple[str, str]:
    mode_blocks: list[str] = []
    for mode in selected_modes:
        questions = question_sets.get(mode) or []
        if not questions:
            continue
        mode_blocks.append(f"[{mode}]")
        for idx, q in enumerate(questions, start=1):
            mode_blocks.append(f"{idx}. {q}")
        mode_blocks.append("")
    questions_text = "\n".join(mode_blocks).strip() or "[core]\n1. Summarize what changed in this section."

    system_prompt = """You are generating compact internal reading-session notes for one newly read section of an artifact.

This is not a chat reply.
Base your analysis primarily on CURRENT SECTION TEXT.
Use SUMMARY SO FAR and RECENT SESSION NOTES only as memory of earlier sections that were already read.
Do not pretend you have read unread future sections.
If FULL ARTIFACT SUMMARY is omitted, do not infer later outcomes from outside the current reading progress.
Keep answers concise but thoughtful. One short answer per question is enough.
Return valid JSON only, with this shape:
{
  "summary_so_far": "updated running summary through the current section",
  "notes": {
    "modes": ["core", "reader_experience"],
    "section_summary": "2 to 5 sentences on this section",
    "by_mode": {
      "core": [{"question": "...", "answer": "..."}]
    },
    "highlights": ["..."],
    "open_questions": ["..."],
    "engagement": "one short sentence",
    "confidence": "low|medium|high"
  }
}
"""

    ordinal_text = f"{section_ordinal}/{step_count}" if section_ordinal and step_count else (str(section_ordinal) if section_ordinal else "unknown")
    user_parts = [
        f"Title: {title}",
        f"Artifact ID: {artifact_id}",
        f"Source kind: {source_kind or 'unknown'}",
        f"Section: {section_label}",
        f"Ordinal: {ordinal_text}",
        f"Selected modes: {', '.join(selected_modes)}",
        "",
        "SUMMARY SO FAR (prior to current section):",
        (summary_so_far or "(none yet)").strip(),
        "",
    ]
    if recent_notes_text:
        user_parts.extend([
            "RECENT SESSION NOTES:",
            recent_notes_text.strip(),
            "",
        ])
    if artifact_summary_text:
        user_parts.extend([
            "FULL ARTIFACT SUMMARY (available only because this is the final reading step):",
            artifact_summary_text.strip(),
            "",
        ])
    user_parts.extend([
        "QUESTIONS TO ANSWER:",
        questions_text,
        "",
        "CURRENT SECTION TEXT:",
        (current_text or "").strip(),
    ])
    return system_prompt, "\n".join(user_parts).strip()


def parse_reading_notes_output(raw_text: str) -> dict[str, Any] | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    candidates = [text]
    for match in _JSON_BLOCK_RE.finditer(text):
        candidate = (match.group(1) or "").strip()
        if candidate:
            candidates.append(candidate)
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        notes = payload.get("notes")
        if notes is None:
            notes = {"raw": payload}
        return {
            "summary_so_far": str(payload.get("summary_so_far") or "").strip(),
            "notes": notes,
        }
    return {
        "summary_so_far": "",
        "notes": {"raw_text": text},
    }
