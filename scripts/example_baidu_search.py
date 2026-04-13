"""示例：自动访问百度、输入关键词、搜索、截图.

运行方式:
    omni run --script scripts/example_baidu_search.py
"""

import asyncio
from omniauto.core.context import TaskContext, StepResult
from omniauto.core.state_machine import AtomicStep, Workflow
from omniauto.steps.navigate import NavigateStep
from omniauto.steps.type import TypeStep
from omniauto.steps.click import ClickStep
from omniauto.steps.wait import WaitStep
from omniauto.steps.screenshot import ScreenshotStep

workflow = Workflow(task_id="baidu_search_demo")
workflow.add_step(NavigateStep("https://www.baidu.com"))
workflow.add_step(WaitStep(1.0))
workflow.add_step(TypeStep("#kw", "影刀RPA"))
workflow.add_step(ClickStep("#su"))
workflow.add_step(WaitStep(2.0))
workflow.add_step(ScreenshotStep("./screenshots"))
