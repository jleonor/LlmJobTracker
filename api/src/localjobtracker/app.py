"""FastAPI application factory. Every route requires the per-launch token."""

import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, status

TOKEN_HEADER = "X-Launch-Token"


def create_app(launch_token: str) -> FastAPI:
    """Build the app. Requests must send `launch_token` in the X-Launch-Token header."""

    def require_token(x_launch_token: str | None = Header(default=None)) -> None:
        if x_launch_token is None or not secrets.compare_digest(x_launch_token, launch_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    app = FastAPI(title="LocalJobTracker", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health", dependencies=[Depends(require_token)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
