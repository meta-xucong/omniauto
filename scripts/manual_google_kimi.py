"""手动脚本：打开 Chrome，访问 Google，搜索 kimi."""

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def search_kimi(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://www.google.com")
    await asyncio.sleep(3)

    # Google 搜索框
    await browser.type_text('textarea[name="q"]', "kimi", interval=(0.05, 0.1))
    await asyncio.sleep(0.5)

    # 按 Enter 搜索 (Playwright 用 "Enter" 而非 "Return")
    page = browser.page
    await page.keyboard.press("Enter")
    await asyncio.sleep(5)

    # 提取搜索结果页标题
    title = await browser.evaluate("document.title")
    return StepResult(success=True, data=title)

workflow = Workflow(task_id="manual_google_kimi")
workflow.add_step(AtomicStep("search_kimi", search_kimi, lambda r: r.success))
