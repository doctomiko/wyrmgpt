from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests


BRAVE_DEFAULT_BASE_URL = "https://api.search.brave.com/res/v1"


class WebSearchError(RuntimeError):
    """Raised when the configured web search provider fails."""


@dataclass(frozen=True)
class WebSearchResultItem:
    rank: int
    title: str
    url: str
    canonical_url: str
    domain: str
    snippet: str
    extra_snippets: tuple[str, ...] = ()
    provider_result_id: str | None = None
    age: str | None = None
    page_age: str | None = None
    language: str | None = None
    family_friendly: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        out = {
            "rank": self.rank,
            "title": self.title,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "domain": self.domain,
            "snippet": self.snippet,
        }
        if self.extra_snippets:
            out["extra_snippets"] = list(self.extra_snippets)
        if self.provider_result_id:
            out["provider_result_id"] = self.provider_result_id
        if self.age:
            out["age"] = self.age
        if self.page_age:
            out["page_age"] = self.page_age
        if self.language:
            out["language"] = self.language
        if self.family_friendly is not None:
            out["family_friendly"] = self.family_friendly
        return out


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _domain_from_url(url: str) -> str:
    try:
        host = (urlparse(url).netloc or "").strip().lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _normalize_extra_snippets(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            out.append(text)
    return tuple(out)


def _coerce_result_item(raw: dict[str, Any], rank: int) -> WebSearchResultItem | None:
    url = _clean_text(raw.get("url"))
    if not url:
        return None
    canonical_url = _clean_text(raw.get("meta_url", {}).get("url")) or url
    title = _clean_text(raw.get("title")) or canonical_url
    snippet = _clean_text(raw.get("description"))
    domain = _clean_text(raw.get("meta_url", {}).get("hostname")) or _domain_from_url(canonical_url)
    provider_result_id = _clean_text(raw.get("profile", {}).get("long_name")) or None
    family_friendly = raw.get("family_friendly")
    if family_friendly is not None:
        family_friendly = bool(family_friendly)

    return WebSearchResultItem(
        rank=rank,
        title=title,
        url=url,
        canonical_url=canonical_url,
        domain=domain,
        snippet=snippet,
        extra_snippets=_normalize_extra_snippets(raw.get("extra_snippets")),
        provider_result_id=provider_result_id,
        age=_clean_text(raw.get("age")) or None,
        page_age=_clean_text(raw.get("page_age")) or None,
        language=_clean_text(raw.get("language")) or None,
        family_friendly=family_friendly,
    )


def brave_web_search(
    *,
    api_key: str,
    query: str,
    count: int = 8,
    country: str = "us",
    search_lang: str = "en",
    safesearch: str = "moderate",
    freshness: str | None = None,
    extra_snippets: bool = True,
    base_url: str = BRAVE_DEFAULT_BASE_URL,
    timeout: int = 20,
) -> dict[str, Any]:
    q = _clean_text(query)
    if not q:
        raise ValueError("query is required")
    token = _clean_text(api_key)
    if not token:
        raise ValueError("Brave API key is missing")

    url = f"{(base_url or BRAVE_DEFAULT_BASE_URL).rstrip('/')}/web/search"
    params: dict[str, Any] = {
        "q": q,
        "count": max(1, min(int(count), 20)),
        "country": _clean_text(country) or "us",
        "search_lang": _clean_text(search_lang) or "en",
        "safesearch": _clean_text(safesearch) or "moderate",
    }
    fresh = _clean_text(freshness)
    if fresh:
        params["freshness"] = fresh
    if extra_snippets:
        params["extra_snippets"] = "true"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": token,
        "User-Agent": "WyrmGPT/0.1 (+local personal knowledge cockpit)",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise WebSearchError(f"Brave request failed: {type(exc).__name__}: {exc}") from exc

    try:
        payload = resp.json()
    except Exception:
        payload = None

    if resp.status_code >= 400:
        detail = None
        if isinstance(payload, dict):
            detail = _clean_text(payload.get("message") or payload.get("error") or payload.get("detail"))
        if not detail:
            detail = _clean_text(resp.text)[:400]
        raise WebSearchError(f"Brave search failed ({resp.status_code}): {detail or 'unknown error'}")

    if not isinstance(payload, dict):
        raise WebSearchError("Brave search returned a non-JSON response")

    raw_results = payload.get("web", {}).get("results")
    if not isinstance(raw_results, list):
        raw_results = []

    results: list[WebSearchResultItem] = []
    for idx, raw in enumerate(raw_results, start=1):
        if not isinstance(raw, dict):
            continue
        item = _coerce_result_item(raw, idx)
        if item is not None:
            results.append(item)

    query_node = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    mixed_node = payload.get("mixed") if isinstance(payload.get("mixed"), dict) else {}

    return {
        "ok": True,
        "provider": "brave",
        "query": {
            "text": q,
            "country": params["country"],
            "search_lang": params["search_lang"],
            "safesearch": params["safesearch"],
            "freshness": params.get("freshness"),
            "count": params["count"],
            "extra_snippets": bool(extra_snippets),
        },
        "results": [item.as_dict() for item in results],
        "result_count": len(results),
        "mixed": mixed_node,
        "query_info": query_node,
    }
