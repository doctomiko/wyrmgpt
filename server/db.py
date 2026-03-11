# server/db.py
from asyncio import log
from enum import Enum
import hashlib
import sqlite3
import json
import sys
import uuid
import re
from pathlib import Path
from pydantic.dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from .logging_helper import log_debug
from .config import (
    AppConfig,
    load_app_config,
    UIConfig,
    load_ui_config,
    CoreConfig, 
    load_core_config, 
    QueryConfig, 
    load_query_config, 
)
from .markdown_helper import autolink_text, apply_house_markdown_normalization
from .chunking import chunk_text_with_hints
# Support legacy migrations from v1-v7. You can remove this after a few releases once most users have migrated or started fresh.
from .db_migrate import _migrate_schema_legacy

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "callie_mvp.sqlite3"
_VALID_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")

SCHEMA_VERSION = 17

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

# region Big Chunky SQL

def _migrate_schema_v8(conn: sqlite3.Connection) -> None:
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

    -- v14 app_settings
    CREATE TABLE IF NOT EXISTS app_settings (
        scope_type TEXT NOT NULL DEFAULT 'global',
        scope_id TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (scope_type, scope_id, key)
    );
                       
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

            -- v11 additions (sha256 hash)
            sha256 TEXT,

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

            -- v12 metadata (for other uses)
            meta_json TEXT,

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

        CREATE TABLE IF NOT EXISTS app_settings (
            scope_type TEXT NOT NULL DEFAULT 'global',
            scope_id TEXT NOT NULL DEFAULT '',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope_type, scope_id, key)
        );
        """
    )

    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )

# endregion

# region Slightly Older but Newer Migrations

# Basically just makes new tables, but we'll call it a migration regardless
def _migrate_schema_v9(conn) -> None:
    """
    Adds corpus_chunks + FTS index for retrieval.
    Non-destructive: only creates new tables/triggers.
    """
    # corpus_chunks: one row per chunk
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS corpus_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            -- provenance
            artifact_id TEXT NOT NULL,
            artifact_content_hash TEXT,
            source_kind TEXT,
            source_id TEXT,

            -- optional file hints (if the artifact came from a file)
            file_id TEXT,
            filename TEXT,
            mime_type TEXT,

            -- scoping (strings keep it simple: "conversation:<cid>", "project:<pid>", "global")
            scope_key TEXT NOT NULL,

            chunk_index INTEGER NOT NULL,
            start_char INTEGER,
            end_char INTEGER,

            text TEXT NOT NULL,

            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),

            UNIQUE(artifact_id, chunk_index)
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_chunks_scope ON corpus_chunks(scope_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_corpus_chunks_artifact ON corpus_chunks(artifact_id)")

    # FTS virtual table linked to corpus_chunks
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS corpus_fts
        USING fts5(
            text,
            content='corpus_chunks',
            content_rowid='id',
            tokenize='porter'
        )
        """
    )

    # Triggers to keep FTS in sync
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS corpus_chunks_ai
        AFTER INSERT ON corpus_chunks
        BEGIN
          INSERT INTO corpus_fts(rowid, text) VALUES (new.id, new.text);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS corpus_chunks_ad
        AFTER DELETE ON corpus_chunks
        BEGIN
          INSERT INTO corpus_fts(corpus_fts, rowid, text) VALUES('delete', old.id, old.text);
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS corpus_chunks_au
        AFTER UPDATE OF text ON corpus_chunks
        BEGIN
          INSERT INTO corpus_fts(corpus_fts, rowid, text) VALUES('delete', old.id, old.text);
          INSERT INTO corpus_fts(rowid, text) VALUES (new.id, new.text);
        END
        """
    )

def _migrate_schema_v10(conn) -> None:
    _add_column_if_missing(conn, "artifacts", "summary_text", "TEXT")
    _add_column_if_missing(conn, "artifacts", "summary_model", "TEXT")
    _add_column_if_missing(conn, "artifacts", "summary_input_hash", "TEXT")
    _add_column_if_missing(conn, "artifacts", "summary_updated_at", "TEXT")

def _migrate_schema_v11(conn) -> None:
    _add_column_if_missing(conn, "files", "sha256", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha256 ON files(sha256)")

def _migrate_schema_v12(conn) -> None:
    _add_column_if_missing(conn, "artifacts", "meta_json", "TEXT")

def _migrate_schema_v13(conn) -> None:
    _add_column_if_missing(conn, "projects", "visibility", "TEXT NOT NULL DEFAULT 'private'")
    conn.execute("""
        UPDATE projects
        SET visibility = 'private'
        WHERE visibility IS NULL OR TRIM(visibility) = ''
    """)
                 
def _migrate_schema_v14(conn) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        scope_type TEXT NOT NULL DEFAULT 'global',
        scope_id TEXT NOT NULL DEFAULT '',
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (scope_type, scope_id, key)
    );
    """)

def _migrate_schema_v15(conn) -> None:
    # Adjusts the memory_pins table to be used for personalization/instructions
    if _table_exists(conn, "memory_pins"):
        _add_column_if_missing(conn, "memory_pins", "pin_kind", "TEXT NOT NULL DEFAULT 'instruction'")
        _add_column_if_missing(conn, "memory_pins", "title", "TEXT")
        _add_column_if_missing(conn, "memory_pins", "value_json", "TEXT")
        _add_column_if_missing(conn, "memory_pins", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "memory_pins", "is_enabled", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "memory_pins", "scope_type", "TEXT NOT NULL DEFAULT 'global'")
        _add_column_if_missing(conn, "memory_pins", "scope_id", "INTEGER")
        _add_column_if_missing(conn, "memory_pins", "updated_at", "TEXT")
        conn.execute("""
            UPDATE memory_pins
            SET pin_kind = 'instruction'
            WHERE pin_kind IS NULL OR TRIM(pin_kind) = ''
        """)
        conn.execute("""
            UPDATE memory_pins
            SET is_enabled = 1
            WHERE is_enabled IS NULL
        """)
        conn.execute("""
            UPDATE memory_pins
            SET sort_order = 0
            WHERE sort_order IS NULL
        """)
        conn.execute("""
            UPDATE memory_pins
            SET updated_at = COALESCE(updated_at, created_at, ?)
            WHERE updated_at IS NULL OR TRIM(updated_at) = ''
        """, (_utc_now_iso(),))

        pin_cols = {r["name"] for r in conn.execute("PRAGMA table_info(memory_pins)").fetchall()}
        if "project_id" in pin_cols:
            conn.execute("""
                UPDATE memory_pins
                SET
                    scope_type = CASE WHEN project_id IS NULL THEN 'global' ELSE 'project' END,
                    scope_id   = CASE WHEN project_id IS NULL THEN scope_id ELSE project_id END
            """)

    # New provenance fields for memories
    _add_column_if_missing(conn, "memories", "is_enabled", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "memories", "scope_type", "TEXT NOT NULL DEFAULT 'global'")
    _add_column_if_missing(conn, "memories", "scope_id", "INTEGER")
    _add_column_if_missing(conn, "memories", "created_by", "TEXT NOT NULL DEFAULT 'user'")
    _add_column_if_missing(conn, "memories", "origin_kind", "TEXT NOT NULL DEFAULT 'user_asserted'")
    _add_column_if_missing(conn, "memories", "source_conversation_id", "TEXT")
    _add_column_if_missing(conn, "memories", "source_message_id", "TEXT")

    conn.execute("""
        UPDATE memories
        SET scope_type = 'scope_type'
        WHERE scope_type IS NULL OR TRIM(scope_type) = ''
    """)
    conn.execute("""
        UPDATE memories
        SET created_by = 'user'
        WHERE created_by IS NULL OR TRIM(created_by) = ''
    """)
    conn.execute("""
        UPDATE memories
        SET origin_kind = 'user_asserted'
        WHERE origin_kind IS NULL OR TRIM(origin_kind) = ''
    """)

    # Shadow existing pins into memories, but do not duplicate exact-content matches.
    # We are NOT deleting pins yet in this pass, because that would change current context behavior.
    if _table_exists(conn, "memory_pins"):
        pin_rows = conn.execute("""
            SELECT id, text, created_at
            FROM memory_pins
            WHERE TRIM(COALESCE(text, '')) <> ''
            ORDER BY id ASC
        """).fetchall()

        for row in pin_rows:
            text = (row["text"] or "").strip()
            if not text:
                continue

            already = conn.execute("""
                SELECT 1
                FROM memories
                WHERE TRIM(content) = TRIM(?)
                LIMIT 1
            """, (text,)).fetchone()
            if already:
                continue

            mem_id = new_uuid()
            created_at = row["created_at"] or _utc_now_iso()

            conn.execute("""
                INSERT INTO memories (
                    id,
                    content,
                    importance,
                    tags,
                    created_by,
                    origin_kind,
                    source_conversation_id,
                    source_message_id,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mem_id,
                text,
                10,                 # per your instruction
                None,
                "user",             # existing memories/pins are assumed human-authored
                "user_asserted",
                None,
                None,
                created_at,
                created_at,
            ))

# endregion

def _migrate_schema_v16(conn) -> None:
    if _table_exists(conn, "memory_pins"):
        _add_column_if_missing(conn, "memory_pins", "pin_kind", "TEXT NOT NULL DEFAULT 'instruction'")
        _add_column_if_missing(conn, "memory_pins", "title", "TEXT")
        _add_column_if_missing(conn, "memory_pins", "value_json", "TEXT")
        _add_column_if_missing(conn, "memory_pins", "sort_order", "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(conn, "memory_pins", "is_enabled", "INTEGER NOT NULL DEFAULT 1")
        _add_column_if_missing(conn, "memory_pins", "scope_type", "TEXT NOT NULL DEFAULT 'global'")
        _add_column_if_missing(conn, "memory_pins", "scope_id", "INTEGER")
        _add_column_if_missing(conn, "memory_pins", "updated_at", "TEXT")

        conn.execute("""
            UPDATE memory_pins
            SET pin_kind = 'instruction'
            WHERE pin_kind IS NULL OR TRIM(pin_kind) = ''
        """)
        conn.execute("""
            UPDATE memory_pins
            SET is_enabled = 1
            WHERE is_enabled IS NULL
        """)
        conn.execute("""
            UPDATE memory_pins
            SET sort_order = 0
            WHERE sort_order IS NULL
        """)
        conn.execute("""
            UPDATE memory_pins
            SET updated_at = COALESCE(updated_at, created_at, ?)
            WHERE updated_at IS NULL OR TRIM(updated_at) = ''
        """, (_utc_now_iso(),))

def _migrate_schema_v17(conn) -> None:
    _add_column_if_missing(conn, "memories", "scope_type", "TEXT NOT NULL DEFAULT 'global'")
    _add_column_if_missing(conn, "memories", "scope_id", "INTEGER")

    conn.execute("""
        UPDATE memories
        SET scope_type = 'global'
        WHERE scope_type IS NULL
           OR TRIM(scope_type) = ''
           OR scope_type = 'scope_type'
           OR LOWER(scope_type) NOT IN ('global', 'project')
    """)

    conn.execute("""
        UPDATE memories
        SET scope_id = NULL
        WHERE COALESCE(scope_type, 'global') = 'global'
    """)
# endregion

# region Clean builds for new databases

# endregion

def _start_schema_init(conn: sqlite3.Connection) -> int:
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

def _end_schema_init(conn: sqlite3.Connection, current: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )

    conn.execute("PRAGMA foreign_keys = ON;")
    print(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")
    # TODO implement seperate log file and log there as well.
    #log.logger.info(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")

def init_schema() -> None:
    with db_session() as conn:
        # Get the current schema version, or 0 if not set. This also ensures the schema_meta table exists.
        current = _start_schema_init(conn);
        # Comment the next line after cached artifacts are cleared
        # You should not need to do this very often. We'll work on a button later.
        # reset_all_artifacts()
        if current == 0:
            # Clean slate - create all tables
            _apply_schema_v8(conn)
            _migrate_schema_v9(conn)
            _migrate_schema_v10(conn)
            _migrate_schema_v11(conn)
            _migrate_schema_v12(conn)
            _migrate_schema_v13(conn)
            _migrate_schema_v14(conn)
            _migrate_schema_v15(conn)
            _migrate_schema_v16(conn)
            _migrate_schema_v17(conn)
            _end_schema_init(conn, current)
            return

        if current < 7:
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
            _migrate_schema_legacy(conn)
        if current < 8:
            _migrate_schema_v8(conn)
        if current < 9:
            _migrate_schema_v9(conn)
        if current < 10:
            _migrate_schema_v10(conn)
        if current < 11:
            _migrate_schema_v11(conn)
        if current < 12:
            _migrate_schema_v12(conn)
        if current < 13:
            _migrate_schema_v13(conn)
        if current < 14:
            _migrate_schema_v14(conn)
        if current < 15:
            _migrate_schema_v15(conn)
        if current < 16:
            _migrate_schema_v16(conn)
        if current < 17:
            _migrate_schema_v17(conn)
        _end_schema_init(conn, current)

# endregion

# region App Configuration

def get_app_setting(
    key: str,
    default: str | None = None,
    scope_type: str = "global",
    scope_id: str = "",
) -> str | None:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT value
            FROM app_settings
            WHERE scope_type = ? AND scope_id = ? AND key = ?
            """,
            ((scope_type or "global").strip(), (scope_id or "").strip(), key.strip()),
        ).fetchone()
        return row["value"] if row else default


def set_app_setting(
    key: str,
    value: str,
    scope_type: str = "global",
    scope_id: str = "",
) -> None:
    now = _utc_now_iso()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (scope_type, scope_id, key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(scope_type, scope_id, key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                (scope_type or "global").strip(),
                (scope_id or "").strip(),
                key.strip(),
                value,
                now,
            ),
        )


def get_app_setting_bool(
    key: str,
    scope_type: str = "global",
    scope_id: str = "",
    default: bool = False,
) -> bool:
    raw = get_app_setting(key, None, scope_type, scope_id)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")

def ensure_default_app_setting(
    key: str,
    value: str,
    scope_type: str = "global",
    scope_id: str = "",
) -> None:
    now = _utc_now_iso()
    with db_session() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO app_settings (scope_type, scope_id, key, value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (scope_type or "global").strip(),
                (scope_id or "").strip(),
                key.strip(),
                value,
                now,
            ),
        )

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
            "visibility": r["visibility"],
            "description": r["description"],
            "system_prompt": r["system_prompt"],
            "override_core_prompt": bool(r["override_core_prompt"]),
            "default_advanced_mode": bool(r["default_advanced_mode"]),
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

def get_conversation_project_id(conn, conversation_id: str) -> int | None:
    row = conn.execute(
        "SELECT project_id FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if not row:
        return None
    pid = row["project_id"]
    return int(pid) if pid not in (None, "") else None

def get_or_create_project(name: str, visibility: str = "private") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Project name cannot be empty.")

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, name, visibility, created_at, updated_at FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        if row:
            return {
                "id": int(row["id"]),
                "name": row["name"],
                "visibility": row["visibility"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

        puuid = str(uuid.uuid4())
        now = _utc_now_iso()
        conn.execute(
            """
            INSERT INTO projects (uuid, name, visibility, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (puuid, name, visibility, now, now),
        )
        row2 = conn.execute(
            "SELECT id, name, visibility, created_at, updated_at FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        return {
            "id": int(row2["id"]),
            "name": row2["name"],
            "visibility": row2["visibility"],
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

def update_project(
    project_id: int,
    name: str | None = None,
    visibility: str | None = None,
    description: str | None = None,
    system_prompt: str | None = None,
    override_core_prompt: bool | None = None,
    default_advanced_mode: bool | None = None,
) -> dict:
    sets = []
    params = []
    invalidate_all = False

    if name is not None:
        n = (name or "").strip()
        if not n:
            raise ValueError("Project name cannot be empty.")
        sets.append("name = ?")
        params.append(n)

    if description is not None:
        sets.append("description = ?")
        params.append(description)

    if visibility is not None:
        v = (visibility or "").strip().lower()
        if v not in ("private", "global"):
            raise ValueError("visibility must be 'private' or 'global'")
        sets.append("visibility = ?")
        params.append(v)
        invalidate_all = True

    if system_prompt is not None:
        sets.append("system_prompt = ?")
        params.append((system_prompt or "").strip())
        invalidate_all = True

    if override_core_prompt is not None:
        sets.append("override_core_prompt = ?")
        params.append(1 if override_core_prompt else 0)
        invalidate_all = True

    if default_advanced_mode is not None:
        sets.append("default_advanced_mode = ?")
        params.append(1 if default_advanced_mode else 0)

    if not sets:
        raise ValueError("No changes provided.")

    sets.append("updated_at = ?")
    params.append(_utc_now_iso())
    params.append(int(project_id))

    with db_session() as conn:
        _ensure_project_exists(conn, int(project_id))
        conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", tuple(params))
        row = conn.execute(
            """
            SELECT id, name, visibility, description, system_prompt,
                   override_core_prompt, default_advanced_mode,
                   created_at, updated_at
            FROM projects
            WHERE id = ?
            """,
            (int(project_id),),
        ).fetchone()

    if invalidate_all:
        invalidate_all_context_cache()

    return {
        "id": int(row["id"]),
        "name": row["name"],
        "visibility": row["visibility"],
        "description": row["description"],
        "system_prompt": row["system_prompt"],
        "override_core_prompt": bool(row["override_core_prompt"]),
        "default_advanced_mode": bool(row["default_advanced_mode"]),
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

def _scope_keys_for_conversation(conn, conversation_id: str, include_global: bool = False) -> list[str]:
    cid = (conversation_id or "").strip()
    keys = [f"conversation:{cid}", f"chat:{cid}"]

    row = conn.execute(
        "SELECT project_id FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    current_pid = int(row["project_id"]) if row and row["project_id"] is not None else None

    if current_pid is not None:
        keys.append(f"project:{current_pid}")

    global_rows = conn.execute(
        """
        SELECT id
        FROM projects
        WHERE visibility = 'global'
          AND (is_hidden IS NULL OR is_hidden = 0)
          AND (is_global IS NULL OR is_global = 0)
        """
    ).fetchall()
    for r in global_rows:
        pid = int(r["id"])
        if pid != current_pid:
            keys.append(f"project:{pid}")

    if include_global:
        keys.append("global")

    return keys

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
    
def _summary_excerpt(text: str, max_chars: int = 220) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    parts = re.split(r'(?<=[.!?])\s+', s)
    out = " ".join(parts[:2]).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rstrip() + "…"
    return out

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
                p.name AS project_name,
                s.summary_text AS summary_text
            FROM conversations c
            LEFT JOIN projects p ON p.id = c.project_id
            LEFT JOIN artifacts s
              ON s.source_kind = 'conversation:summary'
             AND s.source_id = c.id
             AND s.is_deleted = 0
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
                "summary_excerpt": _summary_excerpt(r["summary_text"] or ""),
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
            SELECT c.project_id, p.name AS project_name, c.archived -- , c.summary_json
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
        # "summary_json": row["summary_json"] if row else None,
        "preview_limit": int(preview_limit),
        "messages_preview": preview,
    }

def get_context_sources(conversation_id: str) -> dict:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT
              c.id AS conversation_id,
              -- c.summary_json,
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
            # "summary_json": row["summary_json"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "project_system_prompt": row["project_system_prompt"],
            "override_core_prompt": row["override_core_prompt"],
        }

# endregion
# region Conversation Summaries (now in Artifacts)

def conversation_summary_artifact_id(conversation_id: str) -> str:
    return _deterministic_artifact_id(source_kind="conversation:summary", source_id=conversation_id)

def save_conversation_summary_artifact(conversation_id: str, summary_text: str, model: str) -> str:
    title = get_conversation_title(conversation_id) or "Conversation"
    artifact_id = conversation_summary_artifact_id(conversation_id)

    with db_session() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts
            (id, source_kind, source_id, title, scope_type, scope_uuid, updated_at)
            VALUES (?, ?, ?, ?, 'conversation', ?, ?)
            """,
            (artifact_id, "conversation:summary", conversation_id, f"Summary: {title}", conversation_id, _utc_now_iso()),
        )
        set_artifact_summary(conn, artifact_id, summary_text, model)
        conn.execute("UPDATE conversations SET summary_json = NULL WHERE id = ?", (conversation_id,))

    # Make the summary immediately searchable
    reindex_artifact_by_id(artifact_id)
    return artifact_id

def get_conversation_summary_text(conversation_id: str) -> str:
    """
    Preferred: artifact summary.
    Fallback: legacy conversations.summary_json if present.
    """
    aid = conversation_summary_artifact_id(conversation_id)
    with db_session() as conn:
        s = get_artifact_summary(conn, aid, include_stale=False)
        if s and s.get("summary_text"):
            return (s["summary_text"] or "").strip()

        # Fallback for old data
        row = conn.execute("SELECT summary_json FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row and row["summary_json"]:
            try:
                obj = json.loads(row["summary_json"])
                return (obj.get("summary") or "").strip()
            except Exception:
                return ""
    return ""

def get_transcript_for_summary(conversation_id: str) -> tuple[str, str]:
    """Retrieves information to summarize a conversation history"""
    title = get_conversation_title(conversation_id)

    # Only "not found" if row is missing. Empty title is allowed.
    if title is None:
        raise KeyError("Conversation not found.")

    title = (title or "").strip() or f"Conversation {conversation_id}"

    with db_session() as conn:
        msgs = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    if not msgs:
        raise ValueError("Conversation is empty.")

    transcript = "\n\n".join(f"{m['role']}: {m['content']}" for m in msgs)
    return title, transcript

# region Conversation Transcript Artifacts

TRANSCRIPT_SOURCE_KIND = "conversation:transcript"
TRANSCRIPT_FORMAT_VERSION = 1

_TRANSCRIPT_ZEIT_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"⟂ts=\d+"
    r"|⟂t=\d{8}T\d{6}Z(?:\s+⟂age=-?\d+)?"
    r")\s*\n",
    re.UNICODE,
)
_TRANSCRIPT_LEGACY_PREFIX_RE = re.compile(r"^\s*\[20\d\d-[^\]]+\]\s*\n")


def _json_loads_or_empty_dict(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _json_dumps_stable(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_dt_loose(value: str | None) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_utc_header_stamp(value: str | None) -> str:
    dt = _parse_dt_loose(value)
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_local_header_stamp(value: str | None, tz_name: str) -> str:
    dt = _parse_dt_loose(value)
    if not dt:
        return ""
    try:
        local_dt = dt.astimezone(ZoneInfo(tz_name))
    except Exception:
        local_dt = dt
    return local_dt.strftime("%a %Y-%m-%d %H:%M:%S %Z")


def _strip_transcript_prefixes(text: str) -> str:
    if not text:
        return text
    text = _TRANSCRIPT_ZEIT_PREFIX_RE.sub("", text, count=1)
    text = _TRANSCRIPT_LEGACY_PREFIX_RE.sub("", text, count=1)
    return text.lstrip("\ufeff")


def conversation_transcript_artifact_id(conversation_id: str) -> str:
    cid = (conversation_id or "").strip()
    if not cid:
        raise ValueError("conversation_id is required.")
    safe_cid = _SAFE_ID_RE.sub("_", cid)
    return f"conversation_transcript--{safe_cid}"


def _get_conversation_title_conn(conn: sqlite3.Connection, conversation_id: str) -> str | None:
    row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        return None
    return (row["title"] or "").strip() or None


def _get_messages_raw_for_transcript_conn(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    after_message_id: int | None = None,
) -> list[dict]:
    params: list[Any] = [conversation_id]
    sql = """
        SELECT id, role, content, created_at, meta, author_meta
        FROM messages
        WHERE conversation_id = ?
    """
    if after_message_id is not None:
        sql += " AND id > ?"
        params.append(int(after_message_id))
    sql += " ORDER BY id ASC"

    rows = conn.execute(sql, params).fetchall()

    out: list[dict] = []
    for r in rows:
        meta_obj = _json_loads_or_empty_dict(r["meta"])
        author_meta_obj = _json_loads_or_empty_dict(r["author_meta"])
        out.append(
            {
                "id": int(r["id"]),
                "role": r["role"],
                "content": r["content"] or "",
                "created_at": r["created_at"],
                "meta": meta_obj,
                "author_meta": author_meta_obj,
            }
        )
    return out


def _get_latest_message_state_conn(conn: sqlite3.Connection, conversation_id: str) -> dict:
    row = conn.execute(
        """
        SELECT
            MAX(id) AS latest_message_id,
            MAX(created_at) AS latest_message_created_at,
            COUNT(*) AS message_count
        FROM messages
        WHERE conversation_id = ?
        """,
        (conversation_id,),
    ).fetchone()

    latest_id = int(row["latest_message_id"] or 0) if row else 0
    latest_created_at = row["latest_message_created_at"] if row else None
    message_count = int(row["message_count"] or 0) if row else 0

    return {
        "latest_message_id": latest_id,
        "latest_message_created_at": latest_created_at,
        "message_count": message_count,
    }

def _ensure_conversation_transcript_artifact_row(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    title: str | None = None,
) -> str:
    artifact_id = conversation_transcript_artifact_id(conversation_id)
    now = _utc_now_iso()
    title = (title or "").strip() or f"Transcript: {conversation_id}"

    proj_row = conn.execute(
        "SELECT project_id FROM conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    project_id = int(proj_row["project_id"]) if proj_row and proj_row["project_id"] is not None else None

    conn.execute(
        """
        INSERT OR IGNORE INTO artifacts
        (id, project_id, source_kind, source_id, title, scope_type, scope_uuid, updated_at)
        VALUES (?, ?, ?, ?, ?, 'conversation', ?, ?)
        """,
        (
            artifact_id,
            project_id,
            TRANSCRIPT_SOURCE_KIND,
            conversation_id,
            title,
            conversation_id,
            now,
        ),
    )

    conn.execute(
        """
        UPDATE artifacts
        SET source_kind = ?,
            source_id = ?,
            project_id = ?,
            title = ?,
            scope_type = 'conversation',
            scope_uuid = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            TRANSCRIPT_SOURCE_KIND,
            conversation_id,
            project_id,
            title,
            conversation_id,
            now,
            artifact_id,
        ),
    )

    return artifact_id

def _artifact_meta_json(conn: sqlite3.Connection, artifact_id: str) -> dict:
    row = conn.execute("SELECT meta_json FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    return _json_loads_or_empty_dict(row["meta_json"] if row else None)


def _set_artifact_meta_json(conn: sqlite3.Connection, artifact_id: str, meta: dict) -> None:
    conn.execute(
        "UPDATE artifacts SET meta_json = ?, updated_at = ? WHERE id = ?",
        (_json_dumps_stable(meta), _utc_now_iso(), artifact_id),
    )


def _set_artifact_text_payload(
    conn: sqlite3.Connection,
    *,
    artifact_id: str,
    source_kind: str,
    text: str,
    sidecar_threshold_bytes: int = SIDECAR_THRESHOLD_BYTES,
) -> None:
    norm = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    content_bytes = len(norm.encode("utf-8"))
    content_hash = _sha256_hex(norm)

    row = conn.execute(
        "SELECT sidecar_path FROM artifacts WHERE id = ?",
        (artifact_id,),
    ).fetchone()
    old_sidecar = (row["sidecar_path"] if row else None)

    if content_bytes > int(sidecar_threshold_bytes):
        new_sidecar = _write_artifact_sidecar(source_kind=source_kind, artifact_id=artifact_id, text=norm)
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
            (new_sidecar, content_hash, content_bytes, _utc_now_iso(), artifact_id),
        )
        if old_sidecar and old_sidecar != new_sidecar:
            _delete_sidecar_if_exists(sidecar_path=old_sidecar)
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
        if old_sidecar:
            _delete_sidecar_if_exists(sidecar_path=old_sidecar)


def _transcript_should_skip_message(row: dict) -> bool:
    content = (row.get("content") or "").strip()
    if not content:
        return True

    meta = row.get("meta") or {}

    # summary messages are stored separately as conversation summary artifacts
    if bool(meta.get("summary")):
        return True

    return False


def _transcript_user_identity(author_meta: dict) -> str | None:
    if not isinstance(author_meta, dict):
        return None
    for key in ("display_name", "username", "user_name", "name", "user_id", "author_id"):
        val = (author_meta.get(key) or "")
        if isinstance(val, str) and val.strip():
            return val.strip()
        if val is not None and str(val).strip():
            return str(val).strip()
    return None


def _transcript_header_for_message(row: dict, *, local_timezone: str) -> str:
    role = (row.get("role") or "").strip().lower()
    meta = row.get("meta") or {}
    author_meta = row.get("author_meta") or {}
    created_at = row.get("created_at")

    parts: list[str] = []

    if role == "user":
        parts.append("User")
        ident = _transcript_user_identity(author_meta)
        if ident:
            parts.append(f"user={ident}")

    elif role == "assistant":
        if meta.get("kind") == "error":
            parts.append("System Message")
            slot = (meta.get("slot") or "").strip()
            if slot:
                parts.append(f"source=Assistant {slot}")
            model = (meta.get("model") or "").strip()
            if model:
                parts.append("provider=OpenAI")
                parts.append(f"model={model}")
        elif meta.get("ab_group"):
            slot = (meta.get("slot") or "").strip() or "?"
            parts.append(f"Assistant {slot}")
            model = (meta.get("model") or "").strip()
            if model:
                parts.append("provider=OpenAI")
                parts.append(f"model={model}")
            if "canonical" in meta:
                parts.append(f"canonical={'true' if bool(meta.get('canonical')) else 'false'}")
        else:
            parts.append("Assistant")
            model = (meta.get("model") or "").strip()
            if model:
                parts.append("provider=OpenAI")
                parts.append(f"model={model}")

    elif role == "system":
        parts.append("System Message")
    else:
        parts.append(role.title() if role else "Message")

    msg_id = row.get("id")
    if msg_id is not None:
        parts.append(f"msg_id={msg_id}")

    utc_stamp = _format_utc_header_stamp(created_at)
    local_stamp = _format_local_header_stamp(created_at, local_timezone)

    if utc_stamp:
        parts.append(utc_stamp)
    if local_stamp:
        parts.append(local_stamp)

    return "[" + " | ".join(parts) + "]"


def _render_conversation_transcript_block(row: dict, *, local_timezone: str) -> str:
    body = _strip_transcript_prefixes((row.get("content") or "").rstrip())
    if not body.strip():
        return ""

    header = _transcript_header_for_message(row, local_timezone=local_timezone)
    return f"{header}\n{body}"


def _get_conversation_transcript_status_conn(conn: sqlite3.Connection, conversation_id: str) -> dict:
    msg_state = _get_latest_message_state_conn(conn, conversation_id)

    row = conn.execute(
        """
        SELECT id, updated_at, meta_json
        FROM artifacts
        WHERE source_kind = ?
          AND source_id = ?
          AND (is_deleted IS NULL OR is_deleted = 0)
        LIMIT 1
        """,
        (TRANSCRIPT_SOURCE_KIND, conversation_id),
    ).fetchone()

    artifact_missing = row is None
    artifact_id = row["id"] if row else None
    artifact_updated_at = row["updated_at"] if row else None
    meta = _json_loads_or_empty_dict(row["meta_json"] if row else None)

    last_indexed_id = int(meta.get("last_message_id_indexed") or 0)
    dirty = bool(meta.get("dirty"))

    latest_message_id = int(msg_state["latest_message_id"] or 0)
    latest_message_created_at = msg_state["latest_message_created_at"]
    message_count = int(msg_state["message_count"] or 0)

    stale = artifact_missing or dirty or (latest_message_id > last_indexed_id)

    # Optional timestamp backup check
    if not stale and latest_message_created_at and artifact_updated_at:
        dt_latest = _parse_dt_loose(latest_message_created_at)
        dt_art = _parse_dt_loose(artifact_updated_at)
        if dt_latest and dt_art and dt_latest > dt_art:
            stale = True

    return {
        "conversation_id": conversation_id,
        "artifact_id": artifact_id,
        "artifact_missing": artifact_missing,
        "artifact_updated_at": artifact_updated_at,
        "dirty": dirty,
        "last_message_id_indexed": last_indexed_id,
        "latest_message_id": latest_message_id,
        "latest_message_created_at": latest_message_created_at,
        "message_count": message_count,
        "stale": stale,
    }


def get_conversation_transcript_status(conversation_id: str) -> dict:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")
    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        return _get_conversation_transcript_status_conn(conn, conversation_id)


def mark_conversation_transcript_dirty(
    conversation_id: str,
    *,
    latest_message_id: int | None = None,
    latest_message_created_at: str | None = None,
) -> str:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    #core_cfg = load_core_config()
    ui_cfg = load_ui_config()
    local_timezone = ui_cfg.local_timezone

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        title = _get_conversation_title_conn(conn, conversation_id) or f"Transcript: {conversation_id}"
        artifact_id = _ensure_conversation_transcript_artifact_row(
            conn,
            conversation_id,
            title=f"Transcript: {title}",
        )

        meta = _artifact_meta_json(conn, artifact_id)
        meta.setdefault("conversation_id", conversation_id)
        meta.setdefault("transcript_format_version", TRANSCRIPT_FORMAT_VERSION)
        meta.setdefault("local_timezone", local_timezone)
        meta["dirty"] = True

        if latest_message_id is not None:
            meta["latest_message_id_seen"] = int(latest_message_id)
        if latest_message_created_at:
            meta["latest_message_created_at_seen"] = latest_message_created_at

        _set_artifact_meta_json(conn, artifact_id, meta)

    return artifact_id


def reindex_conversation_transcript_artifact(
    artifact_id: str,
    *,
    tail_rechunk: bool = False,
) -> dict:
    """
    3A.5 hook:
    today this still falls back to full artifact reindex.
    Later this becomes the place to swap in tail-only chunk rebuild logic.
    """
    return reindex_artifact_by_id(artifact_id)


def refresh_conversation_transcript_artifact(
    conversation_id: str,
    *,
    force_full: bool = False,
    reason: str | None = None,
) -> dict:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    #core_cfg = load_core_config()
    ui_cfg = load_ui_config()
    local_timezone = ui_cfg.local_timezone

    artifact_id = conversation_transcript_artifact_id(conversation_id)
    latest_seen_id = 0
    latest_seen_created_at = None
    did_full_rebuild = False
    appended_message_count = 0

    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)

        status = _get_conversation_transcript_status_conn(conn, conversation_id)
        title = _get_conversation_title_conn(conn, conversation_id) or f"Conversation {conversation_id}"

        _ensure_conversation_transcript_artifact_row(
            conn,
            conversation_id,
            title=f"Transcript: {title}",
        )

        meta = _artifact_meta_json(conn, artifact_id)
        existing_text = hydrate_artifact_content_text(conn, artifact_id)

        if not force_full and not status["stale"]:
            meta.setdefault("conversation_id", conversation_id)
            meta.setdefault("transcript_format_version", TRANSCRIPT_FORMAT_VERSION)
            meta.setdefault("local_timezone", local_timezone)
            meta["last_staleness_check_at"] = _utc_now_iso()
            _set_artifact_meta_json(conn, artifact_id, meta)
        else:
            last_indexed = int(meta.get("last_message_id_indexed") or 0)
            need_full = (
                force_full
                or status["artifact_missing"]
                or not existing_text.strip()
                or int(meta.get("transcript_format_version") or 0) != TRANSCRIPT_FORMAT_VERSION
                or last_indexed <= 0
            )

            rows = _get_messages_raw_for_transcript_conn(
                conn,
                conversation_id,
                after_message_id=None if need_full else last_indexed,
            )

            latest_seen_id = last_indexed
            latest_seen_created_at = meta.get("last_message_created_at_utc")

            rendered_blocks: list[str] = []
            for row in rows:
                latest_seen_id = max(latest_seen_id, int(row.get("id") or 0))
                latest_seen_created_at = row.get("created_at") or latest_seen_created_at

                if _transcript_should_skip_message(row):
                    continue

                block = _render_conversation_transcript_block(row, local_timezone=local_timezone)
                if block:
                    rendered_blocks.append(block)

            rendered_tail = "\n\n".join(rendered_blocks).strip()

            if need_full:
                new_text = rendered_tail
                did_full_rebuild = True
            else:
                if rendered_tail and existing_text.strip():
                    new_text = existing_text.rstrip() + "\n\n" + rendered_tail
                elif rendered_tail:
                    new_text = rendered_tail
                else:
                    new_text = existing_text or ""

            msg_state = _get_latest_message_state_conn(conn, conversation_id)
            latest_message_id = int(msg_state["latest_message_id"] or latest_seen_id or 0)
            latest_message_created = msg_state["latest_message_created_at"] or latest_seen_created_at

            meta.update(
                {
                    "conversation_id": conversation_id,
                    "conversation_title": title,
                    "transcript_format_version": TRANSCRIPT_FORMAT_VERSION,
                    "dirty": False,
                    "last_message_id_indexed": latest_message_id,
                    "last_message_created_at_utc": latest_message_created,
                    "message_count_indexed": int(msg_state["message_count"] or 0),
                    "summary_artifact_id": conversation_summary_artifact_id(conversation_id),
                    "local_timezone": local_timezone,
                    "last_incremental_append_at": None if did_full_rebuild else _utc_now_iso(),
                    "last_full_rebuild_at": _utc_now_iso() if did_full_rebuild else meta.get("last_full_rebuild_at"),
                    "last_staleness_check_at": _utc_now_iso(),
                    "chunking_mode": "full",
                    "tail_rechunk_ready": False,  # 3A.5 rail
                }
            )

            _set_artifact_text_payload(
                conn,
                artifact_id=artifact_id,
                source_kind=TRANSCRIPT_SOURCE_KIND,
                text=new_text,
            )
            _set_artifact_meta_json(conn, artifact_id, meta)
            appended_message_count = len(rows)

    reindex_info = reindex_conversation_transcript_artifact(
        artifact_id,
        tail_rechunk=False,
    )

    final_status = get_conversation_transcript_status(conversation_id)
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "artifact_id": artifact_id,
        "force_full": bool(force_full),
        "reason": reason,
        "full_rebuild": did_full_rebuild,
        "appended_message_count": appended_message_count,
        "latest_message_id": final_status["latest_message_id"],
        "last_message_id_indexed": final_status["last_message_id_indexed"],
        "stale_after_refresh": final_status["stale"],
        "reindex": reindex_info,
    }


def ensure_conversation_transcript_artifact_fresh(
    conversation_id: str,
    *,
    force_full: bool = False,
    reason: str | None = None,
) -> dict:
    status = get_conversation_transcript_status(conversation_id)
    if force_full or status["stale"]:
        return refresh_conversation_transcript_artifact(
            conversation_id,
            force_full=force_full,
            reason=reason or "lazy-repair",
        )
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "artifact_id": status["artifact_id"],
        "refreshed": False,
        "stale": status["stale"],
        "latest_message_id": status["latest_message_id"],
        "last_message_id_indexed": status["last_message_id_indexed"],
    }


def export_conversation_transcript_markdown(
    conversation_id: str,
    *,
    refresh_if_stale: bool = True,
    force_full: bool = False,
) -> str:
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    if refresh_if_stale or force_full:
        ensure_conversation_transcript_artifact_fresh(
            conversation_id,
            force_full=force_full,
            reason="export",
        )

    artifact_id = conversation_transcript_artifact_id(conversation_id)
    with db_session() as conn:
        _ensure_conversation_exists(conn, conversation_id)
        return hydrate_artifact_content_text(conn, artifact_id)


def list_stale_conversation_transcripts(limit: int = 200) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id AS conversation_id,
                c.title AS conversation_title,
                a.id AS artifact_id,
                a.updated_at AS artifact_updated_at,
                a.meta_json AS artifact_meta_json,
                x.latest_message_id,
                x.latest_message_created_at,
                x.message_count
            FROM conversations c
            LEFT JOIN artifacts a
              ON a.source_kind = ?
             AND a.source_id = c.id
             AND (a.is_deleted IS NULL OR a.is_deleted = 0)
            LEFT JOIN (
                SELECT
                    conversation_id,
                    MAX(id) AS latest_message_id,
                    MAX(created_at) AS latest_message_created_at,
                    COUNT(*) AS message_count
                FROM messages
                GROUP BY conversation_id
            ) x
              ON x.conversation_id = c.id
            ORDER BY COALESCE(c.updated_at, c.created_at) DESC
            LIMIT ?
            """,
            (TRANSCRIPT_SOURCE_KIND, int(limit)),
        ).fetchall()

        out: list[dict] = []
        for r in rows:
            meta = _json_loads_or_empty_dict(r["artifact_meta_json"])
            latest_message_id = int(r["latest_message_id"] or 0)
            last_indexed = int(meta.get("last_message_id_indexed") or 0)
            dirty = bool(meta.get("dirty"))
            artifact_missing = r["artifact_id"] is None
            stale = artifact_missing or dirty or (latest_message_id > last_indexed)

            out.append(
                {
                    "conversation_id": r["conversation_id"],
                    "conversation_title": r["conversation_title"],
                    "artifact_id": r["artifact_id"],
                    "artifact_updated_at": r["artifact_updated_at"],
                    "latest_message_id": latest_message_id,
                    "latest_message_created_at": r["latest_message_created_at"],
                    "message_count": int(r["message_count"] or 0),
                    "last_message_id_indexed": last_indexed,
                    "dirty": dirty,
                    "artifact_missing": artifact_missing,
                    "stale": stale,
                }
            )

        return [x for x in out if x["stale"]]

# endregion

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

def invalidate_all_context_cache() -> None:
    """
    Drop the entire context cache.
    Use this for changes that can affect many conversations at once,
    such as global/private project visibility changes or global file scope moves.
    """
    with db_session() as conn:
        if not _table_exists(conn, "context_cache"):
            return
        conn.execute("DELETE FROM context_cache")

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
        ) -> int:
    """
    Adds a new message to a chat conversation, then
    dirties the transcript artifact for the
    conversation, so it will get appended/refreshed.
    """
    now = _utc_now_iso()
    meta_json = json.dumps(meta) if meta is not None else None
    author_meta_json = json.dumps(author_meta) if author_meta is not None else None

    new_message_id = 0

    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages(conversation_id, role, content, created_at, meta, author_meta)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, now, meta_json, author_meta_json),
        )
        new_message_id = int(cur.lastrowid or 0)

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

    # Mark transcript dirty outside the insert transaction
    try:
        mark_conversation_transcript_dirty(
            conversation_id,
            latest_message_id=new_message_id if new_message_id > 0 else None,
            latest_message_created_at=now,
        )
    except Exception as exc:
        log_debug("mark_conversation_transcript_dirty failed cid=%s err=%r", conversation_id, exc)

    return new_message_id

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
# Curated Memories
# ----------------------------

# region Memories

def _ensure_memory_exists(conn: sqlite3.Connection, memory_id: str) -> None:
    row = conn.execute("SELECT 1 FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        raise ValueError(f"Memory not found: {memory_id}")

def _memory_row_to_dict(row: sqlite3.Row) -> dict:
    def _split_csv(value: Any) -> list[str]:
        if value is None:
            return []
        return [part for part in str(value).split(",") if part]

    return {
        "id": row["id"],
        "content": row["content"],
        "importance": int(row["importance"]) if row["importance"] is not None else 0,
        "tags": row["tags"],
        "scope_type": (row["scope_type"] or "global"),
        "scope_id": row["scope_id"],
        "created_by": row["created_by"] or "user",
        "origin_kind": row["origin_kind"] or "user_asserted",
        "source_conversation_id": row["source_conversation_id"],
        "source_message_id": row["source_message_id"],
        "project_ids": [int(x) for x in _split_csv(row["project_ids_csv"]) if str(x).isdigit()],
        "conversation_ids": _split_csv(row["conversation_ids_csv"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def _fetch_memory_row(conn: sqlite3.Connection, memory_id: str) -> dict:
    row = conn.execute("""
        SELECT
            m.id,
            m.scope_type,
            m.scope_id,
            m.content,
            m.importance,
            m.tags,
            COALESCE(m.created_by, 'user') AS created_by,
            COALESCE(m.origin_kind, 'user_asserted') AS origin_kind,
            m.source_conversation_id,
            m.source_message_id,
            m.created_at,
            m.updated_at,
            (
                SELECT GROUP_CONCAT(mp.project_id)
                FROM memory_projects mp
                WHERE mp.memory_id = m.id
            ) AS project_ids_csv,
            (
                SELECT GROUP_CONCAT(mc.conversation_id)
                FROM memory_conversations mc
                WHERE mc.memory_id = m.id
            ) AS conversation_ids_csv
        FROM memories m
        WHERE m.id = ?
          AND COALESCE(m.is_deleted, 0) = 0
        LIMIT 1
    """, (memory_id,)).fetchone()

    if not row:
        raise ValueError(f"Memory not found: {memory_id}")

    return _memory_row_to_dict(row)

def create_memory(
    content: str,
    importance: int = 0,
    tags: Any = None,
    created_by: str = "user",
    origin_kind: str = "user_asserted",
    source_conversation_id: str | None = None,
    source_message_id: str | None = None,
    scope_type: str = "global",
    scope_id: int | None = None,
) -> dict:
    content = (content or "").strip()
    if not content:
        raise ValueError("Memory content cannot be empty.")

    mem_id = new_uuid()
    now = _utc_now_iso()
    tags_text = _normalize_tags(tags)
    created_by = (created_by or "user").strip() or "user"
    origin_kind = (origin_kind or "user_asserted").strip() or "user_asserted"
    source_conversation_id = (source_conversation_id or "").strip() or None
    source_message_id = (source_message_id or "").strip() or None

    scope_type = (scope_type or "global").strip().lower()
    if scope_type not in ("global", "project"):
        scope_type = "global"
    if scope_type == "global":
        scope_id = None
    elif scope_id is None:
        raise ValueError("project-scoped memories require scope_id")

    with db_session() as conn:
        conn.execute("""
            INSERT INTO memories (
                id,
                content,
                importance,
                tags,
                scope_type,
                scope_id,
                created_by,
                origin_kind,
                source_conversation_id,
                source_message_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mem_id,
            content,
            int(importance or 0),
            tags_text,
            scope_type,
            scope_id,
            created_by,
            origin_kind,
            source_conversation_id,
            source_message_id,
            now,
            now,
        ))

        mem = _fetch_memory_row(conn, mem_id)
        artifact_id = _upsert_memory_artifact_for_row(conn, mem)

    try:
        reindex_info = reindex_artifact_by_id(artifact_id)
    except Exception as exc:
        reindex_info = {"ok": False, "artifact_id": artifact_id, "error": repr(exc)}

    mem["artifact_id"] = artifact_id
    mem["artifact_reindex"] = reindex_info
    return mem

def list_memories(limit: int = 200) -> list[dict]:
    """
    Query memories in order by highest importance first.
    Those with zero importance are effectively ignored,
    though they are retained for special use cases.
    """
    with db_session() as conn:
        rows = conn.execute("""
            SELECT
                m.id,
                m.scope_type,
                m.scope_id,
                m.content,
                m.importance,
                m.tags,
                COALESCE(m.created_by, 'user') AS created_by,
                COALESCE(m.origin_kind, 'user_asserted') AS origin_kind,
                m.source_conversation_id,
                m.source_message_id,
                m.created_at,
                m.updated_at,
                (
                    SELECT GROUP_CONCAT(mp.project_id)
                    FROM memory_projects mp
                    WHERE mp.memory_id = m.id
                ) AS project_ids_csv,
                (
                    SELECT GROUP_CONCAT(mc.conversation_id)
                    FROM memory_conversations mc
                    WHERE mc.memory_id = m.id
                ) AS conversation_ids_csv
            FROM memories m
            WHERE COALESCE(m.is_deleted, 0) = 0
              AND COALESCE(m.importance, 0) > 0
            ORDER BY
              COALESCE(m.importance, 0) DESC,
              COALESCE(m.updated_at, m.created_at) DESC,
              m.id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [_memory_row_to_dict(r) for r in rows]
    
if (False):
    def list_memories(limit: int = 200) -> list[dict]:
        with db_session() as conn:
            rows = conn.execute("""
                SELECT
                    m.id,
                    m.scope_type,
                    m.scope_id,
                    m.content,
                    m.importance,
                    m.tags,
                    COALESCE(m.created_by, 'user') AS created_by,
                    COALESCE(m.origin_kind, 'user_asserted') AS origin_kind,
                    m.source_conversation_id,
                    m.source_message_id,
                    m.created_at,
                    m.updated_at,
                    (
                        SELECT GROUP_CONCAT(mp.project_id)
                        FROM memory_projects mp
                        WHERE mp.memory_id = m.id
                    ) AS project_ids_csv,
                    (
                        SELECT GROUP_CONCAT(mc.conversation_id)
                        FROM memory_conversations mc
                        WHERE mc.memory_id = m.id
                    ) AS conversation_ids_csv
                FROM memories m
                WHERE COALESCE(m.is_deleted, 0) = 0
                ORDER BY COALESCE(m.updated_at, m.created_at) DESC, m.id DESC
                LIMIT ?
            """, (limit,)).fetchall()

            return [_memory_row_to_dict(r) for r in rows]

def update_memory(
    memory_id: str,
    content: str,
    importance: int = 0,
    tags: Any = None,
    created_by: str = "user",
    origin_kind: str = "user_asserted",
    scope_type: str | None = None,
    scope_id: int | None = None,
) -> dict:
    memory_id = (memory_id or "").strip()
    if not memory_id:
        raise ValueError("memory_id is required.")

    content = (content or "").strip()
    if not content:
        raise ValueError("Memory content cannot be empty.")

    tags_text = _normalize_tags(tags)
    created_by = (created_by or "user").strip() or "user"
    origin_kind = (origin_kind or "user_asserted").strip() or "user_asserted"
    now = _utc_now_iso()

    with db_session() as conn:
        existing = _fetch_memory_row(conn, memory_id)

        final_scope_type = (scope_type if scope_type is not None else existing.get("scope_type") or "global").strip().lower()
        if final_scope_type not in ("global", "project"):
            final_scope_type = "global"

        if final_scope_type == "global":
            final_scope_id = None
        else:
            final_scope_id = scope_id if scope_id is not None else existing.get("scope_id")
            if final_scope_id is None:
                raise ValueError("project-scoped memories require scope_id")

        conn.execute("""
            UPDATE memories
            SET
                content = ?,
                importance = ?,
                tags = ?,
                scope_type = ?,
                scope_id = ?,
                created_by = ?,
                origin_kind = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            content,
            int(importance or 0),
            tags_text,
            final_scope_type,
            final_scope_id,
            created_by,
            origin_kind,
            now,
            memory_id,
        ))

        mem = _fetch_memory_row(conn, memory_id)
        artifact_id = _upsert_memory_artifact_for_row(conn, mem)

    try:
        reindex_info = reindex_artifact_by_id(artifact_id)
    except Exception as exc:
        reindex_info = {"ok": False, "artifact_id": artifact_id, "error": repr(exc)}

    mem["artifact_id"] = artifact_id
    mem["artifact_reindex"] = reindex_info
    return mem

def delete_memory(memory_id: str) -> None:
    memory_id = (memory_id or "").strip()
    if not memory_id:
        raise ValueError("memory_id is required.")

    with db_session() as conn:
        _ensure_memory_exists(conn, memory_id)

        _soft_delete_memory_artifact_by_id(conn, memory_id)

        conn.execute("DELETE FROM memory_projects WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memory_conversations WHERE memory_id = ?", (memory_id,))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

def memory_link_project(memory_id: str, project_id: int) -> None:
    if not memory_id or not str(memory_id).strip():
        raise ValueError("memory_id is required.")
    if project_id is None:
        raise ValueError("project_id is required.")

    with db_session() as conn:
        _ensure_memory_exists(conn, memory_id)
        _ensure_project_exists(conn, int(project_id))

        conn.execute("""
            INSERT OR IGNORE INTO memory_projects (memory_id, project_id)
            VALUES (?, ?)
        """, (memory_id, int(project_id)))

def memory_link_conversation(memory_id: str, conversation_id: str) -> None:
    if not memory_id or not str(memory_id).strip():
        raise ValueError("memory_id is required.")
    conversation_id = (conversation_id or "").strip()
    if not conversation_id:
        raise ValueError("conversation_id is required.")

    with db_session() as conn:
        _ensure_memory_exists(conn, memory_id)
        _ensure_conversation_exists(conn, conversation_id)

        conn.execute("""
            INSERT OR IGNORE INTO memory_conversations (memory_id, conversation_id)
            VALUES (?, ?)
        """, (memory_id, conversation_id))

def memory_artifact_id(memory_id: str) -> str:
    memory_id = (memory_id or "").strip()
    if not memory_id:
        raise ValueError("memory_id is required.")
    return _deterministic_artifact_id(source_kind="memory", source_id=memory_id)

def _memory_artifact_title(mem: dict) -> str:
    raw = (mem.get("content") or "").strip()
    if not raw:
        return "Memory"
    first = raw.splitlines()[0].strip()
    first = re.sub(r"\s+", " ", first)
    if len(first) > 80:
        first = first[:77].rstrip() + "..."
    return f"Memory: {first}"

def _memory_artifact_text(mem: dict) -> str:
    scope_type = (mem.get("scope_type") or "global").strip().lower()
    scope_id = mem.get("scope_id")
    scope_label = "global" if scope_type == "global" or scope_id is None else f"project:{scope_id}"

    lines: list[str] = [
        "MEMORY RECORD",
        f"Scope: {scope_label}",
        f"Importance: {int(mem.get('importance') or 0)}",
    ]

    tags = (mem.get("tags") or "").strip()
    if tags:
        lines.append(f"Tags: {tags}")

    created_by = (mem.get("created_by") or "").strip()
    if created_by:
        lines.append(f"Created by: {created_by}")

    origin_kind = (mem.get("origin_kind") or "").strip()
    if origin_kind:
        lines.append(f"Origin: {origin_kind}")

    src_conv = (mem.get("source_conversation_id") or "").strip()
    if src_conv:
        lines.append(f"Source conversation: {src_conv}")

    src_msg = (mem.get("source_message_id") or "").strip()
    if src_msg:
        lines.append(f"Source message: {src_msg}")

    lines.append("")
    lines.append((mem.get("content") or "").rstrip())

    return "\n".join(lines).strip() + "\n"

def _memory_artifact_meta(mem: dict) -> dict:
    return {
        "memory_id": mem.get("id"),
        "scope_type": mem.get("scope_type") or "global",
        "scope_id": mem.get("scope_id"),
        "importance": int(mem.get("importance") or 0),
        "tags": mem.get("tags"),
        "created_by": mem.get("created_by") or "user",
        "origin_kind": mem.get("origin_kind") or "user_asserted",
        "source_conversation_id": mem.get("source_conversation_id"),
        "source_message_id": mem.get("source_message_id"),
        "project_ids": mem.get("project_ids") or [],
        "conversation_ids": mem.get("conversation_ids") or [],
    }

def _upsert_memory_artifact_for_row(conn: sqlite3.Connection, mem: dict) -> str:
    artifact_id = upsert_artifact_text(
        conn=conn,
        source_kind="memory",
        source_id=str(mem["id"]),
        title=_memory_artifact_title(mem),
        scope_type=(mem.get("scope_type") or "global"),
        scope_id=mem.get("scope_id"),
        text=_memory_artifact_text(mem),
    )

    project_id = None
    if (mem.get("scope_type") or "global") == "project" and mem.get("scope_id") is not None:
        try:
            project_id = int(mem["scope_id"])
        except Exception:
            project_id = None

    conn.execute(
        """
        UPDATE artifacts
        SET
            project_id = ?,
            meta_json = ?,
            is_deleted = 0,
            deleted_at = NULL,
            deleted_by_user_id = NULL,
            updated_at = ?
        WHERE id = ?
        """,
        (
            project_id,
            json.dumps(_memory_artifact_meta(mem), ensure_ascii=False),
            _utc_now_iso(),
            artifact_id,
        ),
    )

    return artifact_id

def upsert_memory_artifact(memory_id: str, *, reindex: bool = True) -> dict:
    memory_id = (memory_id or "").strip()
    if not memory_id:
        raise ValueError("memory_id is required.")

    with db_session() as conn:
        mem = _fetch_memory_row(conn, memory_id)
        artifact_id = _upsert_memory_artifact_for_row(conn, mem)

    reindex_info = None
    if reindex:
        try:
            reindex_info = reindex_artifact_by_id(artifact_id)
        except Exception as exc:
            reindex_info = {
                "ok": False,
                "artifact_id": artifact_id,
                "error": repr(exc),
            }

    return {
        "ok": True,
        "memory_id": memory_id,
        "artifact_id": artifact_id,
        "reindex": reindex_info,
    }

def _soft_delete_memory_artifact_by_id(
    conn: sqlite3.Connection,
    memory_id: str,
    *,
    deleted_by_user_id: str | None = None,
) -> int:
    artifact_id = memory_artifact_id(memory_id)
    now = _utc_now_iso()
    deleted_by_user_id = (deleted_by_user_id or "").strip() or None

    conn.execute("DELETE FROM conversation_artifacts WHERE artifact_id = ?", (artifact_id,))
    delete_corpus_chunks_for_artifact(conn, artifact_id)

    cur = conn.execute(
        """
        UPDATE artifacts
        SET
            is_deleted = 1,
            deleted_at = ?,
            deleted_by_user_id = ?,
            updated_at = ?
        WHERE id = ?
          AND (is_deleted IS NULL OR is_deleted = 0)
        """,
        (now, deleted_by_user_id, now, artifact_id),
    )
    return cur.rowcount

def rebuild_memory_artifacts(
    *,
    only_missing: bool = False,
    limit: int | None = None,
    reindex: bool = True,
) -> dict:
    sql = """
        SELECT m.id
        FROM memories m
        LEFT JOIN artifacts a
          ON a.source_kind = 'memory'
         AND a.source_id = m.id
         AND (a.is_deleted IS NULL OR a.is_deleted = 0)
        WHERE COALESCE(m.is_deleted, 0) = 0
    """
    params: list[object] = []

    if only_missing:
        sql += " AND a.id IS NULL"

    sql += " ORDER BY COALESCE(m.updated_at, m.created_at) DESC, m.id DESC"

    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))

    with db_session() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
        memory_ids = [str(r["id"]) for r in rows]

    ok = 0
    fail = 0
    chunks_total = 0
    failures: list[dict] = []

    for memory_id in memory_ids:
        try:
            result = upsert_memory_artifact(memory_id, reindex=reindex)
            ok += 1
            reindex_info = result.get("reindex") or {}
            chunks_total += int(reindex_info.get("chunks_written") or 0)
        except Exception as exc:
            fail += 1
            failures.append({
                "memory_id": memory_id,
                "error": repr(exc),
            })

    return {
        "ok": fail == 0,
        "memories_seen": len(memory_ids),
        "memories_ok": ok,
        "memories_failed": fail,
        "chunks_written_total": chunks_total,
        "failures": failures,
    }

# endregion

# ----------------------------
# Pinned Context
# ----------------------------

# region Pinned Instructions

def _pin_row_to_dict(row: sqlite3.Row) -> dict:
    value_json = row["value_json"]
    parsed_value = None
    if value_json:
        try:
            parsed_value = json.loads(value_json)
        except Exception:
            parsed_value = None

    return {
        "id": int(row["id"]),
        "text": row["text"],
        "pin_kind": row["pin_kind"] or "instruction",
        "title": row["title"],
        "value_json": parsed_value,
        "sort_order": int(row["sort_order"] or 0),
        "is_enabled": bool(row["is_enabled"]),
        "scope_type": row["scope_type"] or "global",
        "scope_id": row["scope_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

def _ensure_memory_pin_exists(conn: sqlite3.Connection, pin_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM memory_pins WHERE id = ?", (int(pin_id),)).fetchone()
    if not row:
        raise ValueError(f"Pin not found: {pin_id}")
    return row

def update_memory_pin(
    pin_id: int,
    text: str,
    *,
    pin_kind: str | None = None,
    title: str | None = None,
    value_json: dict | None = None,
    sort_order: int | None = None,
    is_enabled: bool | None = None,
    scope_type: str | None = None,
    scope_id: int | None = None,
) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Pin text cannot be empty.")

    now = _utc_now_iso()

    with db_session() as conn:
        existing = _ensure_memory_pin_exists(conn, pin_id)

        final_pin_kind = (pin_kind if pin_kind is not None else existing["pin_kind"]) or "instruction"
        final_title = title if title is not None else existing["title"]
        final_sort_order = int(sort_order if sort_order is not None else (existing["sort_order"] or 0))
        final_is_enabled = 1 if (is_enabled if is_enabled is not None else bool(existing["is_enabled"])) else 0
        final_scope_type = (scope_type if scope_type is not None else existing["scope_type"]) or "global"
        final_scope_id = scope_id if scope_id is not None else existing["scope_id"]

        if value_json is None:
            final_value_json_text = existing["value_json"]
        else:
            final_value_json_text = json.dumps(value_json, ensure_ascii=False)

        conn.execute("""
            UPDATE memory_pins
            SET
                text = ?,
                pin_kind = ?,
                title = ?,
                value_json = ?,
                sort_order = ?,
                is_enabled = ?,
                scope_type = ?,
                scope_id = ?,
                updated_at = ?
            WHERE id = ?
        """, (
            text,
            final_pin_kind,
            (final_title or "").strip() or None,
            final_value_json_text,
            final_sort_order,
            final_is_enabled,
            final_scope_type,
            final_scope_id,
            now,
            int(pin_id),
        ))

        row = conn.execute("SELECT * FROM memory_pins WHERE id = ?", (int(pin_id),)).fetchone()
        return _pin_row_to_dict(row)

def add_memory_pin(
    text: str,
    *,
    pin_kind: str = "instruction",
    title: str | None = None,
    value_json: dict | None = None,
    sort_order: int = 0,
    is_enabled: bool = True,
    scope_type: str = "global",
    scope_id: int | None = None,
) -> int:
    text = (text or "").strip()
    if not text:
        raise ValueError("Pin text cannot be empty.")

    now = _utc_now_iso()
    value_json_text = json.dumps(value_json, ensure_ascii=False) if value_json is not None else None

    with db_session() as conn:
        cur = conn.execute("""
            INSERT INTO memory_pins (
                text, pin_kind, title, value_json, sort_order, is_enabled,
                scope_type, scope_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            text,
            (pin_kind or "instruction").strip() or "instruction",
            (title or "").strip() or None,
            value_json_text,
            int(sort_order or 0),
            1 if is_enabled else 0,
            (scope_type or "global").strip() or "global",
            scope_id,
            now,
            now,
        ))
        if cur.lastrowid is None:
            raise RuntimeError("failed to retrieve last insert id")
        last_id = int(cur.lastrowid)
        row = conn.execute("SELECT * FROM memory_pins WHERE id = ?", (last_id,)).fetchone()
        return last_id

def upsert_about_you_pin(
    *,
    nickname: str = "",
    age: str = "",
    occupation: str = "",
    more_about_you: str = "",
) -> dict:
    nickname = (nickname or "").strip()
    age = (age or "").strip()
    occupation = (occupation or "").strip()
    more_about_you = (more_about_you or "").strip()

    lines: list[str] = []
    if nickname:
        lines.append(f"Nickname: {nickname}")
    if age:
        lines.append(f"Age: {age}")
    if occupation:
        lines.append(f"Occupation: {occupation}")
    if more_about_you:
        lines.append("More About You:")
        lines.append(more_about_you)

    text = "\n".join(lines).strip()
    value = {
        "nickname": nickname,
        "age": age,
        "occupation": occupation,
        "more_about_you": more_about_you,
    }

    now = _utc_now_iso()

    with db_session() as conn:
        existing = conn.execute("""
            SELECT *
            FROM memory_pins
            WHERE pin_kind = 'profile'
              AND title = 'about_you'
              AND COALESCE(scope_type, 'global') = 'global'
              AND scope_id IS NULL
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        if existing:
            conn.execute("""
                UPDATE memory_pins
                SET
                    text = ?,
                    value_json = ?,
                    is_enabled = 1,
                    updated_at = ?
                WHERE id = ?
            """, (
                text,
                json.dumps(value, ensure_ascii=False),
                now,
                int(existing["id"]),
            ))
            row = conn.execute("SELECT * FROM memory_pins WHERE id = ?", (int(existing["id"]),)).fetchone()
            return _pin_row_to_dict(row)

        cur = conn.execute("""
            INSERT INTO memory_pins (
                text, pin_kind, title, value_json, sort_order, is_enabled,
                scope_type, scope_id, created_at, updated_at
            )
            VALUES (?, 'profile', 'about_you', ?, 0, 1, 'global', NULL, ?, ?)
        """, (
            text,
            json.dumps(value, ensure_ascii=False),
            now,
            now,
        ))
        if cur.lastrowid is None:
            raise RuntimeError("failed to retrieve last insert id")
        row = conn.execute("SELECT * FROM memory_pins WHERE id = ?", (int(cur.lastrowid),)).fetchone()
        return _pin_row_to_dict(row)

def get_about_you_pin() -> dict | None:
    with db_session() as conn:
        row = conn.execute("""
            SELECT *
            FROM memory_pins
            WHERE pin_kind = 'profile'
              AND title = 'about_you'
              AND COALESCE(scope_type, 'global') = 'global'
              AND scope_id IS NULL
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()
        return _pin_row_to_dict(row) if row else None

def list_memory_pins(limit: int = 200) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute("""
            SELECT
                id, text, pin_kind, title, value_json, sort_order, is_enabled,
                scope_type, scope_id, created_at, updated_at
            FROM memory_pins
            WHERE COALESCE(is_enabled, 1) = 1
            ORDER BY sort_order ASC, id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [_pin_row_to_dict(r) for r in rows]

def delete_memory_pin(pin_id: int) -> None:
    with db_session() as conn:
        # TODO shouldn't we quit and warn if it doesn't?
        _ensure_memory_pin_exists(conn, pin_id)
        conn.execute("DELETE FROM memory_pins WHERE id = ?", (pin_id,))

# endregion

# ----------------------------
# Corpus / Indexing / Search
# ----------------------------

# region Corpus / Indexing

# region Corpus Indexing/Chunking

def delete_corpus_chunks_for_artifact(conn, artifact_id: str) -> None:
    conn.execute("DELETE FROM corpus_chunks WHERE artifact_id = ?", (artifact_id,))

def upsert_corpus_chunks_for_artifact_row(conn, artifact_row: dict, *, chunks: list[str]) -> int:
    """
    Writes chunks for this artifact. Assumes you already deleted previous chunks if reindexing.
    """
    artifact_id = artifact_row["id"]
    artifact_hash = artifact_row.get("content_hash") or artifact_row.get("artifact_content_hash")
    source_kind = artifact_row.get("source_kind")
    source_id = artifact_row.get("source_id")
    file_id = artifact_row.get("file_id")
    filename = artifact_row.get("filename")
    mime_type = artifact_row.get("file_mime_type") or artifact_row.get("mime_type")
    scope_key = _artifact_scope_key_for_row(conn, artifact_row)

    n = 0
    for i, text in enumerate(chunks):
        if not text or not text.strip():
            continue
        conn.execute(
            """
            INSERT INTO corpus_chunks(
              artifact_id, artifact_content_hash, source_kind, source_id,
              file_id, filename, mime_type, scope_key,
              chunk_index, start_char, end_char, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
            """,
            (
                artifact_id, artifact_hash, source_kind, source_id,
                file_id, filename, mime_type, scope_key,
                int(i), text,
            ),
        )
        n += 1
    return n

def reindex_corpus_for_conversation(
    *,
    conversation_id: str,
    force: bool = False,
    include_global: bool = False,
    limit_artifacts: int | None = None,
) -> dict:
    """
    Builds/refreshes corpus_chunks for artifacts visible to this conversation (conversation + project [+global]).
    Uses artifact content_hash to skip unchanged artifacts unless force=True.
    """
    cid = (conversation_id or "").strip()
    if not cid:
        return {"ok": False, "error": "missing conversation_id"}

    with db_session() as conn:
        # It is better not to do this stuff here rn
        # Make sure schema exists before we touch corpus_chunks/corpus_fts
        """
        _migrate_schema_v9(conn)
        conn.commit()  # sqlite + DDL: be explicit
        """
        # do self-heal / queries / chunk writes
        ensure_files_artifacted_for_conversation(
            conversation_id=cid,
            limit_per_scope=10,
            include_global=include_global,
        )

        # Ensure missing file artifacts are created (cheap now that it’s capped)
        ensure_files_artifacted_for_conversation(conversation_id=cid, limit_per_scope=10, include_global=include_global)

        #migrate_schema_v9(conn)  # safe to call repeatedly

        scope_keys = _scope_keys_for_conversation(conn, cid, include_global=include_global)
        artifact_rows = iter_artifacts_with_file_hints_for_scope_keys(conn, scope_keys)

        if limit_artifacts is not None:
            artifact_rows = artifact_rows[: int(limit_artifacts)]

        indexed = 0
        skipped = 0
        total_chunks = 0

        for a in artifact_rows:
            artifact_id = a["id"]
            a_hash = a.get("content_hash") or ""

            if not force and a_hash:
                row = conn.execute(
                    "SELECT artifact_content_hash FROM corpus_chunks WHERE artifact_id = ? LIMIT 1",
                    (artifact_id,),
                ).fetchone()
                if row and row["artifact_content_hash"] == a_hash:
                    skipped += 1
                    continue

            # Hydrate artifact text (sidecar-aware) if you have that helper
            try:
                text = hydrate_artifact_content_text(conn, artifact_id)  # type: ignore
            except Exception:
                # fallback if your artifacts table has a text field
                text = a.get("text") or a.get("content_text") or ""

            # When text comes up dry (like in image files or conversation summaries) try the summary instead
            if not text.strip():
                row = conn.execute("SELECT summary_text FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
                if row and row["summary_text"]:
                    text = row["summary_text"]

            if not text or not text.strip():
                skipped += 1
                continue

            # Chunk with hints
            chunks = chunk_text_with_hints(
                text,
                source_kind=a.get("source_kind"),
                filename=a.get("filename") or a.get("file_path"),
                mime_type=a.get("file_mime_type"),
            )

            # Rebuild chunks for this artifact
            delete_corpus_chunks_for_artifact(conn, artifact_id)
            n_chunks = upsert_corpus_chunks_for_artifact_row(conn, a, chunks=chunks)
            total_chunks += n_chunks
            indexed += 1

        return {
            "ok": True,
            "conversation_id": cid,
            "scope_keys": scope_keys,
            "indexed_artifacts": indexed,
            "skipped_artifacts": skipped,
            "total_chunks_written": total_chunks,
        }

def reindex_artifact_by_id(artifact_id: str) -> dict:
    artifact_id = (artifact_id or "").strip()
    if not artifact_id:
        return {"ok": False, "error": "missing artifact_id"}

    with db_session() as conn:
        art = _load_artifact_with_file_hints(conn, artifact_id)
        if not art:
            return {"ok": False, "error": "artifact not found"}

        try:
            text = hydrate_artifact_content_text(conn, artifact_id)
        except Exception:
            text = art.get("content_text") or ""

        if not text.strip():
            row = conn.execute("SELECT summary_text FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
            if row and row["summary_text"]:
                text = row["summary_text"]

        if not text.strip():
            delete_corpus_chunks_for_artifact(conn, artifact_id)
            return {"ok": True, "artifact_id": artifact_id, "chunks_written": 0}

        chunks = chunk_text_with_hints(
            text,
            source_kind=art.get("source_kind"),
            filename=art.get("filename") or art.get("file_path"),
            mime_type=art.get("file_mime_type"),
        )

        delete_corpus_chunks_for_artifact(conn, artifact_id)
        n = upsert_corpus_chunks_for_artifact_row(conn, art, chunks=chunks)
        return {"ok": True, "artifact_id": artifact_id, "chunks_written": n}

# endregion
# region Corpus FTS Query

def _visible_transcript_conversation_ids_for_conversation(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    cfg: QueryConfig,
) -> list[str]:
    cid = (conversation_id or "").strip()
    ids: list[str] = []
    seen: set[str] = set()

    def _add(x: str | None) -> None:
        x = (x or "").strip()
        if not x or x in seen:
            return
        seen.add(x)
        ids.append(x)

    _add(cid)

    row = conn.execute(
        "SELECT project_id FROM conversations WHERE id = ?",
        (cid,),
    ).fetchone()
    project_id = int(row["project_id"]) if row and row["project_id"] is not None else None

    # The current project's conversations
    if cfg.query_include_project_conversation_transcripts and project_id is not None:
        rows = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE project_id = ?
            ORDER BY updated_at DESC
            """,
            (project_id,),
        ).fetchall()
        for r in rows:
            _add(r["id"])

    # Conversations without a project (global chats)
    if cfg.query_include_global_conversation_transcripts:
        rows = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE project_id IS NULL
            ORDER BY updated_at DESC
            """
        ).fetchall()
        for r in rows:
            _add(r["id"])

    global_proj_rows = conn.execute(
        """
        SELECT c.id
        FROM conversations c
        JOIN projects p ON p.id = c.project_id
        WHERE p.visibility = 'global'
        AND (p.is_hidden IS NULL OR p.is_hidden = 0)
        AND (p.is_global IS NULL OR p.is_global = 0)
        ORDER BY c.updated_at DESC
        """
    ).fetchall()
    for r in global_proj_rows:
        _add(r["id"])

    # Any recently had conversations
    # TODO should we hide those in private projects
    if cfg.query_include_recent_conversation_transcripts:
        rows = conn.execute(
            """
            SELECT id
            FROM conversations
            WHERE id <> ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (cid, int(cfg.recent_conversation_transcript_limit)),
        ).fetchall()
        for r in rows:
            _add(r["id"])

    return ids

def search_corpus_for_conversation(
    *,
    conversation_id: str,
    query: str,
    limit: int = 10,
    cfg: QueryConfig | None = None,
) -> list[dict]:
    cid = (conversation_id or "").strip()
    q = (query or "").strip()
    if not cid or not q:
        return []

    cfg = cfg or load_query_config()
    app_cfg = load_app_config()

    with db_session() as conn:
        scope_keys = _scope_keys_for_conversation(conn, cid, include_global=cfg.query_global_artifacts)

        # transcript_cids = _visible_transcript_conversation_ids_for_conversation(conn, cid, cfg=cfg)
        transcript_cids: list[str] = []
        if app_cfg.search_chat_history:
            transcript_cids = _visible_transcript_conversation_ids_for_conversation(conn, cid, cfg=cfg)

        scope_placeholders = ",".join("?" * len(scope_keys)) if scope_keys else "NULL"
        transcript_placeholders = ",".join("?" * len(transcript_cids)) if transcript_cids else "NULL"

        params: list[Any] = [q]
        params.extend(scope_keys)
        params.append(TRANSCRIPT_SOURCE_KIND)
        params.extend(transcript_cids)
        params.append(int(limit))

        rows = conn.execute(
            f"""
            SELECT
              c.id AS chunk_id,
              c.scope_key,
              c.artifact_id,
              c.chunk_index,
              c.source_kind,
              c.source_id,
              c.file_id,
              c.filename,
              c.mime_type,
              c.text,

              a.title AS artifact_title,
              a.updated_at AS artifact_updated_at,

              f.created_at AS file_created_at,
              f.updated_at AS file_updated_at,

              conv.id AS conversation_id,
              conv.title AS conversation_title,
              substr(COALESCE(sumart.summary_text, ''), 1, 220) AS conversation_summary_excerpt,
              convspan.conversation_started_at AS conversation_started_at,
              convspan.conversation_ended_at AS conversation_ended_at,

              COALESCE(mem.importance, 0) AS memory_importance,
              bm25(corpus_fts) AS score
            FROM corpus_fts
            JOIN corpus_chunks c ON corpus_fts.rowid = c.id
            LEFT JOIN artifacts a ON a.id = c.artifact_id
            LEFT JOIN files f ON f.id = c.file_id
            LEFT JOIN memories mem
              ON c.source_kind = 'memory'
             AND c.source_id = mem.id
            LEFT JOIN conversations conv
              ON c.source_kind = '{TRANSCRIPT_SOURCE_KIND}'
             AND c.source_id = conv.id
            LEFT JOIN artifacts sumart
              ON sumart.source_kind = 'conversation:summary'
             AND sumart.source_id = conv.id
             AND (sumart.is_deleted IS NULL OR sumart.is_deleted = 0)
            LEFT JOIN (
                SELECT
                    conversation_id,
                    MIN(created_at) AS conversation_started_at,
                    MAX(created_at) AS conversation_ended_at
                FROM messages
                GROUP BY conversation_id
            ) convspan
            ON convspan.conversation_id = conv.id                        
            WHERE corpus_fts MATCH ?
              AND (
                    c.scope_key IN ({scope_placeholders})
                    OR (
                        c.source_kind = ?
                        AND c.source_id IN ({transcript_placeholders})
                    )
                  )
              AND (
                    c.source_kind <> 'memory'
                    OR COALESCE(mem.importance, 0) > 0
                  )
            ORDER BY
              CASE WHEN COALESCE(mem.importance, 0) >= 10 THEN 0 ELSE 1 END ASC,
              COALESCE(mem.importance, 0) DESC,
              score ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        if (False):
            rows = conn.execute(
                f"""
                SELECT
                c.id AS chunk_id,
                c.scope_key,
                c.artifact_id,
                c.chunk_index,
                c.source_kind,
                c.source_id,
                c.file_id,
                c.filename,
                c.mime_type,
                c.text,

                a.title AS artifact_title,
                a.updated_at AS artifact_updated_at,

                f.created_at AS file_created_at,
                f.updated_at AS file_updated_at,

                conv.id AS conversation_id,
                conv.title AS conversation_title,
                substr(COALESCE(sumart.summary_text, ''), 1, 220) AS conversation_summary_excerpt,

                bm25(corpus_fts) AS score
                FROM corpus_fts
                JOIN corpus_chunks c ON corpus_fts.rowid = c.id
                LEFT JOIN artifacts a ON a.id = c.artifact_id
                LEFT JOIN files f ON f.id = c.file_id
                LEFT JOIN conversations conv
                ON c.source_kind = '{TRANSCRIPT_SOURCE_KIND}'
                AND c.source_id = conv.id
                LEFT JOIN artifacts sumart
                ON sumart.source_kind = 'conversation:summary'
                AND sumart.source_id = conv.id
                AND (sumart.is_deleted IS NULL OR sumart.is_deleted = 0)
                WHERE corpus_fts MATCH ?
                AND (
                        c.scope_key IN ({scope_placeholders})
                        OR (
                            c.source_kind = ?
                            AND c.source_id IN ({transcript_placeholders})
                        )
                    )
                ORDER BY score ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        return [dict(r) for r in rows]

def search_corpus(*, scope_keys: list[str], query: str, limit: int = 10) -> list[dict]:
    q = (query or "").strip()
    if not q or not scope_keys:
        return []

    with db_session() as conn:
        placeholders = ",".join("?" * len(scope_keys))
        params = [q] + scope_keys + [int(limit)]

        rows = conn.execute(
            f"""
            SELECT
              c.id AS chunk_id,
              c.scope_key,
              c.artifact_id,
              c.chunk_index,
              c.source_kind,
              c.source_id,
              c.file_id,
              c.filename,
              c.mime_type,
              c.text,

              a.title AS artifact_title,
              a.updated_at AS artifact_updated_at,

              f.created_at AS file_created_at,
              f.updated_at AS file_updated_at,

              conv.id AS conversation_id,
              conv.title AS conversation_title,
              substr(COALESCE(sumart.summary_text, ''), 1, 220) AS conversation_summary_excerpt,
              convspan.conversation_started_at AS conversation_started_at,
              convspan.conversation_ended_at AS conversation_ended_at,

              COALESCE(mem.importance, 0) AS memory_importance,
              bm25(corpus_fts) AS score
            FROM corpus_fts
            JOIN corpus_chunks c ON corpus_fts.rowid = c.id
            LEFT JOIN artifacts a ON a.id = c.artifact_id
            LEFT JOIN files f ON f.id = c.file_id
            LEFT JOIN memories mem
              ON c.source_kind = 'memory'
             AND c.source_id = mem.id
            LEFT JOIN conversations conv
              ON c.source_kind = '{TRANSCRIPT_SOURCE_KIND}'
             AND c.source_id = conv.id
            LEFT JOIN artifacts sumart
              ON sumart.source_kind = 'conversation:summary'
             AND sumart.source_id = conv.id
             AND (sumart.is_deleted IS NULL OR sumart.is_deleted = 0)
            LEFT JOIN (
              SELECT
                conversation_id,
                MIN(created_at) AS conversation_started_at,
                MAX(created_at) AS conversation_ended_at
              FROM messages
              GROUP BY conversation_id
            ) convspan
            ON convspan.conversation_id = conv.id
            WHERE corpus_fts MATCH ?
              AND c.scope_key IN ({placeholders})
              AND (
                    c.source_kind <> 'memory'
                    OR COALESCE(mem.importance, 0) > 0
                  )
            ORDER BY
              CASE WHEN COALESCE(mem.importance, 0) >= 10 THEN 0 ELSE 1 END ASC,
              COALESCE(mem.importance, 0) DESC,
              score ASC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        if (False):
            rows = conn.execute(
                f"""
                SELECT
                c.id AS chunk_id,
                c.scope_key,
                c.artifact_id,
                c.chunk_index,
                c.source_kind,
                c.source_id,
                c.file_id,
                c.filename,
                c.mime_type,
                c.text,

                a.title AS artifact_title,
                a.updated_at AS artifact_updated_at,

                f.created_at AS file_created_at,
                f.updated_at AS file_updated_at,

                conv.id AS conversation_id,
                conv.title AS conversation_title,
                substr(COALESCE(sumart.summary_text, ''), 1, 220) AS conversation_summary_excerpt,

                bm25(corpus_fts) AS score
                FROM corpus_fts
                JOIN corpus_chunks c ON corpus_fts.rowid = c.id
                LEFT JOIN artifacts a ON a.id = c.artifact_id
                LEFT JOIN files f ON f.id = c.file_id

                LEFT JOIN conversations conv
                ON c.source_kind = '{TRANSCRIPT_SOURCE_KIND}'
                AND c.source_id = conv.id

                LEFT JOIN artifacts sumart
                ON sumart.source_kind = 'conversation:summary'
                AND sumart.source_id = conv.id
                AND (sumart.is_deleted IS NULL OR sumart.is_deleted = 0)

                WHERE corpus_fts MATCH ?
                AND c.scope_key IN ({placeholders})
                ORDER BY score ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        return [dict(r) for r in rows]

# endregion

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

def list_global_files(include_deleted: bool = False) -> list[dict]:
    """
    Returns all globally scoped files.
    A more robust version that is agnostic about what method was used to mark a file.
    Respects the global project id.
    Treats explicit scope_type='global' and legacy unscoped rows as global.
    """
    global_id: int = get_global_project_id()
    with db_session() as conn:
        sql = f"""
            SELECT *
            FROM files
            WHERE (
                project_id = {global_id}
                OR scope_type IS NULL
                OR scope_type = ''
                OR scope_type = 'global'
            )
        """
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        sql += " ORDER BY COALESCE(updated_at, created_at, '') DESC, name COLLATE NOCASE"

        rows = conn.execute(sql).fetchall()

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
    sha256: str | None = None,
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
    sha256 = (sha256 or "").strip() or None
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
                sha256,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                fid,
                name,
                path,
                mime_type,
                sha256,
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

def find_same_scope_same_name_file(
    *,
    name: str,
    scope_type: str | None,
    scope_id: int | None,
    scope_uuid: str | None,
    include_deleted: bool = False,
) -> dict | None:
    name = (name or "").strip()
    scope_type = (scope_type or "").strip() or None
    scope_uuid = (scope_uuid or "").strip() or None

    if not name:
        return None

    with db_session() as conn:
        sql = """
            SELECT *
            FROM files
            WHERE name = ?
              AND COALESCE(scope_type, '') = COALESCE(?, '')
              AND COALESCE(scope_id, -1) = COALESCE(?, -1)
              AND COALESCE(scope_uuid, '') = COALESCE(?, '')
        """
        params = [name, scope_type, scope_id, scope_uuid]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        sql += " LIMIT 1"

        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None

def replace_file_in_place(
    file_id: str,
    *,
    path: str,
    mime_type: str | None,
    sha256: str | None,
) -> dict:
    file_id = (file_id or "").strip()
    if not file_id:
        raise ValueError("file_id is required.")

    mime_type = (mime_type or "").strip() or None
    sha256 = (sha256 or "").strip() or None
    path = (path or "").strip()
    if not path:
        raise ValueError("path is required.")

    with db_session() as conn:
        _ensure_file_exists(conn, file_id)
        conn.execute(
            """
            UPDATE files
            SET path = ?,
                mime_type = ?,
                sha256 = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (path, mime_type, sha256, _utc_now_iso(), file_id),
        )

    return get_file_by_id(file_id)

def list_files_by_sha256(sha256: str, include_deleted: bool = False) -> list[dict]:
    sha256 = (sha256 or "").strip().lower()
    if not sha256:
        return []

    with db_session() as conn:
        sql = "SELECT * FROM files WHERE LOWER(COALESCE(sha256, '')) = ?"
        params = [sha256]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]

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
        # invalidates the summary of attached artifacts
        conn.execute(
            """
            UPDATE artifacts
            SET summary_input_hash = NULL,
                summary_updated_at = NULL
            WHERE is_deleted = 0
            AND source_id = ?
            AND source_kind LIKE 'file:%'
            """,
            (file_id,),
        )        

def move_file_scope(
    file_id: str,
    *,
    scope_type: str,
    scope_id: int | None = None,
    scope_uuid: str | None = None,
) -> dict:
    """
    Move a file between scopes.

    Current UI use-case:
      project -> global

    Supported targets:
      - global
      - project (requires scope_id)
      - conversation (requires scope_uuid)
    """
    file_id = (file_id or "").strip()
    target_scope_type = (scope_type or "").strip().lower()
    target_scope_uuid = (scope_uuid or "").strip() or None

    if not file_id:
        raise ValueError("file_id is required.")

    if target_scope_type not in ("global", "project", "conversation"):
        raise ValueError("scope_type must be 'global', 'project', or 'conversation'.")

    if target_scope_type == "project" and scope_id is None:
        raise ValueError("scope_id is required for project scope.")
    if target_scope_type == "conversation" and not target_scope_uuid:
        raise ValueError("scope_uuid is required for conversation scope.")

    with db_session() as conn:
        _ensure_file_exists(conn, file_id)

        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            raise ValueError(f"File not found: {file_id}")

        file_row = dict(row)
        old_scope_type = (file_row.get("scope_type") or "").strip().lower() or "global"
        old_scope_id = file_row.get("scope_id")
        old_scope_uuid = (file_row.get("scope_uuid") or "").strip() or None

        if target_scope_type == "project":
            if scope_id is None:
                raise ValueError("scope_id is required for project scope.")
            _ensure_project_exists(conn, int(scope_id))
        elif target_scope_type == "conversation":
            if target_scope_uuid is None:
                raise ValueError("scope_uuid is required for conversation scope.")
            _ensure_conversation_exists(conn, target_scope_uuid)

        # Remove old links no matter what.
        conn.execute("DELETE FROM project_files WHERE file_id = ?", (file_id,))
        conn.execute("DELETE FROM conversation_files WHERE file_id = ?", (file_id,))

        new_scope_id = int(scope_id) if target_scope_type == "project" and scope_id is not None else None
        new_scope_uuid = target_scope_uuid if target_scope_type == "conversation" else None

        conn.execute(
            """
            UPDATE files
            SET scope_type = ?, scope_id = ?, scope_uuid = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                target_scope_type,
                new_scope_id,
                new_scope_uuid,
                _utc_now_iso(),
                file_id,
            ),
        )

        if target_scope_type == "project":
            conn.execute(
                "INSERT OR IGNORE INTO project_files (project_id, file_id) VALUES (?, ?)",
                (new_scope_id, file_id),
            )
        elif target_scope_type == "conversation":
            conn.execute(
                "INSERT OR IGNORE INTO conversation_files (conversation_id, file_id) VALUES (?, ?)",
                (new_scope_uuid, file_id),
            )

        updated_row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()

    if updated_row is None:
        raise ValueError(f"File not found after move: {file_id}")

    updated_file = dict(updated_row)

    # Rebuild artifact scope to match the file's new scope.
    artifact_file(updated_file)

    # Scope changes can affect many contexts, especially when moving into global scope.
    invalidate_all_context_cache()

    return {
        "id": updated_file["id"],
        "name": updated_file.get("name"),
        "scope_type": updated_file.get("scope_type"),
        "scope_id": updated_file.get("scope_id"),
        "scope_uuid": updated_file.get("scope_uuid"),
        "old_scope_type": old_scope_type,
        "old_scope_id": old_scope_id,
        "old_scope_uuid": old_scope_uuid,
    }

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

class FileDeleteAction(Enum):
    NOTHING = 0
    MOVE = 1
    DELETE = 2

def delete_file_cascade(
    file_id: str,
    *,
    deleted_by_user_id: str | None = None,
    delete_disk_action: FileDeleteAction = FileDeleteAction.MOVE,
) -> dict:
    """
    Soft-delete a file and remove all derived/search assets tied to it.

    Effects:
      - soft-delete file row
      - soft-delete artifacts sourced from this file
      - delete corpus_chunks for those artifacts
      - unlink from conversation_files / project_files
      - optionally remove physical file from disk
      - invalidate relevant context caches
    """
    file_id = (file_id or "").strip()
    if not file_id:
        raise ValueError("file_id is required.")

    deleted_by_user_id = (deleted_by_user_id or "").strip() or None
    now = _utc_now_iso()

    with db_session() as conn:
        _ensure_file_exists(conn, file_id)

        file_row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if file_row is None:
            raise ValueError(f"File not found: {file_id}")
        file_row = dict(file_row)

        path = (file_row.get("path") or "").strip()
        scope_type = (file_row.get("scope_type") or "").strip() or None
        scope_id = file_row.get("scope_id")
        scope_uuid = (file_row.get("scope_uuid") or "").strip() or None

        # collect artifacts before soft-delete
        arts = conn.execute(
            """
            SELECT id
            FROM artifacts
            WHERE source_id = ?
              AND (is_deleted IS NULL OR is_deleted = 0)
            """,
            (file_id,),
        ).fetchall()
        artifact_ids = [r["id"] for r in arts]

        # remove chunk rows first
        for aid in artifact_ids:
            delete_corpus_chunks_for_artifact(conn, aid)

        # soft-delete artifacts
        conn.execute(
            """
            UPDATE artifacts
            SET is_deleted = 1,
                deleted_at = ?,
                deleted_by_user_id = ?
            WHERE source_id = ?
              AND (is_deleted IS NULL OR is_deleted = 0)
            """,
            (now, deleted_by_user_id, file_id),
        )

        # unlink file from conversation/project link tables
        if _table_exists(conn, "conversation_files"):
            conn.execute("DELETE FROM conversation_files WHERE file_id = ?", (file_id,))
        if _table_exists(conn, "project_files"):
            conn.execute("DELETE FROM project_files WHERE file_id = ?", (file_id,))

        # soft-delete the file row
        conn.execute(
            """
            UPDATE files
            SET is_deleted = 1,
                deleted_at = ?,
                deleted_by_user_id = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, deleted_by_user_id, now, file_id),
        )

    # invalidate caches outside the db_session for simplicity
    try:
        if scope_type == "conversation" and scope_uuid:
            invalidate_context_cache_for_conversation(scope_uuid)
        elif scope_type == "project" and scope_id is not None:
            invalidate_context_cache_for_project(int(scope_id))
    except Exception:
        pass

    disk_deleted = False
    disk_moved = False
    moved_to = None

    if delete_disk_action == FileDeleteAction.MOVE and path:
        try:
            p = Path(path)
            if p.exists() and p.is_file():
                backup_root = DATA_DIR / "deleted_files"
                backup_root.mkdir(parents=True, exist_ok=True)

                # TODO fix deprecated function call
                stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                target = backup_root / f"{stamp}__{file_id}__{p.name}"

                p.replace(target)
                disk_moved = True
                moved_to = str(target)
        except Exception:
            # leave it soft-deleted in DB even if filesystem move fails
            disk_moved = False
            moved_to = None            
    if delete_disk_action == FileDeleteAction.DELETE and path:
        try:
            p = Path(path)
            if p.exists() and p.is_file():
                p.unlink()
                disk_deleted = True
        except Exception:
            # leave it soft-deleted in DB even if filesystem cleanup fails
            disk_deleted = False

    return {
        "ok": True,
        "file_id": file_id,
        "artifact_count": len(artifact_ids),
        "disk_deleted": disk_deleted,
        "disk_moved": disk_moved,
        "moved_to": moved_to,
    }

def list_files_same_name_any_scope(name: str, include_deleted: bool = False) -> list[dict]:
    name = (name or "").strip()
    if not name:
        return []

    with db_session() as conn:
        sql = "SELECT * FROM files WHERE name = ?"
        params = [name]
        if not include_deleted:
            sql += " AND (is_deleted IS NULL OR is_deleted = 0)"
        rows = conn.execute(sql, params).fetchall()

    return [dict(r) for r in rows]

# endregion
# region Artifacts

def scope_rank(scope_type: str | None) -> int:
    st = (scope_type or "").strip().lower()
    if st == "global":
        return 3
    if st == "project":
        return 2
    if st in ("conversation", "chat"):
        return 1
    return 0

def _artifact_scope_key_for_row(conn, artifact_row: dict) -> str:
    st = (artifact_row.get("scope_type") or "").strip().lower()
    sid = artifact_row.get("scope_id")
    suid = (artifact_row.get("scope_uuid") or "").strip()

    if st in ("conversation", "chat"): # Legacy bad-stuff ("chat" scope) in early versions of data
        conv_id = suid or (str(sid).strip() if sid is not None else "")
        if conv_id:
            return f"conversation:{conv_id}" if st == "conversation" else f"chat:{conv_id}"

    if st == "project" and sid:
        return f"project:{sid}"

    return "global"

def load_artifact_row_for_context(conn, artifact_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM artifacts
        WHERE id = ?
          AND (is_deleted IS NULL OR is_deleted = 0)
        LIMIT 1
        """,
        ((artifact_id or "").strip(),),
    ).fetchone()
    if not row:
        return None

    art = dict(row)
    art["content_text"] = hydrate_artifact_content_text(conn, artifact_id)
    return art

# region File Artifact Summaries

def _compute_artifact_summary_input_hash(conn, art: dict) -> str:
    """
    Hash of all inputs that should affect the summary.
    For file artifacts, include files.description/name/mime_type.
    """
    source_kind = (art.get("source_kind") or "")
    source_id = (art.get("source_id") or "")
    title = (art.get("title") or "")
    content_hash = (art.get("content_hash") or "")

    base = f"{source_kind}|{source_id}|{title}|{content_hash}"

    if source_kind.startswith("file:") and source_id:
        f = conn.execute(
            "SELECT name, mime_type, description FROM files WHERE id = ?",
            (source_id,),
        ).fetchone()
        if f:
            base += f"|{f['name'] or ''}|{f['mime_type'] or ''}|{f['description'] or ''}"

    return _sha256_hex(base)


def get_artifact_summary(conn, artifact_id: str, *, include_stale: bool = False) -> dict | None:
    row = conn.execute(
        "SELECT * FROM artifacts WHERE id = ? AND is_deleted = 0",
        (artifact_id,),
    ).fetchone()
    if not row:
        return None

    art = dict(row)
    summary_text = (art.get("summary_text") or "").strip()
    if not summary_text:
        return None

    stored = (art.get("summary_input_hash") or "").strip()
    current = _compute_artifact_summary_input_hash(conn, art)

    is_stale = (not stored) or (stored != current)
    if is_stale and not include_stale:
        return None

    return {
        "artifact_id": artifact_id,
        "summary_text": summary_text,
        "summary_model": art.get("summary_model"),
        "summary_input_hash": stored,
        "summary_updated_at": art.get("summary_updated_at"),
        "is_stale": is_stale,
        "current_input_hash": current,
        "title": art.get("title"),
        "source_kind": art.get("source_kind"),
        "source_id": art.get("source_id"),
    }


def set_artifact_summary(conn, artifact_id: str, summary_text: str, model: str) -> None:
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not row:
        raise ValueError(f"artifact not found: {artifact_id}")

    art = dict(row)
    input_hash = _compute_artifact_summary_input_hash(conn, art)

    conn.execute(
        """
        UPDATE artifacts
        SET summary_text = ?,
            summary_model = ?,
            summary_input_hash = ?,
            summary_updated_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (summary_text, model, input_hash, _utc_now_iso(), _utc_now_iso(), artifact_id),
    )

# endregion

# region File-Artifact Hygeine

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

    # Heal problems caused by scope="chat"
    _heal("chat", "chat", None, cid)  # TODO remove after DB cleanup

    # Project-scoped files (if conversation is in a project)
    pid = get_conversation_project_id(conn, cid)
    if pid is not None:
        _heal("project", "project", pid, None)

    # Optional global
    if include_global:
        _heal("global", "global", None, None)

    return {"checked": checked_total, "created": created_total, "details": details}

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

def hydrate_artifact_content_text(conn, artifact_id: str) -> str:
    """
    Return the artifact's content_text, reading sidecar if necessary.
    """
    artifact_id = (artifact_id or "").strip()
    if not artifact_id:
        return ""

    row = conn.execute(
        "SELECT * FROM artifacts WHERE id = ? AND is_deleted = 0",
        (artifact_id,),
    ).fetchone()
    if not row:
        return ""

    art = dict(row)
    _hydrate_artifact_content_text(art)
    return (art.get("content_text") or "")

def get_scoped_artifact_debug(conversation_id: str, *, include_global: bool = False, preview_chars: int = 180) -> dict:
    with db_session() as conn:
        scope_keys = _scope_keys_for_conversation(conn, conversation_id, include_global=include_global)
        arts = iter_artifacts_with_file_hints_for_scope_keys(conn, scope_keys)

        counts = {
            r["artifact_id"]: r["n"]
            for r in conn.execute(
                "SELECT artifact_id, COUNT(*) AS n FROM corpus_chunks GROUP BY artifact_id"
            ).fetchall()
        }

        items = []
        by_scope = {}

        for a in arts:
            aid = a["id"]
            _hydrate_artifact_content_text(a)

            summary_preview = (a.get("summary_text") or "").strip()
            if summary_preview:
                summary_preview = summary_preview[:preview_chars]

            content_preview = (a.get("content_text") or "").strip()
            if content_preview:
                content_preview = content_preview[:preview_chars]

            item = {
                "artifact_id": aid,
                "scope_type": a.get("scope_type"),
                "scope_id": a.get("scope_id"),
                "scope_uuid": a.get("scope_uuid"),
                "scope_key": _artifact_scope_key_for_row(conn, a),
                "source_kind": a.get("source_kind"),
                "source_id": a.get("source_id"),
                "title": a.get("title"),
                "updated_at": a.get("updated_at"),
                "chunk_count": int(counts.get(aid, 0)),
                "summary_preview": summary_preview,
                "content_preview": content_preview,
                "file": {
                    "file_id": a.get("file_id"),
                    "filename": a.get("filename"),
                    "mime_type": a.get("file_mime_type"),
                    "description": None,
                },
            }

            if a.get("file_id"):
                f = conn.execute(
                    "SELECT description FROM files WHERE id = ?",
                    (a["file_id"],),
                ).fetchone()
                if f:
                    item["file"]["description"] = f["description"]

            by_scope.setdefault(item["scope_key"], {"artifact_count": 0, "chunk_count": 0})
            by_scope[item["scope_key"]]["artifact_count"] += 1
            by_scope[item["scope_key"]]["chunk_count"] += item["chunk_count"]

            items.append(item)

        return {
            "conversation_id": conversation_id,
            "scope_keys": scope_keys,
            "by_scope": by_scope,
            "artifacts": items,
        }

# endregion

# region File-Artifact Queries

def _load_artifact_with_file_hints(conn, artifact_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT
          a.*,
          f.id AS file_id,
          f.name AS filename,
          f.mime_type AS file_mime_type,
          f.path AS file_path
        FROM artifacts a
        LEFT JOIN files f
          ON a.source_kind LIKE 'file:%'
         AND a.source_id = f.id
         AND f.is_deleted = 0
        WHERE a.id = ?
          AND a.is_deleted = 0
        """,
        (artifact_id,),
    ).fetchone()
    return dict(row) if row else None

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

def iter_artifacts_with_file_hints_for_scope_keys(conn, scope_keys: list[str]) -> list[dict]:
    """
    Returns artifact rows in those scope_keys, with optional file hints
    when artifact source_kind is file:* and source_id matches files.id.
    """
    # Break scope_keys into scope_type/scope_id pairs for SQL
    convo_ids = [k.split(":", 1)[1] for k in scope_keys if k.startswith("conversation:")]
    proj_ids = [k.split(":", 1)[1] for k in scope_keys if k.startswith("project:")]
    include_global = any(k == "global" for k in scope_keys)

    clauses = []
    params: list = []

    if convo_ids:
        placeholders = ",".join("?" * len(convo_ids))
        # legacy bad stuff from early versions of the data (scope="chat")
        clauses.append(
            "("
            "a.scope_type IN ('conversation','chat') AND ("
            f"(a.scope_uuid IS NOT NULL AND a.scope_uuid IN ({placeholders})) "
            f"OR (a.scope_id IS NOT NULL AND CAST(a.scope_id AS TEXT) IN ({placeholders}))"
            ")"
            ")"
        )
        params.extend(convo_ids)
        params.extend(convo_ids)

    #if convo_ids:
    #    clauses.append("(a.scope_type = 'conversation' AND a.scope_id IN (" + ",".join("?" * len(convo_ids)) + "))")
    #    params.extend(convo_ids)

    if proj_ids:
        clauses.append("(a.scope_type = 'project' AND a.scope_id IN (" + ",".join("?" * len(proj_ids)) + "))")
        params.extend(proj_ids)

    if include_global:
        clauses.append("(a.scope_type = 'global' OR a.scope_type IS NULL)")

    if not clauses:
        return []

    where_scope = " OR ".join(clauses)

    rows = conn.execute(
        f"""
        SELECT
          a.*,
          f.id AS file_id,
          f.name AS filename,
          f.mime_type AS file_mime_type,
          f.path AS file_path
        FROM artifacts a
        LEFT JOIN files f
          ON a.source_kind LIKE 'file:%'
         AND a.source_id = f.id
         AND f.is_deleted = 0
        WHERE a.is_deleted = 0
          AND ({where_scope})
        ORDER BY a.updated_at DESC
        """,
        tuple(params),
    ).fetchall()

    return [dict(r) for r in rows]

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

# region Add/Upsert File-Artifact

def artifact_file(file_row) -> str:
    """
    Convenience wrapper around upsert_file_artifact for end-to-end artifacting of a single file.
    Uses the file row's real scope, not global defaults.
    """
    if not isinstance(file_row, dict):
        file_row = dict(file_row)

    scope_type = (file_row.get("scope_type") or "").strip() or "global"
    scope_id = None

    if scope_type == "project":
        sid = file_row.get("scope_id")
        scope_id = str(sid) if sid is not None else None
    elif scope_type == "conversation":
        scope_id = (file_row.get("scope_uuid") or "").strip() or None
    else:
        scope_type = "global"
        scope_id = None

    with db_session() as conn:
        aid = upsert_file_artifact(
            conn,
            file_row=file_row,
            scope_type=scope_type,
            scope_id=scope_id,
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

# endregion

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
                updated_at = ?,
                summary_text = NULL,
                summary_model = NULL,
                summary_input_hash = NULL,
                summary_updated_at = NULL
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
                updated_at = ?,
                summary_text = NULL,
                summary_model = NULL,
                summary_input_hash = NULL,
                summary_updated_at = NULL
            WHERE id = ?
            """,
            (norm, content_hash, content_bytes, _utc_now_iso(), artifact_id),
        )
        if old_sidecar_path:
            _delete_sidecar_if_exists(sidecar_path=old_sidecar_path)
    return artifact_id

# endregion