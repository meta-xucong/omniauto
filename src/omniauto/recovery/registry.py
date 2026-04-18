"""Browser recovery rule registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, Set

from .models import BrowserInterruptionSnapshot, RecoveryAction, RecoveryPlan


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    lower = (text or "").lower()
    return any(token.lower() in lower for token in tokens)


def _first_matching(items: Sequence[str], tokens: Iterable[str]) -> str:
    for item in items:
        if _contains_any(item, tokens):
            return item
    return ""


AGREEMENT_KEYWORDS = (
    "\u670d\u52a1\u534f\u8bae",
    "\u9690\u79c1",
    "\u534f\u8bae",
    "\u6761\u6b3e",
    "\u5df2\u9605\u8bfb\u5e76\u540c\u610f",
    "\u6cd5\u5f8b\u58f0\u660e",
)
COOKIE_KEYWORDS = ("cookie", "cookies", "\u9690\u79c1", "\u540c\u610f")
CLOSE_KEYWORDS = (
    "\u5173\u95ed",
    "\u77e5\u9053\u4e86",
    "\u7a0d\u540e\u518d\u8bf4",
    "\u6682\u4e0d",
    "\u4e0d\u611f\u5174\u8da3",
    "\u8df3\u8fc7",
)
CONFIRM_KEYWORDS = (
    "\u540c\u610f",
    "\u63a5\u53d7",
    "\u5141\u8bb8",
    "\u7ee7\u7eed",
    "\u786e\u8ba4",
    "\u786e\u5b9a",
    "\u6211\u77e5\u9053\u4e86",
)
DISMISS_DIALOG_KEYWORDS = (
    "\u901a\u77e5",
    "\u6d88\u606f",
    "\u5b9a\u4f4d",
    "\u9ea6\u514b\u98ce",
    "\u76f8\u673a",
    "\u5f39\u7a97",
    "\u8ba2\u9605",
)
VERIFICATION_CHALLENGE_KEYWORDS = (
    "\u5b89\u5168\u9a8c\u8bc1",
    "\u8bf7\u5b8c\u6210\u9a8c\u8bc1",
    "\u62d6\u52a8\u6ed1\u5757",
    "\u6ed1\u5757",
    "\u4eba\u673a\u9a8c\u8bc1",
    "\u884c\u4e3a\u9a8c\u8bc1",
    "verify",
    "verification",
    "captcha",
)
SUBMIT_OR_CONTINUE_KEYWORDS = (
    "\u53d1\u9001\u9a8c\u8bc1\u7801",
    "\u53d1\u9001",
    "\u767b\u5f55",
    "\u63d0\u4ea4",
    "\u7ee7\u7eed",
    "\u4e0b\u4e00\u6b65",
    "\u786e\u8ba4",
    "\u4fdd\u5b58",
)


@dataclass
class RecoveryRule:
    """Single browser interruption rule."""

    name: str
    description: str
    matcher: Callable[[BrowserInterruptionSnapshot], bool]
    planner: Callable[[BrowserInterruptionSnapshot], RecoveryPlan]
    priority: int = 100
    triggers: Set[str] = field(default_factory=set)

    def matches(self, snapshot: BrowserInterruptionSnapshot, trigger: str) -> bool:
        if self.triggers and trigger not in self.triggers:
            return False
        return self.matcher(snapshot)


def _wait_action(seconds: float, description: str) -> RecoveryAction:
    return RecoveryAction("wait", value=seconds, description=description)


def _plan_agreement_checkbox(snapshot: BrowserInterruptionSnapshot) -> RecoveryPlan:
    target = ""
    for checkbox in snapshot.checkboxes:
        if not checkbox.checked and _contains_any(checkbox.label, AGREEMENT_KEYWORDS):
            target = checkbox.label
            break

    actions = [
        RecoveryAction("check_text", target=target, description="Check the agreement/privacy checkbox")
    ]
    button_target = _first_matching(snapshot.buttons, SUBMIT_OR_CONTINUE_KEYWORDS)
    if button_target:
        actions.append(
            RecoveryAction(
                "click_text",
                target=button_target,
                description="Retry the blocked submit-style action after checking the agreement",
            )
        )
        actions.append(_wait_action(0.35, "Wait for the page to respond after retrying the blocked action"))

    return RecoveryPlan(name="agreement_checkbox", actions=actions, confidence=0.98)


def _plan_cookie_consent(snapshot: BrowserInterruptionSnapshot) -> RecoveryPlan:
    button = _first_matching(snapshot.buttons, CONFIRM_KEYWORDS)
    actions = [
        RecoveryAction("click_text", target=button, description="Accept the cookie/privacy banner"),
        _wait_action(0.2, "Wait for the cookie/privacy banner to close"),
    ]
    return RecoveryPlan(name="cookie_or_privacy_banner", actions=actions, confidence=0.92)


def _plan_close_overlay(snapshot: BrowserInterruptionSnapshot) -> RecoveryPlan:
    button = _first_matching(snapshot.buttons, CLOSE_KEYWORDS)
    actions = [
        RecoveryAction("click_text", target=button, description="Dismiss a low-risk overlay"),
        _wait_action(0.2, "Wait for the low-risk overlay to close"),
    ]
    return RecoveryPlan(name="close_overlay", actions=actions, confidence=0.88)


def _plan_dismiss_dialog(snapshot: BrowserInterruptionSnapshot) -> RecoveryPlan:
    button = _first_matching(snapshot.buttons, (*CLOSE_KEYWORDS, *CONFIRM_KEYWORDS))
    actions = [
        RecoveryAction("click_text", target=button, description="Handle a low-risk notice/permission dialog"),
        _wait_action(0.2, "Wait for the notice/permission dialog to settle"),
    ]
    return RecoveryPlan(name="dismiss_dialog", actions=actions, confidence=0.81)


class BrowserRecoveryRegistry:
    """Collection of browser interruption recovery rules."""

    def __init__(self, rules: Optional[List[RecoveryRule]] = None) -> None:
        self._rules: List[RecoveryRule] = list(rules or [])

    def register(self, rule: RecoveryRule) -> "BrowserRecoveryRegistry":
        self._rules.append(rule)
        return self

    def extend(self, rules: Iterable[RecoveryRule]) -> "BrowserRecoveryRegistry":
        self._rules.extend(rules)
        return self

    def match(self, snapshot: BrowserInterruptionSnapshot, trigger: str) -> List[RecoveryRule]:
        matched = [rule for rule in self._rules if rule.matches(snapshot, trigger)]
        return sorted(matched, key=lambda item: item.priority)

    @property
    def rules(self) -> List[RecoveryRule]:
        return list(self._rules)

    @classmethod
    def default(cls) -> "BrowserRecoveryRegistry":
        registry = cls()
        registry.extend(
            [
                RecoveryRule(
                    name="agreement_checkbox_required",
                    description="Check an agreement/privacy checkbox and retry the blocked action",
                    priority=10,
                    matcher=lambda snapshot: any(
                        (not checkbox.checked) and _contains_any(checkbox.label, AGREEMENT_KEYWORDS)
                        for checkbox in snapshot.checkboxes
                    ),
                    planner=_plan_agreement_checkbox,
                ),
                RecoveryRule(
                    name="cookie_or_privacy_banner",
                    description="Accept a cookie/privacy banner",
                    priority=20,
                    matcher=lambda snapshot: _contains_any(snapshot.text_blob(), COOKIE_KEYWORDS)
                    and bool(_first_matching(snapshot.buttons, CONFIRM_KEYWORDS)),
                    planner=_plan_cookie_consent,
                ),
                RecoveryRule(
                    name="close_overlay",
                    description="Close a low-risk overlay such as later/skip/got-it",
                    priority=30,
                    matcher=lambda snapshot: bool(_first_matching(snapshot.buttons, CLOSE_KEYWORDS)),
                    planner=_plan_close_overlay,
                ),
                RecoveryRule(
                    name="dismiss_permission_or_notice_dialog",
                    description="Dismiss a low-risk notice, permission, or subscription dialog",
                    priority=40,
                    matcher=lambda snapshot: _contains_any(snapshot.text_blob(), DISMISS_DIALOG_KEYWORDS)
                    and bool(_first_matching(snapshot.buttons, (*CLOSE_KEYWORDS, *CONFIRM_KEYWORDS))),
                    planner=_plan_dismiss_dialog,
                ),
            ]
        )
        return registry
