"""Start the API on 127.0.0.1. The launch token comes from LJT_TOKEN or is generated."""

import os
import secrets

import uvicorn

from localjobtracker.app import create_app
from localjobtracker.migrations import migrate
from localjobtracker.storage import connect, data_dir, database_path

HOST = "127.0.0.1"
PORT = 8765


def main() -> None:
    conn = connect(database_path(data_dir()))
    try:
        migrate(conn)
    finally:
        conn.close()
    token = os.environ.get("LJT_TOKEN") or secrets.token_urlsafe(32)
    uvicorn.run(create_app(token), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
