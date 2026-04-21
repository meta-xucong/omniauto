import pytest

from omniauto.recovery.fallback import HeuristicRecoveryFallback
from omniauto.recovery.models import BrowserCheckboxSnapshot, BrowserInterruptionSnapshot
from omniauto.recovery.registry import BrowserRecoveryRegistry


AGREEMENT_TEXT = "\u5df2\u9605\u8bfb\u5e76\u540c\u610f\u670d\u52a1\u534f\u8bae\u53ca\u9690\u79c1\u4fdd\u62a4"
SEND_SMS_TEXT = "\u53d1\u9001\u9a8c\u8bc1\u7801"
DISMISS_TEXT = "\u7a0d\u540e\u518d\u8bf4"


def test_default_registry_matches_agreement_checkbox_blocker():
    snapshot = BrowserInterruptionSnapshot(
        url="https://login.taobao.com/",
        title="\u6dd8\u5b9d\u767b\u5f55",
        visible_texts=["\u77ed\u4fe1\u767b\u5f55", SEND_SMS_TEXT, AGREEMENT_TEXT],
        buttons=[SEND_SMS_TEXT],
        checkboxes=[BrowserCheckboxSnapshot(label=AGREEMENT_TEXT, checked=False)],
        dialogs=[],
    )

    rules = BrowserRecoveryRegistry.default().match(snapshot, trigger="error_click")

    assert rules
    assert rules[0].name == "agreement_checkbox_required"

    plan = rules[0].planner(snapshot)
    assert [action.action_type for action in plan.actions] == ["check_text", "click_text", "wait"]
    assert plan.actions[0].target == AGREEMENT_TEXT
    assert plan.actions[1].target == SEND_SMS_TEXT


@pytest.mark.asyncio
async def test_heuristic_fallback_proposes_low_risk_dialog_dismissal():
    snapshot = BrowserInterruptionSnapshot(
        url="https://example.com/",
        title="\u793a\u4f8b\u9875\u9762",
        visible_texts=["\u5f00\u542f\u901a\u77e5\u4ee5\u4fbf\u53ca\u65f6\u83b7\u53d6\u66f4\u65b0", DISMISS_TEXT],
        buttons=["\u5141\u8bb8", DISMISS_TEXT],
        checkboxes=[],
        dialogs=["\u901a\u77e5\u63d0\u793a"],
    )

    fallback = HeuristicRecoveryFallback()
    plan = await fallback.plan(snapshot, allowed_actions={"click_text", "wait"}, trigger="after_goto")

    assert plan is not None
    assert plan.name == "heuristic_close_overlay"
    assert [action.action_type for action in plan.actions] == ["click_text", "wait"]
    assert plan.actions[0].target == DISMISS_TEXT


@pytest.mark.asyncio
async def test_heuristic_fallback_respects_action_whitelist():
    snapshot = BrowserInterruptionSnapshot(
        url="https://example.com/",
        title="\u793a\u4f8b\u9875\u9762",
        visible_texts=[AGREEMENT_TEXT],
        buttons=[SEND_SMS_TEXT],
        checkboxes=[BrowserCheckboxSnapshot(label=AGREEMENT_TEXT, checked=False)],
        dialogs=[],
    )

    fallback = HeuristicRecoveryFallback()
    plan = await fallback.plan(snapshot, allowed_actions={"wait"}, trigger="error_click")

    assert plan is None
