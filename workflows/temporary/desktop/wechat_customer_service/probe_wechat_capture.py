"""Probe WeChat text capture paths: UIA text, OCR, and optional clipboard copy."""

from __future__ import annotations

import argparse
import time
from dataclasses import asdict

import pyperclip
from pywinauto.keyboard import send_keys
from rapidocr_onnxruntime import RapidOCR

from _probe_common import (
    add_common_args,
    capture_window_screenshot,
    dump_controls,
    ensure_artifact_dir,
    find_wechat_windows,
    focus_window,
    select_best_window,
    summarize_window,
    write_json,
)


def extract_uia_text(controls: list[dict]) -> list[dict]:
    text_controls = []
    for control in controls:
        text = str(control.get("text") or "").strip()
        if text:
            text_controls.append(
                {
                    "index": control.get("index"),
                    "text": text,
                    "control_type": control.get("control_type"),
                    "friendly_class": control.get("friendly_class"),
                    "rectangle": control.get("rectangle"),
                }
            )
    return text_controls


def run_ocr(image_path: str) -> list[dict]:
    engine = RapidOCR()
    results, _ = engine(image_path)
    normalized = []
    for item in results or []:
        if len(item) >= 3:
            box, text, score = item[0], item[1], item[2]
            normalized.append({"text": text, "score": float(score), "box": box})
    return normalized


def capture_clipboard_copy() -> dict:
    original = ""
    try:
        original = pyperclip.paste()
    except Exception:
        pass

    pyperclip.copy("")
    send_keys("^a")
    time.sleep(0.2)
    send_keys("^c")
    time.sleep(0.5)
    copied = pyperclip.paste()

    try:
        pyperclip.copy(original)
    except Exception:
        pass

    return {"text": copied, "length": len(copied or "")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip OCR over the captured WeChat window screenshot.",
    )
    parser.add_argument(
        "--copy-selected",
        action="store_true",
        help="Send Ctrl+A/C to the focused WeChat window and capture clipboard text.",
    )
    args = parser.parse_args()

    artifact_dir = ensure_artifact_dir("capture_probe")
    windows = find_wechat_windows(args.title_pattern)
    selected = select_best_window(windows)
    if selected is None:
        result_path = artifact_dir / "result.json"
        write_json(result_path, {"error": "No WeChat window found", "title_pattern": args.title_pattern})
        print(f"capture_probe result: {result_path}")
        return 2

    focused = focus_window(selected)
    controls = dump_controls(selected, max_controls=args.max_controls)
    uia_text = extract_uia_text(controls)

    screenshot_path = artifact_dir / "wechat_window.png"
    capture_window_screenshot(selected, screenshot_path)

    ocr_text = [] if args.skip_ocr else run_ocr(str(screenshot_path))
    clipboard = capture_clipboard_copy() if args.copy_selected else None

    result = {
        "selected": asdict(summarize_window(selected)),
        "focused": focused,
        "screenshot_path": str(screenshot_path),
        "uia_text_count": len(uia_text),
        "uia_text": uia_text,
        "ocr_text_count": len(ocr_text),
        "ocr_text": ocr_text,
        "clipboard": clipboard,
    }

    result_path = artifact_dir / "result.json"
    controls_path = artifact_dir / "uia_controls.json"
    write_json(result_path, result)
    write_json(controls_path, controls)
    print(f"capture_probe result: {result_path}")
    print(f"uia_text_count={len(uia_text)} ocr_text_count={len(ocr_text)} focused={focused}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

