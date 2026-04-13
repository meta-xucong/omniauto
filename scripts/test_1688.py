"""1688 反爬测试脚本."""

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def test_1688(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    # 访问 1688 首页并搜索
    await browser.goto("https://www.1688.com")
    await asyncio.sleep(5)

    # 截图看页面状态
    shot1 = await browser.screenshot("/tmp/1688_home.png")
    title1 = await browser.evaluate("document.title")

    # 尝试输入搜索词
    try:
        await browser.type_text('input[type="text"]', "机械键盘", interval=(0.05, 0.1))
        await asyncio.sleep(1)
        page = browser.page
        await page.keyboard.press("Enter")
        await asyncio.sleep(5)
        title2 = await browser.evaluate("document.title")
        shot2 = await browser.screenshot("/tmp/1688_search.png")
        return StepResult(success=True, data={
            "home_title": title1,
            "search_title": title2,
            "home_shot": shot1,
            "search_shot": shot2,
        })
    except Exception as e:
        return StepResult(success=False, data={
            "home_title": title1,
            "home_shot": shot1,
            "error": str(e),
        })

workflow = Workflow(task_id="test_1688")
workflow.add_step(AtomicStep("test_1688", test_1688, lambda r: True))
