"""输入原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def TypeStep(
    selector: str,
    text: str,
    interval: tuple[float, float] = (0.05, 0.15),
    clear: bool = True,
) -> AtomicStep:
    """创建浏览器输入原子步骤.

    Args:
        selector: CSS 选择器.
        text: 输入文本.
        interval: 字符输入间隔（秒）.
        clear: 是否先清空现有内容.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        await browser.type_text(selector, text, interval=interval, clear=clear)
        return True

    return AtomicStep(
        step_id=f"type_{selector.replace(' ', '_').replace('>', '_')}",
        action=action,
        validator=lambda r: r is True,
        description=f"在 {selector} 输入文本",
    )
