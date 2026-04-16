"""妗岄潰鑷姩鍖栵紙HardInput 鍏滃簳锛夛細鎵撳紑 WPS 鏂囧瓧锛岃緭鍏ュ叆鍏氱敵璇蜂功锛屼繚瀛樺埌妗岄潰骞跺叧闂?"""

import asyncio
import ctypes
import subprocess
import time
import uuid
from pathlib import Path

from docx import Document

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.hard_input import HardInputEngine


WPS_EXE = r"C:\Users\鍏拌惤钀界殑鏈湰\AppData\Local\Kingsoft\WPS Office\12.1.0.25865\office6\wps.exe"
TEST_ARTIFACT_DIR = Path("test_artifacts/manual_wps")
TEMP_DOCX = TEST_ARTIFACT_DIR / f"temp_party_app_{int(time.time())}.docx"
SAVE_PATH = r"C:\Users\鍏拌惤钀界殑鏈湰\Desktop\鍏ュ厷鐢宠涔?docx"

APPLICATION_TEXT = (
    "鍏ュ厷鐢宠涔n\n"
    "鏁埍鐨勫厷缁勭粐锛歕n\n"
    "    鎴戝織鎰垮姞鍏ヤ腑鍥藉叡浜у厷锛屾効鎰忎负鍏变骇涓讳箟浜嬩笟濂嬫枟缁堣韩銆?
    "涓浗鍏变骇鍏氭槸涓浗宸ヤ汉闃剁骇鐨勫厛閿嬮槦锛屽悓鏃舵槸涓浗浜烘皯鍜屼腑鍗庢皯鏃忕殑鍏堥攱闃燂紝"
    "鏄腑鍥界壒鑹茬ぞ浼氫富涔変簨涓氱殑棰嗗鏍稿績銆俓n\n"
    "    鎴戜箣鎵€浠ヨ鍔犲叆涓浗鍏变骇鍏氾紝鏄洜涓烘垜娣变俊鍏变骇涓讳箟浜嬩笟鐨勫繀鐒舵垚鍔燂紝"
    "娣变俊鍙湁绀句細涓讳箟鎵嶈兘鏁戜腑鍥斤紝鍙湁绀句細涓讳箟鎵嶈兘鍙戝睍涓浗銆俓n\n"
    "    璇峰厷缁勭粐鍦ㄥ疄璺典腑鑰冮獙鎴戯紒\n\n"
    "姝よ嚧\n"
    "鏁ぜ锛乗n\n"
    "鐢宠浜猴細XXX\n"
    "2026骞?鏈?3鏃n"
)


def _create_blank_docx(path: str) -> None:
    doc = Document()
    doc.add_paragraph("")
    doc.save(path)


def _find_wps_window() -> int:
    from ctypes import wintypes
    hwnd = None
    def foreach_window(h, lParam):
        nonlocal hwnd
        length = ctypes.windll.user32.GetWindowTextLengthW(h)
        buff = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(h, buff, length + 1)
        if "docx" in buff.value.lower() and "wps" in buff.value.lower():
            hwnd = h
        return True
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
    return hwnd


def _focus_hwnd(hwnd: int) -> None:
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    current_thread = kernel32.GetCurrentThreadId()
    foreground_window = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_window, None)
    user32.AttachThreadInput(current_thread, foreground_thread, True)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(current_thread, foreground_thread, False)
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
    time.sleep(0.3)


async def step_open_wps(ctx: TaskContext) -> StepResult:
    if not Path(WPS_EXE).exists():
        return StepResult(success=False, error=f"WPS 鏈壘鍒? {WPS_EXE}")

    TEST_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = TEMP_DOCX
    for _ in range(3):
        try:
            _create_blank_docx(str(temp_path))
            break
        except PermissionError:
            temp_path = temp_path.parent / f"temp_party_app_{uuid.uuid4().hex[:8]}.docx"
    else:
        return StepResult(success=False, error=f"鏃犳硶鍒涘缓涓存椂鏂囨。锛堟枃浠惰閿佸畾锛? {temp_path}")

    subprocess.Popen([WPS_EXE, str(temp_path)])
    time.sleep(6)

    try:
        engine = HardInputEngine().start()
    except RuntimeError as exc:
        return StepResult(success=False, error=str(exc))

    ctx.visual_state["engine"] = engine
    hwnd = _find_wps_window()
    if not hwnd:
        return StepResult(success=False, error="WPS 绐楀彛鏈壘鍒?)
    _focus_hwnd(hwnd)
    ctx.visual_state["hwnd"] = hwnd
    return StepResult(success=True, data="WPS 鏂囧瓧宸插惎鍔?)


async def step_type_application(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 鏈垵濮嬪寲")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)

    from ctypes import wintypes
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2 + 100
    engine.move_to(cx, cy)
    engine.click()
    time.sleep(0.3)

    engine.hotkey("ctrl", "a")
    time.sleep(0.3)
    engine.press("delete")
    time.sleep(0.3)

    engine.type_text(
        APPLICATION_TEXT,
        interval=(0.01, 0.03),
        ensure_english=True,
        use_clipboard=True,
    )
    time.sleep(0.5)
    return StepResult(success=True, data="宸茶緭鍏ュ叆鍏氱敵璇蜂功")


async def step_save_file(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 鏈垵濮嬪寲")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)

    if Path(SAVE_PATH).exists():
        Path(SAVE_PATH).unlink()

    # 浣跨敤 F12 鍙﹀瓨涓猴紙WPS 鏂囧瓧瀵瑰唴鏍哥骇 F12 搴旇鏁忔劅锛?    engine.press("f12")
    time.sleep(3)

    engine.hotkey("ctrl", "a")
    time.sleep(0.3)
    engine.type_text(
        "鍏ュ厷鐢宠涔?docx",
        interval=(0.01, 0.03),
        ensure_english=True,
        use_clipboard=True,
    )
    time.sleep(0.5)
    engine.press("enter")
    time.sleep(4)

    if Path(SAVE_PATH).exists():
        return StepResult(success=True, data=f"宸蹭繚瀛樺埌 {SAVE_PATH}")
    return StepResult(success=False, error="淇濆瓨鍚庢湭妫€娴嬪埌鏂囦欢")


async def step_close_wps(ctx: TaskContext) -> StepResult:
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="HardInputEngine 鏈垵濮嬪寲")
    hwnd = ctx.visual_state.get("hwnd")
    if hwnd:
        _focus_hwnd(hwnd)
    engine.hotkey("alt", "f4")
    return StepResult(success=True, data="宸插彂閫佸叧闂寚浠?)


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


