"""Minimal runner for the accepted WeChat customer-service baseline.

This runner intentionally avoids screenshot/OCR/window-capture probes. It only:
1. Connects to an already logged-in WeChat main window.
2. Optionally starts WeChat only when ``--start-if-missing`` is passed.
3. Calls the Python 3.12 wxauto4 sidecar.
4. Emits JSON for status, sessions, messages, send, or smoke-test actions.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from wechat_connector import FILE_TRANSFER_ASSISTANT, WeChatConnector, any_weixin_process


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "sessions", "messages", "send", "smoke"])
    parser.add_argument("--target", default=FILE_TRANSFER_ASSISTANT)
    parser.add_argument("--text")
    parser.add_argument("--wait", type=int, default=60)
    parser.add_argument(
        "--start-if-missing",
        action="store_true",
        help="Start WeChat if no logged-in main window is found.",
    )
    parser.add_argument("--no-start", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.action in {"send", "smoke"} and args.text is None:
        if args.action == "send":
            parser.error("--text is required for send")
        args.text = "omniauto stable check " + datetime.now().strftime("%Y%m%d_%H%M%S")

    connector = WeChatConnector()
    status = connector.status()
    if (
        not status.get("online")
        and args.start_if_missing
        and not args.no_start
        and not any_weixin_process()
    ):
        connector.ensure_wechat_started()
        status = connector.wait_online(args.wait)
    elif not status.get("online") and any_weixin_process():
        status = connector.wait_online(args.wait)

    result: dict[str, Any] = {"status": status}
    if not status.get("ok") or not status.get("online"):
        result["ok"] = False
        result["error"] = "WeChat is not online; confirm login on the phone/client, then rerun."
        print_json(result)
        return 2

    if args.action == "status":
        result["ok"] = True
    elif args.action == "sessions":
        result["sessions"] = connector.list_sessions()
        result["ok"] = bool(result["sessions"].get("ok"))
    elif args.action == "messages":
        result["messages"] = connector.get_messages(args.target, exact=True)
        result["ok"] = bool(result["messages"].get("ok"))
    elif args.action == "send":
        result["send"] = connector.send_text(args.target, args.text or "", exact=True)
        result["ok"] = bool(result["send"].get("ok"))
    elif args.action == "smoke":
        verified = connector.send_text_and_verify(args.target, args.text or "", exact=True)
        result["send"] = verified.get("send")
        result["messages"] = verified.get("messages")
        result["sent_text"] = args.text
        result["verified"] = bool(verified.get("verified"))
        result["ok"] = bool(verified.get("ok"))

    print_json(result)
    return 0 if result.get("ok") else 1


def print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
