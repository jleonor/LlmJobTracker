"""FastAPI application factory. Every route requires the per-launch token."""

import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from localjobtracker.claude_job_queue import ClaudeJobQueue
from localjobtracker.claude_jobs import (
    ClaudeJob,
    get_claude_job,
    list_claude_jobs,
    recover_interrupted,
)
from localjobtracker.job_applications import JobApplication, list_job_applications
from localjobtracker.runner import Runner, RunResult
from localjobtracker.storage import connect

# The one prompt the Phase 1 button sends. It contains no personal data.
CHECK_PROMPT = "Reply with the single word OK."

TOKEN_HEADER = "X-Launch-Token"


def create_app(
    launch_token: str, db_path: Path, runner: Runner, *, run_worker: bool = False
) -> FastAPI:
    """Build the app. Requests must send `launch_token` in the X-Launch-Token header.

    `run_worker` starts the Claude Jobs worker with the app. Tests leave it off and step the
    queue themselves (ClaudeJobQueue.process_next), so the results are repeatable.
    """
    queue = ClaudeJobQueue(db_path, runner)

    # A stopped worker can leave jobs half done. Put them back in the queue (D-62).
    startup_conn = connect(db_path)
    try:
        recover_interrupted(startup_conn)
    finally:
        startup_conn.close()

    def require_token(x_launch_token: str | None = Header(default=None)) -> None:
        if x_launch_token is None or not secrets.compare_digest(x_launch_token, launch_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    def get_db() -> Iterator[Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if run_worker:
            queue.start()
        yield
        queue.stop()

    app = FastAPI(
        title="LocalJobTracker",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.queue = queue

    @app.get("/health", dependencies=[Depends(require_token)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/job-applications",
        response_model=list[JobApplication],
        dependencies=[Depends(require_token)],
    )
    def job_applications(
        conn: Annotated[Connection, Depends(get_db)],
    ) -> list[JobApplication]:
        return list_job_applications(conn)

    @app.post("/runs/check", response_model=RunResult, dependencies=[Depends(require_token)])
    def run_check() -> RunResult:
        return runner.run(CHECK_PROMPT)

    @app.get("/claude-jobs", response_model=list[ClaudeJob], dependencies=[Depends(require_token)])
    def claude_jobs(conn: Annotated[Connection, Depends(get_db)]) -> list[ClaudeJob]:
        return list_claude_jobs(conn)

    @app.post(
        "/claude-jobs/{job_id}/resume",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def resume_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.resume(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not paused.")
        return _job_or_404(conn, job_id)

    @app.post(
        "/claude-jobs/{job_id}/cancel",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def cancel_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.cancel(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already finished.")
        return _job_or_404(conn, job_id)

    return app


def _job_or_404(conn: Connection, job_id: int) -> ClaudeJob:
    job = get_claude_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return job
