"""Low-cost recovery fallback chain."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable, Optional, Protocol, Set

from .models import BrowserInterruptionSnapshot, RecoveryAction, RecoveryPlan
from .registry import SUBMIT_OR_CONTINUE_KEYWORDS, _contains_any, _first_matching


class BrowserRecoveryFallback(Protocol):
    """Protocol for constrained browser recovery fallbacks."""

    async def plan(
        self,
        snapshot: BrowserInterruptionSnapshot,
        allowed_actions: Iterable[str],
        trigger: str,
    ) -> Optional[RecoveryPlan]:
        ...


BrowserAIRecoveryDecider = Callable[
    [BrowserInterruptionSnapshot, Iterable[str], str],
    Awaitable[Optional[RecoveryPlan]],
]


@dataclass
class ChainedRecoveryFallback:
    """Run multiple constrained fallback stages in order."""

    fallbacks: list[BrowserRecoveryFallback]

    async def plan(
        self,
        snapshot: BrowserInterruptionSnapshot,
        allowed_actions: Iterable[str],
        trigger: str,
    ) -> Optional[RecoveryPlan]:
        for fallback in self.fallbacks:
            plan = await fallback.plan(snapshot, allowed_actions, trigger)
            if plan is not None:
                return plan
        return None


@dataclass
class ConstrainedAIRecoveryFallback:
    """Structured AI-assisted fallback constrained to whitelisted actions."""

    decider: BrowserAIRecoveryDecider

    async def plan(
        self,
        snapshot: BrowserInterruptionSnapshot,
        allowed_actions: Iterable[str],
        trigger: str,
    ) -> Optional[RecoveryPlan]:
        plan = await self.decider(snapshot, allowed_actions, trigger)
        if plan is None:
            return None
        plan.source = plan.source or "ai_fallback"
        return plan


@dataclass
class HeuristicRecoveryFallback:
    """Structured heuristic fallback with a strict action whitelist."""

    def _is_allowed(self, action_name: str, allowed_actions: Iterable[str]) -> bool:
        return action_name in set(allowed_actions)

    def _append_wait(self, allowed: Set[str], actions: list[RecoveryAction], seconds: float, description: str) -> None:
        if self._is_allowed("wait", allowed):
            actions.append(
                RecoveryAction(
                    "wait",
                    value=seconds,
                    description=description,
                    source="heuristic_fallback",
                )
            )

    def _append_retry_submit_actions(
        self,
        snapshot: BrowserInterruptionSnapshot,
        allowed: Set[str],
        actions: list[RecoveryAction],
    ) -> None:
        button = _first_matching(snapshot.buttons, SUBMIT_OR_CONTINUE_KEYWORDS)
        if button and self._is_allowed("click_text", allowed):
            actions.append(
                RecoveryAction(
                    "click_text",
                    target=button,
                    description="Retry the blocked submit-style action",
                    source="heuristic_fallback",
                )
            )
        self._append_wait(
            allowed,
            actions,
            0.35,
            "Wait for the page to respond to the heuristic recovery actions",
        )

    async def plan(
        self,
        snapshot: BrowserInterruptionSnapshot,
        allowed_actions: Iterable[str],
        trigger: str,
    ) -> Optional[RecoveryPlan]:
        allowed = set(allowed_actions)

        for checkbox in snapshot.checkboxes:
            if not checkbox.checked and _contains_any(
                checkbox.label,
                (
                    "\u534f\u8bae",
                    "\u9690\u79c1",
                    "\u6761\u6b3e",
                    "\u58f0\u660e",
                    "\u540c\u610f",
                ),
            ):
                if self._is_allowed("check_text", allowed):
                    actions = [
                        RecoveryAction(
                            "check_text",
                            target=checkbox.label,
                            description="Heuristically check an agreement/privacy checkbox",
                            source="heuristic_fallback",
                        )
                    ]
                    self._append_retry_submit_actions(snapshot, allowed, actions)
                    return RecoveryPlan(
                        name="heuristic_check_agreement",
                        source="heuristic_fallback",
                        confidence=0.65,
                        actions=actions,
                    )

        button = _first_matching(
            snapshot.buttons,
            (
                "\u5173\u95ed",
                "\u77e5\u9053\u4e86",
                "\u7a0d\u540e",
                "\u6682\u4e0d",
                "\u8df3\u8fc7",
            ),
        )
        if button and self._is_allowed("click_text", allowed):
            actions = [
                RecoveryAction(
                    "click_text",
                    target=button,
                    description="Heuristically dismiss a low-risk overlay",
                    source="heuristic_fallback",
                )
            ]
            self._append_wait(allowed, actions, 0.2, "Wait for the low-risk overlay to close")
            return RecoveryPlan(
                name="heuristic_close_overlay",
                source="heuristic_fallback",
                confidence=0.55,
                actions=actions,
            )

        confirm = _first_matching(
            snapshot.buttons,
            (
                "\u540c\u610f",
                "\u63a5\u53d7",
                "\u5141\u8bb8",
                "\u7ee7\u7eed",
                "\u786e\u8ba4",
                "\u786e\u5b9a",
            ),
        )
        if confirm and _contains_any(
            snapshot.text_blob(),
            ("cookie", "\u9690\u79c1", "\u901a\u77e5", "\u6743\u9650"),
        ):
            if self._is_allowed("click_text", allowed):
                actions = [
                    RecoveryAction(
                        "click_text",
                        target=confirm,
                        description="Heuristically confirm a low-risk dialog",
                        source="heuristic_fallback",
                    )
                ]
                self._append_wait(allowed, actions, 0.2, "Wait for the low-risk dialog to settle")
                return RecoveryPlan(
                    name="heuristic_confirm_dialog",
                    source="heuristic_fallback",
                    confidence=0.51,
                    actions=actions,
                )

        return None
