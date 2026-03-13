import argparse
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db import init_schema
from server.openai_import import (
    conversation_already_imported,
    ensure_openai_import_tables,
    import_conversation,
    import_feedback,
    upsert_asset_inventory,
    upsert_user_profile,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_zip", help="Path to OpenAI export zip")
    ap.add_argument("--prefix", default="oaiexport-", help="Prefix for local imported conversation IDs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-existing", action="store_true", default=False)
    ap.add_argument("--refresh-transcripts", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args()

    init_schema()
    ensure_openai_import_tables()

    zip_path = Path(args.export_zip).expanduser().resolve()
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing zip: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        zip_infos = zf.infolist()
        zip_names = [zi.filename for zi in zip_infos if not zi.is_dir()]
        upsert_asset_inventory(zip_infos)

        raw_user = json.loads(zf.read("user.json")) if "user.json" in zf.namelist() else {}
        if isinstance(raw_user, dict):
            upsert_user_profile(raw_user)

        raw_conversations = json.loads(zf.read("conversations.json"))
        if not isinstance(raw_conversations, list):
            raise RuntimeError("Expected conversations.json to be a JSON list")

        conversations = raw_conversations[: args.limit] if args.limit else raw_conversations

        imported_conversations = 0
        skipped_conversations = 0
        failed_conversations = 0
        inserted_messages = 0
        inserted_attachments = 0

        for idx, convo in enumerate(conversations, start=1):
            try:
                export_id = str(convo.get("id") or convo.get("conversation_id") or "").strip()
                if not export_id:
                    skipped_conversations += 1
                    print(f"[{idx}/{len(conversations)}] skip (missing export conversation id)")
                    continue

                local_cid = f"{args.prefix}{export_id}"
                if args.skip_existing and conversation_already_imported(local_cid):
                    skipped_conversations += 1
                    print(f"[{idx}/{len(conversations)}] skip {local_cid} (already imported)")
                    continue

                result = import_conversation(
                    convo=convo,
                    prefix=args.prefix,
                    zip_names=zip_names,
                    refresh_transcripts=args.refresh_transcripts,
                    reindex=args.reindex,
                )

                imported_conversations += 1
                inserted_messages += int(result["inserted_messages"])
                inserted_attachments += int(result["inserted_attachments"])
                state = "imported" if result["inserted_any"] else "metadata-updated"
                print(
                    f"[{idx}/{len(conversations)}] {state} "
                    f"{result['local_conversation_id']} "
                    f"({result['branch_nodes']} branch nodes)"
                )

            except Exception as e:
                failed_conversations += 1
                print(f"[{idx}/{len(conversations)}] FAIL: {e!r}")

        imported_feedback = 0
        if "message_feedback.json" in zf.namelist():
            raw_feedback = json.loads(zf.read("message_feedback.json"))
            if isinstance(raw_feedback, list):
                imported_feedback = import_feedback(raw_feedback, args.prefix)

    summary = {
        "conversations_imported_or_updated": imported_conversations,
        "conversations_skipped": skipped_conversations,
        "conversations_failed": failed_conversations,
        "messages_inserted": inserted_messages,
        "attachments_cataloged": inserted_attachments,
        "feedback_rows_imported": imported_feedback,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
