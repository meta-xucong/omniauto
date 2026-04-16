"""场景3: Windows桌面自动化 - 打开记事本，输入文字，保存到 outputs 目录."""

import asyncio
from pathlib import Path
from datetime import datetime
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def notepad_auto_save(ctx: TaskContext) -> StepResult:
    import pyauto_desktop

    session = pyauto_desktop.Session(screen=1)

    # 1. Win + R 打开运行 (pyauto-desktop 中 Windows 键对应 'cmd')
    session.keyDown('cmd')
    session.keyDown('r')
    session.keyUp('r')
    session.keyUp('cmd')
    await asyncio.sleep(1)

    # 2. 输入 notepad 并回车
    session.write("notepad", interval=0.01)
    await asyncio.sleep(0.5)
    session.press('enter')
    await asyncio.sleep(2)

    # 3. 输入内容
    content = f"OmniAuto 桌面自动化测试\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n测试成功!"
    session.write(content, interval=0.01)
    await asyncio.sleep(0.5)

    # 4. Ctrl + S 保存
    session.keyDown('ctrl')
    session.keyDown('s')
    session.keyUp('s')
    session.keyUp('ctrl')
    await asyncio.sleep(1)

    # 5. 输入保存路径
    output_dir = Path("./outputs")
    output_dir.mkdir(exist_ok=True)
    save_path = str(output_dir.resolve() / f"notepad_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    session.write(save_path, interval=0.01)
    await asyncio.sleep(0.5)
    session.press('enter')
    await asyncio.sleep(1)

    # 6. 关闭记事本 Alt+F4
    session.keyDown('alt')
    session.keyDown('f4')
    session.keyUp('f4')
    session.keyUp('alt')
    await asyncio.sleep(0.5)

    return StepResult(success=True, data={"saved_path": save_path})

workflow = Workflow(task_id="scenario_notepad_auto")
workflow.add_step(AtomicStep("notepad_auto", notepad_auto_save, lambda r: r.success))
