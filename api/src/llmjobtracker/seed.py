"""Load synthetic Job Applications into an empty database.

Run with: uv run python -m llmjobtracker.seed
Refuses to add rows to a database that already has applications, so running it twice is safe.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from llmjobtracker.job_applications import count_job_applications, insert_job_application
from llmjobtracker.migrations import migrate
from llmjobtracker.storage import connect, data_dir, database_path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "synthetic" / "job_applications.json"


def load_fixture(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load synthetic applications into an empty database."
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--db", type=Path, default=None, help="defaults to the app database")
    args = parser.parse_args()

    db_path = args.db or database_path(data_dir())
    conn = connect(db_path)
    try:
        migrate(conn)
        existing = count_job_applications(conn)
        if existing:
            print(f"skipped: {existing} job applications already in {db_path}")
            return
        rows = load_fixture(args.fixture)
        for row in rows:
            history = [(step["status"], step["changed_at"]) for step in row.pop("history")]
            insert_job_application(conn, row, history)
        print(f"added {len(rows)} synthetic job applications to {db_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
