import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.config import load_vector_config
from server.db import (
    conversation_transcript_artifact_id,
    create_conversation_scaffold_event_conn,
    db_session,
    init_schema,
    db_refresh_conversation_transcript_artifact,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_iso_utc(value: Any) -> str:
    if value is None:
        return _now_iso()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).replace(microsecond=0).isoformat()
    s = str(value).strip()
    if not s:
        return _now_iso()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return _now_iso()


def _sha256_text(text: str) -> str:
    import hashlib
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _user_context_hash(*, profile_text: str, instructions_text: str) -> str:
    return _sha256_text((profile_text or "").strip() + "\n\n---\n\n" + (instructions_text or "").strip())


def _record_user_context_archive_entry(
    archive: dict[str, dict[str, Any]],
    *,
    export_conversation_id: str,
    export_node_id: str,
    create_time: str | None,
    profile_text: str,
    instructions_text: str,
) -> str:
    profile_text = (profile_text or "").strip()
    instructions_text = (instructions_text or "").strip()
    if not profile_text and not instructions_text:
        return ""

    context_hash = _user_context_hash(
        profile_text=profile_text,
        instructions_text=instructions_text,
    )
    when = _to_iso_utc(create_time)
    row = archive.get(context_hash)
    if row is None:
        archive[context_hash] = {
            "context_hash": context_hash,
            "first_seen_at": when,
            "first_export_conversation_id": export_conversation_id or None,
            "first_export_node_id": export_node_id or None,
            "last_seen_at": when,
            "last_export_conversation_id": export_conversation_id or None,
            "last_export_node_id": export_node_id or None,
            "occurrence_count": 1,
            "profile_text": profile_text,
            "instructions_text": instructions_text,
        }
        return context_hash

    row["occurrence_count"] = int(row.get("occurrence_count") or 0) + 1
    row["last_seen_at"] = when
    row["last_export_conversation_id"] = export_conversation_id or None
    row["last_export_node_id"] = export_node_id or None

    first_seen = (row.get("first_seen_at") or "").strip()
    if not first_seen or when < first_seen:
        row["first_seen_at"] = when
        row["first_export_conversation_id"] = export_conversation_id or None
        row["first_export_node_id"] = export_node_id or None

    return context_hash


def _write_user_context_archive_json(archive: dict[str, dict[str, Any]], out_path: Path) -> Path | None:
    if not archive:
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": _now_iso(),
        "total_unique_contexts": len(archive),
        "contexts": sorted(archive.values(), key=lambda r: ((r.get("first_seen_at") or ""), (r.get("context_hash") or ""))),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _load_json_object(text: str | None) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _extract_context_texts(row: dict) -> tuple[str, str]:
    content = _load_json_object(row.get("content_json"))
    profile_text = (content.get("user_profile") or "").strip()
    instructions_text = (content.get("user_instructions") or "").strip()
    if profile_text or instructions_text:
        return profile_text, instructions_text

    content_text = (row.get("content") or "").strip()
    if not content_text:
        return "", ""

    profile_marker = "USER PROFILE\n"
    instructions_marker = "USER INSTRUCTIONS\n"
    profile_text = ""
    instructions_text = ""

    if content_text.startswith(profile_marker):
        rest = content_text[len(profile_marker):]
        if "\n\nUSER INSTRUCTIONS\n" in rest:
            profile_text, instructions_text = rest.split("\n\nUSER INSTRUCTIONS\n", 1)
        else:
            profile_text = rest
    elif content_text.startswith(instructions_marker):
        instructions_text = content_text[len(instructions_marker):]

    return profile_text.strip(), instructions_text.strip()


def _maybe_create_user_context_scaffold_event_conn(
    conn,
    *,
    conversation_id: str,
    export_conversation_id: str,
    export_node_id: str,
    create_time: str | None,
    context_hash: str,
    profile_text: str,
    instructions_text: str,
) -> bool:
    input_payload = {
        "context_hash": context_hash,
        "export_conversation_id": export_conversation_id or None,
        "export_node_id": export_node_id or None,
        "create_time": _to_iso_utc(create_time),
        "has_profile": bool((profile_text or "").strip()),
        "has_instructions": bool((instructions_text or "").strip()),
    }
    input_json_text = json.dumps(input_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    existing = conn.execute(
        """
        SELECT id
        FROM conversation_scaffold_events
        WHERE conversation_id = ?
          AND event_kind = ?
          AND input_json = ?
        LIMIT 1
        """,
        (conversation_id, "openai_import_user_editable_context", input_json_text),
    ).fetchone()
    if existing:
        return False

    preview_parts: list[str] = []
    if (profile_text or "").strip():
        preview_parts.append("profile")
    if (instructions_text or "").strip():
        preview_parts.append("instructions")
    preview_label = " + ".join(preview_parts) if preview_parts else "context"

    create_conversation_scaffold_event_conn(
        conn,
        conversation_id=conversation_id,
        event_kind="openai_import_user_editable_context",
        status="ready",
        title="Imported OpenAI user-editable context",
        body_text=f"Imported {preview_label} snapshot preserved as scaffold metadata during OpenAI import cleanup.",
        input_json=input_json_text,
        output_json={
            "context_hash": context_hash,
            "profile_text": profile_text,
            "instructions_text": instructions_text,
        },
    )
    return True


def _list_target_rows(limit: int | None = None) -> list[dict]:
    sql = """
        SELECT
            oim.local_message_id,
            oim.local_conversation_id,
            oim.export_conversation_id,
            oim.export_node_id,
            oim.create_time,
            oim.content_json,
            m.content
        FROM openai_import_messages oim
        JOIN openai_import_conversations oic
          ON oic.local_conversation_id = oim.local_conversation_id
        JOIN messages m
          ON m.id = oim.local_message_id
        WHERE COALESCE(oim.content_type, '') = 'user_editable_context'
        ORDER BY oim.local_conversation_id ASC, oim.create_time ASC, oim.export_node_id ASC
    """
    with db_session() as conn:
        rows = conn.execute(sql).fetchall()
    result = [dict(r) for r in rows]
    return result[:limit] if limit is not None else result


def _list_existing_transcript_chunk_ids(conversation_ids: list[str]) -> dict[str, list[int]]:
    if not conversation_ids:
        return {}

    artifact_to_cid = {
        conversation_transcript_artifact_id(cid): cid
        for cid in conversation_ids
    }
    placeholders = ",".join("?" for _ in artifact_to_cid)
    sql = f"""
        SELECT artifact_id, id
        FROM corpus_chunks
        WHERE artifact_id IN ({placeholders})
        ORDER BY artifact_id ASC, id ASC
    """
    out: dict[str, list[int]] = {cid: [] for cid in conversation_ids}
    with db_session() as conn:
        rows = conn.execute(sql, tuple(artifact_to_cid.keys())).fetchall()
    for row in rows:
        artifact_id = str(row["artifact_id"])
        cid = artifact_to_cid.get(artifact_id)
        if cid:
            out[cid].append(int(row["id"]))
    return out


def _delete_citations_for_conversation(conn, conversation_id: str) -> int:
    cur = conn.execute(
        """
        DELETE FROM citations
        WHERE assistant_message_id IN (
            SELECT id
            FROM messages
            WHERE conversation_id = ?
              AND role = 'assistant'
        )
        """,
        (conversation_id,),
    )
    return int(cur.rowcount or 0)


def _delete_import_identity_rows(conn, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    cur = conn.execute(
        f"DELETE FROM import_identities WHERE import_source = ? AND asset_type = 'message' AND local_id IN ({placeholders})",
        ("openai-export", *[str(x) for x in message_ids]),
    )
    return int(cur.rowcount or 0)


def _delete_messages(conn, message_ids: list[int]) -> int:
    if not message_ids:
        return 0
    placeholders = ",".join("?" for _ in message_ids)
    cur = conn.execute(
        f"DELETE FROM messages WHERE id IN ({placeholders})",
        tuple(message_ids),
    )
    return int(cur.rowcount or 0)


def _delete_qdrant_points(chunk_ids: list[int]) -> int:
    if not chunk_ids:
        return 0

    vec_cfg = load_vector_config()
    if vec_cfg.backend != "qdrant_local":
        return 0

    from server.vector.qdrant_local import QdrantLocalVectorStore

    store = QdrantLocalVectorStore(cfg=vec_cfg)
    deleted = 0
    batch_size = 512
    for start in range(0, len(chunk_ids), batch_size):
        batch = chunk_ids[start : start + batch_size]
        store.delete_by_chunk_ids(batch)
        deleted += len(batch)
    return deleted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--json-out",
        default="",
        help="Optional output path for deduplicated user-editable-context JSON archive",
    )
    ap.add_argument(
        "--delete-qdrant-points",
        action="store_true",
        help="Delete existing transcript chunk vectors for affected conversations before transcript rebuild",
    )
    args = ap.parse_args()

    init_schema()

    rows = _list_target_rows(limit=args.limit)
    total_rows = len(rows)
    print(f"Found {total_rows} imported user_editable_context message rows")
    if total_rows == 0:
        return

    rows_by_conversation: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_conversation[str(row["local_conversation_id"])].append(row)

    archive: dict[str, dict[str, Any]] = {}
    affected_conversations = list(rows_by_conversation.keys())

    scaffold_created = 0
    messages_deleted = 0
    citations_deleted = 0
    import_identities_deleted = 0

    with db_session() as conn:
        for idx, (conversation_id, conv_rows) in enumerate(rows_by_conversation.items(), start=1):
            message_ids: list[int] = []
            for row in conv_rows:
                export_conversation_id = str(row.get("export_conversation_id") or "")
                export_node_id = str(row.get("export_node_id") or "")
                local_message_id = int(row["local_message_id"])
                message_ids.append(local_message_id)
                profile_text, instructions_text = _extract_context_texts(row)
                context_hash = _record_user_context_archive_entry(
                    archive,
                    export_conversation_id=export_conversation_id,
                    export_node_id=export_node_id,
                    create_time=row.get("create_time"),
                    profile_text=profile_text,
                    instructions_text=instructions_text,
                )
                if context_hash:
                    created = _maybe_create_user_context_scaffold_event_conn(
                        conn,
                        conversation_id=conversation_id,
                        export_conversation_id=export_conversation_id,
                        export_node_id=export_node_id,
                        create_time=row.get("create_time"),
                        context_hash=context_hash,
                        profile_text=profile_text,
                        instructions_text=instructions_text,
                    )
                    if created:
                        scaffold_created += 1

            citations_deleted += _delete_citations_for_conversation(conn, conversation_id)
            import_identities_deleted += _delete_import_identity_rows(conn, message_ids)
            messages_deleted += _delete_messages(conn, message_ids)
            print(f"[{idx}/{len(rows_by_conversation)}] cleaned message rows for {conversation_id} ({len(message_ids)} messages)")

    deleted_vectors = 0
    if args.delete_qdrant_points:
        transcript_chunk_ids = _list_existing_transcript_chunk_ids(affected_conversations)
        for cid in affected_conversations:
            deleted_vectors += _delete_qdrant_points(transcript_chunk_ids.get(cid) or [])

    rebuilt = 0
    failed = 0
    total_conversations = len(affected_conversations)
    for idx, cid in enumerate(affected_conversations, start=1):
        try:
            out = db_refresh_conversation_transcript_artifact(
                cid,
                force_full=True,
                reason="openai-user-editable-context-cleanup",
            )
            rebuilt += 1
            print(
                f"[{idx}/{total_conversations}] rebuilt transcript {cid} "
                f"(full_rebuild={out.get('full_rebuild')} appended={out.get('appended_message_count')})"
            )
        except Exception as e:
            failed += 1
            print(f"[{idx}/{total_conversations}] FAIL transcript {cid}: {e!r}")

    json_out = Path(args.json_out).expanduser() if args.json_out else (
        ROOT / "data" / f"openai_user_editable_contexts.cleanup.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    written = _write_user_context_archive_json(archive, json_out)

    summary = {
        "target_rows": total_rows,
        "messages_deleted": messages_deleted,
        "import_identities_deleted": import_identities_deleted,
        "scaffold_events_created": scaffold_created,
        "affected_conversations": len(affected_conversations),
        "citations_deleted": citations_deleted,
        "transcript_vectors_deleted": deleted_vectors,
        "transcripts_rebuilt": rebuilt,
        "transcripts_failed": failed,
        "unique_user_contexts": len(archive),
        "json_out": str(written) if written else None,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
