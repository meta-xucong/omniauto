"""Admin-facing wrapper for the local RAG auxiliary layer."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
if str(WORKFLOWS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOWS_ROOT))

from rag_layer import RagService  # noqa: E402
from rag_experience_store import RagExperienceStore, with_quality  # noqa: E402
from rag_operations import RagOperationsAnalyzer  # noqa: E402
from apps.wechat_ai_customer_service.workflows.knowledge_runtime import (  # noqa: E402
    KnowledgeRuntime,
    PRODUCT_SCOPED_SCHEMAS,
)
from .candidate_store import upsert_candidate_to_db  # noqa: E402


REVIEW_ROOT = APP_ROOT / "data" / "review_candidates"
PRODUCT_SCOPED_CATEGORIES = set(PRODUCT_SCOPED_SCHEMAS)


class RagAdminService:
    def __init__(self) -> None:
        self.rag = RagService()
        self.experiences = RagExperienceStore()
        self.operations = RagOperationsAnalyzer(rag_service=self.rag, experience_store=self.experiences)

    def status(self) -> dict[str, Any]:
        payload = self.rag.status()
        payload["experience_counts"] = self.experiences.counts()
        return payload

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rag.search(
            str(payload.get("query") or ""),
            product_id=str(payload.get("product_id") or ""),
            category=str(payload.get("category") or ""),
            source_type=str(payload.get("source_type") or ""),
            limit=int(payload.get("limit") or 6),
        )

    def rebuild(self) -> dict[str, Any]:
        return self.rag.rebuild_index()

    def sources(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        limit = max(1, min(int(payload.get("limit") or 80), 300))
        sources = self.rag.list_sources()
        chunks = [item for item in self.rag.iter_chunks() if str(item.get("source_type") or "") != "rag_experience"]
        chunk_counts = Counter(str(item.get("source_id") or "") for item in chunks)
        enriched_sources = []
        for source in sources:
            source_id = str(source.get("source_id") or "")
            enriched_sources.append({**source, "chunk_count": int(chunk_counts.get(source_id, 0))})
        return {
            "ok": True,
            "sources": enriched_sources,
            "chunks": chunks[:limit],
            "chunk_counts": dict(chunk_counts),
            "total_chunks": len(chunks),
        }

    def analytics(self) -> dict[str, Any]:
        return self.operations.report()

    def list_experiences(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        status = str(payload.get("status") or "active")
        limit = int(payload.get("limit") or 100)
        formal_items = collect_formal_items()
        items = []
        for item in self.experiences.list(status=status, limit=limit):
            enriched = with_quality(item)
            annotated = annotate_experience(enriched, formal_items)
            relation_cache = build_relation_cache(annotated, formal_item_count=len(formal_items))
            annotated["formal_relation_cache"] = relation_cache
            if relation_cache_needs_update(enriched.get("formal_relation_cache"), relation_cache):
                try:
                    self.experiences.update_metadata(
                        str(enriched.get("experience_id") or ""),
                        {"formal_relation_cache": relation_cache, "quality": annotated.get("quality", {})},
                        rebuild_index=False,
                    )
                except KeyError:
                    pass
            items.append(annotated)
        relation_counts = Counter(str(item.get("formal_relation") or "unknown") for item in items)
        quality_counts = Counter(str((item.get("quality") or {}).get("band") or "unknown") for item in items)
        retrieval_counts = Counter("retrievable" if (item.get("quality") or {}).get("retrieval_allowed") else "not_retrievable" for item in items)
        return {
            "ok": True,
            "items": items,
            "counts": self.experiences.counts(),
            "relation_counts": dict(relation_counts),
            "quality_counts": dict(quality_counts),
            "retrieval_counts": dict(retrieval_counts),
            "formal_knowledge_policy": "rag_experience_only_not_formal_knowledge",
        }

    def discard_experience(self, experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        item = self.experiences.discard(experience_id, reason=str(payload.get("reason") or "discarded in admin"))
        index = self.rag.rebuild_index()
        return {"ok": True, "item": item, "index": index}

    def promote_experience(self, experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        item = self.find_experience(experience_id)
        if str(item.get("status") or "active") == "discarded":
            return {"ok": False, "message": "discarded rag experience cannot be promoted"}
        candidate = build_candidate_from_experience(item, preferred_category=str(payload.get("target_category") or ""))
        candidate_path = REVIEW_ROOT / "pending" / f"{candidate['candidate_id']}.json"
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        upsert_candidate_to_db(candidate)
        updated = self.experiences.update_status(
            experience_id,
            status="promoted",
            reason="promoted_to_review_candidate",
            extra={"promoted_at": now(), "promoted_candidate_id": candidate["candidate_id"]},
        )
        index = self.rag.rebuild_index()
        return {"ok": True, "candidate": candidate, "item": updated, "index": index}

    def find_experience(self, experience_id: str) -> dict[str, Any]:
        for item in self.experiences.list(status="all", limit=500):
            if str(item.get("experience_id") or "") == experience_id:
                return item
        raise KeyError(experience_id)


def collect_formal_items() -> list[dict[str, Any]]:
    runtime = KnowledgeRuntime()
    category_ids = [str(item.get("id") or "") for item in runtime.list_categories(enabled_only=True)]
    for category_id in ("products", "policies", "chats", "erp_exports", *sorted(PRODUCT_SCOPED_CATEGORIES)):
        if category_id not in category_ids:
            category_ids.append(category_id)
    items: list[dict[str, Any]] = []
    for category_id in category_ids:
        if not category_id:
            continue
        try:
            records = runtime.list_items(category_id, include_archived=False)
        except Exception:
            continue
        for record in records:
            items.append(
                {
                    "category_id": category_id,
                    "item_id": str(record.get("id") or ""),
                    "product_id": str((record.get("data") or {}).get("product_id") or ""),
                    "title": formal_title(record),
                    "text": formal_text(record),
                    "item": record,
                }
            )
    return items


def annotate_experience(item: dict[str, Any], formal_items: list[dict[str, Any]]) -> dict[str, Any]:
    annotated = dict(item)
    status = str(item.get("status") or "active")
    if status in {"discarded", "promoted"}:
        annotated["formal_relation"] = status
        annotated["formal_match"] = {}
        annotated["recommended_action"] = "already_" + status
        return annotated

    text = experience_text(item)
    best = best_formal_match(item, text, formal_items)
    relation = "novel"
    action = "keep_as_rag_experience"
    if best and detect_conflict(text, best):
        relation = "conflicts_formal"
        action = "manual_review_conflict"
    elif best and best["similarity"] >= 0.78:
        relation = "covered_by_formal"
        action = "keep_low_priority_or_discard"
    elif best and best["similarity"] >= 0.48:
        relation = "supports_formal"
        action = "keep_as_supporting_expression"
    elif is_promotion_candidate(item):
        relation = "promotion_candidate"
        action = "promote_to_review_candidate"

    annotated["formal_relation"] = relation
    annotated["formal_match"] = compact_formal_match(best)
    annotated["recommended_action"] = action
    return annotated


def build_relation_cache(item: dict[str, Any], *, formal_item_count: int) -> dict[str, Any]:
    existing = item.get("formal_relation_cache") if isinstance(item.get("formal_relation_cache"), dict) else {}
    stable = {
        "relation": item.get("formal_relation") or "unknown",
        "formal_match": item.get("formal_match") or {},
        "recommended_action": item.get("recommended_action") or "",
        "formal_item_count": int(formal_item_count or 0),
    }
    if relation_cache_stable_part(existing) == stable:
        stable["evaluated_at"] = existing.get("evaluated_at") or now()
    else:
        stable["evaluated_at"] = now()
    return stable


def relation_cache_stable_part(cache: Any) -> dict[str, Any]:
    if not isinstance(cache, dict):
        return {}
    return {
        "relation": cache.get("relation") or "unknown",
        "formal_match": cache.get("formal_match") or {},
        "recommended_action": cache.get("recommended_action") or "",
        "formal_item_count": int(cache.get("formal_item_count") or 0),
    }


def relation_cache_needs_update(existing: Any, new_cache: dict[str, Any]) -> bool:
    if not isinstance(existing, dict):
        return True
    return relation_cache_stable_part(existing) != relation_cache_stable_part(new_cache)


def best_formal_match(item: dict[str, Any], text: str, formal_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not text.strip():
        return None
    hit = item.get("rag_hit", {}) or {}
    experience_product_id = str(hit.get("product_id") or "")
    experience_category = str(hit.get("category") or "")
    best: dict[str, Any] | None = None
    for formal in formal_items:
        score = text_similarity(text, str(formal.get("text") or ""))
        if experience_product_id and experience_product_id == str(formal.get("product_id") or ""):
            score += 0.08
        if experience_category and experience_category == str(formal.get("category_id") or ""):
            score += 0.04
        score = min(score, 1.0)
        if not best or score > float(best.get("similarity") or 0):
            best = {**formal, "similarity": round(score, 3)}
    if not best or float(best.get("similarity") or 0) < 0.22:
        return None
    return best


def compact_formal_match(match: dict[str, Any] | None) -> dict[str, Any]:
    if not match:
        return {}
    return {
        "category_id": match.get("category_id"),
        "item_id": match.get("item_id"),
        "product_id": match.get("product_id"),
        "title": match.get("title"),
        "similarity": match.get("similarity"),
    }


def is_promotion_candidate(item: dict[str, Any]) -> bool:
    usage = item.get("usage", {}) or {}
    reply_count = int(usage.get("reply_count", 1) or 1)
    hit = item.get("rag_hit", {}) or {}
    risk_terms = [str(value) for value in hit.get("risk_terms", []) or [] if str(value)]
    if risk_terms:
        return False
    return reply_count >= 2


def detect_conflict(experience: str, formal: dict[str, Any]) -> bool:
    formal_text_value = str(formal.get("text") or "")
    combined = experience + "\n" + formal_text_value
    if not any(term in combined for term in RISK_OR_DECISION_TERMS):
        return False
    experience_numbers = set(re.findall(r"\d+(?:\.\d+)?", experience))
    formal_numbers = set(re.findall(r"\d+(?:\.\d+)?", formal_text_value))
    if experience_numbers and formal_numbers and experience_numbers.isdisjoint(formal_numbers):
        return float(formal.get("similarity") or 0) >= 0.32
    return False


RISK_OR_DECISION_TERMS = {
    "price",
    "unit_price",
    "minimum",
    "refund",
    "compensation",
    "contract",
    "credit",
    "account period",
    "价格",
    "报价",
    "最低价",
    "优惠",
    "退款",
    "退货",
    "赔偿",
    "合同",
    "账期",
    "月结",
    "先发货",
}


def build_candidate_from_experience(item: dict[str, Any], *, preferred_category: str = "") -> dict[str, Any]:
    hit = item.get("rag_hit", {}) or {}
    category_id = choose_candidate_category(item, preferred_category=preferred_category)
    data = candidate_data_for_category(category_id, item)
    item_id = safe_item_id(data.get("sku") or data.get("title") or data.get("customer_message") or item.get("experience_id") or "rag_experience")
    candidate_id = "rag_promote_" + stable_digest(str(item.get("experience_id") or json.dumps(item, ensure_ascii=False)), 20)
    candidate_item = {
        "schema_version": 1,
        "category_id": category_id,
        "id": item_id,
        "status": "active",
        "source": {"type": "rag_experience", "experience_id": item.get("experience_id")},
        "data": data,
        "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
    }
    summary = truncate(str(item.get("summary") or item.get("question") or "RAG experience"), 80)
    return {
        "schema_version": 1,
        "candidate_id": candidate_id,
        "generated_at": now(),
        "source": {
            "type": "rag_experience",
            "experience_id": item.get("experience_id"),
            "rag_hit": hit,
            "evidence_excerpt": truncate(experience_text(item), 1200),
        },
        "detected_tags": ["rag_experience", category_id],
        "proposal": {
            "target_category": category_id,
            "change_type": "rag_experience_promote",
            "summary": f"RAG experience -> {category_id}: {summary}",
            "suggested_fields": data,
            "formal_patch": {
                "target_category": category_id,
                "operation": "upsert_item",
                "item": candidate_item,
            },
        },
        "review": {
            "status": "pending",
            "requires_human_approval": True,
            "allowed_auto_apply": False,
            "completeness_status": "ready",
            "rag_experience_id": item.get("experience_id"),
        },
        "intake": {
            "status": "ready",
            "missing_fields": [],
            "missing_labels": [],
            "warnings": [],
            "confidence": 0.72,
            "question": "",
        },
    }


def choose_candidate_category(item: dict[str, Any], *, preferred_category: str = "") -> str:
    if preferred_category in {"products", "policies", "chats", "erp_exports", *PRODUCT_SCOPED_CATEGORIES}:
        if preferred_category in PRODUCT_SCOPED_CATEGORIES and not str((item.get("rag_hit") or {}).get("product_id") or ""):
            return "chats"
        return preferred_category
    hit = item.get("rag_hit", {}) or {}
    hit_category = str(hit.get("category") or "")
    hit_source_type = str(hit.get("source_type") or "")
    if hit_category in PRODUCT_SCOPED_CATEGORIES and str(hit.get("product_id") or ""):
        return hit_category
    if hit_category == "policies" or "policy" in hit_source_type:
        return "policies"
    return "chats"


def candidate_data_for_category(category_id: str, item: dict[str, Any]) -> dict[str, Any]:
    hit = item.get("rag_hit", {}) or {}
    question = str(item.get("question") or "")
    reply = str(item.get("reply_text") or "")
    hit_text = str(hit.get("text") or "")
    title = truncate(str(item.get("summary") or question or reply or "RAG experience"), 64)
    keywords = keyword_list(" ".join([question, reply, hit_text]))
    additional_details = {
        "rag_experience_id": item.get("experience_id"),
        "source_chunk_id": hit.get("chunk_id"),
        "source_id": hit.get("source_id"),
        "source_text": truncate(hit_text, 500),
    }
    if category_id == "policies":
        return compact_dict(
            {
                "title": title,
                "policy_type": "other",
                "keywords": keywords,
                "answer": reply or hit_text,
                "allow_auto_reply": True,
                "requires_handoff": False,
                "operator_alert": False,
                "risk_level": "normal",
                "additional_details": additional_details,
            }
        )
    if category_id in PRODUCT_SCOPED_CATEGORIES:
        product_id = str(hit.get("product_id") or "")
        base = {"product_id": product_id, "title": title, "keywords": keywords, "additional_details": additional_details}
        if category_id == "product_faq":
            return compact_dict({**base, "question": question, "answer": reply or hit_text})
        if category_id == "product_rules":
            return compact_dict({**base, "answer": reply or hit_text, "allow_auto_reply": True, "requires_handoff": False})
        return compact_dict({**base, "content": reply or hit_text})
    return compact_dict(
        {
            "customer_message": question,
            "service_reply": reply or hit_text,
            "intent_tags": keyword_list(str(item.get("intent") or ""), fallback=["rag_experience"]),
            "tone_tags": ["rag_reference"],
            "linked_categories": [str(hit.get("category") or "")] if hit.get("category") else [],
            "additional_details": additional_details,
        }
    )


def formal_title(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return str(data.get("name") or data.get("title") or data.get("customer_message") or data.get("external_id") or item.get("id") or "")


def formal_text(item: dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return json.dumps({"id": item.get("id"), "data": data, "runtime": item.get("runtime", {})}, ensure_ascii=False, sort_keys=True)


def experience_text(item: dict[str, Any]) -> str:
    hit = item.get("rag_hit", {}) or {}
    parts = [
        str(item.get("summary") or ""),
        str(item.get("question") or ""),
        str(item.get("reply_text") or ""),
        str(hit.get("text") or ""),
        str(hit.get("category") or ""),
        str(hit.get("product_id") or ""),
    ]
    return "\n".join(part for part in parts if part.strip())


def text_similarity(left: str, right: str) -> float:
    left_fp = normalized_fingerprint(left)
    right_fp = normalized_fingerprint(right)
    if not left_fp or not right_fp:
        return 0.0
    seq = SequenceMatcher(None, left_fp[:1600], right_fp[:1600]).ratio()
    left_terms = tokenize_for_relation(left)
    right_terms = tokenize_for_relation(right)
    overlap = len(left_terms & right_terms) / max(1, len(left_terms | right_terms))
    coverage = len(left_terms & right_terms) / max(1, len(left_terms))
    return round(max(seq * 0.55 + overlap * 0.25 + coverage * 0.2, overlap), 4)


def tokenize_for_relation(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_.-]{2,}", normalized, flags=re.IGNORECASE))
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        tokens.add(run)
        for size in (2, 3, 4):
            if len(run) >= size:
                tokens.update(run[index : index + size] for index in range(0, len(run) - size + 1))
    return {token for token in tokens if token.strip()}


def keyword_list(text: str, *, fallback: list[str] | None = None) -> list[str]:
    terms = sorted(tokenize_for_relation(text), key=lambda item: (-len(item), item))
    values = [term for term in terms if len(term) >= 2][:8]
    return values or list(fallback or [])


def normalized_fingerprint(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\"'`;:，。；：、/\\\[\]{}()（）<>《》|_-]+", "", text)
    return text


def compact_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in ("", None, [], {})}


def safe_item_id(value: Any) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip().lower())
    text = re.sub(r"-{2,}", "-", text).strip("-._")
    if not text or not re.match(r"^[a-z0-9]", text):
        text = "rag_item_" + stable_digest(str(value), 12)
    return text[:120]


def stable_digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")
