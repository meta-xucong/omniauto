"""Schemas for AI-assisted knowledge candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class AICandidate:
    """A strongly bounded AI-generated knowledge candidate."""

    kind: str
    title: str
    summary: str
    domain: str = "general"
    slug: str = ""
    stage: str = ""
    maturity: str = "medium"
    confidence: str = "medium"
    tags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    boundaries: str = ""
    uncertainty_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AIAssistResult:
    """Outcome of one AI-assisted knowledge candidate pass."""

    enabled: bool
    applied: bool
    reason: str
    candidates: list[AICandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    evidence_pack: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "applied": self.applied,
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "errors": list(self.errors),
            "evidence_pack": self.evidence_pack,
        }

