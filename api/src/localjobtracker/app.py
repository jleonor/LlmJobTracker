"""FastAPI application factory. Every route requires the per-launch token."""

import secrets
from collections.abc import Iterator
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from localjobtracker.jobs import Job, list_jobs
from localjobtracker.storage import connect

TOKEN_HEADER = "X-Launch-Token"


def create_app(launch_token: str, db_path: Path) -> FastAPI:
    """Build the app. Requests must send `launch_token` in the X-Launch-Token header."""

    def require_token(x_launch_token: str | None = Header(default=None)) -> None:
        if x_launch_token is None or not secrets.compare_digest(x_launch_token, launch_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    def get_db() -> Iterator[Connection]:
        conn = connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    app = FastAPI(title="LocalJobTracker", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health", dependencies=[Depends(require_token)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/jobs", response_model=list[Job], dependencies=[Depends(require_token)])
    def jobs(conn: Annotated[Connection, Depends(get_db)]) -> list[Job]:
        return list_jobs(conn)

    return app
