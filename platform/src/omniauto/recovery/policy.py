"""Recovery execution policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Set

from .models import RecoveryAction


DEFAULT_ALLOWED_ACTIONS = {
    "click_text",
    "click_selector",
    "check_text",
    "press_key",
    "wait",
}


@dataclass
class RecoveryPolicy:
    """Safety and budget policy for the recovery layer."""

    allowed_actions: Set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_ACTIONS))
    max_rules_per_cycle: int = 3
    max_actions_per_cycle: int = 6
    max_repeat_per_signature: int = 2
    max_total_cycles: int = 12
    manual_handoff_timeout_sec: float = 1800.0
    manual_handoff_poll_interval_sec: float = 2.0
    count_noop_cycles: bool = False
    sensitive_site_mode: bool = False
    stop_on_risk_pages: bool = True
    wait_for_manual_handoff: bool = True

    def allows(self, action: RecoveryAction) -> bool:
        return action.action_type in self.allowed_actions

    def allowed_action_names(self) -> Iterable[str]:
        return sorted(self.allowed_actions)
