"""Shared helpers for WeChat desktop feasibility probes."""

from __future__ import annotations

import argparse
import ctypes
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import ImageGrab
from pywinauto import Desktop


ARTIFACT_ROOT = Path("runtime/test_artifacts/wechat_customer_service")
WECHAT_TITLE = "".join(chr(c) for c in [0x5FAE, 0x4FE1])
DEFAULT_TITLE_PATTERN = rf"WeChat|Weixin|{WECHAT_TITLE}"
WECHAT_PROCESS_NAMES = {"weixin.exe", "wechatappex.exe"}


@dataclass
class WindowSummary:
    title: str
    handle: int
    process_id: int | None
    process_name: str | None
    class_name: str | None
    rectangle: str
    width: int
    height: int
    is_visible: bool
    is_enabled: bool


def timestamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def ensure_artifact_dir(name: str) -> Path:
    path = ARTIFACT_ROOT / name / timestamp()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def find_wechat_windows(title_pattern: str = DEFAULT_TITLE_PATTERN) -> list[Any]:
    pattern = re.compile(title_pattern, re.IGNORECASE)
    desktop = Desktop(backend="uia")
    matches = []
    for window in desktop.windows():
        process_name = get_process_name(safe_call(lambda: window.process_id(), None))
        title = safe_call(window.window_text, "")
        if process_name in WECHAT_PROCESS_NAMES:
            matches.append(window)
        elif title and pattern.search(title):
            matches.append(window)
    return matches


def summarize_window(window: Any) -> WindowSummary:
    rect = safe_call(window.rectangle, None)
    width = max(0, rect.right - rect.left) if rect else 0
    height = max(0, rect.bottom - rect.top) if rect else 0
    process_id = safe_call(lambda: window.process_id(), None)
    return WindowSummary(
        title=safe_call(window.window_text, ""),
        handle=int(safe_call(lambda: window.handle, 0)),
        process_id=process_id,
        process_name=get_process_name(process_id),
        class_name=safe_call(window.class_name, None),
        rectangle=str(rect or ""),
        width=width,
        height=height,
        is_visible=bool(safe_call(window.is_visible, False)),
        is_enabled=bool(safe_call(window.is_enabled, False)),
    )


def select_best_window(windows: list[Any]) -> Any | None:
    if not windows:
        return None
    visible = [
        window
        for window in windows
        if safe_call(window.is_visible, False) and _window_area(window) > 80_000
    ]
    official = [
        window
        for window in visible
        if get_process_name(safe_call(lambda: window.process_id(), None)) in WECHAT_PROCESS_NAMES
    ]
    candidates = official or visible or windows
    return max(candidates, key=_window_area)


def focus_window(window: Any, keep_topmost: bool = False) -> bool:
    hwnd = int(safe_call(lambda: window.handle, 0))
    if hwnd:
        force_foreground(hwnd, keep_topmost=keep_topmost)
    try:
        window.set_focus()
    except Exception:
        try:
            window.wrapper_object().set_focus()
        except Exception:
            pass
    time.sleep(0.8)
    return is_foreground(hwnd)


def force_foreground(hwnd: int, keep_topmost: bool = False) -> None:
    """Best-effort foreground activation for a desktop window."""
    if not hwnd:
        return
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)

    hwnd_topmost = -1
    hwnd_notopmost = -2
    swp_nomove = 0x0002
    swp_nosize = 0x0001
    swp_showwindow = 0x0040
    flags = swp_nomove | swp_nosize | swp_showwindow
    user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, flags)
    time.sleep(0.1)
    if not keep_topmost:
        user32.SetWindowPos(hwnd, hwnd_notopmost, 0, 0, 0, 0, flags)
    time.sleep(0.4)


def get_foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow())


def is_foreground(hwnd: int) -> bool:
    return bool(hwnd and get_foreground_window() == hwnd)


def dump_controls(window: Any, max_controls: int = 200) -> list[dict[str, Any]]:
    controls = []
    try:
        descendants = window.descendants()
    except Exception as exc:
        return [{"error": f"descendants failed: {exc}"}]

    for index, control in enumerate(descendants[:max_controls]):
        controls.append(
            {
                "index": index,
                "text": safe_call(control.window_text, ""),
                "friendly_class": safe_call(control.friendly_class_name, ""),
                "control_type": safe_call(lambda: control.element_info.control_type, ""),
                "automation_id": safe_call(lambda: control.element_info.automation_id, ""),
                "class_name": safe_call(control.class_name, ""),
                "rectangle": str(safe_call(control.rectangle, "")),
                "visible": safe_call(control.is_visible, None),
                "enabled": safe_call(control.is_enabled, None),
            }
        )
    return controls


def capture_window_screenshot(window: Any, output_path: Path) -> Path:
    rect = window.rectangle()
    bbox = (rect.left, rect.top, rect.right, rect.bottom)
    image = ImageGrab.grab(bbox=bbox)
    image.save(output_path)
    return output_path


def safe_call(fn: Any, default: Any) -> Any:
    try:
        return fn() if callable(fn) else fn
    except Exception:
        return default


def get_process_name(process_id: int | None) -> str | None:
    if not process_id:
        return None
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {int(process_id)}).Path",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
        path = result.stdout.strip()
        return Path(path).name.lower() if path else None
    except Exception:
        return None


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--title-pattern",
        default=DEFAULT_TITLE_PATTERN,
        help="Regex used to find the WeChat window title.",
    )
    parser.add_argument(
        "--max-controls",
        type=int,
        default=200,
        help="Maximum number of UIA controls to dump.",
    )


def summaries_as_dicts(windows: list[Any]) -> list[dict[str, Any]]:
    return [asdict(summarize_window(window)) for window in windows]


def _window_area(window: Any) -> int:
    rect = safe_call(window.rectangle, None)
    if rect is None:
        return 0
    return max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
