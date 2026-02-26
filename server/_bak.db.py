import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "callie_mvp.sqlite3"

# db.py (top-level constants)
SCHEMA_VERSION = 2

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table});").fetchall()
    return any(r["name"] == column for r in rows)

def _table_has_any_rows(conn: sqlite3.Connection, table: str) -> bool:
    try:
        row = conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False

def _db_has_user_data(conn: sqlite3.Connection) -> bool:
    # tables that would indicate real usage
    for t in (
        "messages",
        "conversations",
        "projects",
        "memories", 
        "files", 
        "artifacts"
    ):
        if _table_has_any_rows(conn, t):
            return True
    return False

def _drop_all_tables(conn: sqlite3.Connection) -> None:
    # Drop in dependency order; sqlite doesn’t support DROP ... CASCADE
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


def _apply_schema_v2(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        /* Project table for multi-project support */
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

        /* Chat sessions, which can optionally be associated with projects. Conversations can be archived instead of deleted to preserve data without cluttering the UI. */
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
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            meta TEXT,
            FOREIGN KEY(conversation_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);

        /* Conversation-specific settings, including model preferences and advanced mode toggles */
        CREATE TABLE IF NOT EXISTS conversation_settings (
            conversation_id TEXT PRIMARY KEY,
            advanced_mode INTEGER DEFAULT 0,
            model_pref TEXT,
            modelB_pref TEXT,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );
                 
        /* Simple pinned memory table (manual, user-curated) */
        CREATE TABLE IF NOT EXISTS memory_pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        /* File management tables for future file upload/attachment features */
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            path TEXT NOT NULL,
            mime_type TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );                 

        /* Vector store table for future embedding-based retrieval features */
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,                       
            content TEXT NOT NULL,
            importance INTEGER DEFAULT 0,
            tags TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );                 

        /* Placeholder artifact table for future structured data storage (e.g. extracted tables, fine-tuning data) */
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );                       
                       

        /* Optional / future: keep these only if you truly need many-to-many now. */
        /* Association table between projects and files (many-to-many) */
        CREATE TABLE IF NOT EXISTS project_files (
            project_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            PRIMARY KEY (project_id, file_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (file_id) REFERENCES files(id)
        );

        /* Association table between memories and projects (many-to-many) */
        CREATE TABLE IF NOT EXISTS memory_projects (
            memory_id TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            PRIMARY KEY (memory_id, project_id),
            FOREIGN KEY (memory_id) REFERENCES memories(id),
            FOREIGN KEY (project_id) REFERENCES projects(id)
        );

        /* Association table between memories and conversations (many-to-many) */
        CREATE TABLE IF NOT EXISTS memory_conversations (
            memory_id TEXT NOT NULL,
            conversation_id TEXT NOT NULL,
            PRIMARY KEY (memory_id, conversation_id),
            FOREIGN KEY (memory_id) REFERENCES memories(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        /* Placeholder project imports table for future cross-project memory sharing features */
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

        /* Association table between projects and conversations (many-to-many) */
        CREATE TABLE IF NOT EXISTS project_conversations (
            project_id INTEGER NOT NULL,
            conversation_id TEXT NOT NULL,
            PRIMARY KEY (project_id, conversation_id),
            FOREIGN KEY (project_id) REFERENCES projects(id),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        );

        """)

    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )

def init_schema() -> None:
    conn = get_conn()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
    row = conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
    current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

    if current < SCHEMA_VERSION:
        # You said “no data yet”: enforce that claim so you don’t blow your foot off later.
        if _db_has_user_data(conn):
            conn.close()
            raise RuntimeError(
                "Refusing destructive migration: database already contains data. "
                "Write a non-destructive migration path before proceeding."
            )
        _drop_all_tables(conn)
        _apply_schema_v2(conn)
        conn.commit()

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.close()

def migrate_schema_v1_to_v2(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    # Schema evolution: add title if missing
    if not _column_exists(conn, "conversations", "title"):
        cur.execute("ALTER TABLE conversations ADD COLUMN title TEXT;")
    # Schema evolution: add meta column on messages if missing
    if not _column_exists(conn, "messages", "meta"):
        cur.execute("ALTER TABLE messages ADD COLUMN meta TEXT;")

    if not _column_exists(conn, "conversations", "project_id"):
        cur.execute("ALTER TABLE conversations ADD COLUMN project_id INTEGER;")
    if not _column_exists(conn, "conversations", "archived"):
        cur.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;")
    if not _column_exists(conn, "conversations", "summary_json"):
        cur.execute("ALTER TABLE conversations ADD COLUMN summary_json TEXT;")

    conn.commit()
    conn.close()

# TODO make helper functions instead of letting callers define SQL on their own
# These are for temporary internal use and may be refactored or removed later as the data access patterns become clearer.

def db_write(query, params=()):
    conn = get_conn()
    cur = conn.execute(query, params)
    conn.commit()
    conn.close()
    return cur

def db_read(query, params=()):
    conn = get_conn()
    cur = conn.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows

#endregion

def create_conversation(conversation_id: str, title: str = "New chat") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversations(id, created_at, title) VALUES(?, ?, ?)",
        (conversation_id, _utcnow_iso(), title),
    )
    conn.commit()
    conn.close()

def update_conversation_title(conversation_id: str, title: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE conversations SET title = ? WHERE id = ?",
        (title, conversation_id),
    )
    conn.commit()
    conn.close()

def _message_count(conn: sqlite3.Connection, conversation_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    return int(row["c"])

def add_message(conversation_id: str, role: str, content: str, meta: dict | None = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO messages(conversation_id, role, content, created_at, meta) VALUES(?, ?, ?, ?, ?)",
        (
            conversation_id,
            role,
            content,
            _utcnow_iso(),
            json.dumps(meta) if meta is not None else None,
        ),
    )

    # Auto-title: first user message becomes the conversation title (if still default-ish)
    if role == "user":
        count = _message_count(conn, conversation_id)
        # count includes the message we just inserted; so first message => count == 1
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
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (t, conversation_id),
                )

    conn.commit()
    conn.close()

def get_messages_raw(conversation_id: str, limit: int = 200) -> list[dict]:
    """
    Low-level fetch of messages with metadata, in ascending id order.
    Returns dicts with id, role, content, created_at, meta (parsed JSON or None).
    """
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, role, content, created_at, meta
        FROM messages
        WHERE conversation_id = ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    ).fetchall()
    conn.close()

    results: list[dict] = []
    for r in rows:
        raw_meta = r["meta"]
        meta = None
        if raw_meta is not None:
            try:
                meta = json.loads(raw_meta)
            except Exception:
                meta = None
        results.append(
            {
                "id": int(r["id"]),
                "role": r["role"],
                "content": r["content"],
                "created_at": r["created_at"],
                "meta": meta,
            }
        )
    return results

def get_messages(conversation_id: str, limit: int = 200) -> list[dict]:
    """
    Canonical view of messages for feeding into models, with A/B variants collapsed.
    Returns only role/content pairs.
    """
    rows = get_messages_raw(conversation_id, limit=limit)
    result: list[dict] = []
    seen_groups: set[str] = set()

    for r in rows:
        meta = r.get("meta") or {}
        ab_group = meta.get("ab_group")
        canonical = meta.get("canonical", True)

        if ab_group:
            # Only include one canonical message per A/B group.
            if ab_group in seen_groups:
                continue
            if not canonical:
                # Skip non-canonical variants; the canonical one (if any) will appear separately.
                continue
            seen_groups.add(ab_group)

        result.append({"role": r["role"], "content": r["content"]})

    return result

def list_conversations(limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, COALESCE(title, 'New chat') AS title, created_at
        FROM conversations
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"]} for r in rows]
"""
cur = conn.execute(""
SELECT c.id, c.title, c.created_at, c.updated_at,
       c.project_id,
       c.archived,
       p.name AS project_name
FROM conversations c
LEFT JOIN projects p ON p.id = c.project_id
ORDER BY c.updated_at DESC
"")
rows = cur.fetchall()
conversations = []
for row in rows:
    conversations.append(
        {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "project_id": row["project_id"],
            "project_name": row["project_name"],
            "archived": bool(row["archived"]),
        }
    )
return {"conversations": conversations}
"""

def update_ab_canonical(conversation_id: str, ab_group: str, slot: str) -> None:
    """
    Mark exactly one variant in an A/B pair as canonical for a conversation.
    slot is typically "A" or "B".
    """
    slot = slot.upper()
    if slot not in ("A", "B"):
        return

    conn = get_conn()
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
        # canonical if its slot matches the requested one
        meta["canonical"] = (meta.get("slot") == slot)
        conn.execute(
            "UPDATE messages SET meta = ? WHERE id = ?",
            (json.dumps(meta), r["id"]),
        )

    conn.commit()
    conn.close()

def add_memory_pin(text: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory_pins(text, created_at) VALUES(?, ?)",
        (text, _utcnow_iso()),
    )
    conn.commit()
    lastrowid = cur.lastrowid
    if lastrowid is None:
        conn.close()
        raise RuntimeError("failed to retrieve last insert id")
    new_id = int(lastrowid)
    conn.close()
    return new_id

def list_memory_pins(limit: int = 200) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT id, text, created_at
        FROM memory_pins
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return [{"id": int(r["id"]), "text": r["text"], "created_at": r["created_at"]} for r in rows]

def delete_memory_pin(pin_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM memory_pins WHERE id = ?", (pin_id,))
    conn.commit()
    conn.close()


def get_projects(conn):
    cur = conn.execute(
        "SELECT id, name, created_at, updated_at FROM projects ORDER BY name COLLATE NOCASE"
    )
    rows = cur.fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def get_or_create_project(conn, name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Project name cannot be empty.")
    cur = conn.execute("SELECT id FROM projects WHERE name = ?", (name,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO projects (name) VALUES (?)",
        (name,),
    )
    conn.commit()
    return cur.lastrowid


def assign_conversation_project(conn, conversation_id: str, project_id: int | None):
    conn.execute(
        "UPDATE conversations SET project_id = ?, updated_at = datetime('now') WHERE id = ?",
        (project_id, conversation_id),
    )
    conn.commit()


def set_conversation_archived(conn, conversation_id: str, archived: bool):
    conn.execute(
        "UPDATE conversations SET archived = ?, updated_at = datetime('now') WHERE id = ?",
        (1 if archived else 0, conversation_id),
    )
    conn.commit()


def delete_conversation(conn, conversation_id: str):
    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    conn.commit()


def save_conversation_summary(conn, conversation_id: str, summary_text: str, model: str):
    summary_obj = {
        "model": model,
        "summary": summary_text,
    }
    conn.execute(
        "UPDATE conversations SET summary_json = ?, updated_at = datetime('now') WHERE id = ?",
        (json.dumps(summary_obj), conversation_id),
    )
    conn.commit()