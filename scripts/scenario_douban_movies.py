"""场景7: 访问豆瓣电影Top250，提取电影名称和评分，保存为Excel."""

import asyncio
from pathlib import Path
from datetime import datetime
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from openpyxl import Workbook

async def douban_movies(ctx: TaskContext) -> StepResult:
    browser = ctx.browser_state.get("browser")
    if browser is None:
        raise RuntimeError("浏览器引擎未初始化")

    await browser.goto("https://movie.douban.com/top250")
    await asyncio.sleep(4)

    page = browser.page
    # 提取电影名称和评分
    items = await page.eval_on_selector_all(
        '.item',
        '''elements => elements.slice(0, 5).map(el => {
            const titleEl = el.querySelector('.title');
            const ratingEl = el.querySelector('.rating_num');
            return {
                title: titleEl ? titleEl.innerText : '',
                rating: ratingEl ? ratingEl.innerText : ''
            };
        })'''
    )
    items = [i for i in (items or []) if i.get("title")]

    output_dir = Path("./outputs")
    output_dir.mkdir(exist_ok=True)
    excel_path = output_dir / f"douban_top5_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "豆瓣电影Top5"
    ws.append(["排名", "电影名称", "评分"])
    for idx, item in enumerate(items, 1):
        ws.append([idx, item["title"], item["rating"]])
    wb.save(str(excel_path))

    return StepResult(success=True, data={"excel_path": str(excel_path), "movies": items})

workflow = Workflow(task_id="scenario_douban_movies")
workflow.add_step(AtomicStep("fetch_douban", douban_movies, lambda r: r.success))
