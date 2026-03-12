import argparse
import json
import sys
import time
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import load_context_config, load_openai_config, load_summary_config
from server.context import _get_prompt
from server.db import (
    db_session,
    get_transcript_for_summary,
    init_schema,
    save_conversation_summary_artifact,
)
from server.summary_helper import summarize_conversation_text


def list_conversation_ids(include_archived: bool = False) -> list[str]:
    with db_session() as conn:
        if include_archived:
            rows = conn.execute(
                "SELECT id FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM conversations WHERE archived = 0 ORDER BY updated_at DESC"
            ).fetchall()
    return [r["id"] for r in rows]


def has_summary(conn, conversation_id: str) -> bool:
    aid_row = conn.execute(
        """
        SELECT id, summary_text
        FROM artifacts
        WHERE source_kind = 'conversation:summary'
          AND source_id = ?
          AND is_deleted = 0
        """,
        (conversation_id,),
    ).fetchone()
    return bool(aid_row and (aid_row["summary_text"] or "").strip())


def main() -> None:
    oai_cfg = load_openai_config()
    ctx_cfg = load_context_config()
    sum_cfg = load_summary_config()

    ap = argparse.ArgumentParser()
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--model",
        default=oai_cfg.summary_model or ctx_cfg.estimate_model or "gpt-5-mini",
    )
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    print("Running init_schema...")
    init_schema()
    print("Done.")

    if not (oai_cfg.open_ai_apikey or "").strip():
        raise RuntimeError("OpenAI API key not loaded. Aborting.")

    client = OpenAI(api_key=oai_cfg.open_ai_apikey)

    ids = list_conversation_ids(include_archived=args.include_archived)
    if args.limit is not None:
        ids = ids[: args.limit]

    print(
        f"Summarizing {len(ids)} conversations using model={args.model} "
        f"force={args.force}"
    )

    ok = 0
    skip = 0
    fail = 0

    system_prompt = _get_prompt(
        default_prompt=sum_cfg.summary_conversation_prompt,
        filepath=sum_cfg.summary_conversation_prompt_file,
        cfg_default="SUMMARY_CONVO_PROMPT",
        cfg_filepath="SUMMARY_CONVO_PROMPT_FILE",
    )

    for i, cid in enumerate(ids, start=1):
        try:
            with db_session() as conn:
                if (not args.force) and has_summary(conn, cid):
                    skip += 1
                    print(f"[{i}/{len(ids)}] skip {cid} (summary exists)")
                    continue

            try:
                title, transcript = get_transcript_for_summary(cid)
            except ValueError as e:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue
            except KeyError as e:
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue

            print(
                f"[{i}/{len(ids)}] summarizing {cid} "
                f"title={title!r} transcript_chars={len(transcript)}"
            )

            summary_text = summarize_conversation_text(
                client=client,
                model=args.model,
                title=title,
                transcript=transcript,
                cfg=sum_cfg,
                system_prompt=system_prompt,
            )

            summary_text = (summary_text or "").strip()
            if not summary_text:
                raise RuntimeError(
                    f"empty summary (title={title!r}, transcript_chars={len(transcript)})"
                )

            save_conversation_summary_artifact(cid, summary_text, args.model)

            ok += 1
            print(f"[{i}/{len(ids)}] ok   {cid}  ({len(summary_text)} chars)")
            if args.sleep:
                time.sleep(args.sleep)

        except Exception as e:
            fail += 1
            print(f"[{i}/{len(ids)}] FAIL {cid}: {e!r}")

    print(json.dumps({"ok": ok, "skipped": skip, "failed": fail}, indent=2))


if __name__ == "__main__":
    main()