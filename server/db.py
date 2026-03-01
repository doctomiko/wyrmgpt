# server/db.py
from asyncio import log
import sqlite3
import json
import uuid
import re
from pathlib import Path
from pydantic.dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "callie_mvp.sqlite3"
_VALID_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SCHEMA_VERSION = 7  

# near the top of db.py, alongside other imports or type helpers:
@dataclass
class FileScope:
    project_id: int | None
    scope_type: str | None
    scope_id: int | None
    scope_uuid: str | None

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
        timeout=30.0,   # <- important
    )
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 30000;")   # <- wait for locks instead of failing immediately
        conn.execute("PRAGMA journal_mode = WAL;")     # <- better concurrency
        conn.execute("PRAGMA synchronous = NORMAL;")   # <- reasonable for dev
        yield conn
        conn.commit()
    finally:
        conn.close()

# region Schema Management and Migrations

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None

def _table_has_rows(conn: sqlite3.Connection, table: str) -> bool:
    if not _table_exists(conn, table):
        return False
    try:
        row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False

def _db_has_user_data(conn: sqlite3.Connection) -> bool:
    # If any of these have rows, we treat it as “real data exists.”
    for t in ("messages", "conversations", "projects", "memories", "files", "artifacts"):
        if _table_has_rows(conn, t):
            return True
    return False

def _drop_all_tables(conn: sqlite3.Connection) -> None:
    # Drop in dependency order.
    for t in (
        "project_imports",
        "memory_conversations",
        "memory_projects",
        "project_files",
        "project_conversations",
        "artifacts",
        "files",
        "memories",
        "conversation_settings",
        "messages",
        "conversations",
        "projects",
        "memory_pins",
        "schema_meta",
    ):
        conn.execute(f"DROP TABLE IF EXISTS {t}")


def drop_empty_tables(tables: Iterable[str], conn: sqlite3.Connection | None = None) -> list[str]:
    """
    Drop tables that exist and have 0 rows.
    Returns a list of table names that were dropped.

    NOTE: If you drop a table here, your app must not reference it later
    unless you recreate it in init_schema().
    """
    dropped: list[str] = []
    def _do(conn: sqlite3.Connection) -> list[str]:
        # Be permissive about drops; we’re explicitly choosing to prune.
        conn.execute("PRAGMA foreign_keys = OFF;")
        for t in tables:
            if not t or not _VALID_TABLE.match(t):
                raise ValueError(f"Unsafe table name: {t!r}")
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (t,),
            ).fetchone()
            if not exists:
                continue
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {t}").fetchone()
            count = int(row["c"]) if row and row["c"] is not None else 0
            if count == 0:
                conn.execute(f"DROP TABLE {t}")
                dropped.append(t)
        conn.execute("PRAGMA foreign_keys = ON;")
        return dropped

    if conn is not None:
        return _do(conn)
    with db_session() as sconn:
        return _do(sconn)

def drop_empty_satellite_tables(conn: sqlite3.Connection | None = None) -> list[str]:
    """
    Your “satellite”/optional tables: join tables + imports.
    Adjust this list to taste.
    """
    return drop_empty_tables(
        [
            #"projects",
            "project_conversations",
            "project_files",
            "memory_projects",
            "memory_conversations",
            "project_imports",
            "conversation_settings",
            "artifacts",
            "files",
        ],
        conn
    )

def _apply_schema_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            system_prompt TEXT,
            override_core_prompt INTEGER DEFAULT 0,
            default_advanced_mode INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            project_id INTEGER,
            title TEXT NOT NULL,
            summary_json TEXT,
            archived INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            meta TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

        CREATE TABLE IF NOT EXISTS conversation_settings (
            conversation_id TEXT PRIMARY KEY,
            advanced_mode INTEGER DEFAULT 0,
            model_pref TEXT,
            modelB_pref TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS memory_pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 0,
            tags TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        -- Keep these for future use; types are now consistent.
        CREATE TABLE IF NOT EXISTS project_conversations (
            project_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            PRIMARY KEY (project_id, conversation_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS project_files (
            project_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            PRIMARY KEY (project_id, file_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (file_id) REFERENCES files(id)
        );

        CREATE TABLE IF NOT EXISTS memory_projects (
            memory_id TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            PRIMARY KEY (memory_id, project_id),
            FOREIGN KEY (memory_id) REFERENCES memories(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS memory_conversations (
            memory_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            PRIMARY KEY (memory_id, conversation_id),
            FOREIGN KEY (memory_id) REFERENCES memories(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        CREATE TABLE IF NOT EXISTS project_imports (
            project_id INTEGER NOT NULL,
            source_project_id INTEGER NOT NULL,
            include_tags TEXT,
            exclude_tags TEXT,
            include_artifact_ids TEXT,
            PRIMARY KEY (project_id, source_project_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (source_project_id) REFERENCES projects(id)
        );
        """
    )

    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )

def migrate_schema_v3(conn: sqlite3.Connection) -> None:
    """
    Non-destructive migration for the file/url/artifact/context-cache design.

    Adds:
      - scope + provenance + soft-delete columns on files and artifacts
      - soft-delete columns on memories
      - context_cache, conversation_files, conversation_artifacts tables
    """

    # Extend files table if it exists
    if _table_exists(conn, "files"):
        _add_column_if_missing(conn, "files", "scope_type", "TEXT")
        _add_column_if_missing(conn, "files", "scope_id", "INTEGER")
        _add_column_if_missing(conn, "files", "scope_uuid", "TEXT")
        _add_column_if_missing(conn, "files", "source_kind", "TEXT")
        _add_column_if_missing(conn, "files", "url", "TEXT")
        _add_column_if_missing(conn, "files", "description", "TEXT")
        _add_column_if_missing(conn, "files", "provenance", "TEXT")
        _add_column_if_missing(conn, "files", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "files", "deleted_at", "TEXT")
        _add_column_if_missing(conn, "files", "deleted_by_user_id", "TEXT")

    # Extend artifacts table if it exists
    if _table_exists(conn, "artifacts"):
        _add_column_if_missing(conn, "artifacts", "scope_type", "TEXT")
        _add_column_if_missing(conn, "artifacts", "scope_id", "INTEGER")
        _add_column_if_missing(conn, "artifacts", "scope_uuid", "TEXT")
        _add_column_if_missing(conn, "artifacts", "file_id", "TEXT")
        _add_column_if_missing(conn, "artifacts", "source_kind", "TEXT")
        _add_column_if_missing(conn, "artifacts", "provenance", "TEXT")
        _add_column_if_missing(conn, "artifacts", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "artifacts", "deleted_at", "TEXT")
        _add_column_if_missing(conn, "artifacts", "deleted_by_user_id", "TEXT")

    # Extend memories table with soft-delete markers
    if _table_exists(conn, "memories"):
        _add_column_if_missing(conn, "memories", "is_deleted", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "memories", "deleted_at", "TEXT")
        _add_column_if_missing(conn, "memories", "deleted_by_user_id", "TEXT")

    # Context cache for precomputed context payloads
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS context_cache (
            conversation_id TEXT PRIMARY KEY,
            project_id INTEGER,
            cache_key TEXT NOT NULL DEFAULT 'default',
            payload TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
        """
    )

    # Optional many-to-many link between conversations and files
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_files (
            conversation_id TEXT NOT NULL,
            file_id TEXT NOT NULL,
            PRIMARY KEY (conversation_id, file_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (file_id) REFERENCES files(id)
        )
        """
    )

    # Optional many-to-many link between conversations and artifacts
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_artifacts (
            conversation_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            PRIMARY KEY (conversation_id, artifact_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id)
        )
        """
    )

def migrate_schema_v4(conn: sqlite3.Connection) -> None:
    """
    Non-destructive migration for artifact chunking.

    Adds:
      - chunk_index INTEGER on artifacts
    """
    if _table_exists(conn, "artifacts"):
        _add_column_if_missing(conn, "artifacts", "chunk_index", "INTEGER")

def migrate_schema_v5_messages(conn: sqlite3.Connection) -> None:
    """
    Make sure messages have created_at and author_meta columns.
    """
    _add_column_if_missing(conn, "messages", "created_at", "TEXT")
    _add_column_if_missing(conn, "messages", "author_meta", "TEXT")

def migrate_schema_v6_projects(conn: sqlite3.Connection) -> None:
    """
    Add is_global and is_hidden flags to projects.
    """
    _add_column_if_missing(conn, "projects", "is_global", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "projects", "is_hidden", "INTEGER DEFAULT 0")

def db_debug_info(conn: sqlite3.Connection | None = None) -> dict:
    if conn is None:
        with db_session() as sconn:
            return db_debug_info(sconn)
    else:
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        ]
        # conn.close()
        return {
            "db_path": str(DB_PATH),
            "tables": tables,
        }

def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, coldef: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")

def migrate_schema_minimal(conn: sqlite3.Connection) -> None:
    # conversations: add updated_at + archived + summary_json + project_id if needed
    _add_column_if_missing(conn, "conversations", "project_id", "INTEGER")
    _add_column_if_missing(conn, "conversations", "summary_json", "TEXT")
    _add_column_if_missing(conn, "conversations", "archived", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "conversations", "updated_at", "TEXT")
    # projects: if you have projects already, ensure uuid exists (optional)
    if _table_exists(conn, "projects"):
        _add_column_if_missing(conn, "projects", "uuid", "TEXT")
        _add_column_if_missing(conn, "projects", "updated_at", "TEXT")
        _add_column_if_missing(conn, "projects", "created_at", "TEXT")

def init_schema() -> None:
    with db_session() as conn:
        conn.execute("PRAGMA foreign_keys = OFF;")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

        # Comment the next line after cached artifacts are cleared
        # You should not need to do this very often. We'll work on a button later.
        # reset_all_artifacts()
        if current < SCHEMA_VERSION:
            # Destructive changes - commented unless needed
            """
            dropped = drop_empty_satellite_tables(conn)
            print("Dropped:", dropped)

            if _db_has_user_data(conn):
                raise RuntimeError(
                    "Refusing destructive migration: DB already has data. "
                    "Write a non-destructive migration before upgrading."
                )
            _drop_all_tables(conn)
            """
            # Ensure all tables exist (idempotent)
            _apply_schema_v2(conn)
            # Bring older DBs up to compatibility without dropping data
            migrate_schema_minimal(conn)
            migrate_schema_v3(conn)
            migrate_schema_v4(conn)
            migrate_schema_v5_messages(conn)
            migrate_schema_v6_projects(conn)

        conn.execute("PRAGMA foreign_keys = ON;")
        print(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")
        # TODO implement seperate log file and log there as well.
        #log.logger.info(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")

# endregion

def _normalize_tags(tags: Any) -> str | None:
    """
    Store tags as JSON text (recommended), but accept None/str/list.
    """
    if tags is None:
        return None
    if isinstance(tags, str):
        t = tags.strip()
        return t if t else None
    if isinstance(tags, (list, tuple)):
        cleaned = [str(x).strip() for x in tags if str(x).strip()]
        return json.dumps(cleaned) if cleaned else None
    # last resort: stringify
    t = str(tags).strip()
    return t if t else None

# ----------------------------
# Projects
# ----------------------------

# region Projects

def _ensure_project_exists(conn: sqlite3.Connection, project_id: int) -> None:
    row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise ValueError(f"Project not found: {project_id}")

def list_projects() -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE (is_hidden IS NULL OR is_hidden = 0) AND (is_global IS NULL OR is_global = 0) ORDER BY name COLLATE NOCASE"
        ).fetchall()
        #"SELECT id, name, description, created_at, updated_at FROM projects ORDER BY name COLLATE NOCASE"
        return [
            {
                "id": int(r["id"]),
                "name": r["name"],
                "description": r["description"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

def get_global_project_id() -> int:
    """
    Return the id of the synthetic 'Global' project, creating it if needed.

    This project is for shared/global resources and should be hidden in UI.
    """
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE is_global = 1 LIMIT 1"
        ).fetchone()
        if row is not None:
            return int(row["id"])

        # Create it
        now = _utcnow_iso()
        cur = conn.execute(
            """
            INSERT INTO projects (name, description, is_global, is_hidden, created_at, updated_at)
            VALUES (?, ?, 1, 1, ?, ?)
            """,
            ("Global", "Global shared resources", now, now),
        )
        newid: int = cur.lastrowid # type: ignore[union-attr]
        return newid

def get_or_create_project(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Project name cannot be empty.")

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, name, created_at, updated_at FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        if row:
            return {
                "id": int(row["id"]),
                "name": row["name"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

        puuid = str(uuid.uuid4())
        now = _utcnow_iso()
        conn.execute(
            """
            INSERT INTO projects (uuid, name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (puuid, name, now, now),
        )
        row2 = conn.execute(
            "SELECT id, name, created_at, updated_at FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        return {
            "id": int(row2["id"]),
            "name": row2["name"],
            "created_at": row2["created_at"],
            "updated_at": row2["updated_at"],
        }

def project_add_conversation(project_id: int, conversation_id: str, set_primary: bool = True) -> None:
    if project_id is None:
        raise ValueError("project_id is required.")
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        _ensure_conversation_exists(conn, conversation_id)

        # Keep join table for future multi-project use
        conn.execute(
            "INSERT OR IGNORE INTO project_conversations (project_id, conversation_id) VALUES (?, ?)",
            (int(project_id), conversation_id),
        )

        # Keep your current UI semantics (conversation has a primary project)
        if set_primary:
            conn.execute(
                "UPDATE conversations SET project_id = ?, updated_at = ? WHERE id = ?",
                (int(project_id), _utcnow_iso(), conversation_id),
            )

def update_project(project_id: int, name: str | None = None, description: str | None = None) -> dict:
    sets = []
    params = []

    if name is not None:
        n = (name or "").strip()
        if not n:
            raise ValueError("Project name cannot be empty.")
        sets.append("name = ?")
        params.append(n)

    if description is not None:
        sets.append("description = ?")
        params.append(description)

    if not sets:
        raise ValueError("No changes provided.")

    sets.append("updated_at = ?")
    params.append(_utcnow_iso())
    params.append(int(project_id))

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", tuple(params))
        row = conn.execute(
            "SELECT id, name, description, created_at, updated_at FROM projects WHERE id = ?",
            (int(project_id),),
        ).fetchone()

    return {
        "id": int(row["id"]),
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def project_import(
    project_id: int,
    source_project_id: int,
    include_tags: str | None = None,
    exclude_tags: str | None = None,
    include_artifact_ids: str | None = None,
) -> None:
    if project_id is None:
        raise ValueError("project_id is required.")
    if source_project_id is None:
        raise ValueError("source_project_id is required.")

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        _ensure_project_exists(conn, int(source_project_id))

        conn.execute(
            """
            INSERT OR REPLACE INTO project_imports
              (project_id, source_project_id, include_tags, exclude_tags, include_artifact_ids)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(project_id),
                int(source_project_id),
                include_tags,
                exclude_tags,
                include_artifact_ids,
            ),
        )

# endregion

# ----------------------------
# Conversations
# ----------------------------

# region Conversations

def _ensure_conversation_exists(conn: sqlite3.Connection, conversation_id: str) -> None:
    row = conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        raise ValueError(f"Conversation not found: {conversation_id}")

def create_conversation(conversation_id: str, title: str = "New chat") -> None:
    now = _utcnow_iso()
    title = (title or "").strip() or "New chat"
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO conversations(id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, title, now, now),
        )

def update_conversation_title(conversation_id: str, title: str) -> bool:
    title = (title or "").strip() or "New chat"
    with db_session() as conn:
        cur = conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, _utcnow_iso(), conversation_id),
        )
        return (cur.rowcount or 0) > 0
    
def list_conversations(limit: int = 200, include_archived: bool = False) -> list[dict]:
    with db_session() as conn:
        if include_archived:
            where = ""
            params: tuple[Any, ...] = (limit,)
        else:
            where = "WHERE c.archived = 0"
            params = (limit,)

        rows = conn.execute(
            f"""
            SELECT
                c.id,
                c.title,
                c.created_at,
                c.updated_at,
                c.project_id,
                c.archived,
                p.name AS project_name
            FROM conversations c
            LEFT JOIN projects p ON p.id = c.project_id
            {where}
            ORDER BY COALESCE(c.updated_at, c.created_at) DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

        return [
            {
                "id": r["id"],
                "title": r["title"] or "New chat",
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "project_id": (int(r["project_id"]) if r["project_id"] is not None else None),
                "project_name": r["project_name"],
                "archived": bool(r["archived"]),
            }
            for r in rows
        ]


def set_conversation_project(conversation_id: str, project_id: int | None) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE conversations SET project_id = ?, updated_at = ? WHERE id = ?",
            (project_id, _utcnow_iso(), conversation_id),
        )

def set_conversation_archived(conversation_id: str, archived: bool) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, _utcnow_iso(), conversation_id),
        )

def delete_conversation(conversation_id: str) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversation_settings WHERE conversation_id = ?", (conversation_id,))
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

def get_conversation_title(conversation_id: str) -> str | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT title FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return row["title"] if row else None

def get_conversation_context(conversation_id: str, preview_limit: int = 20) -> dict:
    title = get_conversation_title(conversation_id)
    if title is None:
        raise KeyError("Conversation not found.")

    with db_session() as conn:
        row = conn.execute(
            """
            SELECT c.project_id, p.name AS project_name, c.archived, c.summary_json
            FROM conversations c
            LEFT JOIN projects p ON p.id = c.project_id
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()

    # Messages preview: last N raw messages (so UI can show meta if desired)
    raw = get_messages_raw(conversation_id, limit=2000)
    preview = raw[-max(0, int(preview_limit)):] if preview_limit else []

    return {
        "conversation_id": conversation_id,
        "title": title,
        "project_id": int(row["project_id"]) if row and row["project_id"] is not None else None,
        "project_name": row["project_name"] if row else None,
        "archived": bool(row["archived"]) if row and row["archived"] is not None else False,
        "summary_json": row["summary_json"] if row else None,
        "preview_limit": int(preview_limit),
        "messages_preview": preview,
    }

def get_context_sources(conversation_id: str) -> dict:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT
              c.id AS conversation_id,
              c.summary_json,
              c.project_id,
              p.name AS project_name,
              p.system_prompt AS project_system_prompt,
              p.override_core_prompt AS override_core_prompt
            FROM conversations c
            LEFT JOIN projects p ON p.id = c.project_id
            WHERE c.id = ?
            """,
            (conversation_id,),
        ).fetchone()

        if not row:
            raise KeyError("Conversation not found.")

        return {
            "conversation_id": row["conversation_id"],
            "summary_json": row["summary_json"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "project_system_prompt": row["project_system_prompt"],
            "override_core_prompt": row["override_core_prompt"],
        }

# endregion
# region Conversation Summaries

def get_transcript_for_summary(conversation_id: str) -> tuple[str, str]:
    title = get_conversation_title(conversation_id)
    if not title:
        raise KeyError("Conversation not found.")

    with db_session() as conn:
        msgs = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    if not msgs:
        raise ValueError("Conversation is empty.")

    transcript = "\n\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    return title, transcript

def save_conversation_summary(conversation_id: str, summary_text: str, model: str) -> None:
    summary_obj = {"model": model, "summary": summary_text}
    with db_session() as conn:
        conn.execute(
            "UPDATE conversations SET summary_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(summary_obj), _utcnow_iso(), conversation_id),
        )

# region Context Cache

def get_context_cache(conversation_id: str, cache_key: str = "default") -> dict | None:
    """
    Load a cached context payload for a conversation, if present.
    Returns a dict (whatever you stored) or None.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        if not _table_exists(conn, "context_cache"):
            return None
        row = conn.execute(
            """
            SELECT payload
            FROM context_cache
            WHERE conversation_id = ? AND cache_key = ?
            """,
            (conversation_id, cache_key),
        ).fetchone()

    if not row or not row["payload"]:
        return None

    try:
        return json.loads(row["payload"])
    except json.JSONDecodeError:
        return None

def save_context_cache(
    conversation_id: str,
    project_id: int | None,
    payload: dict,
    cache_key: str = "default",
) -> None:
    """
    Upsert a cached context payload for a conversation.
    payload should be JSON-serializable.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")
    if payload is None:
        raise ValueError("payload is required.")

    payload_text = json.dumps(payload, ensure_ascii=False)
    now = _utcnow_iso()

    with db_session() as conn:
        if not _table_exists(conn, "context_cache"):
            # If the table isn't there yet, fail soft rather than exploding.
            return
        conn.execute(
            """
            INSERT OR REPLACE INTO context_cache (
                conversation_id, project_id, cache_key, payload, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, project_id, cache_key, payload_text, now),
        )


def invalidate_context_cache_for_conversation(conversation_id: str) -> None:
    """
    Drop any cached context for a single conversation.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        if not _table_exists(conn, "context_cache"):
            return
        conn.execute(
            "DELETE FROM context_cache WHERE conversation_id = ?",
            (conversation_id,),
        )

def invalidate_context_cache_for_project(project_id: int) -> None:
    """
    Drop cached context for all conversations under a project.
    Useful after bulk file/import changes.
    """
    if project_id is None:
        raise ValueError("project_id is required.")

    with db_session() as conn:
        if not _table_exists(conn, "context_cache"):
            return
        conn.execute(
            "DELETE FROM context_cache WHERE project_id = ?",
            (int(project_id),),
        )

# endregion

# endregion

# ----------------------------
# Messages (including A/B)
# ----------------------------

# region Messages

def _message_count(conn: sqlite3.Connection, conversation_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    return int(row["c"])

def add_message(
        conversation_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
        author_meta: dict | None = None,
        ) -> None:
    now = _utcnow_iso()
    meta_json = json.dumps(meta) if meta is not None else None
    author_meta_json = json.dumps(author_meta) if author_meta is not None else None
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO messages(conversation_id, role, content, created_at, meta, author_meta)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, now, meta_json, author_meta_json),
        )

        if role == "user":
            count = _message_count(conn, conversation_id)
            if count == 1:
                row = conn.execute(
                    "SELECT title FROM conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                current_title = (row["title"] if row else None) or ""
                if current_title.strip() == "" or current_title.strip().lower() == "new chat":
                    t = content.strip().replace("\n", " ")
                    if len(t) > 60:
                        t = t[:57] + "…"
                    conn.execute(
                        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                        (t, _utcnow_iso(), conversation_id),
                    )


def get_messages_raw(conversation_id: str, limit: int = 200) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, created_at, meta, author_meta
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (conversation_id, limit),
        ).fetchall()

    results: list[dict] = []
    for r in rows:
        raw_meta = r["meta"]
        meta_obj = None
        if raw_meta is not None:
            try:
                meta_obj = json.loads(raw_meta)
            except Exception:
                meta_obj = None
        raw_author_meta = r["author_meta"]
        author_meta_obj = None
        if raw_author_meta is not None:
            try:
                author_meta_obj = json.loads(raw_author_meta)
            except Exception:
                author_meta_obj = None

        results.append(
            {
                "id": int(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"],
                "meta": meta_obj,
                "author_meta": author_meta_obj,
            }
        )
    return results


def get_messages(conversation_id: str, limit: int = 200) -> list[dict]:
    rows = get_messages_raw(conversation_id, limit=limit)
    result: list[dict] = []
    seen_groups: set[str] = set()

    for r in rows:
        meta = r.get("meta") or {}
        ab_group = meta.get("ab_group")
        canonical = meta.get("canonical", True)
        if ab_group:
            if ab_group in seen_groups:
                continue
            if not canonical:
                continue
            seen_groups.add(ab_group)

        result.append({"role": r["role"], "created_at": r["created_at"], "content": r["content"], "author_meta": r["author_meta"]})
    return result


def update_ab_canonical(conversation_id: str, ab_group: str, slot: str) -> None:
    slot = (slot or "").upper()
    if slot not in ("A", "B"):
        return

    with db_session() as conn:
        rows = conn.execute(
            "SELECT id, meta FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()

        for r in rows:
            raw_meta = r["meta"]
            if raw_meta is None:
                continue
            try:
                meta = json.loads(raw_meta)
            except Exception:
                continue
            if not isinstance(meta, dict):
                continue
            if meta.get("ab_group") != ab_group:
                continue
            meta["canonical"] = (meta.get("slot") == slot)
            conn.execute(
                "UPDATE messages SET meta = ? WHERE id = ?",
                (json.dumps(meta), r["id"]),
            )

# endregion

# ----------------------------
# Pins
# ----------------------------

# region Memories

def _ensure_memory_exists(conn: sqlite3.Connection, memory_id: str) -> None:
    row = conn.execute("SELECT 1 FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        raise ValueError(f"Memory not found: {memory_id}")

def create_memory(content: str, importance: int = 0, tags: Any = None) -> dict:
    """
    Create a memory record and return it as a dict.
    memory_id is a TEXT uuid.
    """
    content = (content or "").strip()
    if not content:
        raise ValueError("Memory content cannot be empty.")

    mem_id = str(uuid.uuid4())
    now = _utcnow_iso()
    tags_text = _normalize_tags(tags)

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO memories (id, content, importance, tags, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (mem_id, content, int(importance or 0), tags_text, now, now),
        )

        row = conn.execute(
            "SELECT id, content, importance, tags, created_at, updated_at FROM memories WHERE id = ?",
            (mem_id,),
        ).fetchone()

    return {
        "id": row["id"],
        "content": row["content"],
        "importance": int(row["importance"]) if row["importance"] is not None else 0,
        "tags": row["tags"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def memory_link_project(memory_id: str, project_id: int) -> None:
    """
    Link an existing memory to an existing project.
    Idempotent via PRIMARY KEY (memory_id, project_id).
    """
    if not memory_id or not str(memory_id).strip():
        raise ValueError("memory_id is required.")
    if project_id is None:
        raise ValueError("project_id is required.")

    with db_session() as conn:
        _ensure_memory_exists(conn, memory_id)
        _ensure_project_exists(conn, int(project_id))

        conn.execute(
            """
            INSERT OR IGNORE INTO memory_projects (memory_id, project_id)
            VALUES (?, ?)
            """,
            (memory_id, int(project_id)),
        )


def memory_link_conversation(memory_id: str, conversation_id: str) -> None:
    """
    Link an existing memory to an existing conversation.
    Idempotent via PRIMARY KEY (memory_id, conversation_id).
    """
    if not memory_id or not str(memory_id).strip():
        raise ValueError("memory_id is required.")
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        _ensure_memory_exists(conn, memory_id)
        _ensure_conversation_exists(conn, conversation_id)

        conn.execute(
            """
            INSERT OR IGNORE INTO memory_conversations (memory_id, conversation_id)
            VALUES (?, ?)
            """,
            (memory_id, conversation_id),
        )

# endregion
# region Memory Pins

def add_memory_pin(text: str) -> int:
    text = (text or "").strip()
    if not text:
        raise ValueError("Pin text cannot be empty.")
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO memory_pins(text, created_at) VALUES(?, ?)",
            (text, _utcnow_iso()),
        )
        if cur.lastrowid is None:
            raise RuntimeError("failed to retrieve last insert id")
        return int(cur.lastrowid)

def list_memory_pins(limit: int = 200) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, text, created_at
            FROM memory_pins
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{"id": int(r["id"]), "text": r["text"], "created_at": r["created_at"]} for r in rows]

def delete_memory_pin(pin_id: int) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM memory_pins WHERE id = ?", (pin_id,))

# endregion

# ----------------------------
# Files and Artifacts
# ----------------------------

# region Files

def _ensure_file_exists(conn: sqlite3.Connection, file_id: int | str) -> None:
    file_id_str = str(file_id).strip()
    if not file_id_str:
        raise ValueError("file_id is required.")
    row = conn.execute("SELECT 1 FROM files WHERE id = ?", (file_id_str,)).fetchone()
    if row is None:
        raise ValueError(f"File not found: {file_id_str}")
    
def register_file(name: str, path: str, mime_type: str | None = None) -> dict:
    name = (name or "").strip()
    path = (path or "").strip()
    mime_type = (mime_type or "").strip() or None
    if not name:
        raise ValueError("File name cannot be empty.")
    if not path:
        raise ValueError("File path cannot be empty.")

    fid = str(uuid.uuid4())
    now = _utcnow_iso()

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO files (id, name, path, mime_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fid, name, path, mime_type, now, now),
        )
    return {"id": fid}

def project_add_file(project_id: int, file_id: str) -> None:
    if project_id is None:
        raise ValueError("project_id is required.")
    file_id = (file_id or "").strip()
    if not file_id:
        raise ValueError("file_id is required.")

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        _ensure_file_exists(conn, file_id)

        conn.execute(
            "INSERT OR IGNORE INTO project_files (project_id, file_id) VALUES (?, ?)",
            (int(project_id), file_id),
        )

def conversation_link_file(conversation_id: str, file_id: str) -> None:
    """
    Link a file to a conversation (for chat-scoped context).
    Idempotent via PRIMARY KEY (conversation_id, file_id).
    """
    conversation_id = (conversation_id or "").strip()
    file_id = (file_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")
    if not file_id:
        raise ValueError("file_id is required.")

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        _ensure_file_exists(conn, file_id)
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_files (conversation_id, file_id)
            VALUES (?, ?)
            """,
            (conversation_id, file_id),
        )

def list_files_for_conversation(
    conversation_id: str,
    include_deleted: bool = False,
) -> list[dict]:
    """
    Return all files linked to a conversation via conversation_files,
    optionally excluding soft-deleted ones.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        sql = """
            SELECT f.*
            FROM conversation_files cf
            JOIN files f ON f.id = cf.file_id
            WHERE cf.conversation_id = ?
        """
        params: list[object] = [conversation_id]
        if not include_deleted:
            sql += " AND (f.is_deleted IS NULL OR f.is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()
    
    print(f"[db] list_files_for_conversation({conversation_id!r}, include_deleted={include_deleted}) -> {len(rows)} rows")
    return [dict(r) for r in rows]

def list_files_for_project(
    project_id: int,
    include_deleted: bool = False,
) -> list[dict]:
    """
    Return all files linked to a project via project_files.
    """
    if project_id is None:
        raise ValueError("project_id is required.")
    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        sql = """
            SELECT f.*
            FROM project_files pf
            JOIN files f ON f.id = pf.file_id
            WHERE pf.project_id = ?
        """
        params: list[object] = [int(project_id)]
        if not include_deleted:
            sql += " AND (f.is_deleted IS NULL OR f.is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()
    
    print(f"[db] list_files_for_project({project_id}, include_deleted={include_deleted}) -> {len(rows)} rows")
    return [dict(r) for r in rows]

def list_all_files(include_deleted: bool = False) -> list[dict]:
    """
    Return all files in the files table, optionally including soft-deleted ones.
    """
    with db_session() as conn:
        sql = "SELECT * FROM files"
        params: list[object] = []
        if not include_deleted:
            sql += " WHERE is_deleted IS NULL OR is_deleted = 0"
        rows = conn.execute(sql, params).fetchall()
    print(f"[db] list_all_files(include_deleted={include_deleted}) -> {len(rows)} rows")
    return [dict(r) for r in rows]

def get_files_summary() -> dict:
    """
    Return a simple summary: total file count and counts grouped by scope_type.
    """
    with db_session() as conn:
        total_row = conn.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM files
            WHERE is_deleted IS NULL OR is_deleted = 0
            """
        ).fetchone()
        total = int(total_row["cnt"] if total_row else 0)

        rows = conn.execute(
            """
            SELECT COALESCE(scope_type, '') AS scope_type, COUNT(*) AS cnt
            FROM files
            WHERE is_deleted IS NULL OR is_deleted = 0
            GROUP BY COALESCE(scope_type, '')
            """
        ).fetchall()

    by_scope: dict[str, int] = {}
    for r in rows:
        scope = r["scope_type"] or "global"
        by_scope[scope] = int(r["cnt"])

    return {"total": total, "by_scope": by_scope}

def register_scoped_file(
    name: str,
    path: str,
    mime_type: str | None = None,
    *,
    scope_type: str | None = None,
    scope_id: int | None = None,
    scope_uuid: str | None = None,
    source_kind: str | None = None,
    url: str | None = None,
    provenance: str | None = None,
    description: str | None = None,
) -> dict:
    """
    Register a file with optional scoping/provenance metadata.
    This uses the extended files columns from schema v3.
    """
    name = (name or "").strip()
    path = (path or "").strip()
    mime_type = (mime_type or "").strip() or None
    scope_type = (scope_type or "").strip() or None
    scope_uuid = (scope_uuid or "").strip() or None
    source_kind = (source_kind or "").strip() or None
    url = (url or "").strip() or None
    provenance = (provenance or "").strip() or None
    description = (description or "").strip() or None

    if not name:
        raise ValueError("File name cannot be empty.")
    if not path:
        raise ValueError("File path cannot be empty.")

    fid = str(uuid.uuid4())
    now = _utcnow_iso()

    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO files (
                id,
                name,
                path,
                mime_type,
                scope_type,
                scope_id,
                scope_uuid,
                source_kind,
                url,
                provenance,
                description,
                is_deleted,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                fid,
                name,
                path,
                mime_type,
                scope_type,
                scope_id,
                scope_uuid,
                source_kind,
                url,
                provenance,
                description,
                now,
                now,
            ),
        )
    return {"id": fid}

def update_file_description(file_id: str, description: str | None) -> None:
    file_id = (file_id or "").strip()
    if not file_id:
        raise ValueError("file_id is required.")

    desc = (description or "").strip() or None

    with db_session() as conn:
        _ensure_file_exists(conn, file_id)
        conn.execute(
            "UPDATE files SET description = ?, updated_at = ? WHERE id = ?",
            (desc, _utcnow_iso(), file_id),
        )

def get_file_by_id(file_id: str) -> dict:
    """
    Fetch a file row by id from the files table.

    Raises ValueError if the file does not exist.
    """
    file_id = (file_id or "").strip()
    if not file_id:
        raise ValueError("file_id is required.")

    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()

    if row is None:
        raise ValueError(f"File not found: {file_id}")

    return dict(row)

def resolve_scope_for_file(file_row: dict) -> FileScope:
    """
    Decide project_id / scope_type / scope_id / scope_uuid for a file row.
    Supports:
      - project-scoped files, where scope_id is the project_id
      - conversation-scoped files, where we derive project_id from the conversation
        (if the conversation is attached to a project).
      - global/unscoped files, which we treat as belonging to the synthetic Global project.
    """
    scope_type = (file_row.get("scope_type") or "").strip() or None
    scope_id = file_row.get("scope_id")
    scope_uuid = (file_row.get("scope_uuid") or "").strip() or None

    project_id: int | None = None

    if scope_type == "project" and scope_id is not None:
        project_id = int(scope_id)
    elif scope_type == "conversation" and scope_uuid:
        with db_session() as conn:
            row = conn.execute(
                "SELECT project_id FROM conversations WHERE id = ?",
                (scope_uuid,),
            ).fetchone()
        if row is not None and row["project_id"] is not None:
            project_id = int(row["project_id"])
        else:
            project_id = None
    else:
        # Treat explicit 'global' or NULL scope as belonging to the synthetic Global project.
        project_id = get_global_project_id()
        scope_type = "global"

    return FileScope(
        project_id=project_id,
        scope_type=scope_type,
        scope_id=scope_id if isinstance(scope_id, int) else None,
        scope_uuid=scope_uuid,
    )

# endregion
# region Artifacts

def create_file_artifacts(
    *,
    file_row: dict,
    project_id: int,
    scope_type: str | None,
    scope_id: int | None,
    scope_uuid: str | None,
    chunks: list[str],
    source_kind: str | None,
    provenance: str | None,
) -> list[str]:
    """
    Insert one artifact row per chunk for a given file.

    Handles soft-deleting the previous artifact set for that file_id.

    Returns the list of artifact IDs.
    """
    from .db import soft_delete_artifacts_for_file  # safe self-import once module is loaded

    file_id = file_row.get("id")
    if not file_id:
        raise ValueError("file_row missing 'id'")

    file_id_str = str(file_id)

    # Soft delete old artifacts for this file.
    try:
        soft_delete_artifacts_for_file(file_id_str)
    except Exception as e:
        # Fallback if helper is missing or fails (during odd migration states).
        now = _utcnow_iso()
        with db_session() as conn:
            conn.execute(
                """
                UPDATE artifacts
                SET is_deleted = 1, deleted_at = ?
                WHERE file_id = ?
                  AND (is_deleted IS NULL OR is_deleted = 0)
                """,
                (now, file_id_str),
            )

    artifact_ids: list[str] = []
    name = file_row.get("name") or Path(str(file_row.get("path", "file"))).name
    tags: Any = None

    for idx, chunk in enumerate(chunks):
        if not chunk:
            continue

        # Create the artifact row itself.
        try:
            art = create_scoped_artifact(
                project_id=project_id,
                name=name,
                content=chunk,
                tags=tags,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_uuid=scope_uuid,
                file_id=file_id_str,
                source_kind=source_kind,
                provenance=provenance,
                chunk_index=idx,
            )
        except TypeError:
            # Fallback for older signature without chunk_index.
            art = create_scoped_artifact(
                project_id=project_id,
                name=name,
                content=chunk,
                tags=tags,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_uuid=scope_uuid,
                file_id=file_id_str,
                source_kind=source_kind,
                provenance=provenance,
            )

        art_id = art.get("id")
        if not art_id:
            continue

        artifact_ids.append(str(art_id))

        # If this file is conversation-scoped, link the artifact to that conversation.
        if scope_type == "conversation" and scope_uuid:
            try:
                conversation_link_artifact(scope_uuid, str(art_id))
            except Exception:
                # Don’t explode artifact creation just because linking failed.
                pass

    return artifact_ids

def create_artifact(project_id: int, name: str, content: str, tags: Any = None) -> dict:
    if project_id is None:
        raise ValueError("project_id is required.")
    name = (name or "").strip()
    content = (content or "").strip()
    tags_text = _normalize_tags(tags)  # from earlier memory helper; ok if tags is str/None/list
    if not name:
        raise ValueError("Artifact name cannot be empty.")
    if not content:
        raise ValueError("Artifact content cannot be empty.")

    aid = str(uuid.uuid4())
    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        conn.execute(
            """
            INSERT INTO artifacts (id, project_id, name, content, tags, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (aid, int(project_id), name, content, tags_text, _utcnow_iso()),
        )
    return {"id": aid}

def conversation_link_artifact(conversation_id: str, artifact_id: str) -> None:
    """
    Link an artifact to a conversation (chat-scoped derived content).
    """
    conversation_id = (conversation_id or "").strip()
    artifact_id = (artifact_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")
    if not artifact_id:
        raise ValueError("artifact_id is required.")

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        row = conn.execute(
            "SELECT 1 FROM artifacts WHERE id = ?",
            (artifact_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Artifact not found: {artifact_id}")

        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_artifacts (conversation_id, artifact_id)
            VALUES (?, ?)
            """,
            (conversation_id, artifact_id),
        )


def list_artifacts_for_conversation(
    conversation_id: str,
    include_deleted: bool = False,
) -> list[dict]:
    """
    Return all artifacts linked to a conversation, optionally excluding soft-deleted.
    """
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        sql = """
            SELECT a.*
            FROM conversation_artifacts ca
            JOIN artifacts a ON a.id = ca.artifact_id
            WHERE ca.conversation_id = ?
        """
        params: list[object] = [conversation_id]
        if not include_deleted:
            sql += " AND (a.is_deleted IS NULL OR a.is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]


def list_artifacts_for_project(
    project_id: int,
    include_deleted: bool = False,
) -> list[dict]:
    """
    Convenience to fetch all artifacts under a project.
    Right now it's just a straight select on artifacts.project_id.
    """
    if project_id is None:
        raise ValueError("project_id is required.")

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        sql = """
            SELECT *
            FROM artifacts
            WHERE project_id = ?
        """
        params: list[object] = [int(project_id)]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]

def list_artifacts_for_file(
    file_id: int | str,
    include_deleted: bool = False,
) -> list[dict]:
    """
    Return all artifacts associated with a given file_id,
    ordered by chunk_index (if present) and updated_at.
    """
    file_id_str = str(file_id).strip()
    if not file_id_str:
        raise ValueError("file_id is required.")

    with db_session() as conn:
        _ensure_file_exists(conn, file_id_str)
        sql = """
            SELECT *
            FROM artifacts
            WHERE file_id = ?
        """
        params: list[object] = [file_id_str]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        sql += " ORDER BY chunk_index ASC, updated_at ASC"
        rows = conn.execute(sql, params).fetchall()

    print(f"[db] list_artifacts_for_file({file_id_str!r}, include_deleted={include_deleted}) -> {len(rows)} rows")
    return [dict(r) for r in rows]

def soft_delete_artifacts_for_file(
    file_id: int | str,
    deleted_by_user_id: str | None = None,
) -> int:
    """
    Soft-delete all artifacts associated with a given file_id.

    Returns the number of rows affected.
    """
    file_id_str = str(file_id).strip()
    if not file_id_str:
        raise ValueError("file_id is required.")

    deleted_by_user_id = (deleted_by_user_id or "").strip() or None
    now = _utcnow_iso()

    with db_session() as conn:
        _ensure_file_exists(conn, file_id_str)
        cur = conn.execute(
            """
            UPDATE artifacts
            SET is_deleted = 1,
                deleted_at = ?,
                deleted_by_user_id = ?
            WHERE file_id = ?
              AND (is_deleted IS NULL OR is_deleted = 0)
            """,
            (now, deleted_by_user_id, file_id_str),
        )
        return cur.rowcount

def create_scoped_artifact(
    project_id: int,
    name: str,
    content: str,
    tags: Any = None,
    *,
    scope_type: str | None = None,
    scope_id: int | None = None,
    scope_uuid: str | None = None,
    file_id: str | None = None,
    source_kind: str | None = None,
    provenance: str | None = None,
    chunk_index: int | None = None,
) -> dict:
    """
    Extended artifact-creation helper that fills the additional schema columns.

    This is the variant you should use for file-/scope-aware artifacts
    and for multi-chunk file artifacts (via chunk_index).
    """
    if project_id is None:
        raise ValueError("project_id is required.")
    name = (name or "").strip()
    content = (content or "").strip()
    if not name:
        raise ValueError("Artifact name cannot be empty.")
    if not content:
        raise ValueError("Artifact content cannot be empty.")

    tags_text = _normalize_tags(tags)
    scope_type = (scope_type or "").strip() or None
    scope_uuid = (scope_uuid or "").strip() or None
    file_id = (file_id or "").strip() or None
    source_kind = (source_kind or "").strip() or None
    provenance = (provenance or "").strip() or None

    if chunk_index is None:
        chunk_index_int: int | None = None
    else:
        try:
            chunk_index_int = int(chunk_index)
        except (TypeError, ValueError):
            raise ValueError("chunk_index must be an integer or None.")
        if chunk_index_int < 0:
            raise ValueError("chunk_index cannot be negative.")

    aid = str(uuid.uuid4())
    now = _utcnow_iso()

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        conn.execute(
            """
            INSERT INTO artifacts (
                id,
                project_id,
                name,
                content,
                tags,
                scope_type,
                scope_id,
                scope_uuid,
                file_id,
                source_kind,
                provenance,
                chunk_index,
                is_deleted,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                aid,
                int(project_id),
                name,
                content,
                tags_text,
                scope_type,
                scope_id,
                scope_uuid,
                file_id,
                source_kind,
                provenance,
                chunk_index_int,
                now,
            ),
        )

    return {"id": aid}

def reset_all_artifacts() -> None:
    """
    Hard-reset the artifacts table. Intended for use during development
    or after changing artifact semantics; artifacts will be lazily
    rebuilt by _ensure_artifacts_for_files().

    Hard-reset the artifact graph:
      - delete all conversation_artifacts rows
      - delete all artifacts rows

    Safe because artifacts are derived from files and can be rebuilt lazily.
    """
    with db_session() as conn:
        print("[db] reset_all_artifacts: deleting conversation_artifacts and artifacts")

        # First, clear the child table that references artifacts.id
        if _table_exists(conn, "conversation_artifacts"):
            conn.execute("DELETE FROM conversation_artifacts")

        if _table_exists(conn, "project_artifacts"):
            conn.execute("DELETE FROM project_artifacts")

        # Now it's safe to delete from artifacts
        if _table_exists(conn, "artifacts"):
            conn.execute("DELETE FROM artifacts")

        conn.commit()
        print("[db] reset_all_artifacts: done")

# endregion