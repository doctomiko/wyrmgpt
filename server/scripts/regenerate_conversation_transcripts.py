import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.db import (  # noqa: E402
    db_session,
    init_schema,
    db_refresh_conversation_transcript_artifact,
)


def list_conversation_ids(*, include_archived: bool = False) -> list[str]:
    with db_session() as conn:
        if include_archived:
            rows = conn.execute(
                "SELECT id FROM conversations ORDER BY COALESCE(updated_at, created_at, '') DESC, id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM conversations WHERE archived = 0 ORDER BY COALESCE(updated_at, created_at, '') DESC, id DESC"
            ).fetchall()
    return [str(r["id"]).strip() for r in rows if str(r["id"]).strip()]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Force-regenerate conversation transcript artifacts so scope metadata and corpus entries are rebuilt."
    )
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument(
        "--conversation-id",
        action="append",
        dest="conversation_ids",
        default=None,
        help="restrict to one or more specific conversation ids",
    )
    args = ap.parse_args()

    print("Running init_schema...")
    init_schema()
    print("Done.")

    ids = [cid.strip() for cid in (args.conversation_ids or []) if cid and cid.strip()]
    if not ids:
        ids = list_conversation_ids(include_archived=args.include_archived)
    if args.limit is not None:
        ids = ids[: args.limit]

    print(f"Regenerating {len(ids)} conversation transcript artifacts")

    ok = 0
    fail = 0
    for i, cid in enumerate(ids, start=1):
        try:
            out = db_refresh_conversation_transcript_artifact(
                cid,
                force_full=True,
                reason="transcript-regeneration-script",
            )
            ok += 1
            print(
                f"[{i}/{len(ids)}] ok   {cid} "
                f"(artifact_id={out.get('artifact_id')} full_rebuild={out.get('full_rebuild')} "
                f"appended={out.get('appended_message_count')} stale_after={out.get('stale_after_refresh')})"
            )
            if args.sleep:
                time.sleep(args.sleep)
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(ids)}] FAIL {cid}: {e!r}")

    print(json.dumps({"ok": ok, "failed": fail}, indent=2))


if __name__ == "__main__":
    main()
