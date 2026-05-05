"""Shared raw WeChat message persistence for customer-service and recorder flows."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config


MAX_FILE_RECORDS = 10000
MAX_BATCH_RECORDS = 2000
SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class RawMessageStore:
    def __init__(self, *, tenant_id: str | None = None, root: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.root = root or (tenant_runtime_root(self.tenant_id) / "raw_messages")

    @property
    def conversations_path(self) -> Path:
        return self.root / "conversations.json"

    @property
    def messages_path(self) -> Path:
        return self.root / "messages.json"

    @property
    def batches_path(self) -> Path:
        return self.root / "batches.json"

    def upsert_conversation(self, record: dict[str, Any]) -> dict[str, Any]:
        conversation = normalize_conversation(record, tenant_id=self.tenant_id)
        db = postgres_store()
        config = load_storage_config()
        if db:
            db.upsert_raw_conversation(self.tenant_id, conversation)
            if not config.mirror_files:
                return conversation
        conversations = self._read_json(self.conversations_path, [])
        by_id = {str(item.get("conversation_id") or ""): item for item in conversations if isinstance(item, dict)}
        existing = by_id.get(conversation["conversation_id"], {})
        merged = {**existing, **conversation}
        by_id[conversation["conversation_id"]] = merged
        self._write_json(self.conversations_path, sorted(by_id.values(), key=lambda item: str(item.get("updated_at") or ""), reverse=True))
        return merged

    def list_conversations(self, *, conversation_type: str = "", status: str = "all", limit: int = 200) -> list[dict[str, Any]]:
        db = postgres_store()
        if db:
            items = db.list_raw_conversations(self.tenant_id, conversation_type=conversation_type, status=status)
            if items:
                return items[: max(1, min(int(limit or 200), 500))]
        records = [item for item in self._read_json(self.conversations_path, []) if isinstance(item, dict)]
        if conversation_type:
            records = [item for item in records if str(item.get("conversation_type") or "") == conversation_type]
        if status and status != "all":
            records = [item for item in records if str(item.get("status") or "active") == status]
        records.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return records[: max(1, min(int(limit or 200), 500))]

    def upsert_messages(
        self,
        conversation: dict[str, Any],
        messages: list[dict[str, Any]],
        *,
        source_module: str,
        learning_enabled: bool = True,
        create_batch: bool = True,
        batch_reason: str = "message_observed",
    ) -> dict[str, Any]:
        normalized_conversation = self.upsert_conversation(conversation)
        existing = self._message_map()
        inserted: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        updated_records = dict(existing)
        db = postgres_store()
        config = load_storage_config()
        for raw in messages:
            message = normalize_message(
                raw,
                conversation=normalized_conversation,
                tenant_id=self.tenant_id,
                source_module=source_module,
                learning_enabled=learning_enabled,
            )
            db_existing = db.get_raw_message_by_dedupe(self.tenant_id, message["dedupe_key"]) if db else None
            previous = db_existing or updated_records.get(message["dedupe_key"])
            if previous:
                message = merge_message(previous, message, source_module=source_module)
                duplicates.append(message)
            else:
                inserted.append(message)
            if db:
                db.upsert_raw_message(self.tenant_id, message)
            updated_records[message["dedupe_key"]] = message
        if not db or config.mirror_files:
            records = sorted(updated_records.values(), key=lambda item: str(item.get("observed_at") or ""), reverse=True)
            self._write_json(self.messages_path, records[:MAX_FILE_RECORDS])
        batch = None
        if create_batch and inserted:
            batch = self.create_batch(
                conversation_id=normalized_conversation["conversation_id"],
                message_ids=[str(item.get("raw_message_id") or "") for item in inserted],
                reason=batch_reason,
                source_module=source_module,
            )
        return {
            "ok": True,
            "conversation": normalized_conversation,
            "inserted_count": len(inserted),
            "duplicate_count": len(duplicates),
            "message_ids": [item["raw_message_id"] for item in inserted],
            "duplicate_message_ids": [item["raw_message_id"] for item in duplicates],
            "batch": batch,
        }

    def list_messages(self, *, conversation_id: str = "", query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        db = postgres_store()
        if db:
            return db.list_raw_messages(self.tenant_id, conversation_id=conversation_id, query=query, limit=limit)
        records = [item for item in self._read_json(self.messages_path, []) if isinstance(item, dict)]
        if conversation_id:
            records = [item for item in records if str(item.get("conversation_id") or "") == conversation_id]
        if query:
            lowered = query.lower()
            records = [item for item in records if lowered in str(item.get("content") or "").lower()]
        records.sort(key=lambda item: str(item.get("observed_at") or ""), reverse=True)
        return records[: max(1, min(int(limit or 100), 500))]

    def create_batch(
        self,
        *,
        conversation_id: str,
        message_ids: list[str],
        reason: str,
        source_module: str,
    ) -> dict[str, Any]:
        clean_ids = [str(item) for item in message_ids if str(item)]
        created_at = now()
        batch = {
            "batch_id": "raw_batch_" + stable_digest(f"{self.tenant_id}:{conversation_id}:{reason}:{created_at}:{clean_ids}", 20),
            "tenant_id": self.tenant_id,
            "conversation_id": conversation_id,
            "message_ids": clean_ids,
            "reason": reason,
            "source_module": source_module,
            "status": "pending",
            "created_at": created_at,
        }
        db = postgres_store()
        config = load_storage_config()
        if db:
            db.upsert_raw_message_batch(self.tenant_id, batch)
            if not config.mirror_files:
                return batch
        records = [item for item in self._read_json(self.batches_path, []) if isinstance(item, dict)]
        records = [item for item in records if item.get("batch_id") != batch["batch_id"]]
        records.insert(0, batch)
        self._write_json(self.batches_path, records[:MAX_BATCH_RECORDS])
        return batch

    def list_batches(self, *, conversation_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        db = postgres_store()
        if db:
            return db.list_raw_message_batches(self.tenant_id, conversation_id=conversation_id, limit=limit)
        records = [item for item in self._read_json(self.batches_path, []) if isinstance(item, dict)]
        if conversation_id:
            records = [item for item in records if str(item.get("conversation_id") or "") == conversation_id]
        records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return records[: max(1, min(int(limit or 100), 500))]

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        for batch in self.list_batches(limit=500):
            if str(batch.get("batch_id") or "") == batch_id:
                return batch
        return None

    def update_batch(self, batch_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_batch(batch_id)
        if not existing:
            raise FileNotFoundError(batch_id)
        updated = {**existing, **patch, "updated_at": now()}
        db = postgres_store()
        config = load_storage_config()
        if db:
            db.upsert_raw_message_batch(self.tenant_id, updated)
            if not config.mirror_files:
                return updated
        records = [item for item in self._read_json(self.batches_path, []) if isinstance(item, dict)]
        replaced = False
        for index, item in enumerate(records):
            if str(item.get("batch_id") or "") == batch_id:
                records[index] = updated
                replaced = True
                break
        if not replaced:
            records.insert(0, updated)
        self._write_json(self.batches_path, records[:MAX_BATCH_RECORDS])
        return updated

    def summary(self) -> dict[str, Any]:
        conversations = self.list_conversations(limit=500)
        messages = self.list_messages(limit=500)
        batches = self.list_batches(limit=500)
        return {
            "conversation_count": len(conversations),
            "message_count": len(messages),
            "batch_count": len(batches),
            "group_count": len([item for item in conversations if item.get("conversation_type") == "group"]),
            "private_count": len([item for item in conversations if item.get("conversation_type") == "private"]),
            "pending_batch_count": len([item for item in batches if item.get("status") == "pending"]),
        }

    def _message_map(self) -> dict[str, dict[str, Any]]:
        return {
            str(item.get("dedupe_key") or ""): item
            for item in self._read_json(self.messages_path, [])
            if isinstance(item, dict) and item.get("dedupe_key")
        }

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)


def normalize_conversation(record: dict[str, Any], *, tenant_id: str) -> dict[str, Any]:
    target_name = str(record.get("target_name") or record.get("name") or record.get("display_name") or "").strip()
    conversation_type = normalize_conversation_type(str(record.get("conversation_type") or record.get("type") or "unknown"))
    seed = str(record.get("conversation_id") or f"{conversation_type}:{target_name or record}")
    conversation_id = safe_id(str(record.get("conversation_id") or "conv_" + stable_digest(f"{tenant_id}:{seed}", 18)))
    timestamp = now()
    return {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "conversation_type": conversation_type,
        "target_name": target_name,
        "display_name": str(record.get("display_name") or target_name or conversation_id),
        "group_name": str(record.get("group_name") or (target_name if conversation_type == "group" else "")),
        "status": str(record.get("status") or "active"),
        "exact": record.get("exact", True) is not False,
        "record_self": bool(record.get("record_self", False)),
        "learning_enabled": record.get("learning_enabled", True) is not False,
        "notify_enabled": bool(record.get("notify_enabled", False)),
        "selected_by_user": bool(record.get("selected_by_user", False)),
        "created_at": str(record.get("created_at") or timestamp),
        "updated_at": timestamp,
        "source": record.get("source") if isinstance(record.get("source"), dict) else {},
        "raw_payload": record.get("raw_payload") if "raw_payload" in record else record,
    }


def normalize_message(
    record: dict[str, Any],
    *,
    conversation: dict[str, Any],
    tenant_id: str,
    source_module: str,
    learning_enabled: bool,
) -> dict[str, Any]:
    content = str(record.get("content") or record.get("text") or "")
    message_id = str(record.get("id") or record.get("message_id") or "")
    sender = str(record.get("sender") or "")
    message_time = str(record.get("time") or record.get("message_time") or "")
    content_type = str(record.get("type") or record.get("content_type") or "text")
    sender_role = normalize_sender_role(record, sender=sender)
    content_fingerprint = normalized_content_fingerprint(content)
    explicit_dedupe_key = str(record.get("dedupe_key") or "").strip()
    if explicit_dedupe_key:
        dedupe_seed = explicit_dedupe_key
    elif content_fingerprint:
        dedupe_seed = "|".join([conversation["conversation_id"], sender, content_type, content_fingerprint, message_time])
    else:
        dedupe_seed = message_id or "|".join([conversation["conversation_id"], sender, content_type, message_time])
    dedupe_key = stable_digest(f"{tenant_id}:{conversation['conversation_id']}:{dedupe_seed}", 32)
    raw_message_id = "raw_msg_" + dedupe_key[:20]
    timestamp = now()
    return {
        "tenant_id": tenant_id,
        "raw_message_id": raw_message_id,
        "conversation_id": conversation["conversation_id"],
        "conversation_type": conversation.get("conversation_type") or "unknown",
        "target_name": conversation.get("target_name") or "",
        "group_name": conversation.get("group_name") or "",
        "message_id": message_id,
        "sender": sender,
        "sender_role": sender_role,
        "group_member_name": str(record.get("group_member_name") or (sender if conversation.get("conversation_type") == "group" else "")),
        "content_type": content_type,
        "content": content,
        "message_time": message_time,
        "message_fingerprint": content_fingerprint,
        "observed_at": str(record.get("observed_at") or timestamp),
        "updated_at": timestamp,
        "source_modules": [source_module],
        "source_adapter": str(record.get("source_adapter") or "wxauto4"),
        "learning_enabled": bool(learning_enabled),
        "excluded_reason": str(record.get("excluded_reason") or ""),
        "dedupe_key": dedupe_key,
        "raw_payload": record,
    }


def merge_message(existing: dict[str, Any], incoming: dict[str, Any], *, source_module: str) -> dict[str, Any]:
    merged = dict(existing)
    modules = [str(item) for item in merged.get("source_modules", []) if str(item)]
    if source_module not in modules:
        modules.append(source_module)
    merged["source_modules"] = modules
    merged["updated_at"] = now()
    merged["learning_enabled"] = bool(merged.get("learning_enabled", incoming.get("learning_enabled", True)))
    return merged


def normalize_conversation_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if text in {"private", "group", "file_transfer", "system", "unknown"}:
        return text
    if text in {"chatroom", "room"}:
        return "group"
    return "unknown"


def normalize_sender_role(record: dict[str, Any], *, sender: str) -> str:
    role = str(record.get("sender_role") or "").strip().lower()
    if role in {"self", "contact", "group_member", "bot", "system", "unknown"}:
        return role
    if sender == "self" or record.get("is_self"):
        return "self"
    return "unknown"


def safe_id(value: str) -> str:
    text = SAFE_ID_RE.sub("_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("._-")
    if not text or not re.match(r"^[A-Za-z0-9]", text):
        text = "id_" + stable_digest(value, 12)
    return text[:120]


def stable_digest(value: Any, length: int = 16) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def normalized_content_fingerprint(value: str) -> str:
    text = re.sub(r"\s+", "\n", str(value or "").strip())
    return stable_digest(text, 32) if text else ""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def postgres_store():
    config = load_storage_config()
    if not config.use_postgres or not config.postgres_configured:
        return None
    store = get_postgres_store(config=config)
    return store if store.available() else None
