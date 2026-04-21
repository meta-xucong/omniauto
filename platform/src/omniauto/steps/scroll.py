"""滚动原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def ScrollToBottomStep() -> AtomicStep:
    """创建滚动到页面底部原子步骤."""
    async def action(ctx: TaskContext) -> bool:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        await browser.scroll_to_bottom()
        return True

    return AtomicStep(
        step_id="scroll_bottom",
        action=action,
        validator=lambda r: r is True,
        description="滚动到页面底部",
    )
