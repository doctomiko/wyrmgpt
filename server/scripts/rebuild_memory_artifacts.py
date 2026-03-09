import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from server.db import init_schema, rebuild_memory_artifacts, upsert_memory_artifact

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("memory_id", nargs="?", default=None, help="Optional single memory id to rebuild")
    ap.add_argument("--only-missing", action="store_true", help="Only create artifacts for memories that do not already have one")
    ap.add_argument("--limit", type=int, default=None, help="Limit how many memories to process")
    ap.add_argument("--no-reindex", action="store_true", help="Create/update artifacts but skip chunk reindex")
    ap.add_argument("--yes", action="store_true", help="Skip confirmation prompt for bulk rebuild")
    ap.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = ap.parse_args()

    init_schema()

    if args.memory_id:
        result = upsert_memory_artifact(
            args.memory_id.strip(),
            reindex=not args.no_reindex,
        )
        print(json.dumps(result, indent=2))
        return

    if not args.yes:
        print("")
        print("This will rebuild memory artifacts for existing memories.")
        print("Artifacts are deterministic and safe to refresh.")
        print("")
        resp = input("Type YES to proceed: ").strip()
        if resp != "YES":
            print("Aborted.")
            return

    result = rebuild_memory_artifacts(
        only_missing=args.only_missing,
        limit=args.limit,
        reindex=not args.no_reindex,
    )

    print(json.dumps(result, indent=2) if args.json else json.dumps(result, indent=2))

if __name__ == "__main__":
    main()