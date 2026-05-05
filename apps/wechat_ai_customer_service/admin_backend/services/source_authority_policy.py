"""Source-authority policy for AI-assisted knowledge candidates.

Observed conversations are useful evidence for experience and reply-style
learning, but they are not authoritative product master data.
"""

from __future__ import annotations

import json
import re
from typing import Any

from apps.wechat_ai_customer_service.platform_safety_rules import guard_term_set, load_platform_safety_rules


OBSERVED_WECHAT_SOURCE_TYPES = {
    "raw_wechat_private",
    "raw_wechat_group",
    "raw_wechat_file_transfer",
    "wechat_raw_message",
}
PRODUCT_MASTER_CATEGORIES = {"products", "erp_exports"}
PRODUCT_SCOPED_CATEGORIES = {"product_faq", "product_rules", "product_explanations"}


def visible_rule_patterns(group: str) -> list[str]:
    rules = load_platform_safety_rules().get("item", {})
    return sorted(guard_term_set(rules, group))


def matches_visible_patterns(text: str, group: str) -> bool:
    return any(re.search(pattern, text) for pattern in visible_rule_patterns(group))


def candidate_target_category(candidate: dict[str, Any]) -> str:
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    patch = proposal.get("formal_patch") if isinstance(proposal.get("formal_patch"), dict) else {}
    return str(patch.get("target_category") or proposal.get("target_category") or "").strip()


def candidate_item_data(candidate: dict[str, Any]) -> dict[str, Any]:
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    patch = proposal.get("formal_patch") if isinstance(proposal.get("formal_patch"), dict) else {}
    item = patch.get("item") if isinstance(patch.get("item"), dict) else {}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return data


def candidate_source_types(candidate: dict[str, Any]) -> set[str]:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    patch = proposal.get("formal_patch") if isinstance(proposal.get("formal_patch"), dict) else {}
    item = patch.get("item") if isinstance(patch.get("item"), dict) else {}
    item_source = item.get("source") if isinstance(item.get("source"), dict) else {}
    values = {
        str(source.get("type") or ""),
        str(source.get("original_type") or ""),
        str(source.get("original_channel") or ""),
        str(item_source.get("type") or ""),
        str(item_source.get("original_type") or ""),
        str(item_source.get("candidate_source_type") or ""),
    }
    for item in review.get("source_chain", []) if isinstance(review.get("source_chain"), list) else []:
        values.add(str(item or ""))
    rag_hit = source.get("rag_hit") if isinstance(source.get("rag_hit"), dict) else {}
    values.add(str(rag_hit.get("source_type") or ""))
    for hit in source.get("rag_hits", []) if isinstance(source.get("rag_hits"), list) else []:
        if isinstance(hit, dict):
            values.add(str(hit.get("source_type") or ""))
    return {value for value in values if value}


def is_observed_wechat_source(source_types: set[str]) -> bool:
    return bool(source_types & OBSERVED_WECHAT_SOURCE_TYPES) or any(value.startswith("raw_wechat_") for value in source_types)


def candidate_contains_model_reply(candidate: dict[str, Any]) -> bool:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    if bool(source.get("contains_model_reply") or review.get("source_contains_model_reply")):
        return True
    text = json.dumps(
        {
            "evidence_excerpt": source.get("evidence_excerpt"),
            "summary": (candidate.get("proposal") or {}).get("summary") if isinstance(candidate.get("proposal"), dict) else "",
            "suggested_fields": (candidate.get("proposal") or {}).get("suggested_fields")
            if isinstance(candidate.get("proposal"), dict)
            else {},
        },
        ensure_ascii=False,
        default=str,
    )
    return any(marker in text for marker in visible_rule_patterns("model_reply_markers"))


def candidate_review_text(candidate: dict[str, Any]) -> str:
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    review = candidate.get("review") if isinstance(candidate.get("review"), dict) else {}
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    data = candidate_item_data(candidate)
    return json.dumps(
        {
            "source": source,
            "review": {
                "rag_evidence": review.get("rag_evidence"),
                "source_authority": review.get("source_authority"),
            },
            "proposal_summary": proposal.get("summary"),
            "data": data,
        },
        ensure_ascii=False,
        default=str,
    )


def observed_chat_candidate_is_too_specific(candidate: dict[str, Any]) -> bool:
    data = candidate_item_data(candidate)
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    customer_message = str(data.get("customer_message") or "")
    service_reply = str(data.get("service_reply") or data.get("answer") or "")
    primary_text = "\n".join(
        str(value or "")
        for value in (
            customer_message,
            service_reply,
            data.get("title"),
            data.get("summary"),
            proposal.get("summary"),
        )
    )
    if matches_visible_patterns(primary_text, "personalized_reply_patterns"):
        return True
    if matches_visible_patterns(service_reply, "situational_handoff_patterns"):
        return True
    if matches_visible_patterns(customer_message + "\n" + service_reply, "finance_boundary_patterns"):
        return True
    return False


def product_scoped_has_product(candidate: dict[str, Any]) -> bool:
    data = candidate_item_data(candidate)
    return bool(str(data.get("product_id") or "").strip())


def evaluate_candidate_source_authority(candidate: dict[str, Any]) -> dict[str, Any]:
    category = candidate_target_category(candidate)
    source_types = candidate_source_types(candidate)
    observed_wechat = is_observed_wechat_source(source_types)
    contains_model_reply = candidate_contains_model_reply(candidate)

    if observed_wechat and category in PRODUCT_MASTER_CATEGORIES:
        return denied(
            category,
            source_types,
            "observed_wechat_cannot_write_product_master",
            "聊天记录只能作为AI经验或线索，不能新增或修改商品资料、价格、库存、订单等权威数据。",
        )
    if observed_wechat and contains_model_reply and category != "chats":
        return denied(
            category,
            source_types,
            "model_reply_cannot_be_factual_source",
            "这条内容包含AI自动回复，只能用于话术经验参考，不能作为商品、政策或商品专属事实的来源。",
        )
    if observed_wechat and category in PRODUCT_SCOPED_CATEGORIES and not product_scoped_has_product(candidate):
        return denied(
            category,
            source_types,
            "product_scoped_wechat_candidate_requires_existing_product",
            "聊天中整理出的商品专属问答、规则或解释必须先关联到已有商品；没有关联商品时只能保留为AI经验。",
        )
    if observed_wechat and category == "chats" and observed_chat_candidate_is_too_specific(candidate):
        return denied(
            category,
            source_types,
            "observed_wechat_chat_candidate_not_generalized",
            "这条聊天话术带有具体客户、人称、转人工场景或金融边界，不能直接写入正式话术；请保留在RAG经验层，或人工改写成通用边界规则后再提交。",
        )

    return {
        "allowed": True,
        "category": category,
        "source_types": sorted(source_types),
        "observed_wechat": observed_wechat,
        "contains_model_reply": contains_model_reply,
        "policy_version": "source_authority_v1",
    }


def denied(category: str, source_types: set[str], reason: str, message: str) -> dict[str, Any]:
    return {
        "allowed": False,
        "category": category,
        "source_types": sorted(source_types),
        "reason": reason,
        "message": message,
        "observed_wechat": is_observed_wechat_source(source_types),
        "policy_version": "source_authority_v1",
    }


def mark_candidate_source_policy(candidate: dict[str, Any], decision: dict[str, Any]) -> None:
    candidate.setdefault("review", {})["source_authority"] = decision
    if not decision.get("allowed"):
        candidate.setdefault("intake", {}).setdefault("warnings", []).append(str(decision.get("message") or decision.get("reason") or ""))


def experience_source_types(item: dict[str, Any]) -> set[str]:
    hit = item.get("rag_hit") if isinstance(item.get("rag_hit"), dict) else {}
    values = {
        str(item.get("source") or ""),
        str(item.get("source_type") or ""),
        str(item.get("original_type") or ""),
        str(item.get("original_source_type") or ""),
        str(hit.get("source_type") or ""),
    }
    original = item.get("original_source") if isinstance(item.get("original_source"), dict) else {}
    values.update(
        {
            str(original.get("type") or ""),
            str(original.get("source_type") or ""),
            str(original.get("conversation_type") or ""),
        }
    )
    for key in ("source_chain", "detected_tags"):
        if isinstance(item.get(key), list):
            values.update(str(value or "") for value in item.get(key) or [])
    return {value for value in values if value}


def experience_contains_model_reply(item: dict[str, Any]) -> bool:
    text = json.dumps(
        {
            "summary": item.get("summary"),
            "question": item.get("question"),
            "reply_text": item.get("reply_text"),
            "evidence_excerpt": item.get("evidence_excerpt"),
            "rag_hit": item.get("rag_hit"),
        },
        ensure_ascii=False,
        default=str,
    )
    return any(marker in text for marker in visible_rule_patterns("model_reply_markers"))


def experience_review_text(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "summary": item.get("summary"),
            "question": item.get("question"),
            "reply_text": item.get("reply_text"),
            "evidence_excerpt": item.get("evidence_excerpt"),
            "source_dialogue": item.get("source_dialogue"),
            "rag_hit": item.get("rag_hit"),
            "ai_interpretation": item.get("ai_interpretation"),
        },
        ensure_ascii=False,
        default=str,
    )


def observed_chat_experience_is_too_specific(item: dict[str, Any]) -> bool:
    text = experience_review_text(item)
    if matches_visible_patterns(text, "personalized_reply_patterns"):
        return True
    if matches_visible_patterns(text, "situational_handoff_patterns"):
        return True
    if matches_visible_patterns(text, "finance_boundary_patterns"):
        return True
    return False


def evaluate_experience_source_authority(item: dict[str, Any], category: str) -> dict[str, Any]:
    source_types = experience_source_types(item)
    observed_wechat = is_observed_wechat_source(source_types)
    contains_model_reply = experience_contains_model_reply(item)
    if observed_wechat and category in PRODUCT_MASTER_CATEGORIES:
        return denied(
            category,
            source_types,
            "observed_wechat_rag_cannot_promote_to_product_master",
            "这条AI经验来自微信聊天，只能作为经验或话术线索，不能升级为商品资料、价格、库存或订单数据。",
        )
    if observed_wechat and contains_model_reply and category != "chats":
        return denied(
            category,
            source_types,
            "model_reply_rag_cannot_promote_to_factual_knowledge",
            "这条AI经验包含AI自动回复，不能作为事实知识升级；如有价值，请保留在经验层或改成话术候选。",
        )
    if observed_wechat and category == "chats" and observed_chat_experience_is_too_specific(item):
        return denied(
            category,
            source_types,
            "observed_wechat_chat_experience_not_generalized",
            "这条AI经验带有具体客户、人称、转人工场景或金融边界，不能直接升级为正式话术候选；请保留在经验层，或人工改写成通用边界规则后再提交。",
        )
    return {
        "allowed": True,
        "category": category,
        "source_types": sorted(source_types),
        "observed_wechat": observed_wechat,
        "contains_model_reply": contains_model_reply,
        "policy_version": "source_authority_v1",
    }
