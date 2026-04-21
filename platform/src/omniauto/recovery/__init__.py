"""Recovery-layer public exports."""

from .fallback import (
    BrowserAIRecoveryDecider,
    BrowserRecoveryFallback,
    ChainedRecoveryFallback,
    ConstrainedAIRecoveryFallback,
    HeuristicRecoveryFallback,
)
from .manager import BrowserRecoveryManager
from .models import (
    BrowserCheckboxSnapshot,
    BrowserInterruptionSnapshot,
    RecoveryAction,
    RecoveryAttemptResult,
    RecoveryPlan,
)
from .policy import RecoveryPolicy
from .registry import BrowserRecoveryRegistry, RecoveryRule

__all__ = [
    "BrowserCheckboxSnapshot",
    "BrowserInterruptionSnapshot",
    "BrowserAIRecoveryDecider",
    "BrowserRecoveryFallback",
    "BrowserRecoveryManager",
    "BrowserRecoveryRegistry",
    "ChainedRecoveryFallback",
    "ConstrainedAIRecoveryFallback",
    "HeuristicRecoveryFallback",
    "RecoveryAction",
    "RecoveryAttemptResult",
    "RecoveryPlan",
    "RecoveryPolicy",
    "RecoveryRule",
]
