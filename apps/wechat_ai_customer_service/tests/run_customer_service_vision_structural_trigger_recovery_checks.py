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
    private_ordinal: bool = False,
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
    if private_ordinal:
        message["_vision_occurrence_ordinal"] = 0
        message["_vision_transaction_ordinal"] = "0"
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
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True, "state": "observed", "messages": list(observed)}

    def locate(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "state": "vision_visual_group_located", "messages": list(observed)}

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
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
        scheduler_capture.legacy_locate_current_visual_group = original_locate
    return result, calls


def _prepare_with_locate(
    *,
    messages: list[dict[str, Any]],
    located: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, int]]:
    calls = {"observe": 0, "locate": 0}
    original_observe = scheduler_capture.legacy_observe_current_surface
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        calls["observe"] += 1
        return {"ok": True, "state": "observed", "messages": []}

    def locate(**kwargs: Any) -> dict[str, Any]:
        calls["locate"] += 1
        assert_true("source_preview" not in kwargs, "private locate must not carry dead source preview args")
        assert_true("pending_signal_id" not in kwargs, "private locate must not carry dead signal args")
        return {
            "ok": True,
            "state": "vision_visual_group_located",
            "reason": "visual_group_selected",
            "messages": list(located),
            "locate": {"scroll_steps": 1, "snapshot_count": 2, "restored_to_latest": True},
        }

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
    target = SimpleNamespace(
        name="Customer A",
        exact=True,
        session_key="wx:customer-a",
        conversation_type="private",
    )
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "image_capture",
        "pending_signal_text": "[图片]",
        "preview_content": "[图片]",
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
            target_state={},
            pending_signal=signal,
            pending_signal_kind="image_capture",
            pending_signal_id="signal-current",
            history_meta={},
            self_context_runner=None,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original_observe
        scheduler_capture.legacy_locate_current_visual_group = original_locate
    return result, calls


def _prepare_normal_with_locate(
    *,
    messages: list[dict[str, Any]],
    located: list[dict[str, Any]],
    target_state: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    calls = {"observe": 0, "locate": 0}
    original_observe = scheduler_capture.legacy_observe_current_surface
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        calls["observe"] += 1
        return {"ok": True, "state": "observed", "messages": []}

    def locate(**kwargs: Any) -> dict[str, Any]:
        calls["locate"] += 1
        assert_equal(kwargs.get("anchor_message_id"), "customer-question-anchor", "normal locate must use the scheduler body anchor id")
        assert_equal(kwargs.get("anchor_text_key"), "现在想换这台", "normal locate must use the scheduler body anchor key")
        assert_equal(kwargs.get("max_scroll_steps"), 2, "normal locate must use the short scroll cap")
        assert_equal(kwargs.get("max_snapshots"), 3, "normal locate must use the short snapshot cap")
        assert_equal(kwargs.get("max_seconds"), 6.0, "normal locate must use the short time cap")
        return {
            "ok": True,
            "state": "vision_visual_group_located",
            "reason": "visual_group_selected",
            "messages": list(located),
            "locate": {"scroll_steps": 1, "snapshot_count": 2, "restored_to_latest": True},
        }

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
    target = SimpleNamespace(
        name="Customer A",
        exact=True,
        session_key="wx:customer-a",
        conversation_type="private",
    )
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "后续文字",
        "preview_content": "后续文字",
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
            pending_signal_kind="normal",
            pending_signal_id="signal-current",
            history_meta={},
            self_context_runner=None,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original_observe
        scheduler_capture.legacy_locate_current_visual_group = original_locate
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


def check_explicit_image_pending_uses_bounded_locate_and_existing_proxy_shape() -> None:
    result, calls = _prepare_with_locate(
        messages=[],
        located=[
            _surface_occurrence(
                side="customer",
                message_id="visual-located-1",
                private_ordinal=True,
            )
        ],
    )
    assert_equal(calls, {"observe": 0, "locate": 1}, "explicit image pending must use the bounded locate seam")
    structural = [item for item in result.get("messages") or [] if item.get("type") == "image"]
    proxies = [item for item in result.get("messages") or [] if item.get("is_customer_image_proxy")]
    assert_equal(len(structural), 1, "located structural occurrence must be projected unchanged")
    assert_equal(len(proxies), 1, "located customer image must emit the existing clipboard proxy")
    assert_equal(proxies[0].get("pending_signal_id"), "signal-current", "proxy must keep the existing pending signal id")
    assert_true(not any(str(key).startswith("_vision_") for key in structural[0]), "located structural occurrence must not leak private locator fields")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert_true(
        "_vision_occurrence_ordinal" not in serialized
        and "_vision_transaction_ordinal" not in serialized,
        "scheduler proxy result must not leak transaction-local ordinal fields",
    )


def check_normal_pending_uses_body_anchor_bounded_locate_for_offscreen_image() -> None:
    current_texts = [
        _text("customer-question-anchor", "现在想换这台", top=410, bottom=450),
        _text("customer-question-2", "预算便宜点", top=460, bottom=500),
        _text("customer-question-3", "最好日系", top=510, bottom=550),
        _text("customer-question-4", "车况好点", top=560, bottom=600),
        _text("customer-question-5", "尽快回复", top=610, bottom=650, signal_id="signal-current"),
    ]
    result, calls = _prepare_normal_with_locate(
        messages=current_texts,
        located=[
            _surface_occurrence(
                side="customer",
                message_id="visual-normal-located-1",
                following_text_id="customer-question-anchor",
            )
        ],
    )
    assert_equal(calls, {"observe": 0, "locate": 1}, "normal multi-text pending must use one private locate worker")
    proxies = [item for item in result.get("messages") or [] if item.get("is_customer_image_proxy")]
    assert_equal(len(proxies), 1, "normal pending offscreen image must produce the existing image proxy")
    assert_equal(proxies[0].get("pending_signal_id"), "signal-current", "proxy must stay bound to the current scheduler signal")


def check_normal_single_text_keeps_legacy_observe_without_backsearch() -> None:
    calls = {"observe": 0, "locate": 0}
    original_observe = scheduler_capture.legacy_observe_current_surface
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        calls["observe"] += 1
        return {"ok": True, "state": "observed", "messages": []}

    def locate(**_kwargs: Any) -> dict[str, Any]:
        calls["locate"] += 1
        return {"ok": True, "messages": [_surface_occurrence(side="customer", message_id="visual-single-text-1")]}

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "普通咨询",
        "preview_content": "普通咨询",
    }
    try:
        result = scheduler_capture.prepare_scheduler_capture(
            connector=SimpleNamespace(call_compat_sidecar=lambda *_args, **_kwargs: {}),
            target=SimpleNamespace(
                name="Customer A",
                exact=True,
                session_key="wx:customer-a",
                conversation_type="private",
            ),
            config={},
            payload={"messages": [], "pending_signal": dict(signal)},
            messages=[
                _text("single-normal", "普通咨询", top=410, bottom=450, signal_id="signal-current"),
            ],
            target_state={},
            pending_signal=signal,
            pending_signal_kind="normal",
            pending_signal_id="signal-current",
            history_meta={},
            self_context_runner=None,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original_observe
        scheduler_capture.legacy_locate_current_visual_group = original_locate
    assert_equal(calls, {"observe": 1, "locate": 0}, "normal single text must not start bounded locate")
    assert_true(not any(item.get("is_customer_image_proxy") for item in result.get("messages") or []), "normal single text must not create a proxy from history")


def check_processed_history_texts_do_not_trigger_normal_backsearch() -> None:
    calls = {"observe": 0, "locate": 0}
    original_observe = scheduler_capture.legacy_observe_current_surface
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        calls["observe"] += 1
        return {"ok": True, "state": "observed", "messages": []}

    def locate(**_kwargs: Any) -> dict[str, Any]:
        calls["locate"] += 1
        return {"ok": True, "messages": [_surface_occurrence(side="customer", message_id="visual-history-1")]}

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "本次单条文字",
        "preview_content": "本次单条文字",
    }
    try:
        result = scheduler_capture.prepare_scheduler_capture(
            connector=SimpleNamespace(call_compat_sidecar=lambda *_args, **_kwargs: {}),
            target=SimpleNamespace(
                name="Customer A",
                exact=True,
                session_key="wx:customer-a",
                conversation_type="private",
            ),
            config={},
            payload={"messages": [], "pending_signal": dict(signal)},
            messages=[
                _text("old-processed-1", "旧问题一", top=310, bottom=350),
                _text("old-processed-2", "旧问题二", top=360, bottom=400),
                _text("fresh-single", "本次单条文字", top=410, bottom=450, signal_id="signal-current"),
            ],
            target_state={"processed_message_ids": ["old-processed-1"], "handoff_message_ids": ["old-processed-2"]},
            pending_signal=signal,
            pending_signal_kind="normal",
            pending_signal_id="signal-current",
            history_meta={},
            self_context_runner=None,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original_observe
        scheduler_capture.legacy_locate_current_visual_group = original_locate
    assert_equal(calls, {"observe": 1, "locate": 0}, "processed/handoff history must not inflate normal text count")
    assert_true(not any(item.get("is_customer_image_proxy") for item in result.get("messages") or []), "processed history must not create image proxy")


def check_processed_history_is_skipped_and_first_fresh_text_becomes_anchor() -> None:
    result, calls = _prepare_normal_with_locate(
        messages=[
            _text("old-processed-1", "旧问题", top=300, bottom=340),
            _text("customer-question-anchor", "现在想换这台", top=410, bottom=450),
            _text("fresh-second", "预算便宜点", top=460, bottom=500, signal_id="signal-current"),
        ],
        located=[
            _surface_occurrence(
                side="customer",
                message_id="visual-normal-located-2",
                following_text_id="customer-question-anchor",
            )
        ],
        target_state={"processed_message_ids": ["old-processed-1"]},
    )
    assert_equal(calls, {"observe": 0, "locate": 1}, "two fresh texts after processed history must still use bounded locate")
    assert_true(any(item.get("is_customer_image_proxy") for item in result.get("messages") or []), "fresh anchor must still produce proxy")


def check_normal_pending_duplicate_body_anchor_does_not_backsearch_or_proxy() -> None:
    calls = {"observe": 0, "locate": 0}
    original_observe = scheduler_capture.legacy_observe_current_surface
    original_locate = scheduler_capture.legacy_locate_current_visual_group

    def observe(**_kwargs: Any) -> dict[str, Any]:
        calls["observe"] += 1
        return {"ok": True, "state": "observed", "messages": []}

    def locate(**_kwargs: Any) -> dict[str, Any]:
        calls["locate"] += 1
        return {"ok": True, "messages": [_surface_occurrence(side="customer", message_id="visual-duplicate-1")]}

    scheduler_capture.legacy_observe_current_surface = observe
    scheduler_capture.legacy_locate_current_visual_group = locate
    signal = {
        "pending_signal_id": "signal-current",
        "pending_signal_kind": "normal",
        "pending_signal_text": "现在想换这台",
        "preview_content": "现在想换这台",
    }
    try:
        result = scheduler_capture.prepare_scheduler_capture(
            connector=SimpleNamespace(call_compat_sidecar=lambda *_args, **_kwargs: {}),
            target=SimpleNamespace(
                name="Customer A",
                exact=True,
                session_key="wx:customer-a",
                conversation_type="private",
            ),
            config={},
            payload={"messages": [], "pending_signal": dict(signal)},
            messages=[
                _text("dup-1", "现在想换这台", top=410, bottom=450),
                _text("dup-2", "现在想换这台", top=460, bottom=500, signal_id="signal-current"),
            ],
            target_state={},
            pending_signal=signal,
            pending_signal_kind="normal",
            pending_signal_id="signal-current",
            history_meta={},
            self_context_runner=None,
        )
    finally:
        scheduler_capture.legacy_observe_current_surface = original_observe
        scheduler_capture.legacy_locate_current_visual_group = original_locate
    assert_equal(calls, {"observe": 1, "locate": 0}, "duplicated body anchor must not enter bounded locate")
    assert_true(not any(item.get("is_customer_image_proxy") for item in result.get("messages") or []), "duplicated body anchor must not create a proxy")


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


def check_structurally_recovered_customer_image_runs_one_current_visual_group_acquire() -> None:
    calls: list[dict[str, Any]] = []

    class EphemeralImage:
        def __init__(self) -> None:
            self.released = False

        def release(self) -> None:
            self.released = True

    ephemeral = EphemeralImage()
    original_acquire = runtime._run_current_visual_group_acquire
    original_understanding = runtime.maybe_run_customer_image_understanding

    def acquire(**kwargs: Any) -> dict[str, Any]:
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
            "messages": [{"message_id": "visual-runtime-2", "type": "image", "sender": "customer"}],
            "_ephemeral_clipboard_images": [ephemeral],
        }

    runtime._run_current_visual_group_acquire = acquire
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
                conversation_type="private",
            ),
            config={"vehicle_image_retrieval": {"enabled": False}},
            payload={"pending_signal": signal, "messages": [structural, proxy]},
            target_state={},
            batch=[proxy],
            combined="这是什么车？",
        )
    finally:
        runtime._run_current_visual_group_acquire = original_acquire
        runtime.maybe_run_customer_image_understanding = original_understanding
    assert_true(result.get("applied") is True and result.get("adoptable") is True, f"recovered image turn must reach Brain evidence: {result}")
    assert_equal(len(calls), 1, "one recovered occurrence must execute exactly one current visual group acquire")
    assert_equal(calls[0].get("session_key"), "wx:customer-a", "group acquire must keep the session identity")
    assert_equal(calls[0].get("conversation_type"), "private", "group acquire must keep the conversation type")
    assert_equal(calls[0].get("max_images"), 3, "strict customer image route must acquire a bounded 1-3 image group")
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
        check_explicit_image_pending_uses_bounded_locate_and_existing_proxy_shape,
        check_normal_pending_uses_body_anchor_bounded_locate_for_offscreen_image,
        check_normal_single_text_keeps_legacy_observe_without_backsearch,
        check_processed_history_texts_do_not_trigger_normal_backsearch,
        check_processed_history_is_skipped_and_first_fresh_text_becomes_anchor,
        check_normal_pending_duplicate_body_anchor_does_not_backsearch_or_proxy,
        check_old_visible_image_does_not_reactivate_on_new_text,
        check_text_preview_recovers_self_image_without_consuming_customer_text,
        check_text_only_capture_has_no_clipboard_or_llm_route,
        check_custom_connector_without_pr_host_does_not_start_desktop_observer,
        check_runtime_accepts_structurally_bound_normal_pending_signal,
        check_structurally_recovered_customer_image_runs_one_current_visual_group_acquire,
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
