"""导航原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def NavigateStep(url: str) -> AtomicStep:
    """创建浏览器导航原子步骤.

    Args:
        url: 目标地址.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化，请在 context.browser_state 中设置 'browser'")
        await browser.goto(url)
        return True

    return AtomicStep(
        step_id=f"navigate_{url.replace('://', '_').replace('/', '_').replace('.', '_')}",
        action=action,
        validator=lambda r: r is True,
        description=f"导航到 {url}",
    )
