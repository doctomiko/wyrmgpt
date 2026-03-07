import sqlite3
from pathlib import Path

"""
from .db import (
    _table_exists,
    _add_column_if_missing,
    SCHEMA_VERSION, 
    DATA_DIR, 
    DB_PATH
)
"""

def _migrate_schema_legacy(conn: sqlite3.Connection) -> None:
        # Ensure all tables exist (idempotent)
    _apply_schema_v2(conn)
    # Bring older DBs up to compatibility without dropping data
    migrate_schema_v3(conn)
    migrate_schema_v4(conn)
    migrate_schema_v5(conn)
    migrate_schema_v6(conn)
    migrate_schema_v7(conn)

# region Legacy Migrations for older schemas

def _apply_schema_v2(conn: sqlite3.Connection) -> None:
    from .db import SCHEMA_VERSION

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
    from .db import _table_exists, _add_column_if_missing

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

def migrate_schema_v4(conn: sqlite3.Connection) -> None:
    from .db import _table_exists, _add_column_if_missing

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

def migrate_schema_v5(conn: sqlite3.Connection) -> None:
    """
    Non-destructive migration for artifact chunking.

    Adds:
      - chunk_index INTEGER on artifacts
    """
    from .db import _table_exists, _add_column_if_missing

    if _table_exists(conn, "artifacts"):
        _add_column_if_missing(conn, "artifacts", "chunk_index", "INTEGER")

def migrate_schema_v6(conn: sqlite3.Connection) -> None:
    """
    Make sure messages have created_at and author_meta columns.
    """
    from .db import _table_exists, _add_column_if_missing

    _add_column_if_missing(conn, "messages", "created_at", "TEXT")
    _add_column_if_missing(conn, "messages", "author_meta", "TEXT")

def migrate_schema_v7(conn: sqlite3.Connection) -> None:
    """
    Add is_global and is_hidden flags to projects.
    """
    from .db import _table_exists, _add_column_if_missing

    _add_column_if_missing(conn, "projects", "is_global", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "projects", "is_hidden", "INTEGER DEFAULT 0")

if (False): # phased out in favor shoot-all-your-problems-away
    def migrate_schema_v8_notimplemented(conn: sqlite3.Connection) -> None:
        """
        This migration makes changes to artifacts in support of future RAG implementation
        """
        _add_column_if_missing(conn, "artifacts", "content_text", "TEXT")
        _add_column_if_missing(conn, "artifacts", "sidecar_path", "TEXT")
        _add_column_if_missing(conn, "artifacts", "content_hash", "TEXT")
        _add_column_if_missing(conn, "artifacts", "content_bytes", "INTEGER")
        _add_column_if_missing(conn, "artifacts", "updated_at", "TEXT")
        conn.executescript(f"""
        CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_content_ins
        BEFORE INSERT ON artifacts
        FOR EACH ROW
        BEGIN
        SELECT
            CASE
            WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
            THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
            END;
        END;

        CREATE TRIGGER IF NOT EXISTS trg_artifacts_exclusive_content_upd
        BEFORE UPDATE OF content_text, sidecar_path ON artifacts
        FOR EACH ROW
        BEGIN
        SELECT
            CASE
            WHEN NEW.content_text IS NOT NULL AND NEW.sidecar_path IS NOT NULL
            THEN RAISE(ABORT, 'artifacts: content_text and sidecar_path are mutually exclusive')
            END;
        END;
                    
        CREATE VIEW IF NOT EXISTS v_artifacts AS
        SELECT
        a.*,
        CASE
            WHEN a.content_text IS NOT NULL THEN 'inline'
            WHEN a.sidecar_path IS NOT NULL THEN 'sidecar'
            ELSE 'empty'
        END AS storage_mode
        FROM artifacts a;

        CREATE INDEX IF NOT EXISTS idx_artifacts_content_hash ON artifacts(content_hash);
        CREATE INDEX IF NOT EXISTS idx_artifacts_updated_at ON artifacts(updated_at);
        """)
        if (False): # phased out in favor shoot-all-your-problems-away
            article_sidecar_threshold_bytes = 50 * 1024 * 1024 # cfg.article_sidecar_threshold_bytes
            stats = merge_legacy_article_chunks_to_single_pass(
                conn,
                data_dir="data",
                sidecar_threshold_bytes=article_sidecar_threshold_bytes,
            )
            print(f"Merged {stats['merged_count']} artifact groups, deleted {stats['deleted_rows']} rows.")

# endregion
