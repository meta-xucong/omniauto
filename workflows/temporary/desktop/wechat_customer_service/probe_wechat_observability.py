"""Probe WeChat observability channels without typing or sending messages.

The probe compares:
- Win32 window metadata, including display affinity and DWM cloaking.
- UI Automation text/control trees via pywinauto and uiautomation.
- Screenshot paths: PIL ImageGrab, MSS, desktop BitBlt, and PrintWindow.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import mss
import psutil
import uiautomation as auto
from PIL import Image, ImageChops, ImageGrab, ImageStat
from pywinauto import Desktop

from _probe_common import ARTIFACT_ROOT, timestamp, write_json


WECHAT_PROCESS_NAMES = {"weixin.exe", "wechatappex.exe"}
MAX_IMAGE_SIDE = 3200
MAX_TEXT_SAMPLES = 120

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
gdi32 = ctypes.windll.gdi32

user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [
    wintypes.HDC,
    wintypes.HBITMAP,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.UINT,
]
gdi32.GetDIBits.restype = ctypes.c_int


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    process_name: str
    process_path: str
    title: str
    class_name: str
    visible: bool
    enabled: bool
    iconic: bool
    zoomed: bool
    rect: tuple[int, int, int, int]
    client_rect: tuple[int, int, int, int]
    area: int
    parent: int
    owner: int
    style: str
    exstyle: str
    display_affinity: int | None
    affinity_name: str
    cloaked: int | None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=8, help="Number of largest candidate windows to exercise.")
    parser.add_argument("--uia-limit", type=int, default=1500, help="Maximum UIA controls to traverse per window.")
    parser.add_argument("--skip-capture", action="store_true", help="Only dump metadata and UIA.")
    args = parser.parse_args()

    out_dir = ARTIFACT_ROOT / "observability_probe" / timestamp()
    out_dir.mkdir(parents=True, exist_ok=True)

    windows = enumerate_wechat_windows()
    ranked = sorted(windows, key=lambda item: item.area, reverse=True)
    targets = sorted(windows, key=lambda item: (target_score(item), item.area), reverse=True)[: args.top]

    report: dict[str, Any] = {
        "artifact_dir": str(out_dir),
        "started_at": timestamp(),
        "processes": process_snapshot(),
        "windows": [asdict(item) for item in ranked],
        "targets": [],
    }

    for index, info in enumerate(targets):
        target_dir = out_dir / f"{index:02d}_{info.process_name}_{info.hwnd}"
        target_dir.mkdir(parents=True, exist_ok=True)
        target: dict[str, Any] = {"window": asdict(info), "target_score": target_score(info)}

        target["pywinauto_uia"] = probe_pywinauto_uia(info.hwnd, args.uia_limit)
        target["uiautomation"] = probe_uiautomation(info.hwnd, args.uia_limit)

        if not args.skip_capture and info.area > 0:
            activate_result = activate_window(info.hwnd)
            time.sleep(0.8)
            refreshed = get_window_info(info.hwnd)
            target["activate_result"] = activate_result
            target["after_activate"] = asdict(refreshed) if refreshed else None
            capture_info = capture_matrix(refreshed or info, target_dir)
            target["captures"] = capture_info
            clear_topmost(info.hwnd)

        report["targets"].append(target)

    report_path = out_dir / "report.json"
    write_json(report_path, report)
    print(f"observability_probe result: {report_path}")
    print(f"windows={len(windows)} targets={len(targets)}")
    for target in report["targets"]:
        window = target["window"]
        py_text = target.get("pywinauto_uia", {}).get("text_count")
        ua_text = target.get("uiautomation", {}).get("text_count")
        print(
            f"hwnd={window['hwnd']} proc={window['process_name']} class={window['class_name']} "
            f"area={window['area']} affinity={window['affinity_name']} "
            f"py_text={py_text} ua_text={ua_text}"
        )
    return 0


def process_snapshot() -> list[dict[str, Any]]:
    rows = []
    for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name in WECHAT_PROCESS_NAMES:
                rows.append(
                    {
                        "pid": proc.info["pid"],
                        "name": proc.info.get("name"),
                        "exe": proc.info.get("exe"),
                        "cmdline": proc.info.get("cmdline"),
                    }
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted(rows, key=lambda item: (str(item.get("name")), int(item.get("pid") or 0)))


def enumerate_wechat_windows() -> list[WindowInfo]:
    process_by_pid = {}
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            process_by_pid[int(proc.info["pid"])] = {
                "name": proc.info.get("name") or "",
                "exe": proc.info.get("exe") or "",
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    hwnds: list[int] = []

    def on_window(hwnd: int, _lparam: int) -> bool:
        hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(EnumWindowsProc(on_window), 0)

    all_hwnds = set(hwnds)
    for parent in list(hwnds):
        children: list[int] = []

        def on_child(hwnd: int, _lparam: int) -> bool:
            children.append(int(hwnd))
            return True

        user32.EnumChildWindows(parent, EnumChildProc(on_child), 0)
        all_hwnds.update(children)

    windows = []
    for hwnd in sorted(all_hwnds):
        pid = get_window_pid(hwnd)
        proc = process_by_pid.get(pid, {})
        name = str(proc.get("name") or "").lower()
        if name not in WECHAT_PROCESS_NAMES:
            continue
        info = get_window_info(hwnd, proc)
        if info:
            windows.append(info)
    return windows


def target_score(info: WindowInfo) -> float:
    class_name = info.class_name.lower()
    title = info.title.lower()
    score = min(info.area / 10_000, 150)
    if info.visible:
        score += 100
    if not info.iconic:
        score += 25
    if info.display_affinity == 0x11:
        score += 160
    if info.title in {"微信", "Weixin"}:
        score += 130
    if "qt51514qwindowicon" in class_name:
        score += 110
    if "chrome_widgetwin_0" in class_name:
        score += 90
    if "chrome_renderwidgethosthwnd" in class_name or "intermediate d3d window" in class_name:
        score += 60
    if info.parent or info.owner:
        score += 10
    if "ime" in class_name or "systemmessagewindow" in class_name or "power" in class_name:
        score -= 220
    if info.area <= 0:
        score -= 120
    return score


def get_window_info(hwnd: int, proc: dict[str, str] | None = None) -> WindowInfo | None:
    pid = get_window_pid(hwnd)
    if not proc:
        try:
            p = psutil.Process(pid)
            proc = {"name": p.name(), "exe": p.exe()}
        except Exception:
            proc = {"name": "", "exe": ""}

    rect = get_window_rect(hwnd)
    client = get_client_screen_rect(hwnd)
    width = max(0, rect[2] - rect[0])
    height = max(0, rect[3] - rect[1])
    affinity = get_display_affinity(hwnd)
    return WindowInfo(
        hwnd=int(hwnd),
        pid=int(pid),
        process_name=str(proc.get("name") or ""),
        process_path=str(proc.get("exe") or ""),
        title=get_window_text(hwnd),
        class_name=get_class_name(hwnd),
        visible=bool(user32.IsWindowVisible(hwnd)),
        enabled=bool(user32.IsWindowEnabled(hwnd)),
        iconic=bool(user32.IsIconic(hwnd)),
        zoomed=bool(user32.IsZoomed(hwnd)),
        rect=rect,
        client_rect=client,
        area=width * height,
        parent=int(user32.GetParent(hwnd)),
        owner=int(user32.GetWindow(hwnd, 4)),  # GW_OWNER
        style=hex(int(user32.GetWindowLongW(hwnd, -16)) & 0xFFFFFFFF),
        exstyle=hex(int(user32.GetWindowLongW(hwnd, -20)) & 0xFFFFFFFF),
        display_affinity=affinity,
        affinity_name=affinity_name(affinity),
        cloaked=get_dwm_cloaked(hwnd),
    )


def get_window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, buffer, 512)
    return buffer.value


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return (0, 0, 0, 0)
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def get_client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return (0, 0, 0, 0)
    top_left = POINT(rect.left, rect.top)
    bottom_right = POINT(rect.right, rect.bottom)
    user32.ClientToScreen(hwnd, ctypes.byref(top_left))
    user32.ClientToScreen(hwnd, ctypes.byref(bottom_right))
    return (int(top_left.x), int(top_left.y), int(bottom_right.x), int(bottom_right.y))


def get_display_affinity(hwnd: int) -> int | None:
    value = wintypes.DWORD()
    ok = user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(value))
    return int(value.value) if ok else None


def affinity_name(value: int | None) -> str:
    if value is None:
        return "unavailable"
    names = {
        0x0: "WDA_NONE",
        0x1: "WDA_MONITOR",
        0x11: "WDA_EXCLUDEFROMCAPTURE",
    }
    return names.get(value, hex(value))


def get_dwm_cloaked(hwnd: int) -> int | None:
    cloaked = ctypes.c_int(0)
    # DWMWA_CLOAKED = 14
    result = dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return int(cloaked.value) if result == 0 else None


def activate_window(hwnd: int) -> dict[str, Any]:
    result: dict[str, Any] = {"hwnd": hwnd}
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.1)
    result["bring_to_top"] = bool(user32.BringWindowToTop(hwnd))
    result["set_foreground"] = bool(user32.SetForegroundWindow(hwnd))
    result["set_topmost"] = set_window_pos(hwnd, -1)
    time.sleep(0.2)
    result["foreground"] = int(user32.GetForegroundWindow())
    return result


def set_window_pos(hwnd: int, insert_after: int) -> bool:
    flags = 0x0001 | 0x0002 | 0x0040  # NOSIZE | NOMOVE | SHOWWINDOW
    return bool(user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags))


def clear_topmost(hwnd: int) -> None:
    set_window_pos(hwnd, -2)  # HWND_NOTOPMOST


def probe_pywinauto_uia(hwnd: int, limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "error": None, "control_count": 0, "text_count": 0, "text_samples": []}
    try:
        window = Desktop(backend="uia").window(handle=hwnd)
        controls = window.descendants()
        result["ok"] = True
        result["control_count"] = len(controls)
        samples = []
        for control in controls[:limit]:
            text = safe_text(lambda: control.window_text())
            if text:
                samples.append(
                    {
                        "text": text,
                        "control_type": safe_text(lambda: control.element_info.control_type),
                        "class_name": safe_text(lambda: control.class_name()),
                        "rectangle": str(safe_any(lambda: control.rectangle(), "")),
                    }
                )
            if len(samples) >= MAX_TEXT_SAMPLES:
                break
        result["text_count"] = len(samples)
        result["text_samples"] = samples
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def probe_uiautomation(hwnd: int, limit: int) -> dict[str, Any]:
    result: dict[str, Any] = {"ok": False, "error": None, "control_count": 0, "text_count": 0, "text_samples": []}
    try:
        auto.SetGlobalSearchTimeout(1)
        root = auto.ControlFromHandle(hwnd)
        stack = [(root, 0)]
        samples = []
        count = 0
        while stack and count < limit:
            control, depth = stack.pop()
            count += 1
            name = safe_text(lambda: control.Name)
            if name:
                samples.append(
                    {
                        "text": name,
                        "control_type": safe_text(lambda: control.ControlTypeName),
                        "class_name": safe_text(lambda: control.ClassName),
                        "automation_id": safe_text(lambda: control.AutomationId),
                        "depth": depth,
                        "rectangle": str(safe_any(lambda: control.BoundingRectangle, "")),
                    }
                )
            try:
                children = control.GetChildren()
            except Exception:
                children = []
            for child in reversed(children):
                stack.append((child, depth + 1))
            if len(samples) >= MAX_TEXT_SAMPLES and count >= limit:
                break
        result["ok"] = True
        result["control_count"] = count
        result["text_count"] = len(samples)
        result["text_samples"] = samples[:MAX_TEXT_SAMPLES]
    except Exception as exc:
        result["error"] = repr(exc)
    return result


def capture_matrix(info: WindowInfo, out_dir: Path) -> dict[str, Any]:
    captures: dict[str, Any] = {}
    rect = info.rect
    if not valid_rect(rect):
        return {"error": f"invalid rect: {rect}"}

    methods: list[tuple[str, Any]] = [
        ("imagegrab_bbox", lambda: ImageGrab.grab(bbox=rect)),
        ("imagegrab_all_screens", lambda: crop_from_full(ImageGrab.grab(all_screens=True), rect)),
        ("imagegrab_layered", lambda: ImageGrab.grab(bbox=rect, include_layered_windows=True)),
        ("mss_bbox", lambda: grab_mss(rect)),
        ("desktop_bitblt", lambda: grab_desktop_bitblt(rect)),
        ("printwindow_0", lambda: print_window(info.hwnd, 0)),
        ("printwindow_2", lambda: print_window(info.hwnd, 2)),
    ]

    for name, fn in methods:
        try:
            image = fn()
            if image is None:
                captures[name] = {"ok": False, "error": "no image returned"}
                continue
            image = image.convert("RGB")
            path = out_dir / f"{name}.png"
            image_for_file = downscale(image)
            image_for_file.save(path)
            captures[name] = {"ok": True, "path": str(path), "metrics": image_metrics(image_for_file)}
        except Exception as exc:
            captures[name] = {"ok": False, "error": repr(exc)}
    return captures


def valid_rect(rect: tuple[int, int, int, int]) -> bool:
    left, top, right, bottom = rect
    return right > left and bottom > top and (right - left) <= 10000 and (bottom - top) <= 10000


def crop_from_full(image: Image.Image, rect: tuple[int, int, int, int]) -> Image.Image:
    # ImageGrab(all_screens=True) has origin at the virtual screen's left/top.
    vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    left, top, right, bottom = rect
    return image.crop((left - vx, top - vy, right - vx, bottom - vy))


def grab_mss(rect: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = rect
    monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
    with mss.mss() as sct:
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def grab_desktop_bitblt(rect: tuple[int, int, int, int]) -> Image.Image | None:
    left, top, right, bottom = rect
    width = right - left
    height = bottom - top
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    # SRCCOPY | CAPTUREBLT
    ok = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, 0x00CC0020 | 0x40000000)
    image = bitmap_to_image(hbmp, width, height) if ok else None
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return image


def print_window(hwnd: int, flags: int) -> Image.Image | None:
    rect = get_window_rect(hwnd)
    width = max(0, rect[2] - rect[0])
    height = max(0, rect[3] - rect[1])
    if width <= 0 or height <= 0:
        return None
    hdc_screen = user32.GetDC(0)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    old = gdi32.SelectObject(hdc_mem, hbmp)
    ok = user32.PrintWindow(hwnd, hdc_mem, flags)
    image = bitmap_to_image(hbmp, width, height) if ok else None
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(0, hdc_screen)
    return image


def bitmap_to_image(hbmp: int, width: int, height: int) -> Image.Image:
    bmp_info = ctypes.create_string_buffer(40)
    ctypes.memset(bmp_info, 0, 40)
    ctypes.cast(bmp_info, ctypes.POINTER(ctypes.c_uint32))[0] = 40
    ctypes.cast(bmp_info, ctypes.POINTER(ctypes.c_int32))[1] = width
    ctypes.cast(bmp_info, ctypes.POINTER(ctypes.c_int32))[2] = -height
    ctypes.cast(bmp_info, ctypes.POINTER(ctypes.c_uint16))[6] = 1
    ctypes.cast(bmp_info, ctypes.POINTER(ctypes.c_uint16))[7] = 32

    buffer = ctypes.create_string_buffer(width * height * 4)
    hdc = user32.GetDC(0)
    gdi32.GetDIBits(hdc, hbmp, 0, height, buffer, bmp_info, 0)
    user32.ReleaseDC(0, hdc)
    return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")


def downscale(image: Image.Image) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_IMAGE_SIDE:
        return image
    ratio = MAX_IMAGE_SIDE / longest
    return image.resize((max(1, math.floor(width * ratio)), max(1, math.floor(height * ratio))))


def image_metrics(image: Image.Image) -> dict[str, Any]:
    stat = ImageStat.Stat(image)
    gray = image.convert("L")
    extrema = gray.getextrema()
    hist = gray.histogram()
    total = max(1, image.size[0] * image.size[1])
    black_ratio = sum(hist[:8]) / total
    white_ratio = sum(hist[248:]) / total
    diff = ImageChops.difference(image, Image.new("RGB", image.size, image.getpixel((0, 0))))
    bbox = diff.getbbox()
    return {
        "size": image.size,
        "mean": [round(x, 2) for x in stat.mean],
        "stddev": [round(x, 2) for x in stat.stddev],
        "gray_extrema": extrema,
        "black_ratio": round(black_ratio, 4),
        "white_ratio": round(white_ratio, 4),
        "non_uniform_bbox": bbox,
    }


def safe_text(fn: Any) -> str:
    try:
        value = fn()
    except Exception:
        return ""
    return str(value or "").strip()


def safe_any(fn: Any, default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default


if __name__ == "__main__":
    raise SystemExit(main())
