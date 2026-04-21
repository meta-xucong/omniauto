# Auto-generated OmniAuto atomic script
# Task: 读取 D:\AI\AI_RPA\runtime\data\reports\1688_single_rocking_chair_5\report_data.json，用WPS表格整理成一个直观、方便观看的Excel报表。要求按价格升序排序，包含排名、价格、商品标题、店铺主体、来源页、品牌、材质、风格、颜色、尺寸、参数摘要、1688网页链接。请把结果保存到 D:\AI\AI_RPA\runtime\data\reports\1688_single_rocking_chair_5\1688_单人摇椅_价格排序表_skill_rpa.xlsx。

from omniauto.core.state_machine import Workflow
from omniauto.steps.extract import ExtractTextStep
from omniauto.steps.screenshot import ScreenshotStep

requires_browser = True

workflow = Workflow(task_id="auto_task")
workflow.add_step(ScreenshotStep('./screenshots'))
workflow.add_step(ExtractTextStep('body'))
