"""确定性状态机工作流引擎.

核心原则: AI 绝不直接操作 UI，只生成配置；状态机负责严格执行.
"""

import asyncio
import json
import random
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

from .context import StepResult, TaskContext
from .exceptions import GuardianBlockedError, ValidationError


class TaskState(Enum):
    """工作流/步骤状态枚举."""

    PENDING = auto()
    RUNNING = auto()
    PAUSED = auto()  # 等待人工确认
    COMPLETED = auto()
    FAILED = auto()  # 可重试
    ESCALATED = auto()  # 已上报 AI 决策


@dataclass
class AtomicStep:
    """原子步骤，工作流中不可再拆分的最小执行单元.

    Attributes:
        step_id: 步骤唯一标识.
        action: 异步执行函数，签名 async def action(context: TaskContext) -> Any.
        validator: 结果校验函数，签名 def validator(result: Any) -> bool.
        retry: 最大重试次数（首次执行 + retry 次重试）.
        description: 步骤描述，用于日志和调试.
    """

    step_id: str
    action: Callable[[TaskContext], Awaitable[Any]]
    validator: Callable[[Any], bool]
    retry: int = 3
    description: str = ""
    current_retry: int = field(default=0, repr=False)

    async def execute(self, context: TaskContext) -> Tuple[TaskState, StepResult]:
        """执行原子步骤并返回状态和结果.

        Args:
            context: 任务上下文.

        Returns:
            (TaskState, StepResult) 元组.
        """
        import asyncio

        try:
            if asyncio.iscoroutinefunction(self.action):
                result = await self.action(context)
            else:
                result = self.action(context)
                if asyncio.iscoroutine(result):
                    result = await result
            if self.validator(result):
                return TaskState.COMPLETED, StepResult(success=True, data=result)
            raise ValidationError("结果校验失败")
        except Exception as exc:
            self.current_retry += 1
            if self.current_retry >= self.retry:
                return TaskState.ESCALATED, StepResult(
                    success=False, error=f"{type(exc).__name__}: {exc}"
                )
            return TaskState.FAILED, StepResult(
                success=False, error=f"{type(exc).__name__}: {exc}"
            )

    def reset(self) -> None:
        """重置重试计数器."""
        self.current_retry = 0


class StateStore:
    """基于 SQLite 的轻量级状态持久化存储.

    支持任务级和步骤级状态持久化，实现断点续传.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = str(Path.home() / ".omniauto" / "state.db")
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_state (
                    task_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    current_step INTEGER DEFAULT 0,
                    outputs TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS step_state (
                    task_id TEXT,
                    step_id TEXT,
                    state TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    error TEXT,
                    updated_at TEXT,
                    PRIMARY KEY (task_id, step_id)
                )
                """
            )

    def save_workflow(
        self,
        task_id: str,
        state: TaskState,
        current_step: int,
        outputs: Dict[str, Any],
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO workflow_state (task_id, state, current_step, outputs, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state=excluded.state,
                    current_step=excluded.current_step,
                    outputs=excluded.outputs,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    state.name,
                    current_step,
                    json.dumps(outputs, default=str),
                    datetime.now().isoformat(),
                ),
            )

    def save_step(
        self,
        task_id: str,
        step_id: str,
        state: TaskState,
        retry_count: int,
        error: Optional[str] = None,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO step_state (task_id, step_id, state, retry_count, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, step_id) DO UPDATE SET
                    state=excluded.state,
                    retry_count=excluded.retry_count,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    step_id,
                    state.name,
                    retry_count,
                    error,
                    datetime.now().isoformat(),
                ),
            )

    def load_workflow(self, task_id: str) -> Optional[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state, current_step, outputs FROM workflow_state WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "state": TaskState[row[0]],
            "current_step": row[1],
            "outputs": json.loads(row[2]) if row[2] else {},
        }

    def reset_task(self, task_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM workflow_state WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM step_state WHERE task_id=?", (task_id,))


class Workflow:
    """确定性工作流编排器.

    按顺序执行 AtomicStep 序列，支持 Guardian 节点、断点续传、异常上报.
    """

    def __init__(
        self,
        task_id: Optional[str] = None,
        steps: Optional[List[AtomicStep]] = None,
        guardian_points: Optional[Set[int]] = None,
        store: Optional[StateStore] = None,
        auto_reset_on_completed: bool = True,
        inter_step_delay: Union[Tuple[float, float], float] = 0.0,
    ) -> None:
        self.task_id = task_id or str(uuid.uuid4())
        self.steps = steps or []
        self.guardian_points = set(guardian_points or [])
        self.store = store or StateStore()
        self.auto_reset_on_completed = auto_reset_on_completed
        if isinstance(inter_step_delay, (int, float)):
            self.inter_step_delay = (float(inter_step_delay), float(inter_step_delay))
        else:
            self.inter_step_delay = inter_step_delay

    def add_step(self, step: AtomicStep) -> "Workflow":
        """链式添加原子步骤."""
        self.steps.append(step)
        return self

    def set_guardian(self, *indices: int) -> "Workflow":
        """链式设置 Guardian 节点索引."""
        self.guardian_points.update(indices)
        return self

    async def run(
        self,
        context: Optional[TaskContext] = None,
        guardian_callback: Optional[Callable[[AtomicStep, TaskContext], Awaitable[bool]]] = None,
    ) -> TaskState:
        """运行工作流.

        Args:
            context: 任务上下文，若未提供则自动生成.
            guardian_callback: Guardian 回调，返回 True 表示允许继续，False 表示阻止.

        Returns:
            工作流最终状态.
        """
        if context is None:
            context = TaskContext(task_id=self.task_id)

        # 尝试恢复断点
        resume_info = self.store.load_workflow(self.task_id)
        start_index = 0
        if resume_info and resume_info["state"] in (TaskState.RUNNING, TaskState.PAUSED, TaskState.FAILED):
            start_index = resume_info["current_step"]
            context.outputs.update(resume_info.get("outputs", {}))

        self.store.save_workflow(self.task_id, TaskState.RUNNING, start_index, context.outputs.copy())

        final_state = TaskState.COMPLETED
        for idx in range(start_index, len(self.steps)):
            step = self.steps[idx]
            step.reset()

            await self._attempt_recovery(step, context, trigger="before_step")

            # Guardian 检查
            if idx in self.guardian_points:
                self.store.save_workflow(self.task_id, TaskState.PAUSED, idx, context.outputs.copy())
                if guardian_callback is not None:
                    if asyncio.iscoroutinefunction(guardian_callback):
                        allowed = await guardian_callback(step, context)
                    else:
                        allowed = guardian_callback(step, context)
                    if not allowed:
                        self.store.save_workflow(self.task_id, TaskState.PAUSED, idx, context.outputs.copy())
                        raise GuardianBlockedError(f"Guardian 阻止了步骤 {step.step_id}")
                else:
                    # 默认 Guardian 行为：打印警告并继续（生产环境应暂停）
                    print(f"[GUARDIAN] 步骤 {step.step_id} 需要人工确认，默认放行（生产环境请配置回调）")

            # 执行步骤（带重试）
            state, result = await self._execute_with_retry(step, context)

            # 保存步骤结果到上下文
            if result.data is not None:
                context.outputs[step.step_id] = result.data

            self.store.save_step(
                self.task_id, step.step_id, state, step.current_retry, result.error
            )
            self.store.save_workflow(
                self.task_id, state, idx + 1, context.outputs.copy()
            )

            if state == TaskState.ESCALATED:
                final_state = TaskState.ESCALATED
                # 继续执行后续步骤还是停止？这里选择停止并上报
                break
            elif state == TaskState.FAILED:
                # 理论上 AtomicStep 内部重试后应返回 ESCALATED，不会走到这里
                final_state = TaskState.FAILED
                break

            await self._attempt_recovery(step, context, trigger="after_step")

            # 步骤间随机冷却（默认 0，不影响现有行为）
            if self.inter_step_delay[1] > 0 and idx < len(self.steps) - 1:
                await asyncio.sleep(random.uniform(self.inter_step_delay[0], self.inter_step_delay[1]))

        if final_state == TaskState.COMPLETED and self.auto_reset_on_completed:
            self.store.save_workflow(self.task_id, TaskState.COMPLETED, len(self.steps), context.outputs.copy())

        return final_state

    async def _execute_with_retry(
        self, step: AtomicStep, context: TaskContext
    ) -> Tuple[TaskState, StepResult]:
        """执行步骤，支持内置重试循环."""
        while True:
            state, result = await step.execute(context)
            if state == TaskState.COMPLETED:
                return state, result

            if state == TaskState.ESCALATED:
                recovered = await self._attempt_recovery(
                    step,
                    context,
                    trigger="on_error",
                    error=result.error,
                )
                if recovered:
                    step.current_retry = max(0, step.current_retry - 1)
                    await asyncio.sleep(0.2)
                    continue
                return state, result

            recovered = await self._attempt_recovery(
                step,
                context,
                trigger="on_error",
                error=result.error,
            )
            if recovered:
                await asyncio.sleep(0.2)
                continue
            # FAILED 表示还可以重试
            await asyncio.sleep(0.5)

    async def _attempt_recovery(
        self,
        step: AtomicStep,
        context: TaskContext,
        trigger: str,
        error: Optional[str] = None,
    ) -> bool:
        browser = (context.browser_state or {}).get("browser")
        if browser is None or not hasattr(browser, "recover_from_interruptions"):
            return False

        try:
            result = await browser.recover_from_interruptions(
                trigger=trigger,
                error=error,
                step_id=step.step_id,
            )
        except Exception:
            return False

        if not getattr(result, "handled", False):
            if getattr(result, "handoff_requested", False):
                context.metadata.setdefault("handoff_events", []).append(result.to_dict())
            return False

        context.metadata.setdefault("recovery_events", []).append(result.to_dict())
        return True
