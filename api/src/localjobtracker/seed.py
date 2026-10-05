"""Load synthetic jobs into an empty database. Run with: uv run python -m localjobtracker.seed

Refuses to add rows to a database that already has jobs, so running it twice is safe.
"""

import argparse
import json
from pathlib import Path

from localjobtracker.jobs import count_jobs, insert_jobs
from localjobtracker.migrations import migrate
from localjobtracker.storage import connect, data_dir, database_path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "jobs.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Load synthetic jobs into an empty database.")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--db", type=Path, default=None, help="defaults to the app database")
    args = parser.parse_args()

    db_path = args.db or database_path(data_dir())
    conn = connect(db_path)
    try:
        migrate(conn)
        existing = count_jobs(conn)
        if existing:
            print(f"skipped: {existing} jobs already in {db_path}")
            return
        rows = json.loads(args.fixture.read_text(encoding="utf-8"))
        added = insert_jobs(conn, rows)
        print(f"added {added} synthetic jobs to {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
