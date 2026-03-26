from __future__ import annotations

from typing import Any

from ..config import load_provider_defs
from ..db import (
    create_web_search_conn,
    db_get_conversation_project_id,
    db_session,
    replace_web_search_results_conn,
)
from ..web_search import WebSearchError, brave_web_search
from .base import ToolExecutionContext, ToolResult, ToolSpec

TOOL_SPEC = ToolSpec(
    name="web.search",
    description="Run a web search and return ranked result links with titles and snippets.",
    input_schema={
        "type": "object",
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "minLength": 2,
                "description": "The web search query to run.",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "default": 8,
            },
            "country": {
                "type": "string",
                "minLength": 2,
                "maxLength": 8,
                "default": "us",
            },
            "search_lang": {
                "type": "string",
                "minLength": 2,
                "maxLength": 8,
                "default": "en",
            },
            "safesearch": {
                "type": "string",
                "enum": ["off", "moderate", "strict"],
                "default": "moderate",
            },
            "freshness": {
                "type": "string",
                "description": "Optional Brave freshness filter such as pd, pw, pm, py, or an explicit range.",
            },
            "extra_snippets": {
                "type": "boolean",
                "default": True,
            },
            "conversation_id": {
                "type": "string",
                "minLength": 1,
            },
        },
        "additionalProperties": False,
    },
    system_usage=(
        "Use when current facts, news, recent changes, or external references are needed. "
        "Prefer this before web.ingest_url. After reviewing the result list, use web.ingest_url "
        "only for one or two promising URLs that you actually need to read in depth."
    ),
    display_name="Web Search",
    tags=("web", "search", "brave"),
)


def _truncate(text: str, limit: int = 140) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _escape_md_label(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "result"
    return raw.replace("[", r"\[").replace("]", r"\]")


def _render_search_result_block(item: dict[str, Any]) -> str:
    url = str(item.get("url") or item.get("canonical_url") or "").strip()
    title = _escape_md_label(str(item.get("title") or url or "result"))
    snippet = str(item.get("snippet") or "").strip()
    extra = [str(x).strip() for x in (item.get("extra_snippets") or []) if str(x or "").strip()]
    age = str(item.get("age") or item.get("page_age") or "").strip()
    domain = str(item.get("domain") or "").strip()

    lines: list[str] = []
    if url:
        lines.append(f"[{title}]({url})")
        lines.append(url)
    else:
        lines.append(title)
    meta_bits = [bit for bit in (domain, age) if bit]
    if meta_bits:
        lines.append(" · ".join(meta_bits))
    summary_parts = [snippet, *extra[:2]]
    summary_parts = [part for part in summary_parts if part]
    if summary_parts:
        lines.append(_truncate(" ".join(summary_parts), 320))
    return "\n".join(lines).strip()


def _render_search_results_markdown(query: str, results: list[dict[str, Any]]) -> str:
    header = f"Brave web search for '{query}' returned {len(results)} results."
    if not results:
        return header
    blocks = [_render_search_result_block(item) for item in results if isinstance(item, dict)]
    blocks = [b for b in blocks if b]
    if not blocks:
        return header
    return header + "\n\n" + "\n\n".join(blocks)


def _load_brave_provider() -> tuple[str, str]:
    providers = load_provider_defs()
    provider = providers.get("brave")
    if provider is None:
        raise WebSearchError("Brave provider is not configured. Add [providers.brave] to config.toml and config.secrets.toml.")
    if not provider.enabled:
        raise WebSearchError("Brave provider is disabled.")
    if (provider.type or "").strip().lower() != "brave":
        raise WebSearchError("Provider 'brave' is configured with the wrong type.")
    if not (provider.api_key or "").strip():
        raise WebSearchError("Brave API key is missing. Add [providers.brave].api_key to config.secrets.toml.")
    return provider.api_key, provider.base_url or "https://api.search.brave.com/res/v1"


def execute(arguments: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error="query is required")

    conversation_id = str(arguments.get("conversation_id") or ctx.conversation_id or "").strip()
    count = max(1, min(int(arguments.get("count") or 8), 10))
    country = str(arguments.get("country") or "us").strip() or "us"
    search_lang = str(arguments.get("search_lang") or "en").strip() or "en"
    safesearch = str(arguments.get("safesearch") or "moderate").strip() or "moderate"
    freshness = str(arguments.get("freshness") or "").strip() or None
    extra_snippets = bool(arguments.get("extra_snippets", True))

    try:
        api_key, base_url = _load_brave_provider()
        search_payload = brave_web_search(
            api_key=api_key,
            base_url=base_url,
            query=query,
            count=count,
            country=country,
            search_lang=search_lang,
            safesearch=safesearch,
            freshness=freshness,
            extra_snippets=extra_snippets,
        )
    except WebSearchError as exc:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=str(exc), display_text=f"Web search failed for '{query}'.")
    except Exception as exc:
        return ToolResult(ok=False, tool=TOOL_SPEC.name, error=f"{type(exc).__name__}: {exc}", display_text=f"Web search failed for '{query}'.")

    results = list(search_payload.get("results") or [])
    search_id = None
    project_id = ctx.project_id

    if conversation_id:
        try:
            with db_session() as conn:
                if project_id is None:
                    project_id = db_get_conversation_project_id(conn, conversation_id)
                search_id = create_web_search_conn(
                    conn,
                    query_text=query,
                    provider="brave",
                    mode="explicit",
                    project_id=project_id,
                    conversation_id=conversation_id,
                    request_message_id=None,
                )
                replace_web_search_results_conn(
                    conn,
                    search_id=int(search_id),
                    results=results,
                )
        except Exception as exc:
            return ToolResult(
                ok=False,
                tool=TOOL_SPEC.name,
                error=f"Search succeeded but persistence failed: {type(exc).__name__}: {exc}",
                result={
                    "query": search_payload.get("query"),
                    "results": results,
                    "result_count": len(results),
                    "provider": "brave",
                },
                display_text=f"Web search found {len(results)} results for '{query}', but could not store the search receipt.",
            )

    display_text = _render_search_results_markdown(query, results)

    return ToolResult(
        ok=True,
        tool=TOOL_SPEC.name,
        result={
            "provider": "brave",
            "conversation_id": conversation_id or None,
            "project_id": project_id,
            "search_id": search_id,
            "query": search_payload.get("query"),
            "query_info": search_payload.get("query_info"),
            "mixed": search_payload.get("mixed"),
            "results": results,
            "result_count": len(results),
            "next_step_hint": "Use web.ingest_url with one of the returned URLs if you need to read a page in depth.",
        },
        display_text=display_text,
        event_kind="tool_result",
    )
