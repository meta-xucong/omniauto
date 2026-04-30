"""Controlled RAG answer layer for customer-service replies.

RAG is allowed to make a reply warmer and more context-aware, but it must not
authorize commitments. Structured product/policy knowledge keeps priority for
prices, stock, shipping, invoices, payment, after-sales, and handoff topics.
"""

from __future__ import annotations

import re
from typing import Any


DEFAULT_MAX_REPLY_CHARS = 220
DEFAULT_MAX_SNIPPET_CHARS = 130
DEFAULT_MIN_HIT_SCORE = 0.12

AUTHORITY_TAGS = {
    "quote",
    "discount",
    "stock",
    "shipping",
    "invoice",
    "payment",
    "after_sales",
    "handoff",
    "customer_data",
}
SOFT_REFERENCE_TAGS = {"scene_product", "spec", "catalog", "small_talk", "greeting"}
SOFT_ACTIONS = {
    "answer_from_evidence",
    "ask_for_contact_fields",
    "review_or_default_reply",
    "reply_small_talk",
    "reply_greeting",
}
RISK_TERMS = {
    "最低价",
    "账期",
    "月结",
    "赔偿",
    "退款",
    "退货",
    "合同",
    "盖章",
    "安装费",
    "上门安装",
    "先发货",
    "赊账",
    "白条",
    "虚开发票",
    "假发票",
    "包赔",
    "保证到",
    "保证效果",
}


def maybe_build_rag_reply(
    *,
    config: dict[str, Any],
    text: str,
    decision: Any,
    reply_text: str,
    intent_assist: dict[str, Any],
    product_knowledge: dict[str, Any],
    data_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("rag_response", {}) or {}
    payload: dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "applied": False,
    }
    if not payload["enabled"]:
        payload["reason"] = "rag_response_disabled"
        return payload
    if data_capture.get("is_customer_data"):
        payload["reason"] = "customer_data_decision_is_deterministic"
        return payload
    if safety_requires_handoff(intent_assist):
        payload["reason"] = "evidence_safety_requires_handoff"
        return payload
    if product_knowledge.get("needs_handoff") or product_knowledge.get("auto_reply_allowed") is False:
        payload["reason"] = "product_knowledge_requires_handoff"
        return payload

    evidence = intent_assist.get("evidence", {}) or {}
    intent_tags = {str(item) for item in evidence.get("intent_tags", []) or [] if str(item)}
    safety = evidence.get("safety", {}) or {}
    effective_intent_tags = set(intent_tags)
    if isinstance(safety, dict) and safety.get("rag_soft_installation_reference_allowed"):
        effective_intent_tags.discard("handoff")
    candidate_intent = str(intent_assist.get("intent") or "")
    candidate_action = str(intent_assist.get("recommended_action") or "")
    if not rag_reply_allowed_for_decision(
        settings=settings,
        decision=decision,
        product_knowledge=product_knowledge,
        intent_tags=effective_intent_tags,
        candidate_intent=candidate_intent,
        candidate_action=candidate_action,
    ):
        payload["reason"] = "rag_not_allowed_for_decision"
        payload["intent_tags"] = sorted(intent_tags)
        return payload

    hits = eligible_rag_hits(evidence, settings)
    payload["hit_count"] = len(hits)
    if not hits:
        risky_hit = first_risky_rag_hit(evidence, settings)
        if risky_hit:
            payload["reason"] = "rag_hit_or_query_has_risk_terms"
            payload["hit"] = compact_hit(risky_hit, settings)
            return payload
        payload["reason"] = "no_eligible_rag_hits"
        return payload

    top_hit = hits[0]
    if has_risk_terms(str(text or "")) or hit_has_risk(top_hit):
        payload["reason"] = "rag_hit_or_query_has_risk_terms"
        payload["hit"] = compact_hit(top_hit, settings)
        return payload

    reply = build_reply_from_hit(top_hit, intent_tags=effective_intent_tags, settings=settings)
    if not reply:
        payload["reason"] = "empty_rag_reply"
        return payload

    payload.update(
        {
            "applied": True,
            "rule_name": "rag_context_reply",
            "reason": "safe_rag_context_reply",
            "needs_handoff": False,
            "raw_reply_text": reply,
            "reply_text": format_with_prefix(reply, str(config.get("reply", {}).get("prefix") or "")),
            "intent_tags": sorted(intent_tags),
            "hit": compact_hit(top_hit, settings),
        }
    )
    return payload


def rag_reply_allowed_for_decision(
    *,
    settings: dict[str, Any],
    decision: Any,
    product_knowledge: dict[str, Any],
    intent_tags: set[str],
    candidate_intent: str,
    candidate_action: str,
) -> bool:
    rule_name = str(getattr(decision, "rule_name", "") or "")
    reason = str(getattr(decision, "reason", "") or "")
    matched = bool(getattr(decision, "matched", False))
    if rule_name in {"customer_data_capture", "customer_data_incomplete"}:
        return False
    if intent_tags & AUTHORITY_TAGS:
        return False
    if product_knowledge.get("matched"):
        return bool(settings.get("apply_to_matched_product", False))
    if candidate_intent == "small_talk" or candidate_action == "reply_small_talk" or "small_talk" in intent_tags:
        return bool(settings.get("apply_to_small_talk", True))
    if not matched or reason == "no_rule_matched":
        if not bool(settings.get("apply_to_unmatched", True)):
            return False
        return bool((intent_tags & SOFT_REFERENCE_TAGS) or candidate_action in SOFT_ACTIONS)
    return False


def eligible_rag_hits(evidence: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    hits = [item for item in evidence.get("rag_hits", []) or [] if isinstance(item, dict)]
    min_score = float(settings.get("min_hit_score", DEFAULT_MIN_HIT_SCORE) or DEFAULT_MIN_HIT_SCORE)
    filtered = []
    for hit in hits:
        try:
            score = float(hit.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score < min_score:
            continue
        if not hit_passes_scope_filters(hit, settings):
            continue
        if hit_has_risk(hit):
            continue
        filtered.append(hit)
    return filtered


def first_risky_rag_hit(evidence: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any] | None:
    hits = [item for item in evidence.get("rag_hits", []) or [] if isinstance(item, dict)]
    min_score = float(settings.get("min_hit_score", DEFAULT_MIN_HIT_SCORE) or DEFAULT_MIN_HIT_SCORE)
    for hit in hits:
        try:
            score = float(hit.get("score") or 0)
        except (TypeError, ValueError):
            score = 0.0
        if score >= min_score and hit_has_risk(hit):
            if not hit_passes_scope_filters(hit, settings):
                continue
            return hit
    return None


def hit_passes_scope_filters(hit: dict[str, Any], settings: dict[str, Any]) -> bool:
    allowed_categories = {str(item) for item in settings.get("allowed_categories", []) or [] if str(item)}
    allowed_source_types = {str(item) for item in settings.get("allowed_source_types", []) or [] if str(item)}
    if allowed_categories and str(hit.get("category") or "") not in allowed_categories:
        return False
    if allowed_source_types and str(hit.get("source_type") or "") not in allowed_source_types:
        return False
    return True


def build_reply_from_hit(hit: dict[str, Any], *, intent_tags: set[str], settings: dict[str, Any]) -> str:
    snippet = clean_snippet(str(hit.get("text") or ""), max_chars=int(settings.get("max_snippet_chars", DEFAULT_MAX_SNIPPET_CHARS)))
    if not snippet:
        return ""
    if intent_tags <= {"small_talk", "greeting"} or "small_talk" in intent_tags:
        reply = (
            f"可以的，您先慢慢看。我先按资料给您把相关点捋一下：{snippet}。"
            "这部分可以先作为参考；后面如果想看价格、规格或售后，直接发我，我再按正式规则帮您确认。"
        )
    else:
        reply = (
            f"我查到资料里有一条相关说明：{snippet}。"
            "这部分可以先作为参考；如果您要确认价格、库存、发货或售后承诺，我再按正式规则核对。"
        )
    return truncate_sentence(reply, int(settings.get("max_reply_chars", DEFAULT_MAX_REPLY_CHARS) or DEFAULT_MAX_REPLY_CHARS))


def safety_requires_handoff(intent_assist: dict[str, Any]) -> bool:
    evidence = intent_assist.get("evidence", {}) or {}
    safety = evidence.get("safety", {}) or {}
    return bool(isinstance(safety, dict) and safety.get("must_handoff"))


def hit_has_risk(hit: dict[str, Any]) -> bool:
    if hit.get("risk_terms"):
        return True
    return has_risk_terms(str(hit.get("text") or ""))


def has_risk_terms(text: str) -> bool:
    return any(term in text for term in RISK_TERMS)


def clean_snippet(text: str, *, max_chars: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    compacted = compacted.strip(" \t\r\n-:：;；,，。")
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max(1, max_chars - 1)].rstrip("，,。；; ") + "…"


def truncate_sentence(text: str, max_chars: int) -> str:
    compacted = re.sub(r"\s+", " ", text).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max(1, max_chars - 1)].rstrip("，,。；; ") + "…"


def compact_hit(hit: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": hit.get("chunk_id"),
        "source_id": hit.get("source_id"),
        "score": hit.get("score"),
        "category": hit.get("category"),
        "source_type": hit.get("source_type"),
        "product_id": hit.get("product_id"),
        "retrieval_mode": hit.get("retrieval_mode"),
        "scoring": hit.get("scoring", {}),
        "risk_terms": hit.get("risk_terms", []),
        "text": clean_snippet(
            str(hit.get("text") or ""),
            max_chars=int(settings.get("audit_snippet_chars", DEFAULT_MAX_SNIPPET_CHARS) or DEFAULT_MAX_SNIPPET_CHARS),
        ),
    }


def format_with_prefix(reply_text: str, prefix: str) -> str:
    if not prefix:
        return reply_text
    if reply_text.startswith(prefix):
        return reply_text
    return prefix + reply_text
