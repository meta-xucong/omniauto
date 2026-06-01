"""Regression checks for the WeChat Win32/OCR compatibility adapter."""

from __future__ import annotations

import ast
import os
from pathlib import Path
import sys
import types

from PIL import Image, ImageDraw


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_connector import (  # noqa: E402
    WeChatConnector,
    blind_send_without_ocr,
    compat_args,
    enqueue_simulated_inbound_message,
    guarded_send_confirmation_fallback,
    inject_simulated_inbound_messages,
    interactive_rpa_probe_env,
    parse_json_object,
    pop_simulated_inbound_message,
    rpa_payload_has_invalid_window_handle,
    rpa_payload_needs_interactive_confirmation,
    send_rpa_env,
    verify_send_from_messages,
    wechat_rpa_lock,
)
import apps.wechat_ai_customer_service.adapters.wechat_connector as wechat_connector_module  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar import (  # noqa: E402
    active_chat_matches,
    active_chat_title_cutoff_y,
    adapt_humanized_input_settings,
    auxiliary_wechat_shell_like,
    blind_target_confirmation_guard,
    capabilities_payload,
    chat_header_cutoff_y,
    calculate_send_points,
    classify_message_side,
    clear_existing_input_draft,
    detect_session_subview_back_target,
    detect_blank_render,
    allow_blind_target_confirmation,
    likely_foreign_overlay_capture,
    normalize_chat_title_for_match,
    parse_messages_from_ocr,
    parse_sessions_from_ocr,
    quick_login_like,
    rect_in_input_area,
    rect_in_input_toolbar,
    set_uia_control_value_humanized,
    search_box_point_for_geometry,
    send_rate_decision,
    session_name_matches,
    session_row_click_x,
    session_click_x_for_geometry,
    select_uia_edit_control,
    select_uia_send_button,
    humanized_chunk_text,
    humanized_input_settings,
    input_text_region_state,
    input_region_visual_delta_confirms,
    is_message_noise,
    jitter_input_click_point,
    jitter_send_click_point,
    sendinput_safe_text,
    sendinput_utf16_units,
    merge_message_history_snapshots,
    message_anchor_match_type,
    message_probe_tokens,
    sidecar_message_content_key,
    normalize_anchor_reply_key,
    normalize_send_trigger_mode,
    normalize_wechat_window,
    non_retryable_input_failure,
    type_text_with_sendinput_unicode,
    ensure_visible_wechat_window,
    select_primary_visible_main_window,
    use_passive_probe_mode,
    validate_capture_geometry,
    validate_active_send_target,
    validate_send_geometry,
    scroll_to_latest_before_read_enabled,
    active_ui_action_budget_decision,
    send_input_confirm_attempt_count,
)
import apps.wechat_ai_customer_service.admin_backend.services.wechat_startup_check as startup_check  # noqa: E402
import apps.wechat_ai_customer_service.workflows.preflight as preflight  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.wechat_startup_check import evaluate_wechat_capability  # noqa: E402


class FakeControl:
    def __init__(self, *, name: str, control_type: str, rect: object, class_name: str = "") -> None:
        self.Name = name
        self.ControlTypeName = control_type
        self.BoundingRectangle = rect
        self.ClassName = class_name


class FakeRect:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeValuePattern:
    def __init__(self) -> None:
        self.values: list[str] = []

    def SetValue(self, value: str) -> None:
        self.values.append(str(value))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_parse_sessions_from_ocr() -> None:
    items = [
        {"text": "Q搜索", "confidence": 0.99, "left": 110, "right": 170, "top": 55, "bottom": 80, "center_x": 140, "center_y": 68},
        {"text": "文件传输助手", "confidence": 0.99, "left": 155, "right": 260, "top": 117, "bottom": 140, "center_x": 205, "center_y": 128},
        {"text": "星期三", "confidence": 0.99, "left": 280, "right": 322, "top": 119, "bottom": 138, "center_x": 301, "center_y": 128},
        {"text": "您想今天定，我完全理...", "confidence": 0.96, "left": 154, "right": 316, "top": 143, "bottom": 165, "center_x": 235, "center_y": 154},
        {"text": "许聪", "confidence": 0.99, "left": 154, "right": 195, "top": 198, "bottom": 221, "center_x": 174, "center_y": 209},
        {"text": "[图片]", "confidence": 0.96, "left": 154, "right": 200, "top": 225, "bottom": 247, "center_x": 177, "center_y": 236},
        {"text": "新数据测试", "confidence": 0.99, "left": 154, "right": 247, "top": 361, "bottom": 385, "center_x": 200, "center_y": 373},
        {"text": "[文件] recorder_expor...", "confidence": 0.96, "left": 157, "right": 321, "top": 388, "bottom": 408, "center_x": 239, "center_y": 398},
    ]
    sessions = parse_sessions_from_ocr(items, (641, 919))
    names = [item["name"] for item in sessions]
    assert_true(names == ["文件传输助手", "许聪", "新数据测试"], f"unexpected sessions: {names}")
    assert_true(
        sessions[0].get("preview") == "您想今天定，我完全理...",
        f"session preview should be parsed from the same row: {sessions[0]}",
    )


def test_parse_sessions_detects_visual_unread_red_dot() -> None:
    image = Image.new("RGB", (641, 919), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((124, 112, 144, 132), fill=(250, 81, 81))
    items = [
        {"text": "许聪", "confidence": 0.99, "left": 154, "right": 195, "top": 117, "bottom": 140, "center_x": 174, "center_y": 128},
        {"text": "服务号", "confidence": 0.99, "left": 154, "right": 215, "top": 198, "bottom": 221, "center_x": 184, "center_y": 209},
    ]
    sessions = parse_sessions_from_ocr(items, (641, 919), screenshot=image)
    assert_true(sessions[0].get("unread_badge") == "visual_red_dot", f"red dot should become unread signal: {sessions}")
    assert_true(not sessions[1].get("unread_badge"), f"nearby rows should not inherit unread dot: {sessions}")


def test_parse_sessions_normalizes_truncated_file_transfer() -> None:
    items = [
        {"text": "文件传输..昨天02:57", "confidence": 0.93, "left": 156, "right": 302, "top": 117, "bottom": 140, "center_x": 229, "center_y": 128},
        {"text": "许聪", "confidence": 0.99, "left": 154, "right": 195, "top": 198, "bottom": 221, "center_x": 174, "center_y": 209},
    ]
    sessions = parse_sessions_from_ocr(items, (981, 860))
    names = [item["name"] for item in sessions]
    assert_true(names[:2] == ["文件传输助手", "许聪"], f"truncated file-transfer alias should normalize: {names}")


def test_message_probe_tokens_prefer_semantic_body_after_live_marker() -> None:
    text = "【常规验收20260531_0401_post_aipool_twosession-R1】你好，我预算12万左右，想买省心家用二手车，主要上下班和周末带娃，先看哪类？"
    tokens = message_probe_tokens(text)
    assert_true("预算12万左右" in tokens, f"semantic budget token should be preferred: {tokens}")
    assert_true(any("省心家用" in token or "心家用二手车" in token for token in tokens), f"semantic product token should be preferred: {tokens}")
    assert_true(
        not any("常规验收" in token for token in tokens[:3]),
        f"bracketed live marker should be fallback, not primary: {tokens}",
    )


def test_parse_messages_from_ocr() -> None:
    items = [
        {"text": "新数据测试(2)", "confidence": 0.99, "left": 350, "right": 450, "top": 55, "bottom": 80, "center_x": 400, "center_y": 68},
        {"text": "星期三03:02", "confidence": 0.99, "left": 516, "right": 609, "top": 594, "bottom": 614, "center_x": 562, "center_y": 604},
        {"text": "高频漏采实盘测试 订测试耗材1", "confidence": 0.98, "left": 441, "right": 640, "top": 652, "bottom": 672, "center_x": 540, "center_y": 662},
        {"text": "1个 1元", "confidence": 0.98, "left": 439, "right": 520, "top": 674, "bottom": 698, "center_x": 480, "center_y": 686},
    ]
    messages = parse_messages_from_ocr(items, (641, 919), target="新数据测试")
    assert_true(len(messages) == 1, f"unexpected message count: {messages}")
    assert_true("订测试耗材1" in messages[0]["content"], f"message content not merged: {messages}")
    assert_true(messages[0]["sender"] == "self", f"right-side message should be self: {messages}")


def test_parse_messages_keeps_low_visible_bubble_lines() -> None:
    items = [
        {"text": "长订单第一行", "confidence": 0.98, "left": 440, "right": 610, "top": 712, "bottom": 736, "center_x": 525, "center_y": 724},
        {"text": "末尾价格 324元", "confidence": 0.98, "left": 440, "right": 610, "top": 782, "bottom": 806, "center_x": 525, "center_y": 794},
        {"text": "发送", "confidence": 0.99, "left": 560, "right": 610, "top": 850, "bottom": 876, "center_x": 585, "center_y": 863},
    ]
    messages = parse_messages_from_ocr(items, (641, 919), target="新数据测试")
    content = "\n".join(item["content"] for item in messages)
    assert_true("末尾价格 324元" in content, f"low visible bubble line should be retained: {messages}")
    assert_true("发送" not in content, f"send button noise should still be filtered: {messages}")


def test_parse_messages_classifies_wide_right_bubbles_as_self() -> None:
    items = [
        {"text": "从9万以内、自动挡、倒车影像配置优先、日常家", "confidence": 0.99, "left": 469, "right": 857, "top": 173, "bottom": 196, "center_x": 663, "center_y": 184.5},
        {"text": "用代步这个条件看，可以先排在前面。", "confidence": 0.99, "left": 469, "right": 760, "top": 198, "bottom": 221, "center_x": 614.5, "center_y": 209.5},
        {"text": "顺序排清楚。", "confidence": 0.99, "left": 474, "right": 575, "top": 223, "bottom": 246, "center_x": 524.5, "center_y": 234.5},
    ]
    messages = parse_messages_from_ocr(items, (980, 860), target="文件传输助手")
    assert_true(len(messages) == 1, f"wide right bubble lines should stay merged: {messages}")
    assert_true(messages[0]["sender"] == "self", f"wide right bubble should be self: {messages}")
    assert_true(
        classify_message_side(items[0], width=980) == "self",
        "left-edge cue should classify long self bubbles even when center is near threshold",
    )


def test_history_snapshot_merge_orders_and_dedupes() -> None:
    latest = {
        "messages": [
            {"id": "b03-new", "sender": "self", "content": "[GAP-B03] 连续补充\n第3点"},
            {"id": "b04", "sender": "self", "content": "[GAP-B04] 连续补充\n第4点"},
        ]
    }
    older = {
        "messages": [
            {"id": "b01", "sender": "self", "content": "[GAP-B01] 连续补充\n第1点"},
            {"id": "b02", "sender": "self", "content": "[GAP-B02] 连续补充\n第2点"},
            {"id": "b03-old", "sender": "self", "content": "[GAP-B03]连续补充\n第3点"},
        ]
    }
    merged = merge_message_history_snapshots([latest, older])
    contents = [item["content"] for item in merged]
    assert_true(contents == ["[GAP-B01] 连续补充\n第1点", "[GAP-B02] 连续补充\n第2点", "[GAP-B03]连续补充\n第3点", "[GAP-B04] 连续补充\n第4点"], f"unexpected merged order: {merged}")


def test_anchor_match_supports_content_and_reply_keys() -> None:
    customer_message = {"id": "ocr-different", "sender": "customer", "type": "text", "content": "上一轮\n已经处理"}
    key = sidecar_message_content_key(customer_message)
    assert_true(key.endswith("上一轮已经处理"), f"content key should normalize OCR line breaks: {key!r}")
    assert_true(
        message_anchor_match_type(
            customer_message,
            anchor_ids=set(),
            anchor_content_keys={key},
            reply_content_keys=set(),
        )
        == "message_content_key",
        "customer content key should locate an anchor",
    )
    reply_message = {"id": "reply-1", "sender": "self", "type": "text", "content": "这台可以先重点看，车况和预算都更贴近。"}
    reply_key = normalize_anchor_reply_key("这台可以先重点看车况和预算都更贴近")
    assert_true(
        message_anchor_match_type(
            reply_message,
            anchor_ids=set(),
            anchor_content_keys=set(),
            reply_content_keys={reply_key},
        )
        == "reply_content_key",
        "self reply content key should locate a reply boundary",
    )


def test_message_noise_filters_relative_timestamps() -> None:
    assert_true(is_message_noise("昨天23:57"), "relative timestamp should be filtered")
    assert_true(is_message_noise("今天 08:01"), "relative timestamp with space should be filtered")


def test_connector_helpers() -> None:
    args = compat_args(["sessions", "--fresh"])
    assert_true(args == ["sessions"], f"--fresh should be omitted for compat sidecar: {args}")
    previous = os.environ.get("WECHAT_WIN32_OCR_ARTIFACT_DIR")
    try:
        os.environ["WECHAT_WIN32_OCR_ARTIFACT_DIR"] = "runtime/wechat_debug_artifacts"
        with_artifact = compat_args(["send", "--target", "文件传输助手", "--text", "你好"])
        assert_true(
            with_artifact[-2:] == ["--artifact-dir", "runtime/wechat_debug_artifacts"],
            f"compat args should append artifact dir when configured: {with_artifact}",
        )
    finally:
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_ARTIFACT_DIR", None)
        else:
            os.environ["WECHAT_WIN32_OCR_ARTIFACT_DIR"] = previous
    payload = parse_json_object("library log\n{\"ok\": true, \"nested\": {\"a\": 1}}")
    assert_true(payload == {"ok": True, "nested": {"a": 1}}, f"failed to parse logged JSON: {payload}")
    skip_guard = compat_args(
        ["send", "--target", "文件传输助手", "--text", "你好", "--skip-send-rate-guard"]
    )
    assert_true(
        "--skip-send-rate-guard" in skip_guard,
        f"compat args should preserve loopback guard flag: {skip_guard}",
    )


def test_send_geometry_guard() -> None:
    unsafe = {"width": 650, "height": 1100}
    safe = {"width": 801, "height": 1149}
    assert_true(validate_send_geometry(unsafe)["ok"] is False, "small WeChat window should be blocked")
    points = calculate_send_points(safe)
    assert_true(points["ok"] is True, f"safe geometry should produce points: {points}")
    assert_true(points["input_point"][1] > 900, f"input point should stay in text area: {points}")
    assert_true(points["send_point"][1] > 1000, f"send point should stay near send button: {points}")


def test_send_points_apply_small_safe_jitter() -> None:
    geometry = {"width": 980, "height": 860}
    input_x, input_y = jitter_input_click_point(650, 715, geometry)
    send_x, send_y = jitter_send_click_point(918, 816, geometry)
    assert_true(540 <= input_x <= 892, f"input jitter should remain in input pane: {(input_x, input_y)}")
    assert_true(640 <= input_y <= 778, f"input jitter should remain near draft box: {(input_x, input_y)}")
    assert_true(848 <= send_x <= 960, f"send jitter should remain near send button: {(send_x, send_y)}")
    assert_true(768 <= send_y <= 844, f"send jitter should remain near send button row: {(send_x, send_y)}")


def test_input_region_visual_delta_confirmation() -> None:
    before = {"has_visible_text": False, "ocr_hits": 0, "dark_ratio": 0.001}
    after = {"has_visible_text": True, "ocr_hits": 0, "dark_ratio": 0.025}
    result = input_region_visual_delta_confirms(before, after, {"ok": True, "method": "sendinput_unicode", "typed_chars": 32})
    assert_true(result["ok"] is True, f"visual delta should confirm fresh typed text: {result}")

    stale_before = {"has_visible_text": True, "ocr_hits": 1, "dark_ratio": 0.02}
    stale = input_region_visual_delta_confirms(stale_before, after, {"ok": True, "method": "sendinput_unicode", "typed_chars": 32})
    assert_true(stale["ok"] is False, f"pre-existing input text must not be blindly sent: {stale}")


def test_input_area_token_confirmation_excludes_recent_chat_bubble() -> None:
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    recent_chat_bubble = {"left": 425, "top": 615, "right": 610, "bottom": 655}
    draft_text = {"left": 405, "top": 705, "right": 610, "bottom": 735}
    assert_true(
        rect_in_input_area(recent_chat_bubble, geometry) is False,
        "recent lower chat bubble must not confirm input text",
    )
    assert_true(rect_in_input_area(draft_text, geometry) is True, "draft text inside input area should confirm")


def test_clear_existing_input_draft_noops_when_blank() -> None:
    result = clear_existing_input_draft(
        0,
        points={"input_point": [600, 720], "send_point": [920, 810]},
        geometry={"width": 980, "height": 860},
        before_state={"has_visible_text": False, "reason": "input_region_blank"},
    )
    assert_true(result["ok"] is True and result["cleared"] is False, f"blank input should not trigger select-all: {result}")


def test_send_rate_guard() -> None:
    state = {"events": [{"target": "新数据测试", "at": 100.0}]}
    limited = send_rate_decision(
        state,
        target="新数据测试",
        now_ts=120.0,
        min_interval_seconds=30,
        burst_window_seconds=600,
        burst_limit=5,
    )
    assert_true(limited["ok"] is False and limited["reason"] == "min_interval_not_elapsed", f"expected interval block: {limited}")
    burst = send_rate_decision(
        {"events": [{"target": "新数据测试", "at": value} for value in (100, 150, 200, 250, 300)]},
        target="新数据测试",
        now_ts=350.0,
        min_interval_seconds=0,
        burst_window_seconds=600,
        burst_limit=5,
    )
    assert_true(burst["ok"] is False and burst["reason"] == "burst_limit_reached", f"expected burst block: {burst}")


def test_wechat_rpa_lock_recovers_stale_lock_and_times_out_on_live_lock() -> None:
    import json
    import tempfile
    import time

    original_lock_path = wechat_connector_module.WECHAT_RPA_LOCK_PATH
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "wechat_rpa.lock"
        wechat_connector_module.WECHAT_RPA_LOCK_PATH = lock_path
        try:
            lock_path.write_text(
                json.dumps({"pid": 99999999, "action": "dead", "created_at": time.time()}),
                encoding="utf-8",
            )
            with wechat_rpa_lock("fresh_after_stale", timeout_seconds=1.0, stale_seconds=60.0):
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                assert_true(payload.get("action") == "fresh_after_stale", f"stale lock should be replaced: {payload}")
            assert_true(not lock_path.exists(), "lock should be released after context exit")

            lock_path.write_text(
                json.dumps({"pid": os.getpid(), "action": "live", "created_at": time.time()}),
                encoding="utf-8",
            )
            timed_out = False
            try:
                with wechat_rpa_lock("blocked_by_live", timeout_seconds=0.35, stale_seconds=60.0):
                    pass
            except TimeoutError:
                timed_out = True
            assert_true(timed_out, "live lock should timeout instead of breaking a healthy owner")
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
            assert_true(payload.get("action") == "live", f"live lock should be preserved: {payload}")
        finally:
            wechat_connector_module.WECHAT_RPA_LOCK_PATH = original_lock_path


def test_uia_control_selection_prefers_chatbox() -> None:
    geometry = {"left": 0, "top": 0, "width": 801, "height": 1149}
    edit = FakeControl(name="", control_type="EditControl", rect=FakeRect(345, 970, 770, 1085))
    search = FakeControl(name="搜索", control_type="EditControl", rect=FakeRect(95, 55, 275, 90))
    send = FakeControl(name="发送", control_type="ButtonControl", rect=FakeRect(690, 1082, 766, 1125))
    attach = FakeControl(name="文件", control_type="ButtonControl", rect=FakeRect(440, 1082, 475, 1125))
    assert_true(rect_in_input_area({"left": 345, "top": 970, "right": 770, "bottom": 1085}, geometry), "chat edit should be inside input area")
    assert_true(rect_in_input_toolbar({"left": 690, "top": 1082, "right": 766, "bottom": 1125}, geometry), "send button should be inside toolbar")
    assert_true(select_uia_edit_control([search, edit], geometry) is edit, "chat edit should beat search box")
    assert_true(select_uia_send_button([attach, send], geometry) is send, "send button should be selected by name")


def test_startup_capability_decision() -> None:
    offline = evaluate_wechat_capability(
        {"online": False, "scheme": "wechat_not_ready", "receive": {"ok": False}, "send": {"ok": False}},
        require_send=True,
        module_name="微信自动客服",
    )
    assert_true(offline["ok"] is False and offline["detail"] == "wechat_not_ready", f"offline should block startup: {offline}")
    minimized = evaluate_wechat_capability(
        {
            "online": False,
            "scheme": "win32_ocr_window_geometry_invalid",
            "state": "main_window_geometry_invalid",
            "reason": "window_offscreen_or_minimized",
            "receive": {"ok": False},
            "send": {"ok": False},
        },
        require_send=True,
        module_name="微信自动客服",
    )
    assert_true(
        minimized["ok"] is False
        and minimized["detail"] == "wechat_window_minimized"
        and "未检测到" not in str(minimized.get("message") or ""),
        f"minimized window should not be reported as missing WeChat: {minimized}",
    )

    receive_only = {
        "online": True,
        "scheme": "win32_ocr_receive_only",
        "adapter": "win32_ocr",
        "receive": {"ok": True},
        "send": {"ok": False},
    }
    recorder = evaluate_wechat_capability(receive_only, require_send=False, module_name="AI智能记录员")
    service = evaluate_wechat_capability(receive_only, require_send=True, module_name="微信自动客服")
    assert_true(recorder["ok"] is True, f"recorder can run with receive-only transport: {recorder}")
    assert_true(service["ok"] is False and service["detail"] == "wechat_send_unavailable", f"customer service requires send: {service}")

    wxauto = evaluate_wechat_capability({"online": True, "adapter": "wxauto4", "scheme": "wxauto4"}, require_send=True, module_name="微信自动客服")
    assert_true(wxauto["ok"] is True and wxauto["scheme"] == "wxauto4", f"wxauto4 should pass startup: {wxauto}")


def test_startup_self_check_uses_interactive_probe_env() -> None:
    original_connector = startup_check.WeChatConnector
    observed: dict[str, object] = {}

    class FakeConnector:
        def capabilities(self, *, interactive: bool = False) -> dict[str, object]:
            observed["interactive"] = interactive
            return {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "scheme": "win32_ocr_guarded_click",
                "receive": {"ok": True},
                "send": {"ok": True},
            }

    try:
        startup_check.WeChatConnector = FakeConnector
        result = startup_check.run_wechat_startup_self_check(require_send=True, module_name="微信自动客服")
        assert_true(result["ok"] is True, f"interactive startup self-check should pass: {result}")
        assert_true(observed["interactive"] is True, f"startup should explicitly request interactive probe: {observed}")
    finally:
        startup_check.WeChatConnector = original_connector


def test_connector_interactive_capabilities_passes_probe_env() -> None:
    observed: dict[str, object] = {}

    class StubConnector(WeChatConnector):
        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            observed["args"] = list(args)
            observed["env_overrides"] = dict(env_overrides or {})
            return {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "scheme": "win32_ocr_guarded_click",
                "receive": {"ok": True},
                "send": {"ok": True},
            }

    payload = StubConnector().capabilities(interactive=True)
    env_overrides = observed.get("env_overrides") if isinstance(observed.get("env_overrides"), dict) else {}
    expected_env = interactive_rpa_probe_env()
    assert_true(payload.get("ok") is True, f"interactive capabilities should pass: {payload}")
    assert_true(observed.get("args") == ["capabilities"], f"capabilities action should be used: {observed}")
    assert_true(env_overrides == expected_env, f"interactive probe env should be explicit: {observed}")


def test_connector_interactive_status_passes_probe_env() -> None:
    observed: dict[str, object] = {}

    class StubConnector(WeChatConnector):
        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            observed["args"] = list(args)
            observed["env_overrides"] = dict(env_overrides or {})
            return {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "state": "main_window_compat",
            }

    payload = StubConnector().status(interactive=True)
    env_overrides = observed.get("env_overrides") if isinstance(observed.get("env_overrides"), dict) else {}
    assert_true(payload.get("ok") is True, f"interactive status should pass: {payload}")
    assert_true(observed.get("args") == ["status"], f"status action should be used: {observed}")
    assert_true(env_overrides == interactive_rpa_probe_env(), f"interactive status env should be explicit: {observed}")


def test_connector_interactive_capabilities_recovers_minimized_window() -> None:
    observed: dict[str, object] = {"calls": [], "reserve_calls": 0}

    class StubConnector(WeChatConnector):
        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            calls = observed["calls"]
            assert isinstance(calls, list)
            calls.append({"args": list(args), "env": dict(env_overrides or {})})
            if len(calls) == 1:
                return {
                    "ok": False,
                    "online": False,
                    "adapter": "win32_ocr",
                    "scheme": "win32_ocr_window_geometry_invalid",
                    "state": "main_window_geometry_invalid",
                    "reason": "window_offscreen_or_minimized",
                    "geometry": {"left": -32000, "top": -32000, "width": 199, "height": 34},
                    "receive": {"ok": False},
                    "send": {"ok": False},
                }
            return {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "scheme": "win32_ocr_guarded_click",
                "state": "capabilities_ocr",
                "receive": {"ok": True},
                "send": {"ok": True},
            }

        def call_reserve_sidecar(self, args, *, allow_failure=False, primary_payload=None):  # type: ignore[override]
            observed["reserve_calls"] = int(observed.get("reserve_calls") or 0) + 1
            return {"ok": False, "online": False, "adapter": "wxauto4", "state": "wxauto4_reserve_disabled"}

    payload = StubConnector().capabilities(interactive=True)
    calls = observed["calls"]
    assert isinstance(calls, list)
    assert_true(payload.get("ok") is True and payload.get("adapter") == "win32_ocr", f"interactive recovery should pass: {payload}")
    assert_true(len(calls) == 2, f"recoverable geometry failure should be retried once: {observed}")
    assert_true(calls[0]["env"] == interactive_rpa_probe_env(), f"first interactive call should use restore env: {observed}")
    assert_true(calls[1]["env"] == interactive_rpa_probe_env(), f"retry should keep restore env: {observed}")
    recovery = payload.get("rpa_recovery") if isinstance(payload.get("rpa_recovery"), dict) else {}
    assert_true(recovery.get("ok") is True, f"recovery diagnostics should be attached: {payload}")
    assert_true(observed.get("reserve_calls") == 0, f"wxauto4 reserve should not run after RPA recovery: {observed}")


def test_connector_passive_status_does_not_recover_minimized_window() -> None:
    observed: dict[str, object] = {"calls": [], "reserve_calls": 0}

    class StubConnector(WeChatConnector):
        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            calls = observed["calls"]
            assert isinstance(calls, list)
            calls.append({"args": list(args), "env": dict(env_overrides or {})})
            return {
                "ok": False,
                "online": False,
                "adapter": "win32_ocr",
                "state": "main_window_geometry_invalid",
                "reason": "window_offscreen_or_minimized",
                "geometry": {"left": -32000, "top": -32000, "width": 199, "height": 34},
            }

        def call_reserve_sidecar(self, args, *, allow_failure=False, primary_payload=None):  # type: ignore[override]
            observed["reserve_calls"] = int(observed.get("reserve_calls") or 0) + 1
            return {"ok": False, "online": False, "adapter": "wxauto4", "state": "wxauto4_reserve_disabled"}

    payload = StubConnector().status(interactive=False)
    calls = observed["calls"]
    assert isinstance(calls, list)
    assert_true(payload.get("ok") is False, f"passive status should stay passive on recoverable failure: {payload}")
    assert_true(len(calls) == 1 and calls[0]["env"] == {}, f"passive status should not do interactive retry: {observed}")
    assert_true(observed.get("reserve_calls") == 1, f"reserve status should still be recorded for diagnostics: {observed}")


def test_connector_interactive_status_recovers_blank_render_with_tray_redraw() -> None:
    observed: dict[str, object] = {"calls": [], "reserve_calls": 0}

    class StubConnector(WeChatConnector):
        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            calls = observed["calls"]
            assert isinstance(calls, list)
            calls.append({"args": list(args), "env": dict(env_overrides or {})})
            if len(calls) == 1:
                return {
                    "ok": False,
                    "online": False,
                    "adapter": "win32_ocr",
                    "scheme": "win32_ocr_blank_render",
                    "state": "blank_render_detected",
                    "reason": "blank_render",
                    "render_probe": {"detected": True, "reason": "blank_white_like"},
                }
            if list(args) == ["recover-render"]:
                return {
                    "ok": True,
                    "online": True,
                    "adapter": "win32_ocr",
                    "state": "main_window_compat",
                    "render_recovery": {"ok": True, "attempted": True},
                }
            return {
                "ok": True,
                "online": True,
                "adapter": "win32_ocr",
                "state": "main_window_compat",
            }

        def call_reserve_sidecar(self, args, *, allow_failure=False, primary_payload=None):  # type: ignore[override]
            observed["reserve_calls"] = int(observed.get("reserve_calls") or 0) + 1
            return {"ok": False, "online": False, "adapter": "wxauto4", "state": "wxauto4_reserve_disabled"}

    payload = StubConnector().status(interactive=True)
    calls = observed["calls"]
    assert isinstance(calls, list)
    assert_true(payload.get("ok") is True, f"blank render interactive recovery should pass: {payload}")
    assert_true(
        [item["args"] for item in calls] == [["status"], ["recover-render"], ["status"]],
        f"blank render should run explicit tray redraw before retry: {observed}",
    )
    recovery = payload.get("rpa_recovery") if isinstance(payload.get("rpa_recovery"), dict) else {}
    assert_true(
        recovery.get("mode") == "interactive_blank_render_tray_redraw",
        f"blank render recovery mode should be explicit: {payload}",
    )
    assert_true(observed.get("reserve_calls") == 0, f"wxauto4 reserve should not run after blank-render recovery: {observed}")


def test_startup_evaluates_nested_rpa_geometry_failure() -> None:
    payload = {
        "ok": False,
        "online": False,
        "adapter": "none",
        "scheme": "wechat_not_ready",
        "state": "no_supported_wechat_transport",
        "primary_status": {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "scheme": "win32_ocr_window_geometry_invalid",
            "state": "main_window_geometry_invalid",
            "reason": "window_offscreen_or_minimized",
            "geometry": {"left": -32000, "top": -32000, "width": 199, "height": 34},
        },
        "reserve_status": {"ok": False, "online": False, "adapter": "wxauto4", "state": "wxauto4_reserve_disabled"},
    }
    decision = evaluate_wechat_capability(payload, require_send=True, module_name="微信自动客服")
    assert_true(decision.get("detail") == "wechat_window_minimized", f"nested RPA geometry reason should be preserved: {decision}")
    assert_true("未检测到" not in str(decision.get("message") or ""), f"minimized window should not be called missing: {decision}")
    assert_true(rpa_payload_needs_interactive_confirmation(payload["primary_status"]) is True, "recoverable geometry helper should trigger")
    blank_payload = {
        "ok": False,
        "online": False,
        "adapter": "win32_ocr",
        "scheme": "win32_ocr_blank_render",
        "state": "blank_render_detected",
        "reason": "blank_render",
    }
    assert_true(
        rpa_payload_needs_interactive_confirmation(blank_payload) is True,
        "blank render should be classified as interactively recoverable",
    )


def test_preflight_uses_interactive_status_probe() -> None:
    observed: dict[str, object] = {}
    original_connector = preflight.WeChatConnector
    original_build_review_queue = preflight.build_review_queue
    original_load_config = preflight.load_config
    original_check_local_config = preflight.check_local_config
    original_parse_targets = preflight.parse_targets
    original_resolve_path = preflight.resolve_path

    class Target:
        name = "文件传输助手"

    class FakeConnector:
        sidecar_python = Path(__file__)
        sidecar_script = Path(__file__)
        compat_sidecar_script = Path(__file__)

        def wxauto4_reserve_enabled(self) -> bool:
            return False

        def status(self, *, interactive: bool = False) -> dict[str, object]:
            observed["status_interactive"] = interactive
            return {"ok": True, "online": True, "adapter": "win32_ocr", "compat_reason": "rpa_primary"}

        def list_sessions(self) -> dict[str, object]:
            observed["list_sessions_called"] = True
            return {"ok": True, "sessions": [{"name": "文件传输助手"}]}

    try:
        preflight.WeChatConnector = FakeConnector  # type: ignore[assignment]
        preflight.build_review_queue = lambda **_kwargs: {"counts": {}}  # type: ignore[assignment]
        preflight.load_config = lambda _path: {"rpa_humanized_send": {}}  # type: ignore[assignment]
        preflight.check_local_config = lambda _path, _config: {"checks": [], "warnings": [], "errors": []}  # type: ignore[assignment]
        preflight.parse_targets = lambda _config: [Target()]  # type: ignore[assignment]
        preflight.resolve_path = lambda _value: Path(__file__)  # type: ignore[assignment]
        result = preflight.run_preflight(Path("fake.json"), extra_targets=[], skip_wechat=False)
    finally:
        preflight.WeChatConnector = original_connector
        preflight.build_review_queue = original_build_review_queue
        preflight.load_config = original_load_config
        preflight.check_local_config = original_check_local_config
        preflight.parse_targets = original_parse_targets
        preflight.resolve_path = original_resolve_path

    assert_true(result.get("ok") is True, f"preflight should pass with interactive RPA status: {result}")
    assert_true(observed.get("status_interactive") is True, f"preflight should request interactive status: {observed}")
    assert_true(observed.get("list_sessions_called") is True, f"preflight should still validate sessions: {observed}")


def test_adaptive_window_points() -> None:
    compact = {"width": 760, "height": 780}
    wide = {"width": 1600, "height": 980}
    compact_search = search_box_point_for_geometry(compact)
    wide_search = search_box_point_for_geometry(wide)
    compact_session_x = session_click_x_for_geometry(compact)
    wide_session_x = session_click_x_for_geometry(wide)
    assert_true(90 <= compact_search[0] <= 170, f"compact search x should stay in sidebar area: {compact_search}")
    assert_true(90 <= wide_search[0] <= 170, f"wide search x should stay in sidebar area: {wide_search}")
    assert_true(compact_session_x <= 330, f"compact session click x should stay inside session list: {compact_session_x}")
    assert_true(wide_session_x <= 330, f"wide session click x should stay inside session list: {wide_session_x}")
    assert_true(chat_header_cutoff_y(780) >= 90, "header cutoff should respect baseline minimum")
    assert_true(chat_header_cutoff_y(1400) <= 150, "header cutoff should be capped for large windows")


def test_session_match_and_click_x() -> None:
    geometry = {"width": 980, "height": 860}
    default_x = session_click_x_for_geometry(geometry)
    session = {"name": "文件传输助手", "left": 152, "right": 276, "center_y": 292}
    click_x = session_row_click_x(session, geometry, default_x=default_x)
    assert_true(170 <= click_x <= 352, f"session click should stay inside sidebar: {click_x}")
    assert_true(session_name_matches("文件传输助手", "文件传输助手", exact=True), "exact match should pass")
    assert_true(session_name_matches("文件传输助手(2)", "文件传输助手", exact=False), "fuzzy match should pass")
    assert_true(session_name_matches("File Transfer Assistant", "文件传输助手", exact=True), "alias exact match should pass")
    assert_true(session_name_matches("新数据测试昨天10:39", "新数据测试", exact=True), "OCR-merged session time should be stripped")
    assert_true(session_name_matches("许聪星期四", "许聪", exact=True), "OCR-merged weekday suffix should be stripped")
    assert_true(session_name_matches("文件传输站", "文件传输助手", exact=True) is False, "unrelated exact mismatch should fail")


def test_active_chat_matches_file_transfer_alias() -> None:
    items = [
        {"text": "File Transfer Assistant", "confidence": 0.99, "left": 412, "right": 668, "top": 62, "bottom": 92, "center_x": 540, "center_y": 76},
    ]
    ok = active_chat_matches(items, (980, 860), target="文件传输助手", exact=True)
    assert_true(ok, "header alias should match file transfer target")


def test_active_chat_matches_wrapped_title_text() -> None:
    items = [
        {"text": "与文件传输助手的聊天", "confidence": 0.99, "left": 420, "right": 705, "top": 108, "bottom": 144, "center_x": 562, "center_y": 126},
    ]
    ok = active_chat_matches(items, (980, 860), target="文件传输助手", exact=True)
    assert_true(ok, "wrapped title text should match exact target")
    assert_true(
        normalize_chat_title_for_match("与文件传输助手的聊天") == normalize_chat_title_for_match("文件传输助手"),
        "wrapped title normalization should collapse to target identity",
    )


def test_quick_login_detection() -> None:
    items = [
        {"text": "Meta_xc", "confidence": 0.99, "left": 120, "right": 200, "top": 100, "bottom": 128, "center_x": 160, "center_y": 114},
        {"text": "进入微信", "confidence": 0.99, "left": 90, "right": 220, "top": 280, "bottom": 322, "center_x": 155, "center_y": 301},
        {"text": "仅传输文件", "confidence": 0.99, "left": 170, "right": 255, "top": 342, "bottom": 368, "center_x": 212, "center_y": 355},
        {"text": "切换账号", "confidence": 0.99, "left": 70, "right": 150, "top": 342, "bottom": 368, "center_x": 110, "center_y": 355},
    ]
    geometry = {"width": 368, "height": 484}
    assert_true(quick_login_like(items, geometry=geometry), "quick-login card should be detected")
    assert_true(quick_login_like(items, geometry={"width": 980, "height": 860}) is False, "large window should not be treated as quick-login")


def test_service_subview_back_target_detection() -> None:
    items = [
        {"text": "<服务号", "confidence": 0.99, "left": 104, "right": 188, "top": 112, "bottom": 144, "center_x": 146, "center_y": 128},
        {"text": "丰巢", "confidence": 0.99, "left": 154, "right": 204, "top": 162, "bottom": 188, "center_x": 179, "center_y": 175},
    ]
    point = detect_session_subview_back_target(items, (981, 860))
    assert_true(isinstance(point, dict), f"service subview back point should be detected: {point}")
    assert_true(70 <= int(point.get("x") or 0) <= 170, f"back x should stay in sidebar header: {point}")


def test_connector_rpa_priority_and_wxauto_reserve_toggle() -> None:
    class StubConnector(WeChatConnector):
        def __init__(self, *, reserve_enabled: bool, rpa_ok: bool, reserve_ok: bool) -> None:
            super().__init__()
            self._reserve_enabled = reserve_enabled
            self._rpa_ok = rpa_ok
            self._reserve_ok = reserve_ok

        def wxauto4_reserve_enabled(self) -> bool:
            return self._reserve_enabled

        def call_compat_sidecar(self, args, *, allow_failure=False, primary_payload=None, env_overrides=None):  # type: ignore[override]
            if self._rpa_ok:
                return {"ok": True, "online": True, "adapter": "win32_ocr", "state": "stub_rpa_ok"}
            return {"ok": False, "online": False, "adapter": "win32_ocr", "state": "stub_rpa_fail"}

        def call_reserve_sidecar(self, args, *, allow_failure=False, primary_payload=None):  # type: ignore[override]
            if self._reserve_enabled is False:
                return {
                    "ok": False,
                    "online": False,
                    "adapter": "wxauto4",
                    "state": "wxauto4_reserve_disabled",
                }
            if self._reserve_ok:
                return {"ok": True, "online": True, "adapter": "wxauto4", "state": "stub_wxauto_ok"}
            return {"ok": False, "online": False, "adapter": "wxauto4", "state": "stub_wxauto_fail"}

    rpa_primary = StubConnector(reserve_enabled=False, rpa_ok=True, reserve_ok=False)
    rpa_status = rpa_primary.status()
    assert_true(rpa_status["adapter"] == "win32_ocr", f"RPA should be primary adapter: {rpa_status}")

    reserve_disabled = StubConnector(reserve_enabled=False, rpa_ok=False, reserve_ok=True)
    disabled_status = reserve_disabled.status()
    assert_true(
        disabled_status.get("wxauto4_reserve_status", {}).get("state") == "wxauto4_reserve_disabled",
        f"reserve should remain disabled by default: {disabled_status}",
    )

    reserve_enabled = StubConnector(reserve_enabled=True, rpa_ok=False, reserve_ok=True)
    reserve_status = reserve_enabled.status()
    assert_true(reserve_status.get("adapter") == "wxauto4", f"wxauto4 reserve should activate only when enabled: {reserve_status}")


def test_send_verify_handles_split_multiline_messages() -> None:
    expected = "你好，在吗？\n[live-regression:20260523180041:1:1]"
    payload = {
        "messages": [
            {"sender": "unknown", "content": "你好，在吗？"},
            {"sender": "self", "content": "[live-regression:20260523180041:1:1]"},
        ]
    }
    assert_true(
        verify_send_from_messages(payload, expected_text=expected),
        "split multiline messages should be considered verified",
    )


def test_blind_send_without_ocr_verification_fallback() -> None:
    send = {
        "ok": True,
        "send_result": {
            "post_send_guard": {"reason": "target_confirm_skipped_no_ocr"},
        },
    }
    messages = {"ok": True, "state": "messages_ocr", "messages": []}
    assert_true(
        blind_send_without_ocr(send, messages),
        "blind send fallback should accept empty-message verification payload",
    )


def test_guarded_send_confirmation_fallback() -> None:
    send = {
        "ok": True,
        "send_result": {
            "ok": True,
            "post_send_guard": {"ok": True, "reason": "target_confirmed"},
            "click": {
                "paste": {
                    "ok": True,
                    "confirmed_by": "clipboard_copyback",
                }
            },
        },
    }
    messages = {"ok": True, "state": "messages_ocr", "messages": []}
    assert_true(
        guarded_send_confirmation_fallback(send, messages),
        "guard-confirmed send should allow fallback when OCR replay misses fresh bubble",
    )
    visual_send = {
        "ok": True,
        "send_result": {
            "ok": True,
            "post_send_guard": {"ok": True, "reason": "target_confirmed"},
            "click": {
                "paste": {
                    "ok": True,
                    "confirmed_by": "input_area_visual_delta_fast",
                }
            },
        },
    }
    assert_true(
        guarded_send_confirmation_fallback(visual_send, messages),
        "visual-delta fast confirmation should be treated as guarded send confirmation",
    )
    blocked = {"ok": True, "state": "login_window_detected", "messages": []}
    assert_true(
        guarded_send_confirmation_fallback(send, blocked) is False,
        "guard fallback should not pass when login window is detected",
    )


def test_fast_send_confirmation_skips_slow_message_read_when_guard_is_strong() -> None:
    class FastVerifyConnector(WeChatConnector):
        def __init__(self) -> None:
            self.messages_called = 0

        def send_text(self, target: str, text: str, exact: bool = True, *, skip_send_rate_guard: bool = False) -> dict:
            return {
                "ok": True,
                "send_result": {
                    "ok": True,
                    "post_send_guard": {"ok": True, "reason": "target_confirmed"},
                    "click": {"paste": {"ok": True, "confirmed_by": "ocr_input_area"}},
                },
            }

        def get_messages(self, target: str, exact: bool = True, history_load_times: int = 0) -> dict:
            self.messages_called += 1
            return {"ok": True, "state": "messages_ocr", "messages": []}

    previous = os.environ.get("WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION")
    os.environ["WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION"] = "1"
    try:
        connector = FastVerifyConnector()
        result = connector.send_text_and_verify("文件传输助手", "您好")
        assert_true(bool(result.get("verified")), "fast confirmation should verify strong guarded sends")
        assert_true(
            result.get("verification_mode") == "send_guard_confirmed_fast",
            "fast confirmation should be explicitly labeled",
        )
        assert_true(connector.messages_called == 0, "fast confirmation should skip full OCR message read")
    finally:
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION", None)
        else:
            os.environ["WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION"] = previous


def test_invalid_window_handle_is_hard_stop_not_recovery() -> None:
    payload = {
        "ok": False,
        "online": False,
        "state": "win32_ocr_failed",
        "error": "error(1400, 'GetWindowRect', '无效的窗口句柄。')",
    }
    assert_true(
        rpa_payload_has_invalid_window_handle(payload),
        "invalid Win32 hwnd should be classified explicitly",
    )
    assert_true(
        rpa_payload_needs_interactive_confirmation(payload) is False,
        "invalid hwnd should not be treated as a recoverable interactive probe",
    )


def test_send_text_invalid_window_handle_skips_wxauto4_reserve() -> None:
    class InvalidHwndConnector(WeChatConnector):
        def __init__(self) -> None:
            super().__init__()
            self.reserve_calls = 0

        def call_compat_sidecar(self, args, allow_failure=False, env_overrides=None):  # type: ignore[override]
            return {
                "ok": False,
                "online": False,
                "state": "win32_ocr_failed",
                "error": "error(1400, 'GetWindowRect', '无效的窗口句柄。')",
            }

        def call_reserve_sidecar(self, args, *, allow_failure=False, primary_payload=None):  # type: ignore[override]
            self.reserve_calls += 1
            return {"ok": True, "online": True, "adapter": "wxauto4", "state": "unexpected_reserve_call"}

    connector = InvalidHwndConnector()
    result = connector.send_text("文件传输助手", "您好", exact=True)
    assert_true(result.get("ok") is False, f"invalid hwnd send should fail: {result}")
    assert_true(result.get("risk_stop_recommended") is True, f"invalid hwnd should request hard stop: {result}")
    assert_true(
        result.get("risk_stop_reason") == "win32_invalid_window_handle",
        f"invalid hwnd reason should be explicit: {result}",
    )
    assert_true(connector.reserve_calls == 0, f"wxauto4 reserve should be skipped after hard stop: {result}")
    assert_true(
        result.get("wxauto4_reserve_status", {}).get("state") == "wxauto4_reserve_skipped_due_to_rpa_hard_stop",
        f"reserve skip should be recorded: {result}",
    )


def test_foreign_overlay_capture_filter_and_blind_target_gate() -> None:
    foreign = [
        {"text": "apps/wechat_ai_customer_servic"},
        {"text": "15个文件已更改+1550-351"},
        {"text": "New project"},
    ]
    assert_true(likely_foreign_overlay_capture(foreign), "codex overlay OCR should be recognized as foreign capture")
    assert_true(allow_blind_target_confirmation("文件传输助手"), "file transfer should allow blind target confirmation")
    assert_true(
        allow_blind_target_confirmation("许聪") is False,
        "non-file-transfer sessions should not allow blind target confirmation",
    )


def test_blind_target_confirmation_uses_sidebar_match_when_title_missing() -> None:
    items = [
        {"text": "文件传输助手", "confidence": 0.99, "left": 156, "right": 272, "top": 130, "bottom": 152, "center_x": 214, "center_y": 141},
        {"text": "周六下午三点到店", "confidence": 0.98, "left": 498, "right": 664, "top": 642, "bottom": 672, "center_x": 581, "center_y": 657},
    ]
    guard = blind_target_confirmation_guard(
        target="文件传输助手",
        exact=True,
        ocr_items=items,
        image_size=(980, 860),
        geometry={"width": 980, "height": 860},
        screenshot_path="",
    )
    assert_true(bool(guard.get("ok")), f"file-transfer blind fallback should pass when sidebar match exists: {guard}")
    assert_true(
        guard.get("reason") == "target_confirm_skipped_title_ocr_drift",
        f"fallback reason should be explicit for diagnostics: {guard}",
    )
    blocked = blind_target_confirmation_guard(
        target="许聪",
        exact=True,
        ocr_items=items,
        image_size=(980, 860),
        geometry={"width": 980, "height": 860},
        screenshot_path="",
    )
    assert_true(bool(blocked.get("ok")) is False, f"non-file-transfer target should not use blind fallback: {blocked}")


def test_active_chat_cutoff_extends_above_sidebar_cutoff() -> None:
    height = 860
    assert_true(
        active_chat_title_cutoff_y(height) > chat_header_cutoff_y(height),
        "active chat title cutoff should be looser than sidebar/message cutoff",
    )


def test_file_transfer_simulated_inbound_fallback() -> None:
    enqueue_simulated_inbound_message(target="文件传输助手", text="回环测试消息")
    payload = {"ok": True, "state": "messages_ocr", "messages": []}
    patched = inject_simulated_inbound_messages(payload, target="文件传输助手")
    messages = patched.get("messages") if isinstance(patched, dict) else []
    assert_true(isinstance(messages, list) and len(messages) == 1, f"loopback fallback should inject one message: {patched}")
    assert_true(messages[0].get("source_adapter") == "win32_loopback", f"injected message should be loopback typed: {messages}")
    enqueue_simulated_inbound_message(target="文件传输助手", text="回环测试消息2")
    with_existing = inject_simulated_inbound_messages(
        {"ok": True, "state": "messages_ocr", "messages": [{"id": "legacy", "content": "旧消息", "sender": "self"}]},
        target="文件传输助手",
    )
    with_existing_messages = with_existing.get("messages") if isinstance(with_existing, dict) else []
    assert_true(
        isinstance(with_existing_messages, list) and len(with_existing_messages) == 2,
        f"loopback fallback should append even when OCR has existing messages: {with_existing}",
    )
    assert_true(
        with_existing_messages[-1].get("source_adapter") == "win32_loopback",
        f"appended fallback should stay loopback typed: {with_existing_messages}",
    )
    untouched = inject_simulated_inbound_messages({"ok": True, "state": "messages_ocr", "messages": []}, target="许聪")
    assert_true(untouched.get("messages") == [], f"non-file-transfer target should not receive loopback fallback: {untouched}")


def test_fast_confirmation_still_enqueues_file_transfer_loopback() -> None:
    while pop_simulated_inbound_message("文件传输助手") is not None:
        pass

    class FastConfirmConnector(WeChatConnector):
        def __init__(self) -> None:
            super().__init__()
            self.messages_reads = 0

        def send_text(self, target: str, text: str, exact: bool = True, *, skip_send_rate_guard: bool = False) -> dict:
            assert_true(skip_send_rate_guard, "file-transfer loopback should skip the transport rate guard only for simulated inbound")
            return {
                "ok": True,
                "send_result": {
                    "ok": True,
                    "post_send_guard": {"ok": True, "reason": "target_confirmed"},
                    "click": {"paste": {"ok": True, "confirmed_by": "ocr_input_area"}},
                },
            }

        def get_messages(self, target: str, exact: bool = True, **_kwargs) -> dict:
            self.messages_reads += 1
            return {"ok": True, "state": "messages_ocr", "messages": []}

    previous = os.environ.get("WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION")
    try:
        os.environ["WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION"] = "1"
        connector = FastConfirmConnector()
        result = connector.send_text_and_verify(
            "文件传输助手",
            "快速确认回环测试",
            exact=True,
            simulate_inbound_file_transfer=True,
        )
        assert_true(result.get("verified") is True, f"fast confirmation should verify send: {result}")
        assert_true(connector.messages_reads == 0, "fast confirmation should still skip slow message reads")
        patched = inject_simulated_inbound_messages(
            {"ok": True, "state": "messages_ocr", "messages": []},
            target="文件传输助手",
        )
        messages = patched.get("messages") if isinstance(patched, dict) else []
        assert_true(isinstance(messages, list) and len(messages) == 1, f"loopback message should be enqueued: {patched}")
        assert_true(messages[0].get("content") == "快速确认回环测试", f"unexpected loopback content: {messages}")
    finally:
        while pop_simulated_inbound_message("文件传输助手") is not None:
            pass
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION", None)
        else:
            os.environ["WECHAT_WIN32_OCR_FAST_SEND_CONFIRMATION"] = previous


def test_passive_probe_mode_toggle() -> None:
    previous = os.environ.get("WECHAT_WIN32_OCR_PASSIVE_PROBE")
    try:
        os.environ["WECHAT_WIN32_OCR_PASSIVE_PROBE"] = "1"
        assert_true(use_passive_probe_mode("status"), "status should support passive probe mode")
        assert_true(use_passive_probe_mode("capabilities"), "capabilities should support passive probe mode")
        assert_true(use_passive_probe_mode("sessions"), "sessions should support passive probe mode")
        assert_true(use_passive_probe_mode("send") is False, "send action should never use passive probe mode")
        os.environ["WECHAT_WIN32_OCR_PASSIVE_PROBE"] = "0"
        assert_true(use_passive_probe_mode("status") is False, "env override should disable passive probe mode")
    finally:
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_PASSIVE_PROBE", None)
        else:
            os.environ["WECHAT_WIN32_OCR_PASSIVE_PROBE"] = previous


def test_low_disturbance_read_and_action_budget_defaults() -> None:
    previous_scroll = os.environ.get("WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ")
    previous_budget = os.environ.get("WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENABLED")
    try:
        os.environ.pop("WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ", None)
        assert_true(
            scroll_to_latest_before_read_enabled() is False,
            "message reads should not scroll to latest before every capture by default",
        )
        os.environ["WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ"] = "1"
        assert_true(scroll_to_latest_before_read_enabled() is True, "explicit env override should keep compatibility")
        os.environ["WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENABLED"] = "0"
        decision = active_ui_action_budget_decision(action="unit_test", reserve=False)
        assert_true(decision.get("ok") is True and decision.get("enabled") is False, "UI action budget should be disable-able for diagnostics")
    finally:
        if previous_scroll is None:
            os.environ.pop("WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ", None)
        else:
            os.environ["WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ"] = previous_scroll
        if previous_budget is None:
            os.environ.pop("WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENABLED", None)
        else:
            os.environ["WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENABLED"] = previous_budget


def test_passive_probe_window_discovery_is_non_interactive() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    original_probe = sidecar_mod.probe_wechat_windows
    original_focus = sidecar_mod.focus_wechat_window
    original_restore = sidecar_mod.restore_wechat_window
    calls = {"focus": 0, "restore": 0}
    try:
        def fake_probe():
            return {
                "visible_main_windows": [{"hwnd": 1}],
                "windows": [{"hwnd": 1}],
            }

        def fake_focus(_probe):
            calls["focus"] += 1
            return {"hwnd": 1}

        def fake_restore(_probe):
            calls["restore"] += 1
            return {"hwnd": 1}

        sidecar_mod.probe_wechat_windows = fake_probe
        sidecar_mod.focus_wechat_window = fake_focus
        sidecar_mod.restore_wechat_window = fake_restore

        passive_probe = ensure_visible_wechat_window(interactive=False)
        active_probe = ensure_visible_wechat_window(interactive=True)
        assert_true(bool(passive_probe.get("visible_main_windows")), f"passive probe should still discover windows: {passive_probe}")
        assert_true(bool(active_probe.get("visible_main_windows")), f"interactive probe should discover windows: {active_probe}")
        assert_true(calls["focus"] == 1, f"focus should be skipped for passive and called once for interactive: {calls}")
        assert_true(calls["restore"] == 0, f"restore should not run when visible window exists: {calls}")
    finally:
        sidecar_mod.probe_wechat_windows = original_probe
        sidecar_mod.focus_wechat_window = original_focus
        sidecar_mod.restore_wechat_window = original_restore


def test_interactive_probe_restores_offscreen_visible_window() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    originals = {
        "probe_wechat_windows": sidecar_mod.probe_wechat_windows,
        "focus_wechat_window": sidecar_mod.focus_wechat_window,
        "restore_wechat_window": sidecar_mod.restore_wechat_window,
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "time_sleep": sidecar_mod.time.sleep,
    }
    calls = {"probe": 0, "focus": 0, "restore": 0}

    def fake_probe():
        calls["probe"] += 1
        if calls["probe"] == 1:
            return {
                "windows": [{"hwnd": 1001, "title": "微信"}],
                "visible_main_windows": [{"hwnd": 1001, "title": "微信"}],
            }
        return {
            "windows": [{"hwnd": 1002, "title": "微信"}],
            "visible_main_windows": [{"hwnd": 1002, "title": "微信"}],
        }

    def fake_get_window_geometry(hwnd):
        if int(hwnd) == 1001:
            return {"left": -32000, "top": -32000, "right": -31801, "bottom": -31966, "width": 199, "height": 34}
        return {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}

    def fake_focus(probe):
        calls["focus"] += 1
        return dict((probe.get("visible_main_windows") or [{}])[0])

    def fake_restore(_probe):
        calls["restore"] += 1
        return {"hwnd": 1001, "title": "微信"}

    try:
        sidecar_mod.probe_wechat_windows = fake_probe
        sidecar_mod.get_window_geometry = fake_get_window_geometry
        sidecar_mod.focus_wechat_window = fake_focus
        sidecar_mod.restore_wechat_window = fake_restore
        sidecar_mod.time.sleep = lambda *_args, **_kwargs: None
        probe = ensure_visible_wechat_window(interactive=True)
        assert_true(calls["restore"] == 1, f"offscreen visible window should trigger restore: {calls}")
        assert_true(calls["focus"] == 1, f"restored window should be focused: {calls}")
        assert_true(
            int((probe.get("visible_main_windows") or [{}])[0].get("hwnd") or 0) == 1002,
            f"probe should refresh after restore: {probe}",
        )
    finally:
        sidecar_mod.probe_wechat_windows = originals["probe_wechat_windows"]
        sidecar_mod.focus_wechat_window = originals["focus_wechat_window"]
        sidecar_mod.restore_wechat_window = originals["restore_wechat_window"]
        sidecar_mod.get_window_geometry = originals["get_window_geometry"]
        sidecar_mod.time.sleep = originals["time_sleep"]


def test_capture_geometry_guard_and_window_selection() -> None:
    bad_geometry = {"left": -32000, "top": -32000, "width": 199, "height": 34}
    good_geometry = {"left": 0, "top": 0, "width": 980, "height": 860}
    bad_check = validate_capture_geometry(bad_geometry)
    good_check = validate_capture_geometry(good_geometry)
    assert_true(bad_check.get("ok") is False, f"offscreen/tiny geometry should be rejected: {bad_check}")
    assert_true(good_check.get("ok") is True, f"normal geometry should pass capture guard: {good_check}")

    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    original_get_window_geometry = sidecar_mod.get_window_geometry
    try:
        geometry_map = {
            1001: {"left": -32000, "top": -32000, "width": 199, "height": 34},
            1002: {"left": 0, "top": 0, "width": 980, "height": 860},
        }

        def fake_get_window_geometry(hwnd):
            return geometry_map.get(int(hwnd), {"left": 0, "top": 0, "width": 0, "height": 0})

        sidecar_mod.get_window_geometry = fake_get_window_geometry
        selected = select_primary_visible_main_window(
            {
                "visible_main_windows": [
                    {"hwnd": 1001, "title": "微信"},
                    {"hwnd": 1002, "title": "微信"},
                ]
            }
        )
        assert_true(int((selected or {}).get("hwnd") or 0) == 1002, f"selection should prefer healthy window geometry: {selected}")
    finally:
        sidecar_mod.get_window_geometry = original_get_window_geometry


def test_window_selection_prefers_real_wechat_title_over_weixin_shell() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    original_get_window_geometry = sidecar_mod.get_window_geometry
    original_activate = sidecar_mod.activate_window
    original_foreground_match = sidecar_mod.foreground_window_matches_target
    calls: list[int] = []
    try:
        sidecar_mod.get_window_geometry = lambda hwnd: {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
        sidecar_mod.activate_window = lambda hwnd: calls.append(int(hwnd))
        sidecar_mod.foreground_window_matches_target = lambda hwnd: {
            "ok": True,
            "reason": "foreground_matches_target",
            "hwnd": int(hwnd or 0),
            "foreground_hwnd": int(hwnd or 0),
        }
        probe = {
            "windows": [
                {"hwnd": 1001, "title": "Weixin", "class_name": "Qt51514QWindowIcon", "visible": True},
                {"hwnd": 1002, "title": "微信", "class_name": "Qt51514QWindowIcon", "visible": True},
            ],
            "visible_main_windows": [
                {"hwnd": 1001, "title": "Weixin", "class_name": "Qt51514QWindowIcon", "visible": True},
                {"hwnd": 1002, "title": "微信", "class_name": "Qt51514QWindowIcon", "visible": True},
            ],
        }
        selected = select_primary_visible_main_window(probe)
        assert_true(int((selected or {}).get("hwnd") or 0) == 1002, f"should prefer real 微信 window: {selected}")
        focused = sidecar_mod.focus_wechat_window(probe)
        assert_true(int((focused or {}).get("hwnd") or 0) == 1002, f"focus should use selected real window: {focused}")
        restored = sidecar_mod.restore_wechat_window(probe)
        assert_true(int((restored or {}).get("hwnd") or 0) == 1002, f"restore should prefer real window: {restored}")
        assert_true(calls == [1002, 1002], f"unexpected activation calls: {calls}")
    finally:
        sidecar_mod.get_window_geometry = original_get_window_geometry
        sidecar_mod.activate_window = original_activate
        sidecar_mod.foreground_window_matches_target = original_foreground_match


def test_auxiliary_wechat_shell_is_blocked() -> None:
    shell = auxiliary_wechat_shell_like([{"text": "Weixin"}], geometry={"width": 784, "height": 688})
    assert_true(shell.get("detected") is True, f"title-only shell should be blocked: {shell}")
    chat = auxiliary_wechat_shell_like(
        [{"text": "文件传输助手"}, {"text": "Q搜索"}, {"text": "您好"}],
        geometry={"width": 784, "height": 688},
    )
    assert_true(chat.get("detected") is False, f"real chat surface should pass: {chat}")


def test_normalize_wechat_window_clamps_offscreen_when_size_is_already_safe() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    original_get_window_geometry = sidecar_mod.get_window_geometry
    original_win32gui = sidecar_mod.win32gui
    if sidecar_mod.win32gui is None:
        sidecar_mod.win32gui = types.SimpleNamespace(MoveWindow=lambda *_args, **_kwargs: None)
    original_move_window = sidecar_mod.win32gui.MoveWindow
    original_windll = sidecar_mod.ctypes.windll
    previous_fixed_origin = os.environ.get("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN")
    geometry_state = {"left": -180, "top": 80, "right": 800, "bottom": 940, "width": 980, "height": 860}
    calls: list[tuple[int, int, int, int]] = []

    class FakeUser32:
        @staticmethod
        def GetSystemMetrics(index: int) -> int:
            return 1920 if index == 0 else 1200

    class FakeWindll:
        user32 = FakeUser32()

    def fake_get_window_geometry(_hwnd: int) -> dict[str, int]:
        return dict(geometry_state)

    def fake_move_window(_hwnd: int, left: int, top: int, width: int, height: int, _repaint: bool) -> None:
        calls.append((left, top, width, height))
        geometry_state.update(
            {
                "left": left,
                "top": top,
                "right": left + width,
                "bottom": top + height,
                "width": width,
                "height": height,
            }
        )

    try:
        os.environ.pop("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", None)
        sidecar_mod.get_window_geometry = fake_get_window_geometry
        sidecar_mod.win32gui.MoveWindow = fake_move_window
        sidecar_mod.ctypes.windll = FakeWindll()
        result = normalize_wechat_window(1001)
        assert_true(result.get("ok") is True, f"normalization should pass: {result}")
        assert_true(result.get("applied") is True, f"offscreen same-size window must be moved: {result}")
        assert_true(calls == [(0, 0, 980, 860)], f"unexpected move call: {calls}")
        assert_true((result.get("after") or {}).get("left") == 0, f"window should be clamped on-screen: {result}")
        assert_true((result.get("after") or {}).get("top") == 0, f"window should use fixed top origin: {result}")
    finally:
        if previous_fixed_origin is None:
            os.environ.pop("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", None)
        else:
            os.environ["WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN"] = previous_fixed_origin
        sidecar_mod.get_window_geometry = original_get_window_geometry
        sidecar_mod.win32gui.MoveWindow = original_move_window
        sidecar_mod.win32gui = original_win32gui
        sidecar_mod.ctypes.windll = original_windll


def test_capabilities_success_exposes_top_level_geometry() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    screenshot = Image.new("RGB", (980, 860), "white")
    originals = {
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "validate_capture_geometry": sidecar_mod.validate_capture_geometry,
        "capture_wechat": sidecar_mod.capture_wechat,
        "run_ocr": sidecar_mod.run_ocr,
        "quick_login_like": sidecar_mod.quick_login_like,
        "detect_blank_render": sidecar_mod.detect_blank_render,
        "blocking_screen_reason": sidecar_mod.blocking_screen_reason,
        "validate_send_geometry": sidecar_mod.validate_send_geometry,
        "calculate_send_points": sidecar_mod.calculate_send_points,
        "inspect_uia_send_capability": sidecar_mod.inspect_uia_send_capability,
    }
    try:
        sidecar_mod.get_window_geometry = lambda hwnd: geometry
        sidecar_mod.validate_capture_geometry = lambda current: {"ok": True, "reason": "capture_geometry_ok", "geometry": current}
        sidecar_mod.capture_wechat = lambda hwnd, artifact_dir=None, label="capabilities": (screenshot, "capabilities.png")
        sidecar_mod.run_ocr = lambda image: [{"text": "文件传输助手", "left": 100, "top": 100, "right": 240, "bottom": 130}]
        sidecar_mod.quick_login_like = lambda items, geometry=None: False
        sidecar_mod.detect_blank_render = lambda image, items, geometry=None: {"detected": False}
        sidecar_mod.blocking_screen_reason = lambda items: ""
        sidecar_mod.validate_send_geometry = lambda current: {"ok": True, "reason": "geometry_ok", "geometry": current}
        sidecar_mod.calculate_send_points = lambda current: {
            "ok": True,
            "input_point": [637, 715],
            "send_point": [918, 816],
            "geometry": current,
        }
        sidecar_mod.inspect_uia_send_capability = lambda hwnd, current: {"ok": False, "reason": "uia_unavailable"}
        payload = capabilities_payload(1001, {"passive_probe": True}, artifact_dir=None)
        assert_true(payload.get("ok") is True, f"capabilities should pass: {payload}")
        assert_true(payload.get("geometry") == geometry, f"success payload should expose geometry: {payload}")
    finally:
        for name, value in originals.items():
            setattr(sidecar_mod, name, value)


def test_blank_render_detection_for_empty_white_capture() -> None:
    screenshot = Image.new("RGB", (980, 860), color=(255, 255, 255))
    detected = detect_blank_render(screenshot, [], geometry={"width": 980, "height": 860})
    assert_true(detected.get("detected") is True, f"blank render should be detected for pure white capture: {detected}")
    assert_true(detected.get("reason") == "blank_white_like", f"unexpected blank reason: {detected}")
    not_detected_with_ocr = detect_blank_render(
        screenshot,
        [{"text": "微信", "left": 12, "top": 8, "right": 58, "bottom": 26}],
        geometry={"width": 980, "height": 860},
    )
    assert_true(
        not_detected_with_ocr.get("detected") is False,
        f"blank render should not trigger when OCR sees visible text: {not_detected_with_ocr}",
    )


def test_send_guard_blocks_blank_render_before_file_transfer_blind_send() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    screenshot = Image.new("RGB", (980, 860), color=(255, 255, 255))
    originals = {
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "validate_send_geometry": sidecar_mod.validate_send_geometry,
        "capture_wechat": sidecar_mod.capture_wechat,
        "run_ocr": sidecar_mod.run_ocr,
    }
    try:
        sidecar_mod.get_window_geometry = lambda hwnd: geometry
        sidecar_mod.validate_send_geometry = lambda current: {"ok": True, "reason": "geometry_ok", "geometry": current}
        sidecar_mod.capture_wechat = lambda hwnd, artifact_dir=None, label="send_guard": (screenshot, "blank.png")
        sidecar_mod.run_ocr = lambda image: []
        guard = validate_active_send_target(1001, "文件传输助手", exact=True)
        assert_true(guard.get("ok") is False, f"blank render must block blind file-transfer send: {guard}")
        assert_true(guard.get("reason") == "blank_render", f"blank render reason should be explicit: {guard}")
        assert_true("blind_send" not in guard, f"blank render should not be marked as blind-send-safe: {guard}")
    finally:
        for name, value in originals.items():
            setattr(sidecar_mod, name, value)


def test_humanized_chunk_text_and_settings() -> None:
    previous = {
        name: os.environ.get(name)
        for name in (
            "WECHAT_WIN32_OCR_HUMANIZED_INPUT_ENABLED",
            "WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD",
            "WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MIN_CHARS",
            "WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MAX_CHARS",
            "WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS",
            "WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS",
            "WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_PROBABILITY",
        )
    }
    try:
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_INPUT_ENABLED"] = "1"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD"] = "clipboard_chunks"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MIN_CHARS"] = "3"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MAX_CHARS"] = "3"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS"] = "0"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS"] = "0"
        os.environ["WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_PROBABILITY"] = "0"
        settings = humanized_input_settings()
        assert_true(settings.get("enabled") is True, f"humanized input should be enabled: {settings}")
        assert_true(settings.get("method") == "clipboard_chunks", f"method should be parsed: {settings}")
        chunks = humanized_chunk_text("abcdefghij", min_chars=3, max_chars=3)
        assert_true(chunks == ["abc", "def", "ghi", "j"], f"chunking should be deterministic under fixed size: {chunks}")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_adaptive_humanized_input_speed_profiles() -> None:
    base = {
        "enabled": True,
        "method": "sendinput_unicode",
        "chunk_min_chars": 2,
        "chunk_max_chars": 6,
        "char_delay_min_ms": 50,
        "char_delay_max_ms": 180,
        "micro_pause_every_chars": 18,
        "micro_pause_min_ms": 220,
        "micro_pause_max_ms": 650,
        "typo_probability": 0.22,
        "typo_max": 1,
        "send_pre_delay_min_ms": 280,
        "send_pre_delay_max_ms": 1300,
        "send_post_input_delay_min_ms": 120,
        "send_post_input_delay_max_ms": 460,
        "adaptive_speed_enabled": True,
    }
    short = adapt_humanized_input_settings(base, "这台车今天能看吗？")
    assert_true(short.get("speed_profile") == "short_natural", f"short reply should use natural profile: {short}")
    assert_true(3 <= int(short.get("chunk_min_chars") or 0) <= 7, f"short chunks should remain human-sized: {short}")
    assert_true(45 <= int(short.get("char_delay_min_ms") or 0) <= 125, f"short char delay should not be superhuman: {short}")
    assert_true(18 <= int(short.get("micro_pause_every_chars") or 0) <= 40, f"short pauses should remain natural: {short}")

    long_text = "这边先帮您确认几个点。" * 40
    long_profile = adapt_humanized_input_settings(base, long_text)
    assert_true(long_profile.get("speed_profile") == "long_natural_capped", f"long reply should use natural capped profile: {long_profile}")
    assert_true(int(long_profile.get("chunk_max_chars") or 0) <= 12, f"long chunks should remain bounded: {long_profile}")
    assert_true(32 <= int(long_profile.get("char_delay_min_ms") or 0) <= 95, f"long char delay should stay human-like: {long_profile}")

    disabled = dict(base)
    disabled["adaptive_speed_enabled"] = False
    unchanged = adapt_humanized_input_settings(disabled, "这台车今天能看吗？")
    assert_true(unchanged.get("speed_profile") is None, f"disabled adaptive profile should not mutate speed: {unchanged}")


def test_set_uia_control_value_humanized_progressive_updates() -> None:
    settings = {
        "chunk_min_chars": 2,
        "chunk_max_chars": 2,
        "char_delay_min_ms": 0,
        "char_delay_max_ms": 0,
        "micro_pause_every_chars": 0,
        "micro_pause_min_ms": 0,
        "micro_pause_max_ms": 0,
        "typo_probability": 0.0,
        "typo_max": 0,
    }
    pattern = FakeValuePattern()
    result = set_uia_control_value_humanized(pattern, "你好ABCDE", settings)
    assert_true(result.get("ok") is True, f"uia humanized set value should succeed: {result}")
    assert_true(len(pattern.values) >= 2, f"humanized set value should write progressively: {pattern.values}")
    assert_true(pattern.values[-1] == "你好ABCDE", f"final value should match full text: {pattern.values}")


def test_sendinput_unicode_text_entry_helpers() -> None:
    settings = {
        "chunk_min_chars": 2,
        "chunk_max_chars": 2,
        "char_delay_min_ms": 0,
        "char_delay_max_ms": 0,
        "micro_pause_every_chars": 0,
        "micro_pause_min_ms": 0,
        "micro_pause_max_ms": 0,
        "typo_probability": 0.0,
        "typo_max": 0,
    }
    sent_units: list[int] = []
    result = type_text_with_sendinput_unicode("你\n好AB", settings, send_unit_func=sent_units.append)
    expected_text = "你 好AB"
    assert_true(result.get("ok") is True, f"sendinput unicode helper should succeed: {result}")
    assert_true(result.get("method") == "sendinput_unicode", f"method should be explicit: {result}")
    assert_true(result.get("normalized_newlines") is True, f"newlines should be normalized: {result}")
    assert_true(sent_units == sendinput_utf16_units(expected_text), f"typed utf16 units should match: {sent_units}")
    assert_true(sendinput_safe_text("a\r\nb\t c") == "a b c", "sendinput text should avoid accidental line-send")


def test_sendinput_unicode_aborts_when_window_guard_fails() -> None:
    settings = {
        "chunk_min_chars": 2,
        "chunk_max_chars": 2,
        "char_delay_min_ms": 0,
        "char_delay_max_ms": 0,
        "micro_pause_every_chars": 0,
        "micro_pause_min_ms": 0,
        "micro_pause_max_ms": 0,
        "typo_probability": 0.0,
        "typo_max": 0,
    }
    sent_units: list[int] = []
    calls = {"count": 0}

    def guard() -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] >= 2:
            return {"ok": False, "reason": "unit_window_lost"}
        return {"ok": True}

    result = type_text_with_sendinput_unicode(
        "ABCDEFGH",
        settings,
        send_unit_func=sent_units.append,
        window_guard_func=guard,
    )
    assert_true(result.get("ok") is False, f"typing should abort on window loss: {result}")
    assert_true(result.get("reason") == "window_lost_during_sendinput", f"abort reason should be explicit: {result}")
    assert_true(len(sent_units) == 0, f"no unit should be typed after an immediate focus guard failure: {sent_units}")


def test_send_trigger_mode_defaults_to_enter_only() -> None:
    assert_true(normalize_send_trigger_mode(None) == "enter_only", "default send trigger should avoid clicking the send button")
    assert_true(normalize_send_trigger_mode("click_only") == "click_only", "single-click trigger should remain opt-in")
    assert_true(normalize_send_trigger_mode("enter_then_click") == "enter_then_click", "legacy trigger should remain opt-in")
    assert_true(normalize_send_trigger_mode("bad") == "enter_only", "bad trigger mode should fail safe")


def test_input_text_region_state_distinguishes_blank_and_text() -> None:
    geometry = {"left": 0, "top": 0, "width": 980, "height": 860}
    blank = Image.new("RGB", (980, 860), "white")
    blank_state = input_text_region_state(blank, [], geometry=geometry)
    assert_true(blank_state.get("has_visible_text") is False, f"blank input should stay retry-safe: {blank_state}")
    blank_with_boundary_ocr = input_text_region_state(
        blank,
        [
            {"text": "按您说的9万", "left": 400, "top": 688, "right": 560, "bottom": 712},
            {"text": "顺序排清楚", "left": 600, "top": 735, "right": 780, "bottom": 760},
        ],
        geometry=geometry,
    )
    assert_true(
        blank_with_boundary_ocr.get("has_visible_text") is False,
        f"OCR boundary drift on a white input area should not block typing: {blank_with_boundary_ocr}",
    )
    text_image = blank.copy()
    ImageDraw.Draw(text_image).rectangle([370, 690, 560, 715], fill="black")
    text_state = input_text_region_state(
        text_image,
        [
            {
                "text": "奇骏和哈弗H6哪个更",
                "left": 370,
                "top": 690,
                "right": 560,
                "bottom": 715,
            }
        ],
        geometry=geometry,
    )
    assert_true(text_state.get("has_visible_text") is True, f"OCR text should block duplicate retry: {text_state}")


def test_send_rpa_env_enables_strict_focus_and_single_confirm() -> None:
    previous = os.environ.get("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS")
    previous_retry = os.environ.get("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY")
    previous_strict = os.environ.get("WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD")
    try:
        os.environ.pop("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS", None)
        os.environ.pop("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", None)
        os.environ.pop("WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD", None)
        env = send_rpa_env()
        assert_true(env.get("WECHAT_WIN32_OCR_AGGRESSIVE_FOCUS") == "1", f"send env should force focus: {env}")
        assert_true(env.get("WECHAT_WIN32_OCR_ATTACH_THREAD_INPUT") == "1", f"send env should attach input: {env}")
        assert_true(env.get("WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD") == "1", f"send env should guard foreground focus: {env}")
        assert_true(env.get("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND") == "1", f"send env should allow unknown-foreground guarded degrade: {env}")
        assert_true(env.get("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY") == "0", f"send env should not retry blank focus: {env}")
        assert_true(env.get("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS") == "1", f"send env should use one confirmed input attempt: {env}")
    finally:
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS", None)
        else:
            os.environ["WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS"] = previous
        if previous_retry is None:
            os.environ.pop("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", None)
        else:
            os.environ["WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY"] = previous_retry
        if previous_strict is None:
            os.environ.pop("WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD", None)
        else:
            os.environ["WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD"] = previous_strict


def test_activate_window_debounces_aggressive_refocus() -> None:
    source_path = PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "adapters" / "wechat_win32_ocr_sidecar.py"
    source = source_path.read_text(encoding="utf-8")
    assert_true(
        "WECHAT_WIN32_OCR_ACTIVATE_DEBOUNCE_SECONDS" in source,
        "activate_window should debounce repeated foreground activations",
    )
    assert_true(
        'and not aggressive_focus' not in source[source.find("def activate_window") : source.find("def configure_dpi_awareness")],
        "aggressive focus must still skip when WeChat is already foreground",
    )
    assert_true(
        "WECHAT_WIN32_OCR_FOCUS_CLICK_FALLBACK" in source,
        "activate_window should expose focus click fallback env switch for strict-focus lock scenarios",
    )
    assert_true(
        "focus_click_fallback_enabled()" in source[source.find("def activate_window") : source.find("def configure_dpi_awareness")],
        "activate_window should optionally use click fallback when foreground lock blocks SetForegroundWindow",
    )


def test_non_retryable_input_failure_detects_focus_loss() -> None:
    result = {
        "ok": False,
        "reason": "window_lost_during_sendinput",
        "window_guard": {"ok": False, "reason": "foreground_not_wechat_target"},
    }
    assert_true(non_retryable_input_failure(result), f"focus loss must not be retried: {result}")


def test_foreground_guard_zero_hwnd_can_degrade_when_enabled() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    previous = os.environ.get("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND")
    win32gui_mod = sidecar_mod.win32gui
    if win32gui_mod is None:
        return
    originals = {
        "GetForegroundWindow": getattr(win32gui_mod, "GetForegroundWindow"),
        "GetAncestor": getattr(win32gui_mod, "GetAncestor"),
    }
    try:
        os.environ["WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND"] = "1"
        setattr(win32gui_mod, "GetForegroundWindow", lambda: 0)
        setattr(win32gui_mod, "GetAncestor", lambda _hwnd, _flag: 0)
        result = sidecar_mod.foreground_window_matches_target(1001)
        assert_true(result.get("ok") is True, f"foreground=0 should degrade to guarded-pass when enabled: {result}")
        assert_true(str(result.get("reason") or "") == "foreground_unknown_guard_degraded", f"unexpected reason: {result}")
    finally:
        setattr(win32gui_mod, "GetForegroundWindow", originals["GetForegroundWindow"])
        setattr(win32gui_mod, "GetAncestor", originals["GetAncestor"])
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND", None)
        else:
            os.environ["WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND"] = previous


def test_foreground_guard_zero_hwnd_blocks_when_disabled() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    previous = os.environ.get("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND")
    win32gui_mod = sidecar_mod.win32gui
    if win32gui_mod is None:
        return
    originals = {
        "GetForegroundWindow": getattr(win32gui_mod, "GetForegroundWindow"),
        "GetAncestor": getattr(win32gui_mod, "GetAncestor"),
    }
    try:
        os.environ["WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND"] = "0"
        setattr(win32gui_mod, "GetForegroundWindow", lambda: 0)
        setattr(win32gui_mod, "GetAncestor", lambda _hwnd, _flag: 0)
        result = sidecar_mod.foreground_window_matches_target(1001)
        assert_true(result.get("ok") is False, f"foreground=0 should be blocked when disabled: {result}")
        assert_true(str(result.get("reason") or "") == "foreground_not_wechat_target", f"unexpected reason: {result}")
    finally:
        setattr(win32gui_mod, "GetForegroundWindow", originals["GetForegroundWindow"])
        setattr(win32gui_mod, "GetAncestor", originals["GetAncestor"])
        if previous is None:
            os.environ.pop("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND", None)
        else:
            os.environ["WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND"] = previous


def test_recover_send_window_guard_recovers_foreground_mismatch() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    originals = {
        "basic_send_window_guard": sidecar_mod.basic_send_window_guard,
        "activate_window": sidecar_mod.activate_window,
        "sleep": sidecar_mod.time.sleep,
        "uniform": sidecar_mod.random.uniform,
    }
    calls = {"guard": 0, "activate": 0}
    try:
        def fake_guard(_hwnd: int) -> dict[str, object]:
            calls["guard"] += 1
            if calls["guard"] == 1:
                return {"ok": False, "reason": "foreground_not_wechat_target"}
            return {"ok": True, "reason": "window_valid"}

        def fake_activate(_hwnd: int) -> None:
            calls["activate"] += 1

        sidecar_mod.basic_send_window_guard = fake_guard
        sidecar_mod.activate_window = fake_activate
        sidecar_mod.time.sleep = lambda _seconds: None
        sidecar_mod.random.uniform = lambda _a, _b: 0.0
        result = sidecar_mod.recover_send_window_guard(1001, max_attempts=1)
        assert_true(result.get("ok") is True, f"expected focus recovery success: {result}")
        assert_true(result.get("focus_recovered") is True, f"expected focus_recovered flag: {result}")
        assert_true(int(result.get("focus_recovery_attempts") or 0) == 1, f"expected single recovery attempt: {result}")
        assert_true(calls["activate"] == 1, f"expected one activate call: {calls}")
    finally:
        sidecar_mod.basic_send_window_guard = originals["basic_send_window_guard"]
        sidecar_mod.activate_window = originals["activate_window"]
        sidecar_mod.time.sleep = originals["sleep"]
        sidecar_mod.random.uniform = originals["uniform"]


def test_recover_send_window_guard_does_not_retry_non_focus_failures() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    originals = {
        "basic_send_window_guard": sidecar_mod.basic_send_window_guard,
        "activate_window": sidecar_mod.activate_window,
    }
    calls = {"activate": 0}
    try:
        sidecar_mod.basic_send_window_guard = lambda _hwnd: {"ok": False, "reason": "window_not_visible"}
        sidecar_mod.activate_window = lambda _hwnd: calls.__setitem__("activate", calls["activate"] + 1)
        result = sidecar_mod.recover_send_window_guard(1001, max_attempts=2)
        assert_true(result.get("ok") is False, f"expected guard to fail: {result}")
        assert_true(str(result.get("reason") or "") == "window_not_visible", f"unexpected guard reason: {result}")
        assert_true(calls["activate"] == 0, f"non-focus failures should not trigger recovery activate: {calls}")
    finally:
        sidecar_mod.basic_send_window_guard = originals["basic_send_window_guard"]
        sidecar_mod.activate_window = originals["activate_window"]


def test_blank_input_focus_retry_keeps_single_confirm_semantics() -> None:
    previous_attempts = os.environ.get("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS")
    previous_retry = os.environ.get("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY")
    try:
        os.environ["WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS"] = "1"
        os.environ.pop("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", None)
        assert_true(send_input_confirm_attempt_count(3) == 2, "blank-only focus retry should add one safe focus attempt")
        os.environ["WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY"] = "0"
        assert_true(send_input_confirm_attempt_count(3) == 1, "blank focus retry must be configurable off")
        os.environ["WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS"] = "3"
        os.environ.pop("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", None)
        assert_true(send_input_confirm_attempt_count(3) == 3, "explicit retry budget should be preserved")
    finally:
        if previous_attempts is None:
            os.environ.pop("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS", None)
        else:
            os.environ["WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS"] = previous_attempts
        if previous_retry is None:
            os.environ.pop("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", None)
        else:
            os.environ["WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY"] = previous_retry


def test_target_ready_defaults_to_single_attempt_and_hard_stops_blank_render() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    previous_attempts = os.environ.get("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS")
    originals = {
        "open_chat": sidecar_mod.open_chat,
        "validate_active_send_target": sidecar_mod.validate_active_send_target,
        "key_press": sidecar_mod.key_press,
        "sleep": sidecar_mod.time.sleep,
    }
    calls = {"open": 0, "validate": 0, "key": 0}
    try:
        os.environ.pop("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS", None)

        def fake_open_chat(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> bool:
            calls["open"] += 1
            return False

        def fake_validate(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> dict[str, object]:
            calls["validate"] += 1
            return {"ok": False, "online": False, "state": "blank_render_detected", "reason": "blank_render"}

        sidecar_mod.open_chat = fake_open_chat
        sidecar_mod.validate_active_send_target = fake_validate
        sidecar_mod.key_press = lambda key: calls.__setitem__("key", calls["key"] + 1)
        sidecar_mod.time.sleep = lambda seconds: None
        result = sidecar_mod.ensure_target_ready_for_send(1001, "新数据测试", exact=True)
        assert_true(result.get("ok") is False, f"blank render must fail target readiness: {result}")
        assert_true(result.get("hard_stop") is True, f"blank render should hard-stop retries: {result}")
        assert_true(result.get("attempts") == 1, f"default target ready attempts should be one: {result}")
        assert_true(calls["open"] == 0 and calls["validate"] == 1, f"unexpected retry count: {calls}")
        assert_true(calls["key"] == 0, f"hard stop should not press ESC for another retry: {calls}")
    finally:
        if previous_attempts is None:
            os.environ.pop("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS", None)
        else:
            os.environ["WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS"] = previous_attempts
        for name, value in originals.items():
            if name == "sleep":
                sidecar_mod.time.sleep = value
            else:
                setattr(sidecar_mod, name, value)


def test_target_ready_requires_guard_confirmation_even_when_open_chat_returns_true() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    previous_attempts = os.environ.get("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS")
    originals = {
        "open_chat": sidecar_mod.open_chat,
        "validate_active_send_target": sidecar_mod.validate_active_send_target,
        "key_press": sidecar_mod.key_press,
        "sleep": sidecar_mod.time.sleep,
    }
    calls = {"open": 0, "validate": 0, "key": 0}
    try:
        os.environ["WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS"] = "1"

        def fake_open_chat(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> bool:
            calls["open"] += 1
            return True

        def fake_validate(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> dict[str, object]:
            calls["validate"] += 1
            return {"ok": False, "online": True, "state": "target_mismatch", "reason": "target_not_confirmed"}

        sidecar_mod.open_chat = fake_open_chat
        sidecar_mod.validate_active_send_target = fake_validate
        sidecar_mod.key_press = lambda key: calls.__setitem__("key", calls["key"] + 1)
        sidecar_mod.time.sleep = lambda seconds: None
        result = sidecar_mod.ensure_target_ready_for_send(1001, "新数据测试", exact=True)
        assert_true(result.get("ok") is False, f"target readiness must fail when guard confirmation fails: {result}")
        assert_true(result.get("attempts") == 1, f"single-attempt mode should stop immediately: {result}")
        assert_true(calls["open"] == 1 and calls["validate"] == 2, f"unexpected call path: {calls}")
        assert_true(calls["key"] == 0, f"single-attempt mode should not trigger retry ESC: {calls}")
    finally:
        if previous_attempts is None:
            os.environ.pop("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS", None)
        else:
            os.environ["WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS"] = previous_attempts
        for name, value in originals.items():
            if name == "sleep":
                sidecar_mod.time.sleep = value
            else:
                setattr(sidecar_mod, name, value)


def test_target_ready_short_circuits_when_active_target_already_confirmed() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    originals = {
        "open_chat": sidecar_mod.open_chat,
        "validate_active_send_target": sidecar_mod.validate_active_send_target,
    }
    calls = {"open": 0, "validate": 0}
    try:
        sidecar_mod.open_chat = lambda *_args, **_kwargs: calls.__setitem__("open", calls["open"] + 1) or False

        def fake_validate(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> dict[str, object]:
            calls["validate"] += 1
            return {"ok": True, "online": True, "reason": "target_confirmed"}

        sidecar_mod.validate_active_send_target = fake_validate
        result = sidecar_mod.ensure_target_ready_for_send(1001, "新数据测试", exact=True)
        assert_true(result.get("ok") is True, f"pre-validated active target should pass immediately: {result}")
        assert_true(calls["open"] == 0 and calls["validate"] == 1, f"open_chat should be skipped on pre-validation pass: {calls}")
    finally:
        for name, value in originals.items():
            setattr(sidecar_mod, name, value)


def test_send_payload_reuses_prevalidated_guard_without_revalidating_active_target() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    originals = {
        "validate_active_send_target": sidecar_mod.validate_active_send_target,
        "recover_send_window_guard": sidecar_mod.recover_send_window_guard,
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "validate_send_geometry": sidecar_mod.validate_send_geometry,
        "calculate_send_points": sidecar_mod.calculate_send_points,
        "reserve_send_rate": sidecar_mod.reserve_send_rate,
        "send_with_guarded_clicks": sidecar_mod.send_with_guarded_clicks,
        "validate_post_send_target": sidecar_mod.validate_post_send_target,
        "humanized_action_sleep": sidecar_mod.humanized_action_sleep,
    }
    calls = {"validate_active": 0}
    try:
        def fail_validate(*_args, **_kwargs):
            calls["validate_active"] += 1
            return {"ok": False, "reason": "should_not_be_called"}

        sidecar_mod.validate_active_send_target = fail_validate
        sidecar_mod.recover_send_window_guard = lambda _hwnd, max_attempts=1: {"ok": True, "reason": "window_valid"}
        sidecar_mod.get_window_geometry = lambda _hwnd: dict(geometry)
        sidecar_mod.validate_send_geometry = lambda _g: {"ok": True}
        sidecar_mod.calculate_send_points = lambda _g: {
            "ok": True,
            "input_point": [640, 715],
            "send_point": [915, 816],
        }
        sidecar_mod.reserve_send_rate = lambda **_kwargs: {"ok": True, "reason": "rate_ok"}
        sidecar_mod.send_with_guarded_clicks = lambda *_args, **_kwargs: {
            "ok": True,
            "method": "win32.human_click_input+sendinput_unicode+send_trigger:enter_only",
            "paste": {"ok": True, "input_mode": "sendinput_unicode"},
        }
        sidecar_mod.validate_post_send_target = lambda *_args, **_kwargs: {
            "ok": True,
            "online": True,
            "reason": "target_confirmed",
            "geometry": dict(geometry),
            "post_send_fast_guard": True,
            "screenshot_path": "",
        }
        sidecar_mod.humanized_action_sleep = lambda *_args, **_kwargs: 0.0
        payload = sidecar_mod.send_payload(
            1001,
            {"windows": [], "visible_main_windows": []},
            target="新数据测试",
            text="您好",
            exact=True,
            validated_guard={
                "ok": True,
                "online": True,
                "reason": "target_confirmed",
                "geometry": dict(geometry),
            },
        )
        assert_true(payload.get("ok") is True, f"send payload should succeed with prevalidated guard: {payload}")
        send_result = payload.get("send_result") if isinstance(payload.get("send_result"), dict) else {}
        assert_true(
            str(send_result.get("validation_source") or "") == "prevalidated_guard",
            f"send payload should mark validation_source as prevalidated_guard: {send_result}",
        )
        assert_true(calls["validate_active"] == 0, f"active target validation should be skipped: {calls}")
    finally:
        for name, value in originals.items():
            setattr(sidecar_mod, name, value)


def test_open_chat_search_fallback_clicks_visible_result_without_enter() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    screenshot = Image.new("RGB", (980, 860), "white")
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    previous_enter_fallback = os.environ.get("WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK")
    originals = {
        "ensure_main_session_list": sidecar_mod.ensure_main_session_list,
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "target_switch_surface_state": sidecar_mod.target_switch_surface_state,
        "active_chat_matches": sidecar_mod.active_chat_matches,
        "parse_sessions_from_ocr": sidecar_mod.parse_sessions_from_ocr,
        "clear_sidebar_search_box_without_select_all": sidecar_mod.clear_sidebar_search_box_without_select_all,
        "type_sidebar_search_query": sidecar_mod.type_sidebar_search_query,
        "capture_wechat": sidecar_mod.capture_wechat,
        "run_ocr": sidecar_mod.run_ocr,
        "activate_session_candidate": sidecar_mod.activate_session_candidate,
        "key_press": sidecar_mod.key_press,
        "sleep": sidecar_mod.time.sleep,
    }
    calls = {"clear": 0, "type": 0, "activate": 0, "key_return": 0}
    parse_call_count = {"count": 0}
    try:
        os.environ["WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK"] = "0"
        sidecar_mod.ensure_main_session_list = lambda hwnd, artifact_dir=None: (
            screenshot,
            [{"text": "文件传输助手", "left": 86, "top": 120, "right": 210, "bottom": 150, "center_y": 135}],
        )
        sidecar_mod.get_window_geometry = lambda hwnd: geometry
        sidecar_mod.target_switch_surface_state = lambda *args, **kwargs: {"ok": True, "reason": "surface_ready"}
        sidecar_mod.active_chat_matches = lambda *args, **kwargs: False

        def fake_parse_sessions(items, image_size, screenshot=None):
            parse_call_count["count"] += 1
            if parse_call_count["count"] == 1:
                return []
            return [{"name": "新数据测试", "center_y": 188, "left": 95, "right": 190}]

        sidecar_mod.parse_sessions_from_ocr = fake_parse_sessions
        sidecar_mod.clear_sidebar_search_box_without_select_all = (
            lambda hwnd, search_x, search_y, target_hint="": calls.__setitem__("clear", calls["clear"] + 1)
        )
        sidecar_mod.type_sidebar_search_query = (
            lambda hwnd, target: calls.__setitem__("type", calls["type"] + 1) or {"ok": True, "method": "sendinput_unicode"}
        )
        sidecar_mod.capture_wechat = lambda hwnd, artifact_dir=None, label="open_chat": (screenshot, f"{label}.png")
        sidecar_mod.run_ocr = lambda image: [
            {"text": "新数据测试", "left": 95, "top": 172, "right": 190, "bottom": 204, "center_y": 188}
        ]
        sidecar_mod.activate_session_candidate = (
            lambda *args, **kwargs: calls.__setitem__("activate", calls["activate"] + 1) or True
        )

        def fake_key_press(key: int) -> None:
            if key == sidecar_mod.win32con.VK_RETURN:
                calls["key_return"] += 1

        sidecar_mod.key_press = fake_key_press
        sidecar_mod.time.sleep = lambda seconds: None
        opened = sidecar_mod.open_chat(1001, "新数据测试", exact=True)
        assert_true(opened is True, f"visible search result should open target chat: {calls}")
        assert_true(calls["clear"] == 1 and calls["type"] == 1, f"search should run once: {calls}")
        assert_true(calls["activate"] == 1, f"visible result should be clicked once: {calls}")
        assert_true(calls["key_return"] == 0, f"default search fallback must not press Enter: {calls}")
    finally:
        if previous_enter_fallback is None:
            os.environ.pop("WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK", None)
        else:
            os.environ["WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK"] = previous_enter_fallback
        for name, value in originals.items():
            if name == "sleep":
                sidecar_mod.time.sleep = value
            else:
                setattr(sidecar_mod, name, value)


def test_open_chat_blocks_search_when_surface_is_blank() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    screenshot = Image.new("RGB", (980, 860), "white")
    geometry = {"left": 0, "top": 0, "right": 980, "bottom": 860, "width": 980, "height": 860}
    originals = {
        "ensure_main_session_list": sidecar_mod.ensure_main_session_list,
        "get_window_geometry": sidecar_mod.get_window_geometry,
        "target_switch_surface_state": sidecar_mod.target_switch_surface_state,
        "clear_sidebar_search_box_without_select_all": sidecar_mod.clear_sidebar_search_box_without_select_all,
    }
    calls = {"clear": 0}
    try:
        sidecar_mod.ensure_main_session_list = lambda hwnd, artifact_dir=None: (screenshot, [])
        sidecar_mod.get_window_geometry = lambda hwnd: geometry
        sidecar_mod.target_switch_surface_state = lambda *args, **kwargs: {
            "ok": False,
            "online": False,
            "state": "blank_render_detected",
            "reason": "blank_render",
        }
        sidecar_mod.clear_sidebar_search_box_without_select_all = (
            lambda *args, **kwargs: calls.__setitem__("clear", calls["clear"] + 1)
        )
        opened = sidecar_mod.open_chat(1001, "新数据测试", exact=True)
        assert_true(opened is False, f"blank render should not open chat: {opened}")
        assert_true(calls["clear"] == 0, f"blank render must block search clicks: {calls}")
    finally:
        for name, value in originals.items():
            setattr(sidecar_mod, name, value)


def test_sidebar_search_clear_uses_window_image_click() -> None:
    sidecar_mod = sys.modules["apps.wechat_ai_customer_service.adapters.wechat_win32_ocr_sidecar"]
    originals = {
        "human_window_image_click": sidecar_mod.human_window_image_click,
        "human_client_click": sidecar_mod.human_client_click,
        "key_press": sidecar_mod.key_press,
        "sleep": sidecar_mod.time.sleep,
    }
    calls = {"window_click": 0, "client_click": 0, "keys": 0}
    try:
        sidecar_mod.human_window_image_click = (
            lambda hwnd, x, y: calls.__setitem__("window_click", calls["window_click"] + 1)
        )
        sidecar_mod.human_client_click = (
            lambda hwnd, x, y: calls.__setitem__("client_click", calls["client_click"] + 1)
        )
        sidecar_mod.key_press = lambda key: calls.__setitem__("keys", calls["keys"] + 1)
        sidecar_mod.time.sleep = lambda seconds: None
        sidecar_mod.clear_sidebar_search_box_without_select_all(1001, 122, 64, target_hint="新数据测试")
        assert_true(calls["window_click"] == 1, f"search box should use screenshot/window coordinates: {calls}")
        assert_true(calls["client_click"] == 0, f"search box should avoid client-coordinate click drift: {calls}")
        assert_true(calls["keys"] >= 1, f"search clear should still clear stale query text: {calls}")
    finally:
        for name, value in originals.items():
            if name == "sleep":
                sidecar_mod.time.sleep = value
            else:
                setattr(sidecar_mod, name, value)


def test_rpa_action_layer_avoids_fixed_sleep_cadence() -> None:
    source_path = PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "adapters" / "wechat_win32_ocr_sidecar.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    action_functions = {
        "activate_window",
        "activate_session_candidate",
        "clear_sidebar_search_box_without_select_all",
        "client_click",
        "click",
        "confirm_input_token_via_clipboard",
        "ensure_left_button_released",
        "ensure_target_ready_for_send",
        "ensure_visible_wechat_window",
        "hotkey",
        "key_press",
        "normalize_wechat_window",
        "scroll_chat_history",
        "scroll_chat_to_latest",
        "send_with_uia_controls",
    }
    fixed_sleeps: list[str] = []
    helper_hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in action_functions:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Name) and call.func.id == "humanized_action_sleep":
                helper_hits.add(node.name)
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "sleep"
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id == "time"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, (int, float))
            ):
                fixed_sleeps.append(f"{node.name}:{call.lineno}:{call.args[0].value}")
    assert_true(not fixed_sleeps, f"RPA action functions should not use fixed sleep cadence: {fixed_sleeps}")
    missing_helpers = sorted(action_functions - helper_hits - {"ensure_visible_wechat_window"})
    assert_true(not missing_helpers, f"RPA action functions should use humanized_action_sleep: {missing_helpers}")


def test_scroll_actions_randomize_wheel_and_cursor_cadence() -> None:
    source_path = PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "adapters" / "wechat_win32_ocr_sidecar.py"
    source = source_path.read_text(encoding="utf-8")
    history_start = source.find("def scroll_chat_history")
    latest_start = source.find("def scroll_chat_to_latest")
    capture_start = source.find("def capture_wechat")
    history_source = source[history_start:latest_start]
    latest_source = source[latest_start:capture_start]
    assert_true("random.randint(-12, 12)" in history_source, "history scroll should jitter cursor X")
    assert_true("random.randint(-10, 10)" in history_source, "history scroll should jitter cursor Y")
    assert_true("random.choice([-1, 0, 1])" in history_source, "history scroll should vary wheel units")
    assert_true("random.randint(5, 7)" in latest_source, "scroll-to-latest should vary wheel units")
    assert_true("humanized_action_sleep(85, 180)" in latest_source, "scroll-to-latest should avoid fixed cadence")


def main() -> int:
    tests = [
        test_parse_sessions_from_ocr,
        test_parse_sessions_detects_visual_unread_red_dot,
        test_parse_sessions_normalizes_truncated_file_transfer,
        test_message_probe_tokens_prefer_semantic_body_after_live_marker,
        test_parse_messages_from_ocr,
        test_parse_messages_keeps_low_visible_bubble_lines,
        test_parse_messages_classifies_wide_right_bubbles_as_self,
        test_history_snapshot_merge_orders_and_dedupes,
        test_anchor_match_supports_content_and_reply_keys,
        test_message_noise_filters_relative_timestamps,
        test_connector_helpers,
        test_send_geometry_guard,
        test_send_points_apply_small_safe_jitter,
        test_send_rate_guard,
        test_wechat_rpa_lock_recovers_stale_lock_and_times_out_on_live_lock,
        test_uia_control_selection_prefers_chatbox,
        test_startup_capability_decision,
        test_startup_self_check_uses_interactive_probe_env,
        test_connector_interactive_capabilities_passes_probe_env,
        test_connector_interactive_status_passes_probe_env,
        test_connector_interactive_capabilities_recovers_minimized_window,
        test_connector_passive_status_does_not_recover_minimized_window,
        test_connector_interactive_status_recovers_blank_render_with_tray_redraw,
        test_startup_evaluates_nested_rpa_geometry_failure,
        test_preflight_uses_interactive_status_probe,
        test_adaptive_window_points,
        test_session_match_and_click_x,
        test_active_chat_matches_file_transfer_alias,
        test_active_chat_matches_wrapped_title_text,
        test_active_chat_cutoff_extends_above_sidebar_cutoff,
        test_file_transfer_simulated_inbound_fallback,
        test_fast_confirmation_still_enqueues_file_transfer_loopback,
        test_passive_probe_mode_toggle,
        test_low_disturbance_read_and_action_budget_defaults,
        test_passive_probe_window_discovery_is_non_interactive,
        test_interactive_probe_restores_offscreen_visible_window,
        test_capture_geometry_guard_and_window_selection,
        test_window_selection_prefers_real_wechat_title_over_weixin_shell,
        test_auxiliary_wechat_shell_is_blocked,
        test_normalize_wechat_window_clamps_offscreen_when_size_is_already_safe,
        test_capabilities_success_exposes_top_level_geometry,
        test_blank_render_detection_for_empty_white_capture,
        test_send_guard_blocks_blank_render_before_file_transfer_blind_send,
        test_quick_login_detection,
        test_service_subview_back_target_detection,
        test_connector_rpa_priority_and_wxauto_reserve_toggle,
        test_send_verify_handles_split_multiline_messages,
        test_blind_send_without_ocr_verification_fallback,
        test_guarded_send_confirmation_fallback,
        test_fast_send_confirmation_skips_slow_message_read_when_guard_is_strong,
        test_invalid_window_handle_is_hard_stop_not_recovery,
        test_send_text_invalid_window_handle_skips_wxauto4_reserve,
        test_foreign_overlay_capture_filter_and_blind_target_gate,
        test_blind_target_confirmation_uses_sidebar_match_when_title_missing,
        test_humanized_chunk_text_and_settings,
        test_adaptive_humanized_input_speed_profiles,
        test_set_uia_control_value_humanized_progressive_updates,
        test_sendinput_unicode_text_entry_helpers,
        test_sendinput_unicode_aborts_when_window_guard_fails,
        test_send_trigger_mode_defaults_to_enter_only,
        test_input_text_region_state_distinguishes_blank_and_text,
        test_input_region_visual_delta_confirmation,
        test_input_area_token_confirmation_excludes_recent_chat_bubble,
        test_clear_existing_input_draft_noops_when_blank,
        test_send_rpa_env_enables_strict_focus_and_single_confirm,
        test_activate_window_debounces_aggressive_refocus,
        test_non_retryable_input_failure_detects_focus_loss,
        test_foreground_guard_zero_hwnd_can_degrade_when_enabled,
        test_foreground_guard_zero_hwnd_blocks_when_disabled,
        test_recover_send_window_guard_recovers_foreground_mismatch,
        test_recover_send_window_guard_does_not_retry_non_focus_failures,
        test_blank_input_focus_retry_keeps_single_confirm_semantics,
        test_target_ready_defaults_to_single_attempt_and_hard_stops_blank_render,
        test_target_ready_requires_guard_confirmation_even_when_open_chat_returns_true,
        test_target_ready_short_circuits_when_active_target_already_confirmed,
        test_send_payload_reuses_prevalidated_guard_without_revalidating_active_target,
        test_open_chat_search_fallback_clicks_visible_result_without_enter,
        test_open_chat_blocks_search_when_surface_is_blank,
        test_sidebar_search_clear_uses_window_image_click,
        test_rpa_action_layer_avoids_fixed_sleep_cadence,
        test_scroll_actions_randomize_wheel_and_cursor_cadence,
    ]
    passed = 0
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
        passed += 1
    print(f"All {passed} WeChat Win32/OCR compatibility checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
