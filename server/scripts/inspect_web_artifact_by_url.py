import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[0]
# If the script is dropped into server/scripts, ROOT should be repo root after adjustment below.
if (ROOT / 'server').exists():
    REPO_ROOT = ROOT
else:
    REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.db import db_session, get_web_source_by_url, hydrate_artifact_content_text


def _safe_json_load(text: Any) -> Any:
    if text is None:
        return None
    if isinstance(text, (dict, list)):
        return text
    s = str(text).strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return text
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n...[truncated]..."


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Inspect the web source, latest snapshot, and artifact(s) associated with a URL."
    )
    ap.add_argument("url", help="URL to inspect")
    ap.add_argument(
        "--all-artifacts",
        action="store_true",
        help="Show all artifact metadata tied to any snapshot of this URL, not just the latest usable snapshot",
    )
    ap.add_argument(
        "--full-text",
        action="store_true",
        help="Print full artifact text instead of a preview",
    )
    ap.add_argument(
        "--preview-chars",
        type=int,
        default=3000,
        help="Preview length when not using --full-text (default: 3000)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of pretty text",
    )
    args = ap.parse_args()

    source = get_web_source_by_url(args.url)
    if not source:
        msg = {"ok": False, "error": "No web_source found for URL", "url": args.url}
        if args.json:
            print(json.dumps(msg, ensure_ascii=False, indent=2))
        else:
            print(f"No web_source found for URL: {args.url}")
        return 1

    with db_session() as conn:
        snapshots = [
            dict(r)
            for r in conn.execute(
                """
                SELECT *
                FROM web_source_snapshots
                WHERE source_id = ?
                ORDER BY is_pinned DESC, fetched_at DESC, id DESC
                """,
                (int(source["id"]),),
            ).fetchall()
        ]

        latest_snapshot = snapshots[0] if snapshots else None
        latest_usable_snapshot = None
        if snapshots:
            for snap in snapshots:
                expires_at = (snap.get("expires_at") or "").strip()
                if int(snap.get("is_pinned") or 0) == 1:
                    latest_usable_snapshot = snap
                    break
                if not expires_at:
                    latest_usable_snapshot = snap
                    break
            if latest_usable_snapshot is None:
                latest_usable_snapshot = latest_snapshot

        snapshot_ids = [int(s["id"]) for s in snapshots]
        artifacts: list[dict] = []
        if snapshot_ids:
            qmarks = ",".join("?" for _ in snapshot_ids)
            rows = conn.execute(
                f"""
                SELECT *
                FROM artifacts
                WHERE is_deleted = 0
                  AND source_kind = 'web:snapshot'
                  AND source_id IN ({qmarks})
                ORDER BY updated_at DESC, id DESC
                """,
                tuple(str(x) for x in snapshot_ids),
            ).fetchall()
            for row in rows:
                art = dict(row)
                art["content_text"] = hydrate_artifact_content_text(conn, art["id"])
                art["meta_json"] = _safe_json_load(art.get("meta_json"))
                art["tags_json"] = _safe_json_load(art.get("tags_json"))
                chunk_count_row = conn.execute(
                    "SELECT COUNT(*) AS n FROM corpus_chunks WHERE artifact_id = ?",
                    (art["id"],),
                ).fetchone()
                art["chunk_count"] = int(chunk_count_row["n"] or 0) if chunk_count_row else 0
                artifacts.append(art)

        selected_artifact = None
        if latest_usable_snapshot:
            latest_snapshot_id = str(latest_usable_snapshot["id"])
            for art in artifacts:
                if (art.get("source_id") or "") == latest_snapshot_id:
                    selected_artifact = art
                    break
        if selected_artifact is None and artifacts:
            selected_artifact = artifacts[0]

        payload = {
            "ok": True,
            "requested_url": args.url,
            "source": {
                "id": source.get("id"),
                "canonical_url": source.get("canonical_url"),
                "domain": source.get("domain"),
                "project_id": source.get("project_id"),
                "created_by": source.get("created_by"),
                "created_at": source.get("created_at"),
                "updated_at": source.get("updated_at"),
            },
            "latest_snapshot": latest_snapshot,
            "latest_usable_snapshot": latest_usable_snapshot,
            "selected_artifact": None,
            "artifacts": [],
        }

        if selected_artifact:
            payload["selected_artifact"] = {
                "id": selected_artifact.get("id"),
                "title": selected_artifact.get("title"),
                "source_kind": selected_artifact.get("source_kind"),
                "source_id": selected_artifact.get("source_id"),
                "scope_type": selected_artifact.get("scope_type"),
                "scope_id": selected_artifact.get("scope_id"),
                "scope_uuid": selected_artifact.get("scope_uuid"),
                "content_hash": selected_artifact.get("content_hash"),
                "content_bytes": selected_artifact.get("content_bytes"),
                "updated_at": selected_artifact.get("updated_at"),
                "chunk_count": selected_artifact.get("chunk_count"),
                "meta_json": selected_artifact.get("meta_json"),
                "tags_json": selected_artifact.get("tags_json"),
                "text": selected_artifact.get("content_text") or "",
            }

        if args.all_artifacts:
            for art in artifacts:
                payload["artifacts"].append(
                    {
                        "id": art.get("id"),
                        "title": art.get("title"),
                        "source_id": art.get("source_id"),
                        "scope_type": art.get("scope_type"),
                        "scope_id": art.get("scope_id"),
                        "updated_at": art.get("updated_at"),
                        "chunk_count": art.get("chunk_count"),
                        "content_bytes": art.get("content_bytes"),
                    }
                )

    if args.json:
        out = payload.copy()
        if out["selected_artifact"] and not args.full_text:
            out["selected_artifact"] = dict(out["selected_artifact"])
            out["selected_artifact"]["text"] = _truncate(
                out["selected_artifact"].get("text") or "",
                int(args.preview_chars or 0),
            )
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print(f"Requested URL:      {payload['requested_url']}")
    print(f"Canonical URL:      {payload['source']['canonical_url']}")
    print(f"Domain:             {payload['source']['domain']}")
    print(f"Web source id:      {payload['source']['id']}")
    print(f"Project id:         {payload['source']['project_id']}")
    print(f"Source created_by:  {payload['source']['created_by']}")
    print(f"Source created_at:  {payload['source']['created_at']}")
    print(f"Source updated_at:  {payload['source']['updated_at']}")
    print()

    if payload["latest_snapshot"]:
        snap = payload["latest_snapshot"]
        print("Latest snapshot:")
        print(f"  id:              {snap.get('id')}")
        print(f"  fetched_at:      {snap.get('fetched_at')}")
        print(f"  fetch_method:    {snap.get('fetch_method')}")
        print(f"  http_status:     {snap.get('http_status')}")
        print(f"  final_url:       {snap.get('final_url')}")
        print(f"  content_type:    {snap.get('content_type')}")
        print(f"  expires_at:      {snap.get('expires_at')}")
        print(f"  is_pinned:       {snap.get('is_pinned')}")
        print(f"  error_text:      {snap.get('error_text')}")
        print(f"  raw_text chars:  {len((snap.get('raw_text') or ''))}")
        print(f"  raw_html chars:  {len((snap.get('raw_html') or ''))}")
        print()
    else:
        print("No snapshots found for this URL.\n")

    if payload["selected_artifact"]:
        art = payload["selected_artifact"]
        print("Selected artifact:")
        print(f"  id:              {art.get('id')}")
        print(f"  title:           {art.get('title')}")
        print(f"  source_kind:     {art.get('source_kind')}")
        print(f"  source_id:       {art.get('source_id')}")
        print(f"  scope_type:      {art.get('scope_type')}")
        print(f"  scope_id:        {art.get('scope_id')}")
        print(f"  scope_uuid:      {art.get('scope_uuid')}")
        print(f"  content_hash:    {art.get('content_hash')}")
        print(f"  content_bytes:   {art.get('content_bytes')}")
        print(f"  updated_at:      {art.get('updated_at')}")
        print(f"  chunk_count:     {art.get('chunk_count')}")
        if art.get('meta_json') is not None:
            print(f"  meta_json:       {json.dumps(art.get('meta_json'), ensure_ascii=False)}")
        print()
        print("Artifact text:")
        text = art.get("text") or ""
        print(text if args.full_text else _truncate(text, int(args.preview_chars or 0)))
    else:
        print("No artifact found for this URL's snapshots.")

    if args.all_artifacts:
        print()
        print("All related artifacts:")
        for art in payload["artifacts"]:
            print(
                f"  - {art['id']} | snapshot={art['source_id']} | scope={art['scope_type']}:{art['scope_id']} | "
                f"chunks={art['chunk_count']} | updated={art['updated_at']} | title={art['title']}"
            )

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
