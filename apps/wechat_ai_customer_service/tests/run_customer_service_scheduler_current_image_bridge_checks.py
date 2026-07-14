"""Regression checks for the scheduler's sole live image-read capability."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    CapturedMessagesConnector,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def sample_capture() -> dict[str, Any]:
    return {
        "capture_id": "capture-current-image-1",
        "target_name": "Image Customer",
        "session_key": "wx:rpa:v1:image-customer",
        "pending_signal": {
            "pending_signal_id": "pending-image-1",
            "pending_signal_kind": "image_capture",
            "pending_signal_text": "[图片]",
        },
        "messages": [{"id": "message-image-1", "type": "image", "content": "客户发了一张图片"}],
        "batch": [{"id": "message-image-1", "type": "image", "content": "客户发了一张图片"}],
    }


def check_only_capture_bound_current_image_transaction_can_delegate() -> None:
    calls: list[dict[str, Any]] = []

    def runner(target: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"target": target, **kwargs})
        return {
            "ok": False,
            "reason": "unit_clipboard_copy_failed",
            "transaction": {"status": "copy_failed", "clipboard_content_read": False},
        }

    connector = CapturedMessagesConnector(
        sample_capture(),
        current_image_transaction_runner=runner,
    )
    rejected = connector.run_customer_clipboard_image_transaction(
        "Image Customer",
        session_key="wx:rpa:v1:image-customer",
        pending_signal_id="other-image-event",
    )
    assert_equal(rejected.get("reason"), "clipboard_current_transaction_signal_mismatch", "wrong event must fail before RPA")
    assert_equal(calls, [], "wrong event must never invoke the live connector")

    result = connector.run_customer_clipboard_image_transaction(
        "Image Customer",
        session_key="wx:rpa:v1:image-customer",
        pending_signal_id="pending-image-1",
        source_preview="[图片]",
        consume_current_clipboard=lambda _transaction: {"ok": False},
    )
    assert_equal(result.get("reason"), "unit_clipboard_copy_failed", "the sole route must delegate to the live clipboard port")
    assert_equal(len(calls), 1, "exactly one transaction may be delegated")
    call = calls[0]
    assert_equal(call.get("target"), "Image Customer", "transaction target must remain capture-bound")
    assert_equal(call.get("session_key"), "wx:rpa:v1:image-customer", "transaction session must remain capture-bound")
    assert_equal(call.get("pending_signal_id"), "pending-image-1", "transaction event must remain capture-bound")
    assert_true(call.get("consume_current_clipboard") is not None, "the live route must read only the current clipboard")
    persisted_capture = connector.capture
    assert_true("image_bytes" not in persisted_capture, "image bytes must never enter the planner capture")
    assert_true("saved_image_path" not in persisted_capture, "image paths must never enter the planner capture")
    assert_true("screenshot_path" not in persisted_capture, "screenshots must never enter the planner capture")


def check_missing_live_port_fails_closed() -> None:
    connector = CapturedMessagesConnector(sample_capture())
    result = connector.run_customer_clipboard_image_transaction(
        "Image Customer",
        session_key="wx:rpa:v1:image-customer",
        pending_signal_id="pending-image-1",
    )
    assert_equal(result.get("reason"), "clipboard_current_transaction_unsupported", "no live port must never fall back")


def main() -> int:
    checks = [
        check_only_capture_bound_current_image_transaction_can_delegate,
        check_missing_live_port_fails_closed,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # noqa: BLE001 - standalone diagnostic runner.
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [result for result in results if not result["ok"]]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
