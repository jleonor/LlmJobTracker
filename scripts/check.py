"""Run lint, format, type and test checks for the API and the web app.

Usage: python scripts/check.py
Every step runs even if an earlier one fails. The exit code is 1 if any step failed.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Step:
    name: str
    cwd: Path
    tool: str
    args: tuple[str, ...]


STEPS = (
    Step("api: lint", ROOT / "api", "uv", ("run", "ruff", "check", ".")),
    Step("api: format", ROOT / "api", "uv", ("run", "ruff", "format", "--check", ".")),
    Step("api: types", ROOT / "api", "uv", ("run", "mypy")),
    Step("api: tests", ROOT / "api", "uv", ("run", "pytest", "-q")),
    Step("web: lint", ROOT / "web", "npm", ("run", "lint")),
    Step("web: types and build", ROOT / "web", "npm", ("run", "build")),
    Step("web: tests", ROOT / "web", "npm", ("test",)),
)


def run(step: Step) -> bool:
    executable = shutil.which(step.tool)
    if executable is None:
        print(f"[FAIL] {step.name}: '{step.tool}' is not on PATH")
        return False
    result = subprocess.run([executable, *step.args], cwd=step.cwd, check=False)
    passed = result.returncode == 0
    print(f"[{'PASS' if passed else 'FAIL'}] {step.name}")
    return passed


def main() -> int:
    results = [run(step) for step in STEPS]
    failed = [step.name for step, ok in zip(STEPS, results, strict=True) if not ok]
    print()
    if failed:
        print(f"check FAILED: {', '.join(failed)}")
        return 1
    print(f"check PASSED: {len(STEPS)} steps")
    return 0


if __name__ == "__main__":
    sys.exit(main())
