# Auto-generated OmniAuto atomic script
# Task: 打开Chrome浏览器，访问Google，搜索kimi

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.core.exceptions import GuardianBlockedError

async def run_task(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://www.google.com")
    await browser.type_text("input", "sample", interval=(0.05, 0.15))
    page = browser.page
    await page.keyboard.press("return")
    return StepResult(success=True)

steps = [
    AtomicStep("main", run_task, lambda r: r.success)
]
workflow = Workflow(task_id="auto_task", steps=steps)
