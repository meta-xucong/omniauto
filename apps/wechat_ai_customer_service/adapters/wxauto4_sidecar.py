"""JSON sidecar for wxauto4-based WeChat probes.

Run this script with a Python 3.9-3.12 interpreter that has ``wxauto4``
installed. The main OmniAuto project currently runs on Python 3.13, while
wxauto4 only publishes wheels through cp312, so keeping this as a sidecar
avoids contaminating the primary environment.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
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
        payload["ok"] = True
    except Exception as exc:
        payload = {"ok": False, "error": repr(exc)}

    logs = captured.getvalue().strip()
    if logs:
        payload["library_stdout"] = logs

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


def run_action(args: argparse.Namespace) -> dict[str, Any]:
    from wxauto4 import LoginWnd, WeChat

    try:
        wx = WeChat(debug=False, resize=args.resize, ads=False)
    except Exception as exc:
        login = LoginWnd()
        login_exists = bool(login.exists(1))
        if args.action == "status" and login_exists:
            return {
                "login_window_exists": True,
                "online": False,
                "state": "login_window",
                "connect_error": repr(exc),
            }
        raise

    payload: dict[str, Any] = {
        "login_window_exists": False,
        "online": bool(wx.IsOnline()),
        "my_info": safe_call(wx.GetMyInfo),
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
        payload["send_result"] = normalize_response(
            wx.SendMsg(args.text, who=args.target, clear=True, exact=args.exact)
        )
    return payload


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
