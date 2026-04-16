"""WPS 文字自动化技能 —— RPA 级高可靠封装.

核心设计原则：
1. 动态前台追踪：WPS/Qt 应用的真实输入窗口与 EnumWindows 枚举到的框架窗口往往不同，
   因此以 `GetForegroundWindow()` + 进程名验证为准。
2. 操作后验证：关键步骤（打开、粘贴、保存）后做效果验证，失败则重试/回退。
3. 多路径回退：快捷键被拦截时自动切到菜单点击、F12 等备用方案。
4. 状态清理：保存前删除旧文件以避免覆盖提示；保存后验证文件存在且大小>0。
5. 多标签兼容：WPS 倾向把新文档合并为标签页，通过标签点击和标题双重确认。
"""

import ctypes
import random
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple

import psutil

from docx import Document

from ..hard_input import HardInputEngine


def _create_blank_docx(path: str) -> None:
    doc = Document()
    doc.add_paragraph("")
    doc.save(path)


# --------------------------------------------------------------------------- #
# 窗口与进程工具
# --------------------------------------------------------------------------- #
def _get_tid_by_hwnd(hwnd: int) -> int:
    return ctypes.windll.user32.GetWindowThreadProcessId(hwnd, None)


def _tid_belongs_to_pid(tid: int, pid: int) -> bool:
    """高效检查指定线程 ID 是否属于指定进程."""
    try:
        proc = psutil.Process(pid)
        for t in proc.threads():
            if t.id == tid:
                return True
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def _is_wps_window(hwnd: int, expected_pid: Optional[int] = None) -> bool:
    """判断指定 hwnd 是否属于 WPS 进程."""
    tid = _get_tid_by_hwnd(hwnd)
    if not tid:
        return False
    if expected_pid is not None:
        return _tid_belongs_to_pid(tid, expected_pid)
    # fallback: 检查窗口类名是否为 WPS 常用类
    cls_buff = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, cls_buff, 256)
    cls = cls_buff.value.lower()
    if cls in ("qt5qwindowicon", "opusapp", "wpsoffice"):
        return True
    return False


def _get_wps_foreground_hwnd(expected_pid: Optional[int] = None) -> Optional[int]:
    """获取当前真正处于前台的 WPS 窗口 hwnd."""
    fg = ctypes.windll.user32.GetForegroundWindow()
    if fg and _is_wps_window(fg, expected_pid=expected_pid):
        return fg
    return None


def _wait_for_wps_foreground(
    timeout: float = 30.0,
    interval: float = 1.0,
    expected_pid: Optional[int] = None,
) -> Optional[int]:
    """等待直到 WPS 窗口成为当前前台窗口."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = _get_wps_foreground_hwnd(expected_pid=expected_pid)
        if hwnd:
            return hwnd
        time.sleep(interval)
    return None


def _get_window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buff = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buff, length + 1)
    return buff.value


def _get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    from ctypes import wintypes
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


# --------------------------------------------------------------------------- #
# 焦点管理（关键：始终基于真实前台窗口操作）
# --------------------------------------------------------------------------- #
def _focus_hwnd(hwnd: int, engine: Optional[HardInputEngine] = None) -> bool:
    """强制将窗口带到前台并临时置顶.
    对 Qt 应用，如果 API 方式失败，回退到鼠标点击标题栏（实测最可靠）.
    """
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    current_thread = kernel32.GetCurrentThreadId()
    foreground_window = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_window, None)
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)

    user32.ShowWindow(hwnd, 5)  # SW_SHOW
    if target_thread and target_thread != foreground_thread:
        user32.AttachThreadInput(foreground_thread, target_thread, True)

    user32.SetForegroundWindow(hwnd)
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_SHOWWINDOW = 0x0040
    # 临时置顶，确保在点击前不会被其他 TOPMOST 窗口遮挡
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    time.sleep(0.3)

    # 回退：鼠标点击标题栏中央（对 WPS/Qt 几乎 100% 有效）
    if user32.GetForegroundWindow() != hwnd and engine is not None:
        left, top, right, _ = _get_window_rect(hwnd)
        title_x = (left + right) // 2
        title_y = top + 12
        engine.move_to(title_x, title_y)
        engine.click()
        time.sleep(0.5)

    # 点击完成后再取消置顶，避免长期干扰用户
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    if target_thread and target_thread != foreground_thread:
        user32.AttachThreadInput(foreground_thread, target_thread, False)
    time.sleep(0.3)

    return True


def _ensure_wps_foreground(
    engine: Optional[HardInputEngine] = None,
    expected_title_contains: str = "",
    retries: int = 3,
    interval: float = 0.6,
) -> Optional[int]:
    """确保当前前台窗口是 WPS，并返回其 hwnd.

    如果当前前台不是 WPS，会尝试 _focus_hwnd 激活已知 WPS 窗口。
    """
    user32 = ctypes.windll.user32
    for _ in range(retries):
        hwnd = _get_wps_foreground_hwnd()
        if hwnd:
            if expected_title_contains:
                title = _get_window_title(hwnd)
                if expected_title_contains.lower() in title.lower():
                    return hwnd
                # 标题不匹配：可能是多标签，尝试激活标签
                if engine:
                    _focus_hwnd(hwnd, engine=engine)
                    _activate_tab_by_name(engine, hwnd, expected_title_contains)
                    # 再检查一次
                    title = _get_window_title(hwnd)
                    if expected_title_contains.lower() in title.lower():
                        return hwnd
            else:
                return hwnd

        # 当前前台不是 WPS，尝试枚举到的 WPS 窗口
        known = _find_wps_window(expected_title_contains)
        if known and engine:
            _focus_hwnd(known, engine=engine)
        time.sleep(interval)

    # 最后尝试一次
    return _get_wps_foreground_hwnd()


def _find_wps_window(doc_name: str = "") -> int:
    """查找包含指定文档名的可见 WPS 窗口（作为激活候选）."""
    from ctypes import wintypes

    target_hwnd = None

    def foreach_window(h, _lParam):
        nonlocal target_hwnd
        if not ctypes.windll.user32.IsWindowVisible(h):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(h)
        if length == 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(h, buff, length + 1)
        title = buff.value.lower()
        if "wps" in title or ".docx" in title or ".wps" in title:
            if doc_name and doc_name.lower() in title:
                target_hwnd = h
                return False
            if not doc_name:
                target_hwnd = h
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
    return target_hwnd


# --------------------------------------------------------------------------- #
# IME 与输入辅助
# --------------------------------------------------------------------------- #
def _is_ime_candidate_visible() -> bool:
    user32 = ctypes.windll.user32
    ime_classes = [
        "Microsoft.IME.UIManager.CandidateWindow.Host",
        "IMEFrame",
        "SogouPy.ime",
        "QQPYInputAlert",
    ]
    for cls in ime_classes:
        if user32.FindWindowW(cls, None):
            return True
    return False


def _dismiss_ime() -> None:
    import interception
    interception.press("esc")
    time.sleep(0.2)


def _safe_clipboard_paste(
    engine: HardInputEngine,
    text: str,
    ensure_english: bool = True,
) -> bool:
    if ensure_english:
        from ..utils.input_method import InputMethodController
        InputMethodController.ensure_english_input()
    engine.type_text(text, use_clipboard=True)
    time.sleep(0.3)
    if _is_ime_candidate_visible():
        _dismiss_ime()
        engine.type_text(text, use_clipboard=True)
        time.sleep(0.3)
    return True


def _click_doc_edit_area(engine: HardInputEngine, hwnd: int) -> None:
    left, top, right, bottom = _get_window_rect(hwnd)
    cx = (left + right) // 2
    cy = (top + bottom) // 2 + 80
    engine.move_to(cx, cy)
    engine.click()
    time.sleep(0.3)


# --------------------------------------------------------------------------- #
# 菜单与保存对话框
# --------------------------------------------------------------------------- #
def _click_file_menu(engine: HardInputEngine, hwnd: int) -> None:
    left, top, _, _ = _get_window_rect(hwnd)
    fx = left + 40
    fy = top + 80
    engine.move_to(fx, fy)
    engine.click()
    time.sleep(0.5)


def _open_save_as_dialog(engine: HardInputEngine, hwnd: int) -> bool:
    """尝试打开另存为对话框.

    WPS 的"另存为"界面通常不是独立 Win32 窗口，因此不做中间态检测，
    直接发送 F12 并等待足够时间。
    """
    engine.press("f12")
    time.sleep(2.5)
    return True


def _activate_tab_by_name(engine: HardInputEngine, hwnd: int, doc_name: str) -> bool:
    """如果 WPS 把文档合并为标签页，尝试点击对应标签."""
    left, top, right, _ = _get_window_rect(hwnd)
    scan_positions = [0.15, 0.28, 0.40, 0.52, 0.64]
    for ratio in scan_positions:
        tx = left + int((right - left) * ratio)
        ty = top + 55
        engine.move_to(tx, ty)
        engine.click()
        time.sleep(0.5)
        title = _get_window_title(hwnd)
        if doc_name.lower() in title.lower():
            return True
    return False


# --------------------------------------------------------------------------- #
# WPS 自动化主类
# --------------------------------------------------------------------------- #
class WPSWordAutomation:
    def __init__(
        self,
        wps_exe: str,
        engine: Optional[HardInputEngine] = None,
    ) -> None:
        self.wps_exe = wps_exe
        self.engine = engine or HardInputEngine().start()
        self.hwnd: Optional[int] = None
        self.doc_name: str = ""

    def open_document(
        self,
        doc_path: str,
        create_if_missing: bool = True,
        startup_timeout: float = 30.0,
    ) -> bool:
        """打开指定 docx，创建空白文档若需要，并等待 WPS 成为前台窗口."""
        path = Path(doc_path)
        if create_if_missing and not path.exists():
            _create_blank_docx(str(path))
        self.doc_name = path.name

        expected_pid = None
        # 检查是否已有包含该文档名的 WPS 窗口
        existing = _find_wps_window(self.doc_name)
        expected_pid = None
        if existing:
            # 已有窗口：主动拉到前台，而不是被动等待
            _focus_hwnd(existing, engine=self.engine)
            time.sleep(0.5)
        else:
            proc = subprocess.Popen([self.wps_exe, str(path)])
            expected_pid = proc.pid

        # 等待 WPS 成为前台窗口（优先匹配刚启动的进程）
        hwnd = _wait_for_wps_foreground(
            timeout=startup_timeout, expected_pid=expected_pid
        )
        if not hwnd and expected_pid is not None:
            # 若按 PID 未匹配到，可能是 WPS 内部又拉起新进程，放宽条件再试
            hwnd = _wait_for_wps_foreground(timeout=10)
        if not hwnd:
            return False

        # 确认标题包含目标文档名（处理多标签）
        title = _get_window_title(hwnd)
        if self.doc_name.lower() not in title.lower():
            _focus_hwnd(hwnd, engine=self.engine)
            _activate_tab_by_name(self.engine, hwnd, self.doc_name)
            # 再确认一次
            title = _get_window_title(hwnd)
            if self.doc_name.lower() not in title.lower():
                # 仍然不匹配，可能是新窗口还未完全加载，再给一次机会
                time.sleep(2)
                hwnd = _wait_for_wps_foreground(timeout=5)
                if hwnd:
                    _activate_tab_by_name(self.engine, hwnd, self.doc_name)

        self.hwnd = hwnd
        return self.hwnd is not None and _is_wps_window(self.hwnd)

    def type_text(
        self,
        text: str,
        clear_existing: bool = True,
        max_retries: int = 3,
    ) -> bool:
        """在文档编辑区输入文本，带焦点确认和重试."""
        for attempt in range(max_retries):
            hwnd = _ensure_wps_foreground(
                engine=self.engine,
                expected_title_contains=self.doc_name,
            )
            if not hwnd:
                continue
            self.hwnd = hwnd

            _click_doc_edit_area(self.engine, hwnd)

            if clear_existing:
                self.engine.hotkey("ctrl", "a")
                time.sleep(0.3)
                self.engine.press("delete")
                time.sleep(0.3)

            _safe_clipboard_paste(self.engine, text)
            time.sleep(0.5)

            if not _is_ime_candidate_visible():
                return True
            _dismiss_ime()
            time.sleep(0.5)

        return False

    def save_as(
        self,
        save_path: str,
        overwrite: bool = True,
        max_retries: int = 3,
    ) -> bool:
        """另存为指定路径，带覆盖处理和保存后验证."""
        target = Path(save_path)
        if overwrite and target.exists():
            try:
                target.unlink()
            except Exception:
                pass

        for attempt in range(max_retries):
            hwnd = _ensure_wps_foreground(
                engine=self.engine,
                expected_title_contains=self.doc_name,
            )
            if not hwnd:
                continue
            self.hwnd = hwnd

            _open_save_as_dialog(self.engine, hwnd)

            # 对话框出现后，确保焦点在文件名输入框
            self.engine.hotkey("ctrl", "a")
            time.sleep(0.3)

            _safe_clipboard_paste(self.engine, target.name, ensure_english=True)
            time.sleep(0.3)

            self.engine.press("return")
            time.sleep(3)

            if target.exists() and target.stat().st_size > 0:
                return True

            # 处理可能的覆盖提示或模态对话框
            self.engine.press("return")
            time.sleep(1)
            if target.exists() and target.stat().st_size > 0:
                return True

        return False

    def close_document(self, save_before_close: bool = False) -> bool:
        """关闭当前文档窗口."""
        hwnd = _ensure_wps_foreground(
            engine=self.engine,
            expected_title_contains=self.doc_name,
        )
        if not hwnd:
            return False
        self.hwnd = hwnd
        if save_before_close:
            self.engine.hotkey("ctrl", "s")
            time.sleep(2)
        self.engine.hotkey("alt", "f4")
        time.sleep(1)
        return True

    def save_via_menu(self, save_path: str) -> bool:
        """通过菜单栏点击"文件 -> 另存为"保存（最终回退）."""
        hwnd = _ensure_wps_foreground(
            engine=self.engine,
            expected_title_contains=self.doc_name,
        )
        if not hwnd:
            return False
        self.hwnd = hwnd

        _click_file_menu(self.engine, hwnd)
        time.sleep(1)

        left, top, right, bottom = _get_window_rect(hwnd)
        sx = left + int((right - left) * 0.12)
        sy = top + int((bottom - top) * 0.45)
        self.engine.move_to(sx, sy)
        self.engine.click()
        time.sleep(3)

        self.engine.hotkey("ctrl", "a")
        time.sleep(0.3)
        _safe_clipboard_paste(self.engine, Path(save_path).name)
        time.sleep(0.3)
        self.engine.press("return")
        time.sleep(4)

        return Path(save_path).exists() and Path(save_path).stat().st_size > 0
