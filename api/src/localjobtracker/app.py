"""FastAPI application factory. Every route requires the per-launch token."""

import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated
from urllib.parse import unquote

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from localjobtracker.claude_job_queue import ClaudeJobQueue
from localjobtracker.claude_jobs import (
    ClaudeJob,
    PromptExchange,
    get_claude_job,
    list_claude_jobs,
    prompt_exchange,
    recover_interrupted,
)
from localjobtracker.job_applications import JobApplication, list_job_applications
from localjobtracker.profile_files import (
    ProfileFile,
    ProfileFileText,
    ProfileUploadError,
    delete_profile_file,
    list_profile_files,
    open_in_default_app,
    profile_file_path,
    profile_file_text,
    store_profile_file,
)
from localjobtracker.profile_pipeline import (
    PROMPT_KIND_FOR_OWN,
    ProfileBusy,
    ProfileNotReady,
    ProfileOutput,
    clear_output,
    list_latest_outputs,
    make_pipeline,
    submit_profile_analysis,
)
from localjobtracker.runner import Runner, RunResult
from localjobtracker.settings import Settings, get_settings, save_settings
from localjobtracker.storage import connect

# The one prompt the Phase 1 button sends. It contains no personal data.
CHECK_PROMPT = "Reply with the single word OK."

TOKEN_HEADER = "X-Launch-Token"


class SettingsEdit(BaseModel):
    user_name: str


def create_app(
    launch_token: str, db_path: Path, runner: Runner, *, run_worker: bool = False
) -> FastAPI:
    """Build the app. Requests must send `launch_token` in the X-Launch-Token header.

    `run_worker` starts the Claude Jobs worker with the app. Tests leave it off and step the
    queue themselves (ClaudeJobQueue.process_next), so the results are repeatable.
    """
    render, on_result = make_pipeline(db_path.parent)
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

    @app.get("/settings", response_model=Settings, dependencies=[Depends(require_token)])
    def read_settings(conn: Annotated[Connection, Depends(get_db)]) -> Settings:
        return get_settings(conn)

    @app.put("/settings", response_model=Settings, dependencies=[Depends(require_token)])
    def update_settings(
        edit: SettingsEdit, conn: Annotated[Connection, Depends(get_db)]
    ) -> Settings:
        return save_settings(conn, edit.user_name)

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
        return [_with_live_text(queue, job) for job in list_claude_jobs(conn)]

    @app.post(
        "/claude-jobs/{job_id}/resume",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def resume_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.resume(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Not paused.")
        return _with_live_text(queue, _job_or_404(conn, job_id))

    @app.get(
        "/claude-jobs/{job_id}/prompts/{position}",
        response_model=PromptExchange,
        dependencies=[Depends(require_token)],
    )
    def claude_job_exchange(
        job_id: int, position: int, conn: Annotated[Connection, Depends(get_db)]
    ) -> PromptExchange:
        exchange = prompt_exchange(conn, job_id, position)
        if exchange is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return exchange

    @app.post(
        "/claude-jobs/{job_id}/cancel",
        response_model=ClaudeJob,
        dependencies=[Depends(require_token)],
    )
    def cancel_claude_job(job_id: int, conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        if not queue.cancel(conn, job_id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already finished.")
        return _with_live_text(queue, _job_or_404(conn, job_id))

    @app.get(
        "/profile/files",
        response_model=list[ProfileFile],
        dependencies=[Depends(require_token)],
    )
    def profile_files(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileFile]:
        return list_profile_files(conn)

    @app.post(
        "/profile/files/{file_id}/open",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_token)],
    )
    def open_profile_file(file_id: int, conn: Annotated[Connection, Depends(get_db)]) -> None:
        path = profile_file_path(conn, db_path.parent, file_id)
        if path is None or not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        open_in_default_app(path)

    @app.delete(
        "/profile/files/{file_id}",
        dependencies=[Depends(require_token)],
    )
    def remove_profile_file(file_id: int, conn: Annotated[Connection, Depends(get_db)]) -> None:
        try:
            deleted = delete_profile_file(conn, db_path.parent, file_id)
        except ProfileUploadError as error:
            raise HTTPException(status_code=error.status, detail=error.message) from error
        if deleted.generated:
            # The file was the readable copy of a generated document (D-84). Removing it should
            # remove the document too, not just leave it quietly in place (D-95).
            kind = PROMPT_KIND_FOR_OWN.get(deleted.kind)
            if kind is not None:
                clear_output(conn, kind)

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
        "/profile/outputs",
        response_model=list[ProfileOutput],
        dependencies=[Depends(require_token)],
    )
    def profile_outputs(conn: Annotated[Connection, Depends(get_db)]) -> list[ProfileOutput]:
        return list_latest_outputs(conn)

    @app.post(
        "/profile/analysis",
        response_model=ClaudeJob,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_token)],
    )
    def start_profile_analysis(conn: Annotated[Connection, Depends(get_db)]) -> ClaudeJob:
        try:
            job_id = submit_profile_analysis(conn, queue, db_path.parent)
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


def _with_live_text(queue: ClaudeJobQueue, job: ClaudeJob) -> ClaudeJob:
    """Fill in each running prompt's streamed-so-far text from the queue's live state (D-105)."""
    for prompt in job.prompts:
        if prompt.status == "running":
            prompt.live_text = queue.live_text(job.id, prompt.position)
    return job
