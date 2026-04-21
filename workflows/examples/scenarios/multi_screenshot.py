"""场景5: 多页面截图存档 - 访问多个页面并保存截图."""

import asyncio
from pathlib import Path
from datetime import datetime
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow

async def multi_screenshot(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

output_dir = Path("./runtime/outputs/screenshots")
    output_dir.mkdir(parents=True, exist_ok=True)

    urls = [
        "https://httpbin.org/html",
        "https://news.ycombinator.com",
    ]

    saved_paths = []
    for idx, url in enumerate(urls, 1):
        await browser.goto(url)
        await asyncio.sleep(2)
        path = await browser.screenshot(str(output_dir / f"shot_{idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"))
        saved_paths.append(path)

    return StepResult(success=True, data={"screenshots": saved_paths})

workflow = Workflow(task_id="scenario_multi_screenshot")
workflow.add_step(AtomicStep("take_screenshots", multi_screenshot, lambda r: r.success))
