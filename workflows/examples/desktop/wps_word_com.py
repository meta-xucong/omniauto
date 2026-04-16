"""桌面自动化：打开 WPS 文字，输入入党申请书，保存到桌面并关闭.

本脚本使用 WPS 的 COM 接口（Kwps.Application）进行操作，
比视觉/键鼠模拟更稳定可靠.
"""

import asyncio
from pathlib import Path

import win32com.client

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow


SAVE_PATH = r"C:\Users\兰落落的本本\Desktop\入党申请书.docx"

APPLICATION_TEXT = (
    "入党申请书\n\n"
    "敬爱的党组织：\n\n"
    "    我志愿加入中国共产党，愿意为共产主义事业奋斗终身。"
    "中国共产党是中国工人阶级的先锋队，同时是中国人民和中华民族的先锋队，"
    "是中国特色社会主义事业的领导核心。\n\n"
    "    我之所以要加入中国共产党，是因为我深信共产主义事业的必然成功，"
    "深信只有社会主义才能救中国，只有社会主义才能发展中国。\n\n"
    "    请党组织在实践中考验我！\n\n"
    "此致\n"
    "敬礼！\n\n"
    "申请人：XXX\n"
    "2026年4月13日\n"
)


async def step_create_and_save(ctx: TaskContext) -> StepResult:
    """启动 WPS 文字，输入内容，保存到桌面并关闭."""
    if Path(SAVE_PATH).exists():
        Path(SAVE_PATH).unlink()

    try:
        app = win32com.client.Dispatch("Kwps.Application")
        app.Visible = True

        doc = app.Documents.Add()
        doc.Content.Text = APPLICATION_TEXT

        doc.SaveAs(SAVE_PATH)
        doc.Close()
        app.Quit()

        if Path(SAVE_PATH).exists():
            return StepResult(success=True, data=f"已保存到 {SAVE_PATH}")
        return StepResult(success=False, error="保存后未检测到文件")
    except Exception as exc:
        return StepResult(success=False, error=f"COM 操作失败: {exc}")


workflow = Workflow(task_id="desktop_wps_word")
workflow.add_step(AtomicStep("create_and_save", step_create_and_save, lambda r: r.success))


if __name__ == "__main__":
    ctx = TaskContext(task_id="desktop_wps_word")
    result = asyncio.run(workflow.run(ctx))
    print(f"Workflow result: {result}")
    for sid, out in ctx.outputs.items():
        print(f"  {sid}: {out}")
