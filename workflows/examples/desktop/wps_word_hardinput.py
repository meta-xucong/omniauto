"""桌面自动化（HardInput 兜底）：打开 WPS 文字，输入入党申请书，保存到桌面并关闭。"""

import asyncio
import ctypes
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from docx import Document

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.hard_input import HardInputEngine


WPS_EXE = r"C:\Users\兰落落的本本\AppData\Local\Kingsoft\WPS Office\12.1.0.25865\office6\wps.exe"
TEST_ARTIFACT_DIR = Path("runtime/test_artifacts/manual_wps")
SAVE_PATH = r"C:\Users\兰落落的本本\Desktop\入党申请书.docx"
APPEND_TEXT = "RPA fallback edit completed"

APPLICATION_TEXT = (
    "入党申请书\n\n"
    "敬爱的党组织：\n\n"
    "    我志愿加入中国共产党，愿意为共产主义事业奋斗终身。"
    "中国共产党是中国工人阶级的先锋队，同时是中国人民和中华民族的先锋队，"
    "是中国特色社会主义事业的领导核心。\n\n"
    "    我之所以要加入中国共产党，是因为我深信共产主义事业的必然成功，"
    "深信只有社会主义才能救中国，只有社会主义才能发展中国。\n\n"
    "    请党组织在实践中考验我！\n\n"
    "此致\n"
    "敬礼！\n\n"
    "申请人：XXX\n"
    "2026年4月3日\n"
)


def _create_blank_docx(path: str) -> None:
    doc = Document()
    for block in APPLICATION_TEXT.split("\n\n"):
        doc.add_paragraph(block)
    doc.save(path)


def _find_wps_window(expected_pid: int | None = None) -> int:
    from ctypes import wintypes

    candidates = []
    user32 = ctypes.windll.user32

    def _window_title(h: int) -> str:
        length = user32.GetWindowTextLengthW(h)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(h, buff, length + 1)
        return buff.value.strip().lower()

    foreground = user32.GetForegroundWindow()
    if foreground:
        title = _window_title(foreground)
        if title and ("wps" in title or "docx" in title or "word" in title):
            return foreground

    def foreach_window(h, lParam):
        if not user32.IsWindowVisible(h):
            return True
        title = _window_title(h)
        if not title:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if expected_pid is not None and pid.value != expected_pid:
            return True
        if "wps" in title or "docx" in title or "word" in title:
            candidates.append(h)
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
    if candidates:
        return candidates[-1]
    if expected_pid is not None:
        return _find_wps_window(None)
    return 0


def _focus_hwnd(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    from ctypes import wintypes

    SW_RESTORE = 9
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    current_thread = kernel32.GetCurrentThreadId()
    foreground_window = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_window, None)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"$ws = New-Object -ComObject WScript.Shell; $ws.AppActivate({pid.value}) | Out-Null",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        time.sleep(0.3)
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.AttachThreadInput(current_thread, foreground_thread, True)
    user32.BringWindowToTop(hwnd)
    user32.SetActiveWindow(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(current_thread, foreground_thread, False)
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.2)
    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.5)


async def step_open_wps(ctx: TaskContext) -> StepResult:
    if not Path(WPS_EXE).exists():
        return StepResult(success=False, error=f"WPS 未找到: {WPS_EXE}")

    TEST_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    target_path = Path(SAVE_PATH)
    for _ in range(3):
        try:
            if target_path.exists():
                target_path.unlink()
            _create_blank_docx(str(target_path))
            break
        except PermissionError:
            target_path = TEST_ARTIFACT_DIR / f"party_app_{uuid.uuid4().hex[:8]}.docx"
    else:
        return StepResult(success=False, error=f"无法创建初始文档（文件被锁定）: {target_path}")

    proc = subprocess.Popen([WPS_EXE, str(target_path)])
    time.sleep(6)

    try:
        engine = HardInputEngine().start()
    except RuntimeError as exc:
        return StepResult(success=False, error=str(exc))

    ctx.visual_state["engine"] = engine
    hwnd = _find_wps_window(proc.pid)
    if not hwnd:
        return StepResult(success=False, error="WPS 窗口未找到")
    _focus_hwnd(hwnd)
    engine.press("enter")
    time.sleep(2.5)
    engine.press("esc")
    time.sleep(0.5)
    ctx.visual_state["hwnd"] = hwnd
    ctx.visual_state["doc_path"] = str(target_path)
    return StepResult(success=True, data="WPS 文字已启动")


async def step_type_application(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 未初始化")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)

    from ctypes import wintypes

    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    title_x = (rect.left + rect.right) // 2
    title_y = rect.top + 20
    engine.move_to(title_x, title_y)
    engine.click()
    time.sleep(0.3)
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2 + 100
    engine.move_to(cx, cy)
    engine.click()
    time.sleep(0.3)

    engine.hotkey("ctrl", "end")
    time.sleep(0.3)
    engine.press("enter")
    time.sleep(0.3)
    engine.type_text(APPEND_TEXT, interval=(0.01, 0.03), ensure_english=True, use_clipboard=False)
    time.sleep(0.5)
    return StepResult(success=True, data="已追加兜底编辑文本")


async def step_save_file(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 未初始化")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)

    engine.hotkey("ctrl", "s")
    time.sleep(3)

    doc_path = Path(ctx.visual_state.get("doc_path", SAVE_PATH))
    if doc_path.exists():
        save_path = Path(SAVE_PATH)
        if doc_path.resolve() != save_path.resolve():
            shutil.copy2(doc_path, save_path)
            return StepResult(success=True, data=f"已保存到 {save_path}")
        return StepResult(success=True, data=f"已保存到 {doc_path}")
    return StepResult(success=False, error="保存后未检测到文件")


async def step_close_wps(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 未初始化")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)
    engine.hotkey("alt", "f4")
    return StepResult(success=True, data="已发送关闭指令")


workflow = Workflow(task_id="desktop_wps_word_hardinput")
workflow.add_step(AtomicStep("open_wps", step_open_wps, lambda r: r.success))
workflow.add_step(AtomicStep("type_application", step_type_application, lambda r: r.success))
workflow.add_step(AtomicStep("save_file", step_save_file, lambda r: r.success))
workflow.add_step(AtomicStep("close_wps", step_close_wps, lambda r: r.success))


if __name__ == "__main__":
    ctx = TaskContext(task_id="desktop_wps_word_hardinput")
    result = asyncio.run(workflow.run(ctx))
    print(f"Workflow result: {result}")
    for sid, out in ctx.outputs.items():
        print(f"  {sid}: {out}")
