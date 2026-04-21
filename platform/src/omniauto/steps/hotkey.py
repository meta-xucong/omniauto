"""热键原子步骤."""

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def HotkeyStep(*keys: str) -> AtomicStep:
    """创建浏览器热键原子步骤.

    Args:
        *keys: 按键序列，如 "ctrl", "l".

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        page = browser.page
        if page is None:
            raise RuntimeError("浏览器页面未打开")
        await page.keyboard.down(keys[0])
        for k in keys[1:]:
            await page.keyboard.down(k)
        for k in reversed(keys):
            await page.keyboard.up(k)
        return True

    key_str = "+".join(keys)
    return AtomicStep(
        step_id=f"hotkey_{key_str}",
        action=action,
        validator=lambda r: r is True,
        description=f"按下热键 {key_str}",
    )
