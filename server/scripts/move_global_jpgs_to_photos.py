import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.db import db_get_or_create_project, db_list_global_files, db_move_file_scope  # noqa: E402


TARGET_PROJECT_NAME = "Photos"
TARGET_EXTENSIONS = {".jpg", ".jpeg"}
TARGET_MIME_TYPES = {"image/jpeg"}


def is_target_file(file_row: dict) -> bool:
    name = str(file_row.get("name") or "").strip().lower()
    mime_type = str(file_row.get("mime_type") or "").strip().lower()
    suffix = Path(name).suffix.lower()
    return suffix in TARGET_EXTENSIONS or mime_type in TARGET_MIME_TYPES


def main() -> None:
    ap = argparse.ArgumentParser(
        description='Create/update a project named "Photos" and move global JPG/JPEG files into it.'
    )
    ap.add_argument("--dry-run", action="store_true", help="Show what would move without changing anything.")
    ap.add_argument("--limit", type=int, default=None, help="Only move up to this many matching files.")
    args = ap.parse_args()

    files = [f for f in db_list_global_files() if is_target_file(f)]
    files.sort(key=lambda f: (str(f.get("name") or "").lower(), str(f.get("id") or "")))

    if args.limit is not None:
        files = files[: args.limit]

    print(f"Found {len(files)} matching global JPG/JPEG file(s).")

    if not files:
        return

    project = db_get_or_create_project(TARGET_PROJECT_NAME, visibility="private")
    print(f'Target project: {project["name"]} (id={project["id"]})')

    moved = 0
    failed = 0

    for i, file_row in enumerate(files, start=1):
        file_id = str(file_row.get("id") or "").strip()
        name = str(file_row.get("name") or file_id)
        mime_type = str(file_row.get("mime_type") or "")
        print(f"[{i}/{len(files)}] {name} ({mime_type or 'unknown MIME'})")

        if args.dry_run:
            continue

        try:
            out = db_move_file_scope(
                file_id,
                scope_type="project",
                scope_id=int(project["id"]),
            )
            moved += 1
            print(
                f"    moved: {out.get('old_scope_type')} -> {out.get('scope_type')} "
                f"(scope_id={out.get('scope_id')})"
            )
        except Exception as e:
            failed += 1
            print(f"    FAIL: {e!r}")

    if args.dry_run:
        print("Dry run only. No files were moved.")
    else:
        print(f"Done. moved={moved} failed={failed}")


if __name__ == "__main__":
    main()
