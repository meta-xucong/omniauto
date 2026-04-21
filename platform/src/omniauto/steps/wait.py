"""等待原子步骤."""

import asyncio

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


def WaitStep(seconds: float) -> AtomicStep:
    """创建固定等待原子步骤.

    Args:
        seconds: 等待秒数.

    Returns:
        AtomicStep 实例.
    """
    async def action(ctx: TaskContext) -> bool:
        await asyncio.sleep(seconds)
        return True

    return AtomicStep(
        step_id=f"wait_{seconds}s",
        action=action,
        validator=lambda r: r is True,
        description=f"等待 {seconds} 秒",
    )
