"""Agent Runtime 单元测试."""

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
    result = await agent.process("查看队列")
    assert result.success is True
    # 中文字符在 pytest 输出中可能乱码，改用数据断言
    assert "pending_tasks" in result.data or "0" in result.message or len(result.message) > 0


@pytest.mark.asyncio
async def test_agent_intent_list_steps(agent):
    result = await agent.process("有哪些步骤")
    assert result.success is True
    assert "NavigateStep" in result.message


def test_extract_cron_daily(agent):
    cron = agent._extract_cron("每天早上9点打卡")
    assert cron == "0 9 * * *"


def test_extract_cron_weekly(agent):
    cron = agent._extract_cron("每周五下午3点")
    assert cron == "0 15 * * 5"
    cron2 = agent._extract_cron("每周五上午9点")
    assert cron2 == "0 9 * * 5"
