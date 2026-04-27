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
                db.upsert_rag_experience(existing)
                if not config.mirror_files:
                    return existing
            else:
                db.upsert_rag_experience(record)
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
                records[index] = existing
                self._write(records)
                return existing
        records.append(record)
        self._write(records)
        return record

    def discard(self, experience_id: str, *, reason: str = "") -> dict[str, Any]:
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            records = db.list_rag_experiences(self.tenant_id, status="all", limit=500)
            for item in records:
                if item.get("experience_id") != experience_id:
                    continue
                now_text = now()
                item["status"] = "discarded"
                item["discard_reason"] = reason or "discarded_by_user"
                item["discarded_at"] = now_text
                item["updated_at"] = now_text
                db.upsert_rag_experience(item)
                if not config.mirror_files:
                    return item
                break
        records = self._read()
        now_text = now()
        for index, item in enumerate(records):
            if item.get("experience_id") != experience_id:
                continue
            item["status"] = "discarded"
            item["discard_reason"] = reason or "discarded_by_user"
            item["discarded_at"] = now_text
            item["updated_at"] = now_text
            records[index] = item
            self._write(records)
            return item
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


def postgres_store(tenant_id: str):
    config = load_storage_config()
    if not config.use_postgres or not config.postgres_configured:
        return None
    store = get_postgres_store(tenant_id=tenant_id, config=config)
    return store if store.available() else None
