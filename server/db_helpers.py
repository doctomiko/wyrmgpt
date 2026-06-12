import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SCHEMA_VERSION = 25

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SQL_DIR = DATA_DIR / "sql"
DB_PATH = SQL_DIR / "wyrmgpt.sqlite3"

_VALID_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="strict")).hexdigest()

def _audit_metadata_json(metadata: Any | None) -> str | None:
    if metadata is None:
        return None
    if isinstance(metadata, str):
        value = metadata.strip()
        return value or None
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)

def ensure_audit_events_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT 'default',
            event_type TEXT NOT NULL,
            actor_principal_type TEXT,
            actor_principal_id TEXT,
            resource_type TEXT,
            resource_id TEXT,
            action TEXT,
            decision TEXT,
            reason TEXT,
            request_id TEXT,
            source_ip TEXT,
            user_agent TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_audit_events_tenant_created
            ON audit_events(tenant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_resource
            ON audit_events(resource_type, resource_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_actor
            ON audit_events(actor_principal_type, actor_principal_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
            ON audit_events(event_type, created_at);
        CREATE INDEX IF NOT EXISTS idx_audit_events_request_id
            ON audit_events(request_id);
        """
    )

def log_audit_event(
    *,
    event_type: str,
    tenant_id: str = "default",
    actor_principal_type: str | None = None,
    actor_principal_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
    request_id: str | None = None,
    source_ip: str | None = None,
    user_agent: str | None = None,
    metadata: Any | None = None,
    conn: sqlite3.Connection | None = None,
    raise_on_error: bool = False,
) -> str | None:
    event_type = (event_type or "").strip()
    if not event_type:
        raise ValueError("event_type is required")

    audit_id = new_uuid()
    values = (
        audit_id,
        (tenant_id or "default").strip() or "default",
        event_type,
        (actor_principal_type or "").strip() or None,
        (actor_principal_id or "").strip() or None,
        (resource_type or "").strip() or None,
        (resource_id or "").strip() or None,
        (action or "").strip() or None,
        (decision or "").strip() or None,
        (reason or "").strip() or None,
        (request_id or "").strip() or None,
        (source_ip or "").strip() or None,
        (user_agent or "").strip() or None,
        _audit_metadata_json(metadata),
        _utc_now_iso(),
    )

    def _insert(target: sqlite3.Connection) -> None:
        target.execute(
            """
            INSERT INTO audit_events (
                id, tenant_id, event_type, actor_principal_type, actor_principal_id,
                resource_type, resource_id, action, decision, reason, request_id,
                source_ip, user_agent, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values,
        )

    try:
        if conn is not None:
            _insert(conn)
        else:
            with db_session() as sconn:
                _insert(sconn)
    except sqlite3.Error:
        if raise_on_error:
            raise
        return None

    return audit_id

def get_audit_event(audit_id: str, conn: sqlite3.Connection | None = None) -> dict | None:
    audit_id = (audit_id or "").strip()
    if not audit_id:
        return None

    def _fetch(target: sqlite3.Connection) -> dict | None:
        row = target.execute("SELECT * FROM audit_events WHERE id = ?", (audit_id,)).fetchone()
        return dict(row) if row else None

    if conn is not None:
        return _fetch(conn)
    with db_session() as sconn:
        return _fetch(sconn)

_OWNED_RESOURCE_TABLES = (
    "projects",
    "conversations",
    "messages",
    "memories",
    "files",
    "artifacts",
)

def ensure_resource_ownership_columns(
    conn: sqlite3.Connection,
    tables: Iterable[str] = _OWNED_RESOURCE_TABLES,
) -> None:
    for table in tables:
        if not table or not _VALID_TABLE.match(table):
            raise ValueError(f"Unsafe table name: {table!r}")
        if not _table_exists(conn, table):
            continue
        _add_column_if_missing(conn, table, "tenant_id", "TEXT NOT NULL DEFAULT 'default'")
        _add_column_if_missing(conn, table, "owner_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "owner_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "created_by_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "created_by_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_type", "TEXT")
        _add_column_if_missing(conn, table, "source_principal_id", "TEXT")
        _add_column_if_missing(conn, table, "visibility", "TEXT NOT NULL DEFAULT 'private'")
        _add_column_if_missing(conn, table, "sharing_mode", "TEXT NOT NULL DEFAULT 'owner'")
        _add_column_if_missing(conn, table, "provenance_json", "TEXT")

        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id)"
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_owner_principal
                ON {table}(owner_principal_type, owner_principal_id)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_created_by_principal
                ON {table}(created_by_principal_type, created_by_principal_id)
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{table}_source_principal
                ON {table}(source_principal_type, source_principal_id)
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_visibility ON {table}(visibility)"
        )

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

# region Schema Init

def _force_schema_regression_if_table_missing(
    target_version: int,
    required_table: str,
) -> None:
    target = int(target_version)
    table = (required_table or "").strip()
    if target < 0:
        raise ValueError("target_version must be >= 0")
    if not table:
        raise ValueError("required_table is required")

    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

        table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()

        if table_row:
            print(f"Regression skipped: table {table!r} already exists; schema_version={current}")
            return

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(target),),
        )
        print(f"Forced schema regression because {table!r} is missing: {current} -> {target}")

def _force_schema_regression(target_version: int) -> None:
    """
    TEMPORARY REPAIR TOOL.

    Force schema_meta.schema_version backward so init_schema() will re-run
    later migrations. This does NOT drop tables. It only rewinds the version
    marker.

    Comment out/remove call sites when done.
    """
    target = int(target_version)
    if target < 0:
        raise ValueError("target_version must be >= 0")

    with db_session() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        current = int(row["value"]) if row and str(row["value"]).isdigit() else 0

        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(target),),
        )

        print(f"Forced schema regression: {current} -> {target}")

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

_SCHEMA_INIT_LOGGED = False

def _end_schema_init(conn: sqlite3.Connection, original: int, current: int = SCHEMA_VERSION) -> None:
    global _SCHEMA_INIT_LOGGED
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
        (str(current),),
    )

    if not _SCHEMA_INIT_LOGGED or original != current:
        print(f"DB initialized with schema version {current} (was {original})")
        _SCHEMA_INIT_LOGGED = True
        # TODO implement seperate log file and log there as well.
        #log.logger.info(f"DB initialized with schema version {SCHEMA_VERSION} (was {current})")

# endregion