from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (  # noqa: E402
    PR28_BLOBS,
    PR28_HEAD,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.integrations import (  # noqa: E402
    wechat_current,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def check_pr_commit_and_every_owned_blob_are_byte_identical() -> None:
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", PR28_HEAD, "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    for relative, expected in PR28_BLOBS.items():
        source_blob = _git("rev-parse", f"{PR28_HEAD}:{relative}")
        head_blob = _git("rev-parse", f"HEAD:{relative}")
        worktree_blob = _git("hash-object", "--", relative)
        assert_true(source_blob == expected, f"PR source blob drifted: {relative}")
        assert_true(head_blob == expected, f"HEAD changed PR file: {relative}")
        assert_true(worktree_blob == expected, f"worktree changed PR file: {relative}")


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Subscript):
        index = node.func.slice
        if isinstance(index, ast.Constant) and index.value == "WeChatConnector":
            return "WeChatConnector"
    return ""


def check_every_production_connector_construction_is_adapted() -> None:
    misses: list[str] = []
    covered: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if "/tests/" in f"/{relative}/":
            continue
        if relative == "apps/wechat_ai_customer_service/adapters/wechat_connector.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) != "WeChatConnector":
                continue
            parent = parents.get(node)
            adapted = (
                isinstance(parent, ast.Call)
                and isinstance(parent.func, ast.Name)
                and parent.func.id == "adapt_wechat_pr28_connector"
                and node in parent.args
            )
            label = f"{relative}:{node.lineno}"
            (covered if adapted else misses).append(label)
    assert_true(bool(covered), "no production WeChatConnector construction was audited")
    assert_true(not misses, f"production connector bypasses PR adapter: {misses}")


class _VisionConnector:
    compat_sidecar_python = sys.executable
    root = PROJECT_ROOT
    timeout_seconds = 5.0


def check_vision_worker_inherits_additive_pr_host_policy() -> None:
    captured_envs: list[dict[str, str]] = []

    def fake_run(*_args: Any, **kwargs: Any) -> SimpleNamespace:
        captured_envs.append(dict(kwargs.get("env") or {}))
        return SimpleNamespace(stdout='{"ok": true}', stderr="", returncode=0)

    setting = "WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN"
    previous = os.environ.get(setting)
    try:
        os.environ.pop(setting, None)
        with patch.object(wechat_current.subprocess, "run", side_effect=fake_run):
            result = wechat_current._run_vision_worker(_VisionConnector(), ["observe-current-surface"])
        assert_true(result.get("ok") is True, f"vision worker probe failed: {result}")
        assert_true(captured_envs[-1].get(setting) == "1", "Vision worker missed the additive fixed-origin default")

        os.environ[setting] = "0"
        with patch.object(wechat_current.subprocess, "run", side_effect=fake_run):
            result = wechat_current._run_vision_worker(_VisionConnector(), ["observe-current-surface"])
        assert_true(result.get("ok") is True, f"explicit-policy worker probe failed: {result}")
        assert_true(captured_envs[-1].get(setting) == "0", "Vision worker overrode an explicit operator policy")
    finally:
        if previous is None:
            os.environ.pop(setting, None)
        else:
            os.environ[setting] = previous


def check_sidecar_runner_imports_in_both_supported_launch_modes() -> None:
    script = APP_ROOT / "adapters" / "wechat_sidecar_runner.py"
    commands = (
        [sys.executable, str(script), "--help"],
        [
            sys.executable,
            "-m",
            "apps.wechat_ai_customer_service.adapters.wechat_sidecar_runner",
            "--help",
        ],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        assert_true(
            completed.returncode == 0 and "voice-transcribe" in completed.stdout,
            f"sidecar runner import failed: {command}: {completed.stderr[-1000:]}",
        )


def main() -> int:
    checks = [
        check_pr_commit_and_every_owned_blob_are_byte_identical,
        check_every_production_connector_construction_is_adapted,
        check_vision_worker_inherits_additive_pr_host_policy,
        check_sidecar_runner_imports_in_both_supported_launch_modes,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    print(
        json.dumps(
            {"ok": not failures, "count": len(results), "failures": failures, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
