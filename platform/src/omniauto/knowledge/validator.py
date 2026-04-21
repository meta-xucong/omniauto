"""Validation helpers for AI-assisted knowledge candidates."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .policy import KnowledgePolicy
from .schemas import AICandidate


class AICandidateValidator:
    """Validate and normalize AI-produced candidate payloads."""

    def __init__(self, policy: KnowledgePolicy) -> None:
        self.policy = policy

    def validate(
        self,
        raw_candidates: Iterable[Mapping[str, Any]],
        *,
        allowed_evidence: set[str],
    ) -> tuple[list[AICandidate], list[str]]:
        candidates: list[AICandidate] = []
        errors: list[str] = []
        for index, item in enumerate(raw_candidates):
            if index >= self.policy.ai_candidate_limit:
                errors.append("candidate_limit_exceeded")
                break
            candidate, item_errors = self._validate_one(item, allowed_evidence=allowed_evidence)
            if item_errors:
                errors.extend(item_errors)
                continue
            if candidate is not None:
                candidates.append(candidate)
        return candidates, errors

    def _validate_one(
        self,
        item: Mapping[str, Any],
        *,
        allowed_evidence: set[str],
    ) -> tuple[AICandidate | None, list[str]]:
        errors: list[str] = []
        kind = str(item.get("kind", "")).strip().lower()
        if kind not in self.policy.ai_candidate_kinds:
            errors.append(f"invalid_kind:{kind or 'missing'}")
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not title:
            errors.append("missing_title")
        if not summary:
            errors.append("missing_summary")
        evidence_refs = [str(ref).strip() for ref in item.get("evidence_refs", []) if str(ref).strip()]
        if not evidence_refs:
            errors.append("missing_evidence")
        if len(evidence_refs) > self.policy.ai_candidate_evidence_limit:
            errors.append("too_many_evidence_refs")
        invalid_refs = [ref for ref in evidence_refs if ref not in allowed_evidence]
        if invalid_refs:
            errors.append(f"unknown_evidence:{','.join(sorted(invalid_refs))}")
        confidence = str(item.get("confidence", "medium")).strip().lower() or "medium"
        if confidence not in {"low", "medium", "high"}:
            errors.append(f"invalid_confidence:{confidence}")
        if errors:
            return None, errors
        return (
            AICandidate(
                kind=kind,
                title=title,
                summary=summary,
                domain=self.policy.normalize_domain(str(item.get("domain", "general")).strip() or "general"),
                slug=str(item.get("slug", "")).strip(),
                stage=str(item.get("stage", "")).strip(),
                maturity=str(item.get("maturity", "medium")).strip() or "medium",
                confidence=confidence,
                tags=[str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()],
                evidence_refs=evidence_refs,
                related=[str(rel).strip() for rel in item.get("related", []) if str(rel).strip()],
                boundaries=str(item.get("boundaries", "")).strip(),
                uncertainty_note=str(item.get("uncertainty_note", "")).strip(),
            ),
            [],
        )

