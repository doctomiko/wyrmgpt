import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import (
    db_session,
    mark_conversation_transcript_dirty,
    refresh_conversation_transcript_artifact,
    reindex_corpus_for_conversation,
)

MAX_MESSAGE_CONTENT_CHARS = 100_000


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_iso_utc(value: Any) -> str:
    if value is None:
        return now_iso()

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc).replace(microsecond=0).isoformat()

    s = str(value).strip()
    if not s:
        return now_iso()

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return now_iso()


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def join_nonempty(parts: list[str]) -> str:
    return "\n\n".join([p for p in parts if p and p.strip()]).strip()


def flatten_strings(obj: Any) -> list[str]:
    out: list[str] = []
    if obj is None:
        return out
    if isinstance(obj, str):
        s = obj.strip()
        if s:
            out.append(s)
        return out
    if isinstance(obj, dict):
        for key in ("text", "content", "summary", "result", "user_profile", "user_instructions", "title", "name"):
            if key in obj:
                out.extend(flatten_strings(obj.get(key)))
        if "parts" in obj:
            out.extend(flatten_strings(obj.get("parts")))
        if "thoughts" in obj:
            out.extend(flatten_strings(obj.get("thoughts")))
        return out
    if isinstance(obj, (list, tuple)):
        for item in obj:
            out.extend(flatten_strings(item))
        return out
    return out


def extract_message_text(message: dict) -> str:
    content = message.get("content") or {}
    ctype = (content.get("content_type") or "").strip()

    if ctype in {"text", "multimodal_text"}:
        text = join_nonempty(flatten_strings(content.get("parts")))
        if text:
            return text
        return join_nonempty(flatten_strings(content))

    if ctype in {"code", "execution_output"}:
        return join_nonempty(flatten_strings(content.get("text")))

    if ctype == "reasoning_recap":
        return join_nonempty(flatten_strings(content.get("content")))

    if ctype == "thoughts":
        return join_nonempty(flatten_strings(content.get("thoughts")))

    if ctype == "user_editable_context":
        parts = []
        up = (content.get("user_profile") or "").strip()
        ui = (content.get("user_instructions") or "").strip()
        if up:
            parts.append("USER PROFILE\n" + up)
        if ui:
            parts.append("USER INSTRUCTIONS\n" + ui)
        return join_nonempty(parts)

    if ctype in {"tether_browsing_display", "tether_quote", "system_error"}:
        return join_nonempty(flatten_strings(content))

    return join_nonempty(flatten_strings(content))


def normalize_message_text(text: str) -> str:
    s = (text or "").strip()
    if len(s) > MAX_MESSAGE_CONTENT_CHARS:
        trimmed = s[:MAX_MESSAGE_CONTENT_CHARS].rstrip()
        s = trimmed + "\n\n[TRUNCATED DURING IMPORT — FULL STRUCTURED CONTENT PRESERVED IN OPENAI IMPORT METADATA]"
    return s


def local_conversation_id(export_id: str, prefix: str) -> str:
    return f"{prefix}{export_id}"


def extract_current_path_nodes(convo: dict) -> list[dict]:
    mapping = convo.get("mapping") or {}
    current = convo.get("current_node")
    if not isinstance(mapping, dict) or not current:
        return []

    seen: set[str] = set()
    path: list[dict] = []

    while current and current in mapping and current not in seen:
        seen.add(current)
        node = mapping.get(current) or {}
        path.append(node)
        current = node.get("parent")

    path.reverse()
    return path


def ensure_openai_import_tables() -> None:
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_user (
                user_id TEXT PRIMARY KEY,
                email TEXT,
                chatgpt_plus_user INTEGER,
                birth_year INTEGER,
                phone_number TEXT,
                raw_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_conversations (
                local_conversation_id TEXT PRIMARY KEY,
                export_conversation_id TEXT NOT NULL UNIQUE,
                title TEXT,
                create_time TEXT,
                update_time TEXT,
                current_node TEXT,
                default_model_slug TEXT,
                gizmo_id TEXT,
                gizmo_type TEXT,
                conversation_template_id TEXT,
                memory_scope TEXT,
                is_archived INTEGER NOT NULL DEFAULT 0,
                is_starred INTEGER NOT NULL DEFAULT 0,
                async_status TEXT,
                safe_urls_json TEXT,
                plugin_ids_json TEXT,
                disabled_tool_ids_json TEXT,
                extra_json TEXT,
                mapping_node_count INTEGER NOT NULL DEFAULT 0,
                current_branch_length INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL,
                FOREIGN KEY(local_conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_openai_import_conversations_export_id ON openai_import_conversations(export_conversation_id)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_messages (
                local_message_id INTEGER PRIMARY KEY,
                local_conversation_id TEXT NOT NULL,
                export_conversation_id TEXT NOT NULL,
                export_message_id TEXT,
                export_node_id TEXT NOT NULL UNIQUE,
                parent_node_id TEXT,
                author_role TEXT,
                author_name TEXT,
                author_metadata_json TEXT,
                recipient TEXT,
                status TEXT,
                content_type TEXT,
                create_time TEXT,
                update_time TEXT,
                weight REAL,
                end_turn INTEGER,
                channel TEXT,
                model_slug TEXT,
                default_model_slug TEXT,
                request_id TEXT,
                message_type TEXT,
                is_visually_hidden INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT,
                content_json TEXT,
                attachments_json TEXT,
                content_references_json TEXT,
                text_excerpt TEXT,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL,
                FOREIGN KEY(local_message_id) REFERENCES messages(id) ON DELETE CASCADE,
                FOREIGN KEY(local_conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_openai_import_messages_local_conversation_id ON openai_import_messages(local_conversation_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_openai_import_messages_export_message_id ON openai_import_messages(export_message_id)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_feedback (
                feedback_id TEXT PRIMARY KEY,
                export_conversation_id TEXT,
                local_conversation_id TEXT,
                user_id TEXT,
                rating TEXT,
                create_time TEXT,
                update_time TEXT,
                workspace_id TEXT,
                evaluation_name TEXT,
                evaluation_treatment TEXT,
                content_json TEXT,
                raw_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_openai_import_feedback_local_conversation_id ON openai_import_feedback(local_conversation_id)"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_assets (
                asset_path TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_attachments (
                export_attachment_id TEXT NOT NULL,
                export_node_id TEXT NOT NULL,
                export_conversation_id TEXT NOT NULL,
                local_conversation_id TEXT NOT NULL,
                attachment_name TEXT,
                mime_type TEXT,
                file_size_tokens INTEGER,
                binary_present INTEGER NOT NULL DEFAULT 0,
                binary_paths_json TEXT,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL,
                PRIMARY KEY(export_attachment_id, export_node_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_openai_import_attachments_local_conversation_id ON openai_import_attachments(local_conversation_id)"
        )


def upsert_user_profile(user: dict) -> None:
    if not user:
        return
    now = now_iso()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO openai_import_user(
                user_id, email, chatgpt_plus_user, birth_year, phone_number,
                raw_json, imported_at, last_imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email = excluded.email,
                chatgpt_plus_user = excluded.chatgpt_plus_user,
                birth_year = excluded.birth_year,
                phone_number = excluded.phone_number,
                raw_json = excluded.raw_json,
                last_imported_at = excluded.last_imported_at
            """,
            (
                (user.get("id") or "").strip() or "unknown-user",
                (user.get("email") or "").strip() or None,
                1 if bool(user.get("chatgpt_plus_user")) else 0,
                int(user.get("birth_year")) if user.get("birth_year") is not None else None,
                (user.get("phone_number") or "").strip() or None,
                json_dumps(user),
                now,
                now,
            ),
        )


def upsert_asset_inventory(zip_entries: list[zipfile.ZipInfo]) -> None:
    now = now_iso()
    with db_session() as conn:
        for info in zip_entries:
            if info.is_dir():
                continue
            path = info.filename
            if path.startswith("dalle-generations/"):
                kind = "dalle-generation"
            elif path.startswith("user-"):
                kind = "user-root"
            elif Path(path).name.startswith("file-") or Path(path).name.startswith("file_"):
                kind = "file-binary"
            else:
                kind = "other"

            conn.execute(
                """
                INSERT INTO openai_import_assets(asset_path, kind, size_bytes, imported_at, last_imported_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(asset_path) DO UPDATE SET
                    kind = excluded.kind,
                    size_bytes = excluded.size_bytes,
                    last_imported_at = excluded.last_imported_at
                """,
                (path, kind, int(info.file_size or 0), now, now),
            )


def find_binary_paths(zip_names: list[str], attachment_id: str, attachment_name: str | None) -> list[str]:
    att_id = (attachment_id or "").strip()
    att_name = (attachment_name or "").strip()
    out = []
    for name in zip_names:
        base = Path(name).name
        if att_id and att_id in name:
            out.append(name)
        elif att_name and base == att_name:
            out.append(name)
    seen = set()
    final = []
    for x in out:
        if x not in seen:
            seen.add(x)
            final.append(x)
    return final


def upsert_conversation(local_cid: str, convo: dict, branch_nodes: list[dict]) -> None:
    now = now_iso()
    export_id = str(convo.get("id") or convo.get("conversation_id") or "").strip()
    title = (convo.get("title") or "").strip() or "Imported chat"
    created_at = to_iso_utc(convo.get("create_time"))
    updated_at = to_iso_utc(convo.get("update_time") or convo.get("create_time"))

    extra = {
        k: v
        for k, v in convo.items()
        if k not in {
            "mapping", "title", "create_time", "update_time", "current_node", "default_model_slug",
            "gizmo_id", "gizmo_type", "conversation_template_id", "memory_scope",
            "is_archived", "is_starred", "safe_urls", "plugin_ids", "disabled_tool_ids",
            "async_status", "id", "conversation_id"
        }
    }

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO conversations(id, title, archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                archived = excluded.archived,
                updated_at = CASE
                    WHEN excluded.updated_at > conversations.updated_at THEN excluded.updated_at
                    ELSE conversations.updated_at
                END
            """,
            (
                local_cid,
                title,
                1 if bool(convo.get("is_archived")) else 0,
                created_at,
                updated_at,
            ),
        )

        conn.execute(
            """
            INSERT INTO openai_import_conversations(
                local_conversation_id, export_conversation_id, title, create_time, update_time,
                current_node, default_model_slug, gizmo_id, gizmo_type, conversation_template_id,
                memory_scope, is_archived, is_starred, async_status,
                safe_urls_json, plugin_ids_json, disabled_tool_ids_json, extra_json,
                mapping_node_count, current_branch_length, imported_at, last_imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(local_conversation_id) DO UPDATE SET
                export_conversation_id = excluded.export_conversation_id,
                title = excluded.title,
                create_time = excluded.create_time,
                update_time = excluded.update_time,
                current_node = excluded.current_node,
                default_model_slug = excluded.default_model_slug,
                gizmo_id = excluded.gizmo_id,
                gizmo_type = excluded.gizmo_type,
                conversation_template_id = excluded.conversation_template_id,
                memory_scope = excluded.memory_scope,
                is_archived = excluded.is_archived,
                is_starred = excluded.is_starred,
                async_status = excluded.async_status,
                safe_urls_json = excluded.safe_urls_json,
                plugin_ids_json = excluded.plugin_ids_json,
                disabled_tool_ids_json = excluded.disabled_tool_ids_json,
                extra_json = excluded.extra_json,
                mapping_node_count = excluded.mapping_node_count,
                current_branch_length = excluded.current_branch_length,
                last_imported_at = excluded.last_imported_at
            """,
            (
                local_cid,
                export_id,
                title,
                created_at,
                updated_at,
                (convo.get("current_node") or "").strip() or None,
                (convo.get("default_model_slug") or "").strip() or None,
                (convo.get("gizmo_id") or "").strip() or None,
                (convo.get("gizmo_type") or "").strip() or None,
                (convo.get("conversation_template_id") or "").strip() or None,
                (convo.get("memory_scope") or "").strip() or None,
                1 if bool(convo.get("is_archived")) else 0,
                1 if bool(convo.get("is_starred")) else 0,
                str(convo.get("async_status")) if convo.get("async_status") is not None else None,
                json_dumps(convo.get("safe_urls") or []),
                json_dumps(convo.get("plugin_ids") or []),
                json_dumps(convo.get("disabled_tool_ids") or []),
                json_dumps(extra),
                len(convo.get("mapping") or {}),
                len(branch_nodes),
                now,
                now,
            ),
        )


def existing_local_message_id(export_node_id: str) -> int | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT local_message_id FROM openai_import_messages WHERE export_node_id = ?",
            (export_node_id,),
        ).fetchone()
        return int(row["local_message_id"]) if row and row["local_message_id"] is not None else None


def insert_local_message(
    *,
    local_conversation_id: str,
    role: str,
    content: str,
    created_at: str,
    meta: dict,
    author_meta: dict,
) -> int:
    meta_json = json_dumps(meta)
    author_meta_json = json_dumps(author_meta)

    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages(conversation_id, role, content, created_at, meta, author_meta)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (local_conversation_id, role, content, created_at, meta_json, author_meta_json),
        )
        msg_id = int(cur.lastrowid or 0)

        conn.execute(
            """
            UPDATE conversations
            SET updated_at = CASE
                WHEN ? > updated_at THEN ?
                ELSE updated_at
            END
            WHERE id = ?
            """,
            (created_at, created_at, local_conversation_id),
        )
        return msg_id


def upsert_import_message(
    *,
    local_message_id: int,
    local_conversation_id: str,
    export_conversation_id: str,
    export_message_id: str | None,
    export_node_id: str,
    parent_node_id: str | None,
    message: dict,
    text_excerpt: str,
) -> None:
    now = now_iso()
    author = message.get("author") or {}
    metadata = message.get("metadata") or {}
    content = message.get("content") or {}
    attachments = metadata.get("attachments") or []
    content_refs = metadata.get("content_references") or []

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO openai_import_messages(
                local_message_id, local_conversation_id, export_conversation_id,
                export_message_id, export_node_id, parent_node_id,
                author_role, author_name, author_metadata_json, recipient, status, content_type,
                create_time, update_time, weight, end_turn, channel,
                model_slug, default_model_slug, request_id, message_type, is_visually_hidden,
                metadata_json, content_json, attachments_json, content_references_json,
                text_excerpt, imported_at, last_imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(export_node_id) DO UPDATE SET
                local_message_id = excluded.local_message_id,
                local_conversation_id = excluded.local_conversation_id,
                export_conversation_id = excluded.export_conversation_id,
                export_message_id = excluded.export_message_id,
                parent_node_id = excluded.parent_node_id,
                author_role = excluded.author_role,
                author_name = excluded.author_name,
                author_metadata_json = excluded.author_metadata_json,
                recipient = excluded.recipient,
                status = excluded.status,
                content_type = excluded.content_type,
                create_time = excluded.create_time,
                update_time = excluded.update_time,
                weight = excluded.weight,
                end_turn = excluded.end_turn,
                channel = excluded.channel,
                model_slug = excluded.model_slug,
                default_model_slug = excluded.default_model_slug,
                request_id = excluded.request_id,
                message_type = excluded.message_type,
                is_visually_hidden = excluded.is_visually_hidden,
                metadata_json = excluded.metadata_json,
                content_json = excluded.content_json,
                attachments_json = excluded.attachments_json,
                content_references_json = excluded.content_references_json,
                text_excerpt = excluded.text_excerpt,
                last_imported_at = excluded.last_imported_at
            """,
            (
                local_message_id,
                local_conversation_id,
                export_conversation_id,
                (export_message_id or "").strip() or None,
                export_node_id,
                (parent_node_id or "").strip() or None,
                (author.get("role") or "").strip() or None,
                (author.get("name") or "").strip() or None,
                json_dumps(author.get("metadata") or {}),
                (message.get("recipient") or "").strip() or None,
                (message.get("status") or "").strip() or None,
                (content.get("content_type") or "").strip() or None,
                to_iso_utc(message.get("create_time")),
                to_iso_utc(message.get("update_time") or message.get("create_time")),
                float(message.get("weight") or 0.0),
                1 if bool(message.get("end_turn")) else 0,
                (message.get("channel") or "").strip() or None,
                (metadata.get("model_slug") or "").strip() or None,
                (metadata.get("default_model_slug") or "").strip() or None,
                (metadata.get("request_id") or "").strip() or None,
                (metadata.get("message_type") or "").strip() or None,
                1 if bool(metadata.get("is_visually_hidden_from_conversation")) else 0,
                json_dumps(metadata),
                json_dumps(content),
                json_dumps(attachments),
                json_dumps(content_refs),
                text_excerpt[:5000],
                now,
                now,
            ),
        )


def upsert_attachments_for_message(
    *,
    zip_names: list[str],
    export_node_id: str,
    export_conversation_id: str,
    local_conversation_id: str,
    message: dict,
) -> int:
    metadata = message.get("metadata") or {}
    attachments = metadata.get("attachments") or []
    if not isinstance(attachments, list):
        return 0

    now = now_iso()
    count = 0
    with db_session() as conn:
        for att in attachments:
            if not isinstance(att, dict):
                continue
            att_id = (att.get("id") or "").strip()
            if not att_id:
                continue
            att_name = (att.get("name") or "").strip() or None
            binary_paths = find_binary_paths(zip_names, att_id, att_name)

            conn.execute(
                """
                INSERT INTO openai_import_attachments(
                    export_attachment_id, export_node_id, export_conversation_id, local_conversation_id,
                    attachment_name, mime_type, file_size_tokens, binary_present, binary_paths_json,
                    imported_at, last_imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(export_attachment_id, export_node_id) DO UPDATE SET
                    export_conversation_id = excluded.export_conversation_id,
                    local_conversation_id = excluded.local_conversation_id,
                    attachment_name = excluded.attachment_name,
                    mime_type = excluded.mime_type,
                    file_size_tokens = excluded.file_size_tokens,
                    binary_present = excluded.binary_present,
                    binary_paths_json = excluded.binary_paths_json,
                    last_imported_at = excluded.last_imported_at
                """,
                (
                    att_id,
                    export_node_id,
                    export_conversation_id,
                    local_conversation_id,
                    att_name,
                    (att.get("mimeType") or "").strip() or None,
                    int(att.get("fileSizeTokens")) if att.get("fileSizeTokens") is not None else None,
                    1 if binary_paths else 0,
                    json_dumps(binary_paths),
                    now,
                    now,
                ),
            )
            count += 1
    return count


def import_feedback(raw_feedback: list[dict], prefix: str) -> int:
    now = now_iso()
    count = 0
    with db_session() as conn:
        for row in raw_feedback:
            if not isinstance(row, dict):
                continue
            feedback_id = (row.get("id") or "").strip()
            if not feedback_id:
                continue
            export_cid = (row.get("conversation_id") or "").strip() or None
            local_cid = local_conversation_id(export_cid, prefix) if export_cid else None
            conn.execute(
                """
                INSERT INTO openai_import_feedback(
                    feedback_id, export_conversation_id, local_conversation_id, user_id, rating,
                    create_time, update_time, workspace_id, evaluation_name, evaluation_treatment,
                    content_json, raw_json, imported_at, last_imported_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feedback_id) DO UPDATE SET
                    export_conversation_id = excluded.export_conversation_id,
                    local_conversation_id = excluded.local_conversation_id,
                    user_id = excluded.user_id,
                    rating = excluded.rating,
                    create_time = excluded.create_time,
                    update_time = excluded.update_time,
                    workspace_id = excluded.workspace_id,
                    evaluation_name = excluded.evaluation_name,
                    evaluation_treatment = excluded.evaluation_treatment,
                    content_json = excluded.content_json,
                    raw_json = excluded.raw_json,
                    last_imported_at = excluded.last_imported_at
                """,
                (
                    feedback_id,
                    export_cid,
                    local_cid,
                    (row.get("user_id") or "").strip() or None,
                    (row.get("rating") or "").strip() or None,
                    to_iso_utc(row.get("create_time")),
                    to_iso_utc(row.get("update_time") or row.get("create_time")),
                    str(row.get("workspace_id")) if row.get("workspace_id") is not None else None,
                    (row.get("evaluation_name") or "").strip() or None,
                    (row.get("evaluation_treatment") or "").strip() or None,
                    json_dumps(row.get("content")),
                    json_dumps(row),
                    now,
                    now,
                ),
            )
            count += 1
    return count


def conversation_already_imported(local_cid: str) -> bool:
    with db_session() as conn:
        row = conn.execute(
            "SELECT 1 FROM openai_import_conversations WHERE local_conversation_id = ? LIMIT 1",
            (local_cid,),
        ).fetchone()
        return bool(row)


def latest_local_message_for_conversation(local_cid: str) -> tuple[int | None, str | None]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (local_cid,),
        ).fetchone()
        if not row:
            return None, None
        return int(row["id"]), row["created_at"]


def import_conversation(
    *,
    convo: dict,
    prefix: str,
    zip_names: list[str],
    refresh_transcripts: bool,
    reindex: bool,
) -> dict[str, Any]:
    export_id = str(convo.get("id") or convo.get("conversation_id") or "").strip()
    local_cid = local_conversation_id(export_id, prefix)
    branch_nodes = extract_current_path_nodes(convo)

    upsert_conversation(local_cid, convo, branch_nodes)

    inserted_any = False
    inserted_messages = 0
    inserted_attachments = 0

    for node in branch_nodes:
        message = node.get("message")
        if not isinstance(message, dict):
            continue

        export_node_id = (node.get("id") or "").strip()
        if not export_node_id:
            continue

        export_message_id = (message.get("id") or "").strip() or None
        parent_node_id = (node.get("parent") or "").strip() or None
        author = message.get("author") or {}
        role = (author.get("role") or "").strip() or "assistant"

        text = normalize_message_text(extract_message_text(message))
        if not text:
            continue

        existing_local_msg_id = existing_local_message_id(export_node_id)
        if existing_local_msg_id is None:
            local_msg_id = insert_local_message(
                local_conversation_id=local_cid,
                role=role,
                content=text,
                created_at=to_iso_utc(message.get("create_time")),
                meta={
                    "import_source": "openai_export_zip",
                    "openai_export_conversation_id": export_id,
                    "openai_export_message_id": export_message_id,
                    "openai_export_node_id": export_node_id,
                    "openai_parent_node_id": parent_node_id,
                    "openai_content_type": ((message.get("content") or {}).get("content_type") or "").strip() or None,
                    "openai_recipient": (message.get("recipient") or "").strip() or None,
                    "openai_status": (message.get("status") or "").strip() or None,
                    "openai_model_slug": ((message.get("metadata") or {}).get("model_slug") or "").strip() or None,
                    "openai_default_model_slug": ((message.get("metadata") or {}).get("default_model_slug") or "").strip() or None,
                },
                author_meta={
                    "imported": True,
                    "source": "openai_export_zip",
                    "role": role,
                    "name": (author.get("name") or "").strip() or None,
                    "metadata": author.get("metadata") or {},
                },
            )
            inserted_messages += 1
            inserted_any = True
        else:
            local_msg_id = existing_local_msg_id

        upsert_import_message(
            local_message_id=local_msg_id,
            local_conversation_id=local_cid,
            export_conversation_id=export_id,
            export_message_id=export_message_id,
            export_node_id=export_node_id,
            parent_node_id=parent_node_id,
            message=message,
            text_excerpt=text[:5000],
        )

        inserted_attachments += upsert_attachments_for_message(
            zip_names=zip_names,
            export_node_id=export_node_id,
            export_conversation_id=export_id,
            local_conversation_id=local_cid,
            message=message,
        )

    latest_msg_id, latest_created_at = latest_local_message_for_conversation(local_cid)
    if latest_msg_id is not None:
        mark_conversation_transcript_dirty(
            local_cid,
            latest_message_id=latest_msg_id,
            latest_message_created_at=latest_created_at,
        )

    if refresh_transcripts:
        refresh_conversation_transcript_artifact(
            local_cid,
            force_full=True,
            reason="openai-export-zip-import",
        )

    if reindex:
        reindex_corpus_for_conversation(
            conversation_id=local_cid,
            force=True,
            include_global=False,
        )

    return {
        "local_conversation_id": local_cid,
        "export_conversation_id": export_id,
        "branch_nodes": len(branch_nodes),
        "inserted_any": inserted_any,
        "inserted_messages": inserted_messages,
        "inserted_attachments": inserted_attachments,
    }
