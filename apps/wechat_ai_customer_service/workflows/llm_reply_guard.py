"""Safety guard for LLM synthesized customer-service replies."""

from __future__ import annotations

import re
from typing import Any

from apps.wechat_ai_customer_service.platform_safety_rules import guard_term_set, load_platform_safety_rules


def guard_synthesized_reply(
    *,
    candidate: dict[str, Any],
    evidence_pack: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    platform_rules = load_platform_safety_rules(settings).get("item", {})
    normalized = normalize_candidate(candidate)
    if not normalized.get("ok"):
        return {"allowed": False, "action": "fallback", "reason": "candidate_invalid", "errors": normalized.get("errors", [])}

    candidate = normalized["candidate"]
    reply = str(candidate.get("reply") or "").strip()
    safety = evidence_pack.get("safety", {}) or {}
    if isinstance(safety, dict) and safety.get("must_handoff"):
        return handoff_decision("existing_safety_requires_handoff", candidate)

    if candidate.get("needs_handoff") or candidate.get("recommended_action") in {"handoff", "handoff_for_approval"}:
        return handoff_decision("llm_requested_handoff", candidate)

    if not candidate.get("can_answer", True):
        return handoff_decision("llm_cannot_answer", candidate)

    try:
        confidence = float(candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    min_confidence = float(settings.get("min_confidence", 0.62) or 0.62)
    if confidence < min_confidence:
        return {
            "allowed": False,
            "action": "fallback",
            "reason": "confidence_below_threshold",
            "confidence": confidence,
            "min_confidence": min_confidence,
            "candidate": candidate,
        }

    if not reply:
        return {"allowed": False, "action": "fallback", "reason": "empty_reply", "candidate": candidate}

    authority_tags = set(str(item) for item in evidence_pack.get("intent_tags", []) or []) & guard_term_set(platform_rules, "authority_tags")
    has_structured = has_structured_evidence(evidence_pack)
    rag_used = bool(candidate.get("rag_used"))
    structured_used = bool(candidate.get("structured_used"))
    require_structured = settings.get("require_structured_for_authority", True) is not False

    if authority_tags and require_structured and not has_structured:
        return handoff_decision(
            "authority_topic_without_structured_evidence",
            candidate,
            authority_tags=sorted(authority_tags),
        )

    if authority_tags and rag_used and not structured_used and require_structured:
        return handoff_decision(
            "rag_only_cannot_authorize_authority_topic",
            candidate,
            authority_tags=sorted(authority_tags),
        )

    if has_unsafe_commitment(reply, platform_rules) and not has_caution(reply, platform_rules):
        return handoff_decision("unsafe_commitment_without_caution", candidate, include_candidate_reply=False)

    if has_forbidden_private_payment_or_invoice_reply(reply, platform_rules):
        return handoff_decision("forbidden_payment_invoice_or_finance_boundary", candidate, include_candidate_reply=False)

    if has_direct_appointment_commitment(reply, platform_rules):
        return handoff_decision("appointment_or_reservation_commitment_requires_handoff", candidate, include_candidate_reply=False)

    if has_sales_followup_commitment(reply, platform_rules):
        return handoff_decision("sales_followup_requires_handoff", candidate)

    if settings.get("require_evidence", True) is not False and not candidate_evidence_declared(candidate):
        return {"allowed": False, "action": "fallback", "reason": "candidate_missing_used_evidence", "candidate": candidate}

    return {
        "allowed": True,
        "action": "send_reply",
        "reason": "guard_passed",
        "reply": reply,
        "candidate": candidate,
        "authority_tags": sorted(authority_tags),
    }


def handoff_decision(
    reason: str,
    candidate: dict[str, Any],
    *,
    authority_tags: list[str] | None = None,
    include_candidate_reply: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "allowed": True,
        "action": "handoff",
        "reason": reason,
        "candidate": candidate,
    }
    if authority_tags:
        payload["authority_tags"] = authority_tags
    reply = str(candidate.get("reply") or "").strip()
    if include_candidate_reply and handoff_reply_safe(reply):
        payload["reply"] = reply
    return payload


def handoff_reply_safe(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = str(reply or "").strip()
    if not clean:
        return False
    if len(clean) > 700:
        return False
    if has_formulaic_handoff(clean, platform_rules):
        return False
    if has_unsafe_commitment(clean, platform_rules) and not has_caution(clean, platform_rules):
        return False
    return has_caution(clean, platform_rules)


def normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(candidate, dict):
        return {"ok": False, "errors": ["candidate_not_object"]}
    reply = str(candidate.get("reply") or "").strip()
    action = str(candidate.get("recommended_action") or "send_reply").strip() or "send_reply"
    if action not in {"send_reply", "handoff", "handoff_for_approval", "fallback_existing"}:
        errors.append("invalid_recommended_action")
    if action == "send_reply" and not reply:
        errors.append("missing_reply")
    try:
        confidence = float(candidate.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
        errors.append("invalid_confidence")
    confidence = max(0.0, min(1.0, confidence))
    used_evidence = [str(item) for item in candidate.get("used_evidence", []) or [] if str(item)]
    normalized = {
        "can_answer": candidate.get("can_answer", True) is not False,
        "reply": reply,
        "confidence": confidence,
        "recommended_action": action,
        "needs_handoff": bool(candidate.get("needs_handoff", False)),
        "used_evidence": used_evidence,
        "rag_used": bool(candidate.get("rag_used", any(item.startswith("rag:") for item in used_evidence))),
        "structured_used": bool(
            candidate.get(
                "structured_used",
                any(item.startswith(("product:", "faq:", "policy:", "product_scoped:")) for item in used_evidence),
            )
        ),
        "uncertain_points": [str(item) for item in candidate.get("uncertain_points", []) or [] if str(item)],
        "risk_tags": [str(item) for item in candidate.get("risk_tags", []) or [] if str(item)],
        "reason": str(candidate.get("reason") or ""),
    }
    return {"ok": not errors, "candidate": normalized, "errors": errors}


def has_structured_evidence(evidence_pack: dict[str, Any]) -> bool:
    knowledge = evidence_pack.get("knowledge", {}) or {}
    evidence = knowledge.get("evidence", {}) or {}
    return bool(
        evidence.get("products")
        or evidence.get("faq")
        or evidence.get("policies")
        or evidence.get("product_scoped")
        or evidence.get("catalog_candidates")
    )


def candidate_evidence_declared(candidate: dict[str, Any]) -> bool:
    if candidate.get("used_evidence"):
        return True
    return bool(candidate.get("rag_used") or candidate.get("structured_used"))


def has_unsafe_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    normalized = re.sub(r"\s+", "", reply)
    return any(term in normalized for term in guard_term_set(platform_rules, "commitment_terms"))


def has_forbidden_private_payment_or_invoice_reply(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    risky_terms = guard_term_set(platform_rules, "forbidden_reply_terms")
    safe_markers = guard_term_set(platform_rules, "forbidden_safe_markers")
    for term in risky_terms:
        start = clean.find(term)
        while start >= 0:
            window = clean[max(0, start - 12) : start + len(term) + 18]
            if not any(marker in window for marker in safe_markers):
                return True
            start = clean.find(term, start + len(term))
    return False


def has_caution(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    return any(term in reply for term in guard_term_set(platform_rules, "caution_terms"))


def has_formulaic_handoff(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    return any(term in reply for term in guard_term_set(platform_rules, "formulaic_handoff_terms"))


def has_direct_appointment_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    risky_terms = guard_term_set(platform_rules, "appointment_commitment_terms")
    local_caution = guard_term_set(platform_rules, "appointment_caution_terms")
    for term in risky_terms:
        start = clean.find(term)
        while start >= 0:
            window = clean[max(0, start - 18) : start + len(term) + 18]
            if not any(marker in window for marker in local_caution):
                return True
            start = clean.find(term, start + len(term))
    return False


def has_sales_followup_commitment(reply: str, platform_rules: dict[str, Any] | None = None) -> bool:
    platform_rules = platform_rules or load_platform_safety_rules().get("item", {})
    clean = re.sub(r"\s+", "", str(reply or ""))
    actors = guard_term_set(platform_rules, "sales_followup_actors")
    actions = guard_term_set(platform_rules, "sales_followup_actions")
    for actor in actors:
        start = clean.find(actor)
        while start >= 0:
            window = clean[start : start + 36]
            if any(action in window for action in actions):
                return True
            start = clean.find(actor, start + len(actor))
    return False
