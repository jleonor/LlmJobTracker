"""App settings: the user's display name, and Phase 7's backend/retry-policy/model choices.

One row, always id 1 (migration 12, widened by migrations 23, 26 and 27). There is nothing to
create or delete, only read and save.
"""

import sqlite3

from pydantic import BaseModel

from llmjobtracker.migrations import RETRY_POLICIES, RUNNER_BACKENDS

DEFAULT_USER_NAME = "YourName"
DEFAULT_BACKEND = "claude_code"
DEFAULT_RETRY_POLICY = "reset_time"
DEFAULT_RETRY_INTERVAL_MINUTES = 60
DEFAULT_RETRY_MAX_ATTEMPTS = 24
# Mirrors claude_code_runner.MODEL / codex_runner.MODEL - kept here as plain strings rather than
# imported, so this module never needs to know either runner exists (D-20).
DEFAULT_CLAUDE_CODE_MODEL = "claude-sonnet-5"
DEFAULT_CODEX_MODEL = "gpt-6.1-sol"


class Settings(BaseModel):
    user_name: str
    # D-195: one global backend for the whole app, not per-job-kind.
    backend: str
    # D-201: which mode the queue uses when a run hits a rate limit.
    retry_policy: str
    retry_interval_minutes: int
    retry_max_attempts: int
    # D-206: which model each backend uses, selected from that provider's own price table.
    claude_code_model: str
    codex_model: str
    # D-212: where "Open LLM app" rebuilds its export. None means the default (Downloads) -
    # export_llm_bundle.llm_export_folder resolves that, not this module (D-20: this module
    # stays plain settings storage, never knowing what the path is used for).
    llm_export_path: str | None = None


def get_settings(conn: sqlite3.Connection) -> Settings:
    row = conn.execute(
        "SELECT user_name, backend, retry_policy, retry_interval_minutes, retry_max_attempts, "
        "claude_code_model, codex_model, llm_export_path FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return Settings(
            user_name=DEFAULT_USER_NAME,
            backend=DEFAULT_BACKEND,
            retry_policy=DEFAULT_RETRY_POLICY,
            retry_interval_minutes=DEFAULT_RETRY_INTERVAL_MINUTES,
            retry_max_attempts=DEFAULT_RETRY_MAX_ATTEMPTS,
            claude_code_model=DEFAULT_CLAUDE_CODE_MODEL,
            codex_model=DEFAULT_CODEX_MODEL,
            llm_export_path=None,
        )
    return Settings(**dict(row))


def save_settings(
    conn: sqlite3.Connection,
    user_name: str,
    backend: str,
    retry_policy: str,
    retry_interval_minutes: int,
    retry_max_attempts: int,
    claude_code_model: str,
    codex_model: str,
    llm_export_path: str | None,
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
    claude_code_model = claude_code_model.strip()
    codex_model = codex_model.strip()
    if not claude_code_model:
        raise ValueError("claude_code_model cannot be empty")
    if not codex_model:
        raise ValueError("codex_model cannot be empty")
    cleaned_export_path = (llm_export_path or "").strip() or None
    with conn:
        conn.execute(
            "UPDATE settings SET user_name = ?, backend = ?, retry_policy = ?, "
            "retry_interval_minutes = ?, retry_max_attempts = ?, claude_code_model = ?, "
            "codex_model = ?, llm_export_path = ? WHERE id = 1",
            (
                name,
                backend,
                retry_policy,
                retry_interval_minutes,
                retry_max_attempts,
                claude_code_model,
                codex_model,
                cleaned_export_path,
            ),
        )
    return Settings(
        user_name=name,
        backend=backend,
        retry_policy=retry_policy,
        retry_interval_minutes=retry_interval_minutes,
        retry_max_attempts=retry_max_attempts,
        claude_code_model=claude_code_model,
        codex_model=codex_model,
        llm_export_path=cleaned_export_path,
    )
