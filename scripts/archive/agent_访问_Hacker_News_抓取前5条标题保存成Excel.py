# Auto-generated OmniAuto atomic script
# Task: 访问 Hacker News，抓取前5条标题保存成Excel

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.core.exceptions import GuardianBlockedError

async def run_task(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    path = await browser.screenshot()
    return StepResult(success=True, data=path)
    data = await browser.extract_text("body")
    return StepResult(success=True, data=data)
    return StepResult(success=True)

steps = [
    AtomicStep("main", run_task, lambda r: r.success)
]
workflow = Workflow(task_id="auto_task", steps=steps)
