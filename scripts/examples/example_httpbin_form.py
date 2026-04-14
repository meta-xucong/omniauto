"""示例：访问 httpbin 表单页面，输入并提交.

运行方式:
    omni run --script scripts/example_httpbin_form.py --headless
"""

from omniauto.core.state_machine import Workflow
from omniauto.steps.navigate import NavigateStep
from omniauto.steps.type import TypeStep
from omniauto.steps.click import ClickStep
from omniauto.steps.wait import WaitStep
from omniauto.steps.extract import ExtractTextStep

workflow = Workflow(task_id="httpbin_form_demo")
workflow.add_step(NavigateStep("https://httpbin.org/forms/post"))
workflow.add_step(WaitStep(1.0))
workflow.add_step(TypeStep("input[name='custname']", "OmniAuto"))
workflow.add_step(ClickStep('button:has-text("Submit order")'))
workflow.add_step(WaitStep(1.0))
workflow.add_step(ExtractTextStep("h1"))
