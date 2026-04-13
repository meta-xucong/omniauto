"""OmniAutoService 单元测试."""

import pytest
from pathlib import Path

from omniauto.service import OmniAutoService


@pytest.fixture
def svc(tmp_path):
    from omniauto.core.state_machine import StateStore
    store = StateStore(db_path=str(tmp_path / "state.db"))
    return OmniAutoService(state_store=store)


def test_plan_task(svc):
    result = svc.plan_task("访问百度搜索影刀RPA")
    assert "steps" in result
    assert len(result["steps"]) > 0


def test_generate_and_validate_script(svc, tmp_path):
    path = str(tmp_path / "test_script.py")
    gen = svc.generate_script("访问百度", path)
    assert Path(gen["script_path"]).exists()

    val = svc.validate_script(path)
    assert val["valid"] is True


@pytest.mark.asyncio
async def test_run_workflow_validation_fail(svc, tmp_path):
    bad_script = tmp_path / "bad.py"
    bad_script.write_text("eval('1+1')", encoding="utf-8")
    result = await svc.run_workflow(str(bad_script))
    assert result["final_state"] == "VALIDATION_FAILED"


def test_get_task_status_not_found(svc):
    result = svc.get_task_status("nonexistent-task-id")
    assert result["state"] == "NOT_FOUND"


def test_list_available_steps(svc):
    result = svc.list_available_steps()
    names = [s["name"] for s in result["steps"]]
    assert "NavigateStep" in names
    assert "ClickStep" in names
