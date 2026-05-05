"""Evidence packaging for guarded LLM reply synthesis.

This module is intentionally additive. It reuses the existing structured
knowledge and RAG resolver output, then packages it for an LLM that can write a
natural WeChat reply. The package is audit-friendly so operators can verify
that RAG and formal knowledge actually participated.
"""

from __future__ import annotations

import re
from typing import Any

from apps.wechat_ai_customer_service.platform_understanding_rules import intent_group
from admin_backend.services.raw_message_store import RawMessageStore
from knowledge_loader import build_evidence_pack
from knowledge_runtime import KnowledgeRuntime


DEFAULT_MAX_HISTORY_MESSAGES = 40
DEFAULT_HISTORY_CHAR_BUDGET = 12000
DEFAULT_MAX_RAG_HITS = 5
DEFAULT_MAX_TEXT_CHARS = 900


def build_reply_evidence_pack(
    *,
    config: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    decision: Any,
    reply_text: str,
    intent_assist: dict[str, Any],
    rag_reply: dict[str, Any],
    llm_reply: dict[str, Any],
    product_knowledge: dict[str, Any],
    data_capture: dict[str, Any],
    raw_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("llm_reply_synthesis", {}) or {}
    context = dict(target_state.get("conversation_context", {}) or {})
    try:
        knowledge_pack = build_evidence_pack(combined, context=context)
        knowledge_error = ""
    except Exception as exc:
        knowledge_pack = {}
        knowledge_error = repr(exc)

    compact_knowledge = compact_knowledge_pack(
        combined,
        knowledge_pack,
        max_rag_hits=int(settings.get("max_rag_hits", DEFAULT_MAX_RAG_HITS) or DEFAULT_MAX_RAG_HITS),
        max_rag_text_chars=int(settings.get("max_rag_text_chars", DEFAULT_MAX_TEXT_CHARS) or DEFAULT_MAX_TEXT_CHARS),
        max_catalog_candidates=int(settings.get("max_catalog_candidates", 8) or 8),
    )
    relax_soft_synthesis_safety(compact_knowledge)
    history = recent_history(
        raw_capture=raw_capture,
        batch=batch,
        max_messages=int(settings.get("max_history_messages", DEFAULT_MAX_HISTORY_MESSAGES) or DEFAULT_MAX_HISTORY_MESSAGES),
        char_budget=int(settings.get("history_char_budget", DEFAULT_HISTORY_CHAR_BUDGET) or DEFAULT_HISTORY_CHAR_BUDGET),
    )

    evidence_ids = collect_evidence_ids(compact_knowledge)
    return {
        "schema_version": 1,
        "target": target_name,
        "current_message": truncate_text(combined, 2000),
        "current_batch": [compact_message(item) for item in batch],
        "conversation": {
            "context": context,
            "history": history,
            "history_count": len(history),
            "raw_conversation_id": raw_conversation_id(raw_capture),
        },
        "existing_reply": {
            "decision": compact_decision(decision),
            "reply_text": truncate_text(reply_text, 1000),
            "rag_reply": compact_mapping(rag_reply, max_text_chars=500),
            "llm_reply": compact_mapping(llm_reply, max_text_chars=500),
        },
        "product_knowledge": compact_mapping(product_knowledge, max_text_chars=900),
        "data_capture": compact_mapping(data_capture, max_text_chars=500),
        "intent_assist": compact_mapping(intent_assist, max_text_chars=900),
        "knowledge": compact_knowledge,
        "knowledge_error": knowledge_error,
        "evidence_ids": evidence_ids,
        "safety": compact_knowledge.get("safety", {}),
        "intent_tags": compact_knowledge.get("intent_tags", []),
        "rag": compact_knowledge.get("rag_evidence", {}),
        "audit_summary": {
            "structured_evidence_count": structured_evidence_count(compact_knowledge),
            "rag_hit_count": len((compact_knowledge.get("rag_evidence", {}) or {}).get("hits", []) or []),
            "rag_chunk_ids": [
                str(item.get("chunk_id") or "")
                for item in (compact_knowledge.get("rag_evidence", {}) or {}).get("hits", []) or []
                if item.get("chunk_id")
            ],
            "evidence_ids": evidence_ids,
        },
    }


def recent_history(
    *,
    raw_capture: dict[str, Any],
    batch: list[dict[str, Any]],
    max_messages: int,
    char_budget: int,
) -> list[dict[str, Any]]:
    conversation_id = raw_conversation_id(raw_capture)
    messages: list[dict[str, Any]] = []
    if conversation_id:
        try:
            messages = RawMessageStore().list_messages(conversation_id=conversation_id, limit=max_messages)
        except Exception:
            messages = []
    if not messages:
        messages = list(batch)
    compacted = [compact_message(item) for item in reversed(messages[:max_messages])]
    return trim_history(compacted, char_budget=max(500, char_budget))


def raw_conversation_id(raw_capture: dict[str, Any]) -> str:
    conversation = raw_capture.get("conversation", {}) or {}
    return str(conversation.get("conversation_id") or raw_capture.get("conversation_id") or "")


def compact_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(message.get("id") or message.get("message_id") or message.get("raw_message_id") or ""),
        "sender": str(message.get("sender") or ""),
        "time": str(message.get("time") or message.get("message_time") or message.get("observed_at") or ""),
        "content": truncate_text(str(message.get("content") or ""), 600),
    }


def trim_history(history: list[dict[str, Any]], *, char_budget: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    used = 0
    for item in reversed(history):
        content = str(item.get("content") or "")
        cost = len(content)
        if result and used + cost > char_budget:
            break
        result.append(item)
        used += cost
    return list(reversed(result))


def compact_knowledge_pack(
    text: str,
    pack: dict[str, Any],
    *,
    max_rag_hits: int,
    max_rag_text_chars: int,
    max_catalog_candidates: int,
) -> dict[str, Any]:
    evidence = pack.get("evidence", {}) or {}
    rag_evidence = pack.get("rag_evidence", {}) or {}
    catalog_candidates = catalog_product_candidates(text, limit=max_catalog_candidates)
    return {
        "intent_tags": list(pack.get("intent_tags", []) or []),
        "selected_items": [
            compact_mapping(item, max_text_chars=400)
            for item in pack.get("selected_items", []) or []
            if isinstance(item, dict)
        ],
        "evidence": {
            "products": [compact_mapping(item, max_text_chars=700) for item in evidence.get("products", []) or []],
            "faq": [compact_mapping(item, max_text_chars=700) for item in evidence.get("faq", []) or []],
            "policies": compact_mapping(evidence.get("policies", {}) or {}, max_text_chars=700),
            "product_scoped": [
                compact_mapping(item, max_text_chars=700)
                for item in evidence.get("product_scoped", []) or []
            ],
            "catalog_candidates": catalog_candidates,
            "style_examples": [
                compact_mapping(item, max_text_chars=500)
                for item in evidence.get("style_examples", []) or []
            ],
        },
        "rag_evidence": compact_rag_evidence(rag_evidence, max_hits=max_rag_hits, max_text_chars=max_rag_text_chars),
        "safety": compact_mapping(pack.get("safety", {}) or {}, max_text_chars=700),
        "matched_categories": list(pack.get("matched_categories", []) or []),
    }


def compact_rag_evidence(rag_evidence: dict[str, Any], *, max_hits: int, max_text_chars: int = DEFAULT_MAX_TEXT_CHARS) -> dict[str, Any]:
    hits = []
    for item in rag_evidence.get("hits", []) or []:
        if not isinstance(item, dict):
            continue
        hits.append(
            {
                "chunk_id": item.get("chunk_id"),
                "source_id": item.get("source_id"),
                "score": item.get("score"),
                "category": item.get("category"),
                "source_type": item.get("source_type"),
                "product_id": item.get("product_id"),
                "retrieval_mode": item.get("retrieval_mode"),
                "risk_terms": item.get("risk_terms", []),
                "text": truncate_text(str(item.get("text") or ""), max(120, max_text_chars)),
            }
        )
        if len(hits) >= max(1, max_hits):
            break
    return {
        "enabled": rag_evidence.get("enabled", True),
        "ok": rag_evidence.get("ok"),
        "skipped": rag_evidence.get("skipped"),
        "reason": rag_evidence.get("reason"),
        "confidence": rag_evidence.get("confidence", 0.0),
        "rag_can_authorize": bool(rag_evidence.get("rag_can_authorize", False)),
        "structured_priority": rag_evidence.get("structured_priority", True),
        "hits": hits,
    }


def collect_evidence_ids(pack: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    evidence = pack.get("evidence", {}) or {}
    for item in evidence.get("products", []) or []:
        append_id(ids, "product", item.get("id"))
    for item in evidence.get("faq", []) or []:
        append_id(ids, "faq", item.get("intent") or item.get("id"))
    for key in (evidence.get("policies", {}) or {}).keys():
        append_id(ids, "policy", key)
    for item in evidence.get("product_scoped", []) or []:
        append_id(ids, "product_scoped", item.get("id"))
    for item in evidence.get("catalog_candidates", []) or []:
        append_id(ids, "catalog_product", item.get("id"))
    for item in (pack.get("rag_evidence", {}) or {}).get("hits", []) or []:
        append_id(ids, "rag", item.get("chunk_id") or item.get("source_id"))
    return ids


def append_id(items: list[str], prefix: str, value: Any) -> None:
    text = str(value or "").strip()
    if text:
        marker = f"{prefix}:{text}"
        if marker not in items:
            items.append(marker)


def structured_evidence_count(pack: dict[str, Any]) -> int:
    evidence = pack.get("evidence", {}) or {}
    return (
        len(evidence.get("products", []) or [])
        + len(evidence.get("faq", []) or [])
        + len(evidence.get("policies", {}) or {})
        + len(evidence.get("product_scoped", []) or [])
        + len(evidence.get("catalog_candidates", []) or [])
    )


def relax_soft_synthesis_safety(pack: dict[str, Any]) -> None:
    """Let the additive synthesis layer use catalog/RAG evidence for soft scenes.

    The base safety layer may mark a broad natural-language question as
    `no_relevant_business_evidence` before catalog candidates are attached. For
    soft selection questions this module can now provide formal catalog
    candidates plus RAG experience. We only relax that narrow no-evidence marker;
    authority, price, finance, after-sales, or policy reasons remain untouched.
    """
    intent_tags = {str(item) for item in pack.get("intent_tags", []) or [] if str(item)}
    hard_authority_tags = intent_group("rag_authority_block") - {"quote"}
    if intent_tags & hard_authority_tags:
        return
    safety = pack.get("safety", {}) or {}
    if not isinstance(safety, dict) or not safety.get("must_handoff"):
        return
    reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    if not reasons or not reasons <= {"no_relevant_business_evidence"}:
        return
    if structured_evidence_count(pack) <= 0 and not ((pack.get("rag_evidence", {}) or {}).get("hits")):
        return
    safety["must_handoff"] = False
    safety["allowed_auto_reply"] = True
    safety["reasons"] = []
    safety["llm_synthesis_soft_evidence_override"] = True


def catalog_product_candidates(text: str, *, limit: int) -> list[dict[str, Any]]:
    try:
        items = KnowledgeRuntime().list_items("products")
    except Exception:
        return []
    scored = []
    normalized = str(text or "").lower()
    for item in items:
        if not isinstance(item, dict):
            continue
        data = item.get("data", {}) or {}
        if str(item.get("status") or "active") not in {"active", "approved", "published"}:
            continue
        searchable = product_searchable_text(data)
        score = 0
        for token in tokenize_for_catalog(normalized):
            if token and token in searchable:
                score += 2 if len(token) >= 2 else 1
        if score <= 0:
            score = fallback_catalog_score(data, normalized)
        scored.append((score, catalog_product_payload(item)))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [payload for score, payload in scored[: max(0, limit)] if score > 0]


def tokenize_for_catalog(text: str) -> list[str]:
    tokens = []
    for run in re.findall(r"[a-z0-9][a-z0-9_.-]{1,}|[\u4e00-\u9fff]{2,}", text, flags=re.IGNORECASE):
        normalized = run.lower()
        if len(normalized) <= 18:
            tokens.append(normalized)
        if re.search(r"[\u4e00-\u9fff]", normalized):
            for size in (2, 3, 4, 5, 6):
                if len(normalized) >= size:
                    tokens.extend(normalized[index : index + size] for index in range(0, len(normalized) - size + 1))
    return sorted(set(token for token in tokens if token.strip()), key=lambda item: (-len(item), item))


def fallback_catalog_score(data: dict[str, Any], query_text: str = "") -> int:
    query_tokens = set(tokenize_for_catalog(query_text))
    if not query_tokens:
        return 0
    product_tokens = set(tokenize_for_catalog(product_searchable_text(data)))
    if query_tokens & product_tokens:
        return 1
    return 0


def product_searchable_text(data: dict[str, Any]) -> str:
    parts = [
        str(data.get("name") or ""),
        str(data.get("sku") or ""),
        str(data.get("category") or ""),
        str(data.get("specs") or ""),
        " ".join(str(alias) for alias in data.get("aliases", []) or []),
        " ".join(str(rule) for rule in data.get("risk_rules", []) or []),
        " ".join(str(value) for value in (data.get("reply_templates", {}) or {}).values()),
        " ".join(str(value) for value in flatten_text_values(data.get("additional_details"))),
    ]
    return " ".join(part for part in parts if part).lower()


def flatten_text_values(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(flatten_text_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(flatten_text_values(item))
        return values
    return [str(value)]


def catalog_product_payload(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data", {}) or {}
    return {
        "id": item.get("id"),
        "name": data.get("name"),
        "sku": data.get("sku"),
        "category": data.get("category"),
        "aliases": list(data.get("aliases", []) or [])[:10],
        "specs": truncate_text(str(data.get("specs") or ""), 260),
        "price": data.get("price"),
        "unit": data.get("unit"),
        "stock": data.get("inventory"),
        "shipping": truncate_text(str(data.get("shipping_policy") or ""), 220),
        "warranty": truncate_text(str(data.get("warranty_policy") or ""), 220),
        "reply_templates": compact_mapping(data.get("reply_templates", {}) or {}, max_text_chars=260),
        "risk_rules": list(data.get("risk_rules", []) or [])[:8],
    }


def compact_decision(decision: Any) -> dict[str, Any]:
    return {
        "reply_text": truncate_text(str(getattr(decision, "reply_text", "") or ""), 500),
        "rule_name": str(getattr(decision, "rule_name", "") or ""),
        "matched": bool(getattr(decision, "matched", False)),
        "need_handoff": bool(getattr(decision, "need_handoff", False)),
        "reason": str(getattr(decision, "reason", "") or ""),
    }


def compact_mapping(value: Any, *, max_text_chars: int = DEFAULT_MAX_TEXT_CHARS) -> Any:
    if isinstance(value, dict):
        return {
            str(key): compact_mapping(item, max_text_chars=max_text_chars)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, list):
        return [compact_mapping(item, max_text_chars=max_text_chars) for item in value[:20]]
    if isinstance(value, str):
        return truncate_text(value, max_text_chars)
    return value


def truncate_text(text: str, max_chars: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 1)].rstrip() + "..."
