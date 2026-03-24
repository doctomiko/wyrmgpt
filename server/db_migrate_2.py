import sqlite3
from pathlib import Path
from typing import Iterable
from .db_helpers import (
    SCHEMA_VERSION,
    _add_column_if_missing, _table_exists,
    _utc_now_iso, db_session, new_uuid
)

# region Migrate v8 - Big Chunky SQL

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

# region Migrations 8 to 17

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

# region Migrations 18 to 22

def _migrate_schema_v18(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunk_embedding_state (
            chunk_id INTEGER PRIMARY KEY,
            text_hash TEXT NOT NULL,
            embedding_provider TEXT NOT NULL,
            embedding_model TEXT NOT NULL,
            vector_dim INTEGER,
            last_embedded_at TEXT,
            status TEXT NOT NULL DEFAULT 'ready',
            FOREIGN KEY (chunk_id) REFERENCES corpus_chunks(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunk_embedding_state_status ON chunk_embedding_state(status)"
    )

def _migrate_schema_v19(conn) -> None:
    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS import_identities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_source TEXT NOT NULL,          -- e.g. 'openai-export-zip'
        asset_type TEXT NOT NULL,             -- project | conversation | message | file | artifact
        local_id TEXT NOT NULL,               -- store everything as text, even int IDs
        import_id TEXT NOT NULL,              -- stable external ID
        imported_name TEXT,                   -- the name/title/path we saw in the source
        imported_parent_id TEXT,              -- optional: parent external ID
        raw_json TEXT,                        -- optional extra metadata blob
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(import_source, asset_type, import_id)
    );
    """)
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_import_identities_local
        ON import_identities(asset_type, local_id);
    """
    )

def _migrate_schema_v20(conn) -> None:
    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS web_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canonical_url TEXT NOT NULL,
        domain TEXT,
        project_id INTEGER,
        created_by TEXT NOT NULL DEFAULT 'user',   -- user | search | crawler
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(canonical_url),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_sources_project
        ON web_sources(project_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_sources_domain
        ON web_sources(domain);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS web_source_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id INTEGER NOT NULL,
        fetched_at TEXT NOT NULL,
        fetch_method TEXT NOT NULL DEFAULT 'python',   -- python | curl | wget | brave
        http_status INTEGER,
        final_url TEXT,
        content_type TEXT,
        etag TEXT,
        last_modified TEXT,
        headers_json TEXT,
        raw_html TEXT,
        raw_text TEXT,
        ttl_seconds INTEGER,
        expires_at TEXT,
        is_pinned INTEGER NOT NULL DEFAULT 0,
        refresh_requested INTEGER NOT NULL DEFAULT 0,
        error_text TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (source_id) REFERENCES web_sources(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_source_snapshots_source_fetched
        ON web_source_snapshots(source_id, fetched_at DESC);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_source_snapshots_expires
        ON web_source_snapshots(expires_at);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_source_snapshots_refresh_requested
        ON web_source_snapshots(refresh_requested);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_source_snapshots_pinned
        ON web_source_snapshots(is_pinned);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS web_searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        conversation_id TEXT,
        request_message_id INTEGER,
        provider TEXT NOT NULL,                  -- brave | google | local | etc
        query_text TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'auto',       -- auto | explicit | always
        result_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (request_message_id) REFERENCES messages(id) ON DELETE SET NULL
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_searches_project
        ON web_searches(project_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_searches_conversation
        ON web_searches(conversation_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_searches_request_message
        ON web_searches(request_message_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_searches_created
        ON web_searches(created_at);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS web_search_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        search_id INTEGER NOT NULL,
        rank INTEGER NOT NULL,
        title TEXT,
        url TEXT NOT NULL,
        canonical_url TEXT,
        domain TEXT,
        snippet TEXT,
        provider_result_id TEXT,
        source_id INTEGER,                       -- nullable until promoted/resolved
        selected_for_fetch INTEGER NOT NULL DEFAULT 0,
        fetched_snapshot_id INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (search_id) REFERENCES web_searches(id) ON DELETE CASCADE,
        FOREIGN KEY (source_id) REFERENCES web_sources(id) ON DELETE SET NULL,
        FOREIGN KEY (fetched_snapshot_id) REFERENCES web_source_snapshots(id) ON DELETE SET NULL,
        UNIQUE(search_id, rank)
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_search_results_search
        ON web_search_results(search_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_search_results_url
        ON web_search_results(url);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_search_results_canonical_url
        ON web_search_results(canonical_url);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_search_results_source
        ON web_search_results(source_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_web_search_results_snapshot
        ON web_search_results(fetched_snapshot_id);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS citations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        assistant_message_id INTEGER NOT NULL,
        corpus_chunk_id INTEGER,
        artifact_id TEXT,
        source_kind TEXT,
        source_id TEXT,
        retrieval_channel TEXT,                  -- fts | vector | web | manual
        retrieval_rank INTEGER,
        retrieval_score REAL,
        matched_text TEXT,
        highlight_start INTEGER,
        highlight_end INTEGER,
        created_at TEXT NOT NULL,
        FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE,
        FOREIGN KEY (corpus_chunk_id) REFERENCES corpus_chunks(id) ON DELETE SET NULL,
        FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE SET NULL
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_citations_message
        ON citations(assistant_message_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_citations_chunk
        ON citations(corpus_chunk_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_citations_artifact
        ON citations(artifact_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_citations_source
        ON citations(source_kind, source_id);
    """
    )

def _migrate_schema_v21(conn) -> None:
    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS conversation_retained_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,

        -- where/why this artifact entered the conversation working set
        origin_kind TEXT NOT NULL DEFAULT 'retrieval_expand',    -- user_url | retrieval_expand | manual_force | search_fetch | conversation_expand | file_attach
        retention_state TEXT NOT NULL DEFAULT 'active',          -- forced | active | latent | pinned | dropped
        carry_summary_text TEXT,                                 -- compact summary/note for future rounds
        last_inclusion_kind TEXT,                                -- whole | chunk | summary
        include_count INTEGER NOT NULL DEFAULT 0,

        -- message linkage for “when did this start / when was it last used?”
        first_message_id INTEGER,
        last_message_id INTEGER,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(conversation_id, artifact_id),

        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
        FOREIGN KEY (first_message_id) REFERENCES messages(id) ON DELETE SET NULL,
        FOREIGN KEY (last_message_id) REFERENCES messages(id) ON DELETE SET NULL
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_retained_artifacts_conversation
        ON conversation_retained_artifacts(conversation_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_retained_artifacts_artifact
        ON conversation_retained_artifacts(artifact_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_retained_artifacts_state
        ON conversation_retained_artifacts(retention_state);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_retained_artifacts_last_message
        ON conversation_retained_artifacts(last_message_id);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS conversation_artifact_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        message_id INTEGER,

        event_kind TEXT NOT NULL,                 -- retained | included | refreshed | decayed | pinned | dropped
        inclusion_kind TEXT,                      -- whole | chunk | summary
        retrieval_channel TEXT,                   -- fts | vector | web | manual | expansion
        note_text TEXT,
        meta_json TEXT,

        created_at TEXT NOT NULL,

        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_artifact_events_conversation
        ON conversation_artifact_events(conversation_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_artifact_events_artifact
        ON conversation_artifact_events(artifact_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_artifact_events_message
        ON conversation_artifact_events(message_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_artifact_events_kind
        ON conversation_artifact_events(event_kind);
    """
    )

def _migrate_schema_v22(conn) -> None:
    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS artifact_derivatives (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artifact_id TEXT NOT NULL,

        -- what kind of derivative is this?
        derivative_kind TEXT NOT NULL,         -- summary | index | notes | commentary | analysis | plan
        focus_kind TEXT NOT NULL DEFAULT 'general',   -- general | scenes | characters | developmental_edit | style | consistency | redundancy | worldbuilding | etc
        format_kind TEXT NOT NULL DEFAULT 'text',     -- text | json | markdown

        title TEXT,
        content_text TEXT,
        content_json TEXT,

        -- freshness / provenance
        source_artifact_content_hash TEXT,
        model_deployment_id TEXT,
        model_name TEXT,
        generator_kind TEXT NOT NULL DEFAULT 'summary_model',   -- summary_model | planner | manual | imported
        status TEXT NOT NULL DEFAULT 'ready',                   -- ready | stale | failed | pending

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(artifact_id, derivative_kind, focus_kind, format_kind),

        FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_derivatives_artifact
        ON artifact_derivatives(artifact_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_derivatives_kind_focus
        ON artifact_derivatives(derivative_kind, focus_kind);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_derivatives_status
        ON artifact_derivatives(status);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS artifact_derivative_sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artifact_derivative_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL,

        section_kind TEXT NOT NULL DEFAULT 'section',      -- section | scene | chapter | heading
        source_mode TEXT NOT NULL DEFAULT 'heading',       -- heading | inferred_scene | manual
        label TEXT,
        summary_text TEXT,

        chunk_start INTEGER NOT NULL,
        chunk_end INTEGER NOT NULL,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(artifact_derivative_id, ordinal),

        FOREIGN KEY (artifact_derivative_id) REFERENCES artifact_derivatives(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_derivative_sections_derivative
        ON artifact_derivative_sections(artifact_derivative_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_derivative_sections_chunk_range
        ON artifact_derivative_sections(chunk_start, chunk_end);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS conversation_scaffold_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        message_id INTEGER,

        event_kind TEXT NOT NULL,                 -- planner | artifact_map_refresh | reading_progress | capacity_gate
        status TEXT NOT NULL DEFAULT 'ready',     -- ready | running | done | failed
        title TEXT,
        body_text TEXT,
        input_json TEXT,
        output_json TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE SET NULL
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_scaffold_events_conversation
        ON conversation_scaffold_events(conversation_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_scaffold_events_message
        ON conversation_scaffold_events(message_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_conversation_scaffold_events_kind
        ON conversation_scaffold_events(event_kind);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS artifact_reading_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,

        mode TEXT NOT NULL DEFAULT 'reading',         -- reading | reference | mixed
        status TEXT NOT NULL DEFAULT 'active',        -- active | paused | complete | dropped
        strategy_json TEXT,

        current_section_ordinal INTEGER,
        current_chunk_position INTEGER,
        summary_so_far TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(conversation_id, artifact_id),

        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
        FOREIGN KEY (artifact_id) REFERENCES artifacts(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_reading_sessions_conversation
        ON artifact_reading_sessions(conversation_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_reading_sessions_artifact
        ON artifact_reading_sessions(artifact_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_reading_sessions_status
        ON artifact_reading_sessions(status);
    """
    )

    conn.execute(
    """
    CREATE TABLE IF NOT EXISTS artifact_reading_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        ordinal INTEGER NOT NULL,

        label TEXT,
        chunk_start INTEGER NOT NULL,
        chunk_end INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',      -- pending | active | done | skipped
        notes TEXT,

        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,

        UNIQUE(session_id, ordinal),

        FOREIGN KEY (session_id) REFERENCES artifact_reading_sessions(id) ON DELETE CASCADE
    );
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_reading_steps_session
        ON artifact_reading_steps(session_id);
    """
    )
    conn.execute(
    """
    CREATE INDEX IF NOT EXISTS idx_artifact_reading_steps_status
        ON artifact_reading_steps(status);
    """
    )

# endregion