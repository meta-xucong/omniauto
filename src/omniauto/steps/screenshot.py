"""截图原子步骤."""

from pathlib import Path

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def ScreenshotStep(output_dir: str = "./screenshots") -> AtomicStep:
    """创建浏览器截图原子步骤.

    Args:
        output_dir: 截图保存目录.

    Returns:
        AtomicStep 实例.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    async def action(ctx: TaskContext) -> str:
        browser = ctx.browser_state.get("browser")
        if browser is None:
            raise RuntimeError("浏览器引擎未初始化")
        path = str(Path(output_dir) / f"{ctx.task_id}.png")
        return await browser.screenshot(path)

    return AtomicStep(
        step_id="screenshot",
        action=action,
        validator=lambda r: isinstance(r, str) and Path(r).exists(),
        description="全页截图",
    )
