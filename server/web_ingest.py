from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .logging_helper import log_warn
from .markdown_helper import extract_explicit_urls
from .db import (
    db_session,
    get_conversation_project_id,
    upsert_web_source_conn,
    insert_web_source_snapshot_conn,
)
from .web_fetch import fetch_web_url
from .artifactor import artifact_web_snapshot


DEFAULT_WEB_TTL_SECONDS = 7 * 24 * 60 * 60


def _expires_at_from_ttl(ttl_seconds: int | None) -> str | None:
    if not ttl_seconds or ttl_seconds <= 0:
        return None
    dt = datetime.now(timezone.utc) + timedelta(seconds=int(ttl_seconds))
    return dt.replace(microsecond=0).isoformat()


def ingest_urls_from_user_message(
    *,
    conversation_id: str,
    request_message_id: int | None,
    raw_message: str,
    max_urls: int = 3,
    fetch_method: str = "python",
) -> dict:
    urls = extract_explicit_urls(raw_message or "")
    if not urls:
        return {"ok": True, "detected": 0, "ingested": 0, "urls": []}

    urls = urls[: max(0, int(max_urls))]

    touched_sources = 0
    created_snapshots = 0
    artifact_ids: list[str] = []
    errors: list[str] = []

    with db_session() as conn:
        project_id = get_conversation_project_id(conn, conversation_id)

        for url in urls:
            try:
                source_id = upsert_web_source_conn(
                    conn,
                    url=url,
                    project_id=project_id,
                    created_by="user",
                )
                touched_sources += 1

                fetched = fetch_web_url(url)

                snapshot_id = insert_web_source_snapshot_conn(
                    conn,
                    source_id=source_id,
                    fetch_method=fetch_method,
                    http_status=fetched.get("http_status"),
                    final_url=fetched.get("final_url"),
                    content_type=fetched.get("content_type"),
                    etag=fetched.get("etag"),
                    last_modified=fetched.get("last_modified"),
                    headers_json=json.dumps(fetched.get("headers") or {}),
                    raw_html=fetched.get("raw_html"),
                    raw_text=fetched.get("raw_text"),
                    ttl_seconds=DEFAULT_WEB_TTL_SECONDS,
                    expires_at=_expires_at_from_ttl(DEFAULT_WEB_TTL_SECONDS),
                    error_text=fetched.get("error_text"),
                )
                created_snapshots += 1

                artifact_id = artifact_web_snapshot(
                    snapshot_id=snapshot_id,
                    conversation_id=conversation_id,
                )
                if artifact_id:
                    artifact_ids.append(artifact_id)

            except Exception as e:
                errors.append(f"{url}: {type(e).__name__}: {e}")
                log_warn(f"URL ingest failed for {url}: {e}")

    return {
        "ok": len(errors) == 0,
        "detected": len(urls),
        "ingested": created_snapshots,
        "urls": urls,
        "artifact_ids": artifact_ids,
        "errors": errors,
        "request_message_id": request_message_id,
    }