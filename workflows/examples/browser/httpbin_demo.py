"""Demo 脚本：访问 httpbin.org 并提取页面标题."""

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def run_task(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://httpbin.org/html")
    await asyncio.sleep(1)
    title = await browser.extract_text("h1")
    return StepResult(success=True, data=title)

steps = [
    AtomicStep("main", run_task, lambda r: r.success),
]
workflow = Workflow(task_id="demo_httpbin", steps=steps)
