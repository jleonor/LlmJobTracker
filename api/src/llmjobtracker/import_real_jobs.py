"""Import a hand-picked list of real Job Applications and their files.

Not the Phase 3 spreadsheet import (that reads the whole tracker and is still unbuilt) - this is
for adding a few real rows by hand, from a data file you point it at, while that's being built.

Usage: uv run python -m llmjobtracker.import_real_jobs --data <path to a JSON file>

The JSON file is a list of objects, each shaped like:

    {
      "company": "...", "role_title": "...", "lane": "...", "location": "...",
      "work_mode": "Onsite", "contract_type": "Unknown",
      "portal_name": "...", "portal_url": null,
      "description": "...", "requirements": ["...", "..."], "notes": null,
      "history": [["Identified", "2026-09-29T00:00:00Z"], ["Applied", "2026-10-01T12:03:00Z"]],
      "files": [
        {"kind": "listing", "source": "C:\\...\\Job Listing.pdf"},
        {"kind": "eml", "source": "C:\\...\\Confirmation.eml", "date": "2026-10-01T12:03:00Z"}
      ]
    }

`source` is an absolute path to the real file to copy; its own name is kept as `job_files.name`.
This file is never committed to the repo (D-85's "no personal data in the repo" rule, CLAUDE.md
rule 2) - keep it in a scratch location outside the project.

A company+role_title already in the database is skipped, so the file is safe to re-run after
fixing a mistake in a later row.
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from llmjobtracker.extraction import extract
from llmjobtracker.job_applications import insert_job_application
from llmjobtracker.job_files import EXTRACTED_KINDS, insert_job_file, managed_folder
from llmjobtracker.migrations import migrate
from llmjobtracker.storage import connect, data_dir, database_path


def _already_imported(conn: sqlite3.Connection, company: str, role_title: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM job_applications WHERE company = ? AND role_title = ?",
        (company, role_title),
    ).fetchone()
    return row is not None


def import_job(conn: sqlite3.Connection, files_root: Path, job: dict[str, Any]) -> None:
    company = job["company"]
    role_title = job["role_title"]
    if _already_imported(conn, company, role_title):
        print(f"skipped (already imported): {company} - {role_title}")
        return

    history = [(status, changed_at) for status, changed_at in job.get("history", [])]
    app_id = insert_job_application(
        conn,
        {
            "company": company,
            "role_title": role_title,
            "lane": job.get("lane"),
            "location": job.get("location"),
            "work_mode": job.get("work_mode", "Unknown"),
            "contract_type": job.get("contract_type", "Unknown"),
            "portal_name": job.get("portal_name"),
            "portal_url": job.get("portal_url"),
            "description": job.get("description"),
            "requirements": job.get("requirements", []),
            "notes": job.get("notes"),
        },
        history=history or None,
    )

    folder = managed_folder(files_root, company, role_title)
    folder.mkdir(parents=True, exist_ok=True)
    for file_entry in job.get("files", []):
        source = Path(file_entry["source"])
        destination = folder / source.name
        shutil.copyfile(source, destination)
        kind = file_entry["kind"]
        sha256 = extraction_status = extraction_message = extracted_text = None
        if kind in EXTRACTED_KINDS:
            content = destination.read_bytes()
            sha256 = hashlib.sha256(content).hexdigest()
            result = extract(destination)
            extraction_status, extraction_message, extracted_text = (
                result.status,
                result.message,
                result.text,
            )
        insert_job_file(
            conn,
            app_id,
            kind=kind,
            name=source.name,
            stored_path=str(destination.relative_to(files_root)),
            date=file_entry.get("date"),
            sha256=sha256,
            extraction_status=extraction_status,
            extraction_message=extraction_message,
            extracted_text=extracted_text,
        )
    conn.commit()
    print(f"imported: {company} - {role_title} ({len(job.get('files', []))} file(s))")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="path to the JSON data file")
    parser.add_argument("--db", type=Path, default=None, help="defaults to the app database")
    parser.add_argument(
        "--files-root", type=Path, default=None, help="defaults to <data dir>/files"
    )
    args = parser.parse_args()

    root = args.files_root or (data_dir() / "files")
    db_path = args.db or database_path(data_dir())
    jobs = json.loads(args.data.read_text(encoding="utf-8"))

    conn = connect(db_path)
    try:
        migrate(conn)
        for job in jobs:
            import_job(conn, root, job)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
