"""桌面自动化测试：打开 WPS 表格，在 E4 输入 Hello World，保存到桌面并退出."""

import asyncio
import subprocess
import time
from pathlib import Path

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.engines.visual import VisualEngine


# WPS 表格可执行文件路径
ET_EXE = r"C:\Users\兰落落的本本\AppData\Local\Kingsoft\WPS Office\12.1.0.25835\office6\et.exe"
SAVE_PATH = r"C:\Users\兰落落的本本\Desktop\test_wps_hello.xlsx"


async def step_open_wps(ctx: TaskContext) -> StepResult:
    """启动 WPS 表格."""
    if not Path(ET_EXE).exists():
        return StepResult(success=False, error=f"WPS 未找到: {ET_EXE}")
    
    subprocess.Popen([ET_EXE])
    # 等待窗口完全加载
    time.sleep(4)
    
    # 初始化 VisualEngine 并放入上下文
    engine = VisualEngine().start()
    ctx.visual_state["engine"] = engine
    
    return StepResult(success=True, data="WPS 已启动")


async def step_new_document(ctx: TaskContext) -> StepResult:
    """新建空白表格."""
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="VisualEngine 未初始化")
    
    # 在主界面按 Ctrl+N 新建空白表格
    engine.hotkey("ctrl", "n")
    time.sleep(3)
    return StepResult(success=True, data="已新建空白表格")


async def step_navigate_to_e4(ctx: TaskContext) -> StepResult:
    """通过键盘导航到 E4 单元格."""
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="VisualEngine 未初始化")
    
    # 回到 A1
    engine.hotkey("ctrl", "home")
    time.sleep(0.5)
    
    # 向右 4 次到 E1
    for _ in range(4):
        engine.press("right")
        time.sleep(0.2)
    
    # 向下 3 次到 E4
    for _ in range(3):
        engine.press("down")
        time.sleep(0.2)
    
    return StepResult(success=True, data="已定位到 E4")


async def step_type_hello(ctx: TaskContext) -> StepResult:
    """在 E4 输入 Hello World."""
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="VisualEngine 未初始化")
    
    # 自动确保英文输入法，避免中文输入干扰
    engine.type_text("Hello World", interval=(0.05, 0.1), ensure_english=True)
    time.sleep(0.2)
    # 确认单元格编辑完成
    engine.press("enter")
    return StepResult(success=True, data="已输入 Hello World")


async def step_save_file(ctx: TaskContext) -> StepResult:
    """保存到桌面."""
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="VisualEngine 未初始化")
    
    # 删除旧文件（如果存在）
    if Path(SAVE_PATH).exists():
        Path(SAVE_PATH).unlink()
    
    # 触发保存（新建文件第一次 Ctrl+S 会弹出另存为）
    engine.hotkey("ctrl", "s")
    time.sleep(3)
    
    # 另存为对话框已默认定位到桌面，只需修改文件名
    # 先全选现有文件名，再输入新文件名（纯英文避免输入法干扰）
    engine.hotkey("ctrl", "a")
    time.sleep(0.3)
    engine.type_text("test_wps_hello.xlsx", interval=(0.01, 0.03), ensure_english=True)
    time.sleep(0.5)
    
    # 确认保存
    engine.press("enter")
    time.sleep(4)
    
    # 检查是否保存成功
    if Path(SAVE_PATH).exists():
        return StepResult(success=True, data=f"已保存到 {SAVE_PATH}")
    else:
        return StepResult(success=False, error="保存后未检测到文件")


async def step_close_wps(ctx: TaskContext) -> StepResult:
    """关闭 WPS."""
    engine = ctx.visual_state.get("engine")
    if engine is None:
        return StepResult(success=False, error="VisualEngine 未初始化")
    
    engine.hotkey("alt", "f4")
    return StepResult(success=True, data="已发送关闭指令")


workflow = Workflow(task_id="test_wps_excel")
workflow.add_step(AtomicStep("open_wps", step_open_wps, lambda r: r.success))
workflow.add_step(AtomicStep("new_document", step_new_document, lambda r: r.success))
workflow.add_step(AtomicStep("navigate_e4", step_navigate_to_e4, lambda r: r.success))
workflow.add_step(AtomicStep("type_hello", step_type_hello, lambda r: r.success))
workflow.add_step(AtomicStep("save_file", step_save_file, lambda r: r.success))
workflow.add_step(AtomicStep("close_wps", step_close_wps, lambda r: r.success))


if __name__ == "__main__":
    ctx = TaskContext(task_id="test_wps_excel")
    result = asyncio.run(workflow.run(ctx))
    print(f"Workflow result: {result}")
    for sid, out in ctx.outputs.items():
        print(f"  {sid}: {out}")
