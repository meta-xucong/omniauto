"""Probe controlled WeChat text placement and optional sending.

Default mode is safe: it only copies text to the clipboard and focuses WeChat.
Use --mode paste to paste into the currently focused input box.
Use --mode send to paste and press Enter.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict

import pyperclip
from pywinauto.keyboard import send_keys

from _probe_common import (
    add_common_args,
    capture_window_screenshot,
    ensure_artifact_dir,
    find_wechat_windows,
    focus_window,
    select_best_window,
    summarize_window,
    write_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--text", default="OmniAuto WeChat probe message", help="Text to place or send.")
    parser.add_argument(
        "--mode",
        choices=["clipboard-only", "paste", "send"],
        default="clipboard-only",
        help="clipboard-only is default and does not paste or send.",
    )
    parser.add_argument(
        "--restore-clipboard",
        action="store_true",
        help="Restore previous text clipboard content after the probe.",
    )
    args = parser.parse_args()

    artifact_dir = ensure_artifact_dir("send_probe")
    windows = find_wechat_windows(args.title_pattern)
    selected = select_best_window(windows)
    if selected is None:
        result_path = artifact_dir / "result.json"
        write_json(result_path, {"error": "No WeChat window found", "title_pattern": args.title_pattern})
        print(f"send_probe result: {result_path}")
        return 2

    original_clipboard = ""
    try:
        original_clipboard = pyperclip.paste()
    except Exception:
        pass

    focused = focus_window(selected)
    before_path = artifact_dir / "before.png"
    capture_window_screenshot(selected, before_path)

    pyperclip.copy(args.text)
    action_taken = "clipboard-only"

    if args.mode in {"paste", "send"}:
        send_keys("^v")
        action_taken = "paste"
        time.sleep(0.8)

    if args.mode == "send":
        send_keys("{ENTER}")
        action_taken = "send"
        time.sleep(1.0)

    after_path = artifact_dir / "after.png"
    capture_window_screenshot(selected, after_path)

    if args.restore_clipboard:
        try:
            pyperclip.copy(original_clipboard)
        except Exception:
            pass

    result = {
        "selected": asdict(summarize_window(selected)),
        "focused": focused,
        "mode": args.mode,
        "action_taken": action_taken,
        "text_length": len(args.text),
        "before_screenshot_path": str(before_path),
        "after_screenshot_path": str(after_path),
        "clipboard_restored": bool(args.restore_clipboard),
    }
    result_path = artifact_dir / "result.json"
    write_json(result_path, result)
    print(f"send_probe result: {result_path}")
    print(f"mode={args.mode} action_taken={action_taken} focused={focused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

