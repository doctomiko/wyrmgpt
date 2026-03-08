import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.db import (  # noqa: E402
    db_session,
    init_schema,
    get_conversation_transcript_status,
    refresh_conversation_transcript_artifact,
)


def list_conversation_ids(include_archived: bool = False) -> list[str]:
    with db_session() as conn:
        if include_archived:
            rows = conn.execute("SELECT id FROM conversations ORDER BY updated_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT id FROM conversations WHERE archived = 0 ORDER BY updated_at DESC").fetchall()
    return [r["id"] for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--force", action="store_true", help="rebuild even if transcript artifact already exists")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    print("Running init_schema...")
    init_schema()
    print("Done.")

    ids = list_conversation_ids(include_archived=args.include_archived)
    if args.limit is not None:
        ids = ids[: args.limit]

    print(f"Processing {len(ids)} conversations force={args.force}")

    ok = 0
    skip = 0
    fail = 0

    for i, cid in enumerate(ids, start=1):
        try:
            status = get_conversation_transcript_status(cid)
            missing = bool(status.get("artifact_missing"))
            stale = bool(status.get("stale"))

            if not args.force and not missing:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} (transcript exists; stale={stale})")
                continue

            out = refresh_conversation_transcript_artifact(
                cid,
                force_full=bool(args.force or missing),
                reason="backfill-script",
            )
            ok += 1
            print(
                f"[{i}/{len(ids)}] ok   {cid} "
                f"(full_rebuild={out.get('full_rebuild')} appended={out.get('appended_message_count')} stale_after={out.get('stale_after_refresh')})"
            )
            if args.sleep:
                time.sleep(args.sleep)
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(ids)}] FAIL {cid}: {e!r}")

    print(json.dumps({"ok": ok, "skipped": skip, "failed": fail}, indent=2))


if __name__ == "__main__":
    main()
