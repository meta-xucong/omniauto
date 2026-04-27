from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]


def main() -> int:
    checks: list[dict[str, object]] = []
    try:
        check_required_files(checks)
        check_solver_help(checks)
        check_artifact_path(checks)
        print(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc), "checks": checks}, ensure_ascii=False, indent=2))
        return 1


def check_required_files(checks: list[dict[str, object]]) -> None:
    paths = [
        APP_ROOT / "README.md",
        APP_ROOT / "configs" / "default.example.json",
        APP_ROOT / "workflows" / "minesweeper_solver.py",
        APP_ROOT / "scripts" / "run-solver.ps1",
        APP_ROOT / "scripts" / "closeout_solver_run.py",
    ]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise AssertionError(f"missing required files: {missing}")
    checks.append({"name": "required_files", "ok": True, "count": len(paths)})


def check_solver_help(checks: list[dict[str, object]]) -> None:
    command = [sys.executable, str(APP_ROOT / "workflows" / "minesweeper_solver.py"), "--help"]
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, timeout=30)
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise AssertionError(stderr or stdout)
    if "--mode" not in stdout:
        raise AssertionError("solver help output does not include --mode")
    checks.append({"name": "solver_help", "ok": True})


def check_artifact_path(checks: list[dict[str, object]]) -> None:
    source = (APP_ROOT / "workflows" / "minesweeper_solver.py").read_text(encoding="utf-8")
    if "runtime/apps/minesweeper_autoplay/test_artifacts" not in source:
        raise AssertionError("solver does not default to the app-local artifact directory")
    checks.append({"name": "artifact_path", "ok": True})


if __name__ == "__main__":
    raise SystemExit(main())

