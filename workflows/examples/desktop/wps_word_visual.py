"""桌面自动化（RPA 级）：打开 WPS 文字，输入入党申请书，保存到桌面并关闭。

本脚本基于 `omniauto.skills.wps_automation.WPSWordAutomation`，具备以下商业 RPA 特性：
- 防御性窗口焦点管理（AttachThreadInput + TOPMOST）
- 多标签页兼容（自动点击目标标签）
- 剪贴板中文粘贴（绕过 WPS Qt+Chromium 编辑区拦截）
- 快捷键失败回退（F12 / 菜单点击）
- 保存前自动清理旧文件，保存后做文件存在性验证
- IME 候选框检测与自动消除
"""

import asyncio
import time
from pathlib import Path

from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.skills.wps_automation import WPSWordAutomation, _create_blank_docx


WPS_EXE = r"C:\Users\兰落落的本本\AppData\Local\Kingsoft\WPS Office\12.1.0.25865\office6\wps.exe"
SAVE_PATH = r"C:\Users\兰落落的本本\Desktop\入党申请书.docx"
TEST_ARTIFACT_DIR = Path("test_artifacts/manual_wps")
TEMP_DOCX = TEST_ARTIFACT_DIR / f"temp_party_app_{int(time.time())}.docx"

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
    "2026年4月3日\n"
)


async def step_open_wps(ctx: TaskContext) -> StepResult:
    import uuid

    TEST_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = TEMP_DOCX
    for _ in range(3):
        try:
            _create_blank_docx(str(temp_path))
            break
        except PermissionError:
            temp_path = temp_path.parent / f"temp_party_app_{uuid.uuid4().hex[:8]}.docx"
    else:
        return StepResult(success=False, error=f"无法创建临时文档（文件被锁定）: {temp_path}")

    wps = WPSWordAutomation(WPS_EXE)
    ctx.visual_state["wps"] = wps
    ok = wps.open_document(str(temp_path))
    if not ok:
        return StepResult(success=False, error="WPS 文字启动或窗口定位失败")
    return StepResult(success=True, data="WPS 文字已启动并聚焦")


async def step_type_application(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 自动化实例未初始化")
    ok = wps.type_text(APPLICATION_TEXT, clear_existing=True)
    if not ok:
        return StepResult(success=False, error="文本输入失败（可能是焦点丢失或 IME 异常）")
    return StepResult(success=True, data="已输入入党申请书")


async def step_save_file(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 自动化实例未初始化")

    # 主方案：F12 / Ctrl+Shift+S 打开另存为对话框并粘贴文件名
    ok = wps.save_as(SAVE_PATH, overwrite=True)
    if not ok:
        # 回退方案：菜单栏点击保存
        ok = wps.save_via_menu(SAVE_PATH)
    if not ok:
        return StepResult(success=False, error="保存失败（文件未生成或覆盖提示未处理）")
    return StepResult(success=True, data=f"已保存到 {SAVE_PATH}")


async def step_close_wps(ctx: TaskContext) -> StepResult:
    wps = ctx.visual_state.get("wps")
    if wps is None:
        return StepResult(success=False, error="WPS 自动化实例未初始化")
    wps.close_document(save_before_close=False)
    return StepResult(success=True, data="已发送关闭指令")


workflow = Workflow(task_id="desktop_wps_word_visual")
workflow.add_step(AtomicStep("open_wps", step_open_wps, lambda r: r.success))
workflow.add_step(AtomicStep("type_application", step_type_application, lambda r: r.success))
workflow.add_step(AtomicStep("save_file", step_save_file, lambda r: r.success))
workflow.add_step(AtomicStep("close_wps", step_close_wps, lambda r: r.success))


if __name__ == "__main__":
    ctx = TaskContext(task_id="desktop_wps_word_visual")
    result = asyncio.run(workflow.run(ctx))
    print(f"Workflow result: {result}")
    for sid, out in ctx.outputs.items():
        print(f"  {sid}: {out}")
