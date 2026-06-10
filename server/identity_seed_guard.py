# server/identity_seed_guard.py
"""Guarded bootstrap defaults for identity tables.

The original identity bootstrap was useful during the first pass, but it kept
reasserting a specific local-user/local tenant/callie shape on every startup.
This patch replaces that behavior with create-only-if-empty defaults.
"""

from __future__ import annotations

import sqlite3

from .db_helpers import new_uuid, _utc_now_iso

_DEFAULT_ADMIN_SLUG = "@global-admin"
_DEFAULT_ADMIN_NAME = "Admin"
_DEFAULT_TENANT_NAME = "Local"
_DEFAULT_PERSONA_NAME = "Admin"
_DEFAULT_PERSONA_SLUG = "@global-admin"

_INSTALLED = False


def guarded_seed_defaults(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()

    tenant_count = conn.execute("SELECT COUNT(*) AS n FROM tenants").fetchone()["n"]
    tenant_id = None
    if int(tenant_count or 0) == 0:
        cur = conn.execute(
            "INSERT INTO tenants(uuid,name,kind,source_system,external_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (new_uuid(), _DEFAULT_TENANT_NAME, "local", "wyrmgpt", "local", now, now),
        )
        tenant_id = int(cur.lastrowid)
    else:
        row = conn.execute("SELECT id FROM tenants ORDER BY id LIMIT 1").fetchone()
        tenant_id = int(row["id"]) if row else None

    user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if int(user_count or 0) == 0:
        conn.execute(
            """
            INSERT INTO users(uuid,display_name,handle,slug,is_global,is_global_admin,role,tenant_id,created_at,updated_at,meta_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                new_uuid(),
                _DEFAULT_ADMIN_NAME,
                _DEFAULT_ADMIN_SLUG,
                _DEFAULT_ADMIN_SLUG,
                1,
                1,
                "global_admin",
                None,
                now,
                now,
                '{"system_default":true,"protected":true}',
            ),
        )

    persona_count = conn.execute("SELECT COUNT(*) AS n FROM chat_personas").fetchone()["n"]
    if int(persona_count or 0) == 0:
        conn.execute(
            """
            INSERT INTO chat_personas(uuid,tenant_id,name,slug,description,created_at,updated_at,meta_json)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                new_uuid(),
                tenant_id,
                _DEFAULT_PERSONA_NAME,
                _DEFAULT_PERSONA_SLUG,
                "Default WyrmGPT administrative persona.",
                now,
                now,
                '{"system_default":true,"protected":true}',
            ),
        )


def install_identity_seed_patch() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    import server.identity_db as identity_db
    identity_db._seed_defaults = guarded_seed_defaults
    _INSTALLED = True
