"""数据提取原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def ExtractTextStep(selector: str) -> AtomicStep:
    """提取元素文本内容.

    Args:
        selector: CSS 选择器.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> str:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        return await browser.extract_text(selector)

    return AtomicStep(
        step_id=f"extract_text_{selector.replace(' ', '_').replace('>', '_')}",
        action=action,
        validator=lambda r: isinstance(r, str),
        description=f"提取 {selector} 的文本",
    )


def ExtractAttributeStep(selector: str, attribute: str) -> AtomicStep:
    """提取元素指定属性.

    Args:
        selector: CSS 选择器.
        attribute: 属性名（如 href、src）.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> str:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        return await browser.extract_attribute(selector, attribute)

    return AtomicStep(
        step_id=f"extract_attr_{selector.replace(' ', '_').replace('>', '_')}_{attribute}",
        action=action,
        validator=lambda r: isinstance(r, str),
        description=f"提取 {selector} 的 {attribute} 属性",
    )
