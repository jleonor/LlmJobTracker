"""The full-data export behind "Open LLM app" (D-202, D-210).

Builds one project-shaped folder containing every job's managed files, every profile
document, and a snapshot of the whole database, plus a seed file describing how to read it.
Always rebuilt at the same fixed path under the data folder (never a fresh temp folder), so
the external app only needs to be trusted once (confirmed live: both Claude Desktop and the
ChatGPT desktop app show a one-time folder-trust prompt, not a new one per export).
"""

import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from llmjobtracker.job_applications import list_job_applications
from llmjobtracker.job_files import managed_folder
from llmjobtracker.profile_files import profile_folder
from llmjobtracker.settings import get_settings

EXPORT_FOLDER_NAME: Final = "llm-export"

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


def llm_export_folder(data_folder: Path) -> Path:
    return data_folder / EXPORT_FOLDER_NAME


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
    jobs_root = bundle_root / "jobs"
    for application in list_job_applications(conn):
        source = managed_folder(files_root, application.company, application.role_title)
        if not source.exists():
            continue
        destination = managed_folder(jobs_root, application.company, application.role_title)
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

- `tracker.db` - a SQLite snapshot of the whole database (job applications, status history,
  Claude Job history and cost, settings, model prices). Schema below.
- `profile/` - uploaded and generated profile documents: CVs, older cover letters, the
  questionnaire, writing rules, and the three analysis documents (career history,
  questionnaire analysis, strategy).
- `jobs/<Company>/<Role Title>/` - each application's own files: its listing, tailored CV,
  cover letter, positioning breakdown, and any filed emails.

## Database schema

```sql
{schema}
```
""",
        encoding="utf-8",
    )


def export_llm_bundle(conn: sqlite3.Connection, data_folder: Path) -> Path:
    """Rebuilds the full-data export (D-202) at its fixed path, replacing anything left over
    from a previous export. Returns the bundle's root folder.
    """
    bundle_root = llm_export_folder(data_folder)
    shutil.rmtree(bundle_root, ignore_errors=True)
    bundle_root.mkdir(parents=True)

    _copy_job_files(conn, data_folder, bundle_root)

    source_profile = profile_folder(data_folder)
    if source_profile.exists():
        shutil.copytree(source_profile, bundle_root / "profile")

    # sqlite3's own backup API, not a raw file copy - safe to run against a live connection
    # that may have in-progress writes, unlike shutil.copy2 on the .db file directly.
    destination_conn = sqlite3.connect(bundle_root / "tracker.db")
    try:
        conn.backup(destination_conn)
    finally:
        destination_conn.close()

    _write_seed_file(conn, bundle_root)

    return bundle_root
