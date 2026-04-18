"""Recovery-layer data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BrowserCheckboxSnapshot:
    """Visible checkbox/radio snapshot."""

    label: str
    checked: bool = False


@dataclass
class BrowserInterruptionSnapshot:
    """Compact browser interruption snapshot."""

    url: str
    title: str = ""
    visible_texts: List[str] = field(default_factory=list)
    buttons: List[str] = field(default_factory=list)
    checkboxes: List[BrowserCheckboxSnapshot] = field(default_factory=list)
    dialogs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def text_blob(self) -> str:
        parts: List[str] = [self.title, self.url]
        parts.extend(self.visible_texts)
        parts.extend(self.buttons)
        parts.extend(cb.label for cb in self.checkboxes)
        parts.extend(self.dialogs)
        return "\n".join(part for part in parts if part).lower()

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["checkboxes"] = [asdict(item) for item in self.checkboxes]
        return data


@dataclass
class RecoveryAction:
    """Whitelisted recovery action."""

    action_type: str
    target: str = ""
    value: Any = None
    description: str = ""
    source: str = "rule"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecoveryPlan:
    """Recovery plan returned by a rule or fallback."""

    name: str
    actions: List[RecoveryAction] = field(default_factory=list)
    confidence: float = 1.0
    source: str = "rule"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "actions": [action.to_dict() for action in self.actions],
            "confidence": self.confidence,
            "source": self.source,
            "metadata": self.metadata,
        }


@dataclass
class RecoveryAttemptResult:
    """Outcome of one recovery attempt."""

    handled: bool
    trigger: str
    matched_rules: List[str] = field(default_factory=list)
    executed_actions: List[RecoveryAction] = field(default_factory=list)
    before: Optional[BrowserInterruptionSnapshot] = None
    after: Optional[BrowserInterruptionSnapshot] = None
    source: str = "rule_registry"
    error: Optional[str] = None
    handoff_requested: bool = False
    handoff_reason: Optional[str] = None
    attempt_id: Optional[str] = None
    artifact_dir: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "handled": self.handled,
            "trigger": self.trigger,
            "matched_rules": list(self.matched_rules),
            "executed_actions": [action.to_dict() for action in self.executed_actions],
            "before": self.before.to_dict() if self.before is not None else None,
            "after": self.after.to_dict() if self.after is not None else None,
            "source": self.source,
            "error": self.error,
            "handoff_requested": self.handoff_requested,
            "handoff_reason": self.handoff_reason,
            "attempt_id": self.attempt_id,
            "artifact_dir": self.artifact_dir,
        }
