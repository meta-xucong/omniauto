"""RAG self-learning experience store.

This store is deliberately separate from the formal structured knowledge bases.
RAG reply experiences are accepted by default for review and retrieval analysis,
but they are never promoted into formal knowledge without a separate human
approval workflow.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_root
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config


MAX_RECORDS = 2000
QUALITY_RETRIEVAL_MIN_SCORE = 0.52
QUALITY_RETRIEVAL_MIN_HIT_SCORE = 0.32
QUALITY_REPEATABLE_MIN_HIT_SCORE = 0.24
QUALITY_REPEATABLE_REPLY_COUNT = 3
QUALITY_BLOCK_ACTION_TERMS = {
    "handoff",
    "manual",
    "human",
    "operator",
    "approve",
    "approval",
    "reject",
    "refuse",
    "blocked",
    "请示",
    "人工",
    "接管",
    "转人工",
}


class RagExperienceStore:
    def __init__(self, *, tenant_id: str | None = None, root: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.root = root or (tenant_root(self.tenant_id) / "rag_experience")

    @property
    def path(self) -> Path:
        return self.root / "experiences.json"

    def list(self, *, status: str = "active", limit: int = 100) -> list[dict[str, Any]]:
        db = postgres_store(self.tenant_id)
        if db:
            return db.list_rag_experiences(self.tenant_id, status=status, limit=limit)
        records = self._read()
        if status and status != "all":
            records = [item for item in records if str(item.get("status") or "active") == status]
        records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return records[: max(1, min(int(limit or 100), 500))]

    def list_retrievable(self, *, limit: int = 500) -> list[dict[str, Any]]:
        records = []
        for item in self.list(status="active", limit=limit):
            enriched = with_quality(item)
            if experience_is_retrievable(enriched):
                records.append(enriched)
        return records

    def counts(self) -> dict[str, int]:
        db = postgres_store(self.tenant_id)
        if db:
            records = db.list_rag_experiences(self.tenant_id, status="all", limit=500)
            counts = {"total": len(records), "active": 0, "discarded": 0}
            for item in records:
                status = str(item.get("status") or "active")
                counts[status] = counts.get(status, 0) + 1
            return counts
        records = self._read()
        counts = {"total": len(records), "active": 0, "discarded": 0}
        for item in records:
            status = str(item.get("status") or "active")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def record_reply(
        self,
        *,
        target: str,
        message_ids: list[str],
        question: str,
        reply_text: str,
        raw_reply_text: str,
        intent_assist: dict[str, Any],
        rag_reply: dict[str, Any],
    ) -> dict[str, Any]:
        now_text = now()
        hit = rag_reply.get("hit", {}) or {}
        fingerprint = stable_digest(
            "|".join(
                [
                    self.tenant_id,
                    normalize_space(question),
                    str(hit.get("chunk_id") or ""),
                    normalize_space(raw_reply_text or reply_text),
                ]
            ),
            20,
        )
        record = {
            "experience_id": "rag_exp_" + fingerprint,
            "tenant_id": self.tenant_id,
            "status": "active",
            "source": "rag_reply",
            "formal_knowledge_policy": "experience_only_not_formal_knowledge",
            "summary": summarize_experience(question, raw_reply_text or reply_text, hit),
            "question": normalize_space(question),
            "reply_text": normalize_space(raw_reply_text or reply_text),
            "target": target,
            "message_ids": message_ids,
            "intent": intent_assist.get("intent"),
            "recommended_action": intent_assist.get("recommended_action"),
            "safety": (intent_assist.get("evidence", {}) or {}).get("safety", {}),
            "rag_hit": {
                "chunk_id": hit.get("chunk_id"),
                "source_id": hit.get("source_id"),
                "score": hit.get("score"),
                "category": hit.get("category"),
                "source_type": hit.get("source_type"),
                "product_id": hit.get("product_id"),
                "text": hit.get("text"),
                "risk_terms": hit.get("risk_terms", []),
            },
            "usage": {
                "reply_count": 1,
                "last_used_at": now_text,
            },
            "created_at": now_text,
            "updated_at": now_text,
        }
        record["quality"] = score_experience_quality(record)
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            existing = next((item for item in db.list_rag_experiences(self.tenant_id, status="all", limit=500) if item.get("experience_id") == record["experience_id"]), None)
            if existing:
                usage = dict(existing.get("usage", {}) or {})
                usage["reply_count"] = int(usage.get("reply_count", 1) or 1) + 1
                usage["last_used_at"] = now_text
                existing.update(
                    {
                        "status": existing.get("status") or "active",
                        "summary": record["summary"],
                        "question": record["question"],
                        "reply_text": record["reply_text"],
                        "target": record["target"],
                        "message_ids": record["message_ids"],
                        "intent": record["intent"],
                        "recommended_action": record["recommended_action"],
                        "safety": record["safety"],
                        "rag_hit": record["rag_hit"],
                        "usage": usage,
                        "updated_at": now_text,
                    }
                )
                existing["quality"] = score_experience_quality(existing)
                db.upsert_rag_experience(existing)
                rebuild_rag_index_safely(self.tenant_id)
                if not config.mirror_files:
                    return existing
                record = existing
            else:
                db.upsert_rag_experience(record)
                rebuild_rag_index_safely(self.tenant_id)
                if not config.mirror_files:
                    return record
        records = self._read()
        for index, existing in enumerate(records):
            if existing.get("experience_id") == record["experience_id"]:
                usage = dict(existing.get("usage", {}) or {})
                usage["reply_count"] = int(usage.get("reply_count", 1) or 1) + 1
                usage["last_used_at"] = now_text
                existing.update(
                    {
                        "status": existing.get("status") or "active",
                        "summary": record["summary"],
                        "question": record["question"],
                        "reply_text": record["reply_text"],
                        "target": record["target"],
                        "message_ids": record["message_ids"],
                        "intent": record["intent"],
                        "recommended_action": record["recommended_action"],
                        "safety": record["safety"],
                        "rag_hit": record["rag_hit"],
                        "usage": usage,
                        "updated_at": now_text,
                    }
                )
                existing["quality"] = score_experience_quality(existing)
                records[index] = existing
                self._write(records)
                rebuild_rag_index_safely(self.tenant_id)
                return existing
        records.append(record)
        self._write(records)
        rebuild_rag_index_safely(self.tenant_id)
        return record

    def discard(self, experience_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.update_status(
            experience_id,
            status="discarded",
            reason=reason or "discarded_by_user",
            extra={"discarded_at": now()},
        )

    def update_status(
        self,
        experience_id: str,
        *,
        status: str,
        reason: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        allowed = {"active", "discarded", "promoted"}
        status = str(status or "").strip()
        if status not in allowed:
            raise ValueError(f"unsupported rag experience status: {status}")
        extra = extra or {}
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        db_item: dict[str, Any] | None = None
        if db:
            records = db.list_rag_experiences(self.tenant_id, status="all", limit=500)
            for item in records:
                if item.get("experience_id") != experience_id:
                    continue
                now_text = now()
                item["status"] = status
                if reason:
                    item[f"{status}_reason"] = reason
                    if status == "discarded":
                        item["discard_reason"] = reason
                for key, value in extra.items():
                    item[key] = value
                item["updated_at"] = now_text
                item["quality"] = score_experience_quality(item)
                db.upsert_rag_experience(item)
                rebuild_rag_index_safely(self.tenant_id)
                if not config.mirror_files:
                    return item
                db_item = item
                break
        records = self._read()
        now_text = now()
        for index, item in enumerate(records):
            if item.get("experience_id") != experience_id:
                continue
            item["status"] = status
            if reason:
                item[f"{status}_reason"] = reason
                if status == "discarded":
                    item["discard_reason"] = reason
            for key, value in extra.items():
                item[key] = value
            item["updated_at"] = now_text
            item["quality"] = score_experience_quality(item)
            records[index] = item
            self._write(records)
            rebuild_rag_index_safely(self.tenant_id)
            return item
        if db_item:
            records.append(db_item)
            self._write(records)
            rebuild_rag_index_safely(self.tenant_id)
            return db_item
        raise KeyError(experience_id)

    def update_metadata(
        self,
        experience_id: str,
        metadata: dict[str, Any],
        *,
        rebuild_index: bool = False,
    ) -> dict[str, Any]:
        metadata = dict(metadata or {})
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        db_item: dict[str, Any] | None = None
        if db:
            records = db.list_rag_experiences(self.tenant_id, status="all", limit=500)
            for item in records:
                if item.get("experience_id") != experience_id:
                    continue
                item.update(metadata)
                item["updated_at"] = now()
                item["quality"] = score_experience_quality(item)
                db.upsert_rag_experience(item)
                if rebuild_index:
                    rebuild_rag_index_safely(self.tenant_id)
                if not config.mirror_files:
                    return item
                db_item = item
                break
        records = self._read()
        for index, item in enumerate(records):
            if item.get("experience_id") != experience_id:
                continue
            item.update(metadata)
            item["updated_at"] = now()
            item["quality"] = score_experience_quality(item)
            records[index] = item
            self._write(records)
            if rebuild_index:
                rebuild_rag_index_safely(self.tenant_id)
            return item
        if db_item:
            records.append(db_item)
            self._write(records)
            if rebuild_index:
                rebuild_rag_index_safely(self.tenant_id)
            return db_item
        raise KeyError(experience_id)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        compact = records[-MAX_RECORDS:]
        self.path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")


def record_rag_reply_experience(
    *,
    target: str,
    message_ids: list[str],
    question: str,
    reply_text: str,
    raw_reply_text: str,
    intent_assist: dict[str, Any],
    rag_reply: dict[str, Any],
) -> dict[str, Any] | None:
    if not rag_reply.get("applied"):
        return None
    return RagExperienceStore().record_reply(
        target=target,
        message_ids=message_ids,
        question=question,
        reply_text=reply_text,
        raw_reply_text=raw_reply_text,
        intent_assist=intent_assist,
        rag_reply=rag_reply,
    )


def summarize_experience(question: str, reply_text: str, hit: dict[str, Any]) -> str:
    question_text = truncate(normalize_space(question), 54)
    hit_text = truncate(normalize_space(str(hit.get("text") or "")), 68)
    reply = truncate(normalize_space(reply_text), 68)
    parts = [f"客户问法：{question_text}"]
    if hit_text:
        parts.append(f"命中资料：{hit_text}")
    if reply:
        parts.append(f"回复要点：{reply}")
    return "；".join(parts)


def with_quality(item: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(item)
    quality = enriched.get("quality")
    if not isinstance(quality, dict) or "retrieval_allowed" not in quality:
        quality = score_experience_quality(enriched)
    enriched["quality"] = quality
    return enriched


def experience_is_retrievable(item: dict[str, Any]) -> bool:
    if str(item.get("status") or "active") != "active":
        return False
    quality = item.get("quality") if isinstance(item.get("quality"), dict) else score_experience_quality(item)
    return bool(quality.get("retrieval_allowed"))


def score_experience_quality(item: dict[str, Any]) -> dict[str, Any]:
    hit = item.get("rag_hit", {}) or {}
    usage = item.get("usage", {}) or {}
    safety = item.get("safety", {}) or {}
    question = normalize_space(str(item.get("question") or ""))
    reply = normalize_space(str(item.get("reply_text") or ""))
    hit_text = normalize_space(str(hit.get("text") or ""))
    hit_score = coerce_float(hit.get("score"), 0.0)
    reply_count = max(1, int(coerce_float(usage.get("reply_count"), 1)))
    risk_terms = [str(value) for value in hit.get("risk_terms", []) or [] if str(value).strip()]
    recommended_action = str(item.get("recommended_action") or "").lower()
    must_handoff = bool(safety.get("must_handoff"))
    blocked_action = any(term.lower() in recommended_action for term in QUALITY_BLOCK_ACTION_TERMS)
    has_text = bool(question and reply)
    has_source = bool(hit_text or str(hit.get("chunk_id") or ""))

    score = 0.22
    score += min(0.46, max(0.0, hit_score) * 0.46)
    score += min(0.12, reply_count * 0.025)
    if has_text:
        score += 0.1
    if has_source:
        score += 0.06
    if len(question) >= 8 and len(reply) >= 12:
        score += 0.05

    blockers: list[str] = []
    reasons: list[str] = []
    if not has_text:
        blockers.append("缺少清晰的问题或回复")
    if not has_source:
        reasons.append("缺少可追溯的命中资料")
        score -= 0.08
    if risk_terms:
        blockers.append("命中资料包含风险词")
        score -= 0.25
    if must_handoff:
        blockers.append("当时证据要求人工接管")
        score -= 0.25
    if blocked_action:
        blockers.append("当时建议动作需要人工处理")
        score -= 0.18
    if hit_score < QUALITY_REPEATABLE_MIN_HIT_SCORE:
        reasons.append("原始命中分偏低")
        score -= 0.08
    elif hit_score < QUALITY_RETRIEVAL_MIN_HIT_SCORE and reply_count < QUALITY_REPEATABLE_REPLY_COUNT:
        reasons.append("命中分中等偏低且复用次数不足")
        score -= 0.04
    else:
        reasons.append("证据命中分达到经验层要求")
    if reply_count >= QUALITY_REPEATABLE_REPLY_COUNT:
        reasons.append("已被多次复用")

    score = round(max(0.0, min(0.99, score)), 3)
    enough_hit_score = hit_score >= QUALITY_RETRIEVAL_MIN_HIT_SCORE or (
        hit_score >= QUALITY_REPEATABLE_MIN_HIT_SCORE and reply_count >= QUALITY_REPEATABLE_REPLY_COUNT
    )
    retrieval_allowed = not blockers and enough_hit_score and score >= QUALITY_RETRIEVAL_MIN_SCORE
    if blockers:
        band = "blocked"
    elif score >= 0.72:
        band = "high"
    elif retrieval_allowed:
        band = "medium"
    else:
        band = "low"
    reasons.append("允许参与 RAG 经验检索" if retrieval_allowed else "暂不参与 RAG 经验检索")
    return {
        "score": score,
        "band": band,
        "retrieval_allowed": retrieval_allowed,
        "reasons": [*blockers, *reasons],
        "signals": {
            "hit_score": hit_score,
            "reply_count": reply_count,
            "has_risk_terms": bool(risk_terms),
            "risk_terms": risk_terms,
            "must_handoff": must_handoff,
            "blocked_action": blocked_action,
            "has_text": has_text,
            "has_source": has_source,
        },
        "evaluated_at": now(),
    }


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_space(value: str) -> str:
    return " ".join(str(value or "").split())


def truncate(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def stable_digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rebuild_rag_index_safely(tenant_id: str) -> None:
    try:
        from apps.wechat_ai_customer_service.workflows.rag_layer import RagService

        RagService(tenant_id=tenant_id).rebuild_index()
    except Exception:
        return


def postgres_store(tenant_id: str):
    config = load_storage_config()
    if not config.use_postgres or not config.postgres_configured:
        return None
    store = get_postgres_store(tenant_id=tenant_id, config=config)
    return store if store.available() else None
