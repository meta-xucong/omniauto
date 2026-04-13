"""任务上下文与步骤结果数据模型."""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class StepResult(BaseModel):
    """原子步骤执行结果.

    Attributes:
        success: 步骤是否成功执行并通过校验.
        data: 步骤产生的输出数据.
        error: 失败时的异常信息（字符串化存储）.
    """

    success: bool
    data: Any = None
    error: Optional[str] = None


class TaskContext(BaseModel):
    """任务执行上下文，贯穿整个工作流生命周期.

    Attributes:
        task_id: 任务唯一标识.
        variables: 用户注入的变量字典.
        browser_state: 浏览器引擎状态（由引擎内部维护）.
        visual_state: 视觉引擎状态（由引擎内部维护）.
        outputs: 各原子步骤的输出缓存，key 为 step_id.
        metadata: 运行元数据，如耗时、截图路径、URL 等.
    """

    task_id: str
    variables: Dict[str, Any] = Field(default_factory=dict)
    browser_state: Optional[Dict[str, Any]] = Field(default_factory=dict)
    visual_state: Optional[Dict[str, Any]] = Field(default_factory=dict)
    outputs: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}
