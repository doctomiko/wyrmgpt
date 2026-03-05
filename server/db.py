# server/db.py
from asyncio import log
import hashlib
import sqlite3
import json
import sys
import uuid
import re
from pathlib import Path
from pydantic.dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from .markdown_helper import autolink_text, apply_house_markdown_normalization
# Support legacy migrations from v1-v7. You can remove this after a few releases once most users have migrated or started fresh.
from .db_migrate import migrate_schema_legacy

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "callie_mvp.sqlite3"
_VALID_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")

SCHEMA_VERSION = 8  

SIDECAR_THRESHOLD_BYTES = 500 * 1024 # 500KB default threshold for when to use sidecar files for artifact content

# near the top of db.py, alongside other imports or type helpers:
@dataclass
class FileScope:
    project_id: int | None
    scope_type: str | None
    scope_id: int | None
    scope_uuid: str | None

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()

def ensure_parent_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)

def new_uuid() -> str:
    return str(uuid.uuid4())

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

# region Migration helpers

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

def _add_column_if_missing(conn: sqlite3.Connection, table: str, col: str, coldef: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")

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

# endregion

# region Latest migrations

def migrate_schema_v8(conn: sqlite3.Connection) -> None:
    """
    This migration makes changes to artifacts in support of future RAG implementation
    """
    conn.executescript(f"""
    DROP TABLE IF EXISTS artifacts;

    CREATE TABLE artifacts (
        -- Primary key: TEXT uuid (you already do this)
        id TEXT PRIMARY KEY,

        -- Provenance (keep what you already use; add what you need)
        source_kind TEXT NOT NULL,          -- e.g. 'file','web','memory','message','conversation_summary'
        scope_type  TEXT,                   -- e.g. 'project','conversation','global'
        scope_id    INTEGER,                -- links to tables with id as a int
        scope_uuid  TEXT,                   -- links to tables with id as text/uuid -- project id / conversation id / etc (TEXT to stay flexible)
        source_id   TEXT,                   -- e.g. file_id, memory_id, message_id (store as TEXT for uniformity)
        title       TEXT,
        provenance  TEXT,
        tags        TEXT,                       

        -- Canonical readable content: exactly one of these
        content_text  TEXT,
        sidecar_path  TEXT,

        -- Invalidation + later policy knobs
        content_hash  TEXT,                 -- sha256 hex of canonical text
        content_bytes INTEGER,              -- bytes of canonical text (inline or sidecar)
        updated_at    TEXT,                 -- ISO8601 UTC

        -- Optional ranking metadata (if you already have these, keep them)
        significance  REAL DEFAULT 0.0,
        tags_json     TEXT,
                       
        project_id INTEGER,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        deleted_at TEXT,
        deleted_by_user_id TEXT
    );
    """)
    conn.executescript(f"""
    -- Enforce mutual exclusivity: content_text XOR sidecar_path (or both NULL allowed)
    CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_ins
    BEFORE INSERT ON artifacts
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
            THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
        END;
    END;

    CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_upd
    BEFORE UPDATE OF content_text, sidecar_path ON artifacts
    FOR EACH ROW
    BEGIN
        SELECT CASE
            WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
            THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
        END;
    END;

    CREATE INDEX IF NOT EXISTS idx_artifacts_scope ON artifacts(scope_type, scope_id);
    CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_kind, source_id);
    CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(content_hash);
    CREATE INDEX IF NOT EXISTS idx_artifacts_updated_at ON artifacts(updated_at);
    CREATE INDEX IF NOT EXISTS idx_artifacts_project_id ON artifacts(project_id);
""")

def _apply_schema_v8(conn: sqlite3.Connection) -> None:
    # TODO add columns from past migrations
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

            -- v7 additions
            is_global INTEGER DEFAULT 0,
            is_hidden INTEGER DEFAULT 0,

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

            -- v6 additions
            author_meta TEXT,

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

            -- v4 additions (scope/provenance/url + soft delete)
            scope_type TEXT,
            scope_id INTEGER,
            scope_uuid TEXT,
            source_kind TEXT,
            url TEXT,
            description TEXT,
            provenance TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by_user_id TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_files_scope ON files(scope_type, scope_id, scope_uuid);
        CREATE INDEX IF NOT EXISTS idx_files_url ON files(url);

        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 0,
            tags TEXT,

            -- v4 soft delete additions
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by_user_id TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS artifacts (
            -- Primary key
            id TEXT PRIMARY KEY,

            -- legacy/artifacting columns used by current code
            project_id INTEGER,
            -- name TEXT, -- no longer used in v8
            -- content TEXT, -- no longer used in v8
            tags TEXT,

            scope_type TEXT,
            scope_id INTEGER,
            scope_uuid TEXT,

            -- file_id TEXT, -- this has been phased out in favor of source_id
            source_kind TEXT,
            provenance TEXT,

            -- v4 soft delete columns
            is_deleted INTEGER NOT NULL DEFAULT 0,
            deleted_at TEXT,
            deleted_by_user_id TEXT,

            -- v5 chunking (you can stop using it, but code still references it)
            -- chunk_index INTEGER,

            -- v8 “article-ish cache” columns (can coexist with legacy content)
            title TEXT,
            source_id TEXT,
            content_text TEXT,
            sidecar_path TEXT,
            content_hash TEXT,
            content_bytes INTEGER,

            -- optional ranking metadata
            significance REAL DEFAULT 0.0,
            tags_json TEXT,

            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (project_id) REFERENCES projects(id),
            -- instructed by Callie to leave this out.. for now. Makes sense to me if it refers to multiple types of sources, not just files. We can always add specific foreign keys for different source_kinds if we want later.
            --FOREIGN KEY (source_id) REFERENCES files(id)
        );

        -- v8 mutual exclusivity: content_text XOR sidecar_path
        CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_ins
        BEFORE INSERT ON artifacts
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
                THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
            END;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_upd
        BEFORE UPDATE OF content_text, sidecar_path ON artifacts
        FOR EACH ROW
        BEGIN
            SELECT CASE
                WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
                THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
            END;
        END;

        CREATE INDEX IF NOT EXISTS idx_artifacts_project_id ON artifacts(project_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_source ON artifacts(source_kind, source_id);
        CREATE INDEX IF NOT EXISTS idx_artifacts_scope ON artifacts(scope_type, scope_id, scope_uuid);
        CREATE INDEX IF NOT EXISTS idx_artifacts_hash ON artifacts(content_hash);
        CREATE INDEX IF NOT EXISTS idx_artifacts_updated_at ON artifacts(updated_at);

        -- v4 context cache
        CREATE TABLE IF NOT EXISTS context_cache (
            conversation_id TEXT PRIMARY KEY,
            project_id INTEGER,
            cache_key TEXT NOT NULL DEFAULT 'default',
            payload TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        -- v4 conversation-scoped links
        CREATE TABLE IF NOT EXISTS conversation_files (
            conversation_id TEXT NOT NULL,
            file_id TEXT NOT NULL,
            PRIMARY KEY (conversation_id, file_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (file_id) REFERENCES files(id)
        );

        CREATE TABLE IF NOT EXISTS conversation_artifacts (
            conversation_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            PRIMARY KEY (conversation_id, artifact_id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id),
            FOREIGN KEY (artifact_id) REFERENCES artifacts(id)
        );

        -- join tables you already use
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

# endregion

# region Clean builds for new databases

# endregion

def init_schema_start(conn: sqlite3.Connection) -> int:
    """
    Returns the current schema version, or 0 if not set. This also ensures the schema_meta table exists.
    """
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    current = int(row["value"]) if row and str(row["value"]).isdigit() else 0
    return current

def init_schema_end(conn: sqlite3.Connection, current: int) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    print(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")
    # TODO implement seperate log file and log there as well.
    #log.logger.info(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")

def init_schema() -> None:
    with db_session() as conn:
        # Get the current schema version, or 0 if not set. This also ensures the schema_meta table exists.
        current = init_schema_start(conn);
        # Comment the next line after cached artifacts are cleared
        # You should not need to do this very often. We'll work on a button later.
        # reset_all_artifacts()
        if current == 0:
            # Clean slate - create all tables
            _apply_schema_v8(conn)
            init_schema_end(conn, current)
            return

        if current < SCHEMA_VERSION - 1:
            # Destructive changes - commented unless needed
            if (False):
                dropped = drop_empty_satellite_tables(conn)
                print("Dropped:", dropped)

                if _db_has_user_data(conn):
                    raise RuntimeError(
                        "Refusing destructive migration: DB already has data. "
                        "Write a non-destructive migration before upgrading."
                    )
                _drop_all_tables(conn)

            # Warn user that this is deprecated and they should migrate or start fresh. We can remove this code in a future release after giving users time to adjust.
            print(f"\nWARNING: Database schema is {current}, code expects {SCHEMA_VERSION}.")
            print(f"DB path: {DB_PATH}")
            print("Recommended action: delete the DB file and restart.\n")
            if not sys.stdin.isatty():
                raise RuntimeError("Refusing legacy migration without an interactive console. Delete DB and restart.")

            resp = input("Type MIGRATE to attempt legacy migration anyway, or anything else to abort: ").strip().upper()
            if resp != "MIGRATE":
                raise RuntimeError("Aborted legacy migration. Delete DB and restart.")

            migrate_schema_legacy(conn)
            migrate_schema_v8(conn)
        else:
            if current == SCHEMA_VERSION - 1:
                migrate_schema_v8(conn)

        init_schema_end(conn, current)

# endregion

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
        now = _utc_now_iso()
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
        now = _utc_now_iso()
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
                (int(project_id), _utc_now_iso(), conversation_id),
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
    params.append(_utc_now_iso())
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
    now = _utc_now_iso()
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
            (title, _utc_now_iso(), conversation_id),
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
            (project_id, _utc_now_iso(), conversation_id),
        )

def set_conversation_archived(conversation_id: str, archived: bool) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?",
            (1 if archived else 0, _utc_now_iso(), conversation_id),
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
            (json.dumps(summary_obj), _utc_now_iso(), conversation_id),
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
    now = _utc_now_iso()

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
    now = _utc_now_iso()
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
                        (t, _utc_now_iso(), conversation_id),
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

        text = r["content"]
        text = apply_house_markdown_normalization(text)
        text = autolink_text(text)
        result.append({"role": r["role"], "created_at": r["created_at"], "content": text, "author_meta": r["author_meta"]})
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
    now = _utc_now_iso()
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
            (text, _utc_now_iso()),
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
    now = _utc_now_iso()

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
    now = _utc_now_iso()

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
            (desc, _utc_now_iso(), file_id),
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

def gather_scoped_files(conversation_id: str) -> dict[str, dict]:
    """
    Collect all files that should be considered for this conversation:
    - conversation-scoped
    - project-scoped (if any)
    - global/unassigned
    Returns a dict keyed by file id -> file row, to dedupe across scopes.
    """
    sources = get_context_sources(conversation_id)
    project_id = sources.get("project_id")

    files_by_id: dict[str, dict] = {}

    # Conversation-scoped files
    for f in list_files_for_conversation(conversation_id, include_deleted=False):
        files_by_id[f["id"]] = f

    # Project-scoped files, if any
    if project_id:
        for f in list_files_for_project(project_id, include_deleted=False):
            files_by_id[f["id"]] = f

    # Global / unscoped files
    for f in list_all_files(include_deleted=False):
        scope_type = f.get("scope_type")
        # Treat explicit "global" or completely unscoped files as global.
        if not scope_type or scope_type == "global":
            files_by_id[f["id"]] = f

    print(f"[context] gather_scoped_files({conversation_id!r}) -> {len(files_by_id)} files")
    return files_by_id

# endregion
# region Artifacts

# region Artifact-File Hygeine

def get_conversation_project_id(conn, conversation_id: str) -> int | None:
    row = conn.execute(
        "SELECT project_id FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not row:
        return None
    pid = row["project_id"]
    return int(pid) if pid not in (None, "") else None


def list_files_missing_artifacts_for_scope(
    conn,
    *,
    scope_type: str,
    scope_id: int | None = None,
    scope_uuid: str | None = None,
    limit: int = 10,
) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.*
        FROM files f
        LEFT JOIN artifacts a
          ON a.source_id = f.id
         AND a.source_kind LIKE 'file:%'
         AND a.is_deleted = 0
        WHERE f.is_deleted = 0
          AND f.scope_type = ?
          AND ( ? IS NULL OR f.scope_id = ? )
          AND ( ? IS NULL OR f.scope_uuid = ? )
          AND a.id IS NULL
        ORDER BY f.created_at DESC
        LIMIT ?
        """,
        (scope_type, scope_id, scope_id, scope_uuid, scope_uuid, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def ensure_files_artifacted_for_conversation_conn(
    conn,
    *,
    conversation_id: str,
    limit_per_scope: int = 5,
    include_global: bool = False,
) -> dict:
    """
    Same as ensure_files_artifacted_for_conversation, but uses an existing conn.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return {"checked": 0, "created": 0, "details": {}}

    created_total = 0
    checked_total = 0
    details: dict[str, dict[str, int]] = {}

    def _heal(scope_label: str, scope_type: str, scope_id: int | None, scope_uuid: str | None) -> None:
        nonlocal created_total, checked_total, details

        missing = list_files_missing_artifacts_for_scope(
            conn,
            scope_type=scope_type,
            scope_id=scope_id,
            scope_uuid=scope_uuid,
            limit=limit_per_scope,
        )
        checked_total += len(missing)

        created = 0
        for f in missing:
            try:
                # Note: upsert_file_artifact hydrates file_row now (per your recent fix),
                # so passing the DB row dict is enough.
                upsert_file_artifact(
                    conn,
                    file_row=f,
                    scope_type=scope_type,
                    scope_id=str(scope_id) if scope_id is not None else (scope_uuid if scope_uuid else None),
                )
                created += 1
                created_total += 1
            except Exception:
                # your existing logging in upsert_file_artifact / artifactor should capture details
                pass

        details[scope_label] = {"missing_checked": len(missing), "created": created}

    # Conversation-scoped files
    _heal("conversation", "conversation", None, cid)

    # Project-scoped files (if conversation is in a project)
    pid = get_conversation_project_id(conn, cid)
    if pid is not None:
        _heal("project", "project", pid, None)

    # Optional global
    if include_global:
        _heal("global", "global", None, None)

    return {"checked": checked_total, "created": created_total, "details": details}


def ensure_files_artifacted_for_conversation(
    *,
    conversation_id: str,
    limit_per_scope: int = 5,
    include_global: bool = False,
) -> dict:
    """
    Open its own DB session so main.py doesn't need db_session.
    """
    with db_session() as conn:
        return ensure_files_artifacted_for_conversation_conn(
            conn,
            conversation_id=conversation_id,
            limit_per_scope=limit_per_scope,
            include_global=include_global,
        )

if (False): # Above function uses its own conn
    def get_conversation_project_id(conn, conversation_id: str) -> int | None:
        row = conn.execute(
            "SELECT project_id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if not row:
            return None
        pid = row["project_id"]
        return int(pid) if pid not in (None, "") else None

if (False): # above version makes its own conn
    def list_files_missing_artifacts_for_scope(
        conn,
        *,
        scope_type: str,
        scope_id: int | None = None,
        scope_uuid: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Returns file rows in a scope that have no non-deleted file:* artifact.
        """
        rows = conn.execute(
            """
            SELECT f.*
            FROM files f
            LEFT JOIN artifacts a
            ON a.source_id = f.id
            AND a.source_kind LIKE 'file:%'
            AND a.is_deleted = 0
            WHERE f.is_deleted = 0
            AND f.scope_type = ?
            AND ( ? IS NULL OR f.scope_id = ? )
            AND ( ? IS NULL OR f.scope_uuid = ? )
            AND a.id IS NULL
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (scope_type, scope_id, scope_id, scope_uuid, scope_uuid, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]

if (False): # above version makes its own conn
    def ensure_files_artifacted_for_conversation(
        conn,
        *,
        conversation_id: str,
        limit_per_scope: int = 5,
        include_global: bool = False,
    ) -> dict:
        """
        Best-effort self-heal:
        - conversation-scoped files
        - project-scoped files for the conversation's project_id
        - optionally global files
        Returns counts for diagnostics.
        """
        cid = (conversation_id or "").strip()
        if not cid:
            return {"checked": 0, "created": 0, "details": {}}

        created_total = 0
        checked_total = 0
        details: dict[str, dict[str, int]] = {}

        def _heal(scope_label: str, scope_type: str, scope_id: int | None, scope_uuid: str | None) -> None:
            nonlocal created_total, checked_total, details
            missing = list_files_missing_artifacts_for_scope(
                conn,
                scope_type=scope_type,
                scope_id=scope_id,
                scope_uuid=scope_uuid,
                limit=limit_per_scope,
            )
            checked_total += len(missing)
            created = 0
            for f in missing:
                try:
                    # Upsert artifact and scope it consistently
                    upsert_file_artifact(
                        conn,
                        file_row=f,
                        scope_type=scope_type,
                        scope_id=str(scope_id) if scope_id is not None else (scope_uuid if scope_uuid else None),
                    )
                    created += 1
                    created_total += 1
                except Exception:
                    # your existing logging in upsert_file_artifact / artifactor will record details
                    pass
            details[scope_label] = {"missing_checked": len(missing), "created": created}

        # Conversation scope
        _heal("conversation", "conversation", None, cid)

        # Project scope (if this conversation belongs to a project)
        pid = get_conversation_project_id(conn, cid)
        if pid is not None:
            _heal("project", "project", pid, None)

        # Global scope optional (only if you actually use global files)
        if include_global:
            _heal("global", "global", None, None)

        return {"checked": checked_total, "created": created_total, "details": details}

def count_files_missing_artifacts(conn, *, scope_type: str, scope_id: str | None) -> int:
    """
    Count files that exist in a scope but have no non-deleted artifact row.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM files f
        LEFT JOIN artifacts a
          ON a.source_kind LIKE 'file:%'
         AND a.source_id = f.id
         AND a.is_deleted = 0
        WHERE f.is_deleted = 0
          AND f.scope_type = ?
          AND ( ( ? IS NULL AND f.scope_id IS NULL ) OR f.scope_id = ? )
          AND a.id IS NULL
        """,
        (scope_type, scope_id, scope_id),
    ).fetchone()
    return int(row["n"] if row else 0)


def list_files_missing_artifacts(conn, *, scope_type: str, scope_id: str | None, limit: int = 10) -> list[dict]:
    """
    Return file rows missing artifacts in this scope.
    """
    rows = conn.execute(
        """
        SELECT f.*
        FROM files f
        LEFT JOIN artifacts a
          ON a.source_kind LIKE 'file:%'
         AND a.source_id = f.id
         AND a.is_deleted = 0
        WHERE f.is_deleted = 0
          AND f.scope_type = ?
          AND ( ( ? IS NULL AND f.scope_id IS NULL ) OR f.scope_id = ? )
          AND a.id IS NULL
        ORDER BY f.created_at DESC
        LIMIT ?
        """,
        (scope_type, scope_id, scope_id, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def ensure_scope_file_artifacts(conn, *, scope_type: str, scope_id: str | None, limit: int = 5) -> int:
    """
    Create artifacts for missing files in this scope, up to 'limit'.
    Returns number artifacted.
    """
    missing = list_files_missing_artifacts(conn, scope_type=scope_type, scope_id=scope_id, limit=limit)
    n = 0
    for file_row in missing:
        try:
            upsert_file_artifact(conn, file_row=file_row, scope_type=scope_type, scope_id=scope_id)
            n += 1
        except Exception:
            # log where you already log db/artifact failures
            pass
    return n

# endregion

# region Artifact and Sidecar Helpers

def _deterministic_artifact_id(
    *,
    source_kind: str,                          # "file", "web", "memory", "message", "conversation_summary", etc.
    source_id: str | None = None,       # file_id / memory_id / message_id / whatever
    url: str | None = None,             # for web
    conversation_id: str | None = None, # for message/summary
    chunk_index: int | None = None,     # if you ever want deterministic per-chunk IDs
) -> str:
    """
    Deterministic, filename-safe artifact id.

    Examples:
      file:     kind="file", source_id="<file_uuid>" => "file--<file_uuid>"
      web/url:  kind="web",  url="https://..."       => "web--<sha1>"
      memory:   kind="memory", source_id="<uuid>"    => "memory--<uuid>"
      message:  kind="message", conversation_id="<cid>", source_id="<msgid>"
               => "message--<cid>--<msgid>"
      convo summary: kind="conversation_summary", conversation_id="<cid>"
               => "conversation_summary--<cid>"
    """

    kind = (source_kind or "").strip().lower() or "misc"
    # TODO is the below regex no longer needed now?
    kind = kind.split(":", 1)[0]   # "file:pdf" -> "file"

    def safe(s: str) -> str:
        s = (s or "").strip()
        return _SAFE_ID_RE.sub("_", s) if s else ""

    def sha1_hex(s: str) -> str:
        return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()

    if kind in ("web", "url"):
        u = (url or source_id or "").strip()
        if not u:
            raise ValueError("deterministic_artifact_id: web/url requires url or source_id")
        base = f"web--{sha1_hex(u)}"

    elif kind in ("file", "upload"):
        if not source_id:
            raise ValueError("deterministic_artifact_id: file requires source_id (file_id)")
        base = f"file--{safe(str(source_id))}"

    elif kind in ("memory", "fact"):
        if not source_id:
            raise ValueError("deterministic_artifact_id: memory requires source_id (memory_id)")
        base = f"memory--{safe(str(source_id))}"

    elif kind in ("message", "chat_message"):
        if not conversation_id or source_id is None:
            raise ValueError("deterministic_artifact_id: message requires conversation_id and source_id (message_id)")
        base = f"message--{safe(conversation_id)}--{safe(str(source_id))}"

    elif kind in ("conversation_summary", "chat_summary"):
        if not conversation_id:
            raise ValueError("deterministic_artifact_id: conversation_summary requires conversation_id")
        base = f"conversation_summary--{safe(conversation_id)}"

    else:
        # Generic: stable hash if only a blob key exists
        if source_id:
            base = f"{safe(kind)}--{safe(str(source_id))}"
        elif url:
            base = f"{safe(kind)}--{sha1_hex(url)}"
        elif conversation_id:
            base = f"{safe(kind)}--{safe(conversation_id)}"
        else:
            # last resort: deterministic but not meaningful
            base = f"{safe(kind)}--{sha1_hex(kind)}"

    if chunk_index is not None:
        base = f"{base}--c{int(chunk_index)}"

    return base

def _safe_source_folder(source_kind: str) -> str:
    """
    "file:image" -> "file": note the folder normalization—Windows hates file:image as a directory name, so we store under file/ not file:image/
    """
    return source_kind.split(":", 1)[0] if source_kind else "misc"

def _write_artifact_sidecar(*, source_kind: str, artifact_id: str, text: str) -> str:
    rel = Path("articles") / _safe_source_folder(source_kind) / f"artifact.{artifact_id}.txt"
    # relative path is what's stored in DB
    abs_path = Path(DATA_DIR) / rel
    ensure_parent_dir(abs_path)
    abs_path.write_text(text, encoding="utf-8")
    return str(rel).replace("\\", "/")

def _delete_sidecar_if_exists(*, sidecar_path: str | None) -> None:
    if not sidecar_path:
        return
    p = Path(DATA_DIR) / sidecar_path
    try:
        p.unlink()
    except FileNotFoundError:
        pass

def _hydrate_artifact_content_text(art: dict) -> dict:
    """
    Ensure art['content_text'] is populated.

    Rules:
      1) If content_text already present and non-empty, keep it.
      2) Else if sidecar_path exists, read it and put into content_text.
    """
    # Commented out:
    # 3) Else (legacy fallback): if 'content' exists and is non-empty, copy into content_text.
    #    This is only for transition; once you drop the column, this does nothing.
    existing = art.get("content_text")
    if existing is not None and str(existing).strip() != "":
        return art

    sidecar_path = (art.get("sidecar_path") or "").strip() or None
    if sidecar_path:
        p = Path(DATA_DIR) / sidecar_path
        try:
            art["content_text"] = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            art["content_text"] = ""
        except Exception as exc:
            print(f"[db] sidecar read failed for artifact {art.get('id')} path={sidecar_path}: {exc}")
            art["content_text"] = ""
    return art

    # Legacy fallback until you fully remove artifacts.content
    # legacy = art.get("content")
    #if legacy is not None and str(legacy).strip() != "":
    #    art["content_text"] = legacy
    #else:
    # art["content_text"] = ""
    # return art

# endregion

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

def ensure_artifacts_for_files(files_by_id: dict[str, dict]) -> None:
    """
    For each file, if there are no (non-deleted) artifacts, call artifact_file(file_row).
    Swallow errors per-file so one broken file doesn't kill the context build.

    files_by_id is a dict of file_id -> file_row (as dict) for all files relevant to a context build, keyed by file_id which feeds into artifacts source_id.
    """

    print(f"[context] ensure_artifacts_for_files: checking {len(files_by_id)} files")     
    for file_id, file_row in files_by_id.items():
        # If file row doesn't have data, we are the data layer, so let's go get it!!
        if file_row == None:
            file_row = get_file_by_id(file_id)
        try:
            existing = list_artifacts_for_file(file_id, include_deleted=False)
            print(f"[context] file {file_id}: {len(existing)} existing artifacts")
        except Exception as exc:
            print(f"[context] list_artifacts_for_file failed for file {file_id}: {exc}")
            continue

        if existing:
            continue  # already artifacted

        try:
            artifact_file(file_row)
        except Exception as exc:
            # This might be "no project_id for global file" or a decode error; just log and move on.
            print(f"[context] artifact_file failed for file {file_id}: {exc}")
            continue

def list_artifacts_for_file(
    file_id: int | str,
    include_deleted: bool = False,
) -> list[dict]:
    file_id_str = str(file_id).strip()
    if not file_id_str:
        raise ValueError("file_id is required.")

    with db_session() as conn:
        _ensure_file_exists(conn, file_id_str)
        sql = """
            SELECT *
            FROM artifacts
            WHERE source_id = ?
        """
        params: list[object] = [file_id_str]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        sql += " ORDER BY updated_at ASC" # chunk_index ASC, 
        rows = conn.execute(sql, params).fetchall()

    out = [dict(r) for r in rows]
    for art in out:
        _hydrate_artifact_content_text(art)

    print(f"[db] list_artifacts_for_file({file_id_str!r}, include_deleted={include_deleted}) -> {len(out)} rows")
    return out

def list_artifacts_for_project(
    project_id: int,
    include_deleted: bool = False,
    ) -> list[dict]:
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

    out = [dict(r) for r in rows]
    for art in out:
        _hydrate_artifact_content_text(art)
    return out

def list_artifacts_for_conversation(
    conversation_id: str,
    include_deleted: bool = False,
) -> list[dict]:
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

    out = [dict(r) for r in rows]
    for art in out:
        _hydrate_artifact_content_text(art)
    return out

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
    now = _utc_now_iso()

    with db_session() as conn:
        _ensure_file_exists(conn, file_id_str)
        cur = conn.execute(
            """
            UPDATE artifacts
            SET is_deleted = 1,
                deleted_at = ?,
                deleted_by_user_id = ?
            WHERE source_id = ?
              AND (is_deleted IS NULL OR is_deleted = 0)
            """,
            (now, deleted_by_user_id, file_id_str),
        )
        return cur.rowcount

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

def rebuild_file_artifacts_batch(conn, *, data_dir="data", sidecar_threshold_bytes=200_000) -> int:
    # IMPORTANT: import locally to avoid circular import at module load
    from .artifactor import extract_text_from_file

    rows = conn.execute("SELECT * FROM files").fetchall()
    created = 0
    for r in rows:
        upsert_file_artifact(
            conn,
            file_row=r,
            sidecar_threshold_bytes=sidecar_threshold_bytes,
        )
        created += 1
    return created

def artifact_file(file_row) -> str:
    """
    Convenience wrapper around upsert_file_artifact for end-to-end artifacting of a single file.
    Helpful when calling from artifacor.py or other places where you don't already have a db connection.
    Creates conn from db_session() and calls upsert_file_artifact.
    """
    with db_session() as conn:
        aid = upsert_file_artifact(
            conn,
            file_row=file_row,
        )
    return aid

def upsert_file_artifact(
    conn,
    *,
    file_row: dict,  # or sqlite row; needs ["id"]
    scope_type: str = "global",
    scope_id: str | None = None,
    sidecar_threshold_bytes: int = SIDECAR_THRESHOLD_BYTES,
) -> str:
    """
    Ensure we have a complete file_row (path/mime_type/name) before extracting.
    This fixes uploads that pass only {"id": ...}.
    """
    from .artifactor import extract_text_from_file

    # Normalize to dict
    if not isinstance(file_row, dict):
        file_row = dict(file_row)

    file_id = (file_row.get("id") or "").strip()
    if not file_id:
        raise ValueError("upsert_file_artifact: file_row missing id")

    # HYDRATE if incomplete
    if not file_row.get("path") or not file_row.get("name"):
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise ValueError(f"upsert_file_artifact: file not found: {file_id}")
        file_row = dict(row)

    title = (file_row.get("title") or None)

    content_text, source_kind = extract_text_from_file(file_row)

    artifact_id = upsert_artifact_text(
        conn=conn,
        source_id=file_id,
        source_kind=source_kind,
        title=title,
        scope_type=scope_type,
        scope_id=scope_id,
        text=content_text,
        sidecar_threshold_bytes=sidecar_threshold_bytes,
    )
    return artifact_id

if (False): # Replaced by version that correctly calls artifactor
    def upsert_file_artifact(
        conn,
        *,
        file_row: dict, # or sqlite row; just needs ["id"] and optionally ["title"]
        scope_type: str = "global",
        scope_id: str | None = None,
        sidecar_threshold_bytes: int = SIDECAR_THRESHOLD_BYTES,
    ) -> str:
        from .artifactor import extract_text_from_file

        file_id = file_row["id"] if isinstance(file_row, dict) else file_row["id"]
        title = (file_row.get("title") if isinstance(file_row, dict) else None) or None
        content_text, source_kind = extract_text_from_file(file_row)
        artifact_id = upsert_artifact_text(
            conn=conn,
            source_id=file_id,
            source_kind=source_kind, # can be "file:pdf" etc; safe folder handled by _safe_source_folder
            title=title,
            scope_type=scope_type,
            scope_id=scope_id,
            text=content_text,
            sidecar_threshold_bytes=sidecar_threshold_bytes,
        )
        return artifact_id

def upsert_artifact_text(
    conn,
    *,
    source_kind: str = "unspecified",
    source_id: str | None = None,
    title: str | None = None,
    scope_type: str = "global",
    scope_id: str | None = None,
    text: str,
    sidecar_threshold_bytes: int = SIDECAR_THRESHOLD_BYTES,
) -> str:
    if text is None:
        text = ""
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    content_bytes = len(norm.encode("utf-8"))
    content_hash = _sha256_hex(norm)
    
    artifact_id = _deterministic_artifact_id(
        source_kind=source_kind,
        source_id=source_id,
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO artifacts (id, source_kind, source_id, title, scope_type, scope_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (artifact_id, source_kind, source_id, title, scope_type, scope_id, _utc_now_iso()),
    )
    # Hopefully that worked and now we have...
    row = conn.execute(
        "SELECT sidecar_path FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"artifact not found: {artifact_id}")
    old_sidecar_path = row[0]

    use_sidecar = content_bytes > sidecar_threshold_bytes

    if use_sidecar:
        new_sidecar_path = _write_artifact_sidecar(
            source_kind=source_kind,
            artifact_id=artifact_id,
            text=norm,
        )
        conn.execute(
            """
            UPDATE artifacts
            SET content_text = NULL,
                sidecar_path = ?,
                content_hash = ?,
                content_bytes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (new_sidecar_path, content_hash, content_bytes, _utc_now_iso(), artifact_id),
        )
        if old_sidecar_path and old_sidecar_path != new_sidecar_path:
            _delete_sidecar_if_exists(sidecar_path=old_sidecar_path)
    else:
        conn.execute(
            """
            UPDATE artifacts
            SET content_text = ?,
                sidecar_path = NULL,
                content_hash = ?,
                content_bytes = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (norm, content_hash, content_bytes, _utc_now_iso(), artifact_id),
        )
        if old_sidecar_path:
            _delete_sidecar_if_exists(sidecar_path=old_sidecar_path)
    return artifact_id

# endregion