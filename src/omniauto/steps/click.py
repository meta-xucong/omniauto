"""点击原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext
from ..utils.mouse import random_delay


def ClickStep(selector: str, pre_delay: tuple[float, float] = (0.1, 0.3)) -> AtomicStep:
    """创建浏览器点击原子步骤.

    Args:
        selector: CSS 选择器.
        pre_delay: 点击前随机延迟.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        await random_delay(*pre_delay)
        await browser.click(selector)
        return True

    return AtomicStep(
        step_id=f"click_{selector.replace(' ', '_').replace('>', '_')}",
        action=action,
        validator=lambda r: r is True,
        description=f"点击元素 {selector}",
    )
