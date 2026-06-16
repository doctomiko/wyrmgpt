# server/user_profiles.py
"""Per-user About You profile storage.

This intentionally uses the existing user_profiles table instead of global
memory_pins. The first bootstrap clones the legacy global About You pin to all
existing users so the transition is non-destructive.
"""

from __future__ import annotations

import json
from typing import Any

from .db_helpers import db_session, _add_column_if_missing, _utc_now_iso

_PROFILE_KIND = "about_you"


def _compose_about_text(value: dict[str, Any]) -> str:
    parts: list[str] = []
    if value.get("nickname"):
        parts.append(f"Nickname: {value.get('nickname')}")
    if value.get("age"):
        parts.append(f"Approximate age: {value.get('age')}")
    if value.get("occupation"):
        parts.append(f"Occupation: {value.get('occupation')}")
    if value.get("more_about_you"):
        parts.append(f"More about you: {value.get('more_about_you')}")
    return "\n".join(parts).strip()


def _empty_profile(user_id: int | None = None) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "nickname": "",
        "age": "",
        "occupation": "",
        "more_about_you": "",
        "text": "",
    }


def _decode(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ensure_user_profile_schema() -> None:
    with db_session() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER,
                user_id INTEGER NOT NULL,
                profile_kind TEXT NOT NULL DEFAULT 'about_me',
                title TEXT,
                content_text TEXT NOT NULL,
                visibility TEXT NOT NULL DEFAULT 'tenant',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                meta_json TEXT
            )
            """
        )
        _add_column_if_missing(conn, "user_profiles", "value_json", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_user_kind ON user_profiles(user_id, profile_kind)")
        _clone_legacy_about_you_to_users_conn(conn)


def _legacy_about_you_conn(conn) -> dict[str, Any] | None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_pins'").fetchone():
        return None
    row = conn.execute(
        """
        SELECT value_json, text
        FROM memory_pins
        WHERE pin_kind='profile' AND title='about_you'
        ORDER BY id ASC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    value = _decode(row["value_json"])
    if not value and row["text"]:
        value = {"more_about_you": row["text"]}
    text = row["text"] or _compose_about_text(value)
    if not value and not text:
        return None
    value.setdefault("text", text)
    return value


def _clone_legacy_about_you_to_users_conn(conn) -> None:
    legacy = _legacy_about_you_conn(conn)
    if not legacy:
        return
    users = conn.execute("SELECT id, tenant_id FROM users").fetchall() if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'").fetchone() else []
    now = _utc_now_iso()
    for user in users:
        exists = conn.execute(
            "SELECT 1 FROM user_profiles WHERE user_id=? AND profile_kind=? LIMIT 1",
            (int(user["id"]), _PROFILE_KIND),
        ).fetchone()
        if exists:
            continue
        value = {k: legacy.get(k, "") for k in ("nickname", "age", "occupation", "more_about_you")}
        text = legacy.get("text") or _compose_about_text(value)
        conn.execute(
            """
            INSERT INTO user_profiles(tenant_id,user_id,profile_kind,title,content_text,visibility,created_at,updated_at,meta_json,value_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (user["tenant_id"], int(user["id"]), _PROFILE_KIND, "About You", text, "user", now, now, None, json.dumps(value, ensure_ascii=False)),
        )


def get_user_about_you(user_id: int | None) -> dict[str, Any]:
    ensure_user_profile_schema()
    if user_id is None:
        return _empty_profile(None)
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT * FROM user_profiles
            WHERE user_id=? AND profile_kind=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(user_id), _PROFILE_KIND),
        ).fetchone()
    if not row:
        return _empty_profile(int(user_id))
    value = _decode(row["value_json"])
    return {
        "id": row["id"],
        "user_id": int(user_id),
        "tenant_id": row["tenant_id"],
        "nickname": value.get("nickname", ""),
        "age": value.get("age", ""),
        "occupation": value.get("occupation", ""),
        "more_about_you": value.get("more_about_you", ""),
        "text": row["content_text"] or _compose_about_text(value),
        "updated_at": row["updated_at"],
    }


def upsert_user_about_you(user_id: int, value: dict[str, Any], *, tenant_id: int | None = None) -> dict[str, Any]:
    ensure_user_profile_schema()
    clean = {
        "nickname": str(value.get("nickname") or "").strip(),
        "age": str(value.get("age") or "").strip(),
        "occupation": str(value.get("occupation") or "").strip(),
        "more_about_you": str(value.get("more_about_you") or "").strip(),
    }
    text = _compose_about_text(clean)
    now = _utc_now_iso()
    with db_session() as conn:
        if tenant_id is None:
            u = conn.execute("SELECT tenant_id FROM users WHERE id=?", (int(user_id),)).fetchone()
            tenant_id = u["tenant_id"] if u else None
        row = conn.execute(
            "SELECT id FROM user_profiles WHERE user_id=? AND profile_kind=? ORDER BY id DESC LIMIT 1",
            (int(user_id), _PROFILE_KIND),
        ).fetchone()
        if row:
            conn.execute(
                """
                UPDATE user_profiles
                SET tenant_id=?, content_text=?, updated_at=?, value_json=?
                WHERE id=?
                """,
                (tenant_id, text, now, json.dumps(clean, ensure_ascii=False), int(row["id"])),
            )
        else:
            conn.execute(
                """
                INSERT INTO user_profiles(tenant_id,user_id,profile_kind,title,content_text,visibility,created_at,updated_at,meta_json,value_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (tenant_id, int(user_id), _PROFILE_KIND, "About You", text, "user", now, now, None, json.dumps(clean, ensure_ascii=False)),
            )
    return get_user_about_you(int(user_id))
