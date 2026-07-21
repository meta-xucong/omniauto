from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (  # noqa: E402
    PR28_BLOBS,
    WeChatPr28RuntimeAdapter,
    adapt_wechat_pr28_connector,
    physical_rpa_identity_kwargs,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


class FakeConnector:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def call_compat_sidecar(self, args: list[str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "call_compat_sidecar", "args": list(args), **kwargs})
        return {"ok": True}

    def get_messages(self, target: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "get_messages", "target": target, "exact": exact, **kwargs})
        return {"ok": True, "messages": []}

    def send_text(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "send_text", "target": target, "text": text, "exact": exact, **kwargs})
        return {"ok": True}

    def send_text_and_verify(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "send_text_and_verify", "target": target, "text": text, "exact": exact, **kwargs})
        return {"ok": True, "verified": True}


def check_pr28_blob_manifest_matches_worktree() -> None:
    for relative, expected in PR28_BLOBS.items():
        completed = subprocess.run(
            ["git", "hash-object", "--", relative],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        actual = completed.stdout.strip()
        assert_true(actual == expected, f"PR #28 blob changed: {relative}: {actual} != {expected}")


def check_exact_session_key_drops_only_physical_type_filter() -> None:
    source = {
        "session_key": "wx:rpa:v1:opaque-key",
        "conversation_type": "group",
        "artifact_dir": "runtime/probe",
    }
    projected = physical_rpa_identity_kwargs(source)
    assert_true(projected["session_key"] == source["session_key"], "opaque session key changed")
    assert_true(projected["conversation_type"] == "", "drift-prone type remained a physical key filter")
    assert_true(projected["artifact_dir"] == source["artifact_dir"], "unrelated argument changed")
    assert_true(source["conversation_type"] == "group", "caller identity payload was mutated")


def check_type_is_preserved_without_opaque_key() -> None:
    projected = physical_rpa_identity_kwargs({"conversation_type": "group"})
    assert_true(projected["conversation_type"] == "group", "type-only lookup was weakened")


def check_runtime_proxy_preserves_calls_and_has_no_retired_vision_routes() -> None:
    raw = FakeConnector()
    connector = adapt_wechat_pr28_connector(raw)
    assert_true(isinstance(connector, WeChatPr28RuntimeAdapter), "runtime adapter was not installed")
    connector.get_messages(
        "新数据测试(2)",
        exact=True,
        session_key="wx:rpa:v1:opaque-key",
        conversation_type="group",
        history_load_times=2,
    )
    call = raw.calls[-1]
    assert_true(call["target"] == "新数据测试(2)" and call["exact"] is True, "exact title contract changed")
    assert_true(call["session_key"] == "wx:rpa:v1:opaque-key", "opaque key was not preserved")
    assert_true(call["conversation_type"] == "", "physical type drift was not contained")
    assert_true(call["history_load_times"] == 2, "existing connector keyword was lost")

    assert_true(
        not hasattr(connector, "run_customer_clipboard_image_transaction")
        and not hasattr(connector, "run_self_clipboard_image_transaction"),
        "retired image transaction routes remain exposed by the runtime adapter",
    )


def check_sidecar_fixed_origin_default_is_injected_without_overriding_owner_choice() -> None:
    previous = os.environ.get("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN")
    try:
        os.environ.pop("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", None)
        raw = FakeConnector()
        adapt_wechat_pr28_connector(raw)
        raw.call_compat_sidecar(["status"], env_overrides={"OTHER": "1"})
        overrides = raw.calls[-1]["env_overrides"]
        assert_true(overrides["WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN"] == "1", "safe fixed-origin default missing")
        assert_true(overrides["OTHER"] == "1", "existing sidecar environment was replaced")

        os.environ["WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN"] = "0"
        raw2 = FakeConnector()
        adapt_wechat_pr28_connector(raw2)
        raw2.call_compat_sidecar(["status"])
        overrides2 = raw2.calls[-1].get("env_overrides") or {}
        assert_true("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN" not in overrides2, "explicit owner setting was overridden")
    finally:
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", None)
        else:
            os.environ["WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN"] = previous


def main() -> int:
    checks = [
        check_pr28_blob_manifest_matches_worktree,
        check_exact_session_key_drops_only_physical_type_filter,
        check_type_is_preserved_without_opaque_key,
        check_runtime_proxy_preserves_calls_and_has_no_retired_vision_routes,
        check_sidecar_fixed_origin_default_is_injected_without_overriding_owner_choice,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
