import pytest

from omniauto.core.context import TaskContext
from omniauto.core.state_machine import AtomicStep, TaskState, Workflow
from omniauto.recovery.models import RecoveryAction, RecoveryAttemptResult


class FakeRecoveryBrowser:
    def __init__(self) -> None:
        self.calls = []

    async def recover_from_interruptions(self, trigger="manual", error=None, step_id=None):
        self.calls.append((trigger, error, step_id))
        handled = trigger == "on_error"
        actions = [RecoveryAction(action_type="click_text", target="\u540c\u610f")] if handled else []
        return RecoveryAttemptResult(
            handled=handled,
            trigger=trigger,
            matched_rules=["synthetic_rule"] if handled else [],
            executed_actions=actions,
            error=error,
        )


@pytest.mark.asyncio
async def test_workflow_retries_current_step_after_recovery():
    attempts = {"count": 0}
    browser = FakeRecoveryBrowser()
    context = TaskContext(task_id="recovery-workflow", browser_state={"browser": browser})

    async def flaky_action(task_context):
        attempts["count"] += 1
        return "blocked" if attempts["count"] == 1 else "ok"

    step = AtomicStep(
        step_id="send_sms",
        action=flaky_action,
        validator=lambda value: value == "ok",
        retry=2,
        description="send sms with recovery",
    )
    workflow = Workflow(task_id="recovery-workflow", steps=[step], inter_step_delay=0.0)

    state = await workflow.run(context)

    assert state == TaskState.COMPLETED
    assert attempts["count"] == 2
    assert any(trigger == "on_error" for trigger, _, _ in browser.calls)
    assert "recovery_events" in context.metadata
    assert context.metadata["recovery_events"][0]["handled"] is True
