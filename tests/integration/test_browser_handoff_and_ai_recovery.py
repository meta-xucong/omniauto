import asyncio

import pytest
from playwright.async_api import async_playwright

from omniauto.recovery import (
    BrowserRecoveryManager,
    ChainedRecoveryFallback,
    ConstrainedAIRecoveryFallback,
    HeuristicRecoveryFallback,
    RecoveryAction,
    RecoveryPlan,
    RecoveryPolicy,
)


VERIFICATION_HTML = """
<!doctype html>
<html lang="zh-CN">
  <body>
    <div id="challenge">请完成安全验证，拖动滑块继续</div>
  </body>
</html>
"""

NORMAL_HTML = """
<!doctype html>
<html lang="zh-CN">
  <body>
    <div id="ready">验证已完成</div>
  </body>
</html>
"""

AI_FALLBACK_HTML = """
<!doctype html>
<html lang="zh-CN">
  <body>
    <button id="continue">继续流程</button>
    <div id="status">idle</div>
    <script>
      document.getElementById("continue").addEventListener("click", () => {
        document.getElementById("status").textContent = "done";
      });
    </script>
  </body>
</html>
"""


@pytest.mark.asyncio
async def test_browser_recovery_manager_waits_for_manual_handoff_resolution(tmp_path):
    artifact_dir = tmp_path / "handoff_case"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(VERIFICATION_HTML)

        async def clear_challenge():
            await asyncio.sleep(0.5)
            await page.set_content(NORMAL_HTML)

        asyncio.create_task(clear_challenge())
        manager = BrowserRecoveryManager(
            page_getter=lambda: page,
            artifact_dir_getter=lambda: str(artifact_dir),
        )
        manager.policy.manual_handoff_timeout_sec = 3.0
        manager.policy.manual_handoff_poll_interval_sec = 0.2

        result = await manager.recover(trigger="after_goto", error="verification challenge")
        await browser.close()

    assert result.handled is True
    assert result.source == "manual_handoff"
    assert result.handoff_requested is True
    assert result.handoff_reason == "verification_challenge_detected"
    assert (artifact_dir / "recovery").exists()
    assert any(path.suffix == ".json" for path in (artifact_dir / "recovery").iterdir())


@pytest.mark.asyncio
async def test_browser_recovery_manager_uses_constrained_ai_fallback(tmp_path):
    artifact_dir = tmp_path / "ai_case"

    async def decider(snapshot, allowed_actions, trigger):
        if "继续流程" not in snapshot.buttons:
            return None
        return RecoveryPlan(
            name="ai_continue_flow",
            source="ai_fallback",
            confidence=0.62,
            actions=[
                RecoveryAction("click_text", target="继续流程", source="ai_fallback"),
                RecoveryAction("wait", value=0.1, source="ai_fallback"),
            ],
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(AI_FALLBACK_HTML)

        manager = BrowserRecoveryManager(
            page_getter=lambda: page,
            artifact_dir_getter=lambda: str(artifact_dir),
            fallback=ChainedRecoveryFallback(
                [
                    HeuristicRecoveryFallback(),
                    ConstrainedAIRecoveryFallback(decider),
                ]
            ),
        )

        result = await manager.recover(trigger="after_goto")
        status_text = await page.locator("#status").text_content()
        await browser.close()

    assert result.handled is True
    assert result.source == "ai_fallback"
    assert "ai_continue_flow" in result.matched_rules
    assert status_text == "done"


@pytest.mark.asyncio
async def test_browser_recovery_manager_stops_immediately_for_sensitive_site_handoff(tmp_path):
    artifact_dir = tmp_path / "immediate_handoff_case"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(VERIFICATION_HTML)

        manager = BrowserRecoveryManager(
            page_getter=lambda: page,
            artifact_dir_getter=lambda: str(artifact_dir),
            policy=RecoveryPolicy(
                sensitive_site_mode=True,
                stop_on_risk_pages=True,
                wait_for_manual_handoff=False,
                manual_handoff_timeout_sec=3.0,
                manual_handoff_poll_interval_sec=0.2,
            ),
        )

        result = await manager.recover(trigger="after_goto", error="verification challenge")
        await browser.close()

    assert result.handled is False
    assert result.source == "manual_handoff"
    assert result.handoff_requested is True
    assert result.handoff_reason == "verification_challenge_detected"
    assert (artifact_dir / "recovery").exists()


@pytest.mark.asyncio
async def test_browser_recovery_manager_noop_checks_do_not_consume_budget(tmp_path):
    artifact_dir = tmp_path / "noop_case"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content("<html><body><div id='ready'>normal page</div></body></html>")

        manager = BrowserRecoveryManager(
            page_getter=lambda: page,
            artifact_dir_getter=lambda: str(artifact_dir),
            policy=RecoveryPolicy(max_total_cycles=1, count_noop_cycles=False),
        )

        first = await manager.recover(trigger="before_goto")
        second = await manager.recover(trigger="before_wait_for_selector")
        await browser.close()

    assert first.handled is False
    assert first.error is None
    assert second.handled is False
    assert second.error is None
