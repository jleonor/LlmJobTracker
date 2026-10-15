"""The full-data export behind "Open LLM app" (D-202, D-210, D-212).

Builds one project-shaped folder containing every job's managed files, every profile
document, and a snapshot of the whole database, plus a seed file describing how to read it -
including the database. The folder is user-configurable (Settings' llm_export_path), defaulting
to Downloads so the external app only needs to be trusted once there, not somewhere new on
every export.

Built in a temporary staging folder first, then swapped into place as the last step, so a
failure partway through never leaves the folder you'd actually look at half-wiped (D-212) - the
original approach (wipe the live target, then rebuild it in place) could crash between those
two steps (e.g. a locked file from the folder being open elsewhere) and leave it empty.
"""

import shutil
import sqlite3
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from llmjobtracker.job_applications import list_job_applications
from llmjobtracker.job_files import managed_folder
from llmjobtracker.profile_files import profile_folder
from llmjobtracker.settings import get_settings

DEFAULT_EXPORT_FOLDER_NAME: Final = "LlmJobTrackerExport"

# D-210: the URL scheme each backend's desktop app answers to, mirroring the Settings backend
# names so the frontend can key its own install-status display off the same values it already
# uses everywhere else.
LLM_APP_SCHEMES: Final[dict[str, str]] = {"claude_code": "claude", "codex": "codex"}


class LlmAppStatus(BaseModel):
    """Whether this machine has a handler registered for a backend's desktop-app deep link
    (D-210) - the same thing that determines whether "Open LLM app" actually opens anything,
    mirroring AuthStatus's shape (D-203)."""

    installed: bool
    detail: str


class LlmExportBundleBusy(Exception):
    """Raised when the configured export folder couldn't be replaced - something else (the
    file manager, the LLM app itself) still has a file in it open (D-212)."""


def llm_export_folder(configured_path: str | None) -> Path:
    """Where the export is built: the user's configured path (Settings' llm_export_path) if
    set, otherwise Downloads - a visible, ordinary folder, not the app's own hidden data
    folder, so a first-time user finds it without being told where to look.
    """
    if configured_path:
        return Path(configured_path)
    return Path.home() / "Downloads" / DEFAULT_EXPORT_FOLDER_NAME


def _url_scheme_registered(scheme: str) -> bool:
    """Whether some app on this machine answers to this URL scheme - checked the same way
    Windows itself resolves a claude://... or codex://... link, not by guessing an install
    path. Windows only for now (the registry's own URL Protocol marker, confirmed live
    against both apps - runner-notes.md); elsewhere this can't be checked, so it's assumed
    available rather than wrongly blocking the button.
    """
    if sys.platform != "win32":
        return True
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme) as key:
            winreg.QueryValueEx(key, "URL Protocol")
        return True
    except OSError:
        return False


def llm_app_status() -> dict[str, LlmAppStatus]:
    status: dict[str, LlmAppStatus] = {}
    for backend, scheme in LLM_APP_SCHEMES.items():
        installed = _url_scheme_registered(scheme)
        detail = (
            "Installed."
            if installed
            else "Not installed - the deep link has no handler registered."
        )
        status[backend] = LlmAppStatus(installed=installed, detail=detail)
    return status


def _copy_job_files(conn: sqlite3.Connection, data_folder: Path, bundle_root: Path) -> None:
    files_root = data_folder / "files"
    destination_root = bundle_root / "files"
    for application in list_job_applications(conn):
        source = managed_folder(files_root, application.company, application.role_title)
        if not source.exists():
            continue
        destination = managed_folder(destination_root, application.company, application.role_title)
        if destination.exists():
            # Two applications sharing the same company/role_title already share the same
            # live folder - nothing more to copy once the first one's been handled.
            continue
        shutil.copytree(source, destination)


def _write_seed_file(conn: sqlite3.Connection, bundle_root: Path) -> None:
    user_name = get_settings(conn).user_name
    schema_rows = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL ORDER BY name"
    ).fetchall()
    schema = "\n\n".join(row["sql"] for row in schema_rows)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    (bundle_root / "seed.md").write_text(
        f"""# LlmJobTracker export

This is a read-only snapshot of {user_name}'s job-search tracker, exported on {generated_at}
for you to read. Nothing here is live - nothing you do in this folder changes the real app.

## Folder layout

- `tracker.db` - a snapshot of the whole database (job applications, status history, Claude
  Job history and cost, settings, model prices). How to query it, and the schema, are below.
- `files/<Company>/<Role Title>/` - each application's own files: its listing, tailored CV,
  cover letter, positioning breakdown, and any filed emails.
- `profile/` - uploaded and generated profile documents: CVs, older cover letters, the
  questionnaire, writing rules, and the three analysis documents (career history,
  questionnaire analysis, strategy).

## Querying tracker.db

This is a standard SQLite3 database file - no server, no credentials. Open it with:

- The `sqlite3` command-line tool: `sqlite3 tracker.db "SELECT ...;"`
- Python's built-in `sqlite3` module: `import sqlite3; sqlite3.connect("tracker.db")`
- Any SQLite browser (e.g. DB Browser for SQLite)

A few example queries to start from:

```sql
-- Every application, newest first
SELECT company, role_title, status, match_score FROM job_applications ORDER BY id DESC;

-- Status history for one application
SELECT status, changed_at FROM status_history
WHERE job_application_id = (SELECT id FROM job_applications WHERE company = 'Acme Inc')
ORDER BY changed_at;

-- Every file recorded for one application (paths are relative to this export's files/ folder)
SELECT kind, name, stored_path FROM job_files
WHERE job_application_id = (SELECT id FROM job_applications WHERE company = 'Acme Inc');
```

## Database schema

```sql
{schema}
```
""",
        encoding="utf-8",
    )


def export_llm_bundle(conn: sqlite3.Connection, data_folder: Path) -> Path:
    """Rebuilds the full-data export (D-202) at its configured (or default) path (D-212).
    Builds into a temporary staging folder first, then swaps it into place, so a failure
    partway through never leaves the real target half-wiped. Returns the bundle's root folder.
    """
    target = llm_export_folder(get_settings(conn).llm_export_path)
    staging = Path(tempfile.mkdtemp(prefix="llmjobtracker-export-"))
    try:
        _copy_job_files(conn, data_folder, staging)

        source_profile = profile_folder(data_folder)
        if source_profile.exists():
            shutil.copytree(source_profile, staging / "profile")

        # sqlite3's own backup API, not a raw file copy - safe to run against a live
        # connection that may have in-progress writes, unlike shutil.copy2 on the .db file.
        destination_conn = sqlite3.connect(staging / "tracker.db")
        try:
            conn.backup(destination_conn)
        finally:
            destination_conn.close()

        _write_seed_file(conn, staging)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        if target.exists():
            raise LlmExportBundleBusy(
                f"Could not replace {target} - close any app or file manager that has it "
                "open and try again."
            )
        shutil.move(str(staging), str(target))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target
