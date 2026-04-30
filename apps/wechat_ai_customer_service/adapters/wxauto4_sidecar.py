"""JSON sidecar for wxauto4-based WeChat probes.

Run this script with a Python 3.9-3.12 interpreter that has ``wxauto4``
installed. The main OmniAuto project currently runs on Python 3.13, while
wxauto4 only publishes wheels through cp312, so keeping this as a sidecar
avoids contaminating the primary environment.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import io
import json
import sys
import time
from ctypes import wintypes
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "sessions", "messages", "send"])
    parser.add_argument("--target", help="Chat name for messages/send.")
    parser.add_argument("--text", help="Message text for send.")
    parser.add_argument("--exact", action="store_true", help="Use exact chat name matching.")
    parser.add_argument("--resize", action="store_true", help="Allow wxauto4 to resize WeChat.")
    args = parser.parse_args()

    payload: dict[str, Any]
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            payload = run_action(args)
        payload.setdefault("ok", bool(payload.get("online")))
    except Exception as exc:
        payload = {"ok": False, "error": repr(exc)}

    logs = captured.getvalue().strip()
    if logs:
        payload["library_stdout"] = logs

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def run_action(args: argparse.Namespace) -> dict[str, Any]:
    from wxauto4 import WeChat

    window_probe = ensure_visible_wechat_window()
    if not window_probe["visible_main_windows"]:
        return {
            "login_window_exists": False,
            "online": False,
            "state": "main_window_not_found",
            "window_probe": window_probe,
            "error": "No visible WeChat main window was found; refusing to start or attach to a login/secondary window.",
        }

    try:
        wx = WeChat(debug=False, resize=args.resize, ads=False)
    except Exception as exc:
        return {
            "login_window_exists": False,
            "online": False,
            "state": "connect_failed",
            "connect_error": repr(exc),
            "window_probe": window_probe,
            "error": "Visible WeChat window exists, but wxauto4 could not attach to it.",
        }

    payload: dict[str, Any] = {
        "login_window_exists": False,
        "online": bool(wx.IsOnline()),
        "my_info": safe_call(wx.GetMyInfo),
        "window_probe": window_probe,
    }

    if args.action == "status":
        payload["state"] = "main_window"
    elif args.action == "sessions":
        payload["sessions"] = [session_to_dict(item) for item in wx.GetSession()]
    elif args.action == "messages":
        if args.target:
            wx.ChatWith(args.target, exact=args.exact)
            time.sleep(0.5)
        payload["chat_info"] = safe_call(wx.ChatInfo)
        payload["messages"] = [message_to_dict(item) for item in wx.GetAllMessage()]
    elif args.action == "send":
        if not args.target:
            raise ValueError("--target is required for send")
        if args.text is None:
            raise ValueError("--text is required for send")
        chat_result = safe_call(lambda: wx.ChatWith(args.target, exact=args.exact, force=True, force_wait=0.5))
        time.sleep(0.5)
        chat_info = safe_call(wx.ChatInfo)
        if not chat_matches(chat_info, args.target, exact=args.exact):
            raise RuntimeError(f"target chat not active before send: target={args.target!r} chat_info={chat_info!r}")
        payload["chat_with_result"] = chat_result
        payload["chat_info_before_send"] = chat_info
        payload["send_result"] = normalize_response(
            wx.SendMsg(args.text, who=None, clear=True, exact=args.exact)
        )
        time.sleep(0.5)
        payload["chat_info_after_send"] = safe_call(wx.ChatInfo)
    return payload


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


def ensure_visible_wechat_window() -> dict[str, Any]:
    probe = probe_wechat_windows()
    if probe["visible_main_windows"]:
        return probe

    restored = restore_wechat_window(probe)
    if restored:
        time.sleep(0.8)
        probe = probe_wechat_windows()
        probe["restored_window"] = restored
    return probe


def restore_wechat_window(probe: dict[str, Any]) -> dict[str, Any] | None:
    user32 = ctypes.windll.user32
    sw_restore = 9
    sw_show = 5
    for item in probe.get("windows") or []:
        if not is_wechat_main_window(item):
            continue
        hwnd = int(item.get("hwnd") or 0)
        if not hwnd:
            continue
        user32.ShowWindow(hwnd, sw_restore)
        user32.ShowWindow(hwnd, sw_show)
        user32.SetForegroundWindow(hwnd)
        return dict(item)
    return None


def is_wechat_main_window(item: dict[str, Any]) -> bool:
    title = str(item.get("title") or "").strip()
    class_name = str(item.get("class_name") or "")
    return title in {"微信", "Weixin", "WeChat"} and "QWindowIcon" in class_name


def chat_matches(chat_info: Any, target: str, exact: bool) -> bool:
    if not isinstance(chat_info, dict):
        return False
    names = [
        chat_info.get("chat_name"),
        chat_info.get("name"),
        chat_info.get("Name"),
        chat_info.get("title"),
    ]
    normalized = [str(item).strip() for item in names if item]
    if exact:
        return target in normalized
    return any(target in item for item in normalized)


def session_to_dict(session: Any) -> dict[str, Any]:
    info = safe_getattr(session, "info")
    if isinstance(info, dict):
        return info
    return {
        "name": safe_getattr(session, "name"),
        "content": safe_getattr(session, "content"),
        "time": safe_getattr(session, "time"),
    }


def message_to_dict(message: Any) -> dict[str, Any]:
    return {
        "repr": repr(message),
        "type": safe_getattr(message, "type"),
        "sender": safe_getattr(message, "sender"),
        "content": safe_getattr(message, "content"),
        "time": safe_getattr(message, "time"),
        "id": safe_getattr(message, "id"),
    }


def normalize_response(response: Any) -> Any:
    if isinstance(response, dict):
        return response
    return {
        "repr": repr(response),
        "status": safe_getattr(response, "status"),
        "message": safe_getattr(response, "message"),
        "data": safe_getattr(response, "data"),
    }


def safe_getattr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except AttributeError:
        return None
    except Exception as exc:
        return f"<error: {exc!r}>"


def safe_call(fn: Any) -> Any:
    try:
        return fn()
    except Exception as exc:
        return {"error": repr(exc)}


if __name__ == "__main__":
    raise SystemExit(main())
