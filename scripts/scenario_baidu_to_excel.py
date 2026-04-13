"""场景1: 百度搜索"天气预报"，提取结果标题保存为Excel."""

import asyncio
from pathlib import Path
from datetime import datetime
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from openpyxl import Workbook

async def baidu_search_weather(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    # 1. 访问百度
    await browser.goto("https://www.baidu.com")
    await asyncio.sleep(3)

    # 2. 输入搜索词并搜索
    await browser.type_text('#kw', "天气预报", interval=(0.05, 0.1))
    await asyncio.sleep(0.5)
    page = browser.page
    await page.keyboard.press("Enter")
    await asyncio.sleep(3)

    # 3. 提取搜索结果标题
    titles = await page.eval_on_selector_all('h3', 'elements => elements.map(e => e.innerText)')
    titles = [t for t in (titles or []) if t and t.strip()]
    top5 = titles[:5]

    # 4. 保存为Excel
    output_dir = Path("./outputs")
    output_dir.mkdir(exist_ok=True)
    excel_path = output_dir / f"baidu_weather_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "搜索结果"
    ws.append(["序号", "标题"])
    for idx, title in enumerate(top5, 1):
        ws.append([idx, title])
    wb.save(str(excel_path))

    return StepResult(success=True, data={"excel_path": str(excel_path), "titles": top5})

workflow = Workflow(task_id="scenario_baidu_to_excel")
workflow.add_step(AtomicStep("search_and_save", baidu_search_weather, lambda r: r.success))
