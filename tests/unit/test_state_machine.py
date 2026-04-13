"""StateMachine 单元测试."""

import pytest
import asyncio

from omniauto.core.state_machine import AtomicStep, TaskState, Workflow, StateStore
from omniauto.core.context import TaskContext


@pytest.mark.asyncio
async def test_atomic_step_success(tmp_path):
    step = AtomicStep(
        step_id="test_ok",
        action=lambda ctx: asyncio.sleep(0),
        validator=lambda r: True,
    )
    ctx = TaskContext(task_id="t1")
    state, result = await step.execute(ctx)
    assert state == TaskState.COMPLETED
    assert result.success is True


@pytest.mark.asyncio
async def test_atomic_step_failure_then_escalated():
    calls = []

    async def fail_action(ctx):
        calls.append(1)
        raise RuntimeError("boom")

    step = AtomicStep(
        step_id="test_fail",
        action=fail_action,
        validator=lambda r: True,
        retry=1,  # 仅允许首次执行，失败后直接 ESCALATED
    )
    ctx = TaskContext(task_id="t1")
    state, result = await step.execute(ctx)
    assert state == TaskState.ESCALATED
    assert result.success is False
    assert "boom" in result.error
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_workflow_run_success(tmp_path):
    store = StateStore(db_path=str(tmp_path / "state.db"))
    wf = Workflow(task_id="wf1", store=store)
    wf.add_step(AtomicStep("s1", lambda ctx: asyncio.sleep(0), lambda r: True))
    wf.add_step(AtomicStep("s2", lambda ctx: {"key": "value"}, lambda r: isinstance(r, dict)))

    ctx = TaskContext(task_id="wf1")
    final = await wf.run(ctx)
    assert final == TaskState.COMPLETED
    assert ctx.outputs["s2"]["key"] == "value"


@pytest.mark.asyncio
async def test_workflow_guardian_blocks(tmp_path):
    store = StateStore(db_path=str(tmp_path / "state.db"))
    wf = Workflow(task_id="wf2", store=store)
    wf.add_step(AtomicStep("s1", lambda ctx: asyncio.sleep(0), lambda r: True))
    wf.set_guardian(0)

    from omniauto.core.exceptions import GuardianBlockedError

    with pytest.raises(GuardianBlockedError):
        await wf.run(
            TaskContext(task_id="wf2"),
            guardian_callback=lambda step, ctx: False,
        )


@pytest.mark.asyncio
async def test_workflow_resume(tmp_path):
    store = StateStore(db_path=str(tmp_path / "state.db"))
    wf = Workflow(task_id="wf3", store=store)
    wf.add_step(AtomicStep("s1", lambda ctx: asyncio.sleep(0), lambda r: True))
    wf.add_step(AtomicStep("s2", lambda ctx: asyncio.sleep(0), lambda r: True))

    # 第一次完整执行
    await wf.run(TaskContext(task_id="wf3"))

    # 重置并再次执行
    store.reset_task("wf3")
    state = await wf.run(TaskContext(task_id="wf3"))
    assert state == TaskState.COMPLETED
