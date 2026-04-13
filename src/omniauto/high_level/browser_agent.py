"""高层浏览器 Agent 封装.

当前版本基于 OmniAuto 自有的 StealthBrowser 封装，
提供自然语言驱动的浏览器自动化能力.
"""

from typing import Any, Optional

from ..engines.browser import StealthBrowser
from ..utils.logger import get_logger

logger = get_logger("omniauto.browser_agent")


class BrowserAgent:
    """基于 StealthBrowser 的浏览器智能体（MVP 版本）.

    当前版本将自然语言任务翻译为预定义工作流执行，
    后续版本可接入 LLM 做动态决策.

    示例:
        agent = BrowserAgent(task="登录淘宝，搜索机械键盘")
        result = await agent.run()
    """

    def __init__(
        self,
        task: str,
        llm: Any = None,
        headless: bool = False,
    ) -> None:
        self.task = task
        self.llm = llm
        self.headless = headless
        self.browser: Optional[StealthBrowser] = None

    async def run(self) -> str:
        """执行任务并返回结果摘要."""
        from ..core.state_machine import Workflow
        from ..core.context import TaskContext
        from ..steps.navigate import NavigateStep
        from ..steps.extract import ExtractTextStep
        from ..steps.screenshot import ScreenshotStep

        self.browser = await StealthBrowser(headless=self.headless).start()
        try:
            ctx = TaskContext(task_id="browser_agent_task", browser_state={"browser": self.browser})
            wf = Workflow(task_id="browser_agent_task")

            # MVP：基于关键词匹配简单任务
            task_lower = self.task.lower()
            if "http" in self.task:
                import re
                urls = re.findall(r'https?://[^\s\u3002\uff0c]+', self.task)
                if urls:
                    wf.add_step(NavigateStep(urls[0]))
            else:
                wf.add_step(NavigateStep("https://example.com"))

            if "截图" in task_lower or "screenshot" in task_lower:
                wf.add_step(ScreenshotStep())
            else:
                wf.add_step(ExtractTextStep("body"))

            state = await wf.run(ctx)
            summary = f"任务完成，状态: {state.name}"
            if ctx.outputs:
                summary += f" | 输出: {list(ctx.outputs.values())[0][:200]}"
            return summary
        finally:
            await self.browser.close()
