"""App settings: currently just the user's display name, shown in the sidebar.

One row, always id 1 (migration 12). There is nothing to create or delete, only read and save.
"""

import sqlite3

from pydantic import BaseModel

DEFAULT_USER_NAME = "YourName"


class Settings(BaseModel):
    user_name: str


def get_settings(conn: sqlite3.Connection) -> Settings:
    row = conn.execute("SELECT user_name FROM settings WHERE id = 1").fetchone()
    return Settings(user_name=row["user_name"] if row else DEFAULT_USER_NAME)


def save_settings(conn: sqlite3.Connection, user_name: str) -> Settings:
    name = user_name.strip() or DEFAULT_USER_NAME
    with conn:
        conn.execute("UPDATE settings SET user_name = ? WHERE id = 1", (name,))
    return Settings(user_name=name)
