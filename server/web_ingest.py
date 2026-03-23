from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .logging_helper import log_warn
from .markdown_helper import extract_explicit_urls
from .db import (
    db_session, get_conversation_project_id,
    upsert_web_source_conn, insert_web_source_snapshot_conn,
    get_web_snapshot_bundle_conn, upsert_artifact_text,
    retain_conversation_artifact_conn, reindex_artifact_by_id,
)
from .artifactor import build_web_artifact_payload
#from .artifactor import artifact_web_snapshot
from .web_fetch import fetch_web_url


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
    results: list[dict] = []
    errors: list[str] = []
    artifact_ids_to_reindex: list[str] = []

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

                snapshot, source = get_web_snapshot_bundle_conn(conn, snapshot_id)

                payload = build_web_artifact_payload(
                    snapshot=snapshot,
                    source=source,
                )

                artifact_id = None
                artifact_error = None
                if payload:
                    artifact_id = upsert_artifact_text(
                        conn,
                        source_kind=payload["source_kind"],
                        source_id=payload["source_id"],
                        title=payload["title"],
                        scope_type="conversation",
                        scope_id=conversation_id,
                        text=payload["text"],
                    )
                else:
                    artifact_error = "no artifact payload could be built from fetched content"
                    errors.append(f"{url}: {artifact_error}")

                if artifact_id:
                    artifact_ids.append(artifact_id)
                    artifact_ids_to_reindex.append(artifact_id)

                    retain_conversation_artifact_conn(
                        conn,
                        conversation_id=conversation_id,
                        artifact_id=artifact_id,
                        origin_kind="user_url",
                        retention_state="forced",
                        carry_summary_text=None,
                        inclusion_kind="whole",
                        retrieval_channel="manual",
                        message_id=request_message_id,
                        note_text=f"Explicit URL injected by user: {url}",
                        meta_json={
                            "url": url,
                            "source_id": source_id,
                            "snapshot_id": snapshot_id,
                            "fetch_method": fetch_method,
                        },
                        increment_include_count=True,
                    )
                results.append({
                    "url": url,
                    "source_id": source_id,
                    "snapshot_id": snapshot_id,
                    "artifact_id": artifact_id,
                    "artifact_created": bool(artifact_id),
                    "artifact_error": artifact_error,
                    "final_url": fetched.get("final_url"),
                    "content_type": fetched.get("content_type"),
                    "http_status": fetched.get("http_status"),
                })
            except Exception as e:
                errors.append(f"{url}: {type(e).__name__}: {e}")
                log_warn(f"URL ingest failed for {url}: {e}")

    for artifact_id in artifact_ids_to_reindex:
        try:
            reindex_artifact_by_id(artifact_id)
        except Exception as e:
            errors.append(f"reindex {artifact_id}: {type(e).__name__}: {e}")
            log_warn(f"Artifact reindex failed for {artifact_id}: {e}")

    return {
        "ok": len(errors) == 0 and len(artifact_ids) == len(urls),
        "detected": len(urls),
        "snapshots_created": created_snapshots,
        "ingested": len(artifact_ids),
        "urls": urls,
        "artifact_ids": artifact_ids,
        "results": results,
        "errors": errors,
        "request_message_id": request_message_id,
    }