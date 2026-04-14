"""手动脚本：打开 Chrome，访问百度，搜索 kimi."""

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def search_kimi(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://www.baidu.com")
    await asyncio.sleep(2)

    # 百度搜索框 #kw
    await browser.type_text('#kw', "kimi", interval=(0.05, 0.1))
    await asyncio.sleep(0.5)

    # 点击搜索按钮 #su
    await browser.click('#su')
    await asyncio.sleep(3)

    # 提取页面标题
    title = await browser.evaluate("document.title")
    return StepResult(success=True, data=title)

workflow = Workflow(task_id="manual_baidu_kimi")
workflow.add_step(AtomicStep("search_kimi", search_kimi, lambda r: r.success))
