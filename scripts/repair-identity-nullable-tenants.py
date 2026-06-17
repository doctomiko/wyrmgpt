#!/usr/bin/env python3
"""Repair legacy identity tables whose tenant_id column is NOT NULL."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "db",
        nargs="?",
        default="data/sql/wyrmgpt.sqlite3",
        help="Path to wyrmgpt.sqlite3, default: data/sql/wyrmgpt.sqlite3",
    )
    parser.add_argument("--no-backup", action="store_true", help="Do not create a timestamped backup first.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repo_root()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = root / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 2

    if not args.no_backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = db_path.with_name(f"{db_path.name}.pre-nullable-tenants-{stamp}")
        shutil.copy2(db_path, backup_path)
        print(f"Backup: {backup_path}")

    sys.path.insert(0, str(root))
    from server.db_helpers import ensure_identity_tenant_nullable_schema

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        before = {
            table: [(r["name"], bool(r["notnull"])) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for table in ("users", "user_profiles", "chat_personas")
        }
        ensure_identity_tenant_nullable_schema(conn)
        conn.commit()
        after = {
            table: [(r["name"], bool(r["notnull"])) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for table in ("users", "user_profiles", "chat_personas")
        }
    finally:
        conn.close()

    for table in ("users", "user_profiles", "chat_personas"):
        before_tenant = next((notnull for name, notnull in before[table] if name == "tenant_id"), None)
        after_tenant = next((notnull for name, notnull in after[table] if name == "tenant_id"), None)
        print(f"{table}.tenant_id NOT NULL: {before_tenant} -> {after_tenant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
