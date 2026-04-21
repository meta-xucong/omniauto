"""人工审核节点."""

from typing import Awaitable, Callable

from ..core.state_machine import AtomicStep
from ..core.context import TaskContext


class GuardianNode:
    """Guardian 审核节点封装.

    用于在工作流执行到敏感步骤前插入人工确认逻辑.
    """

    def __init__(
        self,
        callback: Callable[[AtomicStep, TaskContext], Awaitable[bool] | bool] = None,
    ) -> None:
        """初始化 Guardian.

        Args:
            callback: 异步回调函数，接收 (step, context)，返回 True 表示允许继续.
        """
        self.callback = callback

    async def check(self, step: AtomicStep, context: TaskContext) -> bool:
        """执行 Guardian 检查.

        Args:
            step: 当前原子步骤.
            context: 任务上下文.

        Returns:
            是否允许继续执行.
        """
        if self.callback is None:
            # 默认行为：打印并放行（实际生产环境应阻塞等待人工输入）
            print(
                f"\n[GUARDIAN] 步骤 '{step.step_id}' ({step.description}) 需要人工确认。"
                "当前为自动放行模式，生产环境请配置 callback。\n"
            )
            return True
        result = self.callback(step, context)
        if hasattr(result, "__await__"):
            return await result
        return bool(result)
