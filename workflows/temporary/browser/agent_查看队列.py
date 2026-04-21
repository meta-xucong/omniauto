# Auto-generated OmniAuto atomic script
# Task: 查看队列

from omniauto.core.state_machine import Workflow
from omniauto.steps.navigate import NavigateStep

requires_browser = True

workflow = Workflow(task_id="auto_task")
workflow.add_step(NavigateStep('https://example.com'))
