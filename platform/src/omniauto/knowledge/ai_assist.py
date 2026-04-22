"""Strictly bounded AI-assisted candidate generation for knowledge closeout."""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Protocol

from .policy import KnowledgePolicy
from .schemas import AIAssistResult
from .validator import AICandidateValidator


class AICandidateProvider(Protocol):
    """Callable provider that returns candidate dictionaries from an evidence pack."""

    def __call__(self, evidence_pack: Dict[str, Any]) -> Iterable[Mapping[str, Any]]:
        ...


class StrictCandidateAIAssist:
    """Generate review-only knowledge candidates under strong policy guards."""

    def __init__(
        self,
        *,
        policy: KnowledgePolicy,
        provider: Optional[AICandidateProvider] = None,
    ) -> None:
        self.policy = policy
        self.provider = provider
        self.validator = AICandidateValidator(policy)

    def maybe_generate(
        self,
        *,
        task_run: Any,
        result: Dict[str, Any],
        task_record: Dict[str, Any],
        script_rel: str,
        explicit_observation_count: int = 0,
    ) -> AIAssistResult:
        mode = self.policy.normalize_ai_mode(self.policy.ai_assist_mode)
        if mode == "off":
            return AIAssistResult(enabled=False, applied=False, reason="ai_assist_disabled")

        error_text = " ".join(
            [
                str(result.get("error", "") or ""),
                str(result.get("validation_report", "") or ""),
            ]
        )
        duration_seconds = float(result.get("duration_seconds", 0.0) or 0.0)
        final_state = str(result.get("final_state", "") or "")
        if (
            mode == "auto_strict_candidate"
            and self.policy.ai_auto_only_without_explicit_observations
            and explicit_observation_count > 0
        ):
            return AIAssistResult(enabled=True, applied=False, reason="explicit_observations_present")
        if not self.policy.should_trigger_ai_assist(
            final_state=final_state,
            duration_seconds=duration_seconds,
            error_text=error_text,
            category=str(getattr(task_run, "category", "") or ""),
        ):
            return AIAssistResult(enabled=True, applied=False, reason="trigger_threshold_not_met")
        if self.provider is None:
            return AIAssistResult(enabled=True, applied=False, reason="ai_provider_unavailable")

        evidence_pack = self._build_evidence_pack(
            task_run=task_run,
            result=result,
            task_record=task_record,
            script_rel=script_rel,
        )
        raw_candidates = list(self.provider(evidence_pack))
        candidates, errors = self.validator.validate(
            raw_candidates,
            allowed_evidence=set(evidence_pack["allowed_evidence"]),
        )
        if not candidates:
            return AIAssistResult(
                enabled=True,
                applied=False,
                reason="no_valid_candidates",
                errors=errors,
                evidence_pack=evidence_pack,
            )
        return AIAssistResult(
            enabled=True,
            applied=True,
            reason="strict_candidates_generated",
            candidates=candidates,
            errors=errors,
            evidence_pack=evidence_pack,
        )

    def _build_evidence_pack(
        self,
        *,
        task_run: Any,
        result: Dict[str, Any],
        task_record: Dict[str, Any],
        script_rel: str,
    ) -> Dict[str, Any]:
        allowed_evidence = [script_rel, task_record.get("record", ""), task_record.get("run_record", "")]
        allowed_evidence = [item for item in allowed_evidence if item][: self.policy.evidence_pack_max_items]
        return {
            "run_id": task_run.run_id,
            "task_id": task_run.task_id,
            "entrypoint": task_run.entrypoint,
            "domain": task_run.domain,
            "category": task_run.category,
            "script": script_rel,
            "final_state": result.get("final_state", ""),
            "duration_seconds": result.get("duration_seconds", 0.0),
            "error": result.get("error", ""),
            "task_record": task_record.get("record", ""),
            "allowed_evidence": allowed_evidence,
        }
