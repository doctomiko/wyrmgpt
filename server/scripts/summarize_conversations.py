import argparse
import os
import sys
import time
import json
from openai import OpenAI

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# These need to appear AFTER sys.path.insert
from server.config import load_context_config, load_openai_config, load_summary_config
from server.context import _get_prompt
from server.db import db_session, init_schema, get_transcript_for_summary, save_conversation_summary_artifact
from server.summary_helper import summarize_conversation_text

def list_conversation_ids(include_archived: bool = False) -> list[str]:
    with db_session() as conn:
        if include_archived:
            rows = conn.execute("SELECT id FROM conversations ORDER BY updated_at DESC").fetchall()
        else:
            rows = conn.execute("SELECT id FROM conversations WHERE archived = 0 ORDER BY updated_at DESC").fetchall()
    return [r["id"] for r in rows]

def has_summary(conn, conversation_id: str) -> bool:
    # summary artifact exists and has summary_text
    # (staleness check can be added later; this is an MVP “skip if present”)
    aid_row = conn.execute(
        "SELECT id, summary_text FROM artifacts WHERE source_kind = 'conversation:summary' AND source_id = ? AND is_deleted = 0",
        (conversation_id,),
    ).fetchone()
    return bool(aid_row and (aid_row["summary_text"] or "").strip())

if (False):
    def extract_response_text(resp) -> str:
        """
        Best-effort extraction of assistant text from OpenAI Responses API result.
        """
        # Fast path
        try:
            txt = getattr(resp, "output_text", None)
            if txt and str(txt).strip():
                return str(txt).strip()
        except Exception:
            pass

        parts: list[str] = []

        # Walk response.output -> message -> content -> text
        try:
            for item in getattr(resp, "output", []) or []:
                item_type = getattr(item, "type", None)
                if item_type != "message":
                    continue

                for c in getattr(item, "content", []) or []:
                    c_type = getattr(c, "type", None)

                    # Newer SDKs often use output_text
                    if c_type == "output_text":
                        text = getattr(c, "text", None)
                        if text:
                            parts.append(str(text))

                    # Some variants use text/value
                    elif c_type == "text":
                        text = getattr(c, "text", None)
                        if text:
                            parts.append(str(text))
                        else:
                            value = getattr(c, "value", None)
                            if value:
                                parts.append(str(value))

                    # Very defensive fallback
                    else:
                        text = getattr(c, "text", None)
                        value = getattr(c, "value", None)
                        if text:
                            parts.append(str(text))
                        elif value:
                            parts.append(str(value))
        except Exception:
            pass

        return "\n".join(p.strip() for p in parts if p and str(p).strip()).strip()

def main():
    oai_cfg = load_openai_config()
    ctx_cfg = load_context_config()    
    sum_cfg = load_summary_config()

    ap = argparse.ArgumentParser()
    ap.add_argument("--include-archived", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--model", default=os.getenv("SUMMARY_MODEL") or os.getenv("MODEL") or ctx_cfg.estimate_model or "gpt-5-mini")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    print("Running init_schema...")
    init_schema()
    print("Done.")

    api_key=oai_cfg.open_ai_apikey
    print("OpenAI API key loaded:", bool(api_key), "len:", len(api_key or ""))
    if not bool(api_key):
        raise RuntimeError("API Key not loaded. Aborting.")
    client = OpenAI(api_key = api_key)

    ids = list_conversation_ids(include_archived=args.include_archived)
    if args.limit is not None:
        ids = ids[: args.limit]

    print(f"Summarizing {len(ids)} conversations using model={args.model} force={args.force}")

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
                # Empty conversation: skip (common for orphan convos)
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue
            except KeyError as e:
                # Conversation row missing: skip
                skip += 1
                print(f"[{i}/{len(ids)}] skip {cid} ({e})")
                continue

            print(f"[{i}/{len(ids)}] summarizing {cid} title={title!r} transcript_chars={len(transcript)}")
            summary_text = summarize_conversation_text(
                client=client,
                model=args.model,
                title=title,
                transcript=transcript,
                cfg=sum_cfg,
                system_prompt=system_prompt,
            )
            if (False):
                resp = client.responses.create(
                    model=args.model,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Title: {title}\n\nFull transcript:\n\n{transcript}"},
                    ],
                    max_output_tokens=sum_cfg.summary_max_tokens,
                )

                summary_text = extract_response_text(resp)

                # One retry with a blunter prompt if the first result is empty
                if not summary_text:
                    retry_prompt = (
                        "Summarize this conversation in 3-8 sentences. "
                        "Return plain text only. No markdown, no preamble."
                    )
                    resp2 = client.responses.create(
                        model=args.model,
                        input=[
                            {"role": "system", "content": retry_prompt},
                            {"role": "user", "content": f"Title: {title}\n\nFull transcript:\n\n{transcript}"},
                        ],
                        max_output_tokens=400,
                    )
                    summary_text = extract_response_text(resp2)

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