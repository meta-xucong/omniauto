"""场景1: 访问 Hacker News，抓取前10条新闻标题保存为Excel."""

import asyncio
from pathlib import Path
from datetime import datetime
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from openpyxl import Workbook

async def hn_to_excel(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    # 1. 访问 HN
    await browser.goto("https://news.ycombinator.com")
    await asyncio.sleep(3)

    # 2. 提取标题
    page = browser.page
    titles = await page.eval_on_selector_all(
        '.titleline > a',
        'elements => elements.slice(0, 10).map(e => e.innerText)'
    )
    titles = [t for t in (titles or []) if t and t.strip()]

    # 3. 保存Excel
    output_dir = Path("./outputs")
    output_dir.mkdir(exist_ok=True)
    excel_path = output_dir / f"hn_titles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "HN头条"
    ws.append(["序号", "标题"])
    for idx, title in enumerate(titles, 1):
        ws.append([idx, title])
    wb.save(str(excel_path))

    return StepResult(success=True, data={"excel_path": str(excel_path), "titles": titles})

workflow = Workflow(task_id="scenario_hn_to_excel")
workflow.add_step(AtomicStep("fetch_and_save", hn_to_excel, lambda r: r.success))
