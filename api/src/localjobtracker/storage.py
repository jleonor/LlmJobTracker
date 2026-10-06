r"""Where the app keeps its data, and how it connects to SQLite.

The data folder is %LOCALAPPDATA%\LocalJobTracker (D-18). LJT_DATA_DIR overrides it, so
tests and development runs can use a temporary folder.
"""

import os
import sqlite3
from pathlib import Path

DATA_DIR_ENV = "LJT_DATA_DIR"
DB_FILE_NAME = "tracker.db"


def data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base / "LocalJobTracker"


def database_path(folder: Path) -> Path:
    return folder / DB_FILE_NAME


def connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
