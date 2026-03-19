from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.artifact_derivative_builder import ensure_artifact_reading_derivatives
from server.db import db_session, init_schema


def _iter_target_artifacts(*, min_chars: int, limit: int | None, artifact_ids: list[str]) -> list[dict]:
    aids = [a.strip() for a in artifact_ids if a.strip()]
    with db_session() as conn:
        if aids:
            placeholders = ",".join("?" for _ in aids)
            rows = conn.execute(
                f"""
                SELECT id, title, source_kind, LENGTH(COALESCE(content_text, '')) AS content_chars
                FROM artifacts
                WHERE is_deleted = 0
                  AND id IN ({placeholders})
                ORDER BY id ASC
                """,
                tuple(aids),
            ).fetchall()
            return [dict(r) for r in rows]

        params: list[object] = [max(0, int(min_chars or 0))]
        sql = """
            SELECT id, title, source_kind, LENGTH(COALESCE(content_text, '')) AS content_chars
            FROM artifacts
            WHERE is_deleted = 0
              AND LENGTH(COALESCE(content_text, '')) >= ?
            ORDER BY content_chars DESC, id ASC
        """
        if limit and int(limit) > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        rows = conn.execute(sql, tuple(params)).fetchall()
        return [dict(r) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact-id", action="append", default=[])
    ap.add_argument("--min-chars", type=int, default=4000)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clear-invalid", action="store_true")
    args = ap.parse_args()

    init_schema()

    rows = _iter_target_artifacts(
        min_chars=args.min_chars,
        limit=(args.limit or None),
        artifact_ids=args.artifact_id,
    )
    print(f"Target artifacts: {len(rows)}")

    ok = 0
    failed = 0
    no_summary = 0
    no_index = 0

    for idx, row in enumerate(rows, start=1):
        aid = str(row["id"])
        title = (row.get("title") or aid).strip()
        try:
            readiness = ensure_artifact_reading_derivatives(
                aid,
                force=bool(args.force),
                clear_invalid=bool(args.clear_invalid),
            )
            if readiness is None:
                print(f"[{idx}/{len(rows)}] SKIP {aid} :: missing artifact")
                continue

            if not readiness.has_summary:
                no_summary += 1
            if not readiness.has_index:
                no_index += 1

            print(
                f"[{idx}/{len(rows)}] OK {aid} :: {title[:80]} :: "
                f"summary={readiness.has_summary} index={readiness.has_index} chars={readiness.content_chars}"
            )
            ok += 1
        except Exception as e:
            failed += 1
            print(f"[{idx}/{len(rows)}] FAIL {aid} :: {title[:80]} :: {type(e).__name__}: {e}")

    summary = {
        "targets": len(rows),
        "ok": ok,
        "failed": failed,
        "without_summary": no_summary,
        "without_index": no_index,
        "force": bool(args.force),
        "clear_invalid": bool(args.clear_invalid),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
