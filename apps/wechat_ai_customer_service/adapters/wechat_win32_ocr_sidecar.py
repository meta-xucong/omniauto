"""Windows Win32/OCR sidecar for the WeChat desktop recorder.

This adapter is designed as the primary transport because it relies only on
the top-level Win32 window, screenshots, OCR, clipboard paste, and guarded
click/input flows. It is the Windows adaptation of WeChat control. Windows 1920x1080
WeChat has different UI geometry and should use a separate platform adapter
rather than reusing these coordinates blindly.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import io
import json
import os
import random
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import pyperclip as _pyperclip
except Exception:  # pragma: no cover - optional clipboard convenience package.
    _pyperclip = None

try:
    import win32api
    import win32con
    import win32gui
    import win32process
    import win32ui
    _WIN32_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - allows pure parser tests without pywin32.
    win32api = None  # type: ignore[assignment]
    win32gui = None  # type: ignore[assignment]
    win32process = None  # type: ignore[assignment]
    win32ui = None  # type: ignore[assignment]
    _WIN32_IMPORT_ERROR = repr(exc)

    class _Win32ConFallback:
        VK_CONTROL = 0x11
        VK_ESCAPE = 0x1B
        VK_BACK = 0x08
        VK_DELETE = 0x2E
        VK_DOWN = 0x28
        VK_RETURN = 0x0D
        VK_LBUTTON = 0x01
        KEYEVENTF_KEYUP = 0x0002
        MOUSEEVENTF_MOVE = 0x0001
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004
        MOUSEEVENTF_WHEEL = 0x0800
        WM_MOUSEWHEEL = 0x020A

    win32con = _Win32ConFallback()  # type: ignore[assignment]
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageStat

from apps.wechat_ai_customer_service.adapters.add_friend_actions import (
    ACTION_COMPOSITE_INPUT,
    make_action_result,
)
from apps.wechat_ai_customer_service.adapters.add_friend_artifacts import (
    ADD_FRIEND_ENTRY_CLICK_PLAN_JSON,
    add_friend_route_artifact_root,
)
from apps.wechat_ai_customer_service.adapters.add_friend_contract import (
    normalize_add_friend_query,
    validate_add_friend_entry_click_contract,
)
from apps.wechat_ai_customer_service.adapters.add_friend_diagnostics import (
    step_events_from_review_rows,
    write_step_event_report,
)
from apps.wechat_ai_customer_service.adapters.add_friend_flow_events import add_friend_entry_click_events_from_payload
from apps.wechat_ai_customer_service.adapters.add_friend_flow_context import AddFriendFlowContext
from apps.wechat_ai_customer_service.adapters.add_friend_flow import (
    add_friend_entry_click_task_outcome,
    run_add_friend_entry_click_plan_flow,
)
from apps.wechat_ai_customer_service.adapters.add_friend_layout import (
    invite_form_field_verification,
    plus_entry_target as layout_plus_entry_target,
    semantic_invite_form_targets,
    windows_1080p_reference_plus_point,
    windows_plus_point,
)
from apps.wechat_ai_customer_service.adapters.add_friend_locator import (
    fixed_geometry_locator,
    geometry_fallback_locator,
    make_locator_result,
    ocr_item_locator,
)
from apps.wechat_ai_customer_service.adapters.add_friend_operator_guard import (
    add_friend_operator_guard_checkpoint,
    start_add_friend_operator_guard,
    stop_add_friend_operator_guard,
)
from apps.wechat_ai_customer_service.adapters.add_friend_ocr import (
    compact_ocr_text as mapped_compact_ocr_text,
    ocr_item_text as mapped_ocr_item_text,
    ocr_surface_text as mapped_ocr_surface_text,
    ocr_text_has_any as mapped_ocr_text_has_any,
)
from apps.wechat_ai_customer_service.adapters.add_friend_pacing import pacing_metadata, pacing_range
from apps.wechat_ai_customer_service.adapters.add_friend_payloads import (
    add_friend_add_contact_entry_not_found_payload,
    add_friend_after_confirm_payload,
    add_friend_invite_form_window_not_found_payload,
    add_friend_phone_not_found_payload,
    add_friend_task_payload_invalid,
)
from apps.wechat_ai_customer_service.adapters.add_friend_result_mapping import (
    ERROR_ACCOUNT_RESTRICTED,
    ERROR_INVITE_FIELD_VERIFICATION_FAILED,
    ERROR_OPERATOR_GUARD_NOT_READY,
    ERROR_PHONE_NOT_FOUND,
    ERROR_TASK_PAYLOAD_INVALID,
    ERROR_WECHAT_WINDOW_NOT_READY,
    RESULT_ALREADY_FRIEND,
    RESULT_INVITE_SENT,
    add_friend_completed_result as mapped_add_friend_completed_result,
    add_friend_failed_result as mapped_add_friend_failed_result,
    add_friend_server_report_payload as mapped_add_friend_server_report_payload,
)
from apps.wechat_ai_customer_service.adapters.add_friend_routes import (
    ADD_FRIEND_MAIN_ROUTE,
    ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE,
    ADD_FRIEND_ROUTES,
    ADD_FRIEND_WINDOWS_ROUTE,
    add_friend_route_accepts_formal_fields,
    add_friend_route_accepts_query,
    add_friend_route_uses_passive_probe,
)
from apps.wechat_ai_customer_service.adapters.add_friend_screenshot import save_screenshot_artifact
from apps.wechat_ai_customer_service.wechat_message_envelope import (
    apply_message_envelope_to_record,
    build_message_envelope,
)

try:
    from rapidocr_onnxruntime import RapidOCR
    _OCR_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - OCR is only needed for live sidecar actions.
    RapidOCR = None  # type: ignore[assignment]
    _OCR_IMPORT_ERROR = repr(exc)


SEARCH_BOX_REL = (110, 70)
SESSION_CLICK_X = 260
CHAT_HEADER_MAX_Y = 90
CHAT_INPUT_BOTTOM_OFFSET = 52
DEFAULT_MESSAGE_BOTTOM_EXCLUDE_PX = 95
OCR_MIN_CONFIDENCE = 0.45
SIDECAR_BASE_ACTIONS = ("status", "capabilities", "sessions", "messages", "send", "recover-render")
SIDECAR_ACTION_CHOICES = (*SIDECAR_BASE_ACTIONS, *ADD_FRIEND_ROUTES)
SEND_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_send_guard.json"
UI_ACTION_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_ui_action_guard.json"
UI_ACTION_AUDIT_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_ui_actions.jsonl"
_LAST_ACTIVATE_MONOTONIC_BY_HWND: dict[int, float] = {}
_LAST_RPA_ACTION_STATE: dict[str, Any] = {}
RENDER_RECOVERY_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_render_recovery_guard.json"
MIN_SEND_CLIENT_WIDTH = 700
MIN_SEND_CLIENT_HEIGHT = 720
LOGIN_WINDOW_MAX_WIDTH = 560
LOGIN_WINDOW_MAX_HEIGHT = 680
DEFAULT_SAFE_WINDOW_WIDTH = 980
DEFAULT_SAFE_WINDOW_HEIGHT = 860
MIN_SAFE_WINDOW_WIDTH = MIN_SEND_CLIENT_WIDTH
MIN_SAFE_WINDOW_HEIGHT = MIN_SEND_CLIENT_HEIGHT
MAX_SAFE_WINDOW_WIDTH = 2560
MAX_SAFE_WINDOW_HEIGHT = 1600
MIN_CAPTURE_WINDOW_WIDTH = 420
MIN_CAPTURE_WINDOW_HEIGHT = 260
OFFSCREEN_GEOMETRY_BOUNDARY = -30000
DEFAULT_SEND_MIN_INTERVAL_SECONDS = 30
DEFAULT_SEND_BURST_WINDOW_SECONDS = 600
DEFAULT_SEND_BURST_LIMIT = 5
DEFAULT_SEND_MODE = "uia_first"
DEFAULT_UI_ACTION_BUDGET_WINDOW_SECONDS = 60
DEFAULT_UI_ACTION_BUDGET_LIMIT = 80
DEFAULT_UI_ACTION_KEYBOARD_MIN_GAP_MS = 34
DEFAULT_UI_ACTION_MOUSE_MIN_GAP_MS = 110
DEFAULT_UI_ACTION_SCROLL_MIN_GAP_MS = 140
DEFAULT_UI_ACTION_FOCUS_MIN_GAP_MS = 180
DEFAULT_UI_ACTION_KIND_SWITCH_GAP_MS = 170
DEFAULT_UI_ACTION_NEAR_POINT_RADIUS_PX = 7
DEFAULT_UI_ACTION_NEAR_POINT_GAP_MS = 720
DEFAULT_UI_ACTION_NEAR_POINT_SOFT_LIMIT = 2
DEFAULT_RENDER_RECOVERY_MIN_INTERVAL_SECONDS = 180
DEFAULT_QUICK_LOGIN_AUTO_ENTER = False
DEFAULT_TARGET_READY_MAX_ATTEMPTS = 1
BLANK_RENDER_BRIGHT_MIN = 238.0
BLANK_RENDER_DARK_MAX = 18.0
BLANK_RENDER_STDDEV_MAX = 8.0
BLANK_RENDER_DENSE_RATIO_MIN = 0.93
BLANK_RENDER_BORDERED_BRIGHT_MIN = 245.0
BLANK_RENDER_BORDERED_DENSE_RATIO_MIN = 0.965
DEFAULT_HUMANIZED_INPUT_ENABLED = True
DEFAULT_HUMANIZED_INPUT_METHOD = "sendinput_unicode"
DEFAULT_HUMANIZED_INPUT_ENFORCE_INTERMITTENT = True
DEFAULT_HUMANIZED_ALLOW_CLIPBOARD_ONCE = False
DEFAULT_HUMANIZED_TYPING_CHUNK_MIN_CHARS = 2
DEFAULT_HUMANIZED_TYPING_CHUNK_MAX_CHARS = 6
DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS = 50
DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS = 180
DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_EVERY_CHARS = 18
DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS = 220
DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS = 650
DEFAULT_HUMANIZED_TYPING_TYPO_PROBABILITY = 0.22
DEFAULT_HUMANIZED_TYPING_TYPO_MAX = 1
DEFAULT_HUMANIZED_SEND_PRE_DELAY_MIN_MS = 280
DEFAULT_HUMANIZED_SEND_PRE_DELAY_MAX_MS = 1300
DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS = 120
DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS = 460
DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MIN_MS = 420
DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MAX_MS = 1350
DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MIN_MS = 220
DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MAX_MS = 760
DEFAULT_HUMANIZED_ADAPTIVE_SPEED_ENABLED = True
DEFAULT_HUMANIZED_SHORT_TEXT_CHARS = 90
DEFAULT_HUMANIZED_LONG_TEXT_CHARS = 240
DEFAULT_INPUT_COPYBACK_STRONG_CONFIRM = False
DEFAULT_SEND_INPUT_CONFIRM_ATTEMPTS = 3
DEFAULT_INPUT_FAST_VISUAL_CONFIRM = False
DEFAULT_POST_SEND_STRICT_CONFIRM = False
DEFAULT_SEND_TRIGGER_MODE = "enter_only"
DEFAULT_STRICT_SEND_FOCUS_GUARD = True
DEFAULT_FOCUS_CLICK_FALLBACK = True
DEFAULT_ALLOW_UNKNOWN_FOREGROUND_GUARD = True
INPUT_TEXT_DARK_RATIO_MIN = 0.0025
INPUT_TEXT_SOFT_BLANK_DARK_RATIO_MAX = 0.035
INPUT_TEXT_SOFT_BLANK_MEAN_MIN = 242.0
HUMANIZED_TYPO_CANDIDATES = "asdfjkl;,.?/[]"
SENDINPUT_INPUT_KEYBOARD = 1
SENDINPUT_KEYEVENTF_KEYUP = 0x0002
SENDINPUT_KEYEVENTF_UNICODE = 0x0004
HARD_BLOCKING_SCREEN_TOKENS = (
    "文件名无效",
    "存储空间已满",
    "无法继续使用微信",
    "清理出足够存储空间",
)
SOFT_BLOCKING_SCREEN_TOKENS = (
    "选择文件",
    "安全验证",
    "账号安全",
    "登录环境异常",
    "操作频繁",
    "拖拽",
)
WECHAT_LOGIN_OR_SECURITY_BLOCK_TOKENS = (
    "请重新登录",
    "重新登录",
    "登录已过期",
    "登录失效",
    "退出登录",
    "无法继续使用微信",
    "账号安全",
    "安全验证",
    "登录环境异常",
    "操作频繁",
    "账号异常",
    "被限制",
    "限制使用",
)
FOREIGN_CAPTURE_TOKENS = (
    "apps/wechat_ai_customer_servic",
    "new project",
    "展开显示",
    "文件已更改",
    "serverchan",
    "要求后续变更",
)

_OCR_ENGINE: RapidOCR | None = None


def clipboard_copy(text: str) -> None:
    if _pyperclip is not None:
        _pyperclip.copy(text)
        return
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return
    except Exception as exc:
        raise RuntimeError("clipboard_copy_unavailable: install pyperclip or enable tkinter clipboard support") from exc


def clipboard_read() -> str:
    if _pyperclip is not None:
        return str(_pyperclip.paste() or "")
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        value = root.clipboard_get()
        root.destroy()
        return str(value or "")
    except Exception as exc:
        raise RuntimeError("clipboard_read_unavailable: install pyperclip or enable tkinter clipboard support") from exc


def main() -> int:
    configure_dpi_awareness()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=SIDECAR_ACTION_CHOICES, nargs="?")
    parser.add_argument("--target", help="Chat name for messages/send.")
    parser.add_argument("--session-key", default="", help="Internal session key for row-level RPA targeting.")
    parser.add_argument("--text", help="Message text for send.")
    parser.add_argument("--phone", default="", help="Phone number for add-friend.")
    parser.add_argument("--wechat", default="", help="WeChat ID for add-friend fallback.")
    parser.add_argument("--verify-message", default="", help="Required add-friend verification message for the entry-click route.")
    parser.add_argument("--remark-name", default="", help="Required WeChat remark name for the entry-click route.")
    parser.add_argument("--remark-code", default="", help="Required system remark code that must be included in remark-name.")
    parser.add_argument("--calibration-only", action="store_true", help="For add-friend routes, capture/OCR/locate/report without clicking.")
    parser.add_argument("--exact", action="store_true", help="Use exact chat name matching.")
    parser.add_argument(
        "--skip-send-rate-guard",
        action="store_true",
        help="Skip rate guard reservation for controlled loopback simulation only.",
    )
    parser.add_argument("--history-load-times", type=int, default=0, help="Scroll upward this many times before reading messages.")
    parser.add_argument("--history-mode", default="", help="History loading strategy, e.g. anchor_until_found.")
    parser.add_argument("--anchor-id", action="append", default=[], help="Message id anchor to stop bounded history search.")
    parser.add_argument("--anchor-content-key", action="append", default=[], help="Normalized customer message content key anchor.")
    parser.add_argument("--reply-content-key", action="append", default=[], help="Normalized self reply content key anchor.")
    parser.add_argument("--max-scroll-steps", type=int, default=6, help="Maximum bounded upward scroll steps for anchor history search.")
    parser.add_argument("--max-duration-seconds", type=int, default=12, help="Maximum bounded anchor history search duration.")
    parser.add_argument("--max-snapshots", type=int, default=8, help="Maximum screenshots during anchor history search.")
    parser.add_argument("--min-delay-ms", type=int, default=180, help="Minimum pause between bounded anchor search scrolls.")
    parser.add_argument("--max-delay-ms", type=int, default=650, help="Maximum pause between bounded anchor search scrolls.")
    parser.add_argument("--restore-to-latest", dest="restore_to_latest", action="store_true", default=None)
    parser.add_argument("--no-restore-to-latest", dest="restore_to_latest", action="store_false")
    parser.add_argument("--artifact-dir", help="Optional directory for debug screenshots.")
    args = parser.parse_args()

    captured = io.StringIO()
    try:
        payload = run_action(args)
    except Exception as exc:
        payload = {"ok": False, "online": False, "state": "win32_ocr_failed", "error": repr(exc)}

    logs = captured.getvalue().strip()
    if logs:
        payload["library_stdout"] = logs
    # This JSON is consumed by parent processes over stdout on Windows.
    # Keep it ASCII-safe so Chinese OCR/window text round-trips after json.loads.
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload.get("ok") else 1


def run_action(args: argparse.Namespace) -> dict[str, Any]:
    action = str(args.action or "").strip().lower()
    if action in ADD_FRIEND_ROUTES:
        validation = validate_add_friend_entry_click_contract(
            phone=str(args.phone or ""),
            wechat=str(args.wechat or ""),
            verify_message=str(args.verify_message or ""),
            remark_name=str(args.remark_name or ""),
            remark_code=str(args.remark_code or ""),
        )
        if not validation.get("ok"):
            return add_friend_entry_click_validation_failure_payload(
                phone=str(args.phone or ""),
                wechat=str(args.wechat or ""),
                verify_message=str(args.verify_message or ""),
                remark_name=str(args.remark_name or ""),
                remark_code=str(args.remark_code or ""),
                artifact_dir=args.artifact_dir,
                probe={"skipped": True, "reason": "task_payload_invalid_before_window_probe"},
            )
    if _WIN32_IMPORT_ERROR:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "pywin32_unavailable",
            "error": _WIN32_IMPORT_ERROR,
        }
    passive_probe = use_passive_probe_mode(action)
    probe = ensure_visible_wechat_window(interactive=not passive_probe)
    if not probe.get("visible_main_windows"):
        if wechat_main_window_is_tray_hidden(probe):
            return {
                "ok": False,
                "online": False,
                "adapter": "win32_ocr",
                "scheme": "win32_ocr_window_in_tray",
                "state": "main_window_in_tray",
                "reason": "wechat_window_in_tray",
                "window_probe": probe,
                "receive": {"ok": False},
                "send": {"ok": False},
                "manual_action_required": "open_wechat_main_window",
                "error": "WeChat is running but its main window is hidden in tray. Open the main window manually before automation.",
            }
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_not_found",
            "window_probe": probe,
            "error": "No visible WeChat main window was found.",
        }
    window = select_primary_visible_main_window(probe)
    if not window:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_not_found",
            "window_probe": probe,
            "error": "No visible WeChat main window was selected.",
        }
    probe["selected_main_window"] = dict(window)
    hwnd = int(window.get("hwnd") or 0)
    if not hwnd:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_not_found",
            "window_probe": probe,
            "error": "Visible WeChat window did not expose an hwnd.",
        }

    probe["passive_probe"] = passive_probe
    if not passive_probe:
        activate_window(hwnd)
        normalized_window = normalize_wechat_window(hwnd)
        probe["window_normalization"] = normalized_window
        if normalized_window.get("applied"):
            humanized_action_sleep(210, 330)
        quick_login = ensure_quick_login_if_available(
            hwnd,
            artifact_dir=args.artifact_dir,
            auto_enter=env_flag("WECHAT_WIN32_OCR_QUICK_LOGIN_AUTO_ENTER", default=DEFAULT_QUICK_LOGIN_AUTO_ENTER),
        )
        probe["quick_login"] = quick_login
        if quick_login.get("attempted"):
            humanized_action_sleep(380, 560)
        humanized_action_sleep(140, 260)
    else:
        probe["window_normalization"] = {
            "ok": True,
            "enabled": False,
            "applied": False,
            "reason": "passive_probe_mode",
        }
        probe["quick_login"] = {
            "attempted": False,
            "detected": False,
            "reason": "passive_probe_mode",
        }
        humanized_action_sleep(35, 80)
    if action == "status":
        return status_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if action == "capabilities":
        return capabilities_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if action == "recover-render":
        return recover_blank_render_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if action == "sessions":
        return sessions_payload(hwnd, probe, artifact_dir=args.artifact_dir)
    if action == "messages":
        if args.target:
            clean_session_key = str(args.session_key or "").strip()
            validation = (
                {"ok": False, "reason": "session_key_requires_row_activation"}
                if clean_session_key
                else validate_active_send_target(
                    hwnd,
                    args.target,
                    exact=bool(args.exact),
                    artifact_dir=args.artifact_dir,
                )
            )
            opened = False
            if not validation.get("ok"):
                opened = open_chat(
                    hwnd,
                    args.target,
                    exact=bool(args.exact),
                    artifact_dir=args.artifact_dir,
                    session_key=clean_session_key,
                )
                humanized_action_sleep(380, 620)
                validation = validate_active_send_target(
                    hwnd,
                    args.target,
                    exact=bool(args.exact),
                    artifact_dir=args.artifact_dir,
                )
            if not validation.get("ok"):
                return {
                    "ok": False,
                    "online": bool(validation.get("online", True)),
                    "adapter": "win32_ocr",
                    "state": "target_not_confirmed_for_messages",
                    "window_probe": probe,
                    "target": args.target,
                    "opened": bool(opened),
                    "guard": validation,
                    "error": "The target chat was not confirmed before reading messages.",
                }
            if scroll_to_latest_before_read_enabled():
                scroll_chat_to_latest(hwnd)
        load_times = bounded_int(args.history_load_times, default=0, minimum=0, maximum=16)
        return messages_payload(
            hwnd,
            probe,
            target=args.target or "",
            history_load_times=load_times,
            history_mode=str(args.history_mode or ""),
            anchor_ids=[str(item) for item in args.anchor_id or []],
            anchor_content_keys=[str(item) for item in args.anchor_content_key or []],
            reply_content_keys=[str(item) for item in args.reply_content_key or []],
            max_scroll_steps=bounded_int(args.max_scroll_steps, default=6, minimum=0, maximum=16),
            max_duration_seconds=bounded_int(args.max_duration_seconds, default=12, minimum=1, maximum=60),
            max_snapshots=bounded_int(args.max_snapshots, default=8, minimum=1, maximum=24),
            min_delay_ms=bounded_int(args.min_delay_ms, default=180, minimum=0, maximum=5000),
            max_delay_ms=bounded_int(args.max_delay_ms, default=650, minimum=0, maximum=10000),
            restore_to_latest=True if args.restore_to_latest is None else bool(args.restore_to_latest),
            artifact_dir=args.artifact_dir,
        )
    if action == "send":
        if not args.target:
            raise ValueError("--target is required for send")
        if args.text is None:
            raise ValueError("--text is required for send")
        target_ready = ensure_target_ready_for_send(
            hwnd,
            args.target,
            exact=bool(args.exact),
            artifact_dir=args.artifact_dir,
            session_key=str(args.session_key or ""),
        )
        if not target_ready.get("ok"):
            validation = target_ready.get("validation") or validate_active_send_target(
                hwnd,
                args.target,
                exact=bool(args.exact),
                artifact_dir=args.artifact_dir,
            )
            return {
                "ok": False,
                "online": True,
                "adapter": "win32_ocr",
                "state": "target_not_confirmed",
                "window_probe": probe,
                "target": args.target,
                "attempts": target_ready.get("attempts"),
                "guard": validation,
                "error": "The target chat was not confirmed before sending.",
            }
        return send_payload(
            hwnd,
            probe,
            target=args.target,
            text=args.text,
            exact=bool(args.exact),
            skip_send_rate_guard=bool(args.skip_send_rate_guard),
            artifact_dir=args.artifact_dir,
            validated_guard=target_ready.get("validation") if isinstance(target_ready.get("validation"), dict) else None,
        )
    if action in ADD_FRIEND_ROUTES:
        return add_friend_entry_click_plan_payload(
            hwnd,
            probe,
            route=action,
            phone=str(args.phone or ""),
            wechat=str(args.wechat or ""),
            verify_message=str(args.verify_message or ""),
            remark_name=str(args.remark_name or ""),
            remark_code=str(args.remark_code or ""),
            artifact_dir=args.artifact_dir,
            calibration_only=bool(getattr(args, "calibration_only", False)),
        )
    return {"ok": False, "online": False, "adapter": "win32_ocr", "state": "unsupported_action"}


def use_passive_probe_mode(action: str) -> bool:
    if action in {"status", "capabilities", "sessions"}:
        return env_flag("WECHAT_WIN32_OCR_PASSIVE_PROBE", default=True)
    if not add_friend_route_uses_passive_probe(action):
        return False
    return env_flag("WECHAT_WIN32_OCR_PASSIVE_PROBE", default=True)


def scroll_to_latest_before_read_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_SCROLL_TO_LATEST_BEFORE_READ", default=False)


def detect_blank_render(
    screenshot: Any,
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    ocr_count = len(ocr_items or [])
    if ocr_count > 0:
        return {
            "detected": False,
            "reason": "",
            "ocr_count": ocr_count,
            "metrics": {},
        }
    try:
        gray = screenshot.convert("L")
        stat = ImageStat.Stat(gray)
        mean = float((stat.mean or [0.0])[0])
        stddev = float((stat.stddev or [0.0])[0])
        histogram = gray.histogram()
        total = max(1, int(sum(histogram)))
        bright_ratio = float(sum(histogram[245:])) / total
        dark_ratio = float(sum(histogram[:10])) / total
    except Exception as exc:
        return {
            "detected": False,
            "reason": "render_metric_probe_failed",
            "error": repr(exc),
            "ocr_count": ocr_count,
            "metrics": {},
        }
    bright_blank = (
        mean >= BLANK_RENDER_BRIGHT_MIN
        and stddev <= BLANK_RENDER_STDDEV_MAX
        and bright_ratio >= BLANK_RENDER_DENSE_RATIO_MIN
    )
    dark_blank = (
        mean <= BLANK_RENDER_DARK_MAX
        and stddev <= BLANK_RENDER_STDDEV_MAX
        and dark_ratio >= BLANK_RENDER_DENSE_RATIO_MIN
    )
    bordered_bright_blank = (
        mean >= BLANK_RENDER_BORDERED_BRIGHT_MIN
        and bright_ratio >= BLANK_RENDER_BORDERED_DENSE_RATIO_MIN
        and int(geometry.get("width") or screenshot.size[0]) >= MIN_CAPTURE_WINDOW_WIDTH
        and int(geometry.get("height") or screenshot.size[1]) >= MIN_CAPTURE_WINDOW_HEIGHT
    )
    detected = bool(bright_blank or dark_blank or bordered_bright_blank)
    if bright_blank:
        reason = "blank_white_like"
    elif dark_blank:
        reason = "blank_dark_like"
    elif bordered_bright_blank:
        reason = "blank_bordered_white_like"
    else:
        reason = ""
    return {
        "detected": detected,
        "reason": reason,
        "ocr_count": ocr_count,
        "metrics": {
            "mean": round(mean, 3),
            "stddev": round(stddev, 3),
            "bright_ratio": round(bright_ratio, 4),
            "dark_ratio": round(dark_ratio, 4),
            "width": int(geometry.get("width") or screenshot.size[0]),
            "height": int(geometry.get("height") or screenshot.size[1]),
        },
        "thresholds": {
            "bright_min": BLANK_RENDER_BRIGHT_MIN,
            "dark_max": BLANK_RENDER_DARK_MAX,
            "stddev_max": BLANK_RENDER_STDDEV_MAX,
            "dense_ratio_min": BLANK_RENDER_DENSE_RATIO_MIN,
            "bordered_bright_min": BLANK_RENDER_BORDERED_BRIGHT_MIN,
            "bordered_dense_ratio_min": BLANK_RENDER_BORDERED_DENSE_RATIO_MIN,
        },
    }


def auxiliary_wechat_shell_like(ocr_items: list[dict[str, Any]], *, geometry: dict[str, Any]) -> dict[str, Any]:
    """Detect a Tencent/Qt shell window that is not the actual chat surface."""
    texts = [normalize_ocr_text(item.get("text")) for item in ocr_items if normalize_ocr_text(item.get("text"))]
    compact = [re.sub(r"\s+", "", text).lower() for text in texts]
    chat_surface_tokens = (
        "搜索",
        "文件传输助手",
        "发送",
        "聊天",
        "通讯录",
        "订阅号",
        "朋友圈",
        "小程序",
        "视频号",
    )
    if any(token in text for text in texts for token in chat_surface_tokens):
        return {"detected": False, "reason": "", "ocr_count": len(texts)}
    title_only_tokens = {"weixin", "wechat", "微信"}
    title_only = bool(texts) and len(texts) <= 2 and all(text in title_only_tokens for text in compact)
    too_sparse_for_chat = len(texts) <= 1 and int(geometry.get("width") or 0) >= MIN_CAPTURE_WINDOW_WIDTH
    detected = bool(title_only or too_sparse_for_chat)
    if title_only:
        reason = "title_only_shell"
    elif too_sparse_for_chat:
        reason = "sparse_auxiliary_shell"
    else:
        reason = ""
    return {
        "detected": detected,
        "reason": reason,
        "ocr_count": len(texts),
        "texts": texts[:5],
        "geometry": {
            "width": int(geometry.get("width") or 0),
            "height": int(geometry.get("height") or 0),
        },
    }


def recover_blank_render_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    initial = status_payload(hwnd, probe, artifact_dir=artifact_dir)
    initial_snapshot = sidecar_payload_snapshot(initial)
    if initial.get("ok") and initial.get("online"):
        initial["render_recovery"] = {
            "ok": True,
            "attempted": False,
            "reason": "wechat_render_already_ready",
        }
        return initial
    if not sidecar_payload_needs_render_recovery(initial):
        initial["render_recovery"] = {
            "ok": False,
            "attempted": False,
            "reason": "not_recoverable_render_state",
        }
        return initial
    if not env_flag("WECHAT_WIN32_OCR_RENDER_RECOVERY_AUTO", default=False):
        initial["render_recovery"] = {
            "ok": False,
            "attempted": False,
            "reason": "auto_render_recovery_disabled",
            "initial_status": initial_snapshot,
            "suggested_action": "stop_and_report_manual_tray_restore",
        }
        return initial

    reservation = reserve_render_recovery()
    if not reservation.get("ok"):
        initial["render_recovery"] = {
            **reservation,
            "attempted": False,
            "reason": reservation.get("reason") or "render_recovery_rate_limited",
        }
        return initial

    redraw = trigger_wechat_tray_redraw(hwnd, probe)
    humanized_action_sleep(1300, 1900)
    recovered_probe = probe_wechat_windows()
    quick_login_recovery = enter_quick_login_from_visible_windows(recovered_probe, artifact_dir=artifact_dir)
    if quick_login_recovery.get("attempted"):
        humanized_action_sleep(900, 1400)
    recovered_probe = ensure_visible_wechat_window(interactive=True)
    if quick_login_recovery:
        recovered_probe["recovery_quick_login"] = quick_login_recovery
    recovered_window = select_primary_visible_main_window(recovered_probe)
    if not recovered_window:
        initial["render_recovery"] = {
            "ok": False,
            "attempted": True,
            "reason": "main_window_not_found_after_redraw",
            "reservation": reservation,
            "redraw": redraw,
            "window_probe": recovered_probe,
        }
        return initial
    recovered_probe["selected_main_window"] = dict(recovered_window)
    recovered_hwnd = int(recovered_window.get("hwnd") or hwnd)
    if recovered_hwnd:
        activate_window(recovered_hwnd)
    final = status_payload(recovered_hwnd or hwnd, recovered_probe, artifact_dir=artifact_dir)
    final["render_recovery"] = {
        "ok": bool(final.get("ok") and final.get("online")),
        "attempted": True,
        "reason": "tray_redraw_reopen",
        "reservation": reservation,
        "redraw": redraw,
        "quick_login": quick_login_recovery,
        "initial_status": initial_snapshot,
    }
    if final.get("ok") and final.get("online"):
        return final
    initial["render_recovery"] = sidecar_payload_snapshot(final["render_recovery"])
    initial["recovered_status"] = sidecar_payload_snapshot(final)
    return initial


def enter_quick_login_from_visible_windows(probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    """Click a visible quick-login card during explicit render recovery only."""
    visible = list(probe.get("visible_main_windows") or [])
    candidates: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for item in visible:
        hwnd = int((item or {}).get("hwnd") or 0)
        if not hwnd:
            continue
        try:
            geometry = get_window_geometry(hwnd)
        except Exception:
            continue
        width = int(geometry.get("width") or 0)
        height = int(geometry.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        if width > LOGIN_WINDOW_MAX_WIDTH or height > LOGIN_WINDOW_MAX_HEIGHT:
            continue
        candidates.append((width * height, dict(item), geometry))
    candidates.sort(key=lambda row: row[0])
    for _area, item, geometry in candidates:
        hwnd = int(item.get("hwnd") or 0)
        try:
            activate_window(hwnd)
            humanized_action_sleep(160, 280)
            result = ensure_quick_login_if_available(hwnd, artifact_dir=artifact_dir, auto_enter=True)
        except Exception as exc:
            result = {"attempted": False, "detected": False, "error": repr(exc)}
        if result.get("detected"):
            return {
                **result,
                "hwnd": hwnd,
                "window": item,
                "geometry": geometry,
                "mode": "render_recovery_quick_login",
            }
    return {"attempted": False, "detected": False, "reason": "quick_login_window_not_found"}


def sidecar_payload_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return json.loads(json.dumps(payload, ensure_ascii=True, default=str))


def sidecar_payload_is_blank_render(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return str(payload.get("state") or "") == "blank_render_detected" or str(payload.get("reason") or "") == "blank_render"


def sidecar_payload_needs_render_recovery(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    if sidecar_payload_is_blank_render(payload):
        return True
    state = str(payload.get("state") or "")
    reason = str(payload.get("reason") or "")
    scheme = str(payload.get("scheme") or "")
    shell_probe = payload.get("shell_probe") if isinstance(payload.get("shell_probe"), dict) else {}
    shell_reason = str(shell_probe.get("reason") or "")
    sparse_shell = (
        state == "auxiliary_shell_window_detected"
        or reason == "auxiliary_shell_window"
        or scheme == "win32_ocr_auxiliary_shell"
    )
    if sparse_shell and shell_reason in {"sparse_auxiliary_shell", "title_only_shell"}:
        return True
    primary = payload.get("primary_status") if isinstance(payload.get("primary_status"), dict) else {}
    if primary:
        return sidecar_payload_needs_render_recovery(primary)
    return False


def reserve_render_recovery() -> dict[str, Any]:
    if env_flag("WECHAT_WIN32_OCR_RENDER_RECOVERY_GUARD", default=True) is False:
        return {"ok": True, "guard_enabled": False, "reason": "render_recovery_guard_disabled"}
    min_interval = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_RENDER_RECOVERY_MIN_INTERVAL_SECONDS"),
        default=DEFAULT_RENDER_RECOVERY_MIN_INTERVAL_SECONDS,
        minimum=30,
        maximum=3600,
    )
    now = time.time()
    previous: dict[str, Any] = {}
    if RENDER_RECOVERY_GUARD_PATH.exists():
        try:
            previous = json.loads(RENDER_RECOVERY_GUARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    last_at = float(previous.get("last_at") or 0)
    remaining = int(max(0, min_interval - (now - last_at)))
    if last_at > 0 and remaining > 0:
        return {
            "ok": False,
            "guard_enabled": True,
            "reason": "render_recovery_rate_limited",
            "retry_after_seconds": remaining,
            "min_interval_seconds": min_interval,
        }
    RENDER_RECOVERY_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RENDER_RECOVERY_GUARD_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(
            {
                "last_at": now,
                "last_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)),
                "min_interval_seconds": min_interval,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(tmp, RENDER_RECOVERY_GUARD_PATH)
    return {"ok": True, "guard_enabled": True, "min_interval_seconds": min_interval}


def trigger_wechat_tray_redraw(hwnd: int, probe: dict[str, Any]) -> dict[str, Any]:
    selected = probe.get("selected_main_window") if isinstance(probe.get("selected_main_window"), dict) else {}
    exe_path = str(selected.get("path") or "").strip()
    if not exe_path:
        for item in probe.get("windows") or []:
            candidate = str((item or {}).get("path") or "").strip()
            if candidate.lower().endswith("weixin.exe"):
                exe_path = candidate
                break
    close_posted = False
    launch_attempted = False
    launch_error = ""
    try:
        if hwnd:
            ensure_left_button_released()
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            close_posted = True
            humanized_action_sleep(800, 1200)
    except Exception:
        close_posted = False
    if exe_path and Path(exe_path).exists():
        try:
            subprocess.Popen([exe_path], cwd=str(Path(exe_path).parent))
            launch_attempted = True
        except Exception as exc:
            launch_error = repr(exc)
    else:
        launch_error = "weixin_exe_path_missing"
    return {
        "ok": bool(close_posted and launch_attempted and not launch_error),
        "method": "wm_close_to_tray_then_launch_weixin",
        "close_posted": close_posted,
        "launch_attempted": launch_attempted,
        "exe_path": exe_path,
        "error": launch_error,
    }


def status_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    geometry = get_window_geometry(hwnd)
    geometry_check = validate_capture_geometry(geometry)
    focus_guard = foreground_window_matches_target(hwnd)
    if not geometry_check.get("ok"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "main_window_geometry_invalid",
            "reason": str(geometry_check.get("reason") or ""),
            "window_probe": probe,
            "geometry": geometry,
            "focus_guard": focus_guard,
            "screenshot_path": "",
            "ocr_count": 0,
            "compat_reason": "rpa_primary",
            "error": str(geometry_check.get("error") or "WeChat window geometry is not ready for capture."),
        }
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="status")
    ocr_items = run_ocr(screenshot)
    login_like = quick_login_like(ocr_items, geometry=geometry)
    if login_like:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "login_window_detected",
            "window_probe": probe,
            "geometry": geometry,
            "focus_guard": focus_guard,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "compat_reason": "rpa_primary",
            "error": "WeChat is still in quick-login view. Enter WeChat first before running automation.",
        }
    blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
    if blank_render.get("detected"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "blank_render_detected",
            "reason": "blank_render",
            "window_probe": probe,
            "geometry": geometry,
            "focus_guard": focus_guard,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "render_probe": blank_render,
            "compat_reason": "rpa_primary",
            "error": "WeChat window appears blank (render stalled); restart WeChat window before automation.",
        }
    auxiliary_shell = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    if auxiliary_shell.get("detected"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "auxiliary_shell_window_detected",
            "reason": "auxiliary_shell_window",
            "window_probe": probe,
            "geometry": geometry,
            "focus_guard": focus_guard,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "shell_probe": auxiliary_shell,
            "compat_reason": "rpa_primary",
            "error": "Selected WeChat window looks like an auxiliary shell, not the logged-in chat window.",
        }
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "main_window_compat",
        "window_probe": probe,
        "geometry": geometry,
        "focus_guard": focus_guard,
        "screenshot_path": path,
        "ocr_count": len(ocr_items),
        "compat_reason": "rpa_primary",
    }
def capabilities_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    geometry = get_window_geometry(hwnd)
    geometry_check = validate_capture_geometry(geometry)
    focus_guard = foreground_window_matches_target(hwnd)
    if not geometry_check.get("ok"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "scheme": "win32_ocr_window_geometry_invalid",
            "state": "main_window_geometry_invalid",
            "reason": str(geometry_check.get("reason") or ""),
            "window_probe": probe,
            "screenshot_path": "",
            "ocr_count": 0,
            "geometry": geometry,
            "focus_guard": focus_guard,
            "receive": {"ok": False},
            "send": {"ok": False},
            "compat_reason": "rpa_primary",
            "error": str(geometry_check.get("error") or "WeChat window geometry is not ready for capture."),
        }
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="capabilities")
    ocr_items = run_ocr(screenshot)
    if quick_login_like(ocr_items, geometry=geometry):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "scheme": "wechat_not_online",
            "state": "login_window_detected",
            "window_probe": probe,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "geometry": geometry,
            "focus_guard": focus_guard,
            "receive": {"ok": False},
            "send": {"ok": False},
            "compat_reason": "rpa_primary",
            "error": "WeChat quick-login view detected; enter WeChat before automation.",
        }
    blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
    if blank_render.get("detected"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "scheme": "win32_ocr_blank_render",
            "state": "blank_render_detected",
            "reason": "blank_render",
            "window_probe": probe,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "geometry": geometry,
            "focus_guard": focus_guard,
            "render_probe": blank_render,
            "receive": {"ok": False, "blocked_by": "blank_render"},
            "send": {"ok": False},
            "compat_reason": "rpa_primary",
            "error": "WeChat window appears blank (render stalled); restart WeChat window before automation.",
        }
    auxiliary_shell = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    if auxiliary_shell.get("detected"):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "scheme": "win32_ocr_auxiliary_shell",
            "state": "auxiliary_shell_window_detected",
            "reason": "auxiliary_shell_window",
            "window_probe": probe,
            "screenshot_path": path,
            "ocr_count": len(ocr_items),
            "geometry": geometry,
            "focus_guard": focus_guard,
            "shell_probe": auxiliary_shell,
            "receive": {"ok": False, "blocked_by": "auxiliary_shell_window"},
            "send": {"ok": False},
            "compat_reason": "rpa_primary",
            "error": "Selected WeChat window looks like an auxiliary shell, not the logged-in chat window.",
        }
    blocking_reason = blocking_screen_reason(ocr_items)
    online = blocking_reason != "login_or_qr"
    geometry_check = validate_send_geometry(geometry)
    points = calculate_send_points(geometry) if geometry_check.get("ok") else geometry_check
    uia = inspect_uia_send_capability(hwnd, geometry) if geometry_check.get("ok") else {
        "ok": False,
        "reason": "geometry_unavailable_for_uia",
        "geometry": geometry,
    }
    receive = {
        "ok": bool(online and not blocking_reason),
        "method": "win32.screenshot+rapidocr",
        "blocked_by": blocking_reason,
    }
    guarded_click = {
        "ok": bool(online and not blocking_reason and geometry_check.get("ok") and points.get("ok")),
        "method": "win32.human_click_input+rpa_text_entry+human_click_send",
        "geometry": geometry_check,
        "points": points,
        "rate_guard": {
            "enabled": env_flag("WECHAT_WIN32_OCR_SEND_RATE_GUARD", default=True),
            "min_interval_seconds": env_int("WECHAT_WIN32_OCR_SEND_MIN_INTERVAL_SECONDS", DEFAULT_SEND_MIN_INTERVAL_SECONDS),
            "burst_window_seconds": env_int("WECHAT_WIN32_OCR_SEND_BURST_WINDOW_SECONDS", DEFAULT_SEND_BURST_WINDOW_SECONDS),
            "burst_limit": env_int("WECHAT_WIN32_OCR_SEND_BURST_LIMIT", DEFAULT_SEND_BURST_LIMIT),
        },
        "humanized_input": humanized_input_settings(),
    }
    if not online:
        scheme = "wechat_not_online"
    elif blocking_reason:
        scheme = "win32_ocr_blocked"
    elif uia.get("ok"):
        scheme = "win32_ocr_uia"
    elif guarded_click.get("ok"):
        scheme = "win32_ocr_guarded_click"
    elif receive.get("ok"):
        scheme = "win32_ocr_receive_only"
    else:
        scheme = "win32_ocr_unavailable"
    send_ok = bool(uia.get("ok") or guarded_click.get("ok"))
    return {
        "ok": bool(online and receive.get("ok")),
        "online": bool(online),
        "adapter": "win32_ocr",
        "scheme": scheme,
        "state": "capabilities_ocr",
        "window_probe": probe,
        "screenshot_path": path,
        "ocr_count": len(ocr_items),
        "geometry": geometry,
        "focus_guard": focus_guard,
        "blocking_reason": blocking_reason,
        "receive": receive,
        "send": {
            "ok": send_ok,
            "preferred_mode": "uia" if uia.get("ok") else ("guarded_human_click" if guarded_click.get("ok") else ""),
            "uia": uia,
            "guarded_click": guarded_click,
        },
        "compat_reason": "rpa_primary",
    }
def sessions_payload(hwnd: int, probe: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="sessions")
    items = run_ocr(screenshot)
    geometry = get_window_geometry(hwnd)
    page_fingerprint = ocr_page_fingerprint(items, geometry=geometry)
    if quick_login_like(items, geometry=geometry):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "login_window_detected",
            "window_probe": probe,
            "screenshot_path": path,
            "ocr_items_count": len(items),
            "error": "WeChat quick-login view detected; enter WeChat before reading sessions.",
        }
    blocking_reason = blocking_screen_reason(items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason == "login_or_qr" else True,
            "adapter": "win32_ocr",
            "state": "sessions_blocked",
            "window_probe": probe,
            "screenshot_path": path,
            "ocr_items_count": len(items),
            "reason": blocking_reason,
            "error": f"WeChat session list is blocked by: {blocking_reason}",
        }
    sessions = parse_sessions_from_ocr(items, screenshot.size, screenshot=screenshot)
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
            "state": "sessions_ocr",
            "window_probe": probe,
            "screenshot_path": path,
            "page_fingerprint": page_fingerprint,
            "passive_probe": bool(probe.get("passive_probe")),
            "sessions": [
            {
                "name": item["name"],
                "title": item["name"],
                "session_key": item.get("session_key", ""),
                "row_fingerprint": item.get("row_fingerprint", {}),
                "duplicate_name_index": item.get("duplicate_name_index", 0),
                "ambiguous_display_name": bool(item.get("ambiguous_display_name")),
                "content": item.get("preview", ""),
                "time": item.get("time", ""),
                "unread_badge": item.get("unread_badge", ""),
                "unread": item.get("unread_badge", ""),
                "unread_signal": bool(item.get("unread_badge")),
                "conversation_type": item.get("conversation_type") or infer_conversation_type(item["name"]),
                "source_adapter": "win32_ocr",
                "ocr_confidence": item.get("confidence"),
            }
            for item in sessions
        ],
        "ocr_items_count": len(items),
    }


def messages_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    target: str,
    history_load_times: int,
    history_mode: str = "",
    anchor_ids: list[str] | None = None,
    anchor_content_keys: list[str] | None = None,
    reply_content_keys: list[str] | None = None,
    max_scroll_steps: int = 6,
    max_duration_seconds: int = 12,
    max_snapshots: int = 8,
    min_delay_ms: int = 180,
    max_delay_ms: int = 650,
    restore_to_latest: bool = True,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    mode = str(history_mode or "").strip().lower()
    if mode == "anchor_until_found":
        snapshots, history_load = capture_message_history_snapshots_until_anchor(
            hwnd,
            target=target,
            anchor_ids=anchor_ids or [],
            anchor_content_keys=anchor_content_keys or [],
            reply_content_keys=reply_content_keys or [],
            max_scroll_steps=max_scroll_steps,
            max_duration_seconds=max_duration_seconds,
            max_snapshots=max_snapshots,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
            restore_to_latest=restore_to_latest,
            artifact_dir=artifact_dir,
        )
    else:
        snapshots = capture_message_history_snapshots(
            hwnd,
            target=target,
            history_load_times=history_load_times,
            artifact_dir=artifact_dir,
        )
        history_load = {
            "ok": True,
            "mode": "fixed_load_times",
            "requested_load_times": history_load_times,
            "mechanism": "win32_ocr.WheelUp+ScreenshotOCR",
            "snapshot_count": len(snapshots),
        }
    latest = snapshots[-1] if snapshots else {}
    ocr_items = latest.get("ocr_items", []) if isinstance(latest.get("ocr_items"), list) else []
    geometry = get_window_geometry(hwnd)
    page_fingerprint = ocr_page_fingerprint(ocr_items, geometry=geometry)
    if quick_login_like(ocr_items, geometry=geometry):
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "login_window_detected",
            "window_probe": probe,
            "screenshot_path": str(latest.get("screenshot_path") or ""),
            "chat_info": {"chat_name": target, "source_adapter": "win32_ocr"},
            "ocr_items_count": len(ocr_items),
            "error": "WeChat quick-login view detected; enter WeChat before reading messages.",
        }
    blocking_reason = blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason == "login_or_qr" else True,
            "adapter": "win32_ocr",
            "state": "messages_blocked",
            "window_probe": probe,
            "screenshot_path": str(latest.get("screenshot_path") or ""),
            "chat_info": {"chat_name": target, "source_adapter": "win32_ocr"},
            "ocr_items_count": len(ocr_items),
            "reason": blocking_reason,
            "error": f"WeChat messages view is blocked by: {blocking_reason}",
        }
    messages = merge_message_history_snapshots(snapshots)
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "messages_ocr",
        "window_probe": probe,
        "screenshot_path": str(latest.get("screenshot_path") or ""),
        "page_fingerprint": page_fingerprint,
        "passive_probe": bool(probe.get("passive_probe")),
        "chat_info": {"chat_name": target, "source_adapter": "win32_ocr"},
        "history_load": history_load,
        "messages": messages,
        "ocr_items_count": len(ocr_items),
    }


def ocr_page_fingerprint(ocr_items: list[dict[str, Any]], *, geometry: dict[str, Any]) -> dict[str, Any]:
    normalized: list[str] = []
    for item in ocr_items or []:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        normalized.append(
            "|".join(
                [
                    str(round(float(item.get("center_x") or 0) / 8.0)),
                    str(round(float(item.get("center_y") or 0) / 8.0)),
                    text,
                ]
            )
        )
    seed = "\n".join(normalized)
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16] if seed else ""
    return {
        "hash": digest,
        "ocr_count": len(normalized),
        "width": int(geometry.get("width") or 0),
        "height": int(geometry.get("height") or 0),
    }


def capture_message_history_snapshots(
    hwnd: int,
    *,
    target: str,
    history_load_times: int,
    artifact_dir: str | None = None,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []

    def capture(label: str) -> None:
        screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label=label)
        ocr_items = run_ocr(screenshot)
        snapshots.append(
            {
                "label": label,
                "screenshot_path": path,
                "ocr_items": ocr_items,
                "messages": parse_messages_from_ocr(ocr_items, screenshot.size, target=target),
            }
        )

    capture("messages")
    for index in range(max(0, int(history_load_times or 0))):
        scroll_chat_history(hwnd, 1)
        humanized_action_sleep(70, 140)
        capture(f"messages_h{index + 1}")
    if history_load_times:
        scroll_chat_to_latest(hwnd, attempts=max(16, int(history_load_times or 0) * 6 + 6))
    return snapshots


def capture_message_history_snapshots_until_anchor(
    hwnd: int,
    *,
    target: str,
    anchor_ids: list[str],
    anchor_content_keys: list[str],
    reply_content_keys: list[str],
    max_scroll_steps: int,
    max_duration_seconds: int,
    max_snapshots: int,
    min_delay_ms: int,
    max_delay_ms: int,
    restore_to_latest: bool,
    artifact_dir: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    anchor_id_set = {str(item).strip() for item in anchor_ids or [] if str(item).strip()}
    anchor_content_set = {str(item).strip() for item in anchor_content_keys or [] if str(item).strip()}
    reply_content_set = {normalize_anchor_reply_key(item) for item in reply_content_keys or [] if normalize_anchor_reply_key(item)}
    start = time.monotonic()

    history_load: dict[str, Any] = {
        "ok": True,
        "mode": "anchor_until_found",
        "mechanism": "win32_ocr.AnchorSearch+WheelUp+ScreenshotOCR",
        "anchor_found": False,
        "anchor_index": -1,
        "anchor_type": "",
        "scroll_steps": 0,
        "snapshot_count": 0,
        "stopped_reason": "",
        "restored_to_latest": False,
        "max_scroll_steps": max_scroll_steps,
        "max_duration_seconds": max_duration_seconds,
        "max_snapshots": max_snapshots,
    }

    def capture(label: str) -> None:
        screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label=label)
        ocr_items = run_ocr(screenshot)
        snapshots.append(
            {
                "label": label,
                "screenshot_path": path,
                "ocr_items": ocr_items,
                "messages": parse_messages_from_ocr(ocr_items, screenshot.size, target=target),
            }
        )
        history_load["snapshot_count"] = len(snapshots)

    def find_anchor() -> tuple[int, str]:
        merged = merge_message_history_snapshots(snapshots)
        latest_index = -1
        latest_type = ""
        for index, message in enumerate(merged):
            anchor_type = message_anchor_match_type(
                message,
                anchor_ids=anchor_id_set,
                anchor_content_keys=anchor_content_set,
                reply_content_keys=reply_content_set,
            )
            if anchor_type:
                latest_index = index
                latest_type = anchor_type
        return latest_index, latest_type

    try:
        capture("messages")
        anchor_index, anchor_type = find_anchor()
        if anchor_index >= 0:
            history_load.update(
                {
                    "anchor_found": True,
                    "anchor_index": anchor_index,
                    "anchor_type": anchor_type,
                    "stopped_reason": "visible_anchor_found_no_scroll",
                }
            )
            return snapshots, history_load

        if not (anchor_id_set or anchor_content_set or reply_content_set):
            history_load["stopped_reason"] = "no_anchor_candidates"
            return snapshots, history_load

        for step in range(max(0, int(max_scroll_steps or 0))):
            if len(snapshots) >= max(1, int(max_snapshots or 1)):
                history_load["stopped_reason"] = "max_snapshots_reached"
                break
            if time.monotonic() - start >= max(1, int(max_duration_seconds or 1)):
                history_load["stopped_reason"] = "max_duration_reached"
                break
            scroll_chat_history(
                hwnd,
                1,
                wheel_units=random.randint(3, 6),
                delay_seconds=random.uniform(0.12, 0.28),
            )
            history_load["scroll_steps"] = step + 1
            pause_min = max(0, int(min_delay_ms or 0)) / 1000.0
            pause_max = max(pause_min, int(max_delay_ms or 0) / 1000.0)
            time.sleep(random.uniform(pause_min, pause_max))
            capture(f"messages_anchor_h{step + 1}")
            anchor_index, anchor_type = find_anchor()
            if anchor_index >= 0:
                history_load.update(
                    {
                        "anchor_found": True,
                        "anchor_index": anchor_index,
                        "anchor_type": anchor_type,
                        "stopped_reason": "anchor_found",
                    }
                )
                break
        if not history_load.get("stopped_reason"):
            history_load["stopped_reason"] = "max_scroll_steps_reached"
    except Exception as exc:
        history_load.update({"ok": False, "stopped_reason": "exception", "error": repr(exc)})
    finally:
        if restore_to_latest and int(history_load.get("scroll_steps") or 0) > 0:
            scroll_chat_to_latest(hwnd, attempts=max(10, int(history_load.get("scroll_steps") or 0) * 5 + 5))
            history_load["restored_to_latest"] = True
    return snapshots, history_load


def merge_message_history_snapshots(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for snapshot in reversed(snapshots):
        occurrence_counts: dict[str, int] = {}
        for message in snapshot.get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            occurrence_hint = None
            base_key = message_history_dedupe_base_key(message)
            if base_key and message_history_requires_occurrence_hint(message, base_key=base_key):
                occurrence_counts[base_key] = occurrence_counts.get(base_key, 0) + 1
                occurrence_hint = occurrence_counts[base_key]
            key = message_history_dedupe_key(message, occurrence_hint=occurrence_hint, base_key=base_key)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(message)
    return merged


def message_history_dedupe_base_key(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "")
    compact = re.sub(r"[\s_\-:：，。,.；;\[\]（）()]+", "", content).lower()
    sender = str(message.get("sender") or "")
    if not compact:
        return ""
    return f"{sender}:{compact}"


def message_history_requires_occurrence_hint(
    message: dict[str, Any],
    *,
    base_key: str | None = None,
    short_len_threshold: int = 7,
) -> bool:
    key = str(base_key or message_history_dedupe_base_key(message))
    if not key:
        return False
    compact = key.split(":", 1)[1] if ":" in key else key
    return len(compact) <= max(1, int(short_len_threshold or 1))


def message_history_dedupe_key(
    message: dict[str, Any],
    *,
    occurrence_hint: int | None = None,
    base_key: str | None = None,
) -> str:
    key = str(base_key or message_history_dedupe_base_key(message))
    if not key:
        return ""
    if occurrence_hint and message_history_requires_occurrence_hint(message, base_key=key):
        return f"{key}#occ{int(occurrence_hint)}"
    return key


def normalize_anchor_message_content(text: Any) -> str:
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(text or "")).lower()


def normalize_anchor_reply_key(text: Any) -> str:
    return normalize_anchor_message_content(text)


def sidecar_message_content_key(message: dict[str, Any]) -> str:
    content = normalize_anchor_message_content(message.get("content"))
    if not content:
        return ""
    return "\x1f".join(
        [
            str(message.get("sender") or "").strip(),
            str(message.get("type") or "").strip(),
            content,
        ]
    )


ADD_FRIEND_STEP_SEQUENCE = [
    "checking_rpa",
    "wechat_window_found",
    "phone_search_started",
    "phone_search_finished",
    "add_friend_button_clicked",
    "invite_text_filled",
    "remark_written",
    "invite_sent",
]


def add_friend_ocr_compact(text: Any) -> str:
    return mapped_compact_ocr_text(text)


def add_friend_item_text(item: dict[str, Any]) -> str:
    return mapped_ocr_item_text(item)


def add_friend_surface_text(ocr_items: list[dict[str, Any]]) -> str:
    return mapped_ocr_surface_text(ocr_items)


def add_friend_blocking_prompt_region(
    item: dict[str, Any],
    *,
    geometry: dict[str, Any] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    width = int((image_size or (0, 0))[0] or (geometry or {}).get("width") or 0)
    height = int((image_size or (0, 0))[1] or (geometry or {}).get("height") or 0)
    if width <= 0 or height <= 0:
        return {"region": "unknown", "sidebar_noise": False, "width": width, "height": height}
    center_x, center_y = add_friend_item_center(item)
    split_x = session_split_x(width)
    nav_right = max(64, min(92, int(width * 0.075)))
    search_bottom = max(112, min(148, int(height * 0.16)))
    sidebar_noise = nav_right < center_x < split_x and center_y > search_bottom
    return {
        "region": "sidebar_session_list" if sidebar_noise else add_friend_region_for_point(center_x, center_y, (width, height)),
        "sidebar_noise": sidebar_noise,
        "width": width,
        "height": height,
    }


def add_friend_login_or_security_block(
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any] | None = None,
    image_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    text = add_friend_surface_text(ocr_items)
    matched_items: list[dict[str, Any]] = []
    for item in ocr_items:
        item_text = add_friend_item_text(item)
        if not item_text:
            continue
        item_tokens = [token for token in WECHAT_LOGIN_OR_SECURITY_BLOCK_TOKENS if add_friend_text_has_any(item_text, (token,))]
        if not item_tokens:
            continue
        region = add_friend_blocking_prompt_region(item, geometry=geometry, image_size=image_size)
        matched_items.append({"text": item_text, "tokens": item_tokens, "region": region})
    matched = sorted({token for item in matched_items for token in item.get("tokens", [])})
    if not matched:
        return {"detected": False, "matched_tokens": [], "surface_text": text}
    strong_login = {"请重新登录", "登录已过期", "登录失效", "退出登录", "无法继续使用微信"}
    strong_security = {"账号安全", "登录环境异常", "操作频繁", "账号异常", "被限制", "限制使用"}
    small_window = int((geometry or {}).get("width") or 0) <= LOGIN_WINDOW_MAX_WIDTH and int((geometry or {}).get("height") or 0) <= LOGIN_WINDOW_MAX_HEIGHT
    accepted_items: list[dict[str, Any]] = []
    for item in matched_items:
        tokens = set(item.get("tokens") or [])
        item_text = str(item.get("text") or "")
        item_compact = add_friend_ocr_compact(item_text)
        item_compact_len = len(item_compact)
        region = item.get("region") if isinstance(item.get("region"), dict) else {}
        sidebar_noise = bool(region.get("sidebar_noise"))
        explanatory_chat_text = (
            "遇到" in item_compact
            and "状态" in item_compact
            and bool(tokens & {"安全验证", "操作频繁", "账号异常"})
        )
        if explanatory_chat_text:
            continue
        if tokens & strong_login and (small_window or not sidebar_noise):
            accepted_items.append(item)
            continue
        security_prompt_like = item_compact_len <= (44 if small_window else 20)
        if tokens & strong_security and (not sidebar_noise) and security_prompt_like:
            accepted_items.append(item)
            continue
        if "安全验证" in tokens and not sidebar_noise and item_compact_len <= 24:
            accepted_items.append(item)
    if not accepted_items:
        return {
            "detected": False,
            "matched_tokens": matched,
            "ignored_as_sidebar_preview": True,
            "matched_items": matched_items,
            "surface_text": text,
        }
    accepted_tokens = sorted({token for item in accepted_items for token in item.get("tokens", [])})
    account_restricted = any(token in accepted_tokens for token in ("账号安全", "安全验证", "登录环境异常", "操作频繁", "账号异常", "被限制", "限制使用"))
    return {
        "detected": True,
        "matched_tokens": accepted_tokens,
        "matched_items": accepted_items,
        "surface_text": text,
        "state": "account_restricted" if account_restricted else "wechat_window_not_ready",
        "error_code": ERROR_ACCOUNT_RESTRICTED if account_restricted else ERROR_WECHAT_WINDOW_NOT_READY,
        "reason": "wechat_account_or_security_prompt" if account_restricted else "wechat_login_required",
    }


def add_friend_item_center(item: dict[str, Any]) -> tuple[int, int]:
    return int(float(item.get("center_x") or 0)), int(float(item.get("center_y") or 0))


def center_of_bounds(bounds: list[int]) -> tuple[int, int]:
    if len(bounds) < 4:
        return 0, 0
    return int((int(bounds[0]) + int(bounds[2])) / 2), int((int(bounds[1]) + int(bounds[3])) / 2)


def add_friend_zone_bounds(image_size: tuple[int, int]) -> list[dict[str, Any]]:
    width, height = image_size
    split_x = session_split_x(width)
    nav_right = max(64, min(92, int(width * 0.075)))
    search_bottom = max(112, min(148, int(height * 0.16)))
    header_bottom = chat_header_cutoff_y(height) + max(32, int(height * 0.045))
    input_left, input_top, input_right, input_bottom = input_text_region_bounds({"width": width, "height": height})
    main_bottom = max(header_bottom + 40, min(height, input_top))
    return [
        {"name": "left_nav", "label": "left_nav", "bounds": [0, 0, nav_right, height], "color": "#2563eb"},
        {"name": "sidebar_search", "label": "sidebar_search", "bounds": [nav_right, 0, split_x, search_bottom], "color": "#059669"},
        {"name": "session_list", "label": "session_list", "bounds": [nav_right, search_bottom, split_x, height], "color": "#ca8a04"},
        {"name": "main_header", "label": "main_header", "bounds": [split_x, 0, width, header_bottom], "color": "#7c3aed"},
        {"name": "main_content", "label": "main_content", "bounds": [split_x, header_bottom, width, main_bottom], "color": "#dc2626"},
        {"name": "input_area", "label": "input_area", "bounds": [input_left, input_top, input_right, input_bottom], "color": "#0891b2"},
    ]


def point_in_bounds(x: int, y: int, bounds: list[int]) -> bool:
    left, top, right, bottom = [int(value) for value in bounds]
    return left <= x <= right and top <= y <= bottom


def clamp_point_to_bounds(x: int, y: int, bounds: list[int]) -> tuple[int, int]:
    left, top, right, bottom = [int(value) for value in bounds]
    return (
        bounded_int(x, default=x, minimum=min(left, right), maximum=max(left, right)),
        bounded_int(y, default=y, minimum=min(top, bottom), maximum=max(top, bottom)),
    )


def add_friend_region_for_point(x: int, y: int, image_size: tuple[int, int]) -> str:
    width, height = image_size
    split_x = session_split_x(width)
    nav_right = max(64, min(92, int(width * 0.075)))
    search_bottom = max(112, min(148, int(height * 0.16)))
    header_bottom = chat_header_cutoff_y(height) + max(32, int(height * 0.045))
    input_left, input_top, input_right, input_bottom = input_text_region_bounds({"width": width, "height": height})
    if point_in_bounds(x, y, [input_left, input_top, input_right, input_bottom]):
        return "input_area"
    if x <= nav_right:
        return "left_nav"
    if x < split_x:
        if y <= search_bottom:
            return "sidebar_search"
        return "session_list"
    if y <= header_bottom:
        return "main_header"
    if y >= input_top:
        return "right_bottom"
    return "main_content"


def add_friend_region_for_item(item: dict[str, Any], image_size: tuple[int, int]) -> str:
    center_x, center_y = add_friend_item_center(item)
    return add_friend_region_for_point(center_x, center_y, image_size)


def add_friend_windows_1080p_reference_plus_button_point_for_geometry(geometry: dict[str, Any]) -> tuple[int, int]:
    """Windows 1920x1080-oriented plus-entry reference kept from the incoming PR.

    On Windows WeChat this can land in the right conversation pane because the
    sidebar split and search-row layout differ. Keep it for comparison only.
    """
    return windows_1080p_reference_plus_point(
        geometry,
        split_x_fn=session_split_x,
        search_box_point_fn=search_box_point_for_geometry,
    )


def add_friend_windows_plus_button_point_for_geometry(geometry: dict[str, Any]) -> tuple[int, int]:
    """Windows WeChat plus-entry point beside the sidebar search box."""
    return windows_plus_point(
        geometry,
        split_x_fn=session_split_x,
        search_box_point_fn=search_box_point_for_geometry,
    )


def add_friend_plus_button_point_for_geometry(geometry: dict[str, Any]) -> tuple[int, int]:
    return add_friend_windows_plus_button_point_for_geometry(geometry)


def add_friend_plus_entry_safe_bounds(image_size: tuple[int, int]) -> list[int]:
    from apps.wechat_ai_customer_service.adapters.add_friend_layout import plus_entry_safe_bounds

    return plus_entry_safe_bounds(image_size, split_x_fn=session_split_x)


def find_sidebar_search_anchor_item(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> dict[str, Any] | None:
    from apps.wechat_ai_customer_service.adapters.add_friend_layout import find_sidebar_search_anchor_item as layout_find_anchor

    return layout_find_anchor(ocr_items, image_size, split_x_fn=session_split_x)


def add_friend_plus_entry_target(
    geometry: dict[str, Any],
    image_size: tuple[int, int],
    ocr_items: list[dict[str, Any]] | None = None,
    *,
    route_kind: str = "windows",
) -> dict[str, Any]:
    return layout_plus_entry_target(
        geometry,
        image_size,
        ocr_items or [],
        route_kind=route_kind,
        split_x_fn=session_split_x,
        search_box_point_fn=search_box_point_for_geometry,
        region_for_point_fn=add_friend_region_for_point,
    )


def normalize_point_for_add_friend_target(point: Any) -> list[int]:
    if isinstance(point, (list, tuple)) and len(point) >= 2:
        return [int(point[0] or 0), int(point[1] or 0)]
    return [0, 0]


def add_friend_text_has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return mapped_ocr_text_has_any(text, tokens)


def add_friend_server_report_payload(
    *,
    task_status: str | None = None,
    result_code: str | None = None,
    error_code: str | None = None,
    current_step: str | None = None,
) -> dict[str, str]:
    return mapped_add_friend_server_report_payload(
        task_status=task_status,
        result_code=result_code,
        error_code=error_code,
        current_step=current_step,
    )


def add_friend_completed_result(
    *,
    state: str,
    result_code: str,
    current_step: str = "task_completed",
    **extra: Any,
) -> dict[str, Any]:
    return mapped_add_friend_completed_result(
        state=state,
        result_code=result_code,
        current_step=current_step,
        **extra,
    )


def add_friend_failed_result(
    *,
    state: str,
    error_code: str,
    current_step: str,
    **extra: Any,
) -> dict[str, Any]:
    return mapped_add_friend_failed_result(
        state=state,
        error_code=error_code,
        current_step=current_step,
        **extra,
    )


def add_friend_entry_click_validation_failure_payload(
    *,
    phone: str,
    wechat: str,
    verify_message: str,
    remark_name: str,
    remark_code: str,
    artifact_dir: str | None = None,
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation = validate_add_friend_entry_click_contract(
        phone=phone,
        wechat=wechat,
        verify_message=verify_message,
        remark_name=remark_name,
        remark_code=remark_code,
    )
    flow = AddFriendFlowContext(
        project_root=PROJECT_ROOT,
        route=ADD_FRIEND_MAIN_ROUTE,
        artifact_dir=artifact_dir,
    )
    flow.add_event(
        step_id="payload_validation",
        title="字段契约校验",
        status="failed",
        state_before="task_received",
        state_after="task_payload_invalid",
        result={
            "ok": False,
            "task_status": "failed",
            "error_code": ERROR_TASK_PAYLOAD_INVALID,
            "verify_message": validation.get("verify_message"),
            "remark_name": validation.get("remark_name"),
            "remark_code": validation.get("remark_code"),
            "remark_code_valid": validation.get("remark_code_valid"),
            "validation_errors": validation.get("validation_errors") or [],
            "legacy_remark_fallback": False,
            "wechat_ui_action_attempted": False,
        },
    )
    payload = add_friend_task_payload_invalid(
        phone=phone,
        wechat=wechat,
        validation=validation,
        plan_path=str(flow.plan_path),
        probe=probe,
    )
    return flow.finalize_payload(payload, report_writer=write_add_friend_entry_click_review)


def find_add_friend_action_item(
    ocr_items: list[dict[str, Any]],
    tokens: tuple[str, ...],
    image_size: tuple[int, int],
    *,
    min_y_ratio: float = 0.0,
    max_y_ratio: float = 1.0,
) -> dict[str, Any] | None:
    width, height = image_size
    min_y = max(0, int(height * min_y_ratio))
    max_y = min(height, int(height * max_y_ratio))
    candidates: list[dict[str, Any]] = []
    for item in ocr_items:
        text = add_friend_item_text(item)
        if not text:
            continue
        matched = False
        for token in tokens:
            compact_token = add_friend_ocr_compact(token)
            if not compact_token:
                continue
            if compact_token == "添加朋友":
                matched = text == compact_token
            else:
                matched = compact_token in text
            if matched:
                break
        if not matched:
            continue
        center_x, center_y = add_friend_item_center(item)
        if center_y < min_y or center_y > max_y:
            continue
        if center_x < 0 or center_x > width:
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (float(item.get("confidence") or 0.0), float(item.get("right") or 0.0) - float(item.get("left") or 0.0)))


def find_add_friend_search_result_item(
    ocr_items: list[dict[str, Any]],
    query: str,
    image_size: tuple[int, int],
) -> dict[str, Any] | None:
    clean_query = re.sub(r"\D+", "", str(query or "")) or add_friend_ocr_compact(query)
    if not clean_query:
        return None
    width, height = image_size
    top_limit = int(height * 0.10)
    right_limit = max(260, int(width * 0.72))
    candidates: list[dict[str, Any]] = []
    for item in ocr_items:
        text = add_friend_item_text(item)
        if not text:
            continue
        center_x, center_y = add_friend_item_center(item)
        if center_y < top_limit or center_x > right_limit:
            continue
        digits = re.sub(r"\D+", "", text)
        if clean_query and (clean_query in digits or clean_query in text):
            candidates.append(item)
            continue
        if "网络查找" in text and any(token in text for token in ("手机", "qq", "微信")):
            candidates.append(item)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (abs(float(item.get("center_y") or 0.0) - height * 0.30), float(item.get("left") or 0.0)))


def classify_add_friend_ocr_surface(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> dict[str, Any]:
    text = add_friend_surface_text(ocr_items)
    phone_not_found_tokens = (
        "用户不存在",
        "该用户不存在",
        "账号不存在",
        "手机号不存在",
        "查无此人",
        "没有找到",
        "未找到相关结果",
    )
    if add_friend_text_has_any(text, phone_not_found_tokens):
        return {"state": "phone_not_found", "result_code": "", "error_code": ERROR_PHONE_NOT_FOUND}
    restricted_tokens = ("操作频繁", "账号异常", "账号安全", "被限制", "限制使用")
    if add_friend_text_has_any(text, restricted_tokens):
        return {"state": "account_restricted", "result_code": "", "error_code": ERROR_ACCOUNT_RESTRICTED}
    if find_add_friend_action_item(ocr_items, ("添加到通讯录", "添加至通讯录", "添加朋友"), image_size):
        return {"state": "add_contact_entry", "result_code": "", "error_code": ""}
    if find_add_friend_action_item(ocr_items, ("发送",), image_size, min_y_ratio=0.35):
        if add_friend_text_has_any(text, ("朋友验证", "发送添加朋友申请", "申请添加朋友", "备注名", "标签")):
            return {"state": "invite_form", "result_code": "", "error_code": ""}
    if add_friend_text_has_any(text, ("发消息", "音视频通话", "视频号")) and not add_friend_text_has_any(text, ("添加到通讯录", "添加朋友")):
        return {"state": "already_friend", "result_code": RESULT_ALREADY_FRIEND, "error_code": ""}
    if find_add_friend_search_result_item(ocr_items, "", image_size):
        return {"state": "search_results", "result_code": "", "error_code": ""}
    return {"state": "unknown", "result_code": "", "error_code": ""}


def classify_add_friend_after_confirm_surface(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    confirm_ok: bool,
) -> dict[str, Any]:
    text = add_friend_surface_text(ocr_items)
    invite_surface = add_friend_invite_form_surface_detected(ocr_items)
    return add_friend_after_confirm_payload(
        confirm_ok=confirm_ok,
        surface_text=text,
        invite_form_detected=bool(invite_surface.get("detected")),
    )


def add_friend_item_snapshot(item: dict[str, Any] | None, image_size: tuple[int, int]) -> dict[str, Any] | None:
    if item is None:
        return None
    left = int(float(item.get("left") or 0))
    top = int(float(item.get("top") or 0))
    right = int(float(item.get("right") or 0))
    bottom = int(float(item.get("bottom") or 0))
    center_x, center_y = add_friend_item_center(item)
    return {
        "text": str(item.get("text") or ""),
        "confidence": float(item.get("confidence") or 0.0),
        "bbox": [left, top, right, bottom],
        "center": [center_x, center_y],
        "region": add_friend_region_for_item(item, image_size),
    }


def add_friend_ocr_snapshots(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for index, item in enumerate(ocr_items, start=1):
        snapshot = add_friend_item_snapshot(item, image_size)
        if snapshot is None:
            continue
        snapshot["index"] = index
        snapshots.append(snapshot)
    return snapshots


def draw_add_friend_screen_annotation(
    screenshot: Image.Image,
    *,
    ocr_items: list[dict[str, Any]],
    targets: list[dict[str, Any]],
    output_path: Path,
    window_rect: list[int] | None = None,
) -> str:
    image = screenshot.convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    width, height = image.size
    if window_rect and len(window_rect) >= 4:
        left, top, right, bottom = [int(value) for value in window_rect[:4]]
        draw.rectangle([left, top, right, bottom], outline="#2563eb", width=4)
        draw.rectangle([left + 2, top + 2, min(right - 2, left + 170), min(bottom - 2, top + 22)], fill="#2563eb")
        draw.text((left + 6, top + 6), "wechat_window", fill="white", font=font)
    for index, item in enumerate(ocr_items, start=1):
        left = int(float(item.get("left") or 0))
        top = int(float(item.get("top") or 0))
        right = int(float(item.get("right") or 0))
        bottom = int(float(item.get("bottom") or 0))
        if right < 0 or bottom < 0 or left > width or top > height:
            continue
        draw.rectangle([left, top, right, bottom], outline="#f97316", width=2)
        label = f"{index}:ocr"
        label_y = max(0, top - 16)
        draw.rectangle([left, label_y, min(width - 1, left + max(42, len(label) * 7)), label_y + 14], fill="#f97316")
        draw.text((left + 2, label_y + 2), label, fill="white", font=font)
    for index, target in enumerate(targets, start=1):
        bounds = target.get("click_bounds")
        if isinstance(bounds, list) and len(bounds) >= 4:
            left, top, right, bottom = [int(value) for value in bounds[:4]]
            draw.rectangle([left, top, right, bottom], outline="#22c55e", width=2)
        x = int(target.get("annotation_x", target.get("x", target.get("screen_x") or 0)) or 0)
        y = int(target.get("annotation_y", target.get("y", target.get("screen_y") or 0)) or 0)
        label = f"T{index}:{target.get('name')}"
        draw.line([x - 16, y, x + 16, y], fill="#ef4444", width=4)
        draw.line([x, y - 16, x, y + 16], fill="#ef4444", width=4)
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline="#ef4444", width=3)
        text_x = min(max(0, x + 12), max(0, width - 220))
        text_y = min(max(0, y + 12), max(0, height - 18))
        draw.rectangle([text_x, text_y, min(width - 1, text_x + max(110, len(label) * 7)), text_y + 16], fill="#ef4444")
        draw.text((text_x + 3, text_y + 3), label, fill="white", font=font)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return str(output_path)


def add_friend_popup_menu_bounds(
    image_size: tuple[int, int],
    *,
    plus_screen_x: int,
    plus_screen_y: int,
) -> list[int]:
    width, height = image_size
    left = max(0, int(plus_screen_x) - 86)
    top = max(0, int(plus_screen_y) + 24)
    right = min(width, int(plus_screen_x) + 132)
    bottom = min(height, int(plus_screen_y) + 206)
    return [left, top, right, bottom]


def run_ocr_on_screen_region(image: Image.Image, bounds: list[int]) -> list[dict[str, Any]]:
    left, top, right, bottom = [int(value) for value in bounds[:4]]
    width, height = image.size
    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    cropped = image.crop((left, top, right, bottom))
    items = run_ocr(cropped)
    for item in items:
        for key in ("left", "right", "center_x"):
            item[key] = float(item.get(key) or 0.0) + left
        for key in ("top", "bottom", "center_y"):
            item[key] = float(item.get(key) or 0.0) + top
        box = item.get("box")
        if isinstance(box, list):
            item["box"] = [[float(point[0]) + left, float(point[1]) + top] for point in box if isinstance(point, (list, tuple)) and len(point) >= 2]
    return items


def add_friend_menu_text_matches(text: str, tokens: tuple[str, ...]) -> bool:
    compact = add_friend_ocr_compact(text)
    if not compact:
        return False
    for token in tokens:
        compact_token = add_friend_ocr_compact(token)
        if compact_token and compact_token in compact:
            return True
    if ("添加朋友" in tokens or "添加好友" in tokens) and "添加" in compact and ("朋友" in compact or "好友" in compact):
        return True
    if "发起群聊" in tokens and ("群聊" in compact or ("发起" in compact and "群" in compact)):
        return True
    if "新建笔记" in tokens and ("笔记" in compact or ("新建" in compact and "笔" in compact)):
        return True
    if "扫一扫" in tokens and "扫" in compact:
        return True
    return False


def find_add_friend_menu_item(
    ocr_items: list[dict[str, Any]],
    tokens: tuple[str, ...],
    image_size: tuple[int, int],
    *,
    popup_bounds: list[int],
) -> dict[str, Any] | None:
    left, top, right, bottom = [int(value) for value in popup_bounds[:4]]
    candidates: list[dict[str, Any]] = []
    for item in ocr_items:
        center_x, center_y = add_friend_item_center(item)
        if not point_in_bounds(center_x, center_y, [left, top, right, bottom]):
            continue
        if not add_friend_menu_text_matches(str(item.get("text") or ""), tokens):
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda item: (float(item.get("confidence") or 0.0), float(item.get("right") or 0.0) - float(item.get("left") or 0.0)))


def add_friend_expected_menu_target(
    *,
    name: str,
    label: str,
    plus_screen_x: int,
    plus_screen_y: int,
    y_offset: int,
    image_size: tuple[int, int],
) -> dict[str, Any]:
    width, height = image_size
    target_x = bounded_int(plus_screen_x + 36, default=plus_screen_x + 36, minimum=0, maximum=max(0, width - 1))
    target_y = bounded_int(plus_screen_y + y_offset, default=plus_screen_y + y_offset, minimum=0, maximum=max(0, height - 1))
    bounds = add_friend_expected_menu_click_bounds(
        image_size=image_size,
        plus_screen_x=plus_screen_x,
        plus_screen_y=plus_screen_y,
        y_offset=y_offset,
    )
    target = geometry_fallback_locator(
        name=name,
        label=label,
        region=add_friend_region_for_point(target_x, target_y, image_size),
        bounds=bounds,
        point=[target_x, target_y],
        selected_reason="expected popup menu row from plus entry geometry",
        fallback_reason="ocr_menu_item_not_detected",
        risk="diagnostic_expected_popup_menu_item_center",
        source="expected_popup_geometry",
        metadata={"image_size": [width, height], "plus_point": [plus_screen_x, plus_screen_y], "y_offset": y_offset},
    )
    target["screen_x"] = target_x
    target["screen_y"] = target_y
    target["item"] = None
    return target


def add_friend_popup_menu_item_click_bounds(item: dict[str, Any], popup_bounds: list[int]) -> list[int]:
    left, top, right, bottom = [int(value) for value in popup_bounds[:4]]
    center_x, center_y = add_friend_item_center(item)
    item_left = int(float(item.get("left") or center_x))
    item_right = int(float(item.get("right") or center_x))
    row_top = max(top + 4, center_y - 22)
    row_bottom = min(bottom - 4, center_y + 22)
    click_left = max(left + 10, min(item_left - 30, right - 32))
    click_right = min(right - 10, max(item_right + 30, click_left + 44))
    if click_right <= click_left:
        click_left = left + 10
        click_right = right - 10
    if row_bottom <= row_top:
        row_top = max(top + 4, center_y - 18)
        row_bottom = min(bottom - 4, center_y + 18)
    return [click_left, row_top, click_right, row_bottom]


def add_friend_expected_menu_click_bounds(
    *,
    image_size: tuple[int, int],
    plus_screen_x: int,
    plus_screen_y: int,
    y_offset: int,
) -> list[int]:
    popup_bounds = add_friend_popup_menu_bounds(image_size, plus_screen_x=plus_screen_x, plus_screen_y=plus_screen_y)
    left, top, right, bottom = [int(value) for value in popup_bounds[:4]]
    center_y = bounded_int(plus_screen_y + y_offset, default=plus_screen_y + y_offset, minimum=top + 8, maximum=bottom - 8)
    return [left + 10, max(top + 4, center_y - 22), right - 10, min(bottom - 4, center_y + 22)]


def add_friend_menu_candidate_targets(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    plus_screen_x: int | None = None,
    plus_screen_y: int | None = None,
    include_expected: bool = True,
) -> list[dict[str, Any]]:
    candidates = [
        ("add_friend_menu_entry", "Menu candidate: 添加朋友", ("添加朋友", "添加好友")),
        ("start_group_chat_menu_entry", "Menu candidate: 发起群聊", ("发起群聊",)),
        ("scan_menu_entry", "Menu candidate: 扫一扫", ("扫一扫",)),
        ("new_note_menu_entry", "Menu candidate: 新建笔记", ("新建笔记",)),
    ]
    popup_bounds = (
        add_friend_popup_menu_bounds(image_size, plus_screen_x=int(plus_screen_x), plus_screen_y=int(plus_screen_y))
        if plus_screen_x is not None and plus_screen_y is not None
        else [0, 0, image_size[0], image_size[1]]
    )
    targets: list[dict[str, Any]] = []
    for name, label, tokens in candidates:
        item = find_add_friend_menu_item(ocr_items, tokens, image_size, popup_bounds=popup_bounds)
        if item is None:
            continue
        center_x, center_y = add_friend_item_center(item)
        click_bounds = add_friend_popup_menu_item_click_bounds(item, popup_bounds)
        click_x, click_y = clamp_point_to_bounds(center_x, center_y, click_bounds)
        target = ocr_item_locator(
            name=name,
            label=label,
            region=add_friend_region_for_point(click_x, click_y, image_size),
            bounds=click_bounds,
            point=[click_x, click_y],
            item=item,
            selected_reason="matched popup menu OCR text",
            risk="diagnostic_only_no_click_menu_item",
            source="ocr_popup_menu_item",
            metadata={"image_size": [image_size[0], image_size[1]], "tokens": list(tokens)},
        )
        target["raw_x"] = center_x
        target["raw_y"] = center_y
        target["item"] = add_friend_item_snapshot(item, image_size)
        targets.append(target)
    if include_expected and plus_screen_x is not None and plus_screen_y is not None:
        existing = {str(target.get("name") or "") for target in targets}
        expected_offsets = [
            ("start_group_chat_menu_entry", "Expected popup center: 发起群聊", 60),
            ("add_friend_menu_entry", "Expected popup center: 添加朋友", 104),
            ("new_note_menu_entry", "Expected popup center: 新建笔记", 148),
        ]
        for name, label, y_offset in expected_offsets:
            if name in existing:
                continue
            expected = add_friend_expected_menu_target(
                name=name,
                label=label,
                plus_screen_x=int(plus_screen_x),
                plus_screen_y=int(plus_screen_y),
                y_offset=y_offset,
                image_size=image_size,
            )
            targets.append(expected)
    return targets


def plus_entry_popup_menu_detected(ocr_items: list[dict[str, Any]], targets: list[dict[str, Any]]) -> dict[str, Any]:
    target_names = {
        str(item.get("name") or "")
        for item in targets
        if isinstance(item, dict) and str(item.get("source") or "") != "expected_popup_geometry"
    }
    menu_target_names = {
        "add_friend_menu_entry",
        "start_group_chat_menu_entry",
        "scan_menu_entry",
        "new_note_menu_entry",
    }
    matched_target_names = sorted(name for name in target_names if name in menu_target_names)
    if matched_target_names:
        return {
            "detected": True,
            "reason": "plus_entry_popup_menu_item_detected",
            "matched_target_names": matched_target_names,
            "target_names": sorted(target_names),
        }
    surface = add_friend_surface_text(ocr_items)
    menu_tokens = ("发起群聊", "添加朋友", "添加好友", "新建笔记", "扫一扫")
    matched = [token for token in menu_tokens if add_friend_ocr_compact(token) in surface]
    return {
        "detected": len(matched) >= 1,
        "reason": "plus_entry_popup_menu_text_detected" if len(matched) >= 1 else "menu_not_detected",
        "matched_tokens": matched,
        "target_names": sorted(target_names),
    }


def add_friend_target_review_text(targets: list[dict[str, Any]]) -> str:
    if not targets:
        return "无目标标注"
    parts: list[str] = []
    for target in targets:
        name = str(target.get("name") or "")
        label = str(target.get("label") or name)
        source = str(target.get("source") or "manual")
        x = target.get("screen_x", target.get("x"))
        y = target.get("screen_y", target.get("y"))
        parts.append(f"{name} ({label}) @ {x},{y}, source={source}")
    return "\n".join(parts)


def add_friend_target_by_name(targets: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for target in targets:
        if isinstance(target, dict) and str(target.get("name") or "") == name:
            return target
    return None


def add_friend_target_screen_point(target: dict[str, Any]) -> tuple[int, int]:
    return int(target.get("click_screen_x", target.get("screen_x", target.get("x") or 0)) or 0), int(target.get("click_screen_y", target.get("screen_y", target.get("y") or 0)) or 0)


def add_click_screen_origin_to_targets(targets: list[dict[str, Any]], *, origin_x: int, origin_y: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for target in targets:
        copied = dict(target)
        copied["click_screen_x"] = int(origin_x) + int(copied.get("x") or 0)
        copied["click_screen_y"] = int(origin_y) + int(copied.get("y") or 0)
        bounds = copied.get("click_bounds")
        if isinstance(bounds, list) and len(bounds) >= 4:
            copied["click_screen_bounds"] = [
                int(origin_x) + int(bounds[0]),
                int(origin_y) + int(bounds[1]),
                int(origin_x) + int(bounds[2]),
                int(origin_y) + int(bounds[3]),
            ]
        result.append(copied)
    return result


def add_friend_page_search_region(image_size: tuple[int, int]) -> list[int]:
    width, height = image_size
    if width <= 560:
        return [20, 54, max(21, width - 16), min(height - 16, 162)]
    split_x = session_split_x(width)
    left = max(split_x + 24, int(width * 0.38))
    top = max(88, int(height * 0.10))
    right = min(width - 24, max(left + 320, int(width * 0.86)))
    bottom = min(height - 40, max(top + 190, int(height * 0.38)))
    return [left, top, right, bottom]


def add_friend_search_result_region(image_size: tuple[int, int]) -> list[int]:
    width, height = image_size
    if width <= 560:
        return [20, 118, max(21, width - 16), max(160, height - 24)]
    split_x = session_split_x(width)
    left = max(split_x + 24, int(width * 0.36))
    top = max(150, int(height * 0.18))
    right = min(width - 24, max(left + 360, int(width * 0.90)))
    bottom = min(height - 36, max(top + 320, int(height * 0.72)))
    return [left, top, right, bottom]


def add_friend_phone_not_found_detected(ocr_items: list[dict[str, Any]]) -> dict[str, Any]:
    text = add_friend_surface_text(ocr_items)
    tokens = (
        "无法找到该用户",
        "请检查你填写的账号是否正确",
        "用户不存在",
        "该用户不存在",
        "账号不存在",
        "手机号不存在",
        "查无此人",
        "没有找到",
        "未找到相关结果",
    )
    matched = [token for token in tokens if add_friend_ocr_compact(token) in text]
    return {
        "detected": bool(matched),
        "matched_tokens": matched,
        "ocr_text": text,
    }


def add_friend_search_result_add_contact_target(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> dict[str, Any] | None:
    item = find_add_friend_action_item(
        ocr_items,
        ("添加到通讯录", "添加至通讯录", "添加通讯录", "添加朋友"),
        image_size,
        min_y_ratio=0.15,
        max_y_ratio=0.95,
    )
    if item is None:
        return None
    center_x, center_y = add_friend_item_center(item)
    left = int(float(item.get("left") or center_x))
    top = int(float(item.get("top") or center_y))
    right = int(float(item.get("right") or center_x))
    bottom = int(float(item.get("bottom") or center_y))
    width, height = image_size
    bounds = [
        max(10, left - 42),
        max(10, top - 18),
        min(width - 10, right + 42),
        min(height - 10, bottom + 18),
    ]
    click_x, click_y = clamp_point_to_bounds(center_x, center_y, bounds)
    target = ocr_item_locator(
        name="add_contact_entry_button",
        label="Search result: 添加到通讯录",
        region=add_friend_region_for_point(click_x, click_y, image_size),
        bounds=bounds,
        point=[click_x, click_y],
        item=item,
        selected_reason="matched add-contact OCR text in search result",
        risk="click_add_contact_entry_then_stop",
        source="ocr_search_result_add_contact",
        metadata={"image_size": [image_size[0], image_size[1]]},
    )
    target["raw_x"] = center_x
    target["raw_y"] = center_y
    target["item"] = add_friend_item_snapshot(item, image_size)
    return target


def click_add_contact_entry_from_search_result(
    hwnd: int,
    output_dir: Path,
    *,
    result_shot: Image.Image,
    result_path: str,
    result_items: list[dict[str, Any]],
    query: str,
    verify_message: str = "",
    remark_name: str = "",
    remark_code: str = "",
) -> dict[str, Any]:
    not_found = add_friend_phone_not_found_detected(result_items)
    if not_found.get("detected"):
        annotated_path = output_dir / "add_friend_search_result_phone_not_found_annotated.png"
        annotated = draw_add_friend_screen_annotation(
            result_shot,
            ocr_items=result_items,
            targets=[],
            output_path=annotated_path,
            window_rect=None,
        )
        payload = add_friend_phone_not_found_payload(
            query=query,
            not_found=not_found,
            screenshot_path=result_path,
            annotated_path=annotated,
            ocr_items=add_friend_ocr_snapshots(result_items, result_shot.size),
        )
        return payload

    target = add_friend_search_result_add_contact_target(result_items, result_shot.size)
    annotated_before_path = output_dir / "add_friend_search_result_add_contact_before_click_annotated.png"
    annotated_before = draw_add_friend_screen_annotation(
        result_shot,
        ocr_items=result_items,
        targets=[target] if target else [],
        output_path=annotated_before_path,
        window_rect=None,
    )
    if target is None:
        surface = classify_add_friend_ocr_surface(result_items, result_shot.size)
        if surface.get("result_code") == RESULT_ALREADY_FRIEND:
            return add_friend_completed_result(
                state="already_friend",
                result_code=RESULT_ALREADY_FRIEND,
                current_step="searching_contact",
                screenshot_path=result_path,
                annotated_path=annotated_before,
                targets=[],
                ocr_items=add_friend_ocr_snapshots(result_items, result_shot.size),
                result_basis="search_result_profile_has_message_actions",
            )
        return add_friend_add_contact_entry_not_found_payload(
            phone=query,
            screenshot_path=result_path,
            annotated_path=annotated_before,
            targets=[],
            ocr_items=add_friend_ocr_snapshots(result_items, result_shot.size),
        )

    timings: list[dict[str, Any]] = []
    pause_seconds = add_friend_paced_pause("critical_click", reason="before_add_contact_entry_click")
    timings.append({"name": "before_add_contact_entry_click_pause", "seconds": round(pause_seconds, 3)})
    click_started_at = time.perf_counter()
    click_result = human_window_image_click_in_bounds(
        hwnd,
        int(target.get("x") or 0),
        int(target.get("y") or 0),
        bounds=list(target.get("click_bounds") or []),
        action_name="add_contact_entry_click",
    )
    timings.append({"name": "add_contact_entry_click", "seconds": round(time.perf_counter() - click_started_at, 3), "result": click_result})
    pause_seconds = add_friend_paced_pause("verify", reason="after_add_contact_entry_click_before_capture")
    timings.append({"name": "after_add_contact_entry_click_before_capture_pause", "seconds": round(pause_seconds, 3)})
    invite_probe = wait_for_add_friend_invite_form_window(exclude_hwnds={int(hwnd or 0)}, output_dir=output_dir)
    invite_hwnd = int(invite_probe.get("hwnd") or 0) if invite_probe.get("ok") else 0
    evidence_hwnd = invite_hwnd or hwnd
    after_shot, after_path = capture_wechat_window_visible_screen(evidence_hwnd, artifact_dir=str(output_dir), label="add_contact_entry_after_click_window")
    after_items = run_ocr_on_screen_region(after_shot, [0, 0, after_shot.size[0], after_shot.size[1]])
    after_annotated_path = output_dir / "add_contact_entry_after_click_window_annotated.png"
    after_targets = list(add_friend_invite_form_targets(after_shot.size, after_items).values()) if invite_hwnd else []
    after_annotated = draw_add_friend_screen_annotation(
        after_shot,
        ocr_items=after_items,
        targets=after_targets,
        output_path=after_annotated_path,
        window_rect=None,
    )
    if not invite_hwnd:
        return add_friend_invite_form_window_not_found_payload(
            phone=query,
            before={
                "screenshot_path": result_path,
                "annotated_path": annotated_before,
                "targets": [target],
                "ocr_items": add_friend_ocr_snapshots(result_items, result_shot.size),
            },
            click=click_result,
            after={
                "screenshot_path": after_path,
                "annotated_path": after_annotated,
                "ocr_items": add_friend_ocr_snapshots(after_items, after_shot.size),
            },
            invite_form_probe=invite_probe,
            timings=timings,
        )
    invite_result = fill_add_friend_invite_form_and_confirm(
        invite_hwnd,
        output_dir,
        verify_message=verify_message,
        remark_name=remark_name,
        remark_code=remark_code,
    )
    invite_timings = list(invite_result.get("timings") or []) if isinstance(invite_result, dict) else []
    timings.extend(invite_timings)
    return {
        "ok": bool(click_result.get("ok")) and bool(invite_result.get("ok")),
        "state": str(invite_result.get("state") or "add_contact_entry_clicked"),
        "query": query,
        "task_status": str(invite_result.get("task_status") or "running"),
        "result_code": str(invite_result.get("result_code") or ""),
        "error_code": str(invite_result.get("error_code") or ""),
        "current_step": str(invite_result.get("current_step") or "invite_confirm_clicked"),
        "server_report_payload": invite_result.get("server_report_payload"),
        "before": {
            "screenshot_path": result_path,
            "annotated_path": annotated_before,
            "targets": [target],
            "ocr_items": add_friend_ocr_snapshots(result_items, result_shot.size),
        },
        "click": click_result,
        "after": {
            "screenshot_path": after_path,
            "annotated_path": after_annotated,
            "ocr_items": add_friend_ocr_snapshots(after_items, after_shot.size),
            "targets": after_targets,
        },
        "invite_form_probe": invite_probe,
        "invite_form": invite_result,
        "timings": timings,
    }


def add_friend_invite_form_targets(
    image_size: tuple[int, int],
    ocr_items: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    return semantic_invite_form_targets(
        image_size,
        ocr_items or [],
        region_for_point_fn=add_friend_region_for_point,
    )


def paste_invite_form_text(
    hwnd: int,
    target: dict[str, Any],
    text: str,
    *,
    action_name: str,
) -> dict[str, Any]:
    clean = str(text or "")
    if not clean:
        return {
            "ok": True,
            "skipped": True,
            "reason": "empty_text",
            "action": make_action_result(
                action_id=action_name,
                action_type=ACTION_COMPOSITE_INPUT,
                status="skipped",
                method="click_ctrl_a_backspace_clipboard_paste",
                target=target,
                text=clean,
                metadata={"reason": "empty_text"},
            ),
        }
    bounds = list(target.get("click_bounds") or [])
    if len(bounds) < 4:
        return {
            "ok": False,
            "reason": "target_missing_click_bounds",
            "target": target,
            "action": make_action_result(
                action_id=action_name,
                action_type=ACTION_COMPOSITE_INPUT,
                status="failed",
                method="click_ctrl_a_backspace_clipboard_paste",
                target=target,
                text=clean,
                error="target_missing_click_bounds",
            ),
        }
    click_result = human_window_image_click_in_bounds(
        hwnd,
        int(target.get("x") or 0),
        int(target.get("y") or 0),
        bounds=bounds,
        action_name=f"{action_name}_click",
    )
    if not click_result.get("ok"):
        return {
            "ok": False,
            "reason": "field_click_failed",
            "method": "click_ctrl_a_backspace_clipboard_paste",
            "text_length": len(clean),
            "click": click_result,
            "target": target,
            "action": make_action_result(
                action_id=action_name,
                action_type=ACTION_COMPOSITE_INPUT,
                status="failed",
                method="click_ctrl_a_backspace_clipboard_paste",
                target=target,
                text=clean,
                error=str(click_result.get("reason") or click_result.get("error") or "field_click_failed"),
                result={"click": click_result, "aborted_before_keyboard_input": True},
            ),
        }
    add_friend_paced_pause("input", reason=f"after_{action_name}_click_before_select_all")
    hotkey(win32con.VK_CONTROL, ord("A"))
    add_friend_paced_pause("input", reason=f"after_{action_name}_select_all_before_backspace")
    key_press(win32con.VK_BACK)
    add_friend_paced_pause("input", reason=f"after_{action_name}_clear_before_clipboard")
    clipboard_copy(clean)
    add_friend_paced_pause("input", reason=f"after_{action_name}_clipboard_copy_before_paste")
    hotkey(win32con.VK_CONTROL, ord("V"))
    add_friend_paced_pause("input", reason=f"after_{action_name}_paste")
    return {
        "ok": bool(click_result.get("ok")),
        "method": "click_ctrl_a_backspace_clipboard_paste",
        "text_length": len(clean),
        "click": click_result,
        "action": make_action_result(
            action_id=action_name,
            action_type=ACTION_COMPOSITE_INPUT,
            status="completed" if bool(click_result.get("ok")) else "failed",
            method="click_ctrl_a_backspace_clipboard_paste",
            target=target,
            text=clean,
            result={"click": click_result},
        ),
    }


def fill_add_friend_invite_form_and_confirm(
    hwnd: int,
    output_dir: Path,
    *,
    verify_message: str,
    remark_name: str,
    remark_code: str,
) -> dict[str, Any]:
    clean_verify_message = str(verify_message or "").strip()
    clean_remark_name = str(remark_name or "").strip()
    clean_remark_code = str(remark_code or "").strip()
    remark_code_valid = bool(clean_remark_code and clean_remark_code in clean_remark_name)
    timings: list[dict[str, Any]] = []

    pause_seconds = add_friend_paced_pause("verify", reason="before_invite_form_capture")
    timings.append({"name": "before_invite_form_capture_pause", "seconds": round(pause_seconds, 3)})
    before_shot, before_path = capture_wechat_window_visible_screen(hwnd, artifact_dir=str(output_dir), label="add_friend_invite_form_before_fill_window")
    before_ocr_started_at = time.perf_counter()
    before_items = run_ocr_on_screen_region(before_shot, [0, 0, before_shot.size[0], before_shot.size[1]])
    timings.append({"name": "invite_form_before_fill_ocr", "seconds": round(time.perf_counter() - before_ocr_started_at, 3), "ocr_count": len(before_items)})
    before_targets_map = add_friend_invite_form_targets(before_shot.size, before_items)
    before_targets = list(before_targets_map.values())
    before_annotated_path = output_dir / "add_friend_invite_form_before_fill_window_annotated.png"
    before_annotated = draw_add_friend_screen_annotation(
        before_shot,
        ocr_items=before_items,
        targets=before_targets,
        output_path=before_annotated_path,
        window_rect=None,
    )

    greeting_started_at = time.perf_counter()
    greeting_result = paste_invite_form_text(
        hwnd,
        before_targets_map["invite_greeting_textarea"],
        clean_verify_message,
        action_name="invite_greeting",
    )
    timings.append({"name": "fill_invite_greeting_text", "seconds": round(time.perf_counter() - greeting_started_at, 3), "result": greeting_result})

    remark_started_at = time.perf_counter()
    remark_result = paste_invite_form_text(
        hwnd,
        before_targets_map["invite_remark_input"],
        clean_remark_name,
        action_name="invite_remark",
    )
    timings.append({"name": "fill_invite_remark_text", "seconds": round(time.perf_counter() - remark_started_at, 3), "result": remark_result})

    pause_seconds = add_friend_paced_pause("verify", reason="after_invite_form_fill_before_review_capture")
    timings.append({"name": "after_invite_form_fill_before_review_capture_pause", "seconds": round(pause_seconds, 3)})
    filled_shot, filled_path = capture_wechat_window_visible_screen(hwnd, artifact_dir=str(output_dir), label="add_friend_invite_form_filled_before_confirm_window")
    filled_ocr_started_at = time.perf_counter()
    filled_items = run_ocr_on_screen_region(filled_shot, [0, 0, filled_shot.size[0], filled_shot.size[1]])
    timings.append({"name": "invite_form_filled_ocr", "seconds": round(time.perf_counter() - filled_ocr_started_at, 3), "ocr_count": len(filled_items)})
    filled_targets_map = add_friend_invite_form_targets(filled_shot.size, filled_items)
    filled_targets = list(filled_targets_map.values())
    field_verification = invite_form_field_verification(
        verify_message=clean_verify_message,
        remark_name=clean_remark_name,
        remark_code=clean_remark_code,
        ocr_items=filled_items,
    )
    filled_annotated_path = output_dir / "add_friend_invite_form_filled_before_confirm_window_annotated.png"
    filled_annotated = draw_add_friend_screen_annotation(
        filled_shot,
        ocr_items=filled_items,
        targets=filled_targets,
        output_path=filled_annotated_path,
        window_rect=None,
    )

    if not field_verification.get("ok"):
        final_status = mapped_add_friend_failed_result(
            state="invite_field_verification_failed",
            error_code=ERROR_INVITE_FIELD_VERIFICATION_FAILED,
            current_step="invite_fields_review",
            field_verification=field_verification,
        )
        timings.append({"name": "invite_field_verification_gate", "seconds": 0.0, "result": field_verification})
        return {
            "ok": False,
            "state": str(final_status.get("state") or "invite_field_verification_failed"),
            "task_status": str(final_status.get("task_status") or "failed"),
            "result_code": str(final_status.get("result_code") or ""),
            "error_code": str(final_status.get("error_code") or ERROR_INVITE_FIELD_VERIFICATION_FAILED),
            "current_step": str(final_status.get("current_step") or "invite_fields_review"),
            "verify_message": clean_verify_message,
            "remark_name": clean_remark_name,
            "remark_code": clean_remark_code,
            "remark_code_valid": remark_code_valid,
            "legacy_remark_fallback": False,
            "validation_errors": [],
            "before": {
                "screenshot_path": before_path,
                "annotated_path": before_annotated,
                "targets": before_targets,
                "ocr_items": add_friend_ocr_snapshots(before_items, before_shot.size),
            },
            "filled": {
                "screenshot_path": filled_path,
                "annotated_path": filled_annotated,
                "targets": filled_targets,
                "ocr_items": add_friend_ocr_snapshots(filled_items, filled_shot.size),
                "field_verification": field_verification,
            },
            "after": {
                "screenshot_path": "",
                "annotated_path": "",
                "ocr_items": [],
                "final_status": final_status,
                "skipped": True,
                "reason": "field_verification_failed_before_confirm",
            },
            "greeting": greeting_result,
            "remark_fill": remark_result,
            "field_verification": field_verification,
            "confirm": {"ok": False, "skipped": True, "reason": "field_verification_failed_before_confirm"},
            "server_report_payload": final_status.get("server_report_payload")
            or {
                "task.status": "failed",
                "task.error_code": ERROR_INVITE_FIELD_VERIFICATION_FAILED,
                "task.current_step": "invite_fields_review",
            },
            "timings": timings,
        }

    pause_seconds = add_friend_paced_pause("critical_click", reason="before_invite_confirm_click")
    timings.append({"name": "before_invite_confirm_click_pause", "seconds": round(pause_seconds, 3)})
    confirm_started_at = time.perf_counter()
    confirm_target = filled_targets_map["invite_confirm_button"]
    confirm_result = human_window_image_click_in_bounds(
        hwnd,
        int(confirm_target.get("x") or 0),
        int(confirm_target.get("y") or 0),
        bounds=list(confirm_target.get("click_bounds") or []),
        action_name="invite_confirm_button_click",
    )
    timings.append({"name": "invite_confirm_button_click", "seconds": round(time.perf_counter() - confirm_started_at, 3), "result": confirm_result})
    pause_seconds = add_friend_paced_pause("verify", reason="after_invite_confirm_click_before_capture")
    timings.append({"name": "after_invite_confirm_click_before_capture_pause", "seconds": round(pause_seconds, 3)})
    after_shot, after_path = capture_wechat_window_visible_screen(hwnd, artifact_dir=str(output_dir), label="add_friend_invite_form_after_confirm_window")
    after_items = run_ocr_on_screen_region(after_shot, [0, 0, after_shot.size[0], after_shot.size[1]])
    final_status = classify_add_friend_after_confirm_surface(
        after_items,
        after_shot.size,
        confirm_ok=bool(confirm_result.get("ok")),
    )
    after_annotated_path = output_dir / "add_friend_invite_form_after_confirm_window_annotated.png"
    after_annotated = draw_add_friend_screen_annotation(
        after_shot,
        ocr_items=after_items,
        targets=[],
        output_path=after_annotated_path,
        window_rect=None,
    )

    return {
        "ok": bool(greeting_result.get("ok")) and bool(remark_result.get("ok")) and bool(confirm_result.get("ok")),
        "state": str(final_status.get("state") or "invite_confirm_clicked"),
        "task_status": str(final_status.get("task_status") or "running"),
        "result_code": str(final_status.get("result_code") or ""),
        "error_code": str(final_status.get("error_code") or ""),
        "current_step": str(final_status.get("current_step") or "invite_confirm_clicked"),
        "verify_message": clean_verify_message,
        "remark_name": clean_remark_name,
        "remark_code": clean_remark_code,
        "remark_code_valid": remark_code_valid,
        "legacy_remark_fallback": False,
        "validation_errors": [],
        "before": {
            "screenshot_path": before_path,
            "annotated_path": before_annotated,
            "targets": before_targets,
            "ocr_items": add_friend_ocr_snapshots(before_items, before_shot.size),
        },
        "filled": {
            "screenshot_path": filled_path,
            "annotated_path": filled_annotated,
            "targets": filled_targets,
            "ocr_items": add_friend_ocr_snapshots(filled_items, filled_shot.size),
            "field_verification": field_verification,
        },
        "after": {
            "screenshot_path": after_path,
            "annotated_path": after_annotated,
            "ocr_items": add_friend_ocr_snapshots(after_items, after_shot.size),
            "final_status": final_status,
        },
        "greeting": greeting_result,
        "remark_fill": remark_result,
        "field_verification": field_verification,
        "confirm": confirm_result,
        "server_report_payload": final_status.get("server_report_payload") or {"task.current_step": "invite_confirm_clicked"},
        "timings": timings,
    }


def find_add_friend_page_search_targets(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> dict[str, Any]:
    search_region = add_friend_page_search_region(image_size)
    small_add_friend_window = image_size[0] <= 560
    if small_add_friend_window:
        width, height = image_size
        y = bounded_int(96, default=96, minimum=70, maximum=max(72, min(height - 24, 126)))
        input_bounds = [32, 72, max(120, min(width - 126, 292)), 122]
        button_bounds = [max(input_bounds[2] + 4, width - 118), 72, max(input_bounds[2] + 44, width - 30), 122]
        input_x, input_y = clamp_point_to_bounds(
            bounded_int(int(width * 0.38), default=158, minimum=input_bounds[0] + 20, maximum=input_bounds[2] - 20),
            y,
            input_bounds,
        )
        button_x, button_y = clamp_point_to_bounds(
            int((button_bounds[0] + button_bounds[2]) / 2),
            y,
            button_bounds,
        )
        return {
            "search_region": search_region,
            "input": geometry_fallback_locator(
                name="add_friend_search_input",
                label="Add friend dialog search input fixed safe area",
                region=add_friend_region_for_point(input_x, input_y, image_size),
                bounds=input_bounds,
                point=[input_x, input_y],
                selected_reason="small add-friend dialog fixed search input safe area",
                fallback_reason="small_dialog_geometry_is_more_stable_than_ocr_placeholder",
                risk="type_query_here_fixed_dialog_input",
                source="fixed_small_add_friend_dialog_geometry",
                metadata={"image_size": [width, height]},
            ),
            "button": geometry_fallback_locator(
                name="add_friend_search_button",
                label="Add friend dialog search button fixed safe area",
                region=add_friend_region_for_point(button_x, button_y, image_size),
                bounds=button_bounds,
                point=[button_x, button_y],
                selected_reason="small add-friend dialog fixed search button safe area",
                fallback_reason="small_dialog_geometry_is_more_stable_than_ocr_button",
                risk="click_search_after_query_verified_fixed_dialog_button",
                source="fixed_small_add_friend_dialog_geometry",
                metadata={"image_size": [width, height]},
            ),
        }
    input_item = find_add_friend_menu_item(
        ocr_items,
        ("微信号/手机号", "微信号", "手机号", "QQ号", "搜索"),
        image_size,
        popup_bounds=search_region,
    )
    search_button = find_add_friend_menu_item(
        ocr_items,
        ("搜索",),
        image_size,
        popup_bounds=search_region,
    )
    split_x = session_split_x(image_size[0])
    fallback_input_x = max(split_x + 150, int(image_size[0] * 0.53))
    fallback_input_y = max(118, int(image_size[1] * 0.16))
    if input_item is not None:
        input_x, input_y = add_friend_item_center(input_item)
        input_x = max(split_x + 80, input_x)
        input_left = int(float(input_item.get("left") or input_x))
        input_top = int(float(input_item.get("top") or input_y))
        input_right = int(float(input_item.get("right") or input_x))
        input_bottom = int(float(input_item.get("bottom") or input_y))
        input_bounds = [
            max(split_x + 12, input_left - 48),
            max(search_region[1], input_top - 18),
            min(image_size[0] - 12, max(input_right + 160, input_x + 80)),
            min(search_region[3], input_bottom + 18),
        ]
        input_target = ocr_item_locator(
            name="add_friend_search_input",
            label="Add friend page search input",
            region=add_friend_region_for_point(input_x, input_y, image_size),
            bounds=input_bounds,
            point=[input_x, input_y],
            item=input_item,
            selected_reason="matched search input placeholder OCR text",
            risk="type_query_here",
            source="ocr_search_input_or_placeholder",
            metadata={"image_size": [image_size[0], image_size[1]], "search_region": search_region},
        )
        input_target["item"] = add_friend_item_snapshot(input_item, image_size)
    else:
        input_x, input_y = fallback_input_x, fallback_input_y
        input_bounds = [
            max(split_x + 48, input_x - 140),
            max(search_region[1], input_y - 24),
            min(image_size[0] - 80, input_x + 170),
            min(search_region[3], input_y + 24),
        ]
        input_target = geometry_fallback_locator(
            name="add_friend_search_input",
            label="Add friend page search input",
            region=add_friend_region_for_point(input_x, input_y, image_size),
            bounds=input_bounds,
            point=[input_x, input_y],
            selected_reason="fallback search input point from window split geometry",
            fallback_reason="search_input_ocr_not_detected",
            risk="type_query_here",
            source="fallback_search_input_geometry",
            metadata={"image_size": [image_size[0], image_size[1]], "search_region": search_region},
        )
        input_target["item"] = None
    if search_button is not None:
        button_x, button_y = add_friend_item_center(search_button)
        if abs(button_x - input_x) < 80:
            button_x = min(image_size[0] - 32, input_x + 210)
        button_left = int(float(search_button.get("left") or button_x))
        button_top = int(float(search_button.get("top") or button_y))
        button_right = int(float(search_button.get("right") or button_x))
        button_bottom = int(float(search_button.get("bottom") or button_y))
        button_bounds = [
            max(search_region[0], button_left - 28),
            max(search_region[1], button_top - 16),
            min(image_size[0] - 12, button_right + 28),
            min(search_region[3], button_bottom + 16),
        ]
        button_target = ocr_item_locator(
            name="add_friend_search_button",
            label="Add friend page search button",
            region=add_friend_region_for_point(button_x, button_y, image_size),
            bounds=button_bounds,
            point=[button_x, button_y],
            item=search_button,
            selected_reason="matched search button OCR text",
            risk="click_search_after_query_verified",
            source="ocr_search_button",
            metadata={"image_size": [image_size[0], image_size[1]], "search_region": search_region},
        )
        button_target["item"] = add_friend_item_snapshot(search_button, image_size)
    else:
        button_x, button_y = min(image_size[0] - 38, input_x + 230), input_y
        button_bounds = [
            max(search_region[0], button_x - 42),
            max(search_region[1], button_y - 24),
            min(image_size[0] - 12, button_x + 42),
            min(search_region[3], button_y + 24),
        ]
        button_target = geometry_fallback_locator(
            name="add_friend_search_button",
            label="Add friend page search button",
            region=add_friend_region_for_point(button_x, button_y, image_size),
            bounds=button_bounds,
            point=[button_x, button_y],
            selected_reason="fallback search button point to the right of search input",
            fallback_reason="search_button_ocr_not_detected",
            risk="click_search_after_query_verified",
            source="fallback_search_button_geometry",
            metadata={"image_size": [image_size[0], image_size[1]], "search_region": search_region},
        )
        button_target["item"] = None
    return {
        "search_region": search_region,
        "input": input_target,
        "button": button_target,
    }


def add_friend_query_visible_in_items(query: str, ocr_items: list[dict[str, Any]]) -> dict[str, Any]:
    clean_query = add_friend_ocr_compact(query)
    text = add_friend_surface_text(ocr_items)
    digits_query = re.sub(r"\D+", "", str(query or ""))
    digits_text = re.sub(r"\D+", "", text)
    visible = bool(clean_query and clean_query in text) or bool(digits_query and digits_query in digits_text)
    return {
        "ok": visible,
        "query": str(query or ""),
        "ocr_text": text,
        "digits_text": digits_text,
    }


def type_add_friend_query_like_human_for_entry(query: str) -> dict[str, Any]:
    clean = str(query or "")
    typed = 0
    if not clean:
        return {"ok": False, "reason": "empty_query", "typed_chars": 0}
    if not re.fullmatch(r"\d{5,20}", clean):
        try:
            clipboard_copy(clean)
            humanized_action_sleep(260, 620)
            hotkey(win32con.VK_CONTROL, ord("V"))
            humanized_action_sleep(260, 680)
            return {"ok": True, "method": "clipboard_paste_full_query", "typed_chars": len(clean)}
        except Exception as exc:
            return {"ok": False, "method": "clipboard_paste_full_query", "error": repr(exc), "typed_chars": 0}
    try:
        for index, char in enumerate(clean, start=1):
            key_press(add_friend_virtual_key_for_digit(char))
            typed += 1
            humanized_action_sleep(
                bounded_int(os.getenv("WECHAT_WIN32_OCR_ADD_FRIEND_CHAR_DELAY_MIN_MS"), default=90, minimum=40, maximum=500),
                bounded_int(os.getenv("WECHAT_WIN32_OCR_ADD_FRIEND_CHAR_DELAY_MAX_MS"), default=210, minimum=80, maximum=800),
            )
            if index % random.randint(4, 6) == 0 and index < len(clean):
                humanized_action_sleep(240, 520)
    except Exception as exc:
        return {"ok": False, "method": "digit_key_by_key", "error": repr(exc), "typed_chars": typed}
    return {"ok": True, "method": "digit_key_by_key", "typed_chars": typed}


def backspace_add_friend_query_chars(count: int) -> dict[str, Any]:
    deleted = 0
    try:
        for _ in range(max(0, int(count or 0))):
            key_press(win32con.VK_BACK)
            deleted += 1
            humanized_action_sleep(85, 220)
    except Exception as exc:
        return {"ok": False, "error": repr(exc), "deleted_chars": deleted}
    return {"ok": True, "deleted_chars": deleted}


def add_friend_dialog_surface_detected(ocr_items: list[dict[str, Any]]) -> dict[str, Any]:
    surface = add_friend_surface_text(ocr_items)
    has_title = "添加朋友" in surface or "添加好友" in surface
    has_search_placeholder = (
        ("搜索" in surface and ("微信号" in surface or "手机号" in surface))
        or "搜索微信号或者手机号" in surface
        or "搜索微信号或手机号" in surface
    )
    return {
        "detected": bool(has_title or has_search_placeholder),
        "has_title": has_title,
        "has_search_placeholder": has_search_placeholder,
        "surface": surface,
    }


def is_add_friend_dialog_window_item(item: dict[str, Any], *, exclude_hwnd: int) -> bool:
    hwnd = int(item.get("hwnd") or 0)
    if not hwnd or hwnd == int(exclude_hwnd or 0):
        return False
    if not item.get("visible"):
        return False
    title = normalize_wechat_title(str(item.get("title") or ""))
    if "添加朋友" in title or "添加好友" in title:
        return True
    try:
        geometry = get_window_geometry(hwnd)
    except Exception:
        return False
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    # The add-friend dialog is a compact WeChat child/top-level window. This
    # only broadens candidates; OCR still confirms before we operate it.
    return 300 <= width <= 620 and 360 <= height <= 760


def wait_for_add_friend_dialog_window(
    *,
    exclude_hwnd: int,
    output_dir: Path,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    deadline = started + max(800, int(timeout_ms)) / 1000.0
    while time.perf_counter() < deadline:
        probe = probe_wechat_windows()
        candidates = [
            item for item in (probe.get("visible_windows") or [])
            if is_add_friend_dialog_window_item(item, exclude_hwnd=exclude_hwnd)
        ]
        candidates.sort(
            key=lambda item: (
                1 if "添加朋友" in normalize_wechat_title(str(item.get("title") or "")) else 0,
                int(get_window_geometry(int(item.get("hwnd") or 0)).get("width") or 0)
                if int(item.get("hwnd") or 0)
                else 0,
            ),
            reverse=True,
        )
        for item in candidates:
            candidate_hwnd = int(item.get("hwnd") or 0)
            if not candidate_hwnd:
                continue
            try:
                screenshot, screenshot_path = capture_wechat_window_visible_screen(
                    candidate_hwnd,
                    artifact_dir=str(output_dir),
                    label="add_friend_dialog_window_candidate",
                )
                region = add_friend_page_search_region(screenshot.size)
                ocr_started_at = time.perf_counter()
                ocr_items = run_ocr_on_screen_region(screenshot, region)
                detection = add_friend_dialog_surface_detected(ocr_items)
                annotated_path = output_dir / f"add_friend_dialog_window_candidate_{candidate_hwnd}_annotated.png"
                annotated = draw_add_friend_screen_annotation(
                    screenshot,
                    ocr_items=ocr_items,
                    targets=[],
                    output_path=annotated_path,
                    window_rect=None,
                )
                attempt = {
                    "hwnd": candidate_hwnd,
                    "window": item,
                    "screenshot_path": screenshot_path,
                    "annotated_path": annotated,
                    "ocr_region": region,
                    "ocr_seconds": round(time.perf_counter() - ocr_started_at, 3),
                    "ocr_count": len(ocr_items),
                    "detection": detection,
                    "geometry": get_window_geometry(candidate_hwnd),
                }
                attempts.append(attempt)
                if detection.get("detected"):
                    return {
                        "ok": True,
                        "hwnd": candidate_hwnd,
                        "window": item,
                        "geometry": attempt["geometry"],
                        "screenshot_path": screenshot_path,
                        "annotated_path": annotated,
                        "ocr_items": add_friend_ocr_snapshots(ocr_items, screenshot.size),
                        "detection": detection,
                        "attempts": attempts,
                        "seconds": round(time.perf_counter() - started, 3),
                    }
            except Exception as exc:
                attempts.append({"hwnd": candidate_hwnd, "window": item, "error": repr(exc)})
        humanized_action_sleep(240, 520)
    return {
        "ok": False,
        "reason": "add_friend_dialog_window_not_found",
        "attempts": attempts,
        "seconds": round(time.perf_counter() - started, 3),
    }


def add_friend_invite_form_surface_detected(ocr_items: list[dict[str, Any]]) -> dict[str, Any]:
    surface = add_friend_surface_text(ocr_items)
    has_title = "申请添加朋友" in surface or "朋友验证" in surface
    has_greeting = "发送添加朋友申请" in surface
    has_remark = "备注" in surface
    has_confirm = "确定" in surface
    return {
        "detected": bool(has_title or (has_greeting and has_remark) or (has_remark and has_confirm)),
        "has_title": has_title,
        "has_greeting": has_greeting,
        "has_remark": has_remark,
        "has_confirm": has_confirm,
        "surface": surface,
    }


def is_add_friend_invite_form_window_item(item: dict[str, Any], *, exclude_hwnds: set[int]) -> bool:
    hwnd = int(item.get("hwnd") or 0)
    if not hwnd or hwnd in exclude_hwnds:
        return False
    if not item.get("visible"):
        return False
    title = normalize_wechat_title(str(item.get("title") or ""))
    if "申请添加朋友" in title or "朋友验证" in title:
        return True
    try:
        geometry = get_window_geometry(hwnd)
    except Exception:
        return False
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    # The invite form is taller than the compact add-friend search dialog.
    # OCR still confirms before we operate it.
    return 360 <= width <= 660 and 580 <= height <= 980


def wait_for_add_friend_invite_form_window(
    *,
    exclude_hwnds: set[int],
    output_dir: Path,
    timeout_ms: int = 6000,
) -> dict[str, Any]:
    started = time.perf_counter()
    attempts: list[dict[str, Any]] = []
    deadline = started + max(1000, int(timeout_ms)) / 1000.0
    while time.perf_counter() < deadline:
        probe = probe_wechat_windows()
        candidates = [
            item for item in (probe.get("visible_windows") or [])
            if is_add_friend_invite_form_window_item(item, exclude_hwnds=exclude_hwnds)
        ]
        candidates.sort(
            key=lambda item: (
                1 if "申请添加朋友" in normalize_wechat_title(str(item.get("title") or "")) else 0,
                int(get_window_geometry(int(item.get("hwnd") or 0)).get("height") or 0)
                if int(item.get("hwnd") or 0)
                else 0,
            ),
            reverse=True,
        )
        for item in candidates:
            candidate_hwnd = int(item.get("hwnd") or 0)
            if not candidate_hwnd:
                continue
            try:
                screenshot, screenshot_path = capture_wechat_window_visible_screen(
                    candidate_hwnd,
                    artifact_dir=str(output_dir),
                    label="add_friend_invite_form_window_candidate",
                )
                ocr_started_at = time.perf_counter()
                ocr_items = run_ocr_on_screen_region(screenshot, [0, 0, screenshot.size[0], screenshot.size[1]])
                detection = add_friend_invite_form_surface_detected(ocr_items)
                annotated_path = output_dir / f"add_friend_invite_form_window_candidate_{candidate_hwnd}_annotated.png"
                annotated = draw_add_friend_screen_annotation(
                    screenshot,
                    ocr_items=ocr_items,
                    targets=list(add_friend_invite_form_targets(screenshot.size, ocr_items).values()),
                    output_path=annotated_path,
                    window_rect=None,
                )
                attempt = {
                    "hwnd": candidate_hwnd,
                    "window": item,
                    "screenshot_path": screenshot_path,
                    "annotated_path": annotated,
                    "ocr_seconds": round(time.perf_counter() - ocr_started_at, 3),
                    "ocr_count": len(ocr_items),
                    "detection": detection,
                    "geometry": get_window_geometry(candidate_hwnd),
                }
                attempts.append(attempt)
                if detection.get("detected"):
                    return {
                        "ok": True,
                        "hwnd": candidate_hwnd,
                        "window": item,
                        "geometry": attempt["geometry"],
                        "screenshot_path": screenshot_path,
                        "annotated_path": annotated,
                        "ocr_items": add_friend_ocr_snapshots(ocr_items, screenshot.size),
                        "detection": detection,
                        "attempts": attempts,
                        "seconds": round(time.perf_counter() - started, 3),
                    }
            except Exception as exc:
                attempts.append({"hwnd": candidate_hwnd, "window": item, "error": repr(exc)})
        humanized_action_sleep(240, 520)
    return {
        "ok": False,
        "reason": "add_friend_invite_form_window_not_found",
        "attempts": attempts,
        "seconds": round(time.perf_counter() - started, 3),
    }


def click_add_friend_menu_entry_and_capture(
    hwnd: int,
    output_dir: Path,
    *,
    menu_targets: list[dict[str, Any]],
) -> dict[str, Any]:
    target = add_friend_target_by_name(menu_targets, "add_friend_menu_entry")
    if target is None:
        return {
            "clicked": False,
            "reason": "add_friend_menu_entry_not_found",
            "target": None,
        }
    if str(target.get("source") or "") != "ocr_popup_menu_item":
        return {
            "clicked": False,
            "reason": "add_friend_menu_entry_requires_ocr_confirmation",
            "target": target,
        }
    click_bounds = target.get("click_bounds")
    screen_bounds = target.get("click_screen_bounds")
    if not (isinstance(click_bounds, list) and len(click_bounds) >= 4 and isinstance(screen_bounds, list) and len(screen_bounds) >= 4):
        return {
            "clicked": False,
            "reason": "add_friend_menu_entry_missing_click_bounds",
            "target": target,
        }
    target_x = int(target.get("x") or 0)
    target_y = int(target.get("y") or 0)
    if not point_in_bounds(target_x, target_y, click_bounds):
        return {
            "clicked": False,
            "reason": "add_friend_menu_entry_target_outside_click_bounds",
            "target": target,
            "click_bounds": click_bounds,
        }
    screen_x, screen_y = add_friend_target_screen_point(target)
    if not point_in_bounds(screen_x, screen_y, screen_bounds):
        screen_x, screen_y = clamp_point_to_bounds(screen_x, screen_y, screen_bounds)
    timings: list[dict[str, Any]] = []
    pause_seconds = add_friend_paced_pause("critical_click", reason="before_add_friend_menu_hover")
    timings.append({"name": "before_add_friend_menu_hover_pause", "seconds": round(pause_seconds, 3)})
    hover_started_at = time.perf_counter()
    hover_result = human_screen_hover(screen_x, screen_y, action_name="add_friend_menu_entry_hover")
    timings.append({"name": "add_friend_menu_entry_hover", "seconds": round(time.perf_counter() - hover_started_at, 3), "result": hover_result})
    pause_seconds = add_friend_paced_pause("critical_click", reason="after_add_friend_menu_hover_before_click")
    timings.append({"name": "after_add_friend_menu_hover_before_click_pause", "seconds": round(pause_seconds, 3)})
    click_started_at = time.perf_counter()
    click_result = human_screen_click_in_bounds(
        screen_x,
        screen_y,
        bounds=screen_bounds,
        action_name="add_friend_menu_entry_click",
    )
    timings.append({"name": "add_friend_menu_entry_click", "seconds": round(time.perf_counter() - click_started_at, 3), "result": click_result})
    pause_seconds = add_friend_paced_pause("verify", reason="after_add_friend_menu_click_before_screen_capture")
    timings.append({"name": "after_add_friend_menu_click_before_screen_capture_pause", "seconds": round(pause_seconds, 3)})
    dialog_probe = wait_for_add_friend_dialog_window(exclude_hwnd=hwnd, output_dir=output_dir)
    next_hwnd = int(dialog_probe.get("hwnd") or 0) if dialog_probe.get("ok") else 0
    evidence_hwnd = next_hwnd or hwnd
    capture_error = ""
    dialog_handle_invalid = False
    try:
        geometry = get_window_geometry(evidence_hwnd)
        screenshot, screenshot_path = capture_wechat_window_visible_screen(
            evidence_hwnd,
            artifact_dir=str(output_dir),
            label="add_friend_menu_entry_after_click_window",
        )
    except Exception as exc:
        capture_error = repr(exc)
        if evidence_hwnd == hwnd:
            return {
                "clicked": False,
                "menu_clicked": bool(click_result.get("ok")),
                "next_hwnd": 0,
                "dialog_window": dialog_probe,
                "reason": "add_friend_menu_entry_after_click_capture_failed",
                "target": target,
                "hover": hover_result,
                "click": click_result,
                "timings": timings,
                "error": capture_error,
            }
        dialog_handle_invalid = True
        stale_hwnd = evidence_hwnd
        evidence_hwnd = hwnd
        next_hwnd = 0
        geometry = get_window_geometry(evidence_hwnd)
        screenshot, screenshot_path = capture_wechat_window_visible_screen(
            evidence_hwnd,
            artifact_dir=str(output_dir),
            label="add_friend_menu_entry_after_click_fallback_main_window",
        )
        dialog_probe = {
            **dialog_probe,
            "stale_hwnd": stale_hwnd,
            "fallback_hwnd": hwnd,
            "fallback_reason": "dialog_window_handle_invalid",
            "fallback_error": capture_error,
        }
    ocr_items: list[dict[str, Any]] = []
    readiness = {
        "ok": bool(dialog_probe.get("ok")) and not dialog_handle_invalid,
        "stage": "after_add_friend_menu_entry_click",
        "capture_mode": "wechat_window_visible",
        "dialog_window_found": bool(dialog_probe.get("ok")),
        "dialog_handle_invalid": dialog_handle_invalid,
        "ocr_count": 0,
        "ocr_skipped": True,
    }
    annotated_path = output_dir / "add_friend_menu_entry_after_click_window_annotated.png"
    local_target = dict(target)
    if evidence_hwnd != hwnd:
        local_target["annotation_x"] = 0
        local_target["annotation_y"] = 0
    annotated = draw_add_friend_screen_annotation(
        screenshot,
        ocr_items=ocr_items,
        targets=[] if evidence_hwnd != hwnd else [target],
        output_path=annotated_path,
        window_rect=None,
    )
    return {
        "clicked": bool(click_result.get("ok")) and bool(dialog_probe.get("ok")) and not dialog_handle_invalid,
        "menu_clicked": bool(click_result.get("ok")),
        "next_hwnd": next_hwnd,
        "dialog_window": dialog_probe,
        "reason": (
            "add_friend_dialog_window_handle_invalid_after_menu_click"
            if dialog_handle_invalid
            else "add_friend_dialog_window_ready" if dialog_probe.get("ok") else "add_friend_dialog_window_not_found_after_menu_click"
        ),
        "target": target,
        "hover": hover_result,
        "click": click_result,
        "timings": timings,
        "error": capture_error,
        "geometry": geometry,
        "screenshot_path": screenshot_path,
        "annotated_path": annotated,
        "readiness": readiness,
        "ocr_items": add_friend_ocr_snapshots(ocr_items, screenshot.size),
    }


def input_add_friend_query_and_search(
    hwnd: int,
    output_dir: Path,
    *,
    query: str,
    verify_message: str = "",
    remark_name: str = "",
    remark_code: str = "",
) -> dict[str, Any]:
    if not query:
        return {"ok": False, "reason": "empty_query"}
    timings: list[dict[str, Any]] = []
    geometry = get_window_geometry(hwnd)
    page_shot, page_path = capture_wechat_window_visible_screen(hwnd, artifact_dir=str(output_dir), label="add_friend_page_before_input_window")
    search_region = add_friend_page_search_region(page_shot.size)
    ocr_started_at = time.perf_counter()
    page_items = run_ocr_on_screen_region(page_shot, search_region)
    timings.append({"name": "add_friend_page_search_region_ocr", "seconds": round(time.perf_counter() - ocr_started_at, 3), "bounds": search_region, "ocr_count": len(page_items)})
    search_targets = find_add_friend_page_search_targets(page_items, page_shot.size)
    targets = [search_targets["input"], search_targets["button"]]
    page_annotated_path = output_dir / "add_friend_page_before_input_window_annotated.png"
    page_annotated = draw_add_friend_screen_annotation(
        page_shot,
        ocr_items=page_items,
        targets=targets,
        output_path=page_annotated_path,
        window_rect=None,
    )

    input_target = search_targets["input"]
    input_click_started_at = time.perf_counter()
    input_bounds = input_target.get("click_bounds")
    if isinstance(input_bounds, list) and len(input_bounds) >= 4:
        input_click_result = human_window_image_click_in_bounds(
            hwnd,
            int(input_target.get("x") or 0),
            int(input_target.get("y") or 0),
            bounds=input_bounds,
            action_name="add_friend_search_input_click",
        )
    else:
        human_window_image_click(hwnd, int(input_target.get("x") or 0), int(input_target.get("y") or 0))
        input_click_result = {"ok": True, "x": int(input_target.get("x") or 0), "y": int(input_target.get("y") or 0), "bounds": None}
    timings.append({"name": "add_friend_search_input_click", "seconds": round(time.perf_counter() - input_click_started_at, 3), "result": input_click_result})
    pause_seconds = add_friend_paced_pause("input", reason="after_add_friend_search_input_click_before_typing")
    timings.append({"name": "after_add_friend_search_input_click_before_typing_pause", "seconds": round(pause_seconds, 3)})
    clear_started_at = time.perf_counter()
    search_x = int(input_target.get("x") or 0)
    search_y = int(input_target.get("y") or 0)
    clear_result = clear_add_friend_sidebar_search_box(hwnd, search_x, search_y, target_hint=query)
    timings.append({"name": "clear_add_friend_search_box", "seconds": round(time.perf_counter() - clear_started_at, 3), "result": clear_result})

    input_attempts: list[dict[str, Any]] = []
    verified = False
    latest_verify_shot = page_shot
    latest_verify_path = page_path
    latest_verify_annotated = page_annotated
    latest_verify_items = page_items
    latest_verify_result: dict[str, Any] = {"ok": False, "reason": "not_attempted"}
    for attempt in range(1, 3):
        type_started_at = time.perf_counter()
        type_result = type_add_friend_query_like_human_for_entry(query)
        timings.append({"name": f"type_query_attempt_{attempt}", "seconds": round(time.perf_counter() - type_started_at, 3), "result": type_result})
        wait_started_at = time.perf_counter()
        add_friend_wait_before_ocr("after_search_input_before_ocr")
        timings.append({"name": f"after_query_type_attempt_{attempt}_before_verify_pause", "seconds": round(time.perf_counter() - wait_started_at, 3)})
        try:
            latest_verify_shot, latest_verify_path = capture_wechat_window_visible_screen(
                hwnd,
                artifact_dir=str(output_dir),
                label=f"add_friend_query_verify_attempt_{attempt}_window",
            )
        except Exception as exc:
            latest_verify_result = {
                "ok": False,
                "reason": "dialog_handle_invalid_during_query_verify",
                "error": repr(exc),
                "attempt": attempt,
                "hwnd": int(hwnd or 0),
            }
            input_attempts.append(
                {
                    "attempt": attempt,
                    "type_result": type_result,
                    "verify": latest_verify_result,
                    "screenshot_path": latest_verify_path,
                    "annotated_path": latest_verify_annotated,
                }
            )
            return {
                "ok": False,
                "state": "dialog_handle_invalid",
                "task_status": "failed",
                "error_code": ERROR_WECHAT_WINDOW_NOT_READY,
                "current_step": "query_input_verify",
                "server_report_payload": add_friend_server_report_payload(
                    task_status="failed",
                    error_code=ERROR_WECHAT_WINDOW_NOT_READY,
                    current_step="query_input_verify",
                ),
                "query": query,
                "geometry": geometry,
                "page": {
                    "screenshot_path": page_path,
                    "annotated_path": page_annotated,
                    "ocr_items": add_friend_ocr_snapshots(page_items, page_shot.size),
                    "targets": targets,
                },
                "input_attempts": input_attempts,
                "latest_verify": {
                    "screenshot_path": latest_verify_path,
                    "annotated_path": latest_verify_annotated,
                    "ocr_items": add_friend_ocr_snapshots(latest_verify_items, latest_verify_shot.size),
                    "verify": latest_verify_result,
                },
                "timings": timings,
            }
        verify_region = add_friend_page_search_region(latest_verify_shot.size)
        verify_ocr_started_at = time.perf_counter()
        latest_verify_items = run_ocr_on_screen_region(latest_verify_shot, verify_region)
        timings.append({"name": f"query_verify_region_ocr_attempt_{attempt}", "seconds": round(time.perf_counter() - verify_ocr_started_at, 3), "bounds": verify_region, "ocr_count": len(latest_verify_items)})
        latest_verify_result = add_friend_query_visible_in_items(query, latest_verify_items)
        latest_verify_annotated_path = output_dir / f"add_friend_query_verify_attempt_{attempt}_window_annotated.png"
        latest_verify_annotated = draw_add_friend_screen_annotation(
            latest_verify_shot,
            ocr_items=latest_verify_items,
            targets=targets,
            output_path=latest_verify_annotated_path,
            window_rect=None,
        )
        input_attempts.append(
            {
                "attempt": attempt,
                "type_result": type_result,
                "verify": latest_verify_result,
                "screenshot_path": latest_verify_path,
                "annotated_path": latest_verify_annotated,
            }
        )
        if latest_verify_result.get("ok"):
            verified = True
            break
        if attempt < 2:
            delete_result = backspace_add_friend_query_chars(len(str(query)))
            timings.append({"name": f"backspace_query_attempt_{attempt}", "result": delete_result})
            pause_seconds = add_friend_paced_pause("input", reason=f"after_query_backspace_attempt_{attempt}")
            timings.append({"name": f"after_query_backspace_attempt_{attempt}_pause", "seconds": round(pause_seconds, 3)})

    if not verified:
        return {
            "ok": False,
            "state": "input_unconfirmed",
            "query": query,
            "page": {
                "screenshot_path": page_path,
                "annotated_path": page_annotated,
                "ocr_items": add_friend_ocr_snapshots(page_items, page_shot.size),
                "targets": targets,
            },
            "input_attempts": input_attempts,
            "latest_verify": {
                "screenshot_path": latest_verify_path,
                "annotated_path": latest_verify_annotated,
                "ocr_items": add_friend_ocr_snapshots(latest_verify_items, latest_verify_shot.size),
                "verify": latest_verify_result,
            },
            "timings": timings,
        }

    button_target = search_targets["button"]
    pause_seconds = add_friend_paced_pause("critical_click", reason="before_add_friend_search_button_click")
    timings.append({"name": "before_add_friend_search_button_click_pause", "seconds": round(pause_seconds, 3)})
    button_click_started_at = time.perf_counter()
    button_bounds = button_target.get("click_bounds")
    if isinstance(button_bounds, list) and len(button_bounds) >= 4:
        button_click_result = human_window_image_click_in_bounds(
            hwnd,
            int(button_target.get("x") or 0),
            int(button_target.get("y") or 0),
            bounds=button_bounds,
            action_name="add_friend_search_button_click",
        )
    else:
        human_window_image_click(hwnd, int(button_target.get("x") or 0), int(button_target.get("y") or 0))
        button_click_result = {"ok": True, "x": int(button_target.get("x") or 0), "y": int(button_target.get("y") or 0), "bounds": None}
    timings.append({"name": "add_friend_search_button_click", "seconds": round(time.perf_counter() - button_click_started_at, 3), "result": button_click_result})
    pause_seconds = add_friend_paced_pause("verify", reason="after_add_friend_search_button_click_before_result_capture")
    timings.append({"name": "after_add_friend_search_button_click_before_result_capture_pause", "seconds": round(pause_seconds, 3)})
    result_shot, result_path = capture_wechat_window_visible_screen(hwnd, artifact_dir=str(output_dir), label="add_friend_search_result_window")
    result_region = add_friend_search_result_region(result_shot.size)
    result_ocr_started_at = time.perf_counter()
    result_items = run_ocr_on_screen_region(result_shot, result_region)
    timings.append({"name": "search_result_region_ocr", "seconds": round(time.perf_counter() - result_ocr_started_at, 3), "bounds": result_region, "ocr_count": len(result_items)})
    result_annotated_path = output_dir / "add_friend_search_result_window_annotated.png"
    result_annotated = draw_add_friend_screen_annotation(
        result_shot,
        ocr_items=result_items,
        targets=[button_target],
        output_path=result_annotated_path,
        window_rect=None,
    )
    add_contact_result = click_add_contact_entry_from_search_result(
        hwnd,
        output_dir,
        result_shot=result_shot,
        result_path=result_path,
        result_items=result_items,
        query=query,
        verify_message=verify_message,
        remark_name=remark_name,
        remark_code=remark_code,
    )
    add_contact_timings = list(add_contact_result.get("timings") or []) if isinstance(add_contact_result, dict) else []
    timings.extend(add_contact_timings)
    return {
        "ok": bool(add_contact_result.get("ok")) if isinstance(add_contact_result, dict) else False,
        "state": str(add_contact_result.get("state") or "search_clicked") if isinstance(add_contact_result, dict) else "search_clicked",
        "query": query,
        "task_status": add_contact_result.get("task_status") if isinstance(add_contact_result, dict) else None,
        "result_code": add_contact_result.get("result_code") if isinstance(add_contact_result, dict) else "",
        "error_code": add_contact_result.get("error_code") if isinstance(add_contact_result, dict) else "",
        "current_step": add_contact_result.get("current_step") if isinstance(add_contact_result, dict) else "searching_contact",
        "server_report_payload": add_contact_result.get("server_report_payload") if isinstance(add_contact_result, dict) else None,
        "geometry": geometry,
        "page": {
            "screenshot_path": page_path,
            "annotated_path": page_annotated,
            "ocr_items": add_friend_ocr_snapshots(page_items, page_shot.size),
            "targets": targets,
        },
        "input_attempts": input_attempts,
        "result": {
            "screenshot_path": result_path,
            "annotated_path": result_annotated,
            "ocr_items": add_friend_ocr_snapshots(result_items, result_shot.size),
        },
        "add_contact_result": add_contact_result,
        "timings": timings,
    }


def write_add_friend_entry_click_review(output_dir: Path, payload: dict[str, Any]) -> str:
    rows: list[dict[str, Any]] = []
    if payload.get("validation_errors") or payload.get("state") == "task_payload_invalid":
        rows.append(
            {
                "title": "00 字段契约校验",
                "purpose": "检查 add-friend-entry-click-plan 是否收到正式必填字段；校验失败时不会触达微信 UI。",
                "expected": "verify_message、remark_name、remark_code 均非空，且 remark_name 必须包含 remark_code。",
                "raw": "",
                "annotated": "",
                "targets": [],
                "detection": {
                    "state": payload.get("state"),
                    "task_status": payload.get("task_status"),
                    "error_code": payload.get("error_code"),
                    "verify_message": payload.get("verify_message"),
                    "remark_name": payload.get("remark_name"),
                    "remark_code": payload.get("remark_code"),
                    "remark_code_valid": payload.get("remark_code_valid"),
                    "validation_errors": payload.get("validation_errors") or [],
                    "legacy_remark_fallback": payload.get("legacy_remark_fallback"),
                    "server_report_payload": payload.get("server_report_payload"),
                },
            }
        )
    before = payload.get("before") if isinstance(payload.get("before"), dict) else {}
    if before:
        rows.append(
            {
                "title": "01 运行前屏幕标注",
                "purpose": "检查 + 入口目标是否落在微信左上搜索框右侧；如果菜单本来已经打开，也会标注菜单项。",
                "expected": "红色 T1 应落在 + 上；不能点到搜索框、聊天区或 PowerShell。",
                "raw": before.get("screenshot_path"),
                "annotated": before.get("annotated_path"),
                "targets": before.get("planned_targets") or [],
                "detection": before.get("popup_detection"),
            }
        )
    for attempt in payload.get("click_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        attempt_no = attempt.get("attempt")
        rows.append(
            {
                "title": f"02 点击 + 后屏幕标注 attempt {attempt_no}",
                "purpose": "检查点击 + 后是否出现快捷操作弹出菜单 plus_entry_popup_menu，并检查菜单里的下一步目标。",
                "expected": "应能看到 发起群聊 / 添加朋友 / 新建笔记；红色 add_friend_menu_entry 应落在“添加朋友”这一行。",
                "raw": attempt.get("screenshot_path"),
                "annotated": attempt.get("annotated_path"),
                "targets": attempt.get("planned_targets") or [],
                "detection": attempt.get("popup_detection"),
            }
        )
    menu_click = payload.get("menu_click") if isinstance(payload.get("menu_click"), dict) else {}
    if menu_click:
        rows.append(
            {
                "title": "03 点击添加朋友后屏幕标注",
                "purpose": "检查鼠标是否已经通过轨迹移动到“添加朋友”，停顿后点击，并进入下一层添加朋友界面。",
                "expected": "应不再停留在快捷操作弹出菜单；如果微信进入添加朋友/搜索页，说明这一格通过。",
                "raw": menu_click.get("screenshot_path"),
                "annotated": menu_click.get("annotated_path"),
                "targets": [menu_click.get("target")] if isinstance(menu_click.get("target"), dict) else [],
                "detection": {
                    "clicked": menu_click.get("clicked"),
                    "hover": menu_click.get("hover"),
                    "click": menu_click.get("click"),
                    "readiness": menu_click.get("readiness"),
                },
            }
        )
    query_search = payload.get("query_search") if isinstance(payload.get("query_search"), dict) else {}
    page = query_search.get("page") if isinstance(query_search.get("page"), dict) else {}
    if page:
        rows.append(
            {
                "title": "04 添加朋友页搜索框标注",
                "purpose": "检查进入添加朋友页后，搜索输入框和搜索按钮定位是否合理。",
                "expected": "红色 add_friend_search_input 应落在输入框，add_friend_search_button 应落在搜索按钮。",
                "raw": page.get("screenshot_path"),
                "annotated": page.get("annotated_path"),
                "targets": page.get("targets") or [],
                "detection": {"state": query_search.get("state"), "query": query_search.get("query")},
            }
        )
    for attempt in query_search.get("input_attempts") or []:
        if not isinstance(attempt, dict):
            continue
        rows.append(
            {
                "title": f"05 输入核对 attempt {attempt.get('attempt')}",
                "purpose": "检查手机号/微信号是否完整输入，OCR 是否确认输入内容正确。",
                "expected": "verify.ok=true；如果 false，脚本会逐个 Backspace 删除后重输一次。",
                "raw": attempt.get("screenshot_path"),
                "annotated": attempt.get("annotated_path"),
                "targets": page.get("targets") or [],
                "detection": attempt.get("verify"),
            }
        )
    result = query_search.get("result") if isinstance(query_search.get("result"), dict) else {}
    if result:
        rows.append(
            {
                "title": "06 点击搜索后结果区标注",
                "purpose": "检查点击搜索后，结果区域是否出现内容。",
                "expected": "截图中应能看到搜索后的页面内容；橙色框只标和搜索结果区域有关的 OCR。",
                "raw": result.get("screenshot_path"),
                "annotated": result.get("annotated_path"),
                "targets": [],
                "detection": {"state": query_search.get("state"), "ok": query_search.get("ok")},
            }
        )
    add_contact_result = query_search.get("add_contact_result") if isinstance(query_search.get("add_contact_result"), dict) else {}
    if add_contact_result:
        add_contact_before = add_contact_result.get("before") if isinstance(add_contact_result.get("before"), dict) else {}
        add_contact_after = add_contact_result.get("after") if isinstance(add_contact_result.get("after"), dict) else {}
        if add_contact_before:
            rows.append(
                {
                    "title": "07 点击添加到通讯录前标注",
                    "purpose": "检查搜索结果里是否识别到“添加到通讯录”按钮；搜不到用户时这里会展示失败状态。",
                    "expected": "搜到用户时红色 add_contact_entry_button 应落在“添加到通讯录”；搜不到时 detection.error_code=PHONE_NOT_FOUND。",
                    "raw": add_contact_before.get("screenshot_path"),
                    "annotated": add_contact_before.get("annotated_path"),
                    "targets": add_contact_before.get("targets") or [],
                    "detection": {
                        "state": add_contact_result.get("state"),
                        "task_status": add_contact_result.get("task_status"),
                        "error_code": add_contact_result.get("error_code"),
                        "current_step": add_contact_result.get("current_step"),
                        "server_report_payload": add_contact_result.get("server_report_payload"),
                    },
                }
            )
        elif add_contact_result.get("annotated_path") or add_contact_result.get("screenshot_path"):
            rows.append(
                {
                    "title": "07 搜索结果失败判定",
                    "purpose": "检查搜索结果是否为找不到用户，并输出任务失败上报字段。",
                    "expected": "找不到用户时 task_status=failed、error_code=PHONE_NOT_FOUND、current_step=searching_phone。",
                    "raw": add_contact_result.get("screenshot_path"),
                    "annotated": add_contact_result.get("annotated_path"),
                    "targets": add_contact_result.get("targets") or [],
                    "detection": {
                        "state": add_contact_result.get("state"),
                        "task_status": add_contact_result.get("task_status"),
                        "error_code": add_contact_result.get("error_code"),
                        "current_step": add_contact_result.get("current_step"),
                        "server_report_payload": add_contact_result.get("server_report_payload"),
                        "not_found": add_contact_result.get("not_found"),
                    },
                }
            )
        if add_contact_after:
            rows.append(
                {
                    "title": "08 点击添加到通讯录后截图",
                    "purpose": "检查脚本是否只点击了一次“添加到通讯录”，然后进入申请添加朋友表单。",
                    "expected": "应出现“申请添加朋友”表单；下一步会清空默认申请文案并填写固定话术。",
                    "raw": add_contact_after.get("screenshot_path"),
                    "annotated": add_contact_after.get("annotated_path"),
                    "targets": add_contact_after.get("targets") or [],
                    "detection": {
                        "state": add_contact_result.get("state"),
                        "task_status": add_contact_result.get("task_status"),
                        "current_step": add_contact_result.get("current_step"),
                        "click": add_contact_result.get("click"),
                        "error_code": add_contact_result.get("error_code"),
                        "invite_form_probe": add_contact_result.get("invite_form_probe"),
                    },
                }
            )
        invite_form = add_contact_result.get("invite_form") if isinstance(add_contact_result.get("invite_form"), dict) else {}
        if invite_form:
            invite_before = invite_form.get("before") if isinstance(invite_form.get("before"), dict) else {}
            invite_filled = invite_form.get("filled") if isinstance(invite_form.get("filled"), dict) else {}
            invite_after = invite_form.get("after") if isinstance(invite_form.get("after"), dict) else {}
            if invite_before:
                rows.append(
                    {
                        "title": "09 申请表单填写前标注",
                        "purpose": "检查申请文案框、备注框、确定按钮三个操作区域是否落在正确位置。",
                        "expected": "invite_greeting_textarea 应落在“发送添加朋友申请”文本框；invite_remark_input 应落在备注框；invite_confirm_button 应落在绿色确定按钮。",
                        "raw": invite_before.get("screenshot_path"),
                        "annotated": invite_before.get("annotated_path"),
                        "targets": invite_before.get("targets") or [],
                        "detection": {
                            "state": invite_form.get("state"),
                            "verify_message": invite_form.get("verify_message"),
                            "remark_name": invite_form.get("remark_name"),
                            "remark_code": invite_form.get("remark_code"),
                            "remark_code_valid": invite_form.get("remark_code_valid"),
                            "validation_errors": invite_form.get("validation_errors") or [],
                            "legacy_remark_fallback": invite_form.get("legacy_remark_fallback"),
                        },
                    }
                )
            if invite_filled:
                rows.append(
                    {
                        "title": "10 申请表单填写后/确定前截图",
                        "purpose": "检查申请语是否写入 verify_message，微信备注框是否写入 remark_name。",
                        "expected": "申请语应等于传入的 verify_message；备注名应等于传入的 remark_name，且 remark_name 包含 remark_code。",
                        "raw": invite_filled.get("screenshot_path"),
                        "annotated": invite_filled.get("annotated_path"),
                        "targets": invite_filled.get("targets") or [],
                        "detection": {
                            "state": invite_form.get("state"),
                            "verify_message": invite_form.get("verify_message"),
                            "remark_name": invite_form.get("remark_name"),
                            "remark_code": invite_form.get("remark_code"),
                            "remark_code_valid": invite_form.get("remark_code_valid"),
                            "validation_errors": invite_form.get("validation_errors") or [],
                            "legacy_remark_fallback": invite_form.get("legacy_remark_fallback"),
                            "greeting": invite_form.get("greeting"),
                            "remark_fill": invite_form.get("remark_fill"),
                        },
                    }
                )
            if invite_after:
                rows.append(
                    {
                        "title": "11 点击确定后截图",
                        "purpose": "检查脚本是否点击了“确定”，并用点击后的 OCR 结果复核最终任务状态。",
                        "expected": "confirm.ok=true；只要没有明确失败/风控提示，就按 completed + invite_sent 上报；already_friend 只允许在发送邀请前的搜索结果/资料页阶段判定。",
                        "raw": invite_after.get("screenshot_path"),
                        "annotated": invite_after.get("annotated_path"),
                        "targets": [],
                        "detection": {
                            "state": invite_form.get("state"),
                            "task_status": invite_form.get("task_status"),
                            "result_code": invite_form.get("result_code"),
                            "error_code": invite_form.get("error_code"),
                            "current_step": invite_form.get("current_step"),
                            "verify_message": invite_form.get("verify_message"),
                            "remark_name": invite_form.get("remark_name"),
                            "remark_code": invite_form.get("remark_code"),
                            "remark_code_valid": invite_form.get("remark_code_valid"),
                            "validation_errors": invite_form.get("validation_errors") or [],
                            "confirm": invite_form.get("confirm"),
                            "final_status": invite_after.get("final_status"),
                            "server_report_payload": invite_form.get("server_report_payload"),
                        },
                    }
                )
    after = payload.get("after") if isinstance(payload.get("after"), dict) else {}
    if after:
        rows.append(
            {
                "title": "99 最终判定",
                "purpose": "确认本次脚本有没有识别到快捷操作弹出菜单，以及后续是否具备点击“添加朋友”的目标。",
                "expected": "popup_detection.detected=true，planned_targets 里应包含 add_friend_menu_entry；menu_click.clicked=true。",
                "raw": after.get("screenshot_path"),
                "annotated": after.get("annotated_path"),
                "targets": after.get("planned_targets") or [],
                "detection": after.get("popup_detection"),
            }
        )
    summary = {
        "state": payload.get("state"),
        "note": payload.get("note"),
        "calibration_only": bool(payload.get("calibration_only")),
        "no_clicks_performed": bool(payload.get("no_clicks_performed")),
        "verify_message": payload.get("verify_message"),
        "remark_name": payload.get("remark_name"),
        "remark_code": payload.get("remark_code"),
        "remark_code_valid": payload.get("remark_code_valid"),
        "validation_errors": payload.get("validation_errors") or [],
        "legacy_remark_fallback": payload.get("legacy_remark_fallback"),
        "device_profile": payload.get("device_profile") or (payload.get("window_probe") or {}).get("device_profile"),
        "operator_guard": payload.get("operator_guard") or (payload.get("window_probe") or {}).get("operator_guard"),
        "operator_guard_release": payload.get("operator_guard_release") or {},
        "timings": payload.get("timings") or [],
    }
    diagnostic_events = payload.get("diagnostic_events")
    existing_events = (
        [event for event in diagnostic_events if isinstance(event, dict)]
        if isinstance(diagnostic_events, list)
        else []
    )
    events = add_friend_entry_click_events_from_payload(payload, existing_events=existing_events)
    if not events:
        events = step_events_from_review_rows(rows)
    summary["event_source"] = "flow_payload_events" if events else "legacy_review_rows"
    if existing_events:
        summary["event_source"] = "diagnostic_events+flow_payload_events"
    return write_step_event_report(
        output_dir=output_dir,
        json_name="add_friend_entry_click_review.json",
        html_name="add_friend_entry_click_review.html",
        title="add_friend 入口点击复核报告",
        description="本报告验证点击 +、点击“添加朋友”、输入手机号/微信号、点击搜索、点击“添加到通讯录”、填写申请表单并点击“确定”。",
        summary=summary,
        events=events,
    )


def add_friend_entry_click_plan_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    route: str = ADD_FRIEND_MAIN_ROUTE,
    phone: str = "",
    wechat: str = "",
    verify_message: str = "",
    remark_name: str = "",
    remark_code: str = "",
    artifact_dir: str | None = None,
    calibration_only: bool = False,
) -> dict[str, Any]:
    try:
        geometry = get_window_geometry(hwnd)
    except Exception as exc:
        geometry = {}
        geometry_check = {"ok": False, "reason": "wechat_window_geometry_unavailable", "error": repr(exc)}
    else:
        geometry_check = validate_capture_geometry(geometry)
    quick_login = probe.get("quick_login") if isinstance(probe.get("quick_login"), dict) else {}
    if not geometry_check.get("ok") or quick_login.get("detected"):
        output_dir = Path(artifact_dir) if artifact_dir else add_friend_route_artifact_root(PROJECT_ROOT, route) / time.strftime("%Y%m%d_%H%M%S")
        output_dir.mkdir(parents=True, exist_ok=True)
        reason = str(quick_login.get("reason") or geometry_check.get("reason") or "wechat_window_not_ready")
        payload = add_friend_failure_payload(
            error_code=ERROR_WECHAT_WINDOW_NOT_READY,
            message="WeChat main window is not ready for add_friend automation.",
            steps=["preflight_window_ready"],
            query=normalize_add_friend_query(phone=phone, wechat=wechat),
            phone=phone,
            wechat=wechat,
            probe=probe,
            evidence={
                "geometry": geometry,
                "geometry_check": geometry_check,
                "quick_login": quick_login,
                "reason": reason,
                "manual_action_required": "open_or_login_wechat_main_window",
            },
            state="wechat_window_not_ready",
        )
        payload["task_status"] = "failed"
        payload["current_step"] = "preflight_window_ready"
        payload["server_report_payload"] = mapped_add_friend_server_report_payload(
            task_status="failed",
            error_code=ERROR_WECHAT_WINDOW_NOT_READY,
            current_step="preflight_window_ready",
        )
        payload["plan_path"] = str(output_dir / ADD_FRIEND_ENTRY_CLICK_PLAN_JSON)
        payload["review_path"] = write_add_friend_entry_click_review(output_dir, payload)
        Path(str(payload["plan_path"])).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    output_dir = Path(artifact_dir) if artifact_dir else add_friend_route_artifact_root(PROJECT_ROOT, route) / time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    device_profile = add_friend_device_profile(hwnd, geometry=geometry, route=route)
    probe = dict(probe or {})
    probe["device_profile"] = device_profile
    if calibration_only:
        return add_friend_calibration_payload(
            hwnd,
            probe,
            geometry=geometry,
            route=route,
            phone=phone,
            wechat=wechat,
            verify_message=verify_message,
            remark_name=remark_name,
            remark_code=remark_code,
            output_dir=output_dir,
        )
    pre_click_readiness = add_friend_pre_click_main_window_readiness(
        hwnd,
        geometry,
        route=route,
        output_dir=output_dir,
    )
    probe["add_friend_pre_click_main_window_readiness"] = pre_click_readiness
    if not pre_click_readiness.get("ok"):
        state = str(pre_click_readiness.get("state") or "wechat_main_surface_not_ready")
        error_code = str(pre_click_readiness.get("error_code") or ERROR_WECHAT_WINDOW_NOT_READY)
        payload = add_friend_failure_payload(
            error_code=error_code,
            message="WeChat main window is not foreground or not on the add_friend entry surface.",
            steps=["preflight_main_surface_ready"],
            query=normalize_add_friend_query(phone=phone, wechat=wechat),
            phone=phone,
            wechat=wechat,
            probe=probe,
            evidence={
                "geometry": geometry,
                "geometry_check": geometry_check,
                "pre_click_readiness": pre_click_readiness,
                "manual_action_required": "run_wechat_startup_self_check_or_bring_wechat_main_window_foreground",
            },
            state=state,
        )
        payload["task_status"] = "failed"
        payload["current_step"] = "preflight_main_surface_ready"
        payload["no_clicks_performed"] = True
        payload["wechat_ui_action_attempted"] = False
        payload["calibration_only"] = False
        payload["route"] = route
        payload["verify_message"] = verify_message
        payload["remark_name"] = remark_name
        payload["remark_code"] = remark_code
        payload["server_report_payload"] = mapped_add_friend_server_report_payload(
            task_status="failed",
            error_code=error_code,
            current_step="preflight_main_surface_ready",
        )
        payload["plan_path"] = str(output_dir / ADD_FRIEND_ENTRY_CLICK_PLAN_JSON)
        payload["review_path"] = write_add_friend_entry_click_review(output_dir, payload)
        Path(str(payload["plan_path"])).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload
    operator_guard = start_add_friend_operator_guard(route=route, artifact_dir=str(output_dir))
    if operator_guard.get("ok") is not True:
        payload = add_friend_failure_payload(
            error_code=ERROR_OPERATOR_GUARD_NOT_READY,
            message="Add-friend RPA operator guard is not ready; the click flow was not started.",
            steps=["operator_guard_ready"],
            query=normalize_add_friend_query(phone=phone, wechat=wechat),
            phone=phone,
            wechat=wechat,
            probe=probe,
            evidence={
                "geometry": geometry,
                "geometry_check": geometry_check,
                "operator_guard": operator_guard,
                "manual_action_required": "check_rpa_floating_ball_operator_guard",
            },
            state="operator_guard_not_ready",
        )
        payload["task_status"] = "failed"
        payload["current_step"] = "operator_guard_ready"
        payload["server_report_payload"] = mapped_add_friend_server_report_payload(
            task_status="failed",
            error_code=ERROR_OPERATOR_GUARD_NOT_READY,
            current_step="operator_guard_ready",
        )
        payload["plan_path"] = str(output_dir / ADD_FRIEND_ENTRY_CLICK_PLAN_JSON)
        payload["review_path"] = write_add_friend_entry_click_review(output_dir, payload)
        Path(str(payload["plan_path"])).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    flow_probe = dict(probe)
    flow_probe["operator_guard"] = operator_guard
    payload: dict[str, Any] = {}
    try:
        payload = run_add_friend_entry_click_plan_flow(
            sys.modules[__name__],
            hwnd,
            flow_probe,
            phone=phone,
            wechat=wechat,
            verify_message=verify_message,
            remark_name=remark_name,
            remark_code=remark_code,
            artifact_dir=str(output_dir),
            route=route,
        )
        payload["operator_guard"] = operator_guard
    finally:
        release = stop_add_friend_operator_guard(operator_guard, reason="add_friend_entry_click_plan_finished")
        if isinstance(payload, dict):
            payload["operator_guard_release"] = release
            persist_add_friend_operator_guard_release(payload, release)
    return payload


ADD_FRIEND_FOREGROUND_READY_REASONS = {
    "foreground_matches_target",
    "foreground_root_matches_target",
}


def add_friend_focus_guard_ready(focus_guard: dict[str, Any]) -> dict[str, Any]:
    reason = str((focus_guard or {}).get("reason") or "")
    ok = bool((focus_guard or {}).get("ok")) and reason in ADD_FRIEND_FOREGROUND_READY_REASONS
    return {
        "ok": ok,
        "reason": reason or "foreground_guard_missing",
        "allowed_reasons": sorted(ADD_FRIEND_FOREGROUND_READY_REASONS),
        "focus_guard": focus_guard or {},
    }


def add_friend_pre_click_readiness_decision(
    *,
    focus_guard: dict[str, Any],
    surface_readiness: dict[str, Any],
) -> dict[str, Any]:
    focus_ready = add_friend_focus_guard_ready(focus_guard)
    if not focus_ready.get("ok"):
        return {
            "ok": False,
            "state": "wechat_window_not_foreground",
            "error_code": ERROR_WECHAT_WINDOW_NOT_READY,
            "reason": str(focus_ready.get("reason") or "foreground_not_wechat_target"),
            "focus_ready": focus_ready,
            "surface_readiness": surface_readiness,
            "no_clicks_performed": True,
        }
    if not bool((surface_readiness or {}).get("ok")):
        return {
            "ok": False,
            "state": str((surface_readiness or {}).get("state") or "wechat_main_surface_not_ready"),
            "error_code": str((surface_readiness or {}).get("error_code") or ERROR_WECHAT_WINDOW_NOT_READY),
            "reason": str((surface_readiness or {}).get("reason") or "add_friend_entry_surface_not_confirmed"),
            "focus_ready": focus_ready,
            "surface_readiness": surface_readiness or {},
            "no_clicks_performed": True,
        }
    return {
        "ok": True,
        "state": "wechat_main_surface_ready",
        "error_code": "",
        "reason": "foreground_and_main_surface_ready",
        "focus_ready": focus_ready,
        "surface_readiness": surface_readiness or {},
    }


def add_friend_pre_click_main_window_readiness(
    hwnd: int,
    geometry: dict[str, Any],
    *,
    route: str,
    output_dir: Path,
) -> dict[str, Any]:
    focus_guard = foreground_window_matches_target(hwnd)
    try:
        screenshot, screenshot_path = capture_wechat_window_visible_screen(
            hwnd,
            artifact_dir=str(output_dir),
            label="add_friend_pre_click_main_window",
        )
    except Exception as exc:
        surface_readiness = {
            "ok": False,
            "state": "wechat_main_surface_not_ready",
            "error_code": ERROR_WECHAT_WINDOW_NOT_READY,
            "stage": "formal_pre_click",
            "reason": "pre_click_capture_failed",
            "error": repr(exc),
            "ocr_count": 0,
        }
        decision = add_friend_pre_click_readiness_decision(
            focus_guard=focus_guard,
            surface_readiness=surface_readiness,
        )
        return {
            **decision,
            "stage": "formal_pre_click",
            "focus_guard": focus_guard,
            "screenshot_path": "",
            "annotated_path": "",
            "ocr_count": 0,
        }

    ocr_started_at = time.perf_counter()
    ocr_items = run_ocr_on_screen_region(screenshot, [0, 0, screenshot.size[0], screenshot.size[1]])
    ocr_seconds = round(time.perf_counter() - ocr_started_at, 3)
    route_kind = "windows_1080p_reference" if str(route or "") == ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE else "windows"
    plus_target = add_friend_plus_entry_target(geometry, screenshot.size, ocr_items, route_kind=route_kind)
    surface_readiness = add_friend_surface_readiness(
        screenshot,
        ocr_items,
        geometry,
        stage="formal_pre_click",
        require_main_surface=True,
    )
    annotated_path = output_dir / "add_friend_pre_click_main_window_annotated.png"
    annotated = draw_add_friend_screen_annotation(
        screenshot,
        ocr_items=ocr_items,
        targets=[plus_target],
        output_path=annotated_path,
        window_rect=None,
    )
    decision = add_friend_pre_click_readiness_decision(
        focus_guard=focus_guard,
        surface_readiness=surface_readiness,
    )
    return {
        **decision,
        "stage": "formal_pre_click",
        "focus_guard": focus_guard,
        "screenshot_path": screenshot_path,
        "annotated_path": annotated,
        "ocr_count": len(ocr_items),
        "ocr_seconds": ocr_seconds,
        "planned_targets": [plus_target],
        "ocr_items": add_friend_ocr_snapshots(ocr_items, screenshot.size),
        "surface_readiness": surface_readiness,
    }


def persist_add_friend_operator_guard_release(payload: dict[str, Any], release: dict[str, Any]) -> None:
    plan_path = Path(str(payload.get("plan_path") or ""))
    if not str(plan_path):
        return
    try:
        if plan_path.exists():
            saved = json.loads(plan_path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                if payload.get("operator_guard") and "operator_guard" not in saved:
                    saved["operator_guard"] = payload.get("operator_guard")
                if payload.get("device_profile") and "device_profile" not in saved:
                    saved["device_profile"] = payload.get("device_profile")
                saved["operator_guard_release"] = release
                payload.update({"diagnostic_events": saved.get("diagnostic_events") or payload.get("diagnostic_events")})
                plan_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
                review_path = write_add_friend_entry_click_review(plan_path.parent, saved)
                payload["review_path"] = review_path
                return
        plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["review_path"] = write_add_friend_entry_click_review(plan_path.parent, payload)
    except Exception as exc:
        payload["operator_guard_release_persist_error"] = repr(exc)


def add_friend_calibration_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    geometry: dict[str, Any],
    route: str,
    phone: str,
    wechat: str,
    verify_message: str,
    remark_name: str,
    remark_code: str,
    output_dir: Path,
) -> dict[str, Any]:
    screenshot, screenshot_path = capture_wechat_window_visible_screen(
        hwnd,
        artifact_dir=str(output_dir),
        label="add_friend_calibration_main_window",
    )
    ocr_started_at = time.perf_counter()
    ocr_items = run_ocr_on_screen_region(screenshot, [0, 0, screenshot.size[0], screenshot.size[1]])
    route_kind = "windows_1080p_reference" if str(route or "") == ADD_FRIEND_WINDOWS_1080P_REFERENCE_ROUTE else "windows"
    plus_target = add_friend_plus_entry_target(geometry, screenshot.size, ocr_items, route_kind=route_kind)
    readiness = add_friend_surface_readiness(screenshot, ocr_items, geometry, stage="calibration")
    annotated_path = output_dir / "add_friend_calibration_main_window_annotated.png"
    annotated = draw_add_friend_screen_annotation(
        screenshot,
        ocr_items=ocr_items,
        targets=[plus_target],
        output_path=annotated_path,
        window_rect=None,
    )
    device_profile = add_friend_device_profile(
        hwnd,
        geometry=geometry,
        screenshot_size=screenshot.size,
        route=route,
    )
    calibration_ready = bool(readiness.get("ok"))
    payload = {
        "ok": calibration_ready,
        "state": "calibration_ready" if readiness.get("ok") else "calibration_surface_not_ready",
        "task_status": "calibration_only",
        "result_code": "",
        "error_code": "" if readiness.get("ok") else str(readiness.get("error_code") or ERROR_WECHAT_WINDOW_NOT_READY),
        "current_step": "calibration",
        "route": route,
        "query": normalize_add_friend_query(phone=phone, wechat=wechat),
        "phone": phone,
        "wechat": wechat,
        "verify_message": verify_message,
        "remark_name": remark_name,
        "remark_code": remark_code,
        "remark_code_valid": bool(str(remark_code or "") and str(remark_code or "") in str(remark_name or "")),
        "calibration_only": True,
        "no_clicks_performed": True,
        "window_probe": probe,
        "geometry": geometry,
        "device_profile": device_profile,
        "before": {
            "screenshot_path": screenshot_path,
            "annotated_path": annotated,
            "capture_mode": "screen_visible",
            "readiness": readiness,
            "ocr_items": add_friend_ocr_snapshots(ocr_items, screenshot.size),
            "planned_targets": [plus_target],
            "ocr_seconds": round(time.perf_counter() - ocr_started_at, 3),
        },
        "timings": [
            {
                "name": "calibration_full_window_ocr",
                "seconds": round(time.perf_counter() - ocr_started_at, 3),
                "ocr_count": len(ocr_items),
            }
        ],
        "diagnostic_events": [
            {
                "step_id": "add_friend_calibration",
                "title": "add_friend 自适应校准",
                "status": "completed" if readiness.get("ok") else "failed",
                "state_before": "main_window",
                "state_after": "calibration_ready" if readiness.get("ok") else "calibration_surface_not_ready",
                "artifacts": {"raw": screenshot_path, "annotated": annotated},
                "targets": [plus_target],
                "selected_target": plus_target,
                "result": {
                    "ok": bool(readiness.get("ok")),
                    "readiness": readiness,
                    "device_profile": device_profile,
                    "no_clicks_performed": True,
                },
            }
        ],
    }
    payload["plan_path"] = str(output_dir / ADD_FRIEND_ENTRY_CLICK_PLAN_JSON)
    payload["review_path"] = write_add_friend_entry_click_review(output_dir, payload)
    Path(str(payload["plan_path"])).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def add_friend_failure_payload(
    *,
    error_code: str,
    message: str,
    steps: list[str],
    query: str,
    phone: str,
    wechat: str,
    probe: dict[str, Any],
    evidence: dict[str, Any] | None = None,
    state: str = "add_friend_failed",
) -> dict[str, Any]:
    return {
        "ok": False,
        "online": True,
        "adapter": "win32_ocr",
        "state": state,
        "task_type": "add_friend",
        "error_code": error_code,
        "message": message,
        "current_step": steps[-1] if steps else "",
        "steps": list(steps),
        "query": query,
        "phone": phone,
        "wechat": wechat,
        "window_probe": probe,
        "evidence": evidence or {},
    }


def add_friend_surface_readiness(
    screenshot: Image.Image,
    ocr_items: list[dict[str, Any]],
    geometry: dict[str, Any],
    *,
    stage: str,
    require_main_surface: bool | None = None,
) -> dict[str, Any]:
    blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
    shell_probe = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    screenshot_size = getattr(
        screenshot,
        "size",
        (
            int(geometry.get("width") or 0),
            int(geometry.get("height") or 0),
        ),
    )
    blocking_prompt = add_friend_login_or_security_block(ocr_items, geometry=geometry, image_size=screenshot_size)
    if blocking_prompt.get("detected"):
        return {
            "ok": False,
            "error_code": blocking_prompt.get("error_code") or ERROR_WECHAT_WINDOW_NOT_READY,
            "state": blocking_prompt.get("state") or "wechat_window_not_ready",
            "stage": stage,
            "reason": blocking_prompt.get("reason") or "wechat_login_or_security_prompt",
            "blocking_prompt": blocking_prompt,
            "render_probe": blank_render,
            "shell_probe": shell_probe,
            "ocr_count": len(ocr_items),
            "ocr_texts": [item.get("text") for item in ocr_items[:20]],
        }
    if blank_render.get("detected"):
        return {
            "ok": False,
            "error_code": "WECHAT_RENDER_NOT_READY",
            "state": "wechat_render_not_ready",
            "stage": stage,
            "reason": "blank_render",
            "render_probe": blank_render,
            "shell_probe": shell_probe,
            "ocr_count": len(ocr_items),
            "ocr_texts": [item.get("text") for item in ocr_items[:20]],
        }
    if shell_probe.get("detected") and str(shell_probe.get("reason") or "") == "title_only_shell":
        return {
            "ok": False,
            "error_code": "WECHAT_RENDER_NOT_READY",
            "state": "wechat_render_not_ready",
            "stage": stage,
            "reason": str(shell_probe.get("reason") or "auxiliary_shell_window"),
            "render_probe": blank_render,
            "shell_probe": shell_probe,
            "ocr_count": len(ocr_items),
            "ocr_texts": [item.get("text") for item in ocr_items[:20]],
        }
    if len(ocr_items) <= 0:
        return {
            "ok": False,
            "error_code": "WECHAT_RENDER_NOT_READY",
            "state": "wechat_render_not_ready",
            "stage": stage,
            "reason": "empty_ocr_surface",
            "render_probe": blank_render,
            "shell_probe": shell_probe,
            "ocr_count": len(ocr_items),
            "ocr_texts": [],
        }
    main_surface = add_friend_main_entry_surface_evidence(ocr_items, screenshot_size)
    main_surface_required = stage == "calibration" if require_main_surface is None else bool(require_main_surface)
    if main_surface_required and not main_surface.get("ok"):
        return {
            "ok": False,
            "error_code": ERROR_WECHAT_WINDOW_NOT_READY,
            "state": "wechat_main_surface_not_ready",
            "stage": stage,
            "reason": str(main_surface.get("reason") or "add_friend_entry_surface_not_confirmed"),
            "main_surface": main_surface,
            "render_probe": blank_render,
            "shell_probe": shell_probe,
            "ocr_count": len(ocr_items),
            "ocr_texts": [item.get("text") for item in ocr_items[:20]],
        }
    return {
        "ok": True,
        "stage": stage,
        "main_surface": main_surface,
        "render_probe": blank_render,
        "shell_probe": shell_probe,
        "ocr_count": len(ocr_items),
    }


def add_friend_main_entry_surface_evidence(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> dict[str, Any]:
    search_anchor = find_sidebar_search_anchor_item(ocr_items, image_size)
    if search_anchor is not None:
        return {
            "ok": True,
            "reason": "sidebar_search_anchor_detected",
            "anchor": add_friend_item_snapshot(search_anchor, image_size),
        }
    text = add_friend_surface_text(ocr_items)
    compact = add_friend_ocr_compact(text)
    has_wechat_sidebar = any(token in compact for token in ("通讯录", "聊天", "文件传输助手", "微信团队"))
    has_browser_like_text = any(token.lower() in compact.lower() for token in ("127.0.0.1", "localhost", "github", "twitter", "provider", "http"))
    if has_wechat_sidebar and not has_browser_like_text:
        return {
            "ok": True,
            "reason": "wechat_sidebar_text_detected",
            "surface_text_sample": [item.get("text") for item in ocr_items[:12]],
        }
    return {
        "ok": False,
        "reason": "sidebar_search_anchor_missing_or_non_wechat_content",
        "browser_like_text": has_browser_like_text,
        "surface_text_sample": [item.get("text") for item in ocr_items[:12]],
    }


def add_friend_human_pause(min_ms: int, max_ms: int | None = None, *, reason: str = "") -> float:
    """Randomized add_friend pacing.

    The add_friend flow runs inside WeChat's sensitive contact-add surface.
    Keep mouse, keyboard and OCR phases strictly separated by visible human
    pauses so the flow does not look like a burst of synthetic operations.
    """
    checkpoint = add_friend_operator_guard_checkpoint(reason=f"pause:{reason or 'add_friend'}")
    multiplier = bounded_float(
        os.getenv("WECHAT_WIN32_OCR_ADD_FRIEND_HUMAN_PACE_MULTIPLIER"),
        default=1.0,
        minimum=0.6,
        maximum=4.0,
    )
    low = int(max(0, int(min_ms)) * multiplier)
    high_source = int(max_ms) if max_ms is not None else int(min_ms * 1.45)
    high = int(max(low, high_source * multiplier))
    delay = humanized_action_sleep(low, high)
    record_ui_action(
        "add_friend_human_pause",
        metadata={
            "reason": reason,
            "min_ms": low,
            "max_ms": high,
            "delay_seconds": delay,
            "pace_multiplier": multiplier,
            "operator_guard_checkpoint": checkpoint,
        },
    )
    return delay


def add_friend_paced_pause(tier: str, *, reason: str = "") -> float:
    low, high = pacing_range(tier)
    metadata = pacing_metadata(tier, reason=reason)
    if high <= 0:
        record_ui_action("add_friend_pacing_skip", metadata=metadata)
        return 0.0
    delay = add_friend_human_pause(low, high, reason=f"{metadata['tier']}:{reason}")
    record_ui_action(
        "add_friend_pacing_tier",
        metadata={
            **metadata,
            "delay_seconds": delay,
        },
    )
    return delay


def click_add_friend_ocr_item(hwnd: int, item: dict[str, Any]) -> None:
    x, y = add_friend_item_center(item)
    add_friend_human_pause(650, 1450, reason="before_mouse_click")
    human_window_image_click(hwnd, x, y)
    add_friend_human_pause(900, 1900, reason="after_mouse_click")


def add_friend_wait_before_ocr(reason: str) -> None:
    add_friend_human_pause(1200, 2600, reason=reason)


def clear_add_friend_sidebar_search_box(
    hwnd: int,
    search_x: int,
    search_y: int,
    *,
    target_hint: str = "",
) -> None:
    """Clear the WeChat sidebar search box with slow serialized key actions."""
    add_friend_human_pause(700, 1600, reason="before_search_clear_escape")
    key_press(win32con.VK_ESCAPE)
    add_friend_human_pause(900, 1800, reason="after_escape_before_search_click")
    human_window_image_click(hwnd, search_x, search_y)
    add_friend_human_pause(900, 1900, reason="after_search_click_before_clear_keys")
    # Default to a minimal clear. In clean main-list state ESC + focus click is
    # enough; long Backspace/Delete bursts are a known anti-automation risk.
    default_backspaces = random.randint(1, 3)
    backspaces = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_ADD_FRIEND_CLEAR_BACKSPACES"),
        default=default_backspaces,
        minimum=0,
        maximum=12,
    )
    deletes = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_ADD_FRIEND_CLEAR_DELETES"),
        default=0,
        minimum=0,
        maximum=4,
    )
    for idx in range(backspaces):
        key_press(win32con.VK_BACK)
        add_friend_human_pause(120, 420, reason=f"clear_backspace_{idx + 1}")
    for idx in range(deletes):
        key_press(win32con.VK_DELETE)
        add_friend_human_pause(150, 460, reason=f"clear_delete_{idx + 1}")
    add_friend_human_pause(700, 1500, reason="after_search_clear_keys")


def add_friend_virtual_key_for_digit(char: str) -> int:
    if not re.fullmatch(r"\d", str(char or "")):
        raise ValueError(f"not_a_digit:{char!r}")
    return ord(str(char))


def type_add_friend_phone_query_like_human(
    hwnd: int,
    query: str,
    *,
    key_press_func: Any | None = None,
    window_guard_func: Any | None = None,
) -> dict[str, Any]:
    """Type a phone query as visible one-by-one key presses.

    This intentionally avoids SendInput Unicode batches and clipboard paste.
    The contact search surface is sensitive; each digit is separated by a
    random pause and periodic longer hesitation.
    """
    clean = re.sub(r"\D+", "", str(query or ""))
    if not clean:
        return {"ok": False, "method": "add_friend_digit_keys", "reason": "empty_phone_query"}
    press = key_press_func or key_press
    typed = 0
    pause_after = random.randint(3, 5)
    try:
        for index, char in enumerate(clean, start=1):
            if window_guard_func is not None:
                guard = window_guard_func()
                if not guard.get("ok"):
                    return {
                        "ok": False,
                        "method": "add_friend_digit_keys",
                        "reason": "window_lost_during_digit_input",
                        "window_guard": guard,
                        "typed_chars": typed,
                    }
            add_friend_human_pause(420, 1300, reason=f"before_digit_{index}")
            press(add_friend_virtual_key_for_digit(char))
            typed += 1
            add_friend_human_pause(520, 1500, reason=f"after_digit_{index}")
            if index >= pause_after and index < len(clean):
                add_friend_human_pause(1200, 2800, reason=f"digit_group_pause_{index}")
                pause_after += random.randint(3, 5)
    except Exception as exc:
        return {
            "ok": False,
            "method": "add_friend_digit_keys",
            "error": repr(exc),
            "typed_chars": typed,
        }
    return {"ok": True, "method": "add_friend_digit_keys", "typed_chars": typed}


def type_add_friend_search_query(hwnd: int, query: str) -> dict[str, Any]:
    if re.fullmatch(r"\d{5,20}", str(query or "")):
        return type_add_friend_phone_query_like_human(
            hwnd,
            query,
            window_guard_func=lambda: basic_send_window_guard(hwnd),
        )
    if not env_flag("WECHAT_WIN32_OCR_ADD_FRIEND_ALLOW_SENDINPUT_QUERY", default=False):
        return {
            "ok": False,
            "method": "add_friend_query_blocked",
            "reason": "non_numeric_query_requires_explicit_sendinput_opt_in",
        }
    add_friend_human_pause(900, 1800, reason="before_non_numeric_sendinput_query")
    result = type_sidebar_search_query(hwnd, query)
    add_friend_human_pause(1000, 2200, reason="after_non_numeric_sendinput_query")
    return result


def add_friend_optional_field_fill_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_ADD_FRIEND_FILL_OPTIONAL_FIELDS", default=False)


def paste_add_friend_text_at_item(
    hwnd: int,
    item: dict[str, Any],
    text: str,
    image_size: tuple[int, int],
    *,
    x_offset: int = 150,
) -> dict[str, Any]:
    if not add_friend_optional_field_fill_enabled():
        return {"ok": True, "skipped": True, "reason": "optional_field_fill_disabled_by_default"}
    clean = str(text or "")
    if not clean:
        return {"ok": True, "skipped": True, "reason": "empty_text"}
    width, _height = image_size
    base_x, base_y = add_friend_item_center(item)
    click_x = bounded_int(base_x + x_offset, default=base_x + x_offset, minimum=base_x + 20, maximum=max(base_x + 20, width - 42))
    click_y = base_y
    add_friend_human_pause(700, 1600, reason="before_field_click")
    human_window_image_click(hwnd, click_x, click_y)
    add_friend_human_pause(850, 1800, reason="after_field_click_before_keyboard")
    hotkey(win32con.VK_CONTROL, ord("A"))
    add_friend_human_pause(420, 1050, reason="after_select_all")
    clipboard_copy(clean)
    add_friend_human_pause(380, 980, reason="after_clipboard_copy")
    hotkey(win32con.VK_CONTROL, ord("V"))
    add_friend_human_pause(900, 1900, reason="after_clipboard_paste")
    return {"ok": True, "method": "clipboard_paste", "x": click_x, "y": click_y, "length": len(clean)}


def fill_add_friend_optional_fields(
    hwnd: int,
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    remark: str,
    greeting: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": True, "greeting": {"skipped": True}, "remark": {"skipped": True}}
    greeting_item = find_add_friend_action_item(ocr_items, ("发送添加朋友申请", "朋友验证", "申请添加朋友"), image_size, min_y_ratio=0.08, max_y_ratio=0.65)
    if greeting and greeting_item is not None:
        result["greeting"] = paste_add_friend_text_at_item(hwnd, greeting_item, greeting, image_size, x_offset=190)
    remark_item = find_add_friend_action_item(ocr_items, ("备注名", "备注"), image_size, min_y_ratio=0.15, max_y_ratio=0.80)
    if remark and remark_item is not None:
        result["remark"] = paste_add_friend_text_at_item(hwnd, remark_item, remark, image_size, x_offset=160)
    return result


def message_anchor_match_type(
    message: dict[str, Any],
    *,
    anchor_ids: set[str],
    anchor_content_keys: set[str],
    reply_content_keys: set[str],
) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id and message_id in anchor_ids:
        return "message_id"
    content_key = sidecar_message_content_key(message)
    if content_key and content_key in anchor_content_keys:
        return "message_content_key"
    reply_key = normalize_anchor_reply_key(message.get("content"))
    if reply_key and reply_key in reply_content_keys:
        return "reply_content_key"
    return ""


def send_payload(
    hwnd: int,
    probe: dict[str, Any],
    *,
    target: str,
    text: str,
    exact: bool,
    skip_send_rate_guard: bool = False,
    artifact_dir: str | None = None,
    validated_guard: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reused_prevalidated_guard = bool(isinstance(validated_guard, dict) and validated_guard.get("ok"))
    if reused_prevalidated_guard:
        validation = dict(validated_guard or {})
        # Re-check foreground/visibility quickly before using the cached target
        # confirmation, then re-run strict OCR target validation immediately
        # before typing.  Cached confirmation can become stale when the
        # scheduler switches between multiple chats; never let it authorize
        # customer-visible text by itself.
        focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
        if not focus_guard.get("ok"):
            # Fallback to full active target validation to keep behavior robust
            # when foreground recovery is temporarily blocked.
            validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
            reused_prevalidated_guard = False
            if not validation.get("ok"):
                return {
                    "ok": False,
                    "online": bool(validation.get("online", True)),
                    "adapter": "win32_ocr",
                    "state": "send_guard_blocked",
                    "window_probe": probe,
                    "target": target,
                    "guard": {**validation, "window_guard": focus_guard},
                    "error": str(validation.get("error") or validation.get("reason") or "send guard blocked"),
                }
            geometry = validation["geometry"]
        else:
            strict_validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
            if not strict_validation.get("ok") or not active_send_guard_is_strong(strict_validation):
                return {
                    "ok": False,
                    "online": bool(strict_validation.get("online", True)),
                    "adapter": "win32_ocr",
                    "state": "send_guard_blocked",
                    "window_probe": probe,
                    "target": target,
                    "guard": {
                        **strict_validation,
                        "cached_prevalidated_guard": validation,
                        "window_guard": focus_guard,
                        "strict_recheck": True,
                    },
                    "error": str(strict_validation.get("error") or strict_validation.get("reason") or "send guard blocked"),
                }
            validation = {
                **strict_validation,
                "cached_prevalidated_guard": validation,
                "window_guard": focus_guard,
                "strict_recheck": True,
            }
            geometry = get_window_geometry(hwnd)
            geometry_check = validate_send_geometry(geometry)
            if not geometry_check.get("ok"):
                return {
                    "ok": False,
                    "online": True,
                    "adapter": "win32_ocr",
                    "state": "send_geometry_blocked",
                    "window_probe": probe,
                    "target": target,
                    "guard": {**validation, "geometry": geometry, "geometry_check": geometry_check},
                    "error": str(geometry_check.get("error") or "send geometry guard blocked"),
                }
            validation["geometry"] = geometry
    else:
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if not validation.get("ok") or not active_send_guard_is_strong(validation):
            return {
                "ok": False,
                "online": validation.get("online", True),
                "adapter": "win32_ocr",
                "state": "send_guard_blocked",
                "window_probe": probe,
                "target": target,
                "guard": validation,
                "error": str(validation.get("error") or validation.get("reason") or "send guard blocked"),
            }
        geometry = validation["geometry"]
    points = calculate_send_points(geometry)
    if not points.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "send_geometry_blocked",
            "window_probe": probe,
            "target": target,
            "guard": {**validation, "points": points},
            "error": str(points.get("error") or "send points were unsafe"),
        }
    requested_send_mode = str(os.getenv("WECHAT_WIN32_OCR_SEND_MODE") or DEFAULT_SEND_MODE).strip().lower()
    settings = adapt_humanized_input_settings(humanized_input_settings(), text)
    send_mode = requested_send_mode
    # When intermittent typing is enforced, keep send path on guarded-click flow
    # so we never downgrade to one-shot UIA SetValue in practice.
    if (
        settings.get("enabled")
        and str(settings.get("method") or "") in {"clipboard_chunks", "sendinput_unicode"}
        and requested_send_mode in {"uia_first", "uia_only"}
    ):
        send_mode = "click_only"
    if skip_send_rate_guard:
        rate = {
            "ok": True,
            "reason": "rate_guard_skipped_for_loopback",
            "skip_send_rate_guard": True,
        }
    else:
        rate = reserve_send_rate(target=target, text=text)
    if not rate.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "send_rate_limited",
            "window_probe": probe,
            "target": target,
            "guard": {**validation, "points": points, "rate": rate},
            "error": str(rate.get("error") or "win32_ocr fallback send is rate limited"),
        }
    uia_result = {"ok": False, "reason": "not_attempted", "mode": send_mode}
    click_result: dict[str, Any] = {"ok": False, "reason": "not_attempted", "mode": send_mode}
    if send_mode in {"uia_first", "uia_only"}:
        uia_result = send_with_uia_controls(hwnd, text, geometry=geometry, settings=settings)
    if not uia_result.get("ok"):
        if send_mode == "uia_only":
            return {
                "ok": False,
                "online": True,
                "adapter": "win32_ocr",
                "state": "send_uia_unavailable",
                "window_probe": probe,
                "target": target,
                "guard": {**validation, "points": points, "rate": rate, "uia": uia_result},
                "error": str(uia_result.get("error") or "UIA controls are unavailable for safe send."),
            }
        click_result = send_with_guarded_clicks(
            hwnd,
            text,
            points=points,
            geometry=geometry,
            allow_unconfirmed_paste=bool(validation.get("blind_send")),
            artifact_dir=artifact_dir,
            settings=settings,
        )
    if not uia_result.get("ok") and not click_result.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "send_input_not_ready",
            "window_probe": probe,
            "target": target,
            "guard": {
                **validation,
                "points": points,
                "rate": rate,
                "uia": uia_result,
                "click": click_result,
            },
            "error": str(click_result.get("error") or uia_result.get("error") or "send input could not be confirmed"),
        }
    humanized_action_sleep(200, 420)
    post_validation = validate_post_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
    if str(post_validation.get("reason") or "") == "blank_render":
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "send_post_guard_blank_render",
            "window_probe": probe,
            "target": target,
            "guard": {
                **validation,
                "points": points,
                "rate": rate,
                "uia": uia_result,
                "click": click_result,
                "post_send_guard": post_validation,
            },
            "error": "WeChat render became blank after input/send; stop before any further RPA action.",
        }
    active_result = uia_result if uia_result.get("ok") else click_result
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "send_win32_rpa",
        "window_probe": probe,
        "target": target,
        "send_result": {
            "ok": bool(active_result.get("ok")),
            "method": active_result.get("method") or "win32.click_input+rpa_text_entry+click_send",
            "mode": send_mode,
            "requested_mode": requested_send_mode,
            "humanized_method": settings.get("method"),
            "validation_source": "prevalidated_guard_strict_recheck" if reused_prevalidated_guard else "active_send_guard",
            "pre_send_guard": validation,
            "geometry": geometry,
            "input_point": points["input_point"],
            "send_point": points["send_point"],
            "rate": rate,
            "uia": uia_result,
            "click": click_result,
            "post_send_guard": post_validation,
        },
    }


def normalize_humanized_input_method(raw_method: str | None, *, default: str = DEFAULT_HUMANIZED_INPUT_METHOD) -> str:
    method = str(raw_method or default).strip().lower()
    if method not in {"auto", "sendinput_unicode", "uia_chunks", "clipboard_chunks", "clipboard_once"}:
        method = default
    enforce_intermittent = env_flag(
        "WECHAT_WIN32_OCR_ENFORCE_INTERMITTENT_TYPING",
        default=DEFAULT_HUMANIZED_INPUT_ENFORCE_INTERMITTENT,
    )
    allow_clipboard_once = env_flag(
        "WECHAT_WIN32_OCR_ALLOW_CLIPBOARD_ONCE",
        default=DEFAULT_HUMANIZED_ALLOW_CLIPBOARD_ONCE,
    )
    if enforce_intermittent and method == "clipboard_once" and not allow_clipboard_once:
        return "clipboard_chunks"
    return method


def normalize_send_trigger_mode(raw_mode: str | None, *, default: str = DEFAULT_SEND_TRIGGER_MODE) -> str:
    mode = str(raw_mode or default).strip().lower()
    if mode not in {"click_only", "enter_only", "enter_then_click"}:
        return default
    if mode == "enter_then_click":
        # Dual triggering is too easy to classify as mechanical, and can also
        # double-send when WeChat is slow. Keep the trigger single-path.
        return "enter_only"
    if mode == "click_only" and not env_flag("WECHAT_WIN32_OCR_ALLOW_CLICK_SEND_TRIGGER", default=False):
        return "enter_only"
    return mode


def humanized_input_settings() -> dict[str, Any]:
    enabled = env_flag("WECHAT_WIN32_OCR_HUMANIZED_INPUT_ENABLED", default=DEFAULT_HUMANIZED_INPUT_ENABLED)
    method = normalize_humanized_input_method(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_INPUT_METHOD", DEFAULT_HUMANIZED_INPUT_METHOD),
        default=DEFAULT_HUMANIZED_INPUT_METHOD,
    )
    chunk_min = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MIN_CHARS"),
        default=DEFAULT_HUMANIZED_TYPING_CHUNK_MIN_CHARS,
        minimum=1,
        maximum=24,
    )
    chunk_max = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHUNK_MAX_CHARS"),
        default=DEFAULT_HUMANIZED_TYPING_CHUNK_MAX_CHARS,
        minimum=chunk_min,
        maximum=36,
    )
    char_delay_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS"),
        default=DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS,
        minimum=0,
        maximum=1200,
    )
    char_delay_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS"),
        default=DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS,
        minimum=char_delay_min_ms,
        maximum=1600,
    )
    micro_pause_every_chars = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_EVERY_CHARS"),
        default=DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_EVERY_CHARS,
        minimum=0,
        maximum=300,
    )
    micro_pause_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS"),
        default=DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS,
        minimum=0,
        maximum=5000,
    )
    micro_pause_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS"),
        default=DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS,
        minimum=micro_pause_min_ms,
        maximum=7000,
    )
    typo_probability = max(
        0.0,
        min(
            1.0,
            env_float(
                "WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_PROBABILITY",
                default=DEFAULT_HUMANIZED_TYPING_TYPO_PROBABILITY,
            ),
        ),
    )
    typo_max = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_TYPING_TYPO_MAX"),
        default=DEFAULT_HUMANIZED_TYPING_TYPO_MAX,
        minimum=0,
        maximum=6,
    )
    pre_delay_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_PRE_DELAY_MIN_MS"),
        default=DEFAULT_HUMANIZED_SEND_PRE_DELAY_MIN_MS,
        minimum=0,
        maximum=6000,
    )
    pre_delay_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_PRE_DELAY_MAX_MS"),
        default=DEFAULT_HUMANIZED_SEND_PRE_DELAY_MAX_MS,
        minimum=pre_delay_min_ms,
        maximum=8000,
    )
    post_delay_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS"),
        default=DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS,
        minimum=0,
        maximum=4000,
    )
    post_delay_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS"),
        default=DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS,
        minimum=post_delay_min_ms,
        maximum=6000,
    )
    trigger_delay_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_TRIGGER_DELAY_MIN_MS"),
        default=DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MIN_MS,
        minimum=0,
        maximum=6000,
    )
    trigger_delay_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_TRIGGER_DELAY_MAX_MS"),
        default=DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MAX_MS,
        minimum=trigger_delay_min_ms,
        maximum=8000,
    )
    after_trigger_delay_min_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MIN_MS"),
        default=DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MIN_MS,
        minimum=0,
        maximum=4000,
    )
    after_trigger_delay_max_ms = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MAX_MS"),
        default=DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MAX_MS,
        minimum=after_trigger_delay_min_ms,
        maximum=6000,
    )
    inter_chunk_delay_scale = max(
        0.35,
        min(
            1.2,
            env_float("WECHAT_WIN32_OCR_HUMANIZED_INTER_CHUNK_DELAY_SCALE", default=1.0),
        ),
    )
    return {
        "enabled": enabled,
        "method": method,
        "chunk_min_chars": chunk_min,
        "chunk_max_chars": chunk_max,
        "char_delay_min_ms": char_delay_min_ms,
        "char_delay_max_ms": char_delay_max_ms,
        "micro_pause_every_chars": micro_pause_every_chars,
        "micro_pause_min_ms": micro_pause_min_ms,
        "micro_pause_max_ms": micro_pause_max_ms,
        "typo_probability": typo_probability,
        "typo_max": typo_max,
        "send_pre_delay_min_ms": pre_delay_min_ms,
        "send_pre_delay_max_ms": pre_delay_max_ms,
        "send_post_input_delay_min_ms": post_delay_min_ms,
        "send_post_input_delay_max_ms": post_delay_max_ms,
        "send_trigger_delay_min_ms": trigger_delay_min_ms,
        "send_trigger_delay_max_ms": trigger_delay_max_ms,
        "send_after_trigger_delay_min_ms": after_trigger_delay_min_ms,
        "send_after_trigger_delay_max_ms": after_trigger_delay_max_ms,
        "inter_chunk_delay_scale": inter_chunk_delay_scale,
        "adaptive_speed_enabled": env_flag(
            "WECHAT_WIN32_OCR_HUMANIZED_ADAPTIVE_SPEED_ENABLED",
            default=DEFAULT_HUMANIZED_ADAPTIVE_SPEED_ENABLED,
        ),
    }


def adapt_humanized_input_settings(settings: dict[str, Any], text: str) -> dict[str, Any]:
    """Adapt typing pace by reply length without becoming superhuman fast."""
    active = dict(settings or {})
    if not active.get("enabled") or not active.get("adaptive_speed_enabled", True):
        return active
    text_len = len(sendinput_safe_text(text))
    if text_len <= DEFAULT_HUMANIZED_SHORT_TEXT_CHARS:
        profile = {
            "speed_profile": "short_natural",
            "chunk_min_chars": 4,
            "chunk_max_chars": 10,
            "char_delay_min_ms": 45,
            "char_delay_max_ms": 95,
            "micro_pause_every_chars": 34,
            "micro_pause_min_ms": 90,
            "micro_pause_max_ms": 260,
            "typo_probability": 0.10,
            "typo_max": 1,
            "send_pre_delay_min_ms": 120,
            "send_pre_delay_max_ms": 360,
            "send_post_input_delay_min_ms": 180,
            "send_post_input_delay_max_ms": 360,
            "send_trigger_delay_min_ms": 520,
            "send_trigger_delay_max_ms": 1500,
            "send_after_trigger_delay_min_ms": 260,
            "send_after_trigger_delay_max_ms": 820,
            "inter_chunk_delay_scale": 0.58,
        }
    elif text_len <= DEFAULT_HUMANIZED_LONG_TEXT_CHARS:
        profile = {
            "speed_profile": "medium_natural",
            "chunk_min_chars": 4,
            "chunk_max_chars": 10,
            "char_delay_min_ms": 42,
            "char_delay_max_ms": 88,
            "micro_pause_every_chars": 38,
            "micro_pause_min_ms": 85,
            "micro_pause_max_ms": 240,
            "typo_probability": 0.08,
            "typo_max": 1,
            "send_pre_delay_min_ms": 110,
            "send_pre_delay_max_ms": 320,
            "send_post_input_delay_min_ms": 160,
            "send_post_input_delay_max_ms": 340,
            "send_trigger_delay_min_ms": 560,
            "send_trigger_delay_max_ms": 1650,
            "send_after_trigger_delay_min_ms": 280,
            "send_after_trigger_delay_max_ms": 880,
            "inter_chunk_delay_scale": 0.62,
        }
    else:
        profile = {
            "speed_profile": "long_natural_capped",
            "chunk_min_chars": 5,
            "chunk_max_chars": 11,
            "char_delay_min_ms": 32,
            "char_delay_max_ms": 78,
            "micro_pause_every_chars": 44,
            "micro_pause_min_ms": 70,
            "micro_pause_max_ms": 220,
            "typo_probability": 0.06,
            "typo_max": 1,
            "send_pre_delay_min_ms": 100,
            "send_pre_delay_max_ms": 280,
            "send_post_input_delay_min_ms": 150,
            "send_post_input_delay_max_ms": 320,
            "send_trigger_delay_min_ms": 680,
            "send_trigger_delay_max_ms": 2200,
            "send_after_trigger_delay_min_ms": 320,
            "send_after_trigger_delay_max_ms": 1100,
            "inter_chunk_delay_scale": 0.68,
        }
    active["speed_profile"] = profile["speed_profile"]
    for key in (
        "char_delay_min_ms",
        "char_delay_max_ms",
        "micro_pause_min_ms",
        "micro_pause_max_ms",
        "send_pre_delay_min_ms",
        "send_pre_delay_max_ms",
        "send_post_input_delay_min_ms",
        "send_post_input_delay_max_ms",
        "send_trigger_delay_min_ms",
        "send_trigger_delay_max_ms",
        "send_after_trigger_delay_min_ms",
        "send_after_trigger_delay_max_ms",
    ):
        current = int(active.get(key) or 0)
        target = int(profile[key])
        if key.startswith("send_trigger") or key.startswith("send_after_trigger"):
            active[key] = max(current, target)
        else:
            active[key] = 0 if current <= 0 else min(current, target)
    active["chunk_min_chars"] = max(int(active.get("chunk_min_chars") or 1), int(profile["chunk_min_chars"]))
    active["chunk_max_chars"] = max(int(active.get("chunk_max_chars") or 1), int(profile["chunk_max_chars"]))
    current_micro_every = int(active.get("micro_pause_every_chars") or 0)
    active["micro_pause_every_chars"] = (
        max(current_micro_every, int(profile["micro_pause_every_chars"])) if current_micro_every > 0 else 0
    )
    if active["chunk_max_chars"] < active["chunk_min_chars"]:
        active["chunk_max_chars"] = active["chunk_min_chars"]
    if int(active.get("char_delay_max_ms") or 0) < int(active.get("char_delay_min_ms") or 0):
        active["char_delay_max_ms"] = active["char_delay_min_ms"]
    if int(active.get("micro_pause_max_ms") or 0) < int(active.get("micro_pause_min_ms") or 0):
        active["micro_pause_max_ms"] = active["micro_pause_min_ms"]
    if int(active.get("send_trigger_delay_max_ms") or 0) < int(active.get("send_trigger_delay_min_ms") or 0):
        active["send_trigger_delay_max_ms"] = active["send_trigger_delay_min_ms"]
    if int(active.get("send_after_trigger_delay_max_ms") or 0) < int(active.get("send_after_trigger_delay_min_ms") or 0):
        active["send_after_trigger_delay_max_ms"] = active["send_after_trigger_delay_min_ms"]
    active["typo_probability"] = min(float(active.get("typo_probability") or 0.0), float(profile["typo_probability"]))
    active["typo_max"] = min(int(active.get("typo_max") or 0), int(profile["typo_max"]))
    try:
        current_scale = float(active.get("inter_chunk_delay_scale") or 1.0)
    except (TypeError, ValueError):
        current_scale = 1.0
    active["inter_chunk_delay_scale"] = max(
        0.35,
        min(
            1.2,
            min(current_scale, float(profile["inter_chunk_delay_scale"])),
        ),
    )
    active["adaptive_text_chars"] = text_len
    return active


def humanized_sleep_ms(min_ms: int, max_ms: int) -> float:
    low = max(0, int(min_ms))
    high = max(low, int(max_ms))
    if high <= 0:
        return 0.0
    delay = random.uniform(float(low) / 1000.0, float(high) / 1000.0)
    time.sleep(delay)
    return round(delay, 3)


def humanized_action_sleep(min_ms: int, max_ms: int | None = None) -> float:
    """Small randomized settle time for RPA UI actions."""
    low = max(0, int(min_ms))
    if max_ms is None:
        spread = max(8, int(low * 0.25))
        high = low + spread
        low = max(0, low - spread)
    else:
        high = max(low, int(max_ms))
    return humanized_sleep_ms(low, high)


def humanized_chunk_text(text: str, *, min_chars: int, max_chars: int) -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    chunks: list[str] = []
    cursor = 0
    lower = max(1, int(min_chars))
    upper = max(lower, int(max_chars))
    while cursor < len(clean):
        step = random.randint(lower, upper)
        next_cursor = min(len(clean), cursor + step)
        chunks.append(clean[cursor:next_cursor])
        cursor = next_cursor
    return chunks


def choose_humanized_typo_char() -> str:
    return random.choice(HUMANIZED_TYPO_CANDIDATES)


def typed_text_delay_ms(segment: str, settings: dict[str, Any]) -> tuple[int, int]:
    char_count = max(1, len(str(segment or "")))
    per_char_low = int(settings.get("char_delay_min_ms") or DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MIN_MS)
    per_char_high = int(settings.get("char_delay_max_ms") or DEFAULT_HUMANIZED_TYPING_CHAR_DELAY_MAX_MS)
    low = max(0, per_char_low * char_count)
    high = max(low, per_char_high * char_count)
    try:
        delay_scale = float(settings.get("inter_chunk_delay_scale") or 1.0)
    except (TypeError, ValueError):
        delay_scale = 1.0
    delay_scale = max(0.35, min(1.2, delay_scale))
    if abs(delay_scale - 1.0) > 1e-6:
        low = max(0, int(round(low * delay_scale)))
        high = max(low, int(round(high * delay_scale)))
    return low, high


def maybe_humanized_typo_allowed(settings: dict[str, Any], *, typo_count: int, text: str) -> bool:
    if typo_count >= int(settings.get("typo_max") or 0):
        return False
    if len(str(text or "")) < 6:
        return False
    probability = float(settings.get("typo_probability") or 0.0)
    return random.random() < max(0.0, min(1.0, probability))


def message_probe_tokens(text: str) -> list[str]:
    first_line = str(text or "").splitlines()[0].strip()
    if not first_line:
        return []
    compact = re.sub(r"\s+", "", first_line)
    if not compact:
        return []
    tokens: list[str] = []

    def add_token(candidate: str) -> None:
        token = str(candidate or "").strip()
        if len(token) < 2:
            return
        if token not in tokens:
            tokens.append(token)

    semantic = compact
    # Live acceptance/customer-service messages often carry a bracketed marker
    # before the real customer text. OCR may split or drop that marker, so use
    # semantic body fragments first and keep the old prefix/suffix fallback.
    for _ in range(3):
        stripped = re.sub(r"^(?:【[^】]{1,80}】|\[[^\]]{1,80}\]|（[^）]{1,80}）|\([^)]{1,80}\))", "", semantic)
        if stripped == semantic:
            break
        semantic = stripped
    semantic = semantic.lstrip("：:，,。；;、 ")

    semantic_spans = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{3,18}", semantic)
    for span in semantic_spans:
        if not re.search(r"[\u4e00-\u9fff]", span):
            continue
        variants = [span]
        if len(span) >= 4 and span[0] in {"我", "想", "要", "请"}:
            variants.append(span[1:])
        for variant in variants:
            add_token(variant[:10])
            add_token(variant[:6])
            add_token(variant[-6:])
            if len(tokens) >= 8:
                break
        if len(tokens) >= 8:
            break

    for candidate in (compact[:10], compact[:6], compact[-6:]):
        add_token(candidate)
    return tokens


def message_probe_token(text: str) -> str:
    tokens = message_probe_tokens(text)
    return tokens[0] if tokens else ""


def input_area_contains_token(
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any],
    token: str,
) -> bool:
    if not token:
        return False
    normalized_token = re.sub(r"\s+", "", token)
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        rect = {
            "left": int(float(item.get("left") or 0)),
            "top": int(float(item.get("top") or 0)),
            "right": int(float(item.get("right") or 0)),
            "bottom": int(float(item.get("bottom") or 0)),
        }
        if not rect_in_input_area(rect, geometry):
            continue
        compact = re.sub(r"\s+", "", text)
        if normalized_token in compact or compact in normalized_token:
            return True
    return False


def input_area_contains_any_token(
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any],
    tokens: list[str],
) -> bool:
    for token in tokens:
        if input_area_contains_token(ocr_items, geometry=geometry, token=token):
            return True
    return False


def input_text_region_bounds(geometry: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    left = max(session_split_x(width) + 24, int(width * 0.36))
    top = max(int(height * 0.79), height - 180)
    right = max(left + 20, width - 95)
    bottom = min(height - 58, height)
    if bottom <= top:
        top = max(0, int(height * 0.84))
        bottom = max(top + 1, height - 58)
    return (left, top, right, bottom)


def rect_overlaps_region(rect: dict[str, int], bounds: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = bounds
    return int(rect.get("right") or 0) > left and int(rect.get("left") or 0) < right and int(rect.get("bottom") or 0) > top and int(rect.get("top") or 0) < bottom


def input_text_region_state(
    screenshot: Any,
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any],
) -> dict[str, Any]:
    """Detect whether the input text area visibly contains text.

    This is deliberately conservative: if text-like pixels are present but OCR
    missed the probe token, we stop instead of retrying and risking a duplicate.
    """
    bounds = input_text_region_bounds(geometry)
    ocr_hits = 0
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        rect = {
            "left": int(float(item.get("left") or 0)),
            "top": int(float(item.get("top") or 0)),
            "right": int(float(item.get("right") or 0)),
            "bottom": int(float(item.get("bottom") or 0)),
        }
        if rect_overlaps_region(rect, bounds):
            ocr_hits += 1
    try:
        gray = screenshot.convert("L")
        crop = gray.crop(bounds)
        histogram = crop.histogram()
        total = max(1, int(sum(histogram)))
        dark_ratio = float(sum(histogram[:180])) / float(total)
        bright_ratio = float(sum(histogram[200:])) / float(total)
        mean = float(sum(index * count for index, count in enumerate(histogram))) / float(total)
    except Exception as exc:
        return {
            "has_visible_text": bool(ocr_hits),
            "reason": "input_region_probe_failed",
            "error": repr(exc),
            "bounds": list(bounds),
            "ocr_hits": ocr_hits,
        }
    # In dark-mode WeChat the whole input region can be dark even when blank.
    # Treat a uniformly dark crop without OCR or bright text strokes as blank;
    # otherwise the send guard will repeatedly refuse to type into an empty box.
    dark_theme_blank_like = bool(
        dark_ratio >= 0.90
        and mean <= 90.0
        and bright_ratio <= 0.002
    )
    pixel_visible = dark_ratio >= INPUT_TEXT_DARK_RATIO_MIN and not dark_theme_blank_like
    # OCR boxes can drift into the lower chat/input boundary on fresh captures.
    # Treat OCR as draft evidence only when the crop is not a uniformly dark
    # blank input box; otherwise dark-mode backgrounds with boundary OCR noise
    # block safe typing in an empty box.
    ocr_visible = bool(ocr_hits > 0 and not dark_theme_blank_like and dark_ratio >= INPUT_TEXT_DARK_RATIO_MIN / 3.0)
    has_visible_text = bool(pixel_visible or ocr_visible)
    return {
        "has_visible_text": has_visible_text,
        "reason": "ocr_or_dark_pixels" if has_visible_text else "input_region_blank",
        "bounds": list(bounds),
        "ocr_hits": ocr_hits,
        "dark_ratio": round(dark_ratio, 6),
        "bright_ratio": round(bright_ratio, 6),
        "mean": round(mean, 3),
        "threshold": INPUT_TEXT_DARK_RATIO_MIN,
        "dark_theme_blank_like": dark_theme_blank_like,
    }


def input_region_visual_delta_confirms(
    before: dict[str, Any],
    after: dict[str, Any],
    input_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Confirm typed input by a conservative before/after visual delta."""
    if not input_result or not input_result.get("ok"):
        return {"ok": False, "reason": "input_operation_failed"}
    try:
        typed_chars = int(input_result.get("typed_chars") or 0)
    except Exception:
        typed_chars = 0
    method = str(input_result.get("method") or "")
    if typed_chars <= 0 and method not in {"clipboard_once", "clipboard_chunks"}:
        return {"ok": False, "reason": "no_typed_chars"}
    if bool(before.get("has_visible_text")):
        return {"ok": False, "reason": "input_region_not_blank_before_type"}
    if not bool(after.get("has_visible_text")):
        return {"ok": False, "reason": "input_region_still_blank_after_type"}
    try:
        before_dark = float(before.get("dark_ratio") or 0.0)
        after_dark = float(after.get("dark_ratio") or 0.0)
    except Exception:
        before_dark = 0.0
        after_dark = 0.0
    before_hits = int(before.get("ocr_hits") or 0)
    after_hits = int(after.get("ocr_hits") or 0)
    dark_delta = after_dark - before_dark
    min_delta = max(INPUT_TEXT_DARK_RATIO_MIN * 2.0, 0.006)
    if after_hits > before_hits or dark_delta >= min_delta:
        return {
            "ok": True,
            "reason": "input_area_visual_delta",
            "before": before,
            "after": after,
            "dark_delta": round(dark_delta, 6),
            "ocr_hit_delta": after_hits - before_hits,
        }
    return {
        "ok": False,
        "reason": "input_area_delta_too_small",
        "before": before,
        "after": after,
        "dark_delta": round(dark_delta, 6),
        "ocr_hit_delta": after_hits - before_hits,
    }


def input_region_soft_blank_noise(state: dict[str, Any]) -> bool:
    """Return True when a draft probe is likely toolbar/shadow noise, not text."""
    if not isinstance(state, dict):
        return False
    try:
        dark_ratio = float(state.get("dark_ratio") or 0.0)
    except Exception:
        dark_ratio = 0.0
    try:
        mean = float(state.get("mean") or 0.0)
    except Exception:
        mean = 0.0
    try:
        ocr_hits = int(state.get("ocr_hits") or 0)
    except Exception:
        ocr_hits = 0
    return bool(
        ocr_hits == 0
        and dark_ratio <= INPUT_TEXT_SOFT_BLANK_DARK_RATIO_MAX
        and mean >= INPUT_TEXT_SOFT_BLANK_MEAN_MIN
    )


def normalize_soft_blank_input_state(state: dict[str, Any], *, reason: str) -> dict[str, Any]:
    normalized = dict(state or {})
    normalized["has_visible_text"] = False
    normalized["reason"] = reason
    normalized["soft_blank_noise"] = True
    return normalized


def clear_existing_input_draft(
    hwnd: int,
    *,
    points: dict[str, Any],
    geometry: dict[str, Any],
    before_state: dict[str, Any],
    artifact_dir: str | None = None,
    attempt: int = 1,
) -> dict[str, Any]:
    """Clear a stale WeChat draft only when the input area is already non-empty."""
    if not before_state.get("has_visible_text"):
        return {"ok": True, "cleared": False, "reason": "input_region_already_blank", "before": before_state}
    if input_region_soft_blank_noise(before_state):
        blank = normalize_soft_blank_input_state(before_state, reason="input_region_soft_blank_noise")
        return {"ok": True, "cleared": False, "reason": "input_region_soft_blank_noise", "before": blank}
    input_x, input_y = jitter_input_click_point(
        int(points["input_point"][0]),
        int(points["input_point"][1]),
        geometry,
    )
    human_client_click(hwnd, input_x, input_y)
    time.sleep(random.uniform(0.08, 0.16))
    # Avoid Ctrl+A here: select-all artifacts can leak to chat history when
    # focus drifts. Use bounded backspace/delete bursts instead.
    key_press(win32con.VK_END)
    humanized_action_sleep(24, 70)
    backspaces = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_DRAFT_CLEAR_BACKSPACES"),
        default=96,
        minimum=24,
        maximum=160,
    )
    deletes = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_DRAFT_CLEAR_DELETES"),
        default=8,
        minimum=0,
        maximum=24,
    )
    for idx in range(backspaces):
        key_press(win32con.VK_BACK)
        humanized_action_sleep(8, 26)
        if idx > 0 and idx % 7 == 0:
            humanized_action_sleep(22, 66)
    for _ in range(deletes):
        key_press(win32con.VK_DELETE)
        humanized_action_sleep(10, 30)
    time.sleep(random.uniform(0.16, 0.32))
    screenshot, _path = capture_wechat(hwnd, artifact_dir=artifact_dir, label=f"send_input_clear_{attempt}")
    ocr_items = run_ocr(screenshot)
    after_state = input_text_region_state(screenshot, ocr_items, geometry=geometry)
    if not after_state.get("has_visible_text") or input_region_soft_blank_noise(after_state):
        if input_region_soft_blank_noise(after_state):
            after_state = normalize_soft_blank_input_state(after_state, reason="input_region_soft_blank_after_clear")
        return {
            "ok": True,
            "cleared": True,
            "reason": "input_region_cleared",
            "before": before_state,
            "after": after_state,
        }
    return {
        "ok": False,
        "cleared": False,
        "reason": "input_region_clear_failed",
        "before": before_state,
        "after": after_state,
        "error": "Could not safely clear pre-existing WeChat draft text.",
    }


def paste_text_once(text: str) -> None:
    clipboard_copy(text)
    hotkey(win32con.VK_CONTROL, ord("V"))


def sendinput_safe_text(text: str) -> str:
    clean = str(text or "")
    clean = clean.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r" {2,}", " ", clean).strip()


def sendinput_utf16_units(text: str) -> list[int]:
    encoded = str(text or "").encode("utf-16-le", errors="surrogatepass")
    return [int.from_bytes(encoded[index:index + 2], "little") for index in range(0, len(encoded), 2)]


def sendinput_unicode_unit(unit: int) -> None:
    ULONG_PTR = getattr(wintypes, "ULONG_PTR", wintypes.WPARAM)

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [
            ("ki", KEYBDINPUT),
            ("mi", MOUSEINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("union",)
        _fields_ = [
            ("type", wintypes.DWORD),
            ("union", INPUTUNION),
        ]

    scan = int(unit) & 0xFFFF
    sequence = (INPUT * 2)(
        INPUT(
            type=SENDINPUT_INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan,
                dwFlags=SENDINPUT_KEYEVENTF_UNICODE,
                time=0,
                dwExtraInfo=ULONG_PTR(0),
            ),
        ),
        INPUT(
            type=SENDINPUT_INPUT_KEYBOARD,
            ki=KEYBDINPUT(
                wVk=0,
                wScan=scan,
                dwFlags=SENDINPUT_KEYEVENTF_UNICODE | SENDINPUT_KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=ULONG_PTR(0),
            ),
        ),
    )
    coordinate_rpa_action("sendinput_unicode_unit", metadata={"unit": int(unit)})
    sent = ctypes.windll.user32.SendInput(2, ctypes.byref(sequence), ctypes.sizeof(INPUT))
    if int(sent) != 2:
        raise RuntimeError(f"sendinput_unicode_failed: sent={int(sent)}")


def type_text_with_sendinput_unicode(
    text: str,
    settings: dict[str, Any],
    *,
    send_unit_func: Any | None = None,
    window_guard_func: Any | None = None,
) -> dict[str, Any]:
    safe_text = sendinput_safe_text(text)
    chunks = humanized_chunk_text(
        safe_text,
        min_chars=int(settings.get("chunk_min_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MIN_CHARS),
        max_chars=int(settings.get("chunk_max_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MAX_CHARS),
    )
    if not chunks:
        return {
            "ok": True,
            "method": "sendinput_unicode",
            "chunks": 0,
            "typo_count": 0,
            "typed_chars": 0,
            "normalized_newlines": safe_text != str(text or ""),
        }
    send_unit = send_unit_func or sendinput_unicode_unit
    typed_chars = 0
    typo_count = 0
    micro_every = int(settings.get("micro_pause_every_chars") or 0)
    micro_bucket = 0
    try:
        for chunk_index, chunk in enumerate(chunks, start=1):
            if window_guard_func is not None:
                guard = window_guard_func()
                if not guard.get("ok"):
                    return {
                        "ok": False,
                        "method": "sendinput_unicode",
                        "reason": "window_lost_during_sendinput",
                        "window_guard": guard,
                        "chunks": len(chunks),
                        "completed_chunks": chunk_index - 1,
                        "typed_chars": typed_chars,
                        "typo_count": typo_count,
                    }
            for unit in sendinput_utf16_units(chunk):
                if window_guard_func is not None:
                    guard = window_guard_func()
                    if not guard.get("ok"):
                        return {
                            "ok": False,
                            "method": "sendinput_unicode",
                            "reason": "window_lost_during_sendinput",
                            "window_guard": guard,
                            "chunks": len(chunks),
                            "completed_chunks": chunk_index - 1,
                            "typed_chars": typed_chars,
                            "typo_count": typo_count,
                        }
                send_unit(unit)
            typed_chars += len(chunk)
            delay_low, delay_high = typed_text_delay_ms(chunk, settings)
            humanized_sleep_ms(delay_low, delay_high)
            if maybe_humanized_typo_allowed(settings, typo_count=typo_count, text=safe_text):
                if window_guard_func is not None:
                    guard = window_guard_func()
                    if not guard.get("ok"):
                        return {
                            "ok": False,
                            "method": "sendinput_unicode",
                            "reason": "window_lost_during_sendinput",
                            "window_guard": guard,
                            "chunks": len(chunks),
                            "completed_chunks": chunk_index,
                            "typed_chars": typed_chars,
                            "typo_count": typo_count,
                        }
                typo = choose_humanized_typo_char()
                for unit in sendinput_utf16_units(typo):
                    send_unit(unit)
                humanized_sleep_ms(40, 120)
                if window_guard_func is not None:
                    guard = window_guard_func()
                    if not guard.get("ok"):
                        return {
                            "ok": False,
                            "method": "sendinput_unicode",
                            "reason": "window_lost_during_sendinput",
                            "window_guard": guard,
                            "chunks": len(chunks),
                            "completed_chunks": chunk_index,
                            "typed_chars": typed_chars,
                            "typo_count": typo_count,
                        }
                key_press(win32con.VK_BACK)
                typo_count += 1
                humanized_sleep_ms(50, 130)
            if micro_every > 0:
                current_bucket = typed_chars // micro_every
                if current_bucket > micro_bucket:
                    micro_bucket = current_bucket
                    humanized_sleep_ms(
                        int(settings.get("micro_pause_min_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS),
                        int(settings.get("micro_pause_max_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS),
                    )
    except Exception as exc:
        return {
            "ok": False,
            "method": "sendinput_unicode",
            "error": repr(exc),
            "chunks": len(chunks),
            "typed_chars": typed_chars,
            "typo_count": typo_count,
        }
    return {
        "ok": True,
        "method": "sendinput_unicode",
        "chunks": len(chunks),
        "typo_count": typo_count,
        "typed_chars": typed_chars,
        "normalized_newlines": safe_text != str(text or ""),
    }


def strict_send_focus_guard_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_STRICT_SEND_FOCUS_GUARD", default=DEFAULT_STRICT_SEND_FOCUS_GUARD)


def focus_click_fallback_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_FOCUS_CLICK_FALLBACK", default=DEFAULT_FOCUS_CLICK_FALLBACK)


def allow_unknown_foreground_guard() -> bool:
    return env_flag("WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND", default=DEFAULT_ALLOW_UNKNOWN_FOREGROUND_GUARD)


def process_executable_path(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        process_query_limited_information = 0x1000
        handle = kernel32.OpenProcess(process_query_limited_information, False, int(pid))
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return str(buffer.value or "")
            return ""
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def foreground_window_matches_target(hwnd: int) -> dict[str, Any]:
    def _window_brief(candidate_hwnd: int) -> dict[str, Any]:
        brief: dict[str, Any] = {"hwnd": int(candidate_hwnd or 0)}
        if not candidate_hwnd:
            return brief
        try:
            brief["title"] = str(win32gui.GetWindowText(candidate_hwnd) or "")
        except Exception:
            brief["title"] = ""
        try:
            brief["class_name"] = str(win32gui.GetClassName(candidate_hwnd) or "")
        except Exception:
            brief["class_name"] = ""
        try:
            pid = int(win32process.GetWindowThreadProcessId(candidate_hwnd)[1] or 0)
        except Exception:
            pid = 0
        brief["pid"] = pid
        if pid > 0:
            try:
                path = process_executable_path(pid)
            except Exception:
                path = ""
            if path:
                brief["path"] = path
        return brief

    if not hwnd or win32gui is None:
        return {"ok": True, "reason": "foreground_guard_unavailable"}
    try:
        foreground = int(win32gui.GetForegroundWindow() or 0)
    except Exception as exc:
        return {"ok": False, "reason": "foreground_probe_failed", "error": repr(exc), "hwnd": int(hwnd or 0)}
    if foreground == 0:
        if allow_unknown_foreground_guard():
            return {
                "ok": True,
                "reason": "foreground_unknown_guard_degraded",
                "hwnd": int(hwnd),
                "foreground_hwnd": 0,
                "foreground_root_hwnd": 0,
            }
        return {
            "ok": False,
            "reason": "foreground_not_wechat_target",
            "hwnd": int(hwnd),
            "foreground_hwnd": 0,
            "foreground_root_hwnd": 0,
        }
    if foreground == int(hwnd):
        return {"ok": True, "reason": "foreground_matches_target", "hwnd": int(hwnd), "foreground_hwnd": foreground}
    root = 0
    try:
        root = int(win32gui.GetAncestor(foreground, 2) or 0) if foreground else 0
    except Exception:
        root = 0
    if root == int(hwnd):
        return {
            "ok": True,
            "reason": "foreground_root_matches_target",
            "hwnd": int(hwnd),
            "foreground_hwnd": foreground,
            "foreground_root_hwnd": root,
        }
    return {
        "ok": False,
        "reason": "foreground_not_wechat_target",
        "hwnd": int(hwnd),
        "foreground_hwnd": foreground,
        "foreground_root_hwnd": root,
        "foreground_window": _window_brief(foreground),
        "foreground_root_window": _window_brief(root),
    }


def non_retryable_input_failure(result: dict[str, Any] | None) -> bool:
    if not isinstance(result, dict):
        return False
    reason = str(result.get("reason") or "")
    if reason in {"window_lost_during_sendinput", "foreground_not_wechat_target", "foreground_probe_failed"}:
        return True
    guard = result.get("window_guard") if isinstance(result.get("window_guard"), dict) else {}
    guard_reason = str(guard.get("reason") or "")
    return guard_reason in {"foreground_not_wechat_target", "foreground_probe_failed", "window_handle_invalid", "window_not_visible"}


def basic_send_window_guard(hwnd: int) -> dict[str, Any]:
    try:
        if not bool(win32gui.IsWindow(hwnd)):
            return {"ok": False, "reason": "window_handle_invalid"}
        if not bool(win32gui.IsWindowVisible(hwnd)):
            return {"ok": False, "reason": "window_not_visible"}
        geometry = get_window_geometry(hwnd)
        send_geometry = validate_send_geometry(geometry)
        if not send_geometry.get("ok"):
            return {"ok": False, "reason": str(send_geometry.get("reason") or "send_geometry_invalid"), "geometry": geometry}
        if strict_send_focus_guard_enabled():
            focus_guard = foreground_window_matches_target(hwnd)
            if not focus_guard.get("ok"):
                return {"ok": False, **focus_guard, "geometry": geometry}
    except Exception as exc:
        return {"ok": False, "reason": "window_guard_failed", "error": repr(exc)}
    return {"ok": True, "reason": "window_valid"}


def recover_send_window_guard(hwnd: int, *, max_attempts: int = 1) -> dict[str, Any]:
    guard = basic_send_window_guard(hwnd)
    if guard.get("ok"):
        return guard
    reason = str(guard.get("reason") or "")
    if reason not in {"foreground_not_wechat_target", "foreground_probe_failed"}:
        return guard
    attempts = max(0, int(max_attempts))
    if attempts <= 0:
        return guard
    last_guard = guard
    for attempt in range(1, attempts + 1):
        activate_window(hwnd)
        time.sleep(random.uniform(0.06, 0.14))
        retry_guard = basic_send_window_guard(hwnd)
        if retry_guard.get("ok"):
            return {
                **retry_guard,
                "focus_recovered": True,
                "focus_recovery_attempts": attempt,
                "focus_recovery_from": reason,
            }
        last_guard = retry_guard
    return {
        **last_guard,
        "focus_recovered": False,
        "focus_recovery_attempts": attempts,
        "focus_recovery_from": reason,
    }


def paste_text_in_chunks_with_humanized_pacing(text: str, settings: dict[str, Any]) -> dict[str, Any]:
    chunks = humanized_chunk_text(
        text,
        min_chars=int(settings.get("chunk_min_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MIN_CHARS),
        max_chars=int(settings.get("chunk_max_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MAX_CHARS),
    )
    if not chunks:
        return {"ok": True, "method": "clipboard_chunks", "chunks": 0, "typo_count": 0}
    typed_chars = 0
    typo_count = 0
    micro_every = int(settings.get("micro_pause_every_chars") or 0)
    micro_bucket = 0
    for chunk in chunks:
        paste_text_once(chunk)
        typed_chars += len(chunk)
        delay_low, delay_high = typed_text_delay_ms(chunk, settings)
        humanized_sleep_ms(delay_low, delay_high)
        if maybe_humanized_typo_allowed(settings, typo_count=typo_count, text=text):
            typo = choose_humanized_typo_char()
            paste_text_once(typo)
            humanized_sleep_ms(40, 120)
            key_press(win32con.VK_BACK)
            typo_count += 1
            humanized_sleep_ms(50, 130)
        if micro_every > 0:
            current_bucket = typed_chars // micro_every
            if current_bucket > micro_bucket:
                micro_bucket = current_bucket
                humanized_sleep_ms(
                    int(settings.get("micro_pause_min_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS),
                    int(settings.get("micro_pause_max_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS),
                )
    return {
        "ok": True,
        "method": "clipboard_chunks",
        "chunks": len(chunks),
        "typo_count": typo_count,
        "typed_chars": typed_chars,
    }


def paste_text_with_confirmation(
    hwnd: int,
    text: str,
    *,
    points: dict[str, Any],
    geometry: dict[str, Any],
    artifact_dir: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_x = int(points["input_point"][0])
    input_y = int(points["input_point"][1])
    probe_tokens = message_probe_tokens(text)
    probe_token = probe_tokens[0] if probe_tokens else ""
    settings = settings or adapt_humanized_input_settings(humanized_input_settings(), text)
    attempts = [
        (input_x, input_y, "human"),
        (max(session_split_x(int(geometry.get("width") or 0)) + 24, input_x - 150), max(int(geometry.get("height") * 0.80), input_y - 18), "client"),
        (max(session_split_x(int(geometry.get("width") or 0)) + 36, input_x - 220), max(int(geometry.get("height") * 0.82), input_y - 8), "client"),
    ]
    confirm_attempts = send_input_confirm_attempt_count(len(attempts))
    allow_copyback = env_flag("WECHAT_WIN32_OCR_INPUT_COPYBACK_CONFIRM", default=False)
    fast_visual_confirm = env_flag(
        "WECHAT_WIN32_OCR_INPUT_FAST_VISUAL_CONFIRM",
        default=DEFAULT_INPUT_FAST_VISUAL_CONFIRM,
    )
    attempts = attempts[:confirm_attempts]
    input_method = "clipboard_chunks"
    last_input_result: dict[str, Any] | None = None
    last_input_region: dict[str, Any] = {}
    if settings.get("enabled"):
        requested = normalize_humanized_input_method(str(settings.get("method") or "auto"))
        if requested in {"sendinput_unicode", "clipboard_chunks", "clipboard_once"}:
            input_method = requested
        else:
            # Guarded-click mode is Win32-centric; prefer chunked pacing here.
            input_method = "clipboard_chunks"
    for attempt, (x, y, mode) in enumerate(attempts, start=1):
        activate_window(hwnd)
        time.sleep(random.uniform(0.08, 0.18))
        focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
        if not focus_guard.get("ok"):
            return {
                "ok": False,
                "reason": "send_focus_guard_failed_before_input",
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "attempts": attempt,
                "copyback_enabled": allow_copyback,
                "input_region": last_input_region,
                "input_mode": input_method,
                "input_result": last_input_result,
                "window_guard": focus_guard,
            }
        try:
            before_screenshot, _before_path = capture_wechat(
                hwnd,
                artifact_dir=artifact_dir,
                label=f"send_input_before_{attempt}",
            )
            before_ocr_items = [] if fast_visual_confirm else run_ocr(before_screenshot)
            before_input_region = input_text_region_state(before_screenshot, before_ocr_items, geometry=geometry)
        except Exception as exc:
            before_input_region = {
                "has_visible_text": True,
                "reason": "input_region_before_probe_failed",
                "error": repr(exc),
            }
        clear_result = clear_existing_input_draft(
            hwnd,
            points=points,
            geometry=geometry,
            before_state=before_input_region,
            artifact_dir=artifact_dir,
            attempt=attempt,
        )
        if not clear_result.get("ok"):
            return {
                "ok": False,
                "reason": "input_region_not_clear_before_type",
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "attempts": attempt,
                "copyback_enabled": allow_copyback,
                "input_region": before_input_region,
                "clear_result": clear_result,
                "input_mode": input_method,
                "input_result": last_input_result,
            }
        before_input_region = clear_result.get("after") or before_input_region
        click_x, click_y = jitter_input_click_point(int(x), int(y), geometry)
        if mode == "human":
            human_client_click(hwnd, click_x, click_y)
        else:
            client_click(hwnd, click_x, click_y)
        time.sleep(random.uniform(0.12, 0.28))
        focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
        if not focus_guard.get("ok"):
            return {
                "ok": False,
                "reason": "send_focus_guard_failed_after_input_click",
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "attempts": attempt,
                "copyback_enabled": allow_copyback,
                "input_region": last_input_region,
                "input_mode": input_method,
                "input_result": last_input_result,
                "window_guard": focus_guard,
            }
        input_result: dict[str, Any]
        if settings.get("enabled") and input_method == "sendinput_unicode":
            input_result = type_text_with_sendinput_unicode(
                text,
                settings,
                window_guard_func=lambda hwnd=hwnd: basic_send_window_guard(hwnd),
            )
        elif settings.get("enabled") and input_method == "clipboard_chunks":
            focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
            if not focus_guard.get("ok"):
                return {
                    "ok": False,
                    "reason": "send_focus_guard_failed_before_clipboard_input",
                    "probe_token": probe_token,
                    "probe_tokens": probe_tokens,
                    "attempts": attempt,
                    "copyback_enabled": allow_copyback,
                    "input_region": last_input_region,
                    "input_mode": input_method,
                    "input_result": last_input_result,
                    "window_guard": focus_guard,
                }
            input_result = paste_text_in_chunks_with_humanized_pacing(text, settings)
        else:
            focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
            if not focus_guard.get("ok"):
                return {
                    "ok": False,
                    "reason": "send_focus_guard_failed_before_clipboard_input",
                    "probe_token": probe_token,
                    "probe_tokens": probe_tokens,
                    "attempts": attempt,
                    "copyback_enabled": allow_copyback,
                    "input_region": last_input_region,
                    "input_mode": input_method,
                    "input_result": last_input_result,
                    "window_guard": focus_guard,
                }
            paste_text_once(text)
            time.sleep(random.uniform(0.18, 0.42))
            input_result = {"ok": True, "method": "clipboard_once"}
        last_input_result = input_result
        if not input_result.get("ok"):
            if non_retryable_input_failure(input_result):
                return {
                    "ok": False,
                    "reason": "input_aborted_without_retry",
                    "probe_token": probe_token,
                    "probe_tokens": probe_tokens,
                    "attempts": attempt,
                    "copyback_enabled": allow_copyback,
                    "input_region": last_input_region,
                    "input_mode": input_method,
                    "input_result": last_input_result,
                }
            continue
        try:
            screenshot, _path = capture_wechat(hwnd, artifact_dir=artifact_dir, label=f"send_input_probe_{attempt}")
        except Exception as exc:
            return {
                "ok": False,
                "reason": "window_lost_after_input",
                "error": repr(exc),
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "attempts": attempt,
                "copyback_enabled": allow_copyback,
                "input_mode": input_method,
                "input_result": last_input_result,
            }
        fast_after_region = input_text_region_state(screenshot, [], geometry=geometry)
        visual_confirm_fast = input_region_visual_delta_confirms(before_input_region, fast_after_region, input_result)
        if fast_visual_confirm and visual_confirm_fast.get("ok"):
            return {
                "ok": True,
                "attempt": attempt,
                "click_mode": mode,
                "point": [click_x, click_y],
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "confirmed_by": "input_area_visual_delta_fast",
                "input_visual_confirm": visual_confirm_fast,
                "input_clear": clear_result,
                "input_mode": input_method,
                "input_result": input_result,
            }
        ocr_items = run_ocr(screenshot)
        if input_area_contains_any_token(ocr_items, geometry=geometry, tokens=probe_tokens):
            return {
                "ok": True,
                "attempt": attempt,
                "click_mode": mode,
                "point": [click_x, click_y],
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "confirmed_by": "ocr_input_area",
                "input_clear": clear_result,
                "input_mode": input_method,
                "input_result": input_result,
            }
        last_input_region = input_text_region_state(screenshot, ocr_items, geometry=geometry)
        visual_confirm = input_region_visual_delta_confirms(before_input_region, last_input_region, input_result)
        if visual_confirm.get("ok"):
            return {
                "ok": True,
                "attempt": attempt,
                "click_mode": mode,
                "point": [click_x, click_y],
                "probe_token": probe_token,
                "probe_tokens": probe_tokens,
                "confirmed_by": "input_area_visual_delta",
                "input_visual_confirm": visual_confirm,
                "input_clear": clear_result,
                "input_mode": input_method,
                "input_result": input_result,
            }
        if allow_copyback:
            clipboard_confirm = confirm_input_token_via_clipboard(probe_tokens)
            if clipboard_confirm.get("ok"):
                return {
                    "ok": True,
                    "attempt": attempt,
                    "click_mode": mode,
                    "point": [click_x, click_y],
                    "probe_token": probe_token,
                    "probe_tokens": probe_tokens,
                    "confirmed_by": "clipboard_copyback",
                    "clipboard_confirm": clipboard_confirm,
                    "input_clear": clear_result,
                    "input_mode": input_method,
                    "input_result": input_result,
                }
        if last_input_region.get("has_visible_text"):
            break
        time.sleep(random.uniform(0.16, 0.34))
    return {
        "ok": False,
        "reason": "input_token_not_detected_after_paste",
        "probe_token": probe_token,
        "probe_tokens": probe_tokens,
        "attempts": len(attempts),
        "copyback_enabled": allow_copyback,
        "input_region": last_input_region,
        "input_mode": input_method,
        "input_result": last_input_result,
    }


def send_input_confirm_attempt_count(total_attempts: int) -> int:
    requested = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_SEND_INPUT_CONFIRM_ATTEMPTS"),
        default=DEFAULT_SEND_INPUT_CONFIRM_ATTEMPTS,
        minimum=1,
        maximum=max(1, int(total_attempts)),
    )
    if (
        requested == 1
        and total_attempts > 1
        and env_flag("WECHAT_WIN32_OCR_BLANK_INPUT_FOCUS_RETRY", default=True)
    ):
        # Preserve the product-level "one confirmed input attempt" rule, but
        # allow one extra focus point when the first attempt leaves the input
        # region visibly blank. Visible or uncertain drafts still stop.
        return 2
    return requested


def _probe_tokens_normalized(tokens: list[str] | str) -> list[str]:
    raw_tokens = tokens if isinstance(tokens, list) else [str(tokens or "")]
    normalized: list[str] = []
    for token in raw_tokens:
        compact = re.sub(r"\s+", "", str(token or ""))
        if len(compact) < 2:
            continue
        if compact not in normalized:
            normalized.append(compact)
    return normalized


def _clipboard_token_matches(copied_text: str, normalized_tokens: list[str]) -> tuple[bool, str]:
    compact = re.sub(r"\s+", "", str(copied_text or ""))
    if len(compact) < 3:
        return False, "clipboard_copyback_too_short"
    for token in normalized_tokens:
        if token in compact or compact in token:
            return True, "clipboard_copyback_token_match"
    return False, "clipboard_copyback_token_mismatch"


def confirm_input_token_via_clipboard(probe_tokens: list[str] | str) -> dict[str, Any]:
    normalized_tokens = _probe_tokens_normalized(probe_tokens)
    if not normalized_tokens:
        return {"ok": False, "reason": "empty_probe_token"}
    try:
        # Low-disturbance copyback probe: do not select-all to avoid visible
        # global selection artifacts when focus drifts.
        hotkey(win32con.VK_CONTROL, ord("C"))
        humanized_action_sleep(60, 110)
        copied = str(clipboard_read() or "")
    except Exception as exc:
        return {"ok": False, "reason": "clipboard_copyback_failed", "error": repr(exc)}
    matched, reason = _clipboard_token_matches(copied, normalized_tokens)
    if matched:
        return {
            "ok": True,
            "reason": reason,
            "mode": "copy",
            "captured_preview": copied[:80],
        }
    strong_confirm = env_flag(
        "WECHAT_WIN32_OCR_INPUT_COPYBACK_STRONG_CONFIRM",
        default=DEFAULT_INPUT_COPYBACK_STRONG_CONFIRM,
    )
    if strong_confirm:
        try:
            hotkey(win32con.VK_CONTROL, ord("A"))
            humanized_action_sleep(45, 90)
            hotkey(win32con.VK_CONTROL, ord("C"))
            humanized_action_sleep(60, 120)
            copied_all = str(clipboard_read() or "")
            matched_all, reason_all = _clipboard_token_matches(copied_all, normalized_tokens)
            if matched_all:
                return {
                    "ok": True,
                    "reason": reason_all,
                    "mode": "select_all_copy",
                    "captured_preview": copied_all[:80],
                }
        except Exception as exc:
            return {"ok": False, "reason": "clipboard_copyback_failed", "error": repr(exc)}
    return {
        "ok": False,
        "reason": reason,
        "captured_preview": copied[:80],
    }


def safe_send_trigger(
    hwnd: int,
    *,
    trigger_mode: str,
    send_point: tuple[int, int] | None = None,
    settings: dict[str, Any] | None = None,
    focus_guard_func: Any | None = None,
) -> dict[str, Any]:
    active_settings = settings or {}
    if active_settings.get("enabled"):
        humanized_sleep_ms(
            int(active_settings.get("send_trigger_delay_min_ms") or DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MIN_MS),
            int(active_settings.get("send_trigger_delay_max_ms") or DEFAULT_HUMANIZED_SEND_TRIGGER_DELAY_MAX_MS),
        )
    guard = focus_guard_func() if focus_guard_func is not None else recover_send_window_guard(hwnd, max_attempts=1)
    if not guard.get("ok"):
        return {
            "ok": False,
            "reason": "send_focus_guard_failed_before_trigger",
            "error": "WeChat lost foreground focus before send trigger; abort without retrying.",
            "window_guard": guard,
            "send_trigger_mode": trigger_mode,
        }
    mode = normalize_send_trigger_mode(trigger_mode)
    if mode in {"enter_only", "enter_then_click"}:
        ensure_left_button_released()
        coordinate_rpa_action(
            "send_trigger_enter",
            metadata={"hwnd": int(hwnd or 0), "key": int(win32con.VK_RETURN), "trigger_mode": mode},
        )
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        humanized_action_sleep(54, 145)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        if active_settings.get("enabled"):
            humanized_sleep_ms(
                int(active_settings.get("send_after_trigger_delay_min_ms") or DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MIN_MS),
                int(active_settings.get("send_after_trigger_delay_max_ms") or DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MAX_MS),
            )
        return {"ok": True, "method": "keyboard_enter", "send_trigger_mode": mode, "window_guard": guard}
    if mode == "click_only":
        if send_point is None:
            return {"ok": False, "reason": "send_click_point_missing", "send_trigger_mode": mode, "window_guard": guard}
        click_guard = focus_guard_func() if focus_guard_func is not None else recover_send_window_guard(hwnd, max_attempts=1)
        if not click_guard.get("ok"):
            return {
                "ok": False,
                "reason": "send_focus_guard_failed_before_click_trigger",
                "error": "WeChat lost foreground focus before clicking send; abort without retrying.",
                "window_guard": click_guard,
                "send_trigger_mode": mode,
            }
        human_client_click(hwnd, int(send_point[0]), int(send_point[1]))
        if active_settings.get("enabled"):
            humanized_sleep_ms(
                int(active_settings.get("send_after_trigger_delay_min_ms") or DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MIN_MS),
                int(active_settings.get("send_after_trigger_delay_max_ms") or DEFAULT_HUMANIZED_SEND_AFTER_TRIGGER_DELAY_MAX_MS),
            )
        return {"ok": True, "method": "human_click_send", "send_trigger_mode": mode, "window_guard": click_guard}
    return {"ok": False, "reason": "unsupported_send_trigger_mode", "send_trigger_mode": mode, "window_guard": guard}


def send_with_guarded_clicks(
    hwnd: int,
    text: str,
    *,
    points: dict[str, Any],
    geometry: dict[str, Any],
    allow_unconfirmed_paste: bool = False,
    artifact_dir: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # WeChat 4.1.x keeps the attachment toolbar near the bottom. Paste first
    # and confirm OCR can see the token in the input area before sending.
    send_x = int(points["send_point"][0])
    send_y = int(points["send_point"][1])
    send_click_x, send_click_y = jitter_send_click_point(send_x, send_y, geometry)
    settings = settings or adapt_humanized_input_settings(humanized_input_settings(), text)
    if settings.get("enabled"):
        humanized_sleep_ms(
            int(settings.get("send_pre_delay_min_ms") or DEFAULT_HUMANIZED_SEND_PRE_DELAY_MIN_MS),
            int(settings.get("send_pre_delay_max_ms") or DEFAULT_HUMANIZED_SEND_PRE_DELAY_MAX_MS),
        )
    paste_result = paste_text_with_confirmation(
        hwnd,
        text,
        points=points,
        geometry=geometry,
        artifact_dir=artifact_dir,
        settings=settings,
    )
    if not paste_result.get("ok"):
        if allow_unconfirmed_paste and str(paste_result.get("reason") or "") == "input_token_not_detected_after_paste":
            paste_result = {
                **paste_result,
                "ok": True,
                "degraded": True,
                "degraded_reason": "blind_send_unconfirmed_input_allowed",
            }
        else:
            return {
                "ok": False,
                "reason": "paste_not_confirmed",
                "error": "Could not confirm pasted text in WeChat input box before send.",
                "paste": paste_result,
            }
    if settings.get("enabled"):
        humanized_sleep_ms(
            int(settings.get("send_post_input_delay_min_ms") or DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS),
            int(settings.get("send_post_input_delay_max_ms") or DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS),
        )
    focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
    if not focus_guard.get("ok"):
        return {
            "ok": False,
            "reason": "send_focus_guard_failed_before_trigger",
            "error": "WeChat lost foreground focus before send trigger; abort without retrying.",
            "paste": paste_result,
            "window_guard": focus_guard,
        }
    input_point = paste_result.get("point")
    if isinstance(input_point, list) and len(input_point) >= 2:
        human_client_click(hwnd, int(input_point[0]), int(input_point[1]))
        humanized_action_sleep(90, 210)
        focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
        if not focus_guard.get("ok"):
            return {
                "ok": False,
                "reason": "send_focus_guard_failed_after_input_refocus",
                "error": "WeChat lost foreground focus after input refocus; abort before send trigger.",
                "paste": paste_result,
                "window_guard": focus_guard,
            }
    trigger_mode = normalize_send_trigger_mode(os.getenv("WECHAT_WIN32_OCR_SEND_TRIGGER_MODE"))
    trigger_result = safe_send_trigger(
        hwnd,
        trigger_mode=trigger_mode,
        send_point=(send_click_x, send_click_y),
        settings=settings,
        focus_guard_func=lambda hwnd=hwnd: recover_send_window_guard(hwnd, max_attempts=1),
    )
    if not trigger_result.get("ok"):
        return {
            "ok": False,
            "reason": str(trigger_result.get("reason") or "send_trigger_failed"),
            "error": str(trigger_result.get("error") or "Could not safely trigger WeChat send."),
            "paste": paste_result,
            "window_guard": trigger_result.get("window_guard") if isinstance(trigger_result.get("window_guard"), dict) else focus_guard,
            "trigger": trigger_result,
        }
    paste_method = str(paste_result.get("input_mode") or paste_result.get("method") or "clipboard_once")
    return {
        "ok": True,
        "method": f"win32.human_click_input+{paste_method}+send_trigger:{trigger_mode}",
        "input_point": [int(points["input_point"][0]), int(points["input_point"][1])],
        "send_point": [send_click_x, send_click_y],
        "paste": paste_result,
        "send_trigger_mode": trigger_mode,
        "send_trigger": trigger_result,
        "degraded": bool(paste_result.get("degraded")),
        "humanized_input": settings,
    }


def send_with_uia_controls(
    hwnd: int,
    text: str,
    *,
    geometry: dict[str, Any],
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        import uiautomation as auto  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": "uiautomation_unavailable", "error": repr(exc)}

    try:
        root = auto.ControlFromHandle(hwnd)
        controls = collect_uia_controls(root, max_depth=8, max_count=900)
        edit = select_uia_edit_control(controls, geometry)
        send_button = select_uia_send_button(controls, geometry)
        if edit is None:
            return {"ok": False, "reason": "uia_edit_not_found", "control_count": len(controls)}
        if send_button is None:
            return {"ok": False, "reason": "uia_send_button_not_found", "control_count": len(controls)}

        edit.SetFocus()
        humanized_action_sleep(80, 160)
        settings = settings or adapt_humanized_input_settings(humanized_input_settings(), text)
        if settings.get("enabled"):
            humanized_sleep_ms(
                int(settings.get("send_pre_delay_min_ms") or DEFAULT_HUMANIZED_SEND_PRE_DELAY_MIN_MS),
                int(settings.get("send_pre_delay_max_ms") or DEFAULT_HUMANIZED_SEND_PRE_DELAY_MAX_MS),
            )
        pattern_result = set_uia_control_value(auto, edit, text, settings=settings)
        if not pattern_result.get("ok"):
            return {**pattern_result, "control_count": len(controls)}
        if settings.get("enabled"):
            humanized_sleep_ms(
                int(settings.get("send_post_input_delay_min_ms") or DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MIN_MS),
                int(settings.get("send_post_input_delay_max_ms") or DEFAULT_HUMANIZED_SEND_POST_INPUT_DELAY_MAX_MS),
            )
        humanized_action_sleep(260, 760)
        humanized_action_sleep(120, 230)
        invoke_result = invoke_uia_button(auto, send_button)
        if not invoke_result.get("ok"):
            return {**invoke_result, "control_count": len(controls)}
        input_method = str(pattern_result.get("method") or "ValuePattern.SetValue")
        return {
            "ok": True,
            "method": f"uia.{input_method}+InvokePattern.Invoke",
            "control_count": len(controls),
            "edit": describe_uia_control(edit, geometry),
            "send_button": describe_uia_control(send_button, geometry),
            "humanized_input": settings,
            "input_result": pattern_result,
        }
    except Exception as exc:
        return {"ok": False, "reason": "uia_send_failed", "error": repr(exc)}


def inspect_uia_send_capability(hwnd: int, geometry: dict[str, Any]) -> dict[str, Any]:
    try:
        import uiautomation as auto  # type: ignore
    except Exception as exc:
        return {"ok": False, "reason": "uiautomation_unavailable", "error": repr(exc)}

    try:
        root = auto.ControlFromHandle(hwnd)
        controls = collect_uia_controls(root, max_depth=8, max_count=900)
        edit = select_uia_edit_control(controls, geometry)
        send_button = select_uia_send_button(controls, geometry)
        missing: list[str] = []
        if edit is None:
            missing.append("edit")
        if send_button is None:
            missing.append("send_button")
        return {
            "ok": not missing,
            "reason": "uia_controls_ready" if not missing else "uia_controls_missing",
            "missing": missing,
            "control_count": len(controls),
            "edit": describe_uia_control(edit, geometry) if edit is not None else None,
            "send_button": describe_uia_control(send_button, geometry) if send_button is not None else None,
        }
    except Exception as exc:
        return {"ok": False, "reason": "uia_inspect_failed", "error": repr(exc)}


def collect_uia_controls(root: Any, *, max_depth: int, max_count: int) -> list[Any]:
    controls: list[Any] = []
    queue: list[tuple[Any, int]] = [(root, 0)]
    while queue and len(controls) < max_count:
        control, depth = queue.pop(0)
        if depth:
            controls.append(control)
        if depth >= max_depth:
            continue
        try:
            children = list(control.GetChildren())
        except Exception:
            children = []
        for child in children:
            if len(controls) + len(queue) >= max_count:
                break
            queue.append((child, depth + 1))
    return controls


def select_uia_edit_control(controls: list[Any], geometry: dict[str, Any]) -> Any | None:
    candidates: list[tuple[float, Any]] = []
    for control in controls:
        if "edit" not in str(safe_uia_attr(control, "ControlTypeName")).lower():
            continue
        rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
        if not rect_in_input_area(rect, geometry):
            continue
        rel = relative_rect(rect, geometry)
        area = max(1, rel["width"]) * max(1, rel["height"])
        score = area + rel["bottom"] * 2
        candidates.append((score, control))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def select_uia_send_button(controls: list[Any], geometry: dict[str, Any]) -> Any | None:
    candidates: list[tuple[float, Any]] = []
    for control in controls:
        control_type = str(safe_uia_attr(control, "ControlTypeName")).lower()
        name = normalize_ocr_text(safe_uia_attr(control, "Name"))
        if "button" not in control_type:
            continue
        if "发送" not in name and name.lower() not in {"send"}:
            continue
        rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
        if not rect_in_input_toolbar(rect, geometry):
            continue
        rel = relative_rect(rect, geometry)
        score = rel["right"] + rel["bottom"] * 2
        candidates.append((score, control))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def set_uia_control_value_humanized(pattern: Any, text: str, settings: dict[str, Any]) -> dict[str, Any]:
    chunks = humanized_chunk_text(
        text,
        min_chars=int(settings.get("chunk_min_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MIN_CHARS),
        max_chars=int(settings.get("chunk_max_chars") or DEFAULT_HUMANIZED_TYPING_CHUNK_MAX_CHARS),
    )
    typo_count = 0
    typed_chars = 0
    value = ""
    micro_every = int(settings.get("micro_pause_every_chars") or 0)
    micro_bucket = 0
    pattern.SetValue("")
    humanized_sleep_ms(40, 120)
    for chunk in chunks:
        value += chunk
        pattern.SetValue(value)
        typed_chars += len(chunk)
        low, high = typed_text_delay_ms(chunk, settings)
        humanized_sleep_ms(low, high)
        if maybe_humanized_typo_allowed(settings, typo_count=typo_count, text=text):
            typo = choose_humanized_typo_char()
            pattern.SetValue(value + typo)
            humanized_sleep_ms(35, 110)
            pattern.SetValue(value)
            typo_count += 1
            humanized_sleep_ms(50, 130)
        if micro_every > 0:
            current_bucket = typed_chars // micro_every
            if current_bucket > micro_bucket:
                micro_bucket = current_bucket
                humanized_sleep_ms(
                    int(settings.get("micro_pause_min_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MIN_MS),
                    int(settings.get("micro_pause_max_ms") or DEFAULT_HUMANIZED_TYPING_MICRO_PAUSE_MAX_MS),
                )
    return {
        "ok": True,
        "method": "ValuePattern.SetValue.humanized_chunks",
        "chunks": len(chunks),
        "typed_chars": typed_chars,
        "typo_count": typo_count,
    }


def set_uia_control_value(auto: Any, control: Any, text: str, *, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        pattern = control.GetPattern(auto.PatternId.ValuePattern)
        active_settings = settings or humanized_input_settings()
        method = normalize_humanized_input_method(str(active_settings.get("method") or "auto"))
        if active_settings.get("enabled") and method in {"auto", "uia_chunks", "clipboard_chunks"}:
            return set_uia_control_value_humanized(pattern, text, active_settings)
        pattern.SetValue("")
        humanized_action_sleep(35, 80)
        pattern.SetValue(text)
        return {"ok": True, "method": "ValuePattern.SetValue"}
    except Exception as exc:
        return {"ok": False, "reason": "uia_value_pattern_failed", "error": repr(exc)}


def invoke_uia_button(auto: Any, control: Any) -> dict[str, Any]:
    try:
        pattern = control.GetPattern(auto.PatternId.InvokePattern)
        pattern.Invoke()
        return {"ok": True, "method": "InvokePattern.Invoke"}
    except Exception:
        try:
            control.Click()
            return {"ok": True, "method": "Control.Click"}
        except Exception as exc:
            return {"ok": False, "reason": "uia_invoke_failed", "error": repr(exc)}


def describe_uia_control(control: Any, geometry: dict[str, Any]) -> dict[str, Any]:
    rect = uia_rect_to_dict(safe_uia_attr(control, "BoundingRectangle"))
    return {
        "name": normalize_ocr_text(safe_uia_attr(control, "Name")),
        "control_type": str(safe_uia_attr(control, "ControlTypeName") or ""),
        "class_name": str(safe_uia_attr(control, "ClassName") or ""),
        "rect": relative_rect(rect, geometry),
    }


def safe_uia_attr(control: Any, name: str) -> Any:
    try:
        value = getattr(control, name)
        return value() if callable(value) and name in {"Name", "ClassName", "ControlTypeName"} else value
    except Exception:
        return ""


def uia_rect_to_dict(rect: Any) -> dict[str, int]:
    return {
        "left": int(getattr(rect, "left", getattr(rect, "Left", 0)) or 0),
        "top": int(getattr(rect, "top", getattr(rect, "Top", 0)) or 0),
        "right": int(getattr(rect, "right", getattr(rect, "Right", 0)) or 0),
        "bottom": int(getattr(rect, "bottom", getattr(rect, "Bottom", 0)) or 0),
    }


def relative_rect(rect: dict[str, int], geometry: dict[str, Any]) -> dict[str, int]:
    left = int(rect.get("left") or 0) - int(geometry.get("left") or 0)
    top = int(rect.get("top") or 0) - int(geometry.get("top") or 0)
    right = int(rect.get("right") or 0) - int(geometry.get("left") or 0)
    bottom = int(rect.get("bottom") or 0) - int(geometry.get("top") or 0)
    return {
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
        "width": max(0, right - left),
        "height": max(0, bottom - top),
    }


def rect_in_input_area(rect: dict[str, int], geometry: dict[str, Any]) -> bool:
    rel = relative_rect(rect, geometry)
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if rel["width"] <= 80 or rel["height"] <= 12:
        return False
    if rel["right"] <= session_split_x(width) + 100:
        return False
    bounds = input_text_region_bounds(geometry)
    left, top, right, bottom = bounds
    draft_top = min(top, max(int(height * 0.79), height - 180))
    center_y = (rel["top"] + rel["bottom"]) / 2.0
    horizontal_overlap = min(rel["right"], right) - max(rel["left"], left)
    if horizontal_overlap <= 0:
        return False
    return rel["top"] >= draft_top - 6 and rel["bottom"] <= bottom + 10 and draft_top <= center_y <= bottom


def rect_in_input_toolbar(rect: dict[str, int], geometry: dict[str, Any]) -> bool:
    rel = relative_rect(rect, geometry)
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if rel["width"] <= 20 or rel["height"] <= 15:
        return False
    if rel["right"] <= session_split_x(width) + 60:
        return False
    return rel["top"] >= int(height * 0.78) and rel["bottom"] <= height + 8


def session_name_matches(name: str, target: str, *, exact: bool) -> bool:
    normalized_name = normalize_session_name(name)
    normalized_target = normalize_session_name(target)
    if not normalized_name or not normalized_target:
        return False
    stripped_name = strip_session_time_suffix(normalized_name)
    canonical_name = canonical_session_name(normalized_name)
    canonical_target = canonical_session_name(normalized_target)
    if canonical_name and canonical_target and canonical_name == canonical_target:
        return True
    stripped_canonical_name = canonical_session_name(stripped_name)
    if stripped_canonical_name and canonical_target and stripped_canonical_name == canonical_target:
        return True
    if exact:
        if normalized_name == normalized_target or stripped_name == normalized_target:
            return True
        wrapped_name = normalize_chat_title_for_match(normalized_name)
        stripped_wrapped_name = normalize_chat_title_for_match(stripped_name)
        wrapped_target = normalize_chat_title_for_match(normalized_target)
        return bool(
            wrapped_target
            and (
                (wrapped_name and wrapped_name == wrapped_target)
                or (stripped_wrapped_name and stripped_wrapped_name == wrapped_target)
            )
        )
    return normalized_target in normalized_name or normalized_name in normalized_target


def strip_session_time_suffix(name: str) -> str:
    normalized = normalize_session_name(name)
    if not normalized:
        return ""
    patterns = (
        r"(?:今天|昨天|前天)?\d{1,2}:\d{2}$",
        r"(?:今天|昨天|前天)$",
        r"(?:星期|周)[一二三四五六日天]$",
        r"\d{4}[/-]\d{1,2}[/-]\d{1,2}$",
        r"\d{1,2}[/-]\d{1,2}$",
    )
    stripped = normalized
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            updated = re.sub(pattern, "", stripped).strip()
            if updated != stripped:
                stripped = updated
                changed = True
    return stripped or normalized


def session_row_click_x(
    session: dict[str, Any],
    geometry: dict[str, Any],
    *,
    default_x: int,
) -> int:
    width = int(geometry.get("width") or 0)
    split_x = session_split_x(width)
    left = int(float(session.get("left") or 0))
    right = int(float(session.get("right") or 0))
    if right > left:
        # Clicking near the rendered text center is more reliable than a fixed
        # sidebar X when the DPI scale or window skin changes.
        text_center = int((left + right) / 2)
        preferred = max(text_center, left + 22)
    else:
        preferred = int(default_x)
    return bounded_int(preferred, default=default_x, minimum=170, maximum=max(210, split_x - 18))


def session_row_click_candidate_points(
    session: dict[str, Any],
    geometry: dict[str, Any],
    *,
    default_x: int,
    min_points: int = 10,
) -> list[tuple[int, int]]:
    """Return a spread of safe points inside one sidebar session row.

    A single text-center click leaks an obvious RPA fingerprint.  Keep the
    points inside the row, away from the unread badge, and let the final click
    jitter add a second small random offset.
    """
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    split_x = session_split_x(width)
    center_y_raw = session.get("center_y")
    if center_y_raw is None:
        return []
    center_y = int(float(center_y_raw))
    text_left = int(float(session.get("left") or 0))
    text_right = int(float(session.get("right") or 0))
    if text_right > text_left:
        row_left = max(74, min(text_left - 56, split_x - 230))
        row_right = min(split_x - 52, max(text_right + 26, row_left + 132))
    else:
        base_x = session_row_click_x(session, geometry, default_x=default_x)
        row_left = max(74, base_x - 82)
        row_right = min(split_x - 52, base_x + 84)
    if row_right <= row_left:
        row_left = max(74, min(int(default_x) - 70, split_x - 180))
        row_right = min(split_x - 52, row_left + 140)
    top = bounded_int(center_y - 16, default=max(88, center_y - 16), minimum=88, maximum=max(88, height - 28))
    bottom = bounded_int(center_y + 18, default=center_y + 18, minimum=top + 8, maximum=max(top + 8, height - 18))
    x_fracs = (0.10, 0.20, 0.32, 0.44, 0.56, 0.68, 0.80, 0.90, 0.38, 0.74)
    y_fracs = (0.24, 0.50, 0.78, 0.34, 0.68, 0.42, 0.82, 0.58, 0.18, 0.72)
    points: list[tuple[int, int]] = []
    for x_frac, y_frac in zip(x_fracs, y_fracs):
        x = int(row_left + (row_right - row_left) * x_frac)
        y = int(top + (bottom - top) * y_frac)
        point = (
            bounded_int(x, default=int(default_x), minimum=row_left, maximum=row_right),
            bounded_int(y, default=center_y, minimum=top, maximum=bottom),
        )
        if point not in points:
            points.append(point)
    while len(points) < max(1, int(min_points or 1)):
        point = (random.randint(row_left, row_right), random.randint(top, bottom))
        if point not in points:
            points.append(point)
    random.shuffle(points)
    return points


def choose_session_row_click_point(
    session: dict[str, Any],
    geometry: dict[str, Any],
    *,
    default_x: int,
) -> tuple[int, int, dict[str, Any]]:
    points = session_row_click_candidate_points(session, geometry, default_x=default_x, min_points=10)
    if not points:
        fallback = (
            session_row_click_x(session, geometry, default_x=default_x),
            int(float(session.get("center_y") or 0)),
        )
        return fallback[0], fallback[1], {"candidate_count": 0, "candidate_index": -1, "candidates": [list(fallback)]}
    index = random.randrange(len(points))
    x, y = points[index]
    return x, y, {
        "candidate_count": len(points),
        "candidate_index": index,
        "candidates": [list(point) for point in points],
    }


def activate_session_candidate(
    hwnd: int,
    session: dict[str, Any],
    *,
    target: str,
    exact: bool,
    geometry: dict[str, Any],
    default_click_x: int,
    artifact_dir: str | None = None,
) -> bool:
    center_y = session.get("center_y")
    if center_y is None:
        return False
    click_x, click_y, _click_meta = choose_session_row_click_point(
        session,
        geometry,
        default_x=default_click_x,
    )
    # Use exactly one human-like click per candidate. If the active-title
    # guard cannot confirm the switch, stop this RPA attempt and let the
    # scheduler cool down/re-capture instead of probing the same row again.
    humanized_action_sleep(260, 720)
    human_client_click(hwnd, click_x, click_y)
    for attempt in range(target_switch_passive_confirm_attempts()):
        if attempt == 0:
            humanized_action_sleep(320, 620)
        else:
            # Passive re-read only. Some WeChat builds need a short render
            # settle after switching chats; repeated row clicks are not needed.
            humanized_action_sleep(180, 360)
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if active_send_guard_is_strong(validation):
            return True
        if target_switch_validation_is_hard_stop(validation):
            return False
    return False


def session_matches_key(session: dict[str, Any], session_key: str) -> bool:
    expected = str(session_key or "").strip()
    if not expected:
        return False
    actual = str(session.get("session_key") or "").strip()
    return bool(actual and actual == expected)


def find_session_candidate_by_key(sessions: list[dict[str, Any]], session_key: str) -> dict[str, Any] | None:
    expected = str(session_key or "").strip()
    if not expected:
        return None
    for item in sessions:
        if isinstance(item, dict) and session_matches_key(item, expected):
            return item
    return None


def visible_session_name_is_unambiguous(
    sessions: list[dict[str, Any]],
    target: str,
    *,
    exact: bool,
) -> bool:
    matches = [
        item
        for item in sessions
        if isinstance(item, dict) and session_name_matches(str(item.get("name") or ""), target, exact=exact)
    ]
    return len(matches) == 1


def detect_session_subview_back_target(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> dict[str, int] | None:
    width, height = image_size
    split_x = session_split_x(width)
    header_limit = chat_header_cutoff_y(height) + max(42, int(height * 0.06))
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        if item["center_y"] > header_limit:
            continue
        if item["right"] > split_x + 40:
            continue
        compact = text.replace(" ", "")
        has_arrow = compact.startswith("<") or compact.startswith("〈") or compact.startswith("‹") or compact.startswith("＜")
        if not has_arrow:
            continue
        if not any(keyword in compact for keyword in ("服务号", "订阅号", "公众号")):
            continue
        return {
            "x": bounded_int(int(float(item.get("left") or 0)) + 10, default=108, minimum=70, maximum=170),
            "y": bounded_int(int(float(item.get("center_y") or 0)), default=124, minimum=86, maximum=220),
        }
    return None


def ensure_main_session_list(
    hwnd: int,
    *,
    artifact_dir: str | None = None,
    max_hops: int = 2,
) -> tuple[Any, list[dict[str, Any]]]:
    screenshot, _path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat")
    ocr_items = run_ocr(screenshot)
    hops = max(0, int(max_hops))
    for _ in range(hops):
        back_target = detect_session_subview_back_target(ocr_items, screenshot.size)
        if not back_target:
            break
        client_click(hwnd, int(back_target["x"]), int(back_target["y"]))
        humanized_action_sleep(280, 480)
        screenshot, _path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat_main_list")
        ocr_items = run_ocr(screenshot)
    return screenshot, ocr_items


def target_switch_surface_state(
    screenshot: Any,
    ocr_items: list[dict[str, Any]],
    *,
    geometry: dict[str, Any],
    screenshot_path: str = "",
) -> dict[str, Any]:
    if not ocr_items:
        blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
        if blank_render.get("detected"):
            return {
                "ok": False,
                "online": False,
                "reason": "blank_render",
                "state": "blank_render_detected",
                "geometry": geometry,
                "screenshot_path": screenshot_path,
                "ocr_count": 0,
                "render_probe": blank_render,
                "error": "WeChat render is blank; stop cross-chat switching before further RPA action.",
            }
        return {"ok": True, "online": True, "reason": "surface_no_ocr_not_blank", "ocr_count": 0}
    if quick_login_like(ocr_items, geometry=geometry):
        return {
            "ok": False,
            "online": False,
            "reason": "login_or_qr",
            "state": "login_window_detected",
            "geometry": geometry,
            "screenshot_path": screenshot_path,
            "ocr_count": len(ocr_items),
            "error": "WeChat quick-login view detected; stop cross-chat switching.",
        }
    blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
    if blank_render.get("detected"):
        return {
            "ok": False,
            "online": False,
            "reason": "blank_render",
            "state": "blank_render_detected",
            "geometry": geometry,
            "screenshot_path": screenshot_path,
            "ocr_count": len(ocr_items),
            "render_probe": blank_render,
            "error": "WeChat render is blank; stop cross-chat switching before further RPA action.",
        }
    auxiliary_shell = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    if auxiliary_shell.get("detected"):
        return {
            "ok": False,
            "online": False,
            "reason": "auxiliary_shell_window",
            "state": "auxiliary_shell_window_detected",
            "geometry": geometry,
            "screenshot_path": screenshot_path,
            "ocr_count": len(ocr_items),
            "shell_probe": auxiliary_shell,
            "error": "Selected WeChat window looks like an auxiliary shell; stop cross-chat switching.",
        }
    blocking_reason = blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason in {"login_or_qr"} else True,
            "reason": blocking_reason,
            "state": "blocking_screen_detected",
            "geometry": geometry,
            "screenshot_path": screenshot_path,
            "ocr_count": len(ocr_items),
            "error": f"WeChat cross-chat switch guard found blocking screen: {blocking_reason}",
        }
    return {"ok": True, "online": True, "reason": "surface_ready", "ocr_count": len(ocr_items)}


def target_switch_validation_is_hard_stop(validation: dict[str, Any] | None) -> bool:
    if not isinstance(validation, dict):
        return False
    state = str(validation.get("state") or "")
    reason = str(validation.get("reason") or "")
    if state in {"blank_render_detected", "login_window_detected", "auxiliary_shell_window_detected"}:
        return True
    return reason in {"blank_render", "login_or_qr", "auxiliary_shell_window"}


def target_ready_attempt_count(max_attempts: int | None) -> int:
    if max_attempts is not None:
        return max(1, int(max_attempts))
    return bounded_int(
        os.getenv("WECHAT_WIN32_OCR_TARGET_READY_MAX_ATTEMPTS"),
        default=DEFAULT_TARGET_READY_MAX_ATTEMPTS,
        minimum=1,
        maximum=3,
    )


def target_search_fallback_enabled() -> bool:
    # The search/header region is a high-risk path for live WeChat RPA. Prefer
    # visible-session and unread-badge switching; enable only for diagnostics.
    return env_flag("WECHAT_WIN32_OCR_TARGET_SEARCH_FALLBACK", default=False)


def target_search_enter_fallback_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_TARGET_SEARCH_ENTER_FALLBACK", default=False)


def clear_sidebar_search_box_without_select_all(
    hwnd: int,
    search_x: int,
    search_y: int,
    *,
    target_hint: str = "",
) -> None:
    """Clear sidebar search text without Ctrl+A to avoid global selection artifacts."""
    # First ESC clears an existing search session in many WeChat builds.
    key_press(win32con.VK_ESCAPE)
    humanized_action_sleep(60, 130)
    human_window_image_click(hwnd, search_x, search_y)
    humanized_action_sleep(70, 150)
    # Use short Backspace/Delete bursts instead of select-all. This is slower,
    # but safer when focus occasionally drifts.
    default_backspaces = min(max(len(str(target_hint or "")) + 6, 10), 18)
    backspaces = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_TARGET_SEARCH_CLEAR_BACKSPACES"),
        default=default_backspaces,
        minimum=4,
        maximum=32,
    )
    deletes = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_TARGET_SEARCH_CLEAR_DELETES"),
        default=2,
        minimum=0,
        maximum=8,
    )
    next_pause_at = random.randint(5, 8)
    for idx in range(backspaces):
        key_press(win32con.VK_BACK)
        humanized_action_sleep(8, 26)
        if idx + 1 >= next_pause_at:
            humanized_action_sleep(25, 70)
            next_pause_at += random.randint(5, 8)
    for _ in range(deletes):
        key_press(win32con.VK_DELETE)
        humanized_action_sleep(12, 34)


def type_sidebar_search_query(hwnd: int, target: str) -> dict[str, Any]:
    method = str(os.getenv("WECHAT_WIN32_OCR_TARGET_SEARCH_INPUT_METHOD") or "sendinput_unicode").strip().lower()
    if method == "clipboard":
        clipboard_copy(target)
        hotkey(win32con.VK_CONTROL, ord("V"))
        humanized_action_sleep(70, 150)
        return {"ok": True, "method": "clipboard"}
    settings = {
        "enabled": True,
        "chunk_min_chars": 2,
        "chunk_max_chars": 4,
        "char_delay_min_ms": 70,
        "char_delay_max_ms": 165,
        "micro_pause_every_chars": 0,
        "micro_pause_min_ms": 0,
        "micro_pause_max_ms": 0,
        "typo_probability": 0.0,
        "typo_max": 0,
    }
    return type_text_with_sendinput_unicode(
        target,
        settings,
        window_guard_func=lambda: basic_send_window_guard(hwnd),
    )


def open_chat(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
    session_key: str = "",
) -> bool:
    screenshot, ocr_items = ensure_main_session_list(hwnd, artifact_dir=artifact_dir)
    geometry = get_window_geometry(hwnd)
    session_click_x = session_click_x_for_geometry(geometry)
    search_x, search_y = search_box_point_for_geometry(geometry)
    surface = target_switch_surface_state(screenshot, ocr_items, geometry=geometry)
    if not surface.get("ok"):
        return False
    if not ocr_items:
        # OCR unavailable is not permission to probe the UI. Searching/clicking
        # blindly after an unreadable screenshot is a high-risk RPA pattern.
        return False
    clean_session_key = str(session_key or "").strip()
    if not clean_session_key and active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        return True
    if (
        clean_session_key
        and str(_LAST_RPA_ACTION_STATE.get("active_session_key") or "") == clean_session_key
        and active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact)
    ):
        return True
    sessions = parse_sessions_from_ocr(ocr_items, screenshot.size, screenshot=screenshot)
    if clean_session_key and active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        if visible_session_name_is_unambiguous(sessions, target, exact=exact):
            _LAST_RPA_ACTION_STATE["active_session_key"] = clean_session_key
            _LAST_RPA_ACTION_STATE["active_target"] = target
            return True
        return False
    if clean_session_key:
        keyed = find_session_candidate_by_key(sessions, clean_session_key)
        if keyed is None:
            return False
        opened = activate_session_candidate(
            hwnd,
            keyed,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        )
        if opened:
            _LAST_RPA_ACTION_STATE["active_session_key"] = clean_session_key
            _LAST_RPA_ACTION_STATE["active_target"] = target
        return opened
    for item in sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        return activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        )

    if not target_search_fallback_enabled():
        return False

    # Search is the highest-risk cross-chat path. Do it at most once per open,
    # then click a visible OCR result instead of blindly pressing Enter/Down.
    clear_sidebar_search_box_without_select_all(hwnd, search_x, search_y, target_hint=target)
    input_result = type_sidebar_search_query(hwnd, target)
    if not input_result.get("ok"):
        return False
    time.sleep(random.uniform(0.45, 0.75))
    search_shot, search_path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat_search_results")
    search_items = run_ocr(search_shot)
    surface = target_switch_surface_state(search_shot, search_items, geometry=geometry, screenshot_path=search_path)
    if not surface.get("ok"):
        return False
    if not search_items:
        return False
    if active_chat_matches(search_items, search_shot.size, target=target, exact=exact):
        return True
    search_sessions = parse_sessions_from_ocr(search_items, search_shot.size, screenshot=search_shot)
    for item in search_sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        return activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        )

    if target_search_enter_fallback_enabled():
        key_press(win32con.VK_RETURN)
        time.sleep(random.uniform(0.45, 0.7))
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if active_send_guard_is_strong(validation):
            return True
        if target_switch_validation_is_hard_stop(validation):
            return False

    # Re-scan and try a direct sidebar click once more after search.
    retry_shot, _retry_path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat_retry")
    retry_items = run_ocr(retry_shot)
    surface = target_switch_surface_state(retry_shot, retry_items, geometry=geometry)
    if not surface.get("ok"):
        return False
    if not retry_items:
        return False
    retry_sessions = parse_sessions_from_ocr(retry_items, retry_shot.size, screenshot=retry_shot)
    for item in retry_sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        return activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        )
    return False


def ensure_target_ready_for_send(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
    max_attempts: int | None = None,
    session_key: str = "",
) -> dict[str, Any]:
    attempts = target_ready_attempt_count(max_attempts)
    last_validation: dict[str, Any] = {}
    clean_session_key = str(session_key or "").strip()
    for attempt in range(1, attempts + 1):
        # Fast path: when we are already on the correct chat, avoid the extra
        # open-chat traversal and send immediately after a strong title guard.
        # Weak/sidebar/body matches are not enough to authorize typing because
        # multi-session/group chats may show the target name inside the body.
        pre_validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if pre_validation.get("ok") and active_send_guard_is_strong(pre_validation):
            opened_by_session_confirm = False
            if clean_session_key:
                cached_session_match = str(_LAST_RPA_ACTION_STATE.get("active_session_key") or "") == clean_session_key
                if not cached_session_match:
                    opened = open_chat(hwnd, target, exact=exact, artifact_dir=artifact_dir, session_key=clean_session_key)
                    if not opened:
                        return {
                            "ok": False,
                            "attempts": attempt,
                            "validation": pre_validation,
                            "opened": False,
                            "reason": "session_key_not_confirmed_by_active_cache",
                        }
                    opened_by_session_confirm = bool(opened)
                    humanized_action_sleep(180, 320)
                    validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
                    if not validation.get("ok") or not active_send_guard_is_strong(validation):
                        return {"ok": False, "attempts": attempt, "validation": validation, "opened": True}
                    pre_validation = validation
                _LAST_RPA_ACTION_STATE["active_session_key"] = clean_session_key
                _LAST_RPA_ACTION_STATE["active_target"] = target
            return {"ok": True, "attempts": attempt, "validation": pre_validation, "opened": opened_by_session_confirm}
        last_validation = pre_validation
        if target_switch_validation_is_hard_stop(pre_validation):
            return {"ok": False, "attempts": attempt, "validation": pre_validation, "hard_stop": True}

        opened = open_chat(hwnd, target, exact=exact, artifact_dir=artifact_dir, session_key=clean_session_key)
        humanized_action_sleep(280 + attempt * 90, 440 + attempt * 150)
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if validation.get("ok") and active_send_guard_is_strong(validation):
            return {"ok": True, "attempts": attempt, "validation": validation, "opened": bool(opened)}
        last_validation = validation
        if target_switch_validation_is_hard_stop(validation):
            return {"ok": False, "attempts": attempt, "validation": validation, "hard_stop": True}
        # Do not loop back into another open_chat/candidate click after a
        # failed target switch.  In recent WeChat builds, clicking the already
        # selected left-session row a second time can collapse/hide the chat
        # bubble pane.  Treat the first unconfirmed switch as a safe failure and
        # let the scheduler retry in a later low-frequency round.
        return {
            "ok": False,
            "attempts": attempt,
            "validation": last_validation,
            "opened": bool(opened),
            "reason": "target_not_confirmed_after_single_switch_attempt",
            "double_click_guard": True,
        }
    return {"ok": False, "attempts": attempts, "validation": last_validation}


def active_send_guard_is_strong(validation: dict[str, Any] | None) -> bool:
    if not isinstance(validation, dict) or validation.get("ok") is not True:
        return False
    confidence = str(validation.get("confirmation_confidence") or "")
    return confidence in {"active_title_strict"}


def validate_active_send_target(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    geometry = get_window_geometry(hwnd)
    geometry_check = validate_send_geometry(geometry)
    if not geometry_check.get("ok"):
        return {**geometry_check, "online": True, "geometry": geometry}
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="send_guard")
    ocr_items = run_ocr(screenshot)
    if not ocr_items:
        blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
        if blank_render.get("detected"):
            return {
                "ok": False,
                "online": False,
                "reason": "blank_render",
                "state": "blank_render_detected",
                "geometry": geometry,
                "screenshot_path": path,
                "render_probe": blank_render,
                "error": "WeChat render is blank; block blind send and recover the window before automation.",
            }
        if allow_blind_target_confirmation(target):
            return {
                "ok": True,
                "online": True,
                "reason": "target_confirm_skipped_no_ocr",
                "blind_send": True,
                "requested_target": target,
                "confirmed_target": "",
                "confirmation_confidence": "none",
                "geometry": geometry,
                "screenshot_path": path,
            }
        return {
            "ok": False,
            "online": True,
            "reason": "ocr_capture_unavailable",
            "requested_target": target,
            "confirmed_target": "",
            "confirmation_confidence": "none",
            "geometry": geometry,
            "screenshot_path": path,
            "error": "No OCR text was captured from WeChat; target confirmation is unavailable.",
        }
    if quick_login_like(ocr_items, geometry=geometry):
        return {
            "ok": False,
            "online": False,
            "reason": "login_or_qr",
            "state": "login_window_detected",
            "geometry": geometry,
            "screenshot_path": path,
            "error": "WeChat quick-login view detected; enter WeChat before sending.",
        }
    auxiliary_shell = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    if auxiliary_shell.get("detected"):
        return {
            "ok": False,
            "online": False,
            "reason": "auxiliary_shell_window",
            "state": "auxiliary_shell_window_detected",
            "geometry": geometry,
            "screenshot_path": path,
            "shell_probe": auxiliary_shell,
            "error": "Selected WeChat window looks like an auxiliary shell, not the requested chat.",
        }
    blocking_reason = blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason in {"login_or_qr"} else True,
            "reason": blocking_reason,
            "geometry": geometry,
            "screenshot_path": path,
            "error": f"WeChat send guard found blocking screen: {blocking_reason}",
        }
    if not active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        blind_guard = blind_target_confirmation_guard(
            target=target,
            exact=exact,
            ocr_items=ocr_items,
            image_size=screenshot.size,
            geometry=geometry,
            screenshot_path=path,
        )
        if blind_guard.get("ok"):
            return blind_guard
        return {
            "ok": False,
            "online": True,
            "reason": "target_title_not_confirmed",
            "requested_target": target,
            "confirmed_target": "",
            "confirmation_confidence": "failed",
            "geometry": geometry,
            "screenshot_path": path,
            "error": "The active chat title did not match the requested target.",
        }
    return {
        "ok": True,
        "online": True,
        "reason": "target_confirmed",
        "requested_target": target,
        "confirmed_target": target,
        "confirmation_confidence": "active_title_strict",
        "geometry": geometry,
        "screenshot_path": path,
    }


def validate_post_send_target(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
) -> dict[str, Any]:
    """Lightweight post-send guard.

    Pre-send already enforces strict target confirmation. Post-send primarily
    needs to detect hard failures (blank render / lost window). We therefore
    use a fast path first and only fall back to strict OCR confirmation when
    the fast probe is inconclusive.
    """
    if env_flag(
        "WECHAT_WIN32_OCR_POST_SEND_STRICT_CONFIRM",
        default=DEFAULT_POST_SEND_STRICT_CONFIRM,
    ):
        return validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)

    geometry = get_window_geometry(hwnd)
    geometry_check = validate_send_geometry(geometry)
    if not geometry_check.get("ok"):
        return {**geometry_check, "online": True, "geometry": geometry}

    focus_guard = basic_send_window_guard(hwnd)
    if not focus_guard.get("ok"):
        return validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)

    try:
        screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="send_post_guard_fast")
    except Exception:
        return validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)

    blank_render = detect_blank_render(screenshot, [], geometry=geometry)
    if blank_render.get("detected"):
        return {
            "ok": False,
            "online": False,
            "reason": "blank_render",
            "state": "blank_render_detected",
            "geometry": geometry,
            "screenshot_path": path,
            "render_probe": blank_render,
            "error": "WeChat render is blank after send.",
        }
    return {
        "ok": True,
        "online": True,
        "reason": "send_window_readable_after_send",
        "requested_target": target,
        "confirmed_target": "",
        "confirmation_confidence": "post_send_window_probe_only",
        "geometry": geometry,
        "screenshot_path": path,
        "post_send_fast_guard": True,
    }


def get_window_geometry(hwnd: int) -> dict[str, int]:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return {
        "left": int(left),
        "top": int(top),
        "right": int(right),
        "bottom": int(bottom),
        "width": int(right - left),
        "height": int(bottom - top),
    }


def get_window_client_geometry(hwnd: int) -> dict[str, int]:
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (left, top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (right, bottom))
        return {
            "left": int(left),
            "top": int(top),
            "right": int(right),
            "bottom": int(bottom),
            "width": int(right - left),
            "height": int(bottom - top),
            "screen_left": int(screen_left),
            "screen_top": int(screen_top),
            "screen_right": int(screen_right),
            "screen_bottom": int(screen_bottom),
        }
    except Exception as exc:
        return {"error": repr(exc)}


def add_friend_device_profile(
    hwnd: int,
    *,
    geometry: dict[str, Any] | None = None,
    screenshot_size: tuple[int, int] | None = None,
    route: str = "",
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "platform": "windows",
        "route": str(route or ""),
        "window_rect": dict(geometry or {}),
        "client_rect": {},
        "screenshot_size": list(screenshot_size) if screenshot_size else [],
        "dpi_scale": 1.0,
        "dpi": 96,
        "screen": {},
        "virtual_screen": {},
        "monitors": [],
    }
    try:
        profile["client_rect"] = get_window_client_geometry(hwnd)
    except Exception as exc:
        profile["client_rect"] = {"error": repr(exc)}
    try:
        scale = window_dpi_scale(hwnd)
        profile["dpi_scale"] = round(float(scale), 4)
        profile["dpi"] = int(round(float(scale) * 96))
    except Exception as exc:
        profile["dpi_error"] = repr(exc)
    try:
        user32 = ctypes.windll.user32
        profile["screen"] = {
            "width": int(user32.GetSystemMetrics(0)),
            "height": int(user32.GetSystemMetrics(1)),
        }
        profile["virtual_screen"] = {
            "left": int(user32.GetSystemMetrics(76)),
            "top": int(user32.GetSystemMetrics(77)),
            "width": int(user32.GetSystemMetrics(78)),
            "height": int(user32.GetSystemMetrics(79)),
        }
    except Exception as exc:
        profile["screen_error"] = repr(exc)
    try:
        monitors = []
        for monitor in win32api.EnumDisplayMonitors():
            _handle, _hdc, rect = monitor
            left, top, right, bottom = rect
            monitors.append(
                {
                    "left": int(left),
                    "top": int(top),
                    "right": int(right),
                    "bottom": int(bottom),
                    "width": int(right - left),
                    "height": int(bottom - top),
                }
            )
        profile["monitors"] = monitors
        profile["monitor_count"] = len(monitors)
    except Exception as exc:
        profile["monitor_error"] = repr(exc)
        profile["monitor_count"] = 0
    return profile


def validate_capture_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    left = int(geometry.get("left") or 0)
    top = int(geometry.get("top") or 0)
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if left <= OFFSCREEN_GEOMETRY_BOUNDARY or top <= OFFSCREEN_GEOMETRY_BOUNDARY:
        return {
            "ok": False,
            "reason": "window_offscreen_or_minimized",
            "geometry": geometry,
            "error": f"WeChat window is offscreen/minimized: left={left}, top={top}, size={width}x{height}.",
        }
    if width < MIN_CAPTURE_WINDOW_WIDTH or height < MIN_CAPTURE_WINDOW_HEIGHT:
        return {
            "ok": False,
            "reason": "window_too_small_for_capture",
            "geometry": geometry,
            "error": f"WeChat window is too small for reliable capture: {width}x{height}.",
        }
    return {"ok": True, "reason": "capture_geometry_ok", "geometry": geometry}


def validate_send_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width < MIN_SEND_CLIENT_WIDTH or height < MIN_SEND_CLIENT_HEIGHT:
        return {
            "ok": False,
            "reason": "window_too_small_for_safe_send",
            "geometry": geometry,
            "error": f"WeChat window is too small for safe send: {width}x{height}.",
        }
    return {"ok": True, "reason": "geometry_ok", "geometry": geometry}


def calculate_send_points(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_check = validate_send_geometry(geometry)
    if not geometry_check.get("ok"):
        return geometry_check
    client_width = int(geometry["width"])
    client_height = int(geometry["height"])
    input_x = int(client_width * 0.65)
    input_y = client_height - 96
    send_x = client_width - 62
    send_y = client_height - 44
    if input_y < client_height * 0.80 or send_y < client_height * 0.82:
        return {
            "ok": False,
            "reason": "send_points_outside_input_area",
            "geometry": geometry,
            "error": "Calculated send points are outside the expected input area.",
        }
    if input_x <= session_split_x(client_width) or send_x <= session_split_x(client_width):
        return {
            "ok": False,
            "reason": "send_points_inside_session_list",
            "geometry": geometry,
            "error": "Calculated send points overlap the session list.",
        }
    input_candidates = input_click_candidate_points(geometry, min_points=10)
    send_candidates = send_click_candidate_points(geometry, min_points=10)
    return {
        "ok": True,
        "input_point": [input_x, input_y],
        "send_point": [send_x, send_y],
        "input_candidate_points": [list(point) for point in input_candidates],
        "send_candidate_points": [list(point) for point in send_candidates],
        "geometry": geometry,
    }


def _spread_points_in_rect(
    left: int,
    top: int,
    right: int,
    bottom: int,
    *,
    min_points: int = 10,
) -> list[tuple[int, int]]:
    if right <= left or bottom <= top:
        return []
    x_fracs = (0.12, 0.24, 0.38, 0.52, 0.66, 0.80, 0.90, 0.30, 0.46, 0.72)
    y_fracs = (0.22, 0.48, 0.74, 0.34, 0.62, 0.82, 0.42, 0.68, 0.18, 0.56)
    points: list[tuple[int, int]] = []
    for x_frac, y_frac in zip(x_fracs, y_fracs):
        point = (
            bounded_int(int(left + (right - left) * x_frac), default=left, minimum=left, maximum=right),
            bounded_int(int(top + (bottom - top) * y_frac), default=top, minimum=top, maximum=bottom),
        )
        if point not in points:
            points.append(point)
    while len(points) < max(1, int(min_points or 1)):
        point = (random.randint(left, right), random.randint(top, bottom))
        if point not in points:
            points.append(point)
    random.shuffle(points)
    return points


def input_click_candidate_points(geometry: dict[str, Any], *, min_points: int = 10) -> list[tuple[int, int]]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return []
    split_x = session_split_x(width)
    # Keep randomized focus clicks safely inside the input pane.  A wider
    # candidate pool is useful for anti-repeat behavior, but the left edge must
    # not drift into the message area or session list on compact WeChat windows.
    left = max(split_x + 64, int(width * 0.55) + 1)
    right = min(width - 96, max(left + 120, int(width * 0.88)))
    top = max(int(height * 0.84), height - 126)
    bottom = min(height - 76, max(top + 30, height - 86))
    return _spread_points_in_rect(left, top, right, bottom, min_points=min_points)


def send_click_candidate_points(geometry: dict[str, Any], *, min_points: int = 10) -> list[tuple[int, int]]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return []
    split_x = session_split_x(width)
    left = max(split_x + 80, width - 132)
    right = max(left + 24, width - 24)
    top = max(int(height * 0.80), height - 88)
    bottom = max(top + 18, height - 18)
    return _spread_points_in_rect(left, top, right, bottom, min_points=min_points)


def jitter_input_click_point(x: int, y: int, geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return int(x), int(y)
    candidates = input_click_candidate_points(geometry, min_points=10)
    if candidates:
        x, y = random.choice(candidates)
    jitter_x = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_POINT_JITTER_X"),
        default=24,
        minimum=0,
        maximum=60,
    )
    jitter_y = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_POINT_JITTER_Y"),
        default=14,
        minimum=0,
        maximum=36,
    )
    split_x = session_split_x(width)
    safe_min_x = max(split_x + 64, int(width * 0.55) + 1)
    safe_max_x = max(safe_min_x, width - 88)
    safe_min_y = max(int(height * 0.84), height - 126)
    safe_max_y = max(safe_min_y, height - 76)
    jittered_x = bounded_int(
        int(x) + random.randint(-jitter_x, jitter_x),
        default=int(x),
        minimum=safe_min_x,
        maximum=safe_max_x,
    )
    jittered_y = bounded_int(
        int(y) + random.randint(-jitter_y, jitter_y),
        default=int(y),
        minimum=safe_min_y,
        maximum=safe_max_y,
    )
    return jittered_x, jittered_y


def rpa_click_surface_jitter_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_CLICK_SURFACE_JITTER_ENABLED", default=True)


def jitter_client_click_surface_point(hwnd: int, x: int, y: int) -> tuple[int, int, dict[str, Any]]:
    """Apply a final low-risk spread so fixed caller coordinates do not leak through."""
    original_x = int(x)
    original_y = int(y)
    if not rpa_click_surface_jitter_enabled():
        return original_x, original_y, {"enabled": False, "original": [original_x, original_y], "final": [original_x, original_y]}
    role = "generic"
    jitter_x = 3
    jitter_y = 2
    min_x = 0
    min_y = 0
    max_x = max(0, original_x + jitter_x)
    max_y = max(0, original_y + jitter_y)
    try:
        geometry = get_window_geometry(hwnd)
        width = int(geometry.get("width") or 0)
        height = int(geometry.get("height") or 0)
        if width > 0 and height > 0:
            split_x = session_split_x(width)
            max_x = max(0, width - 1)
            max_y = max(0, height - 1)
            if original_x > split_x + 40 and original_y > int(height * 0.70):
                role = "input_area"
                jitter_x = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_INPUT_JITTER_X"),
                    default=12,
                    minimum=0,
                    maximum=36,
                )
                jitter_y = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_INPUT_JITTER_Y"),
                    default=7,
                    minimum=0,
                    maximum=20,
                )
                min_x = max(split_x + 35, int(width * 0.48))
                max_x = min(width - 78, max(min_x, original_x + max(jitter_x, 1)))
                min_y = max(int(height * 0.73), height - 228)
                max_y = min(height - 82, max(min_y, original_y + max(jitter_y, 1)))
            elif original_x < split_x and original_y > 86:
                role = "session_or_sidebar"
                jitter_x = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_SESSION_JITTER_X"),
                    default=9,
                    minimum=0,
                    maximum=24,
                )
                jitter_y = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_SESSION_JITTER_Y"),
                    default=6,
                    minimum=0,
                    maximum=16,
                )
                min_x = 65
                max_x = max(min_x, min(split_x - 38, original_x + max(jitter_x, 1)))
                min_y = 84
                max_y = max(min_y, min(height - 20, original_y + max(jitter_y, 1)))
            elif original_x < split_x and original_y <= 86:
                role = "search_or_header"
                jitter_x = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_HEADER_JITTER_X"),
                    default=3,
                    minimum=0,
                    maximum=8,
                )
                jitter_y = bounded_int(
                    os.getenv("WECHAT_WIN32_OCR_CLICK_SURFACE_HEADER_JITTER_Y"),
                    default=2,
                    minimum=0,
                    maximum=5,
                )
                min_x = 70
                max_x = max(min_x, min(split_x - 28, original_x + max(jitter_x, 1)))
                min_y = 38
                max_y = max(min_y, min(88, original_y + max(jitter_y, 1)))
    except Exception:
        pass
    final_x = bounded_int(
        original_x + random.randint(-jitter_x, jitter_x),
        default=original_x,
        minimum=max(0, min_x),
        maximum=max(max_x, min_x),
    )
    final_y = bounded_int(
        original_y + random.randint(-jitter_y, jitter_y),
        default=original_y,
        minimum=max(0, min_y),
        maximum=max(max_y, min_y),
    )
    return final_x, final_y, {
        "enabled": True,
        "role": role,
        "original": [original_x, original_y],
        "final": [final_x, final_y],
        "jitter": [jitter_x, jitter_y],
    }


def jitter_screen_click_surface_point(x: int, y: int) -> tuple[int, int, dict[str, Any]]:
    original_x = int(x)
    original_y = int(y)
    if not rpa_click_surface_jitter_enabled():
        return original_x, original_y, {"enabled": False, "original": [original_x, original_y], "final": [original_x, original_y]}
    jitter_x = bounded_int(os.getenv("WECHAT_WIN32_OCR_SCREEN_CLICK_JITTER_X"), default=3, minimum=0, maximum=8)
    jitter_y = bounded_int(os.getenv("WECHAT_WIN32_OCR_SCREEN_CLICK_JITTER_Y"), default=2, minimum=0, maximum=6)
    final_x = max(0, original_x + random.randint(-jitter_x, jitter_x))
    final_y = max(0, original_y + random.randint(-jitter_y, jitter_y))
    return final_x, final_y, {
        "enabled": True,
        "role": "screen",
        "original": [original_x, original_y],
        "final": [final_x, final_y],
        "jitter": [jitter_x, jitter_y],
    }


def jitter_window_image_click_surface_point(hwnd: int, x: int, y: int) -> tuple[int, int, dict[str, Any]]:
    original_x = int(x)
    original_y = int(y)
    if not rpa_click_surface_jitter_enabled():
        return original_x, original_y, {"enabled": False, "original": [original_x, original_y], "final": [original_x, original_y]}
    role = "window_image"
    jitter_x = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_CLICK_JITTER_X"), default=5, minimum=0, maximum=16)
    jitter_y = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_CLICK_JITTER_Y"), default=4, minimum=0, maximum=12)
    min_x = 0
    min_y = 0
    max_x = max(0, original_x + jitter_x)
    max_y = max(0, original_y + jitter_y)
    try:
        geometry = get_window_geometry(hwnd)
        width = int(geometry.get("width") or 0)
        height = int(geometry.get("height") or 0)
        if width > 0 and height > 0:
            split_x = session_split_x(width)
            max_x = max(0, width - 1)
            max_y = max(0, height - 1)
            if original_x < split_x and original_y <= 92:
                role = "search_or_header_window"
                jitter_x = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_HEADER_JITTER_X"), default=7, minimum=0, maximum=18)
                jitter_y = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_HEADER_JITTER_Y"), default=5, minimum=0, maximum=14)
                min_x = 55
                max_x = max(min_x, min(split_x - 22, original_x + max(jitter_x, 1)))
                min_y = 34
                max_y = max(min_y, min(98, original_y + max(jitter_y, 1)))
                search_x, _search_y = search_box_point_for_geometry(geometry)
                windows_plus_x, windows_plus_y = add_friend_windows_plus_button_point_for_geometry(geometry)
                is_windows_plus_entry = (
                    abs(original_x - windows_plus_x) <= 20
                    and abs(original_y - windows_plus_y) <= 18
                    and original_x >= search_x + 130
                )
                if original_x >= split_x - 34 or is_windows_plus_entry:
                    role = "plus_entry_button"
                    jitter_x = bounded_int(os.getenv("WECHAT_WIN32_OCR_PLUS_ENTRY_JITTER_X"), default=3, minimum=0, maximum=8)
                    jitter_y = bounded_int(os.getenv("WECHAT_WIN32_OCR_PLUS_ENTRY_JITTER_Y"), default=3, minimum=0, maximum=8)
                    if is_windows_plus_entry:
                        min_x = max(55, original_x - 10)
                        max_x = min(split_x - 22, original_x + 10)
                    else:
                        min_x = max(55, split_x - 34)
                        max_x = max(min_x, min(split_x - 8, original_x + max(jitter_x, 1)))
                    min_y = max(34, original_y - 8)
                    max_y = max(min_y, min(108, original_y + max(jitter_y, 1)))
            elif original_x < split_x:
                role = "session_or_sidebar_window"
                jitter_x = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_SESSION_JITTER_X"), default=8, minimum=0, maximum=20)
                jitter_y = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_IMAGE_SESSION_JITTER_Y"), default=5, minimum=0, maximum=14)
                min_x = 65
                max_x = max(min_x, min(split_x - 30, original_x + max(jitter_x, 1)))
                min_y = 82
                max_y = max(min_y, min(height - 22, original_y + max(jitter_y, 1)))
    except Exception:
        pass
    final_x = bounded_int(
        original_x + random.randint(-jitter_x, jitter_x),
        default=original_x,
        minimum=max(0, min_x),
        maximum=max(max_x, min_x),
    )
    final_y = bounded_int(
        original_y + random.randint(-jitter_y, jitter_y),
        default=original_y,
        minimum=max(0, min_y),
        maximum=max(max_y, min_y),
    )
    return final_x, final_y, {
        "enabled": True,
        "role": role,
        "original": [original_x, original_y],
        "final": [final_x, final_y],
        "jitter": [jitter_x, jitter_y],
    }


def jitter_send_click_point(x: int, y: int, geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return int(x), int(y)
    candidates = send_click_candidate_points(geometry, min_points=10)
    if candidates:
        x, y = random.choice(candidates)
    jitter_x = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_SEND_POINT_JITTER_X"),
        default=6,
        minimum=0,
        maximum=16,
    )
    jitter_y = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_SEND_POINT_JITTER_Y"),
        default=5,
        minimum=0,
        maximum=14,
    )
    split_x = session_split_x(width)
    safe_min_x = max(split_x + 80, width - 132)
    safe_max_x = max(safe_min_x, width - 20)
    safe_min_y = max(int(height * 0.80), height - 92)
    safe_max_y = max(safe_min_y, height - 16)
    jittered_x = bounded_int(
        int(x) + random.randint(-jitter_x, jitter_x),
        default=int(x),
        minimum=safe_min_x,
        maximum=safe_max_x,
    )
    jittered_y = bounded_int(
        int(y) + random.randint(-jitter_y, jitter_y),
        default=int(y),
        minimum=safe_min_y,
        maximum=safe_max_y,
    )
    return jittered_x, jittered_y


def blocking_screen_reason(ocr_items: list[dict[str, Any]]) -> str:
    texts = [normalize_ocr_text(item.get("text")) for item in ocr_items if normalize_ocr_text(item.get("text"))]
    joined = "\n".join(texts)
    login_card_tokens = (
        "进入微信",
        "切换账号",
        "仅传输文件",
    )
    qr_login_tokens = (
        "扫码登录",
        "二维码登录",
        "扫描二维码登录",
        "请使用微信扫描二维码",
        "手机确认登录",
    )
    if sum(1 for token in login_card_tokens if token in joined) >= 2:
        return "login_or_qr"
    if any(token in joined for token in qr_login_tokens):
        return "login_or_qr"
    for token in HARD_BLOCKING_SCREEN_TOKENS:
        if token in joined:
            return f"blocking_text:{token}"
    chat_surface_tokens = (
        "搜索",
        "文件传输助手",
        "发送",
        "聊天",
        "通讯录",
        "订阅号",
        "朋友圈",
        "小程序",
        "视频号",
    )
    has_chat_surface = any(token in text for text in texts for token in chat_surface_tokens)
    compact_text_count = len([text for text in texts if text])
    token_items = [
        item
        for item in ocr_items
        if any(token in normalize_ocr_text(item.get("text")) for token in SOFT_BLOCKING_SCREEN_TOKENS)
    ]
    # Soft safety words can appear in normal chat bubbles. Only treat them as
    # global blockers when the capture looks like a sparse/login/dialog page,
    # not when the normal WeChat chat surface is visible behind the text.
    soft_page_like = (
        bool(token_items)
        and not has_chat_surface
        and (
            compact_text_count <= 8
            or any(180 <= float(item.get("center_y") or 0) <= 720 for item in token_items)
        )
    )
    if soft_page_like:
        for token in SOFT_BLOCKING_SCREEN_TOKENS:
            if token in joined:
                return f"blocking_text:{token}"
    return ""


def reserve_send_rate(*, target: str, text: str) -> dict[str, Any]:
    if env_flag("WECHAT_WIN32_OCR_SEND_RATE_GUARD", default=True) is False:
        return {"ok": True, "guard_disabled": True}
    now_ts = time.time()
    min_interval = env_int("WECHAT_WIN32_OCR_SEND_MIN_INTERVAL_SECONDS", DEFAULT_SEND_MIN_INTERVAL_SECONDS)
    burst_window = env_int("WECHAT_WIN32_OCR_SEND_BURST_WINDOW_SECONDS", DEFAULT_SEND_BURST_WINDOW_SECONDS)
    burst_limit = env_int("WECHAT_WIN32_OCR_SEND_BURST_LIMIT", DEFAULT_SEND_BURST_LIMIT)
    state = read_send_guard_state()
    decision = send_rate_decision(
        state,
        target=target,
        now_ts=now_ts,
        min_interval_seconds=min_interval,
        burst_window_seconds=burst_window,
        burst_limit=burst_limit,
    )
    if not decision.get("ok"):
        return decision
    events = [
        item
        for item in state.get("events", [])
        if isinstance(item, dict) and now_ts - float(item.get("at") or 0) <= max(burst_window, min_interval, 1)
    ]
    events.append(
        {
            "target": target,
            "at": now_ts,
            "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
        }
    )
    write_send_guard_state({"events": events, "updated_at": now_ts})
    return decision


def send_rate_decision(
    state: dict[str, Any],
    *,
    target: str,
    now_ts: float,
    min_interval_seconds: int,
    burst_window_seconds: int,
    burst_limit: int,
) -> dict[str, Any]:
    events = [item for item in state.get("events", []) if isinstance(item, dict)]
    target_events = [item for item in events if str(item.get("target") or "") == target]
    if min_interval_seconds > 0 and target_events:
        last_at = max(float(item.get("at") or 0) for item in target_events)
        elapsed = now_ts - last_at
        if elapsed < min_interval_seconds:
            return {
                "ok": False,
                "reason": "min_interval_not_elapsed",
                "min_interval_seconds": min_interval_seconds,
                "wait_seconds": round(min_interval_seconds - elapsed, 2),
                "error": "win32_ocr fallback send is too frequent for this target.",
            }
    if burst_window_seconds > 0 and burst_limit > 0:
        recent = [
            item
            for item in target_events
            if now_ts - float(item.get("at") or 0) <= burst_window_seconds
        ]
        if len(recent) >= burst_limit:
            oldest = min(float(item.get("at") or 0) for item in recent)
            return {
                "ok": False,
                "reason": "burst_limit_reached",
                "burst_limit": burst_limit,
                "burst_window_seconds": burst_window_seconds,
                "wait_seconds": round(max(0.0, burst_window_seconds - (now_ts - oldest)), 2),
                "error": "win32_ocr fallback send burst limit reached.",
            }
    return {
        "ok": True,
        "reason": "rate_ok",
        "min_interval_seconds": min_interval_seconds,
        "burst_window_seconds": burst_window_seconds,
        "burst_limit": burst_limit,
    }


def read_send_guard_state() -> dict[str, Any]:
    try:
        payload = json.loads(SEND_GUARD_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {"events": []}
    return payload if isinstance(payload, dict) else {"events": []}


def write_send_guard_state(payload: dict[str, Any]) -> None:
    SEND_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = SEND_GUARD_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, SEND_GUARD_PATH)


def env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def rpa_action_pacing_enabled() -> bool:
    return env_flag("WECHAT_WIN32_OCR_UI_ACTION_PACING_ENABLED", default=True)


def ui_action_kind(action: str) -> str:
    name = str(action or "").strip().lower()
    if name in {"key_press", "hotkey", "sendinput_unicode_unit"} or name.startswith("keyboard_"):
        return "keyboard"
    if "scroll" in name or "wheel" in name:
        return "scroll"
    if "activate" in name or "focus" in name:
        return "focus"
    if "click" in name or "mouse" in name:
        return "mouse"
    return "other"


def ui_action_point(metadata: dict[str, Any] | None) -> tuple[int, int] | None:
    if not isinstance(metadata, dict):
        return None
    if isinstance(metadata.get("point"), list) and len(metadata["point"]) >= 2:
        try:
            return int(metadata["point"][0]), int(metadata["point"][1])
        except (TypeError, ValueError):
            return None
    jitter = metadata.get("jitter") if isinstance(metadata.get("jitter"), dict) else {}
    final = jitter.get("final") if isinstance(jitter.get("final"), list) else None
    if final and len(final) >= 2:
        try:
            return int(final[0]), int(final[1])
        except (TypeError, ValueError):
            return None
    if "x" in metadata and "y" in metadata:
        try:
            return int(metadata.get("x")), int(metadata.get("y"))
        except (TypeError, ValueError):
            return None
    return None


def ui_action_min_gap_ms(kind: str) -> int:
    if kind == "keyboard":
        return max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_KEYBOARD_MIN_GAP_MS", DEFAULT_UI_ACTION_KEYBOARD_MIN_GAP_MS))
    if kind == "scroll":
        return max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_SCROLL_MIN_GAP_MS", DEFAULT_UI_ACTION_SCROLL_MIN_GAP_MS))
    if kind == "focus":
        return max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_FOCUS_MIN_GAP_MS", DEFAULT_UI_ACTION_FOCUS_MIN_GAP_MS))
    if kind == "mouse":
        return max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_MOUSE_MIN_GAP_MS", DEFAULT_UI_ACTION_MOUSE_MIN_GAP_MS))
    return max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_MIN_GAP_MS", 70))


def count_recent_near_point_actions(
    events: list[dict[str, Any]],
    *,
    point: tuple[int, int],
    now_ts: float,
    radius: int,
    window_seconds: float,
) -> int:
    px, py = point
    count = 0
    cutoff = now_ts - max(0.1, float(window_seconds))
    for item in events:
        try:
            ts = float(item.get("ts") or 0.0)
        except (TypeError, ValueError):
            continue
        if ts < cutoff:
            continue
        meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        candidate = ui_action_point(meta)
        if candidate is None:
            continue
        cx, cy = candidate
        if abs(cx - px) <= radius and abs(cy - py) <= radius:
            count += 1
    return count


def coordinate_rpa_action(
    action: str,
    *,
    metadata: dict[str, Any] | None = None,
    recent_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    kind = ui_action_kind(action)
    if not rpa_action_pacing_enabled():
        return {"enabled": False, "kind": kind, "delay_ms": 0}
    now = time.time()
    delay_ms = 0
    reasons: list[str] = []
    last_ts = float(_LAST_RPA_ACTION_STATE.get("ts") or 0.0)
    last_kind = str(_LAST_RPA_ACTION_STATE.get("kind") or "")
    if last_ts > 0:
        elapsed_ms = max(0.0, (now - last_ts) * 1000.0)
        min_gap = ui_action_min_gap_ms(kind)
        if kind != last_kind and {kind, last_kind} & {"mouse", "keyboard", "scroll"}:
            min_gap = max(min_gap, env_int("WECHAT_WIN32_OCR_UI_ACTION_KIND_SWITCH_GAP_MS", DEFAULT_UI_ACTION_KIND_SWITCH_GAP_MS))
            reasons.append(f"kind_switch:{last_kind}->{kind}")
        if elapsed_ms < min_gap:
            delay_ms = max(delay_ms, int(min_gap - elapsed_ms) + random.randint(18, 70))
            if not reasons:
                reasons.append(f"{kind}_min_gap")
    point = ui_action_point(metadata)
    if kind in {"mouse", "scroll"} and point is not None:
        radius = max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_NEAR_POINT_RADIUS_PX", DEFAULT_UI_ACTION_NEAR_POINT_RADIUS_PX))
        gap_ms = max(0, env_int("WECHAT_WIN32_OCR_UI_ACTION_NEAR_POINT_GAP_MS", DEFAULT_UI_ACTION_NEAR_POINT_GAP_MS))
        soft_limit = max(1, env_int("WECHAT_WIN32_OCR_UI_ACTION_NEAR_POINT_SOFT_LIMIT", DEFAULT_UI_ACTION_NEAR_POINT_SOFT_LIMIT))
        events = recent_events if isinstance(recent_events, list) else []
        near_count = count_recent_near_point_actions(
            events,
            point=point,
            now_ts=now,
            radius=radius,
            window_seconds=max(1.0, gap_ms / 1000.0 * 3.0),
        )
        last_point = _LAST_RPA_ACTION_STATE.get("point")
        if (
            isinstance(last_point, list)
            and len(last_point) >= 2
            and abs(int(last_point[0]) - point[0]) <= radius
            and abs(int(last_point[1]) - point[1]) <= radius
        ):
            delay_ms = max(delay_ms, gap_ms + random.randint(90, 260))
            reasons.append("near_point_repeat")
        if near_count >= soft_limit:
            delay_ms = max(delay_ms, gap_ms + random.randint(240, 680))
            reasons.append(f"near_point_soft_limit:{near_count}")
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    _LAST_RPA_ACTION_STATE.update(
        {
            "ts": time.time(),
            "kind": kind,
            "action": str(action or "unknown"),
            "point": list(point) if point is not None else None,
        }
    )
    return {
        "enabled": True,
        "kind": kind,
        "delay_ms": delay_ms,
        "reasons": reasons,
    }


def active_ui_action_budget_decision(
    *,
    action: str,
    metadata: dict[str, Any] | None = None,
    now_ts: float | None = None,
    reserve: bool = True,
) -> dict[str, Any]:
    if not env_flag("WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENABLED", default=True):
        return {"ok": True, "enabled": False, "action": action}
    now = float(now_ts if now_ts is not None else time.time())
    window_seconds = env_int(
        "WECHAT_WIN32_OCR_UI_ACTION_BUDGET_WINDOW_SECONDS",
        DEFAULT_UI_ACTION_BUDGET_WINDOW_SECONDS,
    )
    limit = env_int("WECHAT_WIN32_OCR_UI_ACTION_BUDGET_LIMIT", DEFAULT_UI_ACTION_BUDGET_LIMIT)
    window_seconds = max(1, int(window_seconds))
    limit = max(1, int(limit))
    events: list[dict[str, Any]] = []
    if UI_ACTION_GUARD_PATH.exists():
        try:
            payload = json.loads(UI_ACTION_GUARD_PATH.read_text(encoding="utf-8"))
            raw_events = payload.get("events", []) if isinstance(payload, dict) else []
            events = [item for item in raw_events if isinstance(item, dict)]
        except (OSError, json.JSONDecodeError):
            events = []
    cutoff = now - float(window_seconds)
    kept = []
    for item in events:
        try:
            ts = float(item.get("ts") or 0.0)
        except (TypeError, ValueError):
            ts = 0.0
        if ts >= cutoff:
            kept.append(item)
    pacing = coordinate_rpa_action(action, metadata=metadata, recent_events=kept) if reserve else {"enabled": rpa_action_pacing_enabled(), "kind": ui_action_kind(action), "delay_ms": 0}
    now = float(now_ts if now_ts is not None else time.time())
    cutoff = now - float(window_seconds)
    kept = [
        item
        for item in kept
        if float(item.get("ts") or 0.0) >= cutoff
    ]
    allowed = len(kept) < limit
    decision = {
        "ok": allowed,
        "enabled": True,
        "action": action,
        "count": len(kept),
        "limit": limit,
        "window_seconds": window_seconds,
        "pacing": pacing,
    }
    if reserve and allowed:
        kept.append({"ts": now, "action": str(action or "unknown"), "metadata": metadata or {}, "kind": ui_action_kind(action)})
    if reserve or len(kept) != len(events):
        try:
            UI_ACTION_GUARD_PATH.parent.mkdir(parents=True, exist_ok=True)
            UI_ACTION_GUARD_PATH.write_text(
                json.dumps({"events": kept[-max(limit * 2, limit):]}, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    return decision


def record_ui_action(action: str, *, decision: dict[str, Any] | None = None, metadata: dict[str, Any] | None = None) -> None:
    if not env_flag("WECHAT_WIN32_OCR_UI_ACTION_AUDIT_ENABLED", default=True):
        return
    payload = {
        "ts": time.time(),
        "action": str(action or "unknown"),
        "ok": bool((decision or {}).get("ok", True)),
        "decision": decision or {},
        "metadata": metadata or {},
    }
    try:
        UI_ACTION_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with UI_ACTION_AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError:
        return


def require_active_ui_action_budget(action: str, *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    decision = active_ui_action_budget_decision(action=action, metadata=metadata, reserve=True)
    record_ui_action(action, decision=decision, metadata=metadata)
    if not decision.get("ok") and env_flag("WECHAT_WIN32_OCR_UI_ACTION_BUDGET_ENFORCE", default=True):
        raise RuntimeError(f"ui_action_budget_exceeded:{action}:{decision.get('count')}/{decision.get('limit')}")
    return decision


def active_chat_matches(ocr_items: list[dict[str, Any]], image_size: tuple[int, int], *, target: str, exact: bool) -> bool:
    if not target:
        return False
    normalized_target = normalize_session_name(target)
    if not normalized_target:
        return False
    width, height = image_size
    split_x = session_split_x(width)
    title_left = active_chat_title_left_x(width)
    title_right = active_chat_title_right_x(width)
    title_top = active_chat_title_top_y(height)
    title_bottom = active_chat_title_bottom_y(height)
    x_tolerance = 24
    y_tolerance = 8
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        if item["right"] < split_x + 8:
            continue
        if item["center_x"] < title_left - x_tolerance or item["center_x"] > title_right + x_tolerance:
            continue
        if item["center_y"] < title_top - y_tolerance or item["center_y"] > title_bottom + y_tolerance:
            continue
        if item["top"] < title_top - 16 or item["bottom"] > title_bottom + 18:
            continue
        candidates = {
            text,
            strip_chat_unread_suffix(text),
            re.sub(r"^[：:.\s]+", "", text).strip(),
            normalize_chat_title_for_match(text),
        }
        for candidate in candidates:
            if session_name_matches(candidate, normalized_target, exact=exact):
                return True
    return False


def target_switch_passive_confirm_attempts() -> int:
    return bounded_int(
        os.getenv("WECHAT_WIN32_OCR_TARGET_SWITCH_PASSIVE_CONFIRM_ATTEMPTS"),
        default=2,
        minimum=1,
        maximum=4,
    )


def scroll_chat_history(hwnd: int, load_times: int, *, wheel_units: int = 8, delay_seconds: float = 0.18) -> None:
    rect = win32gui.GetWindowRect(hwnd)
    x = max(380, int((rect[2] - rect[0]) * 0.6)) + random.randint(-12, 12)
    y = max(180, int((rect[3] - rect[1]) * 0.45)) + random.randint(-10, 10)
    require_active_ui_action_budget(
        "scroll_chat_history",
        metadata={
            "load_times": int(load_times or 0),
            "cursor": [int(x), int(y)],
            "wheel_units": int(wheel_units or 0),
        },
    )
    activate_window(hwnd)
    ensure_left_button_released()
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
    win32api.SetCursorPos((screen_x, screen_y))
    humanized_action_sleep(45, 110)
    wheel_message = getattr(win32con, "WM_MOUSEWHEEL", 0x020A)
    lparam = ((int(screen_y) & 0xFFFF) << 16) | (int(screen_x) & 0xFFFF)
    for _ in range(max(0, load_times)):
        units = max(1, int(wheel_units or 1) + random.choice([-1, 0, 1]))
        delta = int(units * 120)
        try:
            win32gui.PostMessage(hwnd, wheel_message, (delta & 0xFFFF) << 16, lparam)
        except Exception:
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        base_ms = max(0, int(float(delay_seconds) * 1000))
        humanized_action_sleep(max(35, int(base_ms * 0.65)), max(70, int(base_ms * 1.45)))
    ensure_left_button_released()


def scroll_chat_to_latest(hwnd: int, *, attempts: int = 16) -> None:
    requested_attempts = max(0, int(attempts or 0))
    spread = 2 if requested_attempts >= 10 else 1
    actual_attempts = max(1, requested_attempts + random.randint(-spread, spread))
    rect = win32gui.GetWindowRect(hwnd)
    x = max(380, int((rect[2] - rect[0]) * 0.6)) + random.randint(-12, 12)
    y = max(180, int((rect[3] - rect[1]) * 0.55)) + random.randint(-10, 10)
    require_active_ui_action_budget(
        "scroll_chat_to_latest",
        metadata={"attempts": requested_attempts, "actual_attempts": actual_attempts, "cursor": [int(x), int(y)]},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
    win32api.SetCursorPos((screen_x, screen_y))
    humanized_action_sleep(45, 110)
    wheel_message = getattr(win32con, "WM_MOUSEWHEEL", 0x020A)
    lparam = ((int(screen_y) & 0xFFFF) << 16) | (int(screen_x) & 0xFFFF)
    for _ in range(actual_attempts):
        delta = int(-random.randint(5, 7) * 120)
        try:
            win32gui.PostMessage(hwnd, wheel_message, (delta & 0xFFFF) << 16, lparam)
        except Exception:
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        humanized_action_sleep(85, 180)
    ensure_left_button_released()


def capture_wechat(hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat") -> tuple[Any, str]:
    image = capture_window_image(hwnd)
    if image is None:
        candidates = capture_window_by_rect(hwnd)
        if not candidates:
            raise RuntimeError("capture_wechat_failed: no screenshot candidate is available")
        image = max(candidates, key=image_information_score)
    saved = save_screenshot_artifact(image, artifact_dir=artifact_dir, label=label)
    return image, saved


def capture_wechat_visible_rect(hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat_visible") -> tuple[Any, str]:
    candidates = capture_window_by_rect(hwnd)
    if candidates:
        image = max(candidates, key=image_information_score)
    else:
        image = capture_window_image(hwnd)
    if image is None:
        raise RuntimeError("capture_wechat_visible_rect_failed: no screenshot candidate is available")
    saved = save_screenshot_artifact(image, artifact_dir=artifact_dir, label=label)
    return image, saved


def capture_visible_screen(*, artifact_dir: str | None = None, label: str = "screen_visible") -> tuple[Any, str]:
    try:
        image = ImageGrab.grab()
    except Exception as exc:
        raise RuntimeError(f"capture_visible_screen_failed: {exc!r}") from exc
    saved = save_screenshot_artifact(image, artifact_dir=artifact_dir, label=label)
    return image, saved


def capture_wechat_window_visible_screen(hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat_window_visible") -> tuple[Any, str]:
    rect = win32gui.GetWindowRect(hwnd)
    image = try_image_grab((int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])))
    if image is None:
        raise RuntimeError("capture_wechat_window_visible_screen_failed")
    saved = save_screenshot_artifact(image, artifact_dir=artifact_dir, label=label)
    return image, saved


def capture_window_image(hwnd: int) -> Any | None:
    if win32ui is None or win32gui is None:
        return None
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = max(0, int(right - left))
    height = max(0, int(bottom - top))
    if width <= 2 or height <= 2:
        return None
    hwnd_dc = None
    src_dc = None
    mem_dc = None
    bitmap = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        if not hwnd_dc:
            return None
        src_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        mem_dc = src_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)

        user32 = ctypes.windll.user32
        # Prefer PW_RENDERFULLCONTENT(0x2), then fall back to classic mode.
        rendered = int(user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 0x2))
        if rendered != 1:
            rendered = int(user32.PrintWindow(hwnd, mem_dc.GetSafeHdc(), 0))
        if rendered != 1:
            return None

        bmpinfo = bitmap.GetInfo()
        bmpstr = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (int(bmpinfo["bmWidth"]), int(bmpinfo["bmHeight"])),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )
        return image
    except Exception:
        return None
    finally:
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass
        if mem_dc is not None:
            try:
                mem_dc.DeleteDC()
            except Exception:
                pass
        if src_dc is not None:
            try:
                src_dc.DeleteDC()
            except Exception:
                pass
        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass


def capture_window_by_rect(hwnd: int) -> list[Any]:
    rect = win32gui.GetWindowRect(hwnd)
    captures: list[Any] = []
    base = try_image_grab(rect)
    if base is not None:
        captures.append(base)
    scale = window_dpi_scale(hwnd)
    if scale > 1.05:
        scaled_down_rect = (
            int(round(float(rect[0]) / scale)),
            int(round(float(rect[1]) / scale)),
            int(round(float(rect[2]) / scale)),
            int(round(float(rect[3]) / scale)),
        )
        scaled_down = try_image_grab(scaled_down_rect)
        if scaled_down is not None:
            captures.append(scaled_down)
        scaled_rect = (
            int(round(float(rect[0]) * scale)),
            int(round(float(rect[1]) * scale)),
            int(round(float(rect[2]) * scale)),
            int(round(float(rect[3]) * scale)),
        )
        scaled = try_image_grab(scaled_rect)
        if scaled is not None:
            captures.append(scaled)
    return captures


def try_image_grab(rect: tuple[int, int, int, int]) -> Any | None:
    left, top, right, bottom = rect
    if int(right - left) <= 2 or int(bottom - top) <= 2:
        return None
    try:
        return ImageGrab.grab(bbox=rect)
    except Exception:
        return None


def window_dpi_scale(hwnd: int) -> float:
    try:
        user32 = ctypes.windll.user32
        dpi = int(user32.GetDpiForWindow(hwnd))
        if dpi > 0:
            return max(1.0, float(dpi) / 96.0)
    except Exception:
        pass
    return 1.0


def image_information_score(image: Any) -> float:
    try:
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        std = float(stat.stddev[0]) if stat.stddev else 0.0
        extrema = stat.extrema[0] if stat.extrema else (0, 0)
        contrast = float(extrema[1] - extrema[0])
        return std + contrast * 0.02
    except Exception:
        return 0.0


def run_ocr(image: Any) -> list[dict[str, Any]]:
    global _OCR_ENGINE
    if RapidOCR is None:
        raise RuntimeError(f"rapidocr_onnxruntime_unavailable: {_OCR_IMPORT_ERROR}")
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
    result, _ = _OCR_ENGINE(image)
    items: list[dict[str, Any]] = []
    for row in result or []:
        try:
            box, text, confidence = row
        except ValueError:
            continue
        clean = normalize_ocr_text(text)
        if not clean:
            continue
        try:
            conf = float(confidence)
        except (TypeError, ValueError):
            conf = 0.0
        if conf < OCR_MIN_CONFIDENCE:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        items.append(
            {
                "text": clean,
                "confidence": conf,
                "box": box,
                "left": min(xs),
                "right": max(xs),
                "top": min(ys),
                "bottom": max(ys),
                "center_x": sum(xs) / len(xs),
                "center_y": sum(ys) / len(ys),
            }
        )
    items.sort(key=lambda item: (float(item["top"]), float(item["left"])))
    if likely_foreign_overlay_capture(items):
        return []
    return items


def likely_foreign_overlay_capture(ocr_items: list[dict[str, Any]]) -> bool:
    if not ocr_items:
        return False
    joined = "\n".join(str(item.get("text") or "").lower() for item in ocr_items)
    hits = sum(1 for token in FOREIGN_CAPTURE_TOKENS if token in joined)
    return hits >= 2


def allow_blind_target_confirmation(target: str) -> bool:
    if env_flag("WECHAT_WIN32_OCR_ALLOW_BLIND_FILE_TRANSFER_SEND", default=False) is False:
        return False
    return is_file_transfer_session_alias(target)


def blind_target_confirmation_guard(
    *,
    target: str,
    exact: bool,
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    geometry: dict[str, Any],
    screenshot_path: str,
) -> dict[str, Any]:
    if not allow_blind_target_confirmation(target):
        return {"ok": False}
    sidebar_match_count = 0
    sidebar_sessions = parse_sessions_from_ocr(ocr_items, image_size)
    for session in sidebar_sessions:
        if session_name_matches(str(session.get("name") or ""), target, exact=exact):
            sidebar_match_count += 1
    if sidebar_match_count <= 0:
        return {"ok": False}
    return {
        "ok": True,
        "online": True,
        "reason": "target_confirm_skipped_title_ocr_drift",
        "blind_send": True,
        "requested_target": target,
        "confirmed_target": "",
        "confirmation_confidence": "weak_sidebar_only",
        "geometry": geometry,
        "screenshot_path": screenshot_path,
        "sidebar_match_count": sidebar_match_count,
    }


def parse_sessions_from_ocr(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    screenshot: Any | None = None,
) -> list[dict[str, Any]]:
    width, height = image_size
    split_x = session_split_x(width)
    min_header_y = chat_header_cutoff_y(height)
    left_min = max(42, int(width * 0.09))
    left_max = split_x - max(36, int(width * 0.07))
    right_limit = split_x + max(12, int(width * 0.03))
    candidates: list[dict[str, Any]] = []
    for item in ocr_items:
        text = str(item.get("text") or "").strip()
        if not is_session_name_candidate(text):
            continue
        if item["center_y"] < min_header_y or item["center_y"] > height - 20:
            continue
        if item["left"] < left_min or item["left"] > left_max:
            continue
        if item["right"] > right_limit:
            continue
        candidates.append(item)

    sessions: list[dict[str, Any]] = []
    last_y = -999.0
    min_session_row_gap = max(34, int(height * 0.048))
    name_counts: dict[str, int] = {}
    for item in sorted(candidates, key=lambda row: float(row["center_y"])):
        center_y = float(item["center_y"])
        if center_y - last_y < min_session_row_gap:
            continue
        name = normalize_session_name(str(item.get("text") or ""))
        # OCR occasionally glues sidebar timestamps into the session title
        # (e.g. "新数据测试昨天" or "新数据测试昨天19:23"),
        # which breaks session-target matching.
        name = strip_session_time_suffix(name)
        if is_file_transfer_session_alias(name):
            name = "文件传输助手"
        if not name:
            continue
        duplicate_index = int(name_counts.get(name, 0))
        name_counts[name] = duplicate_index + 1
        conversation_type = infer_conversation_type(name)
        row_fingerprint = session_row_fingerprint(item, duplicate_index=duplicate_index)
        sessions.append(
            {
                "name": name,
                "session_key": rpa_session_key(name, conversation_type=conversation_type, row_fingerprint=row_fingerprint),
                "conversation_type": conversation_type,
                "row_fingerprint": row_fingerprint,
                "duplicate_name_index": duplicate_index,
                "ambiguous_display_name": duplicate_index > 0,
                "confidence": item.get("confidence"),
                "center_y": center_y,
                "left": float(item.get("left") or 0),
                "right": float(item.get("right") or 0),
                "top": float(item.get("top") or 0),
                "bottom": float(item.get("bottom") or 0),
                "source_adapter": "win32_ocr",
            }
        )
        last_y = center_y
    enrich_sessions_with_sidebar_signals(
        sessions,
        ocr_items,
        image_size,
        screenshot=screenshot,
        min_header_y=min_header_y,
        split_x=split_x,
    )
    return sessions


def rpa_session_key(name: str, *, conversation_type: str = "unknown", row_fingerprint: dict[str, Any] | None = None) -> str:
    fingerprint = row_fingerprint if isinstance(row_fingerprint, dict) else {}
    duplicate = str(fingerprint.get("duplicate_discriminator") or "").strip()
    seed = json.dumps([str(conversation_type or "unknown"), str(name or ""), duplicate], ensure_ascii=False, sort_keys=True)
    return "wx:rpa:v1:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def session_row_fingerprint(item: dict[str, Any], *, duplicate_index: int = 0) -> dict[str, Any]:
    center_y = float(item.get("center_y") or 0)
    return {
        "title_text": normalize_session_name(str(item.get("text") or "")),
        "title_bbox": [
            int(float(item.get("left") or 0)),
            int(float(item.get("top") or 0)),
            int(float(item.get("right") or 0)),
            int(float(item.get("bottom") or 0)),
        ],
        "row_y_bucket": int(center_y // 8),
        "duplicate_name_index": int(duplicate_index or 0),
        "duplicate_discriminator": str(duplicate_index) if int(duplicate_index or 0) > 0 else "",
    }


def enrich_sessions_with_sidebar_signals(
    sessions: list[dict[str, Any]],
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    screenshot: Any | None,
    min_header_y: int,
    split_x: int,
) -> None:
    if not sessions:
        return
    _width, height = image_size
    centers = [float(item.get("center_y") or 0) for item in sessions]
    for index, session in enumerate(sessions):
        center_y = float(session.get("center_y") or 0)
        previous_y = centers[index - 1] if index > 0 else max(float(min_header_y), center_y - 42)
        next_y = centers[index + 1] if index + 1 < len(centers) else min(float(height - 18), center_y + 52)
        row_top = max(float(min_header_y), (previous_y + center_y) / 2.0 if index > 0 else center_y - 38)
        row_bottom = min(float(height - 18), (center_y + next_y) / 2.0 if index + 1 < len(centers) else center_y + 44)
        preview, time_text = session_preview_and_time(
            ocr_items,
            session,
            row_top=row_top,
            row_bottom=row_bottom,
            split_x=split_x,
        )
        unread = detect_visual_session_unread_badge(
            screenshot,
            session,
            row_top=row_top,
            row_bottom=row_bottom,
            split_x=split_x,
        )
        if preview:
            session["preview"] = preview
        if time_text:
            session["time"] = time_text
        if unread.get("detected"):
            session["unread_badge"] = "visual_red_dot"
            session["unread_badge_meta"] = unread
            fingerprint = session.get("row_fingerprint") if isinstance(session.get("row_fingerprint"), dict) else {}
            fingerprint["last_unread_badge_bbox"] = unread.get("bbox") or unread.get("bounds") or []
            session["row_fingerprint"] = fingerprint


def session_preview_and_time(
    ocr_items: list[dict[str, Any]],
    session: dict[str, Any],
    *,
    row_top: float,
    row_bottom: float,
    split_x: int,
) -> tuple[str, str]:
    name = str(session.get("name") or "")
    session_left = float(session.get("left") or 0)
    session_center_y = float(session.get("center_y") or 0)
    preview_parts: list[str] = []
    time_text = ""
    for item in sorted(ocr_items, key=lambda row: (float(row.get("center_y") or 0), float(row.get("left") or 0))):
        text = normalize_ocr_text(item.get("text"))
        if not text or text == name:
            continue
        center_y = float(item.get("center_y") or 0)
        if center_y < row_top or center_y > row_bottom:
            continue
        left = float(item.get("left") or 0)
        right = float(item.get("right") or 0)
        if right > split_x + 10:
            continue
        if is_session_time_text(text):
            if not time_text and left >= session_left + 60:
                time_text = text
            continue
        if center_y <= session_center_y + 6:
            continue
        if left < session_left - 12:
            continue
        if text in {name, "搜索", "新对话"}:
            continue
        preview_parts.append(text)
    preview = " ".join(preview_parts).strip()
    if len(preview) > 160:
        preview = preview[:160]
    return preview, time_text


def detect_visual_session_unread_badge(
    screenshot: Any | None,
    session: dict[str, Any],
    *,
    row_top: float,
    row_bottom: float,
    split_x: int,
) -> dict[str, Any]:
    if screenshot is None:
        return {"detected": False, "reason": "no_screenshot"}
    try:
        image = screenshot.convert("RGB")
    except Exception:
        return {"detected": False, "reason": "image_unavailable"}
    width, height = image.size
    session_left = float(session.get("left") or 0)
    center_y = float(session.get("center_y") or 0)
    # The unread dot sits near the avatar's upper-right corner, immediately
    # left of the OCR name text. Keep this crop narrow to avoid red avatars.
    left = max(0, int(session_left - 34))
    right = min(width, int(min(session_left + 8, split_x - 26)))
    top = max(0, int(max(row_top, center_y - 32)))
    bottom = min(height, int(min(row_bottom, center_y + 8)))
    if right <= left or bottom <= top:
        return {"detected": False, "reason": "empty_crop"}
    crop = image.crop((left, top, right, bottom))
    red_pixels: list[tuple[int, int]] = []
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b = crop.getpixel((x, y))
            if r >= 190 and g <= 125 and b <= 135 and (r - max(g, b)) >= 55:
                red_pixels.append((x, y))
    if len(red_pixels) < 10:
        return {"detected": False, "red_pixel_count": len(red_pixels), "crop": [left, top, right, bottom]}
    xs = [point[0] for point in red_pixels]
    ys = [point[1] for point in red_pixels]
    box_width = max(xs) - min(xs) + 1
    box_height = max(ys) - min(ys) + 1
    compact = 4 <= box_width <= 32 and 4 <= box_height <= 32
    return {
        "detected": bool(compact),
        "red_pixel_count": len(red_pixels),
        "red_box": [left + min(xs), top + min(ys), left + max(xs) + 1, top + max(ys) + 1],
        "crop": [left, top, right, bottom],
        "reason": "visual_red_dot" if compact else "red_pixels_not_compact",
    }


def parse_messages_from_ocr(ocr_items: list[dict[str, Any]], image_size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
    width, height = image_size
    split_x = session_split_x(width)
    header_cutoff = chat_header_cutoff_y(height)
    geometry = {"left": 0, "top": 0, "right": width, "bottom": height, "width": width, "height": height}
    bottom_exclude_px = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_MESSAGE_BOTTOM_EXCLUDE_PX"),
        default=max(DEFAULT_MESSAGE_BOTTOM_EXCLUDE_PX, int(height * 0.10)),
        minimum=60,
        maximum=max(180, int(height * 0.22)),
    )
    merge_vertical_gap = max(28, int(height * 0.03))
    rows: list[dict[str, Any]] = []
    for item in ocr_items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        if item["center_y"] < header_cutoff:
            continue
        if item["center_y"] > height - bottom_exclude_px:
            continue
        if item["left"] < split_x - 5:
            continue
        if is_message_noise(text):
            continue
        side = classify_message_side(item, width=width)
        rect = {
            "left": int(float(item.get("left") or 0)),
            "top": int(float(item.get("top") or 0)),
            "right": int(float(item.get("right") or 0)),
            "bottom": int(float(item.get("bottom") or 0)),
        }
        # The composer draft box lives above the send button, not only in the
        # final bottom strip.  Exclude left/unknown-side OCR there so failed or
        # partial drafts cannot be fed back to the LLM as customer messages.
        if side != "self" and rect_in_input_area(rect, geometry):
            continue
        rows.append({**item, "side": side})

    grouped: list[list[dict[str, Any]]] = []
    for item in sorted(rows, key=lambda row: (float(row["center_y"]), float(row["left"]))):
        side = str(item.get("side") or classify_message_side(item, width=width))
        if not grouped:
            grouped.append([{**item, "side": side}])
            continue
        previous = grouped[-1][-1]
        previous_side = str(previous.get("side") or "unknown")
        vertical_gap = float(item["top"]) - float(previous["bottom"])
        if previous_side == side and vertical_gap <= merge_vertical_gap:
            grouped[-1].append({**item, "side": side})
        else:
            grouped.append([{**item, "side": side}])

    messages: list[dict[str, Any]] = []
    for group in grouped:
        raw_content = "\n".join(str(item.get("text") or "").strip() for item in group if str(item.get("text") or "").strip())
        content = normalize_message_content(raw_content)
        if not content:
            continue
        side = str(group[0].get("side") or "unknown")
        y = float(group[0].get("center_y") or 0)
        rect = {
            "left": int(min(float(item.get("left") or 0) for item in group)),
            "top": int(min(float(item.get("top") or 0) for item in group)),
            "right": int(max(float(item.get("right") or 0) for item in group)),
            "bottom": int(max(float(item.get("bottom") or 0) for item in group)),
        }
        quality_flags: list[str] = []
        if len(group) > 1:
            gaps = [
                max(0.0, float(group[index].get("top") or 0) - float(group[index - 1].get("bottom") or 0))
                for index in range(1, len(group))
            ]
            avg_height = sum(max(1.0, float(item.get("bottom") or 0) - float(item.get("top") or 0)) for item in group) / len(group)
            if any(gap > max(18.0, avg_height * 1.8) for gap in gaps):
                quality_flags.append("multi_bubble_possible_merge")
        ocr_confidence = min(float(item.get("confidence") or 0) for item in group)
        digest = hashlib.sha1(f"{target}|{side}|{round(y)}|{content}".encode("utf-8")).hexdigest()[:16]
        record = {
            "id": f"win32_ocr:{digest}",
            "type": "text",
            "sender": "self" if side == "self" else "unknown",
            "sender_role": "self" if side == "self" else "unknown",
            "content": content,
            "content_raw_ocr": raw_content,
            "time": "",
            "source_adapter": "win32_ocr",
            "ocr_confidence": ocr_confidence,
            "bubble_rect": rect,
            "ocr_items": group,
            "quality_flags": quality_flags,
        }
        envelope = build_message_envelope(
            record,
            source_adapter="win32_ocr",
            conversation={"target_name": target, "conversation_type": "group" if "群" in str(target or "") else "unknown"},
            ocr_items=group,
            bubble_rect=rect,
        )
        message = apply_message_envelope_to_record(record, envelope)
        if str(message.get("content") or "").strip():
            messages.append(message)
    return messages


def classify_message_side(item: dict[str, Any], *, width: int) -> str:
    split_x = session_split_x(width)
    left = float(item.get("left") or 0)
    center_x = float(item.get("center_x") or 0)
    # Long right-side bubbles can have a center slightly left of the old 68%
    # cutoff. Their left edge is still safely to the right of normal inbound
    # bubbles, so prefer the left-edge cue to avoid replying to ourselves.
    self_left_min = max(float(split_x + 75), float(width) * 0.43)
    if left >= self_left_min:
        return "self"
    if center_x > float(width) * 0.68:
        return "self"
    return "unknown"


def probe_wechat_windows() -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    visible_windows: list[dict[str, Any]] = []
    main_windows: list[dict[str, Any]] = []
    visible_main_windows: list[dict[str, Any]] = []
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    process_query_limited_information = 0x1000

    def process_path(pid: int) -> str:
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def callback(hwnd: int, _lparam: int) -> bool:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        path = process_path(int(pid.value))
        if not path.lower().endswith("\\weixin.exe"):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        item = {
            "hwnd": int(hwnd),
            "pid": int(pid.value),
            "title": title_buffer.value,
            "class_name": class_buffer.value,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "path": path,
        }
        windows.append(item)
        if item["visible"]:
            visible_windows.append(item)
        if is_wechat_main_window(item):
            main_windows.append(item)
            if item["visible"]:
                visible_main_windows.append(item)
        return True

    user32.EnumWindows(enum_windows_proc(callback), 0)
    return {
        "windows": windows,
        "visible_windows": visible_windows,
        "main_windows": main_windows,
        "visible_main_windows": visible_main_windows,
        "visible_count": len(visible_windows),
        "main_count": len(main_windows),
        "visible_main_count": len(visible_main_windows),
    }


def select_primary_visible_main_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    visible = probe.get("visible_main_windows") or []
    if not visible:
        return None
    selected: dict[str, Any] | None = None
    selected_score: tuple[int, int, int, int, int] = (-1, -1, -1, -1, -1)
    enable_content_probe = len(visible) > 1 and env_flag(
        "WECHAT_WIN32_OCR_MULTI_WINDOW_CONTENT_PROBE",
        default=True,
    )
    for item in visible:
        hwnd = int(item.get("hwnd") or 0)
        if not hwnd:
            continue
        try:
            geometry = get_window_geometry(hwnd)
        except Exception:
            geometry = {"left": 0, "top": 0, "width": 0, "height": 0}
        area = max(0, int(geometry.get("width") or 0)) * max(0, int(geometry.get("height") or 0))
        capture_ready = 1 if validate_capture_geometry(geometry).get("ok") else 0
        content_score = window_content_health_score(hwnd, geometry) if enable_content_probe and capture_ready else 0
        safe_action_size = 1 if int(geometry.get("width") or 0) >= MIN_SEND_CLIENT_WIDTH and int(geometry.get("height") or 0) >= MIN_SEND_CLIENT_HEIGHT else 0
        score = (capture_ready, content_score, safe_action_size, area, wechat_window_title_score(item))
        if selected is None or score > selected_score:
            selected = {**dict(item), "geometry_hint": geometry, "content_health_score": content_score}
            selected_score = score
    if selected is not None:
        return selected
    return dict(visible[0])


def window_content_health_score(hwnd: int, geometry: dict[str, Any]) -> int:
    try:
        screenshot, _path = capture_wechat(hwnd, artifact_dir=None, label="window_select_probe")
        ocr_items = run_ocr(screenshot)
    except Exception:
        return 0
    blank_render = detect_blank_render(screenshot, ocr_items, geometry=geometry)
    if blank_render.get("detected"):
        return -100
    if quick_login_like(ocr_items, geometry=geometry):
        return -20
    auxiliary_shell = auxiliary_wechat_shell_like(ocr_items, geometry=geometry)
    if auxiliary_shell.get("detected"):
        return -50
    blocking_reason = blocking_screen_reason(ocr_items)
    if blocking_reason:
        return -10
    texts = [normalize_ocr_text(item.get("text")) for item in ocr_items if normalize_ocr_text(item.get("text"))]
    chat_tokens = ("搜索", "文件传输助手", "发送", "聊天", "通讯录")
    token_score = 15 if any(token in text for text in texts for token in chat_tokens) else 0
    return min(80, 20 + min(len(texts), 30) + token_score)


def ensure_visible_wechat_window(*, interactive: bool = True) -> dict[str, Any]:
    probe = probe_wechat_windows()
    if probe["visible_main_windows"]:
        usable_visible = probe_has_usable_visible_main_window(probe)
        if usable_visible and interactive:
            focused = focus_wechat_window(probe)
            if focused:
                humanized_action_sleep(150, 280)
                probe = probe_wechat_windows()
                probe["focused_window"] = focused
        elif not usable_visible:
            probe["visible_main_window_geometry_invalid"] = True
            if not interactive:
                return probe
            restored = restore_wechat_window(probe)
            if restored:
                humanized_action_sleep(650, 980)
                probe = probe_wechat_windows()
                probe["restored_window"] = restored
                focused = focus_wechat_window(probe)
                if focused:
                    humanized_action_sleep(150, 280)
                    probe = probe_wechat_windows()
                    probe["focused_window"] = focused
        return probe
    if not interactive:
        return probe
    if wechat_main_window_is_tray_hidden(probe):
        probe["main_window_in_tray"] = True
        probe["manual_action_required"] = "open_wechat_main_window"
        probe["restore_skipped_reason"] = "manual_tray_restore_required"
        return probe
    restored = restore_wechat_window(probe)
    if restored:
        humanized_action_sleep(650, 980)
        probe = probe_wechat_windows()
        probe["restored_window"] = restored
        focused = focus_wechat_window(probe)
        if focused:
            humanized_action_sleep(150, 280)
            probe = probe_wechat_windows()
            probe["focused_window"] = focused
    return probe


def wechat_main_window_is_tray_hidden(probe: dict[str, Any]) -> bool:
    """Detect WeChat running with only hidden/tray main windows.

    In this state, automatic ShowWindow/foreground recovery can surface a
    half-rendered shell and trigger blank-screen RPA failures. Prefer an
    explicit manual open by the operator before automation starts.
    """
    try:
        main_count = int(probe.get("main_count") or 0)
        visible_main_count = int(probe.get("visible_main_count") or 0)
    except Exception:
        return False
    return bool(main_count > 0 and visible_main_count <= 0)


def probe_has_usable_visible_main_window(probe: dict[str, Any]) -> bool:
    """Treat offscreen/minimized "visible" windows as not ready for RPA."""
    visible = probe.get("visible_main_windows") or []
    if not visible:
        return False
    checked = False
    for item in visible:
        hwnd = int(item.get("hwnd") or 0)
        if not hwnd:
            continue
        try:
            geometry = get_window_geometry(hwnd)
        except Exception:
            # Unit tests and exotic shell windows may not expose geometry. In
            # that case, keep the old non-invasive focus behavior.
            return True
        checked = True
        if validate_capture_geometry(geometry).get("ok"):
            return True
    return not checked


def restore_wechat_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    candidates = [item for item in (probe.get("windows") or []) if is_wechat_main_window(item)]
    candidates.sort(key=wechat_window_title_score, reverse=True)
    for item in candidates:
        hwnd = int(item.get("hwnd") or 0)
        if hwnd:
            activate_window(hwnd)
            return dict(item)
    return None


def focus_wechat_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    item = select_primary_visible_main_window(probe)
    if not item:
        return None
    hwnd = int(item.get("hwnd") or 0)
    if hwnd:
        activate_window(hwnd)
        try:
            focus_match = foreground_window_matches_target(hwnd)
            if (
                focus_match.get("ok")
                and str(focus_match.get("reason") or "") in {"foreground_matches_target", "foreground_root_matches_target"}
            ):
                return dict(item)
        except Exception:
            pass
    return None


def activate_window(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    if not hwnd:
        return
    aggressive_focus = env_flag("WECHAT_WIN32_OCR_AGGRESSIVE_FOCUS", default=False)
    attach_thread_input = aggressive_focus or env_flag("WECHAT_WIN32_OCR_ATTACH_THREAD_INPUT", default=False)
    try:
        if int(user32.IsIconic(hwnd)):
            user32.ShowWindow(hwnd, 9)
        elif not bool(user32.IsWindowVisible(hwnd)):
            user32.ShowWindow(hwnd, 5)
    except Exception:
        pass
    try:
        focus_match = foreground_window_matches_target(hwnd)
        if (
            focus_match.get("ok")
            and str(focus_match.get("reason") or "") in {"foreground_matches_target", "foreground_root_matches_target"}
        ):
            return
    except Exception:
        pass
    debounce_seconds = max(0.0, min(10.0, env_float("WECHAT_WIN32_OCR_ACTIVATE_DEBOUNCE_SECONDS", 2.5)))
    if debounce_seconds > 0:
        now_monotonic = time.monotonic()
        last_monotonic = float(_LAST_ACTIVATE_MONOTONIC_BY_HWND.get(int(hwnd)) or 0.0)
        if now_monotonic - last_monotonic <= debounce_seconds:
            try:
                if bool(user32.IsWindow(hwnd)) and bool(user32.IsWindowVisible(hwnd)) and not bool(user32.IsIconic(hwnd)):
                    # Only short-circuit when the target is already foreground.
                    # Otherwise we still need to execute a real foreground raise.
                    focus_match = foreground_window_matches_target(hwnd)
                    if (
                        focus_match.get("ok")
                        and str(focus_match.get("reason") or "") in {"foreground_matches_target", "foreground_root_matches_target"}
                    ):
                        return
            except Exception:
                pass
    require_active_ui_action_budget("activate_window", metadata={"hwnd": int(hwnd or 0)})
    if aggressive_focus:
        try:
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    fg_tid = 0
    target_tid = 0
    current_tid = 0
    attached_fg = False
    attached_current = False
    try:
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_tid = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
        target_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        current_tid = win32api.GetCurrentThreadId()
        if attach_thread_input and fg_tid and target_tid and fg_tid != target_tid:
            win32process.AttachThreadInput(fg_tid, target_tid, True)
            attached_fg = True
        if attach_thread_input and current_tid and target_tid and current_tid != target_tid:
            win32process.AttachThreadInput(current_tid, target_tid, True)
            attached_current = True
        win32gui.SetForegroundWindow(hwnd)
        win32gui.SetActiveWindow(hwnd)
        if aggressive_focus:
            win32gui.SetFocus(hwnd)
        # Only use TOPMOST flip as a compatibility fallback when explicitly enabled.
        if aggressive_focus:
            try:
                flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
                win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            except Exception:
                pass
        if aggressive_focus:
            humanized_action_sleep(70, 125)
        else:
            humanized_action_sleep(55, 95)
    except Exception:
        pass
    finally:
        _LAST_ACTIVATE_MONOTONIC_BY_HWND[int(hwnd)] = time.monotonic()
        if attached_fg:
            try:
                win32process.AttachThreadInput(fg_tid, target_tid, False)
            except Exception:
                pass
        if attached_current:
            try:
                win32process.AttachThreadInput(current_tid, target_tid, False)
            except Exception:
                pass
    if aggressive_focus:
        try:
            final_match = foreground_window_matches_target(hwnd)
        except Exception:
            final_match = {}
        if not (
            final_match.get("ok")
            and str(final_match.get("reason") or "") in {"foreground_matches_target", "foreground_root_matches_target"}
        ):
            # Foreground lock fallback: synthesize a tiny ALT keystroke before
            # SetForegroundWindow to satisfy Windows focus-stealing constraints.
            try:
                coordinate_rpa_action("key_press", metadata={"key": int(win32con.VK_MENU), "context": "focus_alt_down"})
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                humanized_action_sleep(25, 55)
                user32.SetForegroundWindow(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetActiveWindow(hwnd)
            except Exception:
                pass
            finally:
                try:
                    coordinate_rpa_action("key_press", metadata={"key": int(win32con.VK_MENU), "context": "focus_alt_up"})
                    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass
            humanized_action_sleep(60, 120)
            try:
                final_match = foreground_window_matches_target(hwnd)
            except Exception:
                final_match = {}
            if not (
                final_match.get("ok")
                and str(final_match.get("reason") or "") in {"foreground_matches_target", "foreground_root_matches_target"}
            ) and focus_click_fallback_enabled():
                try:
                    left, top, right, _bottom = win32gui.GetWindowRect(hwnd)
                    width = max(120, int(right - left))
                    title_x = int(left + min(max(88, width // 3), max(88, width - 88)))
                    title_y = int(top + 18)
                    click(title_x, title_y)
                    humanized_action_sleep(65, 130)
                except Exception:
                    pass


def configure_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def ensure_left_button_released() -> None:
    if win32api is None:
        return
    try:
        key_state = int(win32api.GetKeyState(getattr(win32con, "VK_LBUTTON", 0x01)))
    except Exception:
        return
    if key_state >= 0:
        return
    try:
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        humanized_action_sleep(8, 24)
    except Exception:
        pass


def client_click(hwnd: int, x: int, y: int) -> None:
    """Click a WeChat client coordinate without relying on global DPI math."""
    click_x, click_y, jitter_meta = jitter_client_click_surface_point(hwnd, int(x), int(y))
    require_active_ui_action_budget(
        "client_click",
        metadata={"hwnd": int(hwnd or 0), "x": click_x, "y": click_y, "jitter": jitter_meta},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    lparam = ((int(click_y) & 0xFFFF) << 16) | (int(click_x) & 0xFFFF)
    win32gui.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    humanized_action_sleep(20, 55)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    humanized_action_sleep(45, 100)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    humanized_action_sleep(80, 170)


def human_client_click(hwnd: int, x: int, y: int) -> None:
    """Move the real cursor with small jitter before clicking a client point."""
    click_x, click_y, jitter_meta = jitter_client_click_surface_point(hwnd, int(x), int(y))
    require_active_ui_action_budget(
        "human_client_click",
        metadata={"hwnd": int(hwnd or 0), "x": click_x, "y": click_y, "jitter": jitter_meta},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    left_down_sent = False
    try:
        screen_x, screen_y = client_to_screen(hwnd, int(click_x), int(click_y))
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(5, 9)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            jitter_x = random.randint(-2, 2) if step < steps else 0
            jitter_y = random.randint(-2, 2) if step < steps else 0
            next_x = int(start_x + (screen_x - start_x) * ease) + jitter_x
            next_y = int(start_y + (screen_y - start_y) * ease) + jitter_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.015, 0.045))
        time.sleep(random.uniform(0.04, 0.12))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        left_down_sent = True
        time.sleep(random.uniform(0.05, 0.12))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        left_down_sent = False
        time.sleep(random.uniform(0.12, 0.28))
    except Exception:
        # Some desktop policies deny SetCursorPos; fall back to PostMessage clicks.
        client_click(hwnd, click_x, click_y)
    finally:
        if left_down_sent:
            ensure_left_button_released()


def human_window_image_hover(hwnd: int, x: int, y: int) -> dict[str, Any]:
    """Move the real cursor toward a screenshot-space point without clicking."""
    target_x, target_y, jitter_meta = jitter_window_image_click_surface_point(hwnd, int(x), int(y))
    require_active_ui_action_budget(
        "human_window_image_hover",
        metadata={"hwnd": int(hwnd or 0), "x": target_x, "y": target_y, "jitter": jitter_meta},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    try:
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
        screen_x = int(left) + int(target_x)
        screen_y = int(top) + int(target_y)
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(8, 14)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            drift_x = random.randint(-3, 3) if step < steps else 0
            drift_y = random.randint(-3, 3) if step < steps else 0
            next_x = int(start_x + (screen_x - start_x) * ease) + drift_x
            next_y = int(start_y + (screen_y - start_y) * ease) + drift_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.018, 0.055))
        time.sleep(random.uniform(0.18, 0.55))
        return {"ok": True, "x": target_x, "y": target_y, "screen_x": screen_x, "screen_y": screen_y, "steps": steps, "jitter": jitter_meta}
    except Exception as exc:
        return {"ok": False, "x": target_x, "y": target_y, "error": repr(exc), "jitter": jitter_meta}


def human_window_image_click(hwnd: int, x: int, y: int) -> None:
    """Click a point measured in the same coordinate space as screenshots."""
    click_x, click_y, jitter_meta = jitter_window_image_click_surface_point(hwnd, int(x), int(y))
    require_active_ui_action_budget(
        "human_window_image_click",
        metadata={"hwnd": int(hwnd or 0), "x": click_x, "y": click_y, "jitter": jitter_meta},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    left_down_sent = False
    try:
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
        screen_x = int(left) + int(click_x)
        screen_y = int(top) + int(click_y)
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(5, 9)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            jitter_x = random.randint(-2, 2) if step < steps else 0
            jitter_y = random.randint(-2, 2) if step < steps else 0
            next_x = int(start_x + (screen_x - start_x) * ease) + jitter_x
            next_y = int(start_y + (screen_y - start_y) * ease) + jitter_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.015, 0.045))
        time.sleep(random.uniform(0.04, 0.12))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        left_down_sent = True
        time.sleep(random.uniform(0.05, 0.12))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        left_down_sent = False
        time.sleep(random.uniform(0.12, 0.28))
    except Exception:
        screen_x, screen_y = client_to_screen(hwnd, int(click_x), int(click_y))
        click(screen_x, screen_y)
    finally:
        if left_down_sent:
            ensure_left_button_released()


def human_window_image_click_in_bounds(
    hwnd: int,
    x: int,
    y: int,
    *,
    bounds: list[int],
    action_name: str = "human_window_image_click_in_bounds",
) -> dict[str, Any]:
    """Click a screenshot-space point, clamped to a known safe window rectangle."""
    raw_x, raw_y, jitter_meta = jitter_window_image_click_surface_point(hwnd, int(x), int(y))
    click_x, click_y = clamp_point_to_bounds(raw_x, raw_y, bounds)
    require_active_ui_action_budget(
        action_name,
        metadata={"hwnd": int(hwnd or 0), "x": click_x, "y": click_y, "bounds": bounds, "jitter": jitter_meta},
    )
    activate_window(hwnd)
    ensure_left_button_released()
    left_down_sent = False
    try:
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
        screen_x = int(left) + int(click_x)
        screen_y = int(top) + int(click_y)
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(6, 11)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            jitter_x = random.randint(-2, 2) if step < steps else 0
            jitter_y = random.randint(-2, 2) if step < steps else 0
            next_x = int(start_x + (screen_x - start_x) * ease) + jitter_x
            next_y = int(start_y + (screen_y - start_y) * ease) + jitter_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.016, 0.052))
        time.sleep(random.uniform(0.08, 0.22))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        left_down_sent = True
        time.sleep(random.uniform(0.055, 0.145))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        left_down_sent = False
        time.sleep(random.uniform(0.16, 0.34))
        return {
            "ok": True,
            "x": click_x,
            "y": click_y,
            "screen_x": screen_x,
            "screen_y": screen_y,
            "raw_x": raw_x,
            "raw_y": raw_y,
            "bounds": bounds,
            "steps": steps,
            "jitter": jitter_meta,
        }
    except Exception as exc:
        return {"ok": False, "x": click_x, "y": click_y, "bounds": bounds, "error": repr(exc), "jitter": jitter_meta}
    finally:
        if left_down_sent:
            ensure_left_button_released()


def human_screen_hover(x: int, y: int, *, action_name: str = "human_screen_hover") -> dict[str, Any]:
    """Move the real cursor toward a screen-space point without clicking."""
    target_x, target_y, jitter_meta = jitter_screen_click_surface_point(int(x), int(y))
    require_active_ui_action_budget(action_name, metadata={"x": target_x, "y": target_y, "jitter": jitter_meta})
    ensure_left_button_released()
    try:
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(10, 18)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            drift_x = random.randint(-3, 3) if step < steps else 0
            drift_y = random.randint(-3, 3) if step < steps else 0
            next_x = int(start_x + (target_x - start_x) * ease) + drift_x
            next_y = int(start_y + (target_y - start_y) * ease) + drift_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.018, 0.06))
        time.sleep(random.uniform(0.22, 0.68))
        return {"ok": True, "screen_x": target_x, "screen_y": target_y, "steps": steps, "jitter": jitter_meta}
    except Exception as exc:
        return {"ok": False, "screen_x": target_x, "screen_y": target_y, "error": repr(exc), "jitter": jitter_meta}


def human_screen_click(x: int, y: int, *, action_name: str = "human_screen_click") -> dict[str, Any]:
    """Click a screen-space point after a short human-like cursor movement."""
    target_x, target_y, jitter_meta = jitter_screen_click_surface_point(int(x), int(y))
    require_active_ui_action_budget(action_name, metadata={"x": target_x, "y": target_y, "jitter": jitter_meta})
    ensure_left_button_released()
    left_down_sent = False
    try:
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(4, 8)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            drift_x = random.randint(-2, 2) if step < steps else 0
            drift_y = random.randint(-2, 2) if step < steps else 0
            next_x = int(start_x + (target_x - start_x) * ease) + drift_x
            next_y = int(start_y + (target_y - start_y) * ease) + drift_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.016, 0.05))
        time.sleep(random.uniform(0.08, 0.22))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        left_down_sent = True
        time.sleep(random.uniform(0.055, 0.14))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        left_down_sent = False
        time.sleep(random.uniform(0.16, 0.34))
        return {"ok": True, "screen_x": target_x, "screen_y": target_y, "steps": steps, "jitter": jitter_meta}
    except Exception as exc:
        return {"ok": False, "screen_x": target_x, "screen_y": target_y, "error": repr(exc), "jitter": jitter_meta}
    finally:
        if left_down_sent:
            ensure_left_button_released()


def human_screen_click_in_bounds(
    x: int,
    y: int,
    *,
    bounds: list[int],
    action_name: str = "human_screen_click_in_bounds",
) -> dict[str, Any]:
    """Click a screen-space point, clamped to a known safe target rectangle."""
    raw_x, raw_y, jitter_meta = jitter_screen_click_surface_point(int(x), int(y))
    target_x, target_y = clamp_point_to_bounds(raw_x, raw_y, bounds)
    require_active_ui_action_budget(
        action_name,
        metadata={"x": target_x, "y": target_y, "bounds": bounds, "jitter": jitter_meta},
    )
    ensure_left_button_released()
    left_down_sent = False
    try:
        start_x, start_y = win32api.GetCursorPos()
        steps = random.randint(6, 11)
        for step in range(1, steps + 1):
            ratio = step / steps
            ease = ratio * ratio * (3 - 2 * ratio)
            drift_x = random.randint(-2, 2) if step < steps else 0
            drift_y = random.randint(-2, 2) if step < steps else 0
            next_x = int(start_x + (target_x - start_x) * ease) + drift_x
            next_y = int(start_y + (target_y - start_y) * ease) + drift_y
            win32api.SetCursorPos((next_x, next_y))
            time.sleep(random.uniform(0.016, 0.052))
        time.sleep(random.uniform(0.10, 0.24))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        left_down_sent = True
        time.sleep(random.uniform(0.06, 0.15))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        left_down_sent = False
        time.sleep(random.uniform(0.18, 0.36))
        return {
            "ok": True,
            "screen_x": target_x,
            "screen_y": target_y,
            "raw_screen_x": raw_x,
            "raw_screen_y": raw_y,
            "bounds": bounds,
            "steps": steps,
            "jitter": jitter_meta,
        }
    except Exception as exc:
        return {"ok": False, "screen_x": target_x, "screen_y": target_y, "bounds": bounds, "error": repr(exc), "jitter": jitter_meta}
    finally:
        if left_down_sent:
            ensure_left_button_released()


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(int(x), int(y))
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return int(point.x), int(point.y)


def click(x: int, y: int) -> None:
    click_x, click_y, jitter_meta = jitter_screen_click_surface_point(int(x), int(y))
    require_active_ui_action_budget("screen_click", metadata={"x": click_x, "y": click_y, "jitter": jitter_meta})
    ensure_left_button_released()
    win32api.SetCursorPos((int(click_x), int(click_y)))
    humanized_action_sleep(20, 55)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    humanized_action_sleep(35, 85)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    ensure_left_button_released()


def hotkey(modifier: int, key: int) -> None:
    coordinate_rpa_action("hotkey", metadata={"modifier": int(modifier), "key": int(key)})
    win32api.keybd_event(modifier, 0, 0, 0)
    humanized_action_sleep(16, 42)
    win32api.keybd_event(key, 0, 0, 0)
    humanized_action_sleep(18, 48)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)
    humanized_action_sleep(8, 28)


def key_press(key: int) -> None:
    coordinate_rpa_action("key_press", metadata={"key": int(key)})
    win32api.keybd_event(key, 0, 0, 0)
    humanized_action_sleep(24, 70)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    humanized_action_sleep(8, 26)


def is_wechat_main_window(item: dict[str, Any]) -> bool:
    title = normalize_wechat_title(str(item.get("title") or ""))
    class_name = str(item.get("class_name") or "").lower()
    if not title:
        return False
    if "qwindowicon" not in class_name and "wechatmainwndforpc" not in class_name:
        return False
    lowered = title.lower()
    if any(token in lowered for token in ("login", "qr", "update")) or any(token in title for token in ("登录", "扫码", "更新")):
        return False
    return any(token in title for token in ("微信", "Weixin", "WeChat")) or any(token in lowered for token in ("weixin", "wechat"))


def wechat_window_title_score(item: dict[str, Any]) -> int:
    title = normalize_wechat_title(str(item.get("title") or ""))
    lowered = title.lower()
    if title == "微信" or title.startswith("微信"):
        return 40
    if "微信" in title:
        return 35
    if lowered.startswith("wechat"):
        return 25
    if lowered.startswith("weixin"):
        return 10
    return 0


def normalize_wechat_title(title: str) -> str:
    text = str(title or "").strip()
    text = re.sub(r"^\(\d+\)\s*", "", text).strip()
    text = re.sub(r"^（\d+）\s*", "", text).strip()
    return text


def normalize_ocr_text(text: Any) -> str:
    clean = str(text or "").replace("\u3000", " ").strip()
    clean = re.sub(r"\s+", " ", clean)
    return clean


def normalize_session_name(text: str) -> str:
    clean = normalize_ocr_text(text)
    clean = re.sub(r"^[：:.\s]+", "", clean).strip()
    return clean


def strip_chat_unread_suffix(text: str) -> str:
    clean = normalize_ocr_text(text)
    if not clean:
        return ""
    return re.sub(r"\s*[\(（]\s*\d{1,4}\s*[\)）]\s*$", "", clean).strip()


def normalize_chat_title_for_match(text: str) -> str:
    clean = strip_chat_unread_suffix(normalize_session_name(text))
    if not clean:
        return ""
    compact = re.sub(r"[\s:：\-_·|]+", "", clean).strip().lower()
    if not compact:
        return ""
    prefixes = (
        "当前会话",
        "聊天对象",
        "与",
        "和",
        "跟",
        "chatwith",
        "conversationwith",
        "with",
    )
    suffixes = (
        "的聊天",
        "聊天窗口",
        "聊天",
        "会话",
        "对话",
        "chatwindow",
        "conversation",
        "chat",
    )
    changed = True
    while changed and compact:
        changed = False
        for token in prefixes:
            if compact.startswith(token) and len(compact) > len(token):
                compact = compact[len(token) :]
                changed = True
        for token in suffixes:
            if compact.endswith(token) and len(compact) > len(token):
                compact = compact[: -len(token)]
                changed = True
    return compact.strip()


def canonical_session_name(text: str) -> str:
    clean = normalize_session_name(text)
    if not clean:
        return ""
    collapsed = re.sub(r"[\s_\-:：()\[\]（）]+", "", clean).lower()
    if is_file_transfer_session_alias(clean, collapsed=collapsed):
        return "__file_transfer_assistant__"
    return collapsed


def is_file_transfer_session_alias(text: str, *, collapsed: str | None = None) -> bool:
    clean = normalize_session_name(text)
    if not clean:
        return False
    compact = re.sub(r"\s+", "", clean)
    if compact.startswith("文件传输助"):
        return True
    if compact.startswith("文件传输") and re.search(r"(\.{1,3}|…|今天|昨天|前天|\d{1,2}:\d{2})", compact):
        return True
    if compact in {"文件传输助手", "仅传输文件"}:
        return True
    english = collapsed
    if english is None:
        english = re.sub(r"[^a-z]", "", clean.lower())
    if not english:
        return False
    return english in {
        "filetransferassistant",
        "filetransfer",
        "transferassistant",
    }


def normalize_message_content(text: str) -> str:
    return str(text or "").strip()



def quick_login_like(ocr_items: list[dict[str, Any]], *, geometry: dict[str, Any]) -> bool:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    texts = [normalize_ocr_text(item.get("text")) for item in ocr_items if normalize_ocr_text(item.get("text"))]
    joined = "\\n".join(texts)
    login_tokens = ("进入微信", "切换账号", "仅传输文件")
    has_login_tokens = sum(1 for token in login_tokens if token in joined) >= 2
    likely_login_size = width <= LOGIN_WINDOW_MAX_WIDTH and height <= LOGIN_WINDOW_MAX_HEIGHT
    return bool(has_login_tokens and likely_login_size)


def ensure_quick_login_if_available(
    hwnd: int,
    *,
    artifact_dir: str | None = None,
    auto_enter: bool = DEFAULT_QUICK_LOGIN_AUTO_ENTER,
) -> dict[str, Any]:
    screenshot, path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="quick_login_probe")
    ocr_items = run_ocr(screenshot)
    geometry = get_window_geometry(hwnd)
    if not quick_login_like(ocr_items, geometry=geometry):
        return {
            "attempted": False,
            "detected": False,
            "geometry": geometry,
            "screenshot_path": path,
        }
    if not auto_enter:
        return {
            "attempted": False,
            "detected": True,
            "auto_enter_enabled": False,
            "geometry": geometry,
            "screenshot_path": path,
            "reason": "quick_login_detected_no_auto_enter",
        }
    enter_item = next((item for item in ocr_items if "进入微信" in str(item.get("text") or "")), None)
    if enter_item:
        click_x = int(float(enter_item.get("center_x") or (geometry["width"] * 0.5)))
        click_y = int(float(enter_item.get("center_y") or (geometry["height"] * 0.74)))
    else:
        click_x = int(geometry["width"] * 0.5)
        click_y = int(geometry["height"] * 0.74)
    human_client_click(hwnd, click_x, click_y)
    humanized_action_sleep(500, 850)
    return {
        "attempted": True,
        "detected": True,
        "auto_enter_enabled": True,
        "geometry": geometry,
        "click_point": [click_x, click_y],
        "screenshot_path": path,
        "reason": "quick_login_enter_clicked",
    }
def session_split_x(width: int) -> int:
    return max(300, min(370, int(width * 0.52)))


def chat_header_cutoff_y(height: int) -> int:
    return max(CHAT_HEADER_MAX_Y, min(150, int(height * 0.12)))


def active_chat_title_cutoff_y(height: int) -> int:
    return max(120, min(170, int(height * 0.18)))


def active_chat_title_top_cutoff_y(height: int) -> int:
    return max(92, min(122, int(height * 0.14)))


def active_chat_title_left_x(width: int) -> int:
    split_x = session_split_x(width)
    # Some WeChat builds keep the conversation body split near x=335 even
    # when the historical split heuristic caps at 370.  Use a left-tolerant
    # header ROI while relying on the title Y band to reject body speaker labels.
    return max(300, min(split_x + 24, int(width * 0.37)))


def active_chat_title_right_x(width: int) -> int:
    return min(width - 90, session_split_x(width) + max(330, int(width * 0.48)))


def active_chat_title_top_y(height: int) -> int:
    return max(44, min(68, int(height * 0.075)))


def active_chat_title_bottom_y(height: int) -> int:
    return max(102, min(140, int(height * 0.155)))


def search_box_point_for_geometry(geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    split_x = session_split_x(width)
    fallback_x, fallback_y = SEARCH_BOX_REL
    # WeChat's left sidebar keeps a relatively stable pixel layout across
    # window widths, so anchor search X to sidebar split instead of full width.
    search_x = bounded_int(int(split_x * 0.33), default=fallback_x, minimum=90, maximum=min(170, max(100, split_x - 48)))
    search_y = bounded_int(int(height * 0.075), default=fallback_y, minimum=48, maximum=130)
    return search_x, search_y


def session_click_x_for_geometry(geometry: dict[str, Any]) -> int:
    width = int(geometry.get("width") or 0)
    split_x = session_split_x(width)
    center_hint = int(split_x * 0.72)
    return bounded_int(center_hint, default=SESSION_CLICK_X, minimum=180, maximum=max(220, split_x - 40))


def normalize_wechat_window(hwnd: int) -> dict[str, Any]:
    enabled = env_flag("WECHAT_WIN32_OCR_WINDOW_NORMALIZE", default=True)
    before = get_window_geometry(hwnd)
    if not enabled:
        return {"ok": True, "enabled": False, "applied": False, "before": before}

    target_width = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_WINDOW_WIDTH"),
        default=DEFAULT_SAFE_WINDOW_WIDTH,
        minimum=MIN_SAFE_WINDOW_WIDTH,
        maximum=MAX_SAFE_WINDOW_WIDTH,
    )
    target_height = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_WINDOW_HEIGHT"),
        default=DEFAULT_SAFE_WINDOW_HEIGHT,
        minimum=MIN_SAFE_WINDOW_HEIGHT,
        maximum=MAX_SAFE_WINDOW_HEIGHT,
    )
    requested_target = {"width": target_width, "height": target_height}
    enforce_recommended = env_flag("WECHAT_WIN32_OCR_ENFORCE_RECOMMENDED_WINDOW", default=True)
    recommended_floor_applied = False
    if enforce_recommended:
        if target_width < DEFAULT_SAFE_WINDOW_WIDTH:
            target_width = DEFAULT_SAFE_WINDOW_WIDTH
            recommended_floor_applied = True
        if target_height < DEFAULT_SAFE_WINDOW_HEIGHT:
            target_height = DEFAULT_SAFE_WINDOW_HEIGHT
            recommended_floor_applied = True
    effective_target = {"width": target_width, "height": target_height}
    try:
        user32 = ctypes.windll.user32
        screen_width = int(user32.GetSystemMetrics(0) or 0)
        screen_height = int(user32.GetSystemMetrics(1) or 0)
        safe_width = min(target_width, max(640, screen_width - 12))
        safe_height = min(target_height, max(640, screen_height - 58))
        fixed_origin = env_flag("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", default=True)
        if fixed_origin:
            requested_left = bounded_int(
                os.getenv("WECHAT_WIN32_OCR_WINDOW_LEFT"),
                default=0,
                minimum=0,
                maximum=max(0, screen_width - safe_width),
            )
            requested_top = bounded_int(
                os.getenv("WECHAT_WIN32_OCR_WINDOW_TOP"),
                default=0,
                minimum=0,
                maximum=max(0, screen_height - safe_height),
            )
            left = requested_left
            top = requested_top
        else:
            left = min(max(0, int(before.get("left") or 0)), max(0, screen_width - safe_width))
            top = min(max(0, int(before.get("top") or 0)), max(0, screen_height - safe_height))
    except Exception:
        screen_width = 0
        screen_height = 0
        safe_width = target_width
        safe_height = target_height
        fixed_origin = env_flag("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", default=True)
        if fixed_origin:
            left = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_LEFT"), default=0, minimum=0, maximum=MAX_SAFE_WINDOW_WIDTH)
            top = bounded_int(os.getenv("WECHAT_WIN32_OCR_WINDOW_TOP"), default=0, minimum=0, maximum=MAX_SAFE_WINDOW_HEIGHT)
        else:
            left = max(0, int(before.get("left") or 0))
            top = max(0, int(before.get("top") or 0))

    width_diff = abs(int(before.get("width") or 0) - safe_width)
    height_diff = abs(int(before.get("height") or 0) - safe_height)
    left_diff = abs(int(before.get("left") or 0) - left)
    top_diff = abs(int(before.get("top") or 0) - top)
    if width_diff <= 6 and height_diff <= 6 and left_diff <= 4 and top_diff <= 4:
        return {
            "ok": True,
            "enabled": True,
            "applied": False,
            "before": before,
            "after": before,
            "target": effective_target,
            "requested_target": requested_target,
            "enforce_recommended": enforce_recommended,
            "recommended_floor_applied": recommended_floor_applied,
            "fixed_origin": fixed_origin,
            "screen": {"width": screen_width, "height": screen_height},
            "reason": "already_near_target",
        }

    try:
        win32gui.MoveWindow(hwnd, left, top, safe_width, safe_height, True)
        humanized_action_sleep(90, 180)
        after = get_window_geometry(hwnd)
        applied = (
            abs(int(after.get("width") or 0) - int(before.get("width") or 0)) > 4
            or abs(int(after.get("height") or 0) - int(before.get("height") or 0)) > 4
            or abs(int(after.get("left") or 0) - int(before.get("left") or 0)) > 4
            or abs(int(after.get("top") or 0) - int(before.get("top") or 0)) > 4
        )
        return {
            "ok": True,
            "enabled": True,
            "applied": applied,
            "before": before,
            "after": after,
            "target": effective_target,
            "requested_target": requested_target,
            "enforce_recommended": enforce_recommended,
            "recommended_floor_applied": recommended_floor_applied,
            "fixed_origin": fixed_origin,
            "screen": {"width": screen_width, "height": screen_height},
            "reason": "normalized" if applied else "move_attempt_no_change",
        }
    except Exception as exc:
        return {
            "ok": False,
            "enabled": True,
            "applied": False,
            "before": before,
            "target": effective_target,
            "requested_target": requested_target,
            "enforce_recommended": enforce_recommended,
            "recommended_floor_applied": recommended_floor_applied,
            "fixed_origin": fixed_origin,
            "error": repr(exc),
            "reason": "normalize_failed",
        }


def is_session_name_candidate(text: str) -> bool:
    if not text:
        return False
    if len(text) > 28:
        return False
    if text.startswith("["):
        return False
    if "搜索" in text or text in {"?", "？", "+", "..."}:
        return False
    if re.fullmatch(r"(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|星期.|(今天|昨天|前天)\s*\d{1,2}:\d{2})", text):
        return False
    if "..." in text or "…" in text:
        return False
    return True


def is_session_time_text(text: str) -> bool:
    return bool(
        re.fullmatch(
            r"(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|星期.|(今天|昨天|前天)\s*\d{1,2}:\d{2})",
            str(text or "").strip(),
        )
    )


def is_message_noise(text: str) -> bool:
    if re.fullmatch(r"(\d{1,2}:\d{2}|\d{1,2}/\d{1,2}|(今天|昨天|前天)\s*\d{1,2}:\d{2}|星期.\s*\d{1,2}:\d{2}|星期.)", text):
        return True
    if text in {"发送", "按住 Alt 说话"}:
        return True
    return False


def infer_conversation_type(name: str) -> str:
    if is_file_transfer_session_alias(name):
        return "file_transfer"
    if re.search(r"(群|群聊|测试|chatroom|room)", name, re.IGNORECASE):
        return "group"
    return "private"


def bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def args_for_daemon_request(request: dict[str, Any]) -> list[str]:
    action = str(request.get("action") or "").strip().lower()
    if action not in set(SIDECAR_ACTION_CHOICES):
        action = "status"
    argv: list[str] = [action]
    if bool(request.get("exact")):
        argv.append("--exact")
    target = str(request.get("target") or "").strip()
    if target:
        argv.extend(["--target", target])
    session_key = str(request.get("session_key") or "").strip()
    if session_key:
        argv.extend(["--session-key", session_key])
    text = str(request.get("text") or "")
    if action == "send" and text:
        argv.extend(["--text", text])
    for key, flag in (
        ("phone", "--phone"),
        ("wechat", "--wechat"),
    ):
        value = str(request.get(key) or "")
        if add_friend_route_accepts_query(action) and value:
            argv.extend([flag, value])
    for key, flag in (
        ("verify_message", "--verify-message"),
        ("remark_name", "--remark-name"),
        ("remark_code", "--remark-code"),
    ):
        value = str(request.get(key) or "")
        if add_friend_route_accepts_formal_fields(action) and value:
            argv.extend([flag, value])
    if bool(request.get("skip_send_rate_guard")):
        argv.append("--skip-send-rate-guard")
    if action in ADD_FRIEND_ROUTES and bool(request.get("calibration_only")):
        argv.append("--calibration-only")
    if action == "messages":
        numeric_flags = (
            ("history_load_times", "--history-load-times"),
            ("max_scroll_steps", "--max-scroll-steps"),
            ("max_duration_seconds", "--max-duration-seconds"),
            ("max_snapshots", "--max-snapshots"),
            ("min_delay_ms", "--min-delay-ms"),
            ("max_delay_ms", "--max-delay-ms"),
        )
        for key, flag in numeric_flags:
            if key in request:
                try:
                    value = int(request.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0
                argv.extend([flag, str(max(0, value))])
        history_mode = str(request.get("history_mode") or "").strip()
        if history_mode:
            argv.extend(["--history-mode", history_mode])
        for key, flag in (
            ("anchor_ids", "--anchor-id"),
            ("anchor_content_keys", "--anchor-content-key"),
            ("reply_content_keys", "--reply-content-key"),
        ):
            values = request.get(key)
            if isinstance(values, list):
                for item in values:
                    clean = str(item or "").strip()
                    if clean:
                        argv.extend([flag, clean])
        if request.get("restore_to_latest") is True:
            argv.append("--restore-to-latest")
        elif request.get("restore_to_latest") is False:
            argv.append("--no-restore-to-latest")
    artifact_dir = str(request.get("artifact_dir") or "").strip()
    if artifact_dir:
        argv.extend(["--artifact-dir", artifact_dir])
    return argv


def run_daemon_loop() -> int:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        clean = str(line).strip()
        if not clean:
            continue
        try:
            request = json.loads(clean)
        except json.JSONDecodeError:
            print(json.dumps({"ok": False, "state": "daemon_invalid_json", "error": "invalid_json"}, ensure_ascii=True), flush=True)
            continue
        if not isinstance(request, dict):
            print(json.dumps({"ok": False, "state": "daemon_invalid_request", "error": "request_must_be_object"}, ensure_ascii=True), flush=True)
            continue
        if str(request.get("action") or "").strip().lower() in {"exit", "quit", "stop"}:
            print(json.dumps({"ok": True, "state": "daemon_exit"}, ensure_ascii=True), flush=True)
            return 0
        argv = args_for_daemon_request(request)
        env_overrides = request.get("_env_overrides") if isinstance(request.get("_env_overrides"), dict) else {}
        original_env: dict[str, str | None] = {}
        if env_overrides:
            for key, value in env_overrides.items():
                clean_key = str(key or "").strip()
                if not clean_key:
                    continue
                original_env[clean_key] = os.getenv(clean_key)
                os.environ[clean_key] = str(value)
        try:
            payload = run_sidecar_cli(argv)
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "state": "daemon_dispatch_failed", "error": repr(exc), "request": request}
        finally:
            if env_overrides:
                for key, old_value in original_env.items():
                    if old_value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old_value
        print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


def run_sidecar_cli(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=SIDECAR_ACTION_CHOICES, nargs="?")
    parser.add_argument("--target", help="Chat name for messages/send.")
    parser.add_argument("--session-key", default="", help="Internal session key for row-level RPA targeting.")
    parser.add_argument("--text", help="Message text for send.")
    parser.add_argument("--phone", default="", help="Phone number for add-friend.")
    parser.add_argument("--wechat", default="", help="WeChat ID for add-friend fallback.")
    parser.add_argument("--verify-message", default="", help="Required add-friend verification message for the entry-click route.")
    parser.add_argument("--remark-name", default="", help="Required WeChat remark name for the entry-click route.")
    parser.add_argument("--remark-code", default="", help="Required system remark code that must be included in remark-name.")
    parser.add_argument("--calibration-only", action="store_true", help="For add-friend routes, capture/OCR/locate/report without clicking.")
    parser.add_argument("--exact", action="store_true", help="Use exact chat name matching.")
    parser.add_argument(
        "--skip-send-rate-guard",
        action="store_true",
        help="Skip rate guard reservation for controlled loopback simulation only.",
    )
    parser.add_argument("--history-load-times", type=int, default=0, help="Scroll upward this many times before reading messages.")
    parser.add_argument("--history-mode", default="", help="History loading strategy, e.g. anchor_until_found.")
    parser.add_argument("--anchor-id", action="append", default=[], help="Message id anchor to stop bounded history search.")
    parser.add_argument("--anchor-content-key", action="append", default=[], help="Normalized customer message content key anchor.")
    parser.add_argument("--reply-content-key", action="append", default=[], help="Normalized self reply content key anchor.")
    parser.add_argument("--max-scroll-steps", type=int, default=6, help="Maximum bounded upward scroll steps for anchor history search.")
    parser.add_argument("--max-duration-seconds", type=int, default=12, help="Maximum bounded anchor history search duration.")
    parser.add_argument("--max-snapshots", type=int, default=8, help="Maximum screenshots during anchor history search.")
    parser.add_argument("--min-delay-ms", type=int, default=180, help="Minimum pause between bounded anchor search scrolls.")
    parser.add_argument("--max-delay-ms", type=int, default=650, help="Maximum pause between bounded anchor search scrolls.")
    parser.add_argument("--restore-to-latest", dest="restore_to_latest", action="store_true", default=None)
    parser.add_argument("--no-restore-to-latest", dest="restore_to_latest", action="store_false")
    parser.add_argument(
        "--artifact-dir",
        default="",
        help="Optional directory for OCR screenshots and diagnostics.",
    )
    parser.add_argument("--daemon", action="store_true", help="Run as stdin/stdout JSON daemon.")
    args = parser.parse_args(argv)
    if args.daemon:
        return {"ok": False, "state": "daemon_reentry_not_supported"}
    configure_dpi_awareness()
    return run_action(args)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        raise SystemExit(run_daemon_loop())
    payload = run_sidecar_cli()
    print(json.dumps(payload, ensure_ascii=True))
    raise SystemExit(0 if bool(payload.get("ok")) else 1)
