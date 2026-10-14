"""App settings: the user's display name, and Phase 7's backend/retry-policy choices.

One row, always id 1 (migration 12, widened by migration 23). There is nothing to create or
delete, only read and save.
"""

import sqlite3

from pydantic import BaseModel

from llmjobtracker.migrations import RETRY_POLICIES, RUNNER_BACKENDS

DEFAULT_USER_NAME = "YourName"
DEFAULT_BACKEND = "claude_code"
DEFAULT_RETRY_POLICY = "reset_time"
DEFAULT_RETRY_INTERVAL_MINUTES = 60
DEFAULT_RETRY_MAX_ATTEMPTS = 24


class Settings(BaseModel):
    user_name: str
    # D-195: one global backend for the whole app, not per-job-kind.
    backend: str
    # D-201: which mode the queue uses when a run hits a rate limit.
    retry_policy: str
    retry_interval_minutes: int
    retry_max_attempts: int


def get_settings(conn: sqlite3.Connection) -> Settings:
    row = conn.execute(
        "SELECT user_name, backend, retry_policy, retry_interval_minutes, retry_max_attempts "
        "FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return Settings(
            user_name=DEFAULT_USER_NAME,
            backend=DEFAULT_BACKEND,
            retry_policy=DEFAULT_RETRY_POLICY,
            retry_interval_minutes=DEFAULT_RETRY_INTERVAL_MINUTES,
            retry_max_attempts=DEFAULT_RETRY_MAX_ATTEMPTS,
        )
    return Settings(**dict(row))


def save_settings(
    conn: sqlite3.Connection,
    user_name: str,
    backend: str,
    retry_policy: str,
    retry_interval_minutes: int,
    retry_max_attempts: int,
) -> Settings:
    name = user_name.strip() or DEFAULT_USER_NAME
    if backend not in RUNNER_BACKENDS:
        raise ValueError(f"Unknown backend: {backend!r}")
    if retry_policy not in RETRY_POLICIES:
        raise ValueError(f"Unknown retry policy: {retry_policy!r}")
    if retry_interval_minutes <= 0:
        raise ValueError("retry_interval_minutes must be positive")
    if retry_max_attempts <= 0:
        raise ValueError("retry_max_attempts must be positive")
    with conn:
        conn.execute(
            "UPDATE settings SET user_name = ?, backend = ?, retry_policy = ?, "
            "retry_interval_minutes = ?, retry_max_attempts = ? WHERE id = 1",
            (name, backend, retry_policy, retry_interval_minutes, retry_max_attempts),
        )
    return Settings(
        user_name=name,
        backend=backend,
        retry_policy=retry_policy,
        retry_interval_minutes=retry_interval_minutes,
        retry_max_attempts=retry_max_attempts,
    )
