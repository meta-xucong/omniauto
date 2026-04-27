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
        check_manual_handoff_browser_policy(checks)
        check_builder_output(checks)
        print(json.dumps({"ok": True, "checks": checks}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": repr(exc), "checks": checks}, ensure_ascii=False, indent=2))
        return 1


def check_required_files(checks: list[dict[str, object]]) -> None:
    paths = [
        APP_ROOT / "README.md",
        APP_ROOT / "configs" / "default.example.json",
        APP_ROOT / "workflows" / "base_1688_research.py",
        APP_ROOT / "workflows" / "build_1688_workflow.py",
        APP_ROOT / "scripts" / "run-report.ps1",
        APP_ROOT / "scripts" / "closeout_marketplace_run.py",
    ]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise AssertionError(f"missing required files: {missing}")
    checks.append({"name": "required_files", "ok": True, "count": len(paths)})


def check_manual_handoff_browser_policy(checks: list[dict[str, object]]) -> None:
    source = (APP_ROOT / "workflows" / "base_1688_research.py").read_text(encoding="utf-8")
    manual_section = source.split("def _launch_external_manual_browser", 1)[1].split("def _gentle_page_pause", 1)[0]
    if "--remote-debugging-port" in manual_section:
        raise AssertionError("manual handoff browser must not be launched with remote debugging")
    if "--disable-extensions" in manual_section:
        raise AssertionError("manual handoff browser must not disable extensions")
    if "_stop_profile_automation_chrome_processes(profile_path)" not in manual_section:
        raise AssertionError("manual handoff browser must stop residual automation Chrome for the profile first")
    checks.append({"name": "manual_handoff_browser_policy", "ok": True})


def check_builder_output(checks: list[dict[str, object]]) -> None:
    command = [
        sys.executable,
        str(APP_ROOT / "workflows" / "build_1688_workflow.py"),
        "--repo-root",
        str(REPO_ROOT),
        "--keyword",
        "测试",
        "--pages",
        "1",
        "--detail-sample-size",
        "0",
        "--task-slug",
        "offline_check",
    ]
    completed = subprocess.run(command, cwd=str(REPO_ROOT), capture_output=True, timeout=30)
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        raise AssertionError(stderr or stdout)
    payload = json.loads(stdout)
    workflow_path = Path(payload["workflow_path"])
    output_dir = Path(payload["output_dir"])
    if "runtime\\apps\\marketplace_1688_research" not in str(workflow_path) and "runtime/apps/marketplace_1688_research" not in str(workflow_path):
        raise AssertionError(f"generated workflow is outside app runtime: {workflow_path}")
    if "runtime\\apps\\marketplace_1688_research" not in str(output_dir) and "runtime/apps/marketplace_1688_research" not in str(output_dir):
        raise AssertionError(f"output dir is outside app runtime: {output_dir}")
    content = workflow_path.read_text(encoding="utf-8")
    if '"apps" / "marketplace_1688_research"' not in content and "apps/marketplace_1688_research" not in content:
        raise AssertionError("generated workflow does not reference app-local base workflow")
    checks.append({"name": "builder_output", "ok": True, "workflow_path": str(workflow_path)})


if __name__ == "__main__":
    raise SystemExit(main())
