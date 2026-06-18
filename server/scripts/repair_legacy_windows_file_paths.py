#!/usr/bin/env python3
"""Rewrite legacy Windows WyrmGPT file paths to the current data root."""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.db_helpers import DATA_DIR, DB_PATH  # noqa: E402


WINDOWS_DATA_RE = re.compile(
    r"^[A-Za-z]:[/\\].*?[/\\]wyrmgpt[/\\]data[/\\](?P<rel>.+)$",
    re.IGNORECASE,
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _safe_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _clean_legacy_prefix(prefix: str) -> str:
    return prefix.strip().replace("\\", "/").rstrip("/").lower()


def _relative_from_legacy_path(raw_path: str, legacy_prefixes: list[str]) -> str | None:
    raw = (raw_path or "").strip()
    if not raw:
        return None

    normalized = raw.replace("\\", "/")
    lowered = normalized.lower()

    for prefix in legacy_prefixes:
        cleaned = _clean_legacy_prefix(prefix)
        if cleaned and lowered.startswith(cleaned + "/"):
            return normalized[len(cleaned) + 1 :].lstrip("/")

    match = WINDOWS_DATA_RE.match(raw)
    if match:
        return match.group("rel").replace("\\", "/").lstrip("/")

    return None


def _target_path(data_root: Path, relative_path: str) -> Path:
    parts = [part for part in relative_path.replace("\\", "/").split("/") if part and part != "."]
    return data_root.joinpath(*parts)


def _iter_candidate_rows(conn: sqlite3.Connection, file_id: str | None = None, limit: int | None = None) -> list[sqlite3.Row]:
    where = "WHERE path IS NOT NULL AND TRIM(path) <> ''"
    params: list[object] = []
    if file_id:
        where += " AND id = ?"
        params.append(file_id)
    sql = f"""
        SELECT id, name, path
        FROM files
        {where}
        ORDER BY id
    """
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    return conn.execute(sql, tuple(params)).fetchall()


def repair_paths(args: argparse.Namespace) -> int:
    db_path = args.db.expanduser().resolve()
    data_root = args.data_root.expanduser().resolve()
    legacy_prefixes = args.legacy_prefix or [
        r"M:\RunPortable\wyrmgpt\data",
        r"M:/RunPortable/wyrmgpt/data",
    ]

    conn = _connect(db_path)
    rows = _iter_candidate_rows(conn, file_id=args.file_id, limit=args.limit)

    matched = 0
    exists = 0
    missing = 0
    unchanged = 0
    updated = 0
    skipped = 0

    print(f"DB: {db_path}")
    print(f"Data root: {data_root}")
    print(f"Mode: {'APPLY' if args.apply else 'dry-run'}")

    for row in rows:
        raw_path = row["path"] or ""
        rel = _relative_from_legacy_path(raw_path, legacy_prefixes)
        if not rel:
            continue
        matched += 1
        target = _target_path(data_root, rel)
        target_text = str(target)
        target_exists = _safe_exists(target)
        if target_exists:
            exists += 1
        else:
            missing += 1

        if target_text == raw_path:
            unchanged += 1
            continue

        should_update = args.allow_missing or target_exists
        action = "update" if should_update else "skip-missing"
        if args.verbose or action != "update":
            print(f"{action}: {row['id']} {row['name'] or ''}")
            print(f"  old: {raw_path}")
            print(f"  new: {target_text}")
            print(f"  exists: {target_exists}")

        if not should_update:
            skipped += 1
            continue

        if args.apply:
            conn.execute("UPDATE files SET path = ? WHERE id = ?", (target_text, row["id"]))
        updated += 1

    if args.apply and updated:
        conn.commit()
    else:
        conn.rollback()

    print(
        "Summary: "
        f"scanned={len(rows)} matched={matched} existing_targets={exists} "
        f"missing_targets={missing} updated={'would_update' if not args.apply else 'updated'}:{updated} "
        f"unchanged={unchanged} skipped={skipped}"
    )
    if not args.apply and matched:
        print("Dry run only. Re-run with --apply to update rows.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Repair legacy Windows WyrmGPT file paths, e.g. M:\\RunPortable\\wyrmgpt\\data\\... -> DATA_ROOT/...",
    )
    parser.add_argument("--db", type=Path, default=DB_PATH, help=f"SQLite DB path. Default: {DB_PATH}")
    parser.add_argument("--data-root", type=Path, default=DATA_DIR, help=f"Current WyrmGPT data root. Default: {DATA_DIR}")
    parser.add_argument("--legacy-prefix", action="append", help="Legacy data prefix to replace. Can be passed more than once.")
    parser.add_argument("--file-id", help="Repair only one files.id value.")
    parser.add_argument("--limit", type=int, help="Limit scanned rows for a cautious first pass.")
    parser.add_argument("--allow-missing", action="store_true", help="Update even when the computed target path does not exist.")
    parser.add_argument("--apply", action="store_true", help="Actually write changes. Without this, only prints a dry-run summary.")
    parser.add_argument("--verbose", action="store_true", help="Print every candidate update, not only skipped rows.")
    return parser


def main(argv: list[str] | None = None) -> int:
    return repair_paths(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
