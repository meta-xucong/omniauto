from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision import runtime  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision import scheduler_capture  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.surface import (  # noqa: E402
    visual_image_envelopes_from_bubbles,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.wechat import (  # noqa: E402
    _latest_visual_bubble,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.occurrence import (  # noqa: E402
    resolve_pending_visual_occurrence,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def _text(
    message_id: str,
    content: str,
    *,
    top: int,
    bottom: int,
    signal_id: str = "",
) -> dict[str, Any]:
    message = {
        "id": message_id,
        "message_id": message_id,
        "type": "text",
        "sender": "customer",
        "sender_role": "customer",
        "content": content,
        "bubble_rect": {"left": 420, "top": top, "right": 720, "bottom": bottom},
    }
    if signal_id:
        message["pending_signal_id"] = signal_id
    return message


def _bubble(*, side: str, top: int, bottom: int, message_time: str = "18:10") -> dict[str, Any]:
    left, right = (410, 650) if side == "customer" else (700, 940)
    return {
        "side": side,
        "bounds": [left, top, right, bottom],
        "wechat_message_time": message_time,
        "detection_method": "structural_media_lane_v1",
    }


def _surface_occurrence(
    *,
    side: str,
    message_id: str,
    following_text_id: str = "",
) -> dict[str, Any]:
    message = {
        "id": message_id,
        "message_id": message_id,
        "type": "image",
        "message_type": "image",
        "sender": side,
        "sender_role": side,
        "visual_side": side,
        "visual_turn_kind": f"{side}_image",
        "content": "[图片]",
        "source_adapter": "win32_ocr_structural_image_observer",
    }
    if following_text_id:
        message["_vision_following_text_id"] = following_text_id
    return message


def _prepare(
    *,
    messages: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    signal_kind: str = "normal",
    signal_text: str = "这张图是什么车？",
    signal_id: str = "signal-current",
    target_state: dict[str, Any] | None = None,
    self_runner: Any = None,
) -> tuple[dict[str, Any], int]:
    calls = 0
    original = scheduler_capture.legacy_observe_current_surface

    def observe(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True, "state": "observed", "messages": list(observed)}

    scheduler_capture.legacy_observe_current_surface = observe
    target = SimpleNamespace(
        name="Customer A",
        exact=True,
        session_key="wx:customer-a",
        conversation_type="private",
    )
    signal = {
        "pending_signal_id": signal_id,
        "pending_signal_kind": signal_kind,
        "pending_signal_text": signal_text,
        "preview_content": signal_text,
        "pending": True,
        "unread_detected": True,
    }
    try:
        result = scheduler_capture.prepare_scheduler_capture(
            connector=SimpleNamespace(call_compat_sidecar=lambda *_args, **_kwargs: {}),
            target=target,
            config={},
            payload={"messages": list(messages), "pending_signal": dict(signal)},
            messages=list(messages),
            target_state=dict(target_state or {}),
            pending_signal=signal,
            pending_signal_kind=signal_kind,
            pending_signal_id=signal_id,
            history_meta={},
            self_context_runner=self_runner,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original
    return result, calls


def check_surface_identity_uses_neighbor_anchors_without_geometry_leak() -> None:
    texts = [
        _text("before-1", "上一条", top=150, bottom=195),
        _text("after-1", "图片后的追问", top=500, bottom=550),
    ]
    first = visual_image_envelopes_from_bubbles(
        [_bubble(side="customer", top=250, bottom=450)],
        texts,
        target="Customer A",
    )
    moved = visual_image_envelopes_from_bubbles(
        [_bubble(side="customer", top=262, bottom=462)],
        [
            _text("before-1", "上一条", top=162, bottom=207),
            _text("after-1", "图片后的追问", top=512, bottom=562),
        ],
        target="Customer A",
    )
    assert_equal(first[0].get("message_id"), moved[0].get("message_id"), "scroll movement must not change occurrence identity")
    assert_equal(first[0].get("_vision_following_text_id"), "after-1", "nearest following text must be the private turn anchor")
    encoded = json.dumps(first, ensure_ascii=False).lower()
    assert_true("bounds" not in encoded and "anchor\"" not in encoded, "surface projection must not leak image geometry")


def check_following_text_arrival_does_not_manufacture_a_new_image_occurrence() -> None:
    image_only = visual_image_envelopes_from_bubbles(
        [_bubble(side="customer", top=250, bottom=450)],
        [_text("before-2", "上一条", top=150, bottom=195)],
        target="Customer A",
    )
    image_then_text = visual_image_envelopes_from_bubbles(
        [_bubble(side="customer", top=250, bottom=450)],
        [
            _text("before-2", "上一条", top=150, bottom=195),
            _text("after-2", "稍后补的一句话", top=500, bottom=550),
        ],
        target="Customer A",
    )
    assert_equal(
        image_only[0].get("message_id"),
        image_then_text[0].get("message_id"),
        "a later text anchor may bind the turn but must not redefine the earlier image occurrence",
    )
    assert_equal(image_then_text[0].get("_vision_following_text_id"), "after-2", "later text must still become the recovery relation")


def check_text_preview_recovers_adjacent_customer_image_once() -> None:
    current_text = _text(
        "customer-question-1",
        "这张图是什么车？",
        top=500,
        bottom=550,
        signal_id="signal-current",
    )
    result, calls = _prepare(
        messages=[current_text],
        observed=[
            _surface_occurrence(
                side="customer",
                message_id="visual-customer-1",
                following_text_id="customer-question-1",
            )
        ],
    )
    assert_equal(calls, 1, "one real text capture must perform one cheap structural observation")
    assert_true((result.get("visual_capture_trigger") or {}).get("should_run") is False, "sidebar metadata must remain text-only")
    assert_equal((result.get("customer_image_assets") or {}).get("state"), "clipboard_vision_pending", "adjacent occurrence must enter current clipboard route")
    structural = [item for item in result.get("messages") or [] if item.get("type") == "image"]
    proxies = [item for item in result.get("messages") or [] if item.get("is_customer_image_proxy")]
    assert_equal(len(structural), 1, "exactly one structural occurrence must survive")
    assert_equal(len(proxies), 1, "exactly one customer image proxy must be emitted")
    assert_equal(structural[0].get("pending_signal_id"), "signal-current", "image must reuse the scheduler capture identity")
    assert_true(not any(str(key).startswith("_vision_") for key in structural[0]), "private anchor metadata must be stripped before returning to Core")


def check_old_visible_image_does_not_reactivate_on_new_text() -> None:
    current_text = _text(
        "customer-question-2",
        "今天几点下班？",
        top=500,
        bottom=550,
        signal_id="signal-current",
    )
    result, calls = _prepare(
        messages=[current_text],
        observed=[
            _surface_occurrence(
                side="customer",
                message_id="visual-old-1",
                following_text_id="customer-question-2",
            )
        ],
        target_state={"processed_message_ids": ["visual-old-1"]},
    )
    assert_equal(calls, 1, "old-image rejection still starts from one current structural observation")
    assert_equal(result.get("customer_image_assets"), {}, "an already-seen occurrence must not enter the clipboard route")
    assert_true(not any(item.get("is_customer_image_proxy") for item in result.get("messages") or []), "old image must not create a new proxy")


def check_text_preview_recovers_self_image_without_consuming_customer_text() -> None:
    runner_calls: list[dict[str, Any]] = []

    def self_runner(**kwargs: Any) -> dict[str, Any]:
        runner_calls.append(kwargs)
        return {
            "enabled": True,
            "applied": True,
            "context_only": True,
            "reason": "self_image_context_ready",
        }

    current_text = _text(
        "customer-question-3",
        "刚才你发的是什么图？",
        top=500,
        bottom=550,
        signal_id="signal-current",
    )
    result, calls = _prepare(
        messages=[current_text],
        observed=[
            _surface_occurrence(
                side="self",
                message_id="visual-self-1",
                following_text_id="customer-question-3",
            )
        ],
        self_runner=self_runner,
    )
    assert_equal(calls, 1, "self image recovery must use the same one-probe path")
    assert_equal(len(runner_calls), 1, "self image must be understood exactly once")
    assert_true((result.get("self_image_context") or {}).get("context_only") is True, "self image must remain context-only")
    assert_true(result.get("pending_signal_consumed") is False, "recovering self context must not swallow the customer's current text")
    assert_equal(result.get("customer_image_assets"), {}, "self image must never become a customer image reply turn")


def check_text_only_capture_has_no_clipboard_or_llm_route() -> None:
    current_text = _text(
        "customer-question-4",
        "你好",
        top=500,
        bottom=550,
        signal_id="signal-current",
    )
    result, calls = _prepare(messages=[current_text], observed=[])
    assert_equal(calls, 1, "text capture may perform one cheap surface probe")
    assert_equal(result.get("customer_image_assets"), {}, "text-only capture must not enter clipboard acquisition")
    assert_true(result.get("pending_signal_consumed") is False, "Vision must not consume ordinary text")


def check_custom_connector_without_pr_host_does_not_start_desktop_observer() -> None:
    signal = {
        "pending_signal_id": "signal-custom",
        "pending_signal_kind": "normal",
        "pending_signal_text": "普通文字",
    }
    result = scheduler_capture.prepare_scheduler_capture(
        connector=object(),
        target=SimpleNamespace(
            name="Custom",
            exact=True,
            session_key="custom:1",
            conversation_type="private",
        ),
        config={},
        payload={"pending_signal": signal},
        messages=[
            _text(
                "custom-text-1",
                "普通文字",
                top=500,
                bottom=550,
                signal_id="signal-custom",
            )
        ],
        target_state={},
        pending_signal=signal,
        pending_signal_kind="normal",
        pending_signal_id="signal-custom",
        history_meta={},
        self_context_runner=None,
    )
    assert_equal(result.get("customer_image_assets"), {}, "custom connector text path must remain unchanged")


def check_runtime_accepts_structurally_bound_normal_pending_signal() -> None:
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "这是什么车？",
    }
    payload = {
        "pending_signal": signal,
        "messages": [
            {
                **_surface_occurrence(side="customer", message_id="visual-runtime-1"),
                "pending_signal_id": "signal-current",
            }
        ],
    }
    resolved = runtime._current_image_pending_signal(payload, {})
    assert_equal(resolved.get("pending_signal_id"), "signal-current", "runtime must preserve the structurally confirmed capture id")
    assert_equal(resolved.get("pending_signal_kind"), "normal", "runtime must not rewrite the host pending-signal contract")


def check_structurally_recovered_customer_image_runs_one_current_clipboard_transaction() -> None:
    calls: list[dict[str, Any]] = []

    class EphemeralImage:
        def __init__(self) -> None:
            self.released = False

        def release(self) -> None:
            self.released = True

    ephemeral = EphemeralImage()
    original_transaction = runtime._run_current_clipboard_image_transaction
    original_understanding = runtime.maybe_run_customer_image_understanding

    def transaction(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {
            "ok": True,
            "state": "image_clipboard_copied",
            "transaction": {
                "status": "clipboard_read",
                "right_click_ok": True,
                "menu_copy_confirmed": True,
                "clipboard_sequence_changed": True,
                "clipboard_content_read": True,
                "clipboard_image_valid": True,
            },
            "_ephemeral_clipboard_image": ephemeral,
        }

    runtime._run_current_clipboard_image_transaction = transaction
    runtime.maybe_run_customer_image_understanding = lambda **_kwargs: {
        "applied": True,
        "adoptable": True,
        "reason": "customer_image_understanding_ready",
        "vision_summary": "一张车辆照片",
        "source_messages": [],
        "entities": [],
    }
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "这是什么车？",
    }
    structural = {
        **_surface_occurrence(side="customer", message_id="visual-runtime-2"),
        "pending_signal_id": "signal-current",
    }
    proxy = {
        "id": "proxy-runtime-2",
        "message_id": "proxy-runtime-2",
        "type": "text",
        "sender": "customer",
        "sender_role": "customer",
        "content": "客户发送了一张图片，图片内容暂未取得。",
        "pending_signal_id": "signal-current",
        "visual_turn_kind": "customer_image",
        "is_customer_image_proxy": True,
        "image_capture_pending": True,
        "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
    }
    try:
        result = runtime.maybe_route_customer_image_turn(
            connector=object(),
            target=SimpleNamespace(
                name="Customer A",
                exact=True,
                session_key="wx:customer-a",
            ),
            config={"vehicle_image_retrieval": {"enabled": False}},
            payload={"pending_signal": signal, "messages": [structural, proxy]},
            target_state={},
            batch=[proxy],
            combined="这是什么车？",
        )
    finally:
        runtime._run_current_clipboard_image_transaction = original_transaction
        runtime.maybe_run_customer_image_understanding = original_understanding
    assert_true(result.get("applied") is True and result.get("adoptable") is True, f"recovered image turn must reach Brain evidence: {result}")
    assert_equal(len(calls), 1, "one recovered occurrence must execute exactly one current clipboard transaction")
    assert_equal(calls[0].get("pending_signal_id"), "signal-current", "clipboard transaction must keep the capture identity")
    assert_equal(calls[0].get("side_filter"), "customer", "customer occurrence must copy only the customer-side image")
    assert_true(ephemeral.released, "ephemeral clipboard image must be released after understanding")


def check_unanchored_normal_text_cannot_activate_visible_media() -> None:
    resolution = resolve_pending_visual_occurrence(
        [_surface_occurrence(side="self", message_id="visual-unanchored-1")],
        target_state={},
        explicit_image_pending=False,
        pending_signal_id="signal-current",
    )
    assert_equal(resolution.get("state"), "sidebar_signal_only", "normal text needs a structural relation to the current annotated message")
    assert_equal(resolution.get("occurrence"), {}, "unanchored visible history must stay inert")


def check_same_content_new_occurrence_remains_eligible() -> None:
    current_text = _text(
        "customer-question-5",
        "再看一次这张图",
        top=500,
        bottom=550,
        signal_id="signal-new",
    )
    result, _calls = _prepare(
        messages=[current_text],
        observed=[
            _surface_occurrence(
                side="customer",
                message_id="visual-new-occurrence-2",
                following_text_id="customer-question-5",
            )
        ],
        signal_id="signal-new",
        target_state={"processed_message_ids": ["visual-old-occurrence-1"]},
    )
    assert_equal((result.get("customer_image_assets") or {}).get("state"), "clipboard_vision_pending", "a new occurrence must not be deduplicated by image content")


def check_clipboard_target_prefers_latest_position_over_large_old_image() -> None:
    selected = _latest_visual_bubble(
        [
            {
                "bounds": [410, 180, 760, 520],
                "score": 999999.0,
                "side": "customer",
            },
            {
                "bounds": [410, 560, 610, 720],
                "score": 100.0,
                "side": "customer",
            },
        ]
    )
    assert_equal(selected.get("bounds"), [410, 560, 610, 720], "right-click target must follow chat occurrence order, not visual area score")


def main() -> int:
    checks = [
        check_surface_identity_uses_neighbor_anchors_without_geometry_leak,
        check_following_text_arrival_does_not_manufacture_a_new_image_occurrence,
        check_text_preview_recovers_adjacent_customer_image_once,
        check_old_visible_image_does_not_reactivate_on_new_text,
        check_text_preview_recovers_self_image_without_consuming_customer_text,
        check_text_only_capture_has_no_clipboard_or_llm_route,
        check_custom_connector_without_pr_host_does_not_start_desktop_observer,
        check_runtime_accepts_structurally_bound_normal_pending_signal,
        check_structurally_recovered_customer_image_runs_one_current_clipboard_transaction,
        check_unanchored_normal_text_cannot_activate_visible_media,
        check_same_content_new_occurrence_remains_eligible,
        check_clipboard_target_prefers_latest_position_over_large_old_image,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - standalone harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    print(
        json.dumps(
            {
                "ok": not failures,
                "count": len(results),
                "failures": failures,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
