import argparse
import hashlib
import json
import mimetypes
import shutil
import sys
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db import (
    db_session,
    get_file_by_id,
    get_or_create_project,
    init_schema,
    list_files_by_sha256,
    project_add_conversation,
    register_scoped_file,
    refresh_conversation_transcript_artifact,
    reindex_corpus_for_conversation,
    upsert_artifact_text,
    upsert_file_artifact,
)

IMPORT_SOURCE = "openai-export"
MAX_MESSAGE_CONTENT_CHARS = 100_000
ROOT_FILE_RE = __import__('re').compile(r"^(file[-_][^/\\]+)$", __import__('re').IGNORECASE)


class Logger:
    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.log_path.open("a", encoding="utf-8")

    def log(self, msg: str) -> None:
        print(msg)
        self._fh.write(msg + "\n")
        self._fh.flush()

    def exception(self, prefix: str) -> None:
        tb = traceback.format_exc()
        self.log(prefix)
        self.log(tb.rstrip())

    def close(self) -> None:
        self._fh.close()


class ExportSource:
    def __init__(self, source: str | Path):
        self.path = Path(source).expanduser().resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"Missing export source: {self.path}")
        self.kind = "zip" if self.path.is_file() and self.path.suffix.lower() == ".zip" else "dir"
        self._zip: zipfile.ZipFile | None = None
        self._zip_names: list[str] | None = None
        if self.kind == "zip":
            self._zip = zipfile.ZipFile(self.path)
            self._zip_names = [n for n in self._zip.namelist()]

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def exists(self, relname: str) -> bool:
        if self.kind == "zip":
            return relname in (self._zip_names or [])
        return (self.path / relname).exists()

    def read_bytes(self, relname: str) -> bytes:
        if self.kind == "zip":
            assert self._zip is not None
            return self._zip.read(relname)
        return (self.path / relname).read_bytes()

    def read_json(self, relname: str) -> Any:
        return json.loads(self.read_bytes(relname).decode("utf-8"))

    def list_entries(self) -> list[tuple[str, int, bool]]:
        if self.kind == "zip":
            assert self._zip is not None
            return [(zi.filename, int(zi.file_size or 0), zi.is_dir()) for zi in self._zip.infolist()]
        out: list[tuple[str, int, bool]] = []
        for p in self.path.rglob("*"):
            rel = p.relative_to(self.path).as_posix()
            out.append((rel, 0 if p.is_dir() else p.stat().st_size, p.is_dir()))
        return out

    def root_file_names(self) -> list[str]:
        names: list[str] = []
        if self.kind == "zip":
            candidates = self._zip_names or []
            for name in candidates:
                if "/" in name.strip("/"):
                    continue
                if ROOT_FILE_RE.match(name):
                    names.append(name)
        else:
            for p in self.path.iterdir():
                if p.is_file() and ROOT_FILE_RE.match(p.name):
                    names.append(p.name)
        names.sort()
        return names

    def materialize_file(self, relname: str, dest_dir: Path, *, move_if_possible: bool = False) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / Path(relname).name
        if self.kind == "zip":
            dest.write_bytes(self.read_bytes(relname))
            return dest

        src = (self.path / relname).resolve()
        if move_if_possible:
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))
        else:
            shutil.copy2(src, dest)
        return dest


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


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _safe_slug(value: str) -> str:
    return __import__('re').sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip("-") or "unknown"


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _join_nonempty(parts: list[str]) -> str:
    return "\n\n".join([p for p in parts if p and p.strip()]).strip()


def _flatten_strings(obj: Any) -> list[str]:
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
                out.extend(_flatten_strings(obj.get(key)))
        if "parts" in obj:
            out.extend(_flatten_strings(obj.get("parts")))
        if "thoughts" in obj:
            out.extend(_flatten_strings(obj.get("thoughts")))
        return out
    if isinstance(obj, (list, tuple)):
        for item in obj:
            out.extend(_flatten_strings(item))
        return out
    return out


def _extract_message_text(message: dict) -> str:
    content = message.get("content") or {}
    ctype = (content.get("content_type") or "").strip()

    if ctype in {"text", "multimodal_text"}:
        text = _join_nonempty(_flatten_strings(content.get("parts")))
        if text:
            return text
        return _join_nonempty(_flatten_strings(content))
    if ctype in {"code", "execution_output"}:
        return _join_nonempty(_flatten_strings(content.get("text")))
    if ctype == "reasoning_recap":
        return _join_nonempty(_flatten_strings(content.get("content")))
    if ctype == "thoughts":
        return _join_nonempty(_flatten_strings(content.get("thoughts")))
    if ctype == "user_editable_context":
        parts = []
        up = (content.get("user_profile") or "").strip()
        ui = (content.get("user_instructions") or "").strip()
        if up:
            parts.append("USER PROFILE\n" + up)
        if ui:
            parts.append("USER INSTRUCTIONS\n" + ui)
        return _join_nonempty(parts)
    if ctype in {"tether_browsing_display", "tether_quote", "system_error"}:
        return _join_nonempty(_flatten_strings(content))
    return _join_nonempty(_flatten_strings(content))


def _normalize_message_text(text: str) -> str:
    s = (text or "").strip()
    if len(s) > MAX_MESSAGE_CONTENT_CHARS:
        trimmed = s[:MAX_MESSAGE_CONTENT_CHARS].rstrip()
        s = trimmed + "\n\n[TRUNCATED DURING IMPORT — FULL STRUCTURED CONTENT PRESERVED IN OPENAI IMPORT METADATA]"
    return s


def _local_conversation_id(export_id: str, prefix: str) -> str:
    return f"{prefix}{export_id}"


def _extract_current_path_nodes(convo: dict) -> list[dict]:
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


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


def _ensure_compat_tables() -> None:
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS import_identities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                import_source TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                local_id TEXT NOT NULL,
                import_id TEXT NOT NULL,
                imported_name TEXT,
                imported_parent_id TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(import_source, asset_type, import_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_import_identities_local ON import_identities(asset_type, local_id)")

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
                blocked_urls_json TEXT,
                context_scopes_json TEXT,
                extra_json TEXT,
                mapping_node_count INTEGER NOT NULL DEFAULT 0,
                current_branch_length INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL,
                FOREIGN KEY(local_conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_openai_import_conversations_export_id ON openai_import_conversations(export_conversation_id)")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_openai_import_messages_local_conversation_id ON openai_import_messages(local_conversation_id)")
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
            """
            CREATE TABLE IF NOT EXISTS openai_import_project_map (
                project_key TEXT PRIMARY KEY,
                local_project_id INTEGER NOT NULL,
                conversation_template_id TEXT,
                gizmo_id TEXT,
                gizmo_type TEXT,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_group_chats (
                export_group_chat_id TEXT PRIMARY KEY,
                title TEXT,
                raw_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_import_user_contexts (
                context_hash TEXT PRIMARY KEY,
                profile_text TEXT,
                instructions_text TEXT,
                first_export_conversation_id TEXT,
                last_export_conversation_id TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 0,
                artifact_id TEXT,
                imported_at TEXT NOT NULL,
                last_imported_at TEXT NOT NULL
            )
            """
        )


def _preload_identity_maps() -> dict[str, dict[str, str]]:
    out = {k: {} for k in ["project", "conversation", "message", "file", "artifact"]}
    with db_session() as conn:
        rows = conn.execute(
            "SELECT asset_type, local_id, import_id FROM import_identities WHERE import_source = ?",
            (IMPORT_SOURCE,),
        ).fetchall()
        for row in rows:
            at = (row["asset_type"] or "").strip()
            if at in out:
                out[at][row["import_id"]] = row["local_id"]

        if _table_exists(conn, "openai_import_conversations"):
            rows = conn.execute("SELECT export_conversation_id, local_conversation_id FROM openai_import_conversations").fetchall()
            for row in rows:
                out["conversation"].setdefault(row["export_conversation_id"], row["local_conversation_id"])
        if _table_exists(conn, "openai_import_messages"):
            rows = conn.execute("SELECT export_node_id, local_message_id FROM openai_import_messages").fetchall()
            for row in rows:
                out["message"].setdefault(row["export_node_id"], str(row["local_message_id"]))
        if _table_exists(conn, "openai_import_project_map"):
            rows = conn.execute("SELECT project_key, local_project_id FROM openai_import_project_map").fetchall()
            for row in rows:
                out["project"].setdefault(row["project_key"], str(row["local_project_id"]))
    return out


def _upsert_import_identity_conn(conn, *, asset_type: str, local_id: str | int, import_id: str, imported_name: str | None = None, imported_parent_id: str | None = None, raw_json: Any = None) -> None:
    now = _now_iso()
    local_id = str(local_id)
    raw_json_text = _json_dumps(raw_json) if raw_json is not None and not isinstance(raw_json, str) else raw_json
    conn.execute(
        """
        INSERT INTO import_identities(
            import_source, asset_type, local_id, import_id,
            imported_name, imported_parent_id, raw_json,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(import_source, asset_type, import_id) DO UPDATE SET
            local_id = excluded.local_id,
            imported_name = COALESCE(excluded.imported_name, import_identities.imported_name),
            imported_parent_id = COALESCE(excluded.imported_parent_id, import_identities.imported_parent_id),
            raw_json = COALESCE(excluded.raw_json, import_identities.raw_json),
            updated_at = excluded.updated_at
        """,
        (IMPORT_SOURCE, asset_type, local_id, import_id, imported_name, imported_parent_id, raw_json_text, now, now),
    )


def _upsert_user_profile(raw_user: dict) -> None:
    if not raw_user:
        return
    now = _now_iso()
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
                (raw_user.get("id") or "").strip() or "unknown-user",
                (raw_user.get("email") or "").strip() or None,
                1 if bool(raw_user.get("chatgpt_plus_user")) else 0,
                int(raw_user.get("birth_year")) if raw_user.get("birth_year") is not None else None,
                (raw_user.get("phone_number") or "").strip() or None,
                _json_dumps(raw_user),
                now,
                now,
            ),
        )


def _upsert_asset_inventory(entries: list[tuple[str,int,bool]]) -> None:
    now = _now_iso()
    with db_session() as conn:
        for path, size_bytes, is_dir in entries:
            if is_dir:
                continue
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
                (path, kind, int(size_bytes or 0), now, now),
            )


def _project_key_for_conversation(convo: dict) -> str:
    gizmo_id = (convo.get("gizmo_id") or "").strip()
    template_id = (convo.get("conversation_template_id") or "").strip()
    if gizmo_id:
        return f"gizmo:{gizmo_id}"
    if template_id:
        return f"template:{template_id}"
    return ""


def _project_name_for_conversation(convo: dict) -> str:
    gizmo_id = (convo.get("gizmo_id") or "").strip()
    gizmo_type = (convo.get("gizmo_type") or "").strip()
    template_id = (convo.get("conversation_template_id") or "").strip()
    if gizmo_id:
        return f"OpenAI Import GPT [{gizmo_type}] {gizmo_id}" if gizmo_type else f"OpenAI Import GPT {gizmo_id}"
    if template_id:
        return f"OpenAI Import Template {template_id}"
    return ""


def _resolve_project_for_conversation(convo: dict, caches: dict[str, dict[str, str]]) -> tuple[int | None, str | None]:
    key = _project_key_for_conversation(convo)
    if not key:
        return None, None
    existing = caches["project"].get(key)
    if existing:
        return int(existing), key
    name = _project_name_for_conversation(convo)
    project = get_or_create_project(name=name, visibility="private")
    project_id = int(project["id"])
    caches["project"][key] = str(project_id)
    with db_session() as conn:
        _upsert_import_identity_conn(
            conn,
            asset_type="project",
            local_id=project_id,
            import_id=key,
            imported_name=name,
            raw_json={
                "conversation_template_id": (convo.get("conversation_template_id") or "").strip() or None,
                "gizmo_id": (convo.get("gizmo_id") or "").strip() or None,
                "gizmo_type": (convo.get("gizmo_type") or "").strip() or None,
            },
        )
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO openai_import_project_map(
                project_key, local_project_id, conversation_template_id, gizmo_id, gizmo_type,
                imported_at, last_imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_key) DO UPDATE SET
                local_project_id = excluded.local_project_id,
                conversation_template_id = excluded.conversation_template_id,
                gizmo_id = excluded.gizmo_id,
                gizmo_type = excluded.gizmo_type,
                last_imported_at = excluded.last_imported_at
            """,
            (
                key,
                project_id,
                (convo.get("conversation_template_id") or "").strip() or None,
                (convo.get("gizmo_id") or "").strip() or None,
                (convo.get("gizmo_type") or "").strip() or None,
                now,
                now,
            ),
        )
    return project_id, key


def _upsert_user_context_snapshot(conn, *, export_conversation_id: str, profile_text: str, instructions_text: str, caches: dict[str, dict[str, str]]) -> str:
    profile_text = (profile_text or "").strip()
    instructions_text = (instructions_text or "").strip()
    if not profile_text and not instructions_text:
        return ""
    context_hash = _sha256_text(profile_text + "\n\n---\n\n" + instructions_text)
    title = f"OpenAI User Editable Context {context_hash[:12]}"
    body = _join_nonempty([
        "OPENAI USER EDITABLE CONTEXT SNAPSHOT",
        f"Export conversation id: {export_conversation_id}",
        "",
        "USER PROFILE",
        profile_text,
        "",
        "USER INSTRUCTIONS",
        instructions_text,
    ])
    artifact_id = upsert_artifact_text(
        conn=conn,
        source_kind="openai:user_editable_context",
        source_id=context_hash,
        title=title,
        scope_type="global",
        scope_id=None,
        text=body,
    )
    row = conn.execute(
        "SELECT occurrence_count FROM openai_import_user_contexts WHERE context_hash = ?",
        (context_hash,),
    ).fetchone()
    count = int(row["occurrence_count"] or 0) if row else 0
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO openai_import_user_contexts(
            context_hash, profile_text, instructions_text,
            first_export_conversation_id, last_export_conversation_id,
            occurrence_count, artifact_id, imported_at, last_imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(context_hash) DO UPDATE SET
            profile_text = excluded.profile_text,
            instructions_text = excluded.instructions_text,
            last_export_conversation_id = excluded.last_export_conversation_id,
            occurrence_count = ?,
            artifact_id = excluded.artifact_id,
            last_imported_at = excluded.last_imported_at
        """,
        (
            context_hash,
            profile_text,
            instructions_text,
            export_conversation_id,
            export_conversation_id,
            count + 1,
            artifact_id,
            now,
            now,
            count + 1,
        ),
    )
    _upsert_import_identity_conn(
        conn,
        asset_type="artifact",
        local_id=artifact_id,
        import_id=f"user-context:{context_hash}",
        imported_name=title,
        imported_parent_id=export_conversation_id,
    )
    caches["artifact"][f"user-context:{context_hash}"] = str(artifact_id)
    return artifact_id


def _import_group_chats(raw_group_chats: dict, logger: Logger) -> int:
    chats = raw_group_chats.get("chats") or []
    if not isinstance(chats, list):
        return 0
    now = _now_iso()
    count = 0
    with db_session() as conn:
        for row in chats:
            if not isinstance(row, dict):
                continue
            gcid = (row.get("id") or row.get("group_chat_id") or "").strip() or _sha256_text(_json_dumps(row))[:24]
            title = (row.get("title") or row.get("name") or "").strip() or None
            conn.execute(
                """
                INSERT INTO openai_import_group_chats(export_group_chat_id, title, raw_json, imported_at, last_imported_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(export_group_chat_id) DO UPDATE SET
                    title = excluded.title,
                    raw_json = excluded.raw_json,
                    last_imported_at = excluded.last_imported_at
                """,
                (gcid, title, _json_dumps(row), now, now),
            )
            count += 1
    logger.log(f"Imported/updated {count} group chat metadata rows")
    return count


def _upsert_feedback(raw_feedback: list[dict], prefix: str) -> int:
    now = _now_iso()
    count = 0
    with db_session() as conn:
        for row in raw_feedback:
            if not isinstance(row, dict):
                continue
            feedback_id = (row.get("id") or "").strip()
            if not feedback_id:
                continue
            export_cid = (row.get("conversation_id") or "").strip() or None
            local_cid = _local_conversation_id(export_cid, prefix) if export_cid else None
            conn.execute(
                """
                INSERT INTO openai_import_feedback(
                    feedback_id, export_conversation_id, local_conversation_id, user_id, rating,
                    create_time, update_time, workspace_id, evaluation_name, evaluation_treatment,
                    content_json, raw_json, imported_at, last_imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    _to_iso_utc(row.get("create_time")),
                    _to_iso_utc(row.get("update_time") or row.get("create_time")),
                    str(row.get("workspace_id")) if row.get("workspace_id") is not None else None,
                    (row.get("evaluation_name") or "").strip() or None,
                    (row.get("evaluation_treatment") or "").strip() or None,
                    _json_dumps(row.get("content")),
                    _json_dumps(row),
                    now,
                    now,
                ),
            )
            count += 1
    return count


def _upsert_attachment_rows(conn, *, zip_names: list[str], export_node_id: str, export_conversation_id: str, local_conversation_id: str, message: dict) -> int:
    metadata = message.get("metadata") or {}
    attachments = metadata.get("attachments") or []
    if not isinstance(attachments, list):
        return 0
    now = _now_iso()
    count = 0
    for att in attachments:
        if not isinstance(att, dict):
            continue
        att_id = (att.get("id") or "").strip()
        if not att_id:
            continue
        att_name = (att.get("name") or "").strip() or None
        binary_paths = []
        for name in zip_names:
            base = Path(name).name
            if att_id and att_id in name:
                binary_paths.append(name)
            elif att_name and base == att_name:
                binary_paths.append(name)
        seen = set(); binary_paths = [x for x in binary_paths if not (x in seen or seen.add(x))]
        conn.execute(
            """
            INSERT INTO openai_import_attachments(
                export_attachment_id, export_node_id, export_conversation_id, local_conversation_id,
                attachment_name, mime_type, file_size_tokens, binary_present, binary_paths_json,
                imported_at, last_imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _json_dumps(binary_paths),
                now,
                now,
            ),
        )
        count += 1
    return count


def _import_root_assets(source: ExportSource, source_label: str, caches: dict[str, dict[str, str]], *, move_root_files: bool, logger: Logger) -> int:
    root_files = source.root_file_names()
    if not root_files:
        logger.log("No root file-* assets found")
        return 0
    managed_dir = ROOT / "data" / "sources" / "openai-export" / _safe_slug(source_label) / "root-files"
    imported = 0
    for relname in root_files:
        try:
            # identity short-circuit
            if relname in caches["file"]:
                logger.log(f"[root-file] skip {relname} (identity exists)")
                continue
            dest = source.materialize_file(relname, managed_dir, move_if_possible=move_root_files and source.kind == 'dir')
            sha256 = _sha256_file(dest)
            mime_type = mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
            existing = None
            for row in list_files_by_sha256(sha256):
                if (row.get("scope_type") or "").strip() == "global":
                    existing = row
                    break
            if existing:
                file_row = existing
            else:
                reg = register_scoped_file(
                    name=dest.name,
                    path=str(dest),
                    mime_type=mime_type,
                    sha256=sha256,
                    scope_type="global",
                    scope_id=None,
                    scope_uuid=None,
                    source_kind="openai_export_asset",
                    provenance=f"openai_export:{source_label}",
                    description=f"Imported from OpenAI export root asset {relname}",
                )
                file_row = get_file_by_id(reg["id"])
            with db_session() as conn:
                artifact_id = upsert_file_artifact(conn, file_row=file_row, scope_type="global", scope_id=None)
                _upsert_import_identity_conn(conn, asset_type="file", local_id=file_row["id"], import_id=relname, imported_name=dest.name)
                caches["file"][relname] = str(file_row["id"])
                _upsert_import_identity_conn(conn, asset_type="artifact", local_id=artifact_id, import_id=f"artifact:{relname}", imported_name=dest.name, imported_parent_id=relname)
                caches["artifact"][f"artifact:{relname}"] = str(artifact_id)
            imported += 1
        except Exception:
            logger.exception(f"[root-file] FAIL {relname}")
    return imported


def _message_text_excerpt(message: dict) -> str:
    text = _normalize_message_text(_extract_message_text(message))
    return text[:5000]


def _import_conversation(convo: dict, *, prefix: str, zip_names: list[str], caches: dict[str, dict[str, str]], metadata_only: bool, refresh_transcripts: bool, reindex: bool, logger: Logger) -> dict[str, Any]:
    export_id = str(convo.get("id") or convo.get("conversation_id") or "").strip()
    local_cid = caches["conversation"].get(export_id) or _local_conversation_id(export_id, prefix)
    branch_nodes = _extract_current_path_nodes(convo)
    title = (convo.get("title") or "").strip() or "Imported chat"
    created_at = _to_iso_utc(convo.get("create_time"))
    updated_at = _to_iso_utc(convo.get("update_time") or convo.get("create_time"))
    project_id, project_key = _resolve_project_for_conversation(convo, caches)

    inserted_messages = 0
    inserted_attachments = 0
    inserted_any = False
    latest_msg_id = None
    latest_created_at = None

    extra = {
        k: v for k, v in convo.items()
        if k not in {
            "mapping", "title", "create_time", "update_time", "current_node", "default_model_slug",
            "gizmo_id", "gizmo_type", "conversation_template_id", "memory_scope",
            "is_archived", "is_starred", "safe_urls", "plugin_ids", "disabled_tool_ids",
            "async_status", "blocked_urls", "context_scopes", "id", "conversation_id",
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
                updated_at = CASE WHEN excluded.updated_at > conversations.updated_at THEN excluded.updated_at ELSE conversations.updated_at END
            """,
            (local_cid, title, 1 if bool(convo.get("is_archived")) else 0, created_at, updated_at),
        )
        caches["conversation"][export_id] = local_cid
        _upsert_import_identity_conn(conn, asset_type="conversation", local_id=local_cid, import_id=export_id, imported_name=title, imported_parent_id=project_key or None)
        now = _now_iso()
        conn.execute(
            """
            INSERT INTO openai_import_conversations(
                local_conversation_id, export_conversation_id, title, create_time, update_time,
                current_node, default_model_slug, gizmo_id, gizmo_type, conversation_template_id,
                memory_scope, is_archived, is_starred, async_status,
                safe_urls_json, plugin_ids_json, disabled_tool_ids_json, blocked_urls_json,
                context_scopes_json, extra_json, mapping_node_count, current_branch_length,
                imported_at, last_imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                blocked_urls_json = excluded.blocked_urls_json,
                context_scopes_json = excluded.context_scopes_json,
                extra_json = excluded.extra_json,
                mapping_node_count = excluded.mapping_node_count,
                current_branch_length = excluded.current_branch_length,
                last_imported_at = excluded.last_imported_at
            """,
            (
                local_cid, export_id, title, created_at, updated_at,
                (convo.get("current_node") or "").strip() or None,
                (convo.get("default_model_slug") or "").strip() or None,
                (convo.get("gizmo_id") or "").strip() or None,
                (convo.get("gizmo_type") or "").strip() or None,
                (convo.get("conversation_template_id") or "").strip() or None,
                (convo.get("memory_scope") or "").strip() or None,
                1 if bool(convo.get("is_archived")) else 0,
                1 if bool(convo.get("is_starred")) else 0,
                str(convo.get("async_status")) if convo.get("async_status") is not None else None,
                _json_dumps(convo.get("safe_urls") or []),
                _json_dumps(convo.get("plugin_ids") or []),
                _json_dumps(convo.get("disabled_tool_ids") or []),
                _json_dumps(convo.get("blocked_urls") or []),
                _json_dumps(convo.get("context_scopes") or []),
                _json_dumps(extra),
                len(convo.get("mapping") or {}),
                len(branch_nodes),
                now,
                now,
            ),
        )

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
            text = _normalize_message_text(_extract_message_text(message))
            if not text:
                # still record metadata shell if we can map existing local message
                local_msg_id = caches["message"].get(export_node_id)
                if local_msg_id is None:
                    continue
                local_msg_id_int = int(local_msg_id)
            else:
                local_msg_id = caches["message"].get(export_node_id)
                local_msg_id_int = int(local_msg_id) if local_msg_id is not None else 0
                if local_msg_id_int == 0 and not metadata_only:
                    cur = conn.execute(
                        "INSERT INTO messages(conversation_id, role, content, created_at, meta, author_meta) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            local_cid,
                            role,
                            text,
                            _to_iso_utc(message.get("create_time")),
                            _json_dumps({
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
                            }),
                            _json_dumps({
                                "imported": True,
                                "source": "openai_export_zip",
                                "role": role,
                                "name": (author.get("name") or "").strip() or None,
                                "metadata": author.get("metadata") or {},
                            }),
                        ),
                    )
                    local_msg_id_int = int(cur.lastrowid or 0)
                    caches["message"][export_node_id] = str(local_msg_id_int)
                    inserted_messages += 1
                    inserted_any = True
                elif local_msg_id_int == 0 and metadata_only:
                    continue

            metadata = message.get("metadata") or {}
            content = message.get("content") or {}
            attachments = metadata.get("attachments") or []
            content_refs = metadata.get("content_references") or []
            msg_created_at = _to_iso_utc(message.get("create_time"))
            msg_updated_at = _to_iso_utc(message.get("update_time") or message.get("create_time"))
            excerpt = (text[:5000] if text else _message_text_excerpt(message))
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    local_msg_id_int,
                    local_cid,
                    export_id,
                    export_message_id,
                    export_node_id,
                    parent_node_id,
                    (author.get("role") or "").strip() or None,
                    (author.get("name") or "").strip() or None,
                    _json_dumps(author.get("metadata") or {}),
                    (message.get("recipient") or "").strip() or None,
                    (message.get("status") or "").strip() or None,
                    (content.get("content_type") or "").strip() or None,
                    msg_created_at,
                    msg_updated_at,
                    float(message.get("weight") or 0.0),
                    1 if bool(message.get("end_turn")) else 0,
                    (message.get("channel") or "").strip() or None,
                    (metadata.get("model_slug") or "").strip() or None,
                    (metadata.get("default_model_slug") or "").strip() or None,
                    (metadata.get("request_id") or "").strip() or None,
                    (metadata.get("message_type") or "").strip() or None,
                    1 if bool(metadata.get("is_visually_hidden_from_conversation")) else 0,
                    _json_dumps(metadata),
                    _json_dumps(content),
                    _json_dumps(attachments),
                    _json_dumps(content_refs),
                    excerpt,
                    now,
                    now,
                ),
            )
            _upsert_import_identity_conn(conn, asset_type="message", local_id=local_msg_id_int, import_id=export_node_id, imported_name=(text[:120] if text else export_message_id or export_node_id), imported_parent_id=export_id)
            inserted_attachments += _upsert_attachment_rows(conn, zip_names=zip_names, export_node_id=export_node_id, export_conversation_id=export_id, local_conversation_id=local_cid, message=message)

            ctype = (content.get("content_type") or "").strip()
            if ctype == "user_editable_context" and not metadata_only:
                _upsert_user_context_snapshot(
                    conn,
                    export_conversation_id=export_id,
                    profile_text=(content.get("user_profile") or ""),
                    instructions_text=(content.get("user_instructions") or ""),
                    caches=caches,
                )

            latest_msg_id = local_msg_id_int
            latest_created_at = msg_created_at

    if project_id is not None:
        project_add_conversation(project_id, local_cid, set_primary=True)

    if latest_msg_id is not None and not metadata_only:
        # lighter than refreshing immediately; transcript/reindex can still be optional
        from server.db import mark_conversation_transcript_dirty
        mark_conversation_transcript_dirty(local_cid, latest_message_id=latest_msg_id, latest_message_created_at=latest_created_at)

    if refresh_transcripts and not metadata_only:
        refresh_conversation_transcript_artifact(local_cid, force_full=True, reason="openai-export-import")
    if reindex and not metadata_only:
        reindex_corpus_for_conversation(conversation_id=local_cid, force=True, include_global=False)

    return {
        "local_conversation_id": local_cid,
        "branch_nodes": len(branch_nodes),
        "inserted_any": inserted_any,
        "inserted_messages": inserted_messages,
        "inserted_attachments": inserted_attachments,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("export_source", help="Path to OpenAI export zip OR extracted export folder")
    ap.add_argument("--prefix", default="oaiexport-", help="Prefix for local imported conversation IDs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-existing", action="store_true", default=False)
    ap.add_argument("--metadata-only", action="store_true")
    ap.add_argument("--refresh-transcripts", action="store_true")
    ap.add_argument("--reindex", action="store_true")
    ap.add_argument("--ingest-root-files", action="store_true")
    ap.add_argument("--move-root-files", action="store_true")
    ap.add_argument("--log-file", default="")
    args = ap.parse_args()

    log_path = Path(args.log_file).expanduser() if args.log_file else (ROOT / "data" / "import_logs" / f"openai_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    logger = Logger(log_path)
    logger.log(f"OpenAI import starting: source={args.export_source}")
    logger.log(f"Options: metadata_only={args.metadata_only} refresh_transcripts={args.refresh_transcripts} reindex={args.reindex} ingest_root_files={args.ingest_root_files} move_root_files={args.move_root_files} skip_existing={args.skip_existing}")

    try:
        init_schema()
        _ensure_compat_tables()
        caches = _preload_identity_maps()
        source = ExportSource(args.export_source)
        try:
            entries = source.list_entries()
            names = [name for name, size, is_dir in entries if not is_dir]
            _upsert_asset_inventory(entries)

            source_label = source.path.stem if source.kind == "zip" else source.path.name
            logger.log(f"Source kind={source.kind} label={source_label}")
            if args.move_root_files and source.kind == 'zip':
                logger.log("NOTE: --move-root-files requested for zip input; zip sources are copied, not moved")

            if source.exists("user.json"):
                raw_user = source.read_json("user.json")
                if isinstance(raw_user, dict):
                    _upsert_user_profile(raw_user)

            if source.exists("group_chats.json"):
                try:
                    raw_group_chats = source.read_json("group_chats.json")
                    if isinstance(raw_group_chats, dict):
                        _import_group_chats(raw_group_chats, logger)
                except Exception:
                    logger.exception("Failed importing group_chats.json")

            raw_conversations = source.read_json("conversations.json")
            if not isinstance(raw_conversations, list):
                raise RuntimeError("Expected conversations.json to be a JSON list")

            conversations = raw_conversations[: args.limit] if args.limit else raw_conversations
            imported_conversations = 0
            skipped_conversations = 0
            failed_conversations = 0
            inserted_messages = 0
            inserted_attachments = 0
            imported_root_files = 0
            imported_feedback = 0

            if args.ingest_root_files:
                imported_root_files = _import_root_assets(source, source_label, caches, move_root_files=args.move_root_files, logger=logger)
                logger.log(f"Imported root files: {imported_root_files}")

            for idx, convo in enumerate(conversations, start=1):
                export_id = str(convo.get("id") or convo.get("conversation_id") or "").strip()
                try:
                    if not export_id:
                        skipped_conversations += 1
                        logger.log(f"[{idx}/{len(conversations)}] skip (missing export conversation id)")
                        continue
                    local_cid = caches["conversation"].get(export_id) or _local_conversation_id(export_id, args.prefix)
                    if args.skip_existing and export_id in caches["conversation"]:
                        skipped_conversations += 1
                        logger.log(f"[{idx}/{len(conversations)}] skip {local_cid} (already imported)")
                        continue
                    result = _import_conversation(
                        convo,
                        prefix=args.prefix,
                        zip_names=names,
                        caches=caches,
                        metadata_only=args.metadata_only,
                        refresh_transcripts=args.refresh_transcripts,
                        reindex=args.reindex,
                        logger=logger,
                    )
                    imported_conversations += 1
                    inserted_messages += int(result["inserted_messages"])
                    inserted_attachments += int(result["inserted_attachments"])
                    state = "imported" if result["inserted_any"] else "metadata-updated"
                    logger.log(f"[{idx}/{len(conversations)}] {state} {result['local_conversation_id']} ({result['branch_nodes']} branch nodes)")
                except Exception:
                    failed_conversations += 1
                    title = (convo.get("title") or "").strip()
                    logger.exception(f"[{idx}/{len(conversations)}] FAIL export_id={export_id!r} title={title!r}")

            if source.exists("message_feedback.json"):
                try:
                    raw_feedback = source.read_json("message_feedback.json")
                    if isinstance(raw_feedback, list):
                        imported_feedback = _upsert_feedback(raw_feedback, args.prefix)
                except Exception:
                    logger.exception("Failed importing message_feedback.json")

            summary = {
                "conversations_imported_or_updated": imported_conversations,
                "conversations_skipped": skipped_conversations,
                "conversations_failed": failed_conversations,
                "messages_inserted": inserted_messages,
                "attachments_cataloged": inserted_attachments,
                "root_files_imported": imported_root_files,
                "feedback_rows_imported": imported_feedback,
                "log_file": str(log_path),
            }
            logger.log(json.dumps(summary, indent=2))
        finally:
            source.close()
    finally:
        logger.close()


if __name__ == "__main__":
    main()
