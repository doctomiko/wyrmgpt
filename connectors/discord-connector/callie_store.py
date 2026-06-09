# TODO make config a thing Store gets on its own
import asyncio
from dataclasses import dataclass
import os
import sqlite3
import time
from typing import Any, ClassVar, List, Optional, Tuple

import aiosqlite

from callie_logging import log, setup_logging
from global_config import GlobalConfig
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from guild_config import GuildConfig
from helpers import canonical_json, now_epoch, iso_now_utc, sha256_hex

log, _log_settings = setup_logging("callie_store")

@dataclass
class SessionState:
    channel_id: int
    is_active: bool
    ambient: bool
    verbose: bool
    last_activity: int
    ignore_until: int

    def is_closed(self) -> bool:
        """Only humans should close sessions; no TTL logic here."""
        return not bool(self.is_active)

    def is_quiet_blocked(self, now_ts: int) -> bool:
        """True if we're currently in a quiet period (ignore_until in the future)."""
        try:
            return int(self.ignore_until or 0) > int(now_ts)
        except Exception:
            return False

    def touch(self, now_ts: int) -> None:
        """Update last_activity without changing open/closed state."""
        try:
            self.last_activity = int(now_ts)
        except Exception:
            self.last_activity = 0

    def start(self, now_ts: int) -> None:
        self.is_active = True
        self.touch(now_ts)

    def stop(self, ambient_default: bool) -> None:
        self.is_active = False
        self.ambient = bool(ambient_default)
        # do not alter last_activity; it's informational

    def set_quiet_until(self, until_ts: int) -> None:
        self.ignore_until = int(until_ts or 0)

#def init_callie_store(config: GlobalConfig, do_open: Optional[bool] | None = None) -> "Store":
#   """
#   Initialize the global Store instance.
#   """
#   global CALLIE_STORE
#   if CALLIE_STORE is None:
#       log.info("init_callie_store: Creating new Store instance")
#       CALLIE_STORE = Store(config)
#    if not CALLIE_STORE:
#       log.warning("init_callie_store: Store construction failed!")
#    CALLIE_STORE.__init__(config, do_open)
#    if do_open and not CALLIE_STORE._open_done:
#        log.warning("init_callie_store: do_open=True but store not open after init when forcing synchronous open")
#    else:
#        log.info("init_callie_store: Returning existing CALLIE_STORE instance")
#    return CALLIE_STORE

# Module-level singleton Store instance
#CALLIE_STORE: Optional["Store"]

class Store:
    # Return only one Store instance per process.
    def __new__(cls, config: GlobalConfig, *args, **kwargs):
        if cls._singleton is not None:
            return cls._singleton
        cls._singleton = super(Store, cls).__new__(cls)
        return cls._singleton

    _singleton: ClassVar[Optional["Store"]] = None
    _is_initialized: bool = False
    _open_done: bool = False

    def __init__(self, config: GlobalConfig = GlobalConfig()): # path: str, 
        log.info("Initializing Callie Store at %r", config.sqlite_path)
        if self._is_initialized: # Don't re-initialize
            return
        # , do_open: Optional[bool] = True
        self._is_initialized = False
        self.path = config.sqlite_path
        self.config = config
        # Connect to the SQLite DB
        self.db: Optional[aiosqlite.Connection] = None
        self._open_lock = asyncio.Lock()
        self._open_done = False
        self._write_lock = asyncio.Lock()
        self._messages_cols = None
        self._channel_clock_col = None
        # An attempt to open DB immediately
        if self._open_done: # and do_open is True
            self.ensure_open_sync()
        self._is_initialized = True
        log.info("Callie Store initialized")

    async def _get_table_columns(self, table: str) -> set[str]:
        assert self.db
        cur = await self.db.execute(f"PRAGMA table_info({table})")
        rows = await cur.fetchall()
        await cur.close()
        return {r[1] for r in rows}

    async def _ensure_compat_columns(self):
        # Additive migrations for existing DBs:
        # - messages.created_at legacy NOT NULL support (adds column if missing)
        # - channel_clock column drift: seq vs last_seq (adds missing column if needed)
        # - caches messages columns for dynamic inserts
        assert self.db

        # messages.created_at
        # summarization columns (additive)
        try:
            cols = await self._get_table_columns("messages")
            for col_sql in [
                "ALTER TABLE messages ADD COLUMN is_summary INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE messages ADD COLUMN is_summarized INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE messages ADD COLUMN summarized_in INTEGER",
                "ALTER TABLE messages ADD COLUMN summary_start_db_id INTEGER",
                "ALTER TABLE messages ADD COLUMN summary_end_db_id INTEGER",
                "ALTER TABLE messages ADD COLUMN summary_start_ts INTEGER",
                "ALTER TABLE messages ADD COLUMN summary_end_ts INTEGER",
                "ALTER TABLE messages ADD COLUMN summary_participants TEXT",
            ]:
                col_name = col_sql.split("ADD COLUMN", 1)[1].strip().split()[0]
                if col_name not in cols:
                    try:
                        await self.db.execute(col_sql)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            cols = await self._get_table_columns("messages")
            if "discord_guild_id" not in cols:
                try:
                    await self.db.execute("ALTER TABLE messages ADD COLUMN discord_guild_id INTEGER")
                except Exception:
                    log.warning("Failed to add messages.discord_guild_id column", exc_info=True)
                    pass
            if "created_at" not in cols:
                try:
                    await self.db.execute("ALTER TABLE messages ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0")
                except Exception:
                    log.warning("Failed to add messages.created_at column", exc_info=True   )
                    pass
        except Exception:
            pass

        # channel_clock seq/last_seq compatibility
        try:
            cols = await self._get_table_columns("channel_clock")
            if "seq" in cols:
                self._channel_clock_col = "seq"
                if "last_seq" not in cols:
                    try:
                        await self.db.execute("ALTER TABLE channel_clock ADD COLUMN last_seq INTEGER NOT NULL DEFAULT 0")
                    except Exception:
                        pass
            elif "last_seq" in cols:
                self._channel_clock_col = "last_seq"
                if "seq" not in cols:
                    try:
                        await self.db.execute("ALTER TABLE channel_clock ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
                    except Exception:
                        pass
            else:
                self._channel_clock_col = "seq"
        except Exception:
            self._channel_clock_col = "seq"

        # cache messages columns
        try:
            self._messages_cols = await self._get_table_columns("messages")
        except Exception:
            self._messages_cols = None

    async def ensure_open(self) -> None:
        if self._open_done:
            return
        async with self._open_lock:
            if self._open_done:
                return
            await self.open()

    def ensure_open_sync(self, timeout: float = 60.0) -> None:
        """
        Safe for startup scripts / non-async code.
        Guaranteed: returns only after open completes (or raises).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(asyncio.wait_for(self.ensure_open(), timeout=timeout))
            return
        # If you're already in an event loop, you cannot block it.
        # So: either require caller to await ensure_open(), or run in another thread.
        raise RuntimeError("ensure_open_sync() called while an event loop is running; use `await store.ensure_open()` instead.")

    async def open(self):
        log.info("Opening Callie Store at %r", self.config.sqlite_path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL;")
        await self.db.execute("PRAGMA foreign_keys=ON;")
        log.info("Checking schema migrations")
        await self._migrate()
        await self._ensure_compat_columns()
        await self.db.commit()
        self._open_done = True
        log.info("Schema migrations complete")
        log.info("Callie Store opened")

    async def _migrate(self):
        assert self.db
        await self.db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            channel_id INTEGER PRIMARY KEY,
            is_active INTEGER NOT NULL,
            ambient INTEGER NOT NULL,
            verbose INTEGER NOT NULL DEFAULT 0,
            last_activity INTEGER NOT NULL
            , ignore_until INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            discord_guild_id INTEGER,
            discord_message_id INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            is_callie INTEGER NOT NULL,
            -- Summarization support
            is_summary INTEGER NOT NULL DEFAULT 0,
            is_summarized INTEGER NOT NULL DEFAULT 0,
            summarized_in INTEGER,
            summary_start_db_id INTEGER,
            summary_end_db_id INTEGER,
            summary_start_ts INTEGER,
            summary_end_ts INTEGER,
            summary_participants TEXT
        );

        CREATE TABLE IF NOT EXISTS memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            content TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS memory_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at INTEGER NOT NULL,
            author_id INTEGER NOT NULL,
            author_name TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            decided_at INTEGER NOT NULL DEFAULT 0,
            decided_by_id INTEGER NOT NULL DEFAULT 0,
            decided_by_name TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS tenant_config (
            guild_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (guild_id, key)
        );
        """)
        # Backfill 'verbose' if older DB exists without it.
        try:
            await self.db.execute("ALTER TABLE sessions ADD COLUMN verbose INTEGER NOT NULL DEFAULT 0;")
            await self.db.execute("ALTER TABLE sessions ADD COLUMN ignore_until INTEGER NOT NULL DEFAULT 0;")
        except Exception:
            pass
        await self.db.commit()

    # A snippit shared by Callie Prime
    #def ensure_messages_schema(conn):
    #   cur = conn.cursor()
    #   cur.execute("PRAGMA table_info(messages)")
    #   cols = {row[1] for row in cur.fetchall()}
    #   if "discord_guild_id" not in cols:
    #       cur.execute(
    #           "ALTER TABLE messages ADD COLUMN discord_guild_id INTEGER"
    #       )
    #       conn.commit()

    async def close(self) -> None:
        try:
            if self.db is not None:
                await self.db.close()
        finally:
            self.db = None

    # Needs "(await gc.ambient_default())" so gc is in scope
    # Has a default of False for legacy compatibility
    async def get_session(self, channel_id: int, ambient_default: bool | bool = False) -> SessionState:
        """Return session state for channel_id, creating default if missing.
         ambient_default: default value for ambient if session needs to be created. last param needs (await gc.ambient_default())"""
        if self.db is None:
            import sys
            caller = sys._getframe(1).f_code.co_name if hasattr(sys, "_getframe") else "<unknown>"
            raise RuntimeError(f"Store.get_session() called before DB initialized; caller={caller}")
        assert self.db
        cur = await self.db.execute(
            "SELECT is_active, ambient, verbose, last_activity, ignore_until FROM sessions WHERE channel_id=?",
            (channel_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        if row is None:
            st = SessionState(channel_id, False, ambient_default, False, 0, 0)
            await self.set_session(st)
            return st
        return SessionState(channel_id, bool(row[0]), bool(row[1]), bool(row[2]), int(row[3]), int(row[4] or 0))

    async def set_session(self, st: SessionState):
        assert self.db
        await self.db.execute(
            "INSERT INTO sessions(channel_id, is_active, ambient, verbose, last_activity, ignore_until) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET "
            "is_active=excluded.is_active, ambient=excluded.ambient, verbose=excluded.verbose, "
            "last_activity=excluded.last_activity, ignore_until=excluded.ignore_until",
            (int(st.channel_id), int(st.is_active), int(st.ambient), int(st.verbose), int(st.last_activity), int(st.ignore_until)),
        )
        await self.db.commit()

    async def log_message(
        self, 
        channel_id: int, 
        discord_guild_id: int, 
        discord_message_id: int, 
        author_id: int, 
        author_name: str, 
        content: str, 
        created_at: int, 
        is_callie: bool
    ):
        assert self.db
        await self.db.execute(
            "INSERT INTO messages(channel_id, discord_guild_id, discord_message_id, author_id, author_name, content, created_at, is_callie) VALUES(?,?,?,?,?,?,?,?)",
            (channel_id, discord_guild_id, discord_message_id, author_id, author_name, content, created_at, int(is_callie)),
        )
        await self.db.commit()

    async def recent_messages(self, channel_id: int, limit: int) -> List[dict]:
        # Return recent message rows for a channel in chronological order (oldest -> newest).
        # Includes summary rows. The context builder is responsible for filtering summarized raw rows.
        assert self.db
        cur = await self.db.execute(
            "SELECT id, discord_message_id, author_id, author_name, content, created_at, is_callie, is_summary, is_summarized "
            "FROM messages WHERE channel_id=? ORDER BY id DESC LIMIT ?",
            (channel_id, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        rows = list(rows)
        rows.reverse()

        out: List[dict] = []
        for (db_id, discord_message_id, author_id, author_name, content, created_at, is_callie, is_summary, is_summarized) in rows:
            out.append({
                "db_id": int(db_id),
                "discord_message_id": int(discord_message_id) if discord_message_id is not None else 0,
                "author_id": int(author_id) if author_id is not None else 0,
                "author_name": author_name or "",
                "content": content or "",
                "created_at": int(created_at) if created_at is not None else 0,
                "is_callie": bool(is_callie),
                "is_summary": bool(is_summary),
                "is_summarized": bool(is_summarized),
            })
        return out

    async def unsummarized_dropped_messages(self, channel_id: int, dropped_db_ids: List[int], limit: int) -> List[dict[str, Any]]:
        # Given a list of dropped message DB ids (oldest-first), return up to `limit` unsummarized, non-summary rows in DB order.
        assert self.db
        if not dropped_db_ids:
            return []
        take = dropped_db_ids[: max(1, limit)]
        placeholders = ",".join(["?"] * len(take))
        cur = await self.db.execute(
            f"SELECT id, author_name, content, created_at, is_callie FROM messages "
            f"WHERE id IN ({placeholders}) AND is_summary=0 AND is_summarized=0 "
            f"ORDER BY id ASC",
            tuple(take),
        )
        rows = await cur.fetchall()
        await cur.close()
        out: List[dict] = []
        for (mid, author_name, content, created_at, is_callie) in rows:
            out.append({
                "db_id": int(mid),
                "author_name": author_name,
                "content": content,
                "created_at": int(created_at),
                "is_callie": bool(is_callie),
            })
        return out

    async def insert_summary_and_mark(self, channel_id: int, summary_text: str, start_db_id: int, end_db_id: int,
                                     start_ts: int, end_ts: int, participants: List[str]) -> int:
        # Insert a summary row (is_summary=1) and mark messages in [start_db_id, end_db_id] as summarized.
        # Returns the new summary row id.
        assert self.db
        participants_s = ", ".join(sorted(set([p for p in participants if p])))
        # summary row appears after covered messages because it gets a higher autoincrement id
        cur = await self.db.execute(
            "INSERT INTO messages(channel_id, discord_message_id, author_id, author_name, content, created_at, is_callie, is_summary, "
            "is_summarized, summarized_in, summary_start_db_id, summary_end_db_id, summary_start_ts, summary_end_ts, summary_participants) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (channel_id, 0, 0, "Callie (summary)", summary_text, end_ts, 1, 1, 0, None, start_db_id, end_db_id, start_ts, end_ts, participants_s),
        )
        await cur.close()
        # fetch id
        cur2 = await self.db.execute("SELECT last_insert_rowid()")
        row = await cur2.fetchone()
        await cur2.close()
        sid = int(row[0]) if row and row[0] is not None else 0
        await self.db.execute(
            "UPDATE messages SET is_summarized=1, summarized_in=? WHERE channel_id=? AND id>=? AND id<=? AND is_summary=0",
            (sid, channel_id, start_db_id, end_db_id),
        )
        await self.db.commit()
        return int(sid)

    async def most_recent_summary_time(self, channel_id: int) -> int:
        assert self.db
        cur = await self.db.execute(
            "SELECT created_at FROM messages WHERE channel_id=? AND is_summary=1 ORDER BY id DESC LIMIT 1",
            (channel_id,),
        )
        row = await cur.fetchone()
        await cur.close()
        return int(row[0]) if row else 0


    async def add_memory(self, author_id: int, author_name: str, content: str):
        assert self.db
        await self.db.execute(
            "INSERT INTO memory_items(created_at, author_id, author_name, content) VALUES(?,?,?,?)",
            (now_epoch(), author_id, author_name, content),
        )
        await self.db.commit()


    async def list_memory_items(self, limit: int = 50) -> List[dict]:
        assert self.db
        limit = max(1, min(int(limit), 200))
        cur = await self.db.execute(
            "SELECT id, created_at, author_id, author_name, content FROM memory_items ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
        await cur.close()
        out: List[dict] = []
        for (mid, created_at, author_id, author_name, content) in rows:
            out.append({
                "id": int(mid),
                "mid": f"M{int(mid):06d}",
                "created_at": int(created_at),
                "author_id": int(author_id),
                "author_name": str(author_name),
                "content": str(content),
            })
        return out

    async def get_memory_item(self, mid: int) -> Optional[dict]:
        assert self.db
        cur = await self.db.execute(
            "SELECT id, created_at, author_id, author_name, content FROM memory_items WHERE id=?",
            (int(mid),),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return None
        (mid, created_at, author_id, author_name, content) = row
        return {
            "id": int(mid),
            "mid": f"M{int(mid):06d}",
            "created_at": int(created_at),
            "author_id": int(author_id),
            "author_name": str(author_name),
            "content": str(content),
        }

    async def update_memory_item(self, mid: int, new_content: str) -> bool:
        assert self.db
        await self.db.execute(
            "UPDATE memory_items SET content=? WHERE id=?",
            (str(new_content), int(mid)),
        )
        await self.db.commit()
        return True

    async def delete_memory_item(self, mid: int) -> bool:
        assert self.db
        await self.db.execute("DELETE FROM memory_items WHERE id=?", (int(mid),))
        await self.db.commit()
        return True

    async def get_memory_meta(self) -> Tuple[int, int]:
        # Return (memory_total_count, memory_last_updated_epoch).
        assert self.db
        cur = await self.db.execute("SELECT COUNT(*), COALESCE(MAX(created_at), 0) FROM memory_items")
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    async def add_memory_suggestion(self, author_id: int, author_name: str, payload_json: str) -> int:
        # Store a pending memory suggestion. Returns suggestion id.
        assert self.db
        cur = await self.db.execute(
            "INSERT INTO memory_suggestions(created_at, author_id, author_name, payload_json, status) VALUES(?,?,?,?, 'pending')",
            (now_epoch(), int(author_id), str(author_name), str(payload_json)),
        )
        await self.db.commit()
        return int(cur.lastrowid or 0)

    async def list_memory_suggestions(self, limit: int = 50, status: str = "pending") -> List[dict]:
        assert self.db
        status = (status or "pending").strip().lower()
        limit = max(1, min(int(limit), 200))
        cur = await self.db.execute(
            "SELECT id, created_at, author_name, payload_json FROM memory_suggestions WHERE status=? ORDER BY id DESC LIMIT ?",
            (status, limit),
        )
        rows = await cur.fetchall()
        await cur.close()
        out: List[dict] = []
        for (sid, created_at, author_name, payload_json) in rows:
            out.append({
                "id": int(sid),
                "pid": f"P{int(sid)}",
                "created_at": int(created_at),
                "author_name": str(author_name),
                "payload_json": str(payload_json),
            })
        return out

    async def decide_memory_suggestion(self, suggestion_id: int, decision: str, decided_by_id: int, decided_by_name: str) -> bool:
        # decision: 'accepted' or 'rejected'. If accepted, commits to memory_items.
        assert self.db
        decision = (decision or "").strip().lower()
        if decision not in ("accepted", "rejected"):
            raise ValueError("decision must be accepted or rejected")

        cur = await self.db.execute(
            "SELECT status, author_id, author_name, payload_json FROM memory_suggestions WHERE id=?",
            (int(suggestion_id),),
        )
        row = await cur.fetchone()
        await cur.close()
        if not row:
            return False

        status, author_id, author_name, payload_json = row
        if str(status) != "pending":
            return False

        decided_at = now_epoch()
        await self.db.execute(
            "UPDATE memory_suggestions SET status=?, decided_at=?, decided_by_id=?, decided_by_name=? WHERE id=?",
            (decision, int(decided_at), int(decided_by_id), str(decided_by_name), int(suggestion_id)),
        )

        if decision == "accepted":
            # Commit suggestion payload into memory_items as raw JSON or text
            await self.db.execute(
                "INSERT INTO memory_items(created_at, author_id, author_name, content) VALUES(?,?,?,?)",
                (int(decided_at), int(author_id), str(author_name), str(payload_json)),
            )

        await self.db.commit()
        return True

    async def get_memory_blob(
        self,
        newest: Optional[int] = None,
        oldest: Optional[int] = None,
        random_mid: Optional[int] = None,
        #gc: "GuildConfig | None" = None,
    ) -> str:
        assert self.db

        # Defensive normalization (prevents Ellipsis / weird types from reaching SQLite)
        def _norm_int(v: object, default: int) -> int:
            if v is None or v is ...:
                return default
            try:
                return int(v)  # type: ignore[arg-type]
            except Exception:
                return default

        newest = _norm_int(newest, 10)
        oldest = _norm_int(oldest, 10)
        random_mid = _norm_int(random_mid, 10)

        #if gc is not None:
        #    log.warning("Store.get_memory_blob: gc parameter is deprecated in memory settings")
        #    log.warning("It is dangerous to pass in gc directly because it may lead to inconsistent guild config reads")
        #    log.warning("Please refactor to read memory settings outside and pass in explicit newest/oldest/random_mid values")
        #    if newest is None:
        #        _val = await gc.memory_newest()
        #    if oldest is None:
        #       _val = await gc.memory_oldest()
        #    if random_mid is None:
        #        _val = await gc.memory_random()

        # Total count
        cur = await self.db.execute("SELECT COUNT(*) FROM memory_items")
        row = await cur.fetchone()
        await cur.close()
        total_count = int(row[0]) if row and row[0] is not None else 0

        if total_count == 0:
            return ""

        # Fetch newest
        cur = await self.db.execute(
            "SELECT id, created_at, author_name, content FROM memory_items ORDER BY id DESC LIMIT ?",
            (newest,),
        )
        newest_rows = await cur.fetchall()
        await cur.close()

        # Fetch oldest
        cur = await self.db.execute(
            "SELECT id, created_at, author_name, content FROM memory_items ORDER BY id ASC LIMIT ?",
            (oldest,),
        )
        oldest_rows = await cur.fetchall()
        await cur.close()

        selected_ids = set()
        entries = []

        def add_rows(rows, bucket: str):
            for (mid, created_at, author_name, content) in rows:
                if mid in selected_ids:
                    continue
                selected_ids.add(mid)
                entries.append(
                    {
                        "id": f"M{mid:06d}",
                        "db_id": mid,
                        "created_at": created_at,  # your DB stores epoch ints already
                        "author_name": author_name,
                        "text": content,
                        "bucket": bucket,
                    }
                )

        add_rows(oldest_rows, "oldest")
        add_rows(newest_rows, "newest")

        # Random from the remaining pool (no dupes)
        remaining_needed = max(0, int(random_mid) if random_mid is not None else 0)
        if remaining_needed > 0:
            if selected_ids:
                placeholders = ",".join(["?"] * len(selected_ids))
                sql = (
                    f"SELECT id, created_at, author_name, content "
                    f"FROM memory_items WHERE id NOT IN ({placeholders}) "
                    f"ORDER BY RANDOM() LIMIT ?"
                )
                params = tuple(selected_ids) + (remaining_needed,)
                cur = await self.db.execute(sql, params)
            else:
                cur = await self.db.execute(
                    "SELECT id, created_at, author_name, content FROM memory_items ORDER BY RANDOM() LIMIT ?",
                    (remaining_needed,),
                )
            rand_rows = await cur.fetchall()
            await cur.close()
            add_rows(rand_rows, "random")

        # Receipt + payload
        # Use the max created_at among injected entries as "last updated" surrogate
        last_updated = max(e["created_at"] for e in entries) if entries else 0
        injected_ids = [e["id"] for e in entries]

        payload = {
            "schema": "callie.memory.v1",
            "memory_version": iso_now_utc(),
            "memory_last_updated": last_updated,
            "memory_total_count": total_count,
            "injected_count": len(entries),
            "injected_ids": injected_ids,
            "entries": entries,
        }

        canon = canonical_json(payload)
        payload["checksum"] = "sha256:" + sha256_hex(canon)

        # This is what gets injected into the prompt
        return (
            "=== MEMORY_PAYLOAD_JSON (authoritative, connector-generated) ===\n"
            + canonical_json(payload)
            + "\n=== END_MEMORY_PAYLOAD_JSON ==="
        )


    # --------------------
    # Synchronous admin helpers for console menu (safe, read-only)
    # --------------------
    def admin_message_stats_sync(self) -> dict:
        """Return basic counts for messages table."""
        try:
            con = sqlite3.connect(self.path)
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM messages")
            total = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM messages WHERE is_summarized=1")
            summarized = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM messages WHERE is_summarized=0")
            active = int(cur.fetchone()[0])
            con.close()
            return {"total": total, "summarized": summarized, "active": active}
        except Exception as e:
            return {"error": str(e)}

    def admin_summary_stats_sync(self) -> dict:
        """Return basic counts for summaries table."""
        try:
            con = sqlite3.connect(self.path)
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM messages WHERE is_summary=1")
            total = int(cur.fetchone()[0])
            con.close()
            return {"total": total}
        except Exception as e:
            return {"error": str(e)}

    def count_tenants_sync(self) -> int:
        try:
            con = sqlite3.connect(self.path)
            cur = con.cursor()
            cur.execute("SELECT COUNT(DISTINCT guild_id) FROM tenant_config")
            n = int(cur.fetchone()[0])
            con.close()
            return n
        except Exception:
            return 0
        # -------------------------
        # (Legacy) Hotpatch: bind a module-level get_memory_blob onto Store
        # -------------------------
        # This used to exist because get_memory_blob accidentally lived at module scope.
        # It *also* used to be placed after asyncio.run(main()), so it never ran.
        # get_memory_blob is now a proper Store method, so this is intentionally disabled.
        #
        # try:
        #     if hasattr(Store, "__dict__") and ("get_memory_blob" not in Store.__dict__) and ("get_memory_blob" in globals()):
        #         Store.get_memory_blob = get_memory_blob  # type: ignore
        # except Exception:
        #     pass

    # --- Admin helpers: summaries and message maintenance ---

    async def list_summaries(self, channel_id: int, limit: int = 50, offset: int = 0) -> List[aiosqlite.Row]:
        assert self.db is not None
        q = """SELECT id, created_at, author_name, LENGTH(content) AS chars,
                       summary_start_db_id, summary_end_db_id, summary_start_ts, summary_end_ts, summary_participants
                FROM messages
                WHERE channel_id=? AND is_summary=1
                ORDER BY id DESC
                LIMIT ? OFFSET ?"""
        async with self.db.execute(q, (channel_id, limit, offset)) as cur:
            rows = await cur.fetchall()
            return list(rows)

    async def list_summaries_in_range(self, channel_id: int, start_ts: int, end_ts: int, limit: int = 500) -> List[aiosqlite.Row]:
        """List summary rows (is_summary=1) created in [start_ts, end_ts], oldest-first."""
        assert self.db is not None
        q = """SELECT id, created_at, author_name, content, LENGTH(content) AS chars,
                       summary_start_db_id, summary_end_db_id, summary_start_ts, summary_end_ts, summary_participants
                FROM messages
                WHERE channel_id=? AND is_summary=1 AND created_at>=? AND created_at<=?
                ORDER BY id ASC
                LIMIT ?"""
        async with self.db.execute(q, (channel_id, int(start_ts), int(end_ts), int(limit))) as cur:
            rows = await cur.fetchall()
            return list(rows)


    async def insert_summary_row_only(self, channel_id: int, summary_text: str, start_ts: int, end_ts: int, participants: List[str]) -> int:
        """Insert a summary row without marking any underlying messages as summarized.

        This is used for admin 'summary-of-summaries' merges.
        """
        assert self.db is not None
        participants_s = ", ".join(sorted(set([p for p in participants if p])))
        cur = await self.db.execute(
            """INSERT INTO messages(
                    channel_id, discord_message_id, author_id, author_name, content, created_at,
                    is_callie, is_summary, is_summarized, summarized_in,
                    summary_start_db_id, summary_end_db_id, summary_start_ts, summary_end_ts, summary_participants
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (int(channel_id), 0, 0, "Callie (summary)", summary_text, int(time.time()),
             1, 1, 0, None,
             None, None, int(start_ts), int(end_ts), participants_s),
        )
        await cur.close()
        cur2 = await self.db.execute("SELECT last_insert_rowid()")
        row = await cur2.fetchone()
        await cur2.close()
        await self.db.commit()
        return int(row[0]) if row else 0



    async def read_summary(self, channel_id: int, summary_db_id: int) -> Optional[aiosqlite.Row]:
        assert self.db is not None
        q = """SELECT *
                FROM messages
                WHERE channel_id=? AND id=? AND is_summary=1
                LIMIT 1"""
        async with self.db.execute(q, (channel_id, summary_db_id)) as cur:
            return await cur.fetchone()

    async def delete_summary(self, channel_id: int, summary_db_id: int, *, unsummarize: bool = True) -> bool:
        """Delete a summary row and 'unsummarize' messages that pointed to it."""
        assert self.db is not None
        async with self._write_lock:
            if unsummarize:
                await self.db.execute(
                    "UPDATE messages SET is_summarized=0, summarized_in=NULL WHERE channel_id=? AND summarized_in=?",
                    (channel_id, summary_db_id),
                )
            cur = await self.db.execute(
                "DELETE FROM messages WHERE channel_id=? AND id=? AND is_summary=1",
                (channel_id, summary_db_id),
            )
            await self.db.commit()
            return cur.rowcount > 0

    async def message_stats_by_day(self, channel_id: int, days: int = 14) -> List[aiosqlite.Row]:
        """Basic counts by day for the last N days."""
        assert self.db is not None
        q = """SELECT date(created_at, 'unixepoch') AS day,
                       COUNT(*) AS total,
                       SUM(CASE WHEN is_callie=1 THEN 1 ELSE 0 END) AS callie,
                       SUM(CASE WHEN is_summary=1 THEN 1 ELSE 0 END) AS summaries,
                       SUM(CASE WHEN is_summarized=1 THEN 1 ELSE 0 END) AS summarized_msgs,
                       SUM(CASE WHEN is_summarized=0 AND is_summary=0 THEN 1 ELSE 0 END) AS active_msgs
                FROM messages
                WHERE channel_id=? AND created_at >= strftime('%s','now','-'||?||' days')
                GROUP BY day
                ORDER BY day DESC"""
        async with self.db.execute(q, (channel_id, days)) as cur:
            rows = await cur.fetchall()
            return list(rows)

    async def list_messages(self, channel_id: int, day: Optional[str] = None, limit: int = 50, offset: int = 0,
                            include_summaries: bool = False) -> List[aiosqlite.Row]:
        assert self.db is not None
        where = "channel_id=?"
        params: List = [channel_id]
        if day:
            where += " AND date(created_at,'unixepoch')=?"
            params.append(day)
        if not include_summaries:
            where += " AND is_summary=0"
        q = f"""SELECT id, created_at, author_name, is_callie, is_summary, is_summarized, summarized_in,
                        substr(content,1,200) AS snippet
                 FROM messages
                 WHERE {where}
                 ORDER BY id DESC
                 LIMIT ? OFFSET ?"""
        params.extend([limit, offset])
        async with self.db.execute(q, tuple(params)) as cur:
            rows = await cur.fetchall()
            return list(rows)

    async def read_message(self, channel_id: int, db_id: int) -> Optional[aiosqlite.Row]:
        assert self.db is not None
        async with self.db.execute("SELECT * FROM messages WHERE channel_id=? AND id=? LIMIT 1", (channel_id, db_id)) as cur:
            return await cur.fetchone()

    async def delete_message(self, channel_id: int, db_id: int) -> bool:
        """Delete a message row. If it was a summary, prefer delete_summary()."""
        assert self.db is not None
        async with self._write_lock:
            cur = await self.db.execute("DELETE FROM messages WHERE channel_id=? AND id=?", (channel_id, db_id))
            await self.db.commit()
            return cur.rowcount > 0

    async def config_get(self, guild_id: int, key: str) -> Optional[str]:
        assert self.db is not None
        # await self._ensure_db()
        async with self.db.execute("SELECT value FROM tenant_config WHERE guild_id=? AND key=?", (guild_id, key)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def config_set(self, guild_id: int, key: str, value: str) -> None:
        assert self.db is not None
        # await self._ensure_db()
        now = int(time.time())
        await self.db.execute(
            "INSERT INTO tenant_config (guild_id, key, value, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (guild_id, key, value, now),
        )
        await self.db.commit()

    async def config_unset(self, guild_id: int, key: str) -> bool:
        assert self.db is not None
        # await self._ensure_db()
        cur = await self.db.execute("DELETE FROM tenant_config WHERE guild_id=? AND key=?", (guild_id, key))
        await self.db.commit()
        return cur.rowcount > 0

    async def config_list(self, guild_id: int) -> List[Tuple[str, str, int]]:
        assert self.db is not None
        # await self._ensure_db()
        async with self.db.execute("SELECT key, value, updated_at FROM tenant_config WHERE guild_id=? ORDER BY key ASC", (guild_id,)) as cur:
            rows = await cur.fetchall()
            return [(r[0], r[1], int(r[2])) for r in rows]
