"""Open File Transfer Assistant in Windows WeChat, then optionally send text."""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict
from pathlib import Path

import pyperclip
from pywinauto.keyboard import send_keys
from pywinauto.mouse import click
from rapidocr_onnxruntime import RapidOCR

from _probe_common import (
    capture_window_screenshot,
    ensure_artifact_dir,
    find_wechat_windows,
    focus_window,
    get_foreground_window,
    is_foreground,
    summarize_window,
    write_json,
)


TARGET = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93, 0x52A9, 0x624B])
TARGET_HINT = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93])
LOGIN_MARKERS = [
    "".join(chr(c) for c in [0x767B, 0x5F55]),
    "".join(chr(c) for c in [0x5207, 0x6362, 0x8D26, 0x53F7]),
    "".join(chr(c) for c in [0x4EC5, 0x4F20, 0x8F93, 0x6587, 0x4EF6]),
    "Meta_xc",
]


def rect_tuple(window) -> tuple[int, int, int, int]:
    rect = window.rectangle()
    return rect.left, rect.top, rect.right, rect.bottom


def ocr_image(path: Path) -> list[dict]:
    engine = RapidOCR()
    results, _ = engine(str(path))
    items = []
    for row in results or []:
        if len(row) >= 3:
            box, text, score = row[0], str(row[1]), float(row[2])
            items.append({"box": box, "text": text, "score": score})
    return items


def joined_text(items: list[dict]) -> str:
    return "\n".join(item["text"] for item in items)


def find_target_in_ocr(items: list[dict]) -> dict | None:
    for item in items:
        text = item["text"].replace(" ", "")
        if TARGET in text or TARGET_HINT in text:
            return item
    return None


def looks_like_wrong_surface(items: list[dict]) -> bool:
    joined = joined_text(items)
    markers = ["Codex", "workflows", "wechat_customer_service", "py_compile", "Ran "]
    return any(marker in joined for marker in markers)


def looks_like_login_surface(items: list[dict]) -> bool:
    joined = joined_text(items)
    return any(marker in joined for marker in LOGIN_MARKERS)


def validate_surface(items: list[dict]) -> None:
    if looks_like_wrong_surface(items):
        raise RuntimeError("Focused window screenshot looks like Codex, not WeChat.")
    if looks_like_login_surface(items):
        raise RuntimeError("Focused WeChat window is a login/transfer-only surface, not the chat main window.")
    if len(items) < 3:
        raise RuntimeError("Focused window screenshot has too little OCR text; it may be desktop/blank, not WeChat.")


def click_ocr_item(window, item: dict) -> None:
    left, top, _, _ = rect_tuple(window)
    points = item["box"]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    click(button="left", coords=(left + int(sum(xs) / len(xs)), top + int(sum(ys) / len(ys))))
    time.sleep(1.0)


def open_by_left_list(window, artifact_dir: Path, stem: str) -> bool:
    screenshot = artifact_dir / f"{stem}_left_list_probe.png"
    capture_window_screenshot(window, screenshot)
    items = ocr_image(screenshot)
    write_json(artifact_dir / f"{stem}_left_list_ocr.json", items)
    validate_surface(items)
    target = find_target_in_ocr(items)
    if not target:
        return False
    click_ocr_item(window, target)
    return True


def open_by_search(window) -> None:
    left, top, right, _ = rect_tuple(window)
    width = right - left

    # Prefer WeChat's left-side Search entry. Do not use Ctrl+F, because that
    # can trigger in-conversation or embedded-page search.
    click(button="left", coords=(left + 70, top + 132))
    time.sleep(0.5)

    click(button="left", coords=(left + min(185, max(120, width // 5)), top + 32))
    time.sleep(0.2)
    send_keys("^a")
    time.sleep(0.1)
    pyperclip.copy(TARGET)
    send_keys("^v")
    time.sleep(0.7)
    send_keys("{ENTER}")
    time.sleep(1.2)


def paste_or_send(window, text: str, mode: str) -> str:
    if mode == "open-only":
        return "open-only"

    left, _, right, bottom = rect_tuple(window)
    click(button="left", coords=(left + int((right - left) * 0.72), bottom - 55))
    time.sleep(0.2)
    pyperclip.copy(text)
    send_keys("^v")
    time.sleep(0.5)
    if mode == "send":
        send_keys("{ENTER}")
        time.sleep(1.0)
        return "send"
    return "paste"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", default="hello world")
    parser.add_argument("--mode", choices=["open-only", "paste", "send"], default="open-only")
    args = parser.parse_args()

    artifact_dir = ensure_artifact_dir("file_transfer_probe")
    windows = find_wechat_windows()
    if not windows:
        write_json(artifact_dir / "result.json", {"error": "No WeChat window found"})
        print(f"file_transfer_probe result: {artifact_dir / 'result.json'}")
        return 2

    candidates = sorted(windows, key=lambda w: summarize_window(w).width * summarize_window(w).height, reverse=True)
    blocked_candidates = []
    selected = None
    focused = False
    before = None
    opened = False
    opened_by = "left-list"

    for candidate in candidates:
        summary = summarize_window(candidate)
        selected = candidate
        focused = focus_window(selected, keep_topmost=True)
        before = artifact_dir / f"before_{summary.process_name}_{selected.handle}.png"
        capture_window_screenshot(selected, before)
        try:
            opened = open_by_left_list(selected, artifact_dir, f"{summary.process_name}_{selected.handle}")
            break
        except RuntimeError as exc:
            blocked_candidates.append(
                {
                    "window": asdict(summary),
                    "reason": str(exc),
                    "screenshot_path": str(before),
                }
            )
            selected = None
            continue

    if selected is None:
        result = {
            "blocked_candidates": blocked_candidates,
            "opened": False,
            "mode": args.mode,
            "action": "blocked",
            "failure_reason": "No candidate WeChat window passed screenshot surface validation.",
        }
        result_path = artifact_dir / "result.json"
        write_json(result_path, result)
        print(f"file_transfer_probe result: {result_path}")
        print(result["failure_reason"])
        return 3

    if not opened:
        opened_by = "search"
        open_by_search(selected)
        opened = True

    after_open = artifact_dir / "after_open.png"
    capture_window_screenshot(selected, after_open)
    action = paste_or_send(selected, args.text, args.mode)
    after_action = artifact_dir / "after_action.png"
    capture_window_screenshot(selected, after_action)

    result = {
        "selected": asdict(summarize_window(selected)),
        "focused": focused,
        "foreground_hwnd": get_foreground_window(),
        "selected_is_foreground": is_foreground(int(selected.handle)),
        "opened": opened,
        "opened_by": opened_by,
        "mode": args.mode,
        "action": action,
        "before_screenshot_path": str(before),
        "after_open_screenshot_path": str(after_open),
        "after_action_screenshot_path": str(after_action),
    }
    result_path = artifact_dir / "result.json"
    write_json(result_path, result)
    print(f"file_transfer_probe result: {result_path}")
    print(f"opened_by={opened_by} mode={args.mode} action={action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
