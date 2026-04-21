"""Agent Runtime unit tests."""

from pathlib import Path

import pytest

from omniauto.agent_runtime import OmniAutoAgent
from omniauto.service import OmniAutoService


@pytest.fixture
def agent(tmp_path):
    from omniauto.core.state_machine import StateStore

    svc = OmniAutoService(state_store=StateStore(db_path=str(tmp_path / "state.db")))
    return OmniAutoAgent(service=svc, headless=True)


@pytest.mark.asyncio
async def test_agent_intent_query_queue(agent):
    result = await agent.process("\u67e5\u770b\u961f\u5217")
    assert result.success is True
    assert "pending_tasks" in result.data or "0" in result.message or len(result.message) > 0


@pytest.mark.asyncio
async def test_agent_intent_list_steps(agent):
    result = await agent.process("\u6709\u54ea\u4e9b\u6b65\u9aa4")
    assert result.success is True
    assert "NavigateStep" in result.message


def test_extract_cron_daily(agent):
    cron = agent._extract_cron("\u6bcf\u5929\u65e9\u4e0a9\u70b9\u6253\u5361")
    assert cron == "0 9 * * *"


def test_extract_cron_weekly(agent):
    cron = agent._extract_cron("\u6bcf\u5468\u4e94\u4e0b\u53483\u70b9")
    assert cron == "0 15 * * 5"
    cron2 = agent._extract_cron("\u6bcf\u5468\u4e94\u4e0a\u53489\u70b9")
    assert cron2 == "0 9 * * 5"


@pytest.mark.asyncio
async def test_schedule_does_not_execute_task_immediately(agent, monkeypatch):
    monkeypatch.setattr(
        agent.service,
        "plan_task",
        lambda description: {"steps": [{"type": "navigate", "url": "https://example.com"}], "needs_guardian": False},
    )
    monkeypatch.setattr(
        agent.service,
        "generate_script",
        lambda description, output_path: {
            "script_path": output_path,
            "generated_at": "0",
            "lines_of_code": 1,
        },
    )
    monkeypatch.setattr(
        agent.service,
        "validate_script",
        lambda script_path: {"valid": True, "issues": [], "report": "[OK]"},
    )

    async def fail_run(*args, **kwargs):
        raise AssertionError("\u521b\u5efa\u5b9a\u65f6\u4efb\u52a1\u65f6\u4e0d\u5e94\u5148\u771f\u5b9e\u6267\u884c\u5de5\u4f5c\u6d41")

    scheduled: dict[str, str] = {}

    def fake_schedule(script_path: str, task_name: str, cron_expr: str, headless: bool):
        scheduled.update(
            {
                "script_path": script_path,
                "task_name": task_name,
                "cron_expr": cron_expr,
            }
        )
        return {
            "schedule_id": "sch_demo",
            "task_name": task_name,
            "cron_expr": cron_expr,
            "next_run": "2026-04-17 09:00:00",
        }

    monkeypatch.setattr(agent.service, "run_workflow", fail_run)
    monkeypatch.setattr(agent.service, "schedule_task", fake_schedule)

    result = await agent.process("\u6bcf\u5929\u4e0a\u53489\u70b9\u8bbf\u95ee\u767e\u5ea6")
    assert result.success is True
    assert scheduled["cron_expr"] == "0 9 * * *"
    assert scheduled["script_path"].endswith(".py")


@pytest.mark.asyncio
async def test_fix_script_inserts_wait_step_import(agent, tmp_path):
    script = tmp_path / "task.py"
    script.write_text(
        """from omniauto.core.state_machine import Workflow
from omniauto.steps.navigate import NavigateStep

workflow = Workflow(task_id="auto_task")
workflow.add_step(NavigateStep("https://example.com"))
""",
        encoding="utf-8",
    )

    fixed_path = await agent._fix_script(
        description="\u8bbf\u95ee\u793a\u4f8b\u7f51\u7ad9",
        script_path=str(script),
        failure_result={"error": "TimeoutError: element not found"},
        screenshot_b64="",
    )

    assert fixed_path is not None
    content = Path(fixed_path).read_text(encoding="utf-8")
    assert "from omniauto.steps.wait import WaitStep" in content
    assert "workflow.add_step(WaitStep(3.0))" in content
