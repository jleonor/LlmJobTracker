"""Start the API and the web dev server together, with one launch token shared by both.

Usage: python scripts/dev.py
Prerequisites: `uv sync` in api/ and `npm install` in web/.
Press Ctrl+C to stop both. The token is generated for this launch only and is never printed.
"""

import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "api"
WEB_DIR = ROOT / "web"
WEB_URL = "http://127.0.0.1:5173/"
IS_WINDOWS = sys.platform == "win32"


def api_python() -> Path:
    relative = Path("Scripts/python.exe") if IS_WINDOWS else Path("bin/python")
    return API_DIR / ".venv" / relative


def start(args: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(args, cwd=cwd, env=env, start_new_session=not IS_WINDOWS)


def stop_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop a process and everything it started. npm and uvicorn both spawn children."""
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        os.killpg(process.pid, 15)
    process.wait(timeout=15)


def main() -> int:
    python = api_python()
    npm = shutil.which("npm")
    if not python.exists():
        print("The API environment is missing. Run `uv sync` in api/ first.")
        return 1
    if npm is None:
        print("npm is not on PATH. Install Node.js first.")
        return 1

    token = secrets.token_urlsafe(32)
    env = {**os.environ, "LJT_TOKEN": token}
    processes: list[subprocess.Popen[bytes]] = []
    try:
        processes.append(start([str(python), "-m", "llmjobtracker"], API_DIR, env))
        processes.append(
            start([npm, "run", "dev", "--", "--port", "5173", "--strictPort"], WEB_DIR, env)
        )
        print(f"Web app: {WEB_URL}  (API on 127.0.0.1:8765). Press Ctrl+C to stop.")
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
        print("A process exited. Stopping the other one.")
        return 1
    except KeyboardInterrupt:
        print("Stopping.")
        return 0
    finally:
        for process in processes:
            stop_tree(process)


if __name__ == "__main__":
    sys.exit(main())
