from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import record_capture_result  # noqa: E402
from apps.wechat_ai_customer_service.wechat_message_envelope import visual_ocr_noise_reason  # noqa: E402
from apps.wechat_ai_customer_service.workflows.customer_image_asset_store import (  # noqa: E402
    build_brain_safe_image_proxy_message,
)
from apps.wechat_ai_customer_service.workflows.listen_and_reply import message_is_reply_candidate  # noqa: E402


def main() -> int:
    checks = [
        check_brain_safe_image_proxy_not_filtered_as_visual_noise,
        check_record_capture_result_accepts_saved_image_proxy,
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


def check_brain_safe_image_proxy_not_filtered_as_visual_noise() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "wechat_saved.jpg"
        Image.new("RGB", (128, 80), (230, 230, 230)).save(saved_path)
        proxy = build_brain_safe_image_proxy_message(
            {
                "message_id": "visual_msg_same_image_content",
                "message_type": "image",
                "asset_id": "asset-1",
                "saved_image_path": str(saved_path),
                "source_preview": "许聪:[图片]",
                "captured_at": "2026-07-06T12:00:00",
            },
            target_name="新数据测试",
            session_key="wx:img",
        )
    assert_equal(proxy.get("type"), "text", "proxy type should be text")
    assert_true(not proxy.get("message_type"), f"proxy must not expose message_type=image: {proxy}")
    assert_equal(visual_ocr_noise_reason(proxy), "", f"proxy should not be visual OCR noise: {proxy}")
    assert_true(
        message_is_reply_candidate(
            proxy,
            processed=set(),
            processed_content_keys=set(),
            handoff=set(),
            allow_self_for_test=False,
            config={},
            sent_reply_content_keys=set(),
        ),
        f"proxy should be selectable by workflow: {proxy}",
    )


def check_record_capture_result_accepts_saved_image_proxy() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "wechat_saved.jpg"
        Image.new("RGB", (128, 80), (230, 230, 230)).save(saved_path)
        proxy = build_brain_safe_image_proxy_message(
            {
                "message_id": "visual_msg_capture_1",
                "message_type": "image",
                "asset_id": "asset-capture-1",
                "saved_image_path": str(saved_path),
                "source_preview": "许聪:[图片]",
                "pending_signal_id": "sig-img-1",
                "captured_at": "2026-07-06T12:00:00",
            },
            target_name="新数据测试",
            session_key="wx:capture",
        )
        proxy["image_capture_pending"] = True
        proxy["quality_flags"] = ["synthetic_visual_turn", "clipboard_current_transaction_required"]
        state = {"version": 2, "sessions": {}, "captures": {}, "llm_tasks": {}, "ready_replies": {}, "events": []}
        capture = record_capture_result(
            state,
            "新数据测试",
            messages=[proxy],
            batch=[proxy],
            exact=True,
            conversation_type="single",
            session_key="wx:capture",
            allow_customer_image_proxy=True,
            now="2026-07-06T12:00:01",
        )
    assert_equal(capture.get("status"), "captured", f"image proxy capture should be captured: {capture}")
    assert_equal(capture.get("reply_input_message_count"), 1, f"image proxy should become reply input: {capture}")
    assert_true(bool(capture.get("message_ids")), f"image proxy should have message id: {capture}")
    stored = (capture.get("batch") or [{}])[0]
    assert_equal(str(stored.get("saved_image_path") or ""), "", "capture must strip the retired image path")
    assert_equal(str(stored.get("source_message_type") or ""), "image", "capture should preserve source image type as metadata")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
