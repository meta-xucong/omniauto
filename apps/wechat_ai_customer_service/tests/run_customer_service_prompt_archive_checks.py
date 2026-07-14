from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_service_prompt_archive import (  # noqa: E402
    archive_prompt_event,
    should_archive_brain_prompt,
)


def main() -> int:
    checks = [
        check_archive_prompt_event_writes_jsonl_and_redacts_secrets,
        check_archive_disable_env_skips_write,
        check_brain_prompt_archive_excludes_ephemeral_visual_turns,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def check_archive_prompt_event_writes_jsonl_and_redacts_secrets() -> None:
    old_root = os.environ.get("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT")
    old_enabled = os.environ.get("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT"] = tmp_dir
            os.environ["CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED"] = "1"
            result = archive_prompt_event(
                "customer_service_brain_prompt",
                {
                    "messages": [{"role": "user", "content": "hello"}],
                    "api_key": "secret-key",
                    "headers": {"Authorization": "Bearer token", "x-api-key": "secret"},
                    "nested": {"refresh_token": "refresh"},
                },
                tenant_id="archive-test",
                settings={"prompt_archive": {"include_all_brain_prompts": True}},
            )
            assert_true(result.get("ok") is True and result.get("archived") is True, f"archive failed: {result}")
            archive_files = sorted(Path(tmp_dir).glob("*.jsonl"))
            assert_equal(len(archive_files), 1, f"expected one archive file in {tmp_dir}")
            lines = archive_files[0].read_text(encoding="utf-8").splitlines()
            assert_equal(len(lines), 1, "expected one jsonl event")
            event = json.loads(lines[0])
            payload = event.get("payload") or {}
            assert_equal(event.get("kind"), "customer_service_brain_prompt", "kind should be preserved")
            assert_equal(payload.get("api_key"), "<redacted>", "api_key should be redacted")
            assert_equal((payload.get("headers") or {}).get("Authorization"), "<redacted>", "authorization should be redacted")
            assert_equal((payload.get("headers") or {}).get("x-api-key"), "<redacted>", "x-api-key should be redacted")
            assert_equal((payload.get("nested") or {}).get("refresh_token"), "<redacted>", "refresh token should be redacted")
            assert_equal(((payload.get("messages") or [{}])[0] or {}).get("content"), "hello", "prompt content should be preserved")
    finally:
        restore_env("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT", old_root)
        restore_env("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED", old_enabled)


def check_archive_disable_env_skips_write() -> None:
    old_root = os.environ.get("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT")
    old_enabled = os.environ.get("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.environ["CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT"] = tmp_dir
            os.environ["CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED"] = "0"
            result = archive_prompt_event("customer_image_understanding_prompt", {"prompt": "hello"}, tenant_id="archive-test")
            assert_true(result.get("ok") is True and result.get("archived") is False, f"disabled archive should be skipped: {result}")
            assert_equal(list(Path(tmp_dir).glob("*.jsonl")), [], "disabled archive should not write files")
    finally:
        restore_env("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ROOT", old_root)
        restore_env("CUSTOMER_SERVICE_PROMPT_ARCHIVE_ENABLED", old_enabled)


def check_brain_prompt_archive_excludes_ephemeral_visual_turns() -> None:
    non_visual = {"current_message": {"text": "hello"}}
    visual = {"current_message": {"text": "image", "visual_bridge_input": {"present": True}}}
    assert_true(should_archive_brain_prompt(settings={}, brain_input=non_visual) is False, "non-visual brain prompt should not archive by default")
    assert_true(should_archive_brain_prompt(settings={}, brain_input=visual) is False, "ephemeral visual bridge must never archive a Brain prompt")
    assert_true(
        should_archive_brain_prompt(
            settings={"prompt_archive": {"include_all_brain_prompts": True}},
            brain_input=visual,
        )
        is False,
        "include_all_brain_prompts must not override the visual privacy block",
    )
    assert_true(
        should_archive_brain_prompt(
            settings={"prompt_archive": {"include_all_brain_prompts": True}},
            brain_input=non_visual,
        )
        is True,
        "include_all_brain_prompts should opt in all brain prompts",
    )


def restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
