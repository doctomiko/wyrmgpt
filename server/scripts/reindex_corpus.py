import argparse
import json
import os
import sys
import time

# Allow running as a script: py .\server\scripts\reindex_corpus.py ...
# Adds repo root (two levels up) to sys.path so "import server.*" works.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.config import load_import_config
from server.db import db_session, reindex_corpus_for_conversation, ensure_files_artifacted_for_conversation, _migrate_schema_v9

def list_all_conversation_ids(include_archived: bool = False) -> list[str]:
    """
    Conversation rows are soft-archived via conversations.archived (0/1).
    There is no is_deleted column in this schema.
    """
    with db_session() as conn:
        if include_archived:
            rows = conn.execute(
                """
                SELECT id
                FROM conversations
                ORDER BY updated_at DESC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id
                FROM conversations
                WHERE archived = 0
                ORDER BY updated_at DESC
                """
            ).fetchall()

        return [r["id"] for r in rows]

def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m = int(seconds // 60)
    s = seconds - (m * 60)
    return f"{m}m{s:04.1f}s"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conversation_id", nargs="?", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--include-global", action="store_true")
    ap.add_argument("--limit-artifacts", type=int, default=None)
    ap.add_argument("--limit-conversations", type=int, default=None)
    ap.add_argument("--yes", action="store_true", help="Skip confirmation prompt when reindexing ALL conversations")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary at end")
    args = ap.parse_args()

    import_cfg = load_import_config()

    if args.conversation_id:
        cid = args.conversation_id.strip()
        result = reindex_corpus_for_conversation(
            conversation_id=cid,
            force=args.force,
            include_global=args.include_global,
            limit_artifacts=args.limit_artifacts,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(result, indent=2))
        return

    # Ensure corpus schema exists even when server isn't running
    with db_session() as conn:
        _migrate_schema_v9(conn)
        conn.commit()

    # No conversation_id => ALL conversations
    convo_ids = list_all_conversation_ids(include_archived=False)
    if args.limit_conversations is not None:
        convo_ids = convo_ids[: int(args.limit_conversations)]

    n_total = len(convo_ids)
    print("")
    print("WARNING: You did NOT specify a conversation_id.")
    print(f"This will reindex the corpus for ALL conversations ({n_total}).")
    print("This can take a while and will write to corpus_chunks / corpus_fts.")
    print("")

    if not args.yes:
        resp = input("Type YES to proceed: ").strip()
        if resp != "YES":
            print("Aborted.")
            return

    started = time.time()
    ok = 0
    fail = 0
    indexed_artifacts_total = 0
    skipped_artifacts_total = 0
    chunks_total = 0

    failures: list[dict] = []

    # Simple progress report
    for i, cid in enumerate(convo_ids, start=1):
        ensure_files_artifacted_for_conversation(
            conversation_id=cid,
            limit_per_scope=import_cfg.ensure_files_limit_per_scope,
            include_global=True,
        )
        #ensure_files_artifacted_for_conversation(
        #    conversation_id=cid,
        #    limit_per_scope=25,
        #    include_global=True,
        #)

        prefix = f"[{i}/{n_total}]"
        print(f"{prefix} Reindexing conversation {cid} ...", end="", flush=True)

        t0 = time.time()
        try:
            result = reindex_corpus_for_conversation(
                conversation_id=cid,
                force=args.force,
                include_global=args.include_global,
                limit_artifacts=args.limit_artifacts,
            )
            dt = time.time() - t0

            if result.get("ok") is True:
                ok += 1
                indexed_artifacts_total += int(result.get("indexed_artifacts") or 0)
                skipped_artifacts_total += int(result.get("skipped_artifacts") or 0)
                chunks_total += int(result.get("total_chunks_written") or 0)

                print(
                    f" ok in {fmt_time(dt)} | "
                    f"indexed={result.get('indexed_artifacts')} "
                    f"skipped={result.get('skipped_artifacts')} "
                    f"chunks={result.get('total_chunks_written')}"
                )
            else:
                fail += 1
                print(f" FAILED in {fmt_time(dt)} | {result.get('error')}")
                failures.append({"conversation_id": cid, "result": result})
        except Exception as e:
            dt = time.time() - t0
            fail += 1
            print(f" EXCEPTION in {fmt_time(dt)} | {e!r}")
            failures.append({"conversation_id": cid, "error": repr(e)})

        # rolling totals line
        elapsed = time.time() - started
        print(
            f"    totals: ok={ok} fail={fail} "
            f"artifacts_indexed={indexed_artifacts_total} "
            f"artifacts_skipped={skipped_artifacts_total} "
            f"chunks_written={chunks_total} "
            f"elapsed={fmt_time(elapsed)}"
        )

    elapsed = time.time() - started
    summary = {
        "ok": True if fail == 0 else False,
        "conversations_total": n_total,
        "conversations_ok": ok,
        "conversations_failed": fail,
        "artifacts_indexed_total": indexed_artifacts_total,
        "artifacts_skipped_total": skipped_artifacts_total,
        "chunks_written_total": chunks_total,
        "elapsed_seconds": elapsed,
        "failures": failures,
    }

    print("")
    print("Done.")
    print(json.dumps(summary, indent=2) if args.json else json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()