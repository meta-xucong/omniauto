# Auto-generated OmniAuto atomic script
# Task: 查看当前有哪些定时任务

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.core.exceptions import GuardianBlockedError

async def run_task(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://example.com")
    return StepResult(success=True)

steps = [
    AtomicStep("main", run_task, lambda r: r.success)
]
workflow = Workflow(task_id="auto_task", steps=steps)
