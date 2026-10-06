"""FastAPI application factory. Every route requires the per-launch token."""

import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated, Any
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from localjobtracker.claude_job_queue import ClaudeJobQueue, PromptRejected
from localjobtracker.claude_jobs import (
    ClaudeJob,
    get_claude_job,
    list_claude_jobs,
    recover_interrupted,
)
from localjobtracker.job_applications import JobApplication, list_job_applications
from localjobtracker.profile_facts import (
    Fact,
    FactError,
    FactSheet,
    FactUpdate,
    fact_sheet,
    update_fact,
)
from localjobtracker.profile_files import (
    ProfileFile,
    ProfileFileText,
    ProfileUploadError,
    list_profile_files,
    profile_file_text,
    store_profile_file,
)
from localjobtracker.profile_pipeline import (
    ProfileBusy,
    ProfileNotReady,
    ProfileOutput,
    list_latest_outputs,
    make_pipeline,
    save_user_version,
    submit_profile_analysis,
)
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
    render, on_result = make_pipeline()
    queue = ClaudeJobQueue(db_path, runner, on_result=on_result, render=render)

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
        # FastAPI may set this dependency up and close it on different worker threads. The
        # connection serves one request, so it is safe to let it cross threads.
        conn = connect(db_path, check_same_thread=False)
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

    @app.get(
        "/profile/files",
        response_model=list[ProfileFile],
        dependencies=[Depends(require_token)],
    )
    def profile_files(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileFile]:
        return list_profile_files(conn)

    @app.get(
        "/profile/files/{file_id}/text",
        response_model=ProfileFileText,
        dependencies=[Depends(require_token)],
    )
    def profile_file_text_route(
        file_id: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> ProfileFileText:
        text = profile_file_text(conn, file_id)
        if text is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return text

    @app.get(
        "/profile/facts",
        response_model=FactSheet,
        dependencies=[Depends(require_token)],
    )
    def profile_facts(conn: Annotated[Connection, Depends(get_db)]) -> FactSheet:
        return fact_sheet(conn)

    @app.patch(
        "/profile/facts/{fact_id}",
        response_model=Fact,
        dependencies=[Depends(require_token)],
    )
    def patch_profile_fact(
        fact_id: int, change: FactUpdate, conn: Annotated[Connection, Depends(get_db)]
    ) -> Fact:
        try:
            return update_fact(conn, fact_id, change)
        except FactError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error

    @app.get(
        "/profile/outputs",
        response_model=list[ProfileOutput],
        dependencies=[Depends(require_token)],
    )
    def profile_outputs(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileOutput]:
        return list_latest_outputs(conn)

    @app.put(
        "/profile/outputs/{kind}",
        response_model=ProfileOutput,
        dependencies=[Depends(require_token)],
    )
    def save_profile_output(
        kind: str, body: dict[str, Any], conn: Annotated[Connection, Depends(get_db)]
    ) -> ProfileOutput:
        try:
            return save_user_version(conn, kind, body)
        except PromptRejected as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error

    @app.post(
        "/profile/analysis",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def start_profile_analysis(conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        try:
            job_id = submit_profile_analysis(conn, queue)
        except ProfileNotReady as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
            ) from error
        except ProfileBusy as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        return _job_or_404(conn, job_id)

    @app.post(
        "/profile/files/{kind}",
        response_model=ProfileFile,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    async def upload_profile_file(kind: str, request: Request) -> ProfileFile:
        # The body is the file's bytes. Its name comes in a header, URL-encoded. The request
        # is async, so it opens its own connection: a SQLite connection must stay in one thread.
        name = unquote(request.headers.get("X-File-Name", ""))
        content = await request.body()
        conn = connect(db_path)
        try:
            return store_profile_file(conn, db_path.parent, kind, name, content)
        except ProfileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        finally:
            conn.close()

    return app


def _job_or_404(conn: Connection, job_id: int) -> ClaudeJob:
    job = get_claude_job(conn, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return job
