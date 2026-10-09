"""CLI entry point for seeding MongoDB collections.

Owner: Member 1 (Data & MongoDB)
Run:
    python -m scripts.seed_db [--drop] [--data-dir PATH]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from anvesaka_AI.db.mongo import check_db_connection
from anvesaka_AI.db.seed import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed MongoDB with raw alerts, playbook, and nodes.")
    parser.add_argument("--data-dir", default=None, help="Directory containing raw JSON files")
    parser.add_argument("--drop", action="store_true", help="Drop collections before seeding")
    args = parser.parse_args()

    print("Checking MongoDB connectivity...")
    ok, err_msg = check_db_connection()
    if not ok:
        print(f"ERROR: Could not connect to MongoDB: {err_msg}")
        print("Tip: If using MongoDB Atlas, check your username, password (without < >), and Network Access IP whitelist.")
        sys.exit(1)


    print(f"Connected. Seeding database{' (with collection drop)' if args.drop else ''}...")
    try:
        counts = seed_database(data_dir=Path(args.data_dir) if args.data_dir else None, drop_first=args.drop)
        print(f"Successfully seeded MongoDB:")
        print(f"  - Alerts:    {counts['alerts']}")
        print(f"  - Playbook:  {counts['playbook']}")
        print(f"  - Nodes:     {counts['nodes']}")
        print(f"  - Scenarios: {counts.get('scenarios', 0)}")
    except Exception as e:

        print(f"ERROR: Seeding failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
