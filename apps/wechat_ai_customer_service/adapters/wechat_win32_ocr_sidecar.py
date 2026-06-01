"""Win32/OCR sidecar for the WeChat desktop recorder.

This adapter is designed as the primary transport because it relies only on
the top-level Win32 window, screenshots, OCR, clipboard paste, and guarded
click/input flows. It does not depend on wxauto4 internals and remains usable
across broader WeChat desktop variants.
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
from PIL import Image, ImageGrab, ImageStat

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
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SEND_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_send_guard.json"
UI_ACTION_GUARD_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_ui_action_guard.json"
UI_ACTION_AUDIT_PATH = PROJECT_ROOT / "runtime" / "wechat_win32_ocr_ui_actions.jsonl"
_LAST_ACTIVATE_MONOTONIC_BY_HWND: dict[int, float] = {}
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
DEFAULT_RENDER_RECOVERY_MIN_INTERVAL_SECONDS = 180
DEFAULT_QUICK_LOGIN_AUTO_ENTER = False
DEFAULT_TARGET_READY_MAX_ATTEMPTS = 1
BLANK_RENDER_BRIGHT_MIN = 238.0
BLANK_RENDER_DARK_MAX = 18.0
BLANK_RENDER_STDDEV_MAX = 8.0
BLANK_RENDER_DENSE_RATIO_MIN = 0.93
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
DEFAULT_HUMANIZED_ADAPTIVE_SPEED_ENABLED = True
DEFAULT_HUMANIZED_SHORT_TEXT_CHARS = 90
DEFAULT_HUMANIZED_LONG_TEXT_CHARS = 240
DEFAULT_INPUT_COPYBACK_STRONG_CONFIRM = False
DEFAULT_SEND_INPUT_CONFIRM_ATTEMPTS = 3
DEFAULT_INPUT_FAST_VISUAL_CONFIRM = True
DEFAULT_POST_SEND_STRICT_CONFIRM = False
DEFAULT_SEND_TRIGGER_MODE = "enter_only"
DEFAULT_STRICT_SEND_FOCUS_GUARD = True
DEFAULT_FOCUS_CLICK_FALLBACK = True
DEFAULT_ALLOW_UNKNOWN_FOREGROUND_GUARD = True
INPUT_TEXT_DARK_RATIO_MIN = 0.0025
HUMANIZED_TYPO_CANDIDATES = "asdfjkl;,.?/[]"
SENDINPUT_INPUT_KEYBOARD = 1
SENDINPUT_KEYEVENTF_KEYUP = 0x0002
SENDINPUT_KEYEVENTF_UNICODE = 0x0004
BLOCKING_SCREEN_TOKENS = (
    "登录",
    "扫码",
    "选择文件",
    "文件名无效",
    "安全验证",
    "账号安全",
    "登录环境异常",
    "操作频繁",
    "拖拽",
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
    parser.add_argument("action", choices=["status", "capabilities", "sessions", "messages", "send", "recover-render"], nargs="?")
    parser.add_argument("--target", help="Chat name for messages/send.")
    parser.add_argument("--text", help="Message text for send.")
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
    if _WIN32_IMPORT_ERROR:
        return {
            "ok": False,
            "online": False,
            "adapter": "win32_ocr",
            "state": "pywin32_unavailable",
            "error": _WIN32_IMPORT_ERROR,
        }
    action = str(args.action or "").strip().lower()
    passive_probe = use_passive_probe_mode(action)
    probe = ensure_visible_wechat_window(interactive=not passive_probe)
    if not probe.get("visible_main_windows"):
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
            opened = open_chat(hwnd, args.target, exact=bool(args.exact), artifact_dir=args.artifact_dir)
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
    return {"ok": False, "online": False, "adapter": "win32_ocr", "state": "unsupported_action"}


def use_passive_probe_mode(action: str) -> bool:
    if action not in {"status", "capabilities", "sessions"}:
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
    detected = bool(bright_blank or dark_blank)
    if bright_blank:
        reason = "blank_white_like"
    elif dark_blank:
        reason = "blank_dark_like"
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
    if initial.get("ok") and initial.get("online"):
        initial["render_recovery"] = {
            "ok": True,
            "attempted": False,
            "reason": "wechat_render_already_ready",
        }
        return initial
    if not sidecar_payload_is_blank_render(initial):
        initial["render_recovery"] = {
            "ok": False,
            "attempted": False,
            "reason": "not_blank_render",
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
    recovered_probe = ensure_visible_wechat_window(interactive=True)
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
        "initial_status": initial,
    }
    if final.get("ok") and final.get("online"):
        return final
    initial["render_recovery"] = final["render_recovery"]
    initial["recovered_status"] = final
    return initial


def sidecar_payload_is_blank_render(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return str(payload.get("state") or "") == "blank_render_detected" or str(payload.get("reason") or "") == "blank_render"


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
                "content": item.get("preview", ""),
                "time": item.get("time", ""),
                "unread_badge": item.get("unread_badge", ""),
                "unread": item.get("unread_badge", ""),
                "unread_signal": bool(item.get("unread_badge")),
                "conversation_type": infer_conversation_type(item["name"]),
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
        for message in snapshot.get("messages", []) or []:
            if not isinstance(message, dict):
                continue
            key = message_history_dedupe_key(message)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            merged.append(message)
    return merged


def message_history_dedupe_key(message: dict[str, Any]) -> str:
    content = str(message.get("content") or "")
    compact = re.sub(r"[\s_\-:：，。,.；;\[\]（）()]+", "", content).lower()
    sender = str(message.get("sender") or "")
    if not compact:
        return ""
    return f"{sender}:{compact}"


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
        # confirmation to avoid repeating OCR-heavy guard validation.
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
        if not validation.get("ok"):
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
            "validation_source": "prevalidated_guard" if reused_prevalidated_guard else "active_send_guard",
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
    ):
        current = int(active.get(key) or 0)
        target = int(profile[key])
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
    active["typo_probability"] = min(float(active.get("typo_probability") or 0.0), float(profile["typo_probability"]))
    active["typo_max"] = min(int(active.get("typo_max") or 0), int(profile["typo_max"]))
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
    top = max(int(height * 0.74), height - 190)
    right = max(left + 20, width - 95)
    bottom = min(height - 62, height)
    if bottom <= top:
        top = max(0, int(height * 0.78))
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
        mean = float(sum(index * count for index, count in enumerate(histogram))) / float(total)
    except Exception as exc:
        return {
            "has_visible_text": bool(ocr_hits),
            "reason": "input_region_probe_failed",
            "error": repr(exc),
            "bounds": list(bounds),
            "ocr_hits": ocr_hits,
        }
    pixel_visible = dark_ratio >= INPUT_TEXT_DARK_RATIO_MIN
    # OCR boxes can drift into the lower chat/input boundary on fresh captures.
    # Treat OCR as draft evidence only when the crop also contains text-like
    # dark pixels; otherwise a blank white input area would block safe typing.
    ocr_visible = bool(ocr_hits > 0 and dark_ratio >= INPUT_TEXT_DARK_RATIO_MIN / 3.0)
    has_visible_text = bool(pixel_visible or ocr_visible)
    return {
        "has_visible_text": has_visible_text,
        "reason": "ocr_or_dark_pixels" if has_visible_text else "input_region_blank",
        "bounds": list(bounds),
        "ocr_hits": ocr_hits,
        "dark_ratio": round(dark_ratio, 6),
        "mean": round(mean, 3),
        "threshold": INPUT_TEXT_DARK_RATIO_MIN,
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
    input_x, input_y = jitter_input_click_point(
        int(points["input_point"][0]),
        int(points["input_point"][1]),
        geometry,
    )
    human_client_click(hwnd, input_x, input_y)
    time.sleep(random.uniform(0.08, 0.16))
    # Avoid Ctrl+A here: select-all artifacts can leak to chat history when
    # focus drifts. Use bounded backspace/delete bursts instead.
    backspaces = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_DRAFT_CLEAR_BACKSPACES"),
        default=20,
        minimum=6,
        maximum=64,
    )
    deletes = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_DRAFT_CLEAR_DELETES"),
        default=4,
        minimum=0,
        maximum=18,
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
    if not after_state.get("has_visible_text"):
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
    trigger_mode = normalize_send_trigger_mode(os.getenv("WECHAT_WIN32_OCR_SEND_TRIGGER_MODE"))
    if trigger_mode in {"enter_only", "enter_then_click"}:
        key_press(win32con.VK_RETURN)
        time.sleep(random.uniform(0.08, 0.16))
    if trigger_mode in {"click_only", "enter_then_click"}:
        focus_guard = recover_send_window_guard(hwnd, max_attempts=1)
        if not focus_guard.get("ok"):
            return {
                "ok": False,
                "reason": "send_focus_guard_failed_before_click_trigger",
                "error": "WeChat lost foreground focus before clicking send; abort without retrying.",
                "paste": paste_result,
                "window_guard": focus_guard,
            }
        human_client_click(hwnd, send_click_x, send_click_y)
    paste_method = str(paste_result.get("input_mode") or paste_result.get("method") or "clipboard_once")
    return {
        "ok": True,
        "method": f"win32.human_click_input+{paste_method}+send_trigger:{trigger_mode}",
        "input_point": [int(points["input_point"][0]), int(points["input_point"][1])],
        "send_point": [send_click_x, send_click_y],
        "paste": paste_result,
        "send_trigger_mode": trigger_mode,
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
    if rel["width"] <= 80 or rel["height"] <= 12:
        return False
    if rel["right"] <= session_split_x(width) + 100:
        return False
    bounds = input_text_region_bounds(geometry)
    left, top, right, bottom = bounds
    center_y = (rel["top"] + rel["bottom"]) / 2.0
    horizontal_overlap = min(rel["right"], right) - max(rel["left"], left)
    if horizontal_overlap <= 0:
        return False
    return rel["top"] >= top - 6 and rel["bottom"] <= bottom + 10 and top <= center_y <= bottom


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
    click_x = session_row_click_x(session, geometry, default_x=default_click_x)
    click_y = int(float(center_y))
    # Try a lightweight WM click first, then fall back to real cursor clicks.
    client_click(hwnd, click_x, click_y)
    humanized_action_sleep(240, 420)
    validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
    if validation.get("ok") is True:
        return True
    if target_switch_validation_is_hard_stop(validation):
        return False
    human_client_click(hwnd, click_x, click_y)
    humanized_action_sleep(280, 520)
    validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
    return validation.get("ok") is True


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
    return env_flag("WECHAT_WIN32_OCR_TARGET_SEARCH_FALLBACK", default=True)


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


def open_chat(hwnd: int, target: str, *, exact: bool, artifact_dir: str | None = None) -> bool:
    screenshot, ocr_items = ensure_main_session_list(hwnd, artifact_dir=artifact_dir)
    geometry = get_window_geometry(hwnd)
    session_click_x = session_click_x_for_geometry(geometry)
    search_x, search_y = search_box_point_for_geometry(geometry)
    surface = target_switch_surface_state(screenshot, ocr_items, geometry=geometry)
    if not surface.get("ok"):
        return False
    if active_chat_matches(ocr_items, screenshot.size, target=target, exact=exact):
        return True
    sessions = parse_sessions_from_ocr(ocr_items, screenshot.size, screenshot=screenshot)
    for item in sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        if activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        ):
            return True

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
    if active_chat_matches(search_items, search_shot.size, target=target, exact=exact):
        return True
    search_sessions = parse_sessions_from_ocr(search_items, search_shot.size, screenshot=search_shot)
    for item in search_sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        if activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        ):
            return True

    if target_search_enter_fallback_enabled():
        key_press(win32con.VK_RETURN)
        time.sleep(random.uniform(0.45, 0.7))
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if validation.get("ok") is True:
            return True
        if target_switch_validation_is_hard_stop(validation):
            return False

    # Re-scan and try a direct sidebar click once more after search.
    retry_shot, _retry_path = capture_wechat(hwnd, artifact_dir=artifact_dir, label="open_chat_retry")
    retry_items = run_ocr(retry_shot)
    surface = target_switch_surface_state(retry_shot, retry_items, geometry=geometry)
    if not surface.get("ok"):
        return False
    retry_sessions = parse_sessions_from_ocr(retry_items, retry_shot.size, screenshot=retry_shot)
    for item in retry_sessions:
        if not session_name_matches(str(item.get("name") or ""), target, exact=exact):
            continue
        if activate_session_candidate(
            hwnd,
            item,
            target=target,
            exact=exact,
            geometry=geometry,
            default_click_x=session_click_x,
            artifact_dir=artifact_dir,
        ):
            return True
    return False


def ensure_target_ready_for_send(
    hwnd: int,
    target: str,
    *,
    exact: bool,
    artifact_dir: str | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    attempts = target_ready_attempt_count(max_attempts)
    last_validation: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        # Fast path: when we are already on the correct chat, avoid the extra
        # open-chat traversal and send immediately after guard confirmation.
        pre_validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if pre_validation.get("ok"):
            return {"ok": True, "attempts": attempt, "validation": pre_validation, "opened": False}
        last_validation = pre_validation
        if target_switch_validation_is_hard_stop(pre_validation):
            return {"ok": False, "attempts": attempt, "validation": pre_validation, "hard_stop": True}

        opened = open_chat(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        humanized_action_sleep(280 + attempt * 90, 440 + attempt * 150)
        validation = validate_active_send_target(hwnd, target, exact=exact, artifact_dir=artifact_dir)
        if validation.get("ok"):
            return {"ok": True, "attempts": attempt, "validation": validation, "opened": bool(opened)}
        last_validation = validation
        if target_switch_validation_is_hard_stop(validation):
            return {"ok": False, "attempts": attempt, "validation": validation, "hard_stop": True}
        if attempt < attempts:
            key_press(win32con.VK_ESCAPE)
            humanized_action_sleep(160, 300)
    return {"ok": False, "attempts": attempts, "validation": last_validation}


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
                "geometry": geometry,
                "screenshot_path": path,
            }
        return {
            "ok": False,
            "online": True,
            "reason": "ocr_capture_unavailable",
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
            "geometry": geometry,
            "screenshot_path": path,
            "error": "The active chat title did not match the requested target.",
        }
    return {
        "ok": True,
        "online": True,
        "reason": "target_confirmed",
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
        "reason": "target_confirmed",
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
    input_y = client_height - 145
    send_x = client_width - 62
    send_y = client_height - 44
    if input_y < client_height * 0.72 or send_y < client_height * 0.82:
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
    return {"ok": True, "input_point": [input_x, input_y], "send_point": [send_x, send_y], "geometry": geometry}


def jitter_input_click_point(x: int, y: int, geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return int(x), int(y)
    jitter_x = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_POINT_JITTER_X"),
        default=7,
        minimum=0,
        maximum=20,
    )
    jitter_y = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_INPUT_POINT_JITTER_Y"),
        default=6,
        minimum=0,
        maximum=18,
    )
    split_x = session_split_x(width)
    safe_min_x = max(split_x + 30, int(width * 0.52))
    safe_max_x = max(safe_min_x, width - 88)
    safe_min_y = max(int(height * 0.74), height - 220)
    safe_max_y = max(safe_min_y, height - 82)
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


def jitter_send_click_point(x: int, y: int, geometry: dict[str, Any]) -> tuple[int, int]:
    width = int(geometry.get("width") or 0)
    height = int(geometry.get("height") or 0)
    if width <= 0 or height <= 0:
        return int(x), int(y)
    jitter_x = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_SEND_POINT_JITTER_X"),
        default=4,
        minimum=0,
        maximum=12,
    )
    jitter_y = bounded_int(
        os.getenv("WECHAT_WIN32_OCR_SEND_POINT_JITTER_Y"),
        default=3,
        minimum=0,
        maximum=10,
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
    if any(token in joined for token in ("登录", "扫码")):
        return "login_or_qr"
    for token in BLOCKING_SCREEN_TOKENS:
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


def active_ui_action_budget_decision(
    *,
    action: str,
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
    allowed = len(kept) < limit
    decision = {
        "ok": allowed,
        "enabled": True,
        "action": action,
        "count": len(kept),
        "limit": limit,
        "window_seconds": window_seconds,
    }
    if reserve and allowed:
        kept.append({"ts": now, "action": str(action or "unknown")})
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
    decision = active_ui_action_budget_decision(action=action, reserve=True)
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
    header_cutoff = active_chat_title_cutoff_y(height)
    for item in ocr_items:
        text = normalize_ocr_text(item.get("text"))
        if not text:
            continue
        if item["center_y"] > header_cutoff or item["right"] < split_x:
            continue
        candidates = {
            text,
            re.sub(r"\(\d+\)$", "", text).strip(),
            re.sub(r"（\d+）$", "", text).strip(),
            re.sub(r"^[：:.\s]+", "", text).strip(),
            normalize_chat_title_for_match(text),
        }
        for candidate in candidates:
            if session_name_matches(candidate, normalized_target, exact=exact):
                return True
    return False


def scroll_chat_history(hwnd: int, load_times: int, *, wheel_units: int = 8, delay_seconds: float = 0.18) -> None:
    require_active_ui_action_budget("scroll_chat_history", metadata={"load_times": int(load_times or 0)})
    rect = win32gui.GetWindowRect(hwnd)
    x = max(380, int((rect[2] - rect[0]) * 0.6)) + random.randint(-12, 12)
    y = max(180, int((rect[3] - rect[1]) * 0.45)) + random.randint(-10, 10)
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
    require_active_ui_action_budget("scroll_chat_to_latest", metadata={"attempts": int(attempts or 0)})
    rect = win32gui.GetWindowRect(hwnd)
    x = max(380, int((rect[2] - rect[0]) * 0.6)) + random.randint(-12, 12)
    y = max(180, int((rect[3] - rect[1]) * 0.55)) + random.randint(-10, 10)
    activate_window(hwnd)
    ensure_left_button_released()
    screen_x, screen_y = win32gui.ClientToScreen(hwnd, (x, y))
    win32api.SetCursorPos((screen_x, screen_y))
    humanized_action_sleep(45, 110)
    wheel_message = getattr(win32con, "WM_MOUSEWHEEL", 0x020A)
    lparam = ((int(screen_y) & 0xFFFF) << 16) | (int(screen_x) & 0xFFFF)
    for _ in range(max(0, int(attempts))):
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
    saved = ""
    if artifact_dir:
        root = Path(artifact_dir)
        root.mkdir(parents=True, exist_ok=True)
        saved_path = root / f"{label}_{int(time.time() * 1000)}.png"
        image.save(saved_path)
        saved = str(saved_path)
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
    if env_flag("WECHAT_WIN32_OCR_ALLOW_BLIND_FILE_TRANSFER_SEND", default=True) is False:
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
    for item in sorted(candidates, key=lambda row: float(row["center_y"])):
        center_y = float(item["center_y"])
        if center_y - last_y < min_session_row_gap:
            continue
        name = normalize_session_name(str(item.get("text") or ""))
        # OCR occasionally glues sidebar timestamps into the session title
        # (e.g. "新数据测试昨天19:23"), which breaks session-target matching.
        name = strip_session_time_suffix(name)
        if is_file_transfer_session_alias(name):
            name = "文件传输助手"
        if not name or any(existing["name"] == name for existing in sessions):
            continue
        sessions.append(
            {
                "name": name,
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
        rows.append(item)

    grouped: list[list[dict[str, Any]]] = []
    for item in sorted(rows, key=lambda row: (float(row["center_y"]), float(row["left"]))):
        side = classify_message_side(item, width=width)
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
        content = "\n".join(str(item.get("text") or "").strip() for item in group if str(item.get("text") or "").strip())
        content = normalize_message_content(content)
        if not content:
            continue
        side = str(group[0].get("side") or "unknown")
        y = float(group[0].get("center_y") or 0)
        digest = hashlib.sha1(f"{target}|{side}|{round(y)}|{content}".encode("utf-8")).hexdigest()[:16]
        messages.append(
            {
                "id": f"win32_ocr:{digest}",
                "type": "text",
                "sender": "self" if side == "self" else "unknown",
                "sender_role": "self" if side == "self" else "unknown",
                "content": content,
                "time": "",
                "source_adapter": "win32_ocr",
                "ocr_confidence": min(float(item.get("confidence") or 0) for item in group),
            }
        )
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
    selected_score: tuple[int, int, int] = (-1, -1, -1)
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
        score = (capture_ready, wechat_window_title_score(item), area)
        if selected is None or score > selected_score:
            selected = {**dict(item), "geometry_hint": geometry}
            selected_score = score
    if selected is not None:
        return selected
    return dict(visible[0])


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
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                humanized_action_sleep(25, 55)
                user32.SetForegroundWindow(hwnd)
                win32gui.SetForegroundWindow(hwnd)
                win32gui.SetActiveWindow(hwnd)
            except Exception:
                pass
            finally:
                try:
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
    require_active_ui_action_budget("client_click", metadata={"hwnd": int(hwnd or 0), "x": int(x), "y": int(y)})
    activate_window(hwnd)
    ensure_left_button_released()
    lparam = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)
    win32gui.SendMessage(hwnd, win32con.WM_MOUSEMOVE, 0, lparam)
    humanized_action_sleep(20, 55)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
    humanized_action_sleep(45, 100)
    win32gui.SendMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
    humanized_action_sleep(80, 170)


def human_client_click(hwnd: int, x: int, y: int) -> None:
    """Move the real cursor with small jitter before clicking a client point."""
    require_active_ui_action_budget("human_client_click", metadata={"hwnd": int(hwnd or 0), "x": int(x), "y": int(y)})
    activate_window(hwnd)
    ensure_left_button_released()
    left_down_sent = False
    try:
        screen_x, screen_y = client_to_screen(hwnd, int(x), int(y))
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
        client_click(hwnd, x, y)
    finally:
        if left_down_sent:
            ensure_left_button_released()


def human_window_image_click(hwnd: int, x: int, y: int) -> None:
    """Click a point measured in the same coordinate space as screenshots."""
    require_active_ui_action_budget("human_window_image_click", metadata={"hwnd": int(hwnd or 0), "x": int(x), "y": int(y)})
    activate_window(hwnd)
    ensure_left_button_released()
    left_down_sent = False
    try:
        left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
        screen_x = int(left) + int(x)
        screen_y = int(top) + int(y)
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
        click_x, click_y = client_to_screen(hwnd, int(x), int(y))
        click(click_x, click_y)
    finally:
        if left_down_sent:
            ensure_left_button_released()


def client_to_screen(hwnd: int, x: int, y: int) -> tuple[int, int]:
    point = wintypes.POINT(int(x), int(y))
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(point))
    return int(point.x), int(point.y)


def click(x: int, y: int) -> None:
    require_active_ui_action_budget("screen_click", metadata={"x": int(x), "y": int(y)})
    ensure_left_button_released()
    win32api.SetCursorPos((int(x), int(y)))
    humanized_action_sleep(20, 55)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    humanized_action_sleep(35, 85)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    ensure_left_button_released()


def hotkey(modifier: int, key: int) -> None:
    win32api.keybd_event(modifier, 0, 0, 0)
    humanized_action_sleep(16, 42)
    win32api.keybd_event(key, 0, 0, 0)
    humanized_action_sleep(18, 48)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(modifier, 0, win32con.KEYEVENTF_KEYUP, 0)
    humanized_action_sleep(8, 28)


def key_press(key: int) -> None:
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


def normalize_chat_title_for_match(text: str) -> str:
    clean = normalize_session_name(text)
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
    client_click(hwnd, click_x, click_y)
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


if __name__ == "__main__":
    raise SystemExit(main())
