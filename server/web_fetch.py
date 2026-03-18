from __future__ import annotations

import requests


def fetch_web_url(url: str, timeout: int = 15) -> dict:
    headers = {
        "User-Agent": "WyrmGPT/0.1 (+local personal knowledge cockpit)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        content_type = resp.headers.get("content-type", "")
        text = resp.text or ""

        return {
            "http_status": resp.status_code,
            "final_url": str(resp.url),
            "content_type": content_type,
            "etag": resp.headers.get("etag"),
            "last_modified": resp.headers.get("last-modified"),
            "headers": dict(resp.headers),
            "raw_html": text,
            "raw_text": None,
            "error_text": None,
        }
    except Exception as e:
        return {
            "http_status": None,
            "final_url": url,
            "content_type": None,
            "etag": None,
            "last_modified": None,
            "headers": {},
            "raw_html": None,
            "raw_text": None,
            "error_text": f"{type(e).__name__}: {e}",
        }