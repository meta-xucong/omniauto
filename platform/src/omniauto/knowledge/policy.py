"""Centralized policy for automatic knowledge growth."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_DOMAINS = ("browser", "desktop", "marketplaces", "platform", "general")
DEFAULT_PATTERN_STAGES = ("emerging", "reusable")
DEFAULT_CAPABILITY_STAGES = ("observed", "candidate")
DEFAULT_PROPOSAL_KINDS = ("skill", "platform")
DEFAULT_AI_CANDIDATE_KINDS = ("pattern", "lesson", "capability")
DEFAULT_AI_ASSIST_MODES = ("off", "strict_candidate")


@dataclass(frozen=True)
class KnowledgePolicy:
    """Repository policy for knowledge closeout and AI-assisted candidates."""

    domains: tuple[str, ...] = DEFAULT_DOMAINS
    pattern_stages: tuple[str, ...] = DEFAULT_PATTERN_STAGES
    capability_stages: tuple[str, ...] = DEFAULT_CAPABILITY_STAGES
    proposal_kinds: tuple[str, ...] = DEFAULT_PROPOSAL_KINDS
    ai_candidate_kinds: tuple[str, ...] = DEFAULT_AI_CANDIDATE_KINDS
    ai_assist_modes: tuple[str, ...] = DEFAULT_AI_ASSIST_MODES
    controlled_script_roots: tuple[str, ...] = ("workflows",)
    controlled_entrypoints: tuple[str, ...] = (
        "service.run_workflow",
        "service.schedule_task",
        "agent_runtime.process",
        "cli.run",
        "service.manual_closeout",
    )
    auto_write_roots: tuple[str, ...] = (
        "knowledge/tasks",
        "knowledge/patterns",
        "knowledge/lessons",
        "knowledge/capabilities",
        "knowledge/proposals",
        "knowledge/index",
        "runtime/knowledge_runs",
    )
    forbidden_write_roots: tuple[str, ...] = (
        "skills",
        "platform/src",
        "platform/tests",
    )
    review_candidate_root: str = "knowledge/review/ai_candidates"
    ai_assist_mode: str = "off"
    ai_candidate_limit: int = 3
    ai_candidate_evidence_limit: int = 5
    ai_trigger_min_duration_seconds: float = 90.0
    ai_trigger_error_states: tuple[str, ...] = ("ERROR", "TIMEOUT", "FAILED")
    enable_automatic_derivations: bool = True
    allow_direct_promotion: bool = False
    protect_human_authored_sections: bool = True
    required_candidate_confidence: str = "medium"
    managed_front_matter_marker: str = "automatic_closeout"
    candidate_status: str = "pending_review"
    evidence_pack_max_items: int = 8
    allowed_candidate_domains: tuple[str, ...] = field(default_factory=tuple)

    def normalize_domain(self, domain: str) -> str:
        return domain if domain in self.domains else "general"

    def normalize_pattern_stage(self, stage: str) -> str:
        return stage if stage in self.pattern_stages else self.pattern_stages[0]

    def normalize_capability_stage(self, stage: str) -> str:
        return stage if stage in self.capability_stages else self.capability_stages[0]

    def normalize_proposal_kind(self, proposal_kind: str) -> str:
        return proposal_kind if proposal_kind in self.proposal_kinds else self.proposal_kinds[0]

    def normalize_ai_mode(self, mode: str) -> str:
        return mode if mode in self.ai_assist_modes else "off"

    def is_controlled_task(self, repo_root: Path, script_path: Path) -> bool:
        """Return True when a script is inside a controlled repository root."""

        try:
            relative = script_path.resolve().relative_to(repo_root)
        except ValueError:
            return False
        return relative.parts[:1] in {(root,) for root in self.controlled_script_roots}

    def proposal_bucket(self, proposal_kind: str) -> str:
        normalized = self.normalize_proposal_kind(proposal_kind)
        return "skill_candidates" if normalized == "skill" else "platform_candidates"

    def candidate_bucket(self, kind: str) -> str:
        if kind == "pattern":
            return "patterns"
        if kind == "lesson":
            return "lessons"
        return "capabilities"

    def should_trigger_ai_assist(self, *, final_state: str, duration_seconds: float, error_text: str) -> bool:
        """Apply a conservative trigger gate for AI-assisted summarization."""

        if self.normalize_ai_mode(self.ai_assist_mode) != "strict_candidate":
            return False
        if duration_seconds >= self.ai_trigger_min_duration_seconds:
            return True
        if final_state.upper() in self.ai_trigger_error_states:
            return True
        lowered = error_text.lower()
        return any(token in lowered for token in ("timeout", "not found", "manual_handoff", "verification challenge"))


DEFAULT_KNOWLEDGE_POLICY = KnowledgePolicy()

