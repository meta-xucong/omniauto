"""端到端测试：完整工作流.

构造一个模拟工作流，验证 StateMachine + Steps 的完整链路.
"""

import pytest

from omniauto.core.state_machine import Workflow, AtomicStep
from omniauto.core.context import TaskContext
from omniauto.engines.browser import StealthBrowser
from omniauto.steps.navigate import NavigateStep
from omniauto.steps.extract import ExtractTextStep


@pytest.mark.asyncio
async def test_e2e_httpbin_workflow():
    browser = StealthBrowser(headless=True)
    await browser.start()
    try:
        ctx = TaskContext(task_id="e2e_httpbin", browser_state={"browser": browser})
        wf = Workflow(task_id="e2e_httpbin")
        wf.add_step(NavigateStep("https://httpbin.org/html"))
        wf.add_step(ExtractTextStep("h1"))

        state = await wf.run(ctx)
        assert state.name == "COMPLETED"
        assert "Herman Melville" in ctx.outputs.get("extract_text_h1", "")
    finally:
        await browser.close()
