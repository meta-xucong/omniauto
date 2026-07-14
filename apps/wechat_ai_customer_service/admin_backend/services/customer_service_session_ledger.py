"""Session identity and lightweight local ledger for RPA customer service.

The ledger is the local source of truth for conversation state: session binding,
captured inputs, pending reply anchors, sent reply anchors, and compact context.
It is not an authority source for product facts or formal policy. Brain First
still owns customer-visible reply strategy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root
from apps.wechat_ai_customer_service.message_identity import (
    canonical_input_message_id,
    canonical_visual_message_id,
)

MAX_LEDGER_RECENT_MESSAGES = 80
MAX_LEDGER_EVENT_MESSAGES = 30
MAX_LEDGER_CONTEXT_LINES = 14
MAX_LEDGER_MESSAGE_CHARS = 600
MAX_LEDGER_SEMANTIC_CHARS = 1200
MAX_LEDGER_JSON_ITEMS = 24

# Image pixels were formerly archived through several intermediate scheduler
# and ledger shapes.  Vision is now an in-memory clipboard transaction; these
# historical fields must therefore never be accepted back into persisted
# context, even when an old state file is replayed.
LEGACY_IMAGE_STORAGE_KEYS = frozenset(
    {
        "asset_id",
        "image_assets",
        "saved_image_path",
        "bubble_crop_path",
        "thumbnail_path",
        "turn_capture_path",
        "meta_path",
        "diagnostic_path",
        "sha256",
        "size_bytes",
        "width",
        "height",
        "bubble_bounds",
        "bubble_anchor",
        "capture_detection",
    }
)


def utcnow_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_display_name(value: Any) -> str:
    return str(value or "").strip()


def normalize_conversation_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"private", "group", "file_transfer", "system"}:
        return text
    return "unknown"


def stable_hash(*parts: Any, length: int = 20) -> str:
    seed = json.dumps([str(item) for item in parts], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[: max(8, int(length or 20))]


def stable_session_key(
    display_name: Any,
    *,
    conversation_type: Any = "unknown",
    row_fingerprint: dict[str, Any] | None = None,
    explicit_key: Any = "",
) -> str:
    """Return a stable internal key that is not merely the display name.

    When an explicit key comes from the sidecar/session binding layer, keep it.
    Otherwise use type + display name.  Row fingerprint is deliberately used only
    when it includes a duplicate discriminator, because row order alone can move
    as conversations receive messages.
    """

    explicit = str(explicit_key or "").strip()
    if explicit:
        return explicit
    name = normalize_display_name(display_name)
    ctype = normalize_conversation_type(conversation_type)
    fingerprint = row_fingerprint if isinstance(row_fingerprint, dict) else {}
    duplicate_key = str(fingerprint.get("duplicate_discriminator") or "").strip()
    return "wx:rpa:v1:" + stable_hash(ctype, name, duplicate_key)


def row_fingerprint_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = payload.get("row_fingerprint")
    if isinstance(direct, dict):
        return dict(direct)
    result: dict[str, Any] = {}
    for key in ("center_y", "left", "right", "top", "bottom"):
        if key in payload:
            result[key] = payload.get(key)
    badge_meta = payload.get("unread_badge_meta")
    if isinstance(badge_meta, dict):
        bbox = badge_meta.get("bbox") or badge_meta.get("bounds")
        if bbox:
            result["last_unread_badge_bbox"] = bbox
    preview = str(payload.get("content") or payload.get("preview") or "").strip()
    if preview:
        result["last_preview_digest"] = stable_hash(preview, length=16)
    return result


def session_key_from_payload(payload: dict[str, Any] | None, *, fallback_name: Any = "") -> str:
    payload = payload if isinstance(payload, dict) else {}
    name = payload.get("name") or payload.get("title") or payload.get("target_name") or fallback_name
    return stable_session_key(
        name,
        conversation_type=payload.get("conversation_type") or payload.get("type") or "unknown",
        row_fingerprint=row_fingerprint_from_payload(payload),
        explicit_key=payload.get("session_key"),
    )


def safe_filename(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    return text.strip("._") or "session"


def ledger_message_content_key(message: dict[str, Any]) -> str:
    sender = str(message.get("sender") or "")
    content = " ".join(str(message.get("content") or "").split())
    msg_type = str(message.get("type") or "")
    if msg_type in {"image", "picture", "photo"} or message.get("is_customer_image_proxy"):
        for key in ("visual_occurrence_id", "source_message_id", "message_id", "id", "asset_id"):
            value = str(message.get(key) or "").strip()
            if value:
                return stable_hash(sender, msg_type, "visual_image", value, length=24)
    if not content:
        return ""
    return stable_hash(sender, msg_type, content, length=24)


def _clip_ledger_text(value: Any, *, limit: int = MAX_LEDGER_SEMANTIC_CHARS) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 3)].rstrip() + "..."


def _compact_ledger_json(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return _clip_ledger_text(value, limit=240)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:MAX_LEDGER_JSON_ITEMS]:
            clean_key = _clip_ledger_text(key, limit=80)
            if clean_key:
                result[clean_key] = _compact_ledger_json(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_compact_ledger_json(item, depth=depth + 1) for item in list(value)[:MAX_LEDGER_JSON_ITEMS]]
    if isinstance(value, str):
        return _clip_ledger_text(value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _clip_ledger_text(value)


def scrub_legacy_image_storage(value: Any) -> Any:
    """Remove retired file/crop metadata without touching textual vision facts.

    This is deliberately recursive because old scheduler captures and ledger
    summaries can contain the fields below several layers of metadata.  It is
    used on both read and write paths: stale files cannot become an implicit
    image input again, and new code cannot accidentally persist one.
    """

    if isinstance(value, dict):
        return {
            key: scrub_legacy_image_storage(item)
            for key, item in value.items()
            if str(key) not in LEGACY_IMAGE_STORAGE_KEYS
        }
    if isinstance(value, list):
        return [scrub_legacy_image_storage(item) for item in value]
    if isinstance(value, tuple):
        return [scrub_legacy_image_storage(item) for item in value]
    return value


def sanitize_image_understanding(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    if not source:
        return {}
    result: dict[str, Any] = {}
    for key in (
        "applied",
        "adoptable",
        "enabled",
        "reason",
        "provider",
        "request_style",
        "model",
        "vision_summary",
        "image_ocr_text",
        "classification",
        "entities",
        "intent_hints",
        "bridge",
        "catalog_alignment",
        "source_messages",
        "local_visual_profile",
        "audit",
    ):
        if key not in source:
            continue
        result[key] = _compact_ledger_json(source.get(key))
    if not str(result.get("vision_summary") or "").strip() and not result.get("classification"):
        return result if result.get("reason") else {}
    return result


def ledger_message_modality(message: dict[str, Any], *, msg_type: str = "") -> str:
    explicit = str(message.get("modality") or "").strip().lower()
    if explicit in {"text", "voice", "image"}:
        return explicit
    if message.get("image_capture_pending") or str(message.get("visual_turn_kind") or "").strip() in {
        "customer_image",
        "self_image",
    }:
        return "image"
    source_type = str(message.get("source_type") or "").strip().lower()
    if source_type == "voice_transcription" or message.get("voice_transcribed") or message.get("voice_transcription_text"):
        return "voice"
    normalized_type = str(msg_type or message.get("type") or message.get("message_type") or "").strip().lower()
    if normalized_type in {"image", "picture", "photo"}:
        return "image"
    return "text"


def sanitize_ledger_message(message: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(message, dict):
        return None
    content = " ".join(str(message.get("content") or "").split()).strip()
    msg_type = str(message.get("type") or "text").strip() or "text"
    if not content and msg_type == "text":
        return None
    if len(content) > MAX_LEDGER_MESSAGE_CHARS:
        content = content[:MAX_LEDGER_MESSAGE_CHARS].rstrip() + "..."
    sender = str(message.get("sender") or message.get("role") or "").strip()
    legacy_message_id = str(message.get("legacy_message_id") or message.get("id") or message.get("message_id") or "").strip()
    canonical_id = canonical_input_message_id(message)
    visual_id = canonical_visual_message_id(message)
    message_id = canonical_id or legacy_message_id
    time_value = str(message.get("time") or message.get("created_at") or "").strip()
    identity = canonical_id or message_id or stable_hash(sender, msg_type, content, time_value, length=24)
    content_key = ledger_message_content_key({**message, "sender": sender, "type": msg_type, "content": content})
    result = {
        "id": message_id,
        "legacy_message_id": legacy_message_id,
        "canonical_input_id": canonical_id,
        "canonical_visual_id": visual_id,
        "identity": identity,
        "sender": sender,
        "type": msg_type,
        "content": content,
        "time": time_value,
        "content_key": content_key,
    }
    sender_role = str(message.get("sender_role") or "").strip()
    if sender_role:
        result["sender_role"] = sender_role
    modality = ledger_message_modality(message, msg_type=msg_type)
    result["modality"] = modality
    source_type = str(message.get("source_type") or "").strip()
    if not source_type:
        if modality == "voice":
            source_type = "voice_transcription"
        elif modality == "image":
            source_type = "visual_capture"
        elif sender in {"assistant", "service", "bot"}:
            source_type = "assistant_reply"
        elif msg_type == "text":
            source_type = "ocr_text"
    if source_type:
        result["source_type"] = source_type
    for key in (
        "pending_signal_id",
        "image_capture_pending",
        "source_message_id",
        "source_message_type",
        "is_customer_image_proxy",
        "visual_turn_kind",
        "speaker_name",
        "group_member_name",
        "source_adapter",
        "voice_source_message_id",
        "voice_transcribed_at",
    ):
        value = message.get(key)
        if isinstance(value, bool):
            result[key] = value
        else:
            text = str(value or "").strip()
            if text:
                result[key] = text
    if message.get("voice_transcribed") or modality == "voice":
        result["voice_transcribed"] = True
        transcript = _clip_ledger_text(
            message.get("voice_transcription_text") or message.get("transcript") or content,
            limit=MAX_LEDGER_MESSAGE_CHARS,
        )
        if transcript:
            result["voice_transcription_text"] = transcript
    quality_flags = [
        _clip_ledger_text(item, limit=120)
        for item in (message.get("quality_flags") or [])
        if _clip_ledger_text(item, limit=120)
    ]
    if quality_flags:
        result["quality_flags"] = list(dict.fromkeys(quality_flags))[:20]
    role_evidence = [
        _clip_ledger_text(item, limit=160)
        for item in (message.get("sender_role_evidence") or [])
        if _clip_ledger_text(item, limit=160)
    ]
    if role_evidence:
        result["sender_role_evidence"] = list(dict.fromkeys(role_evidence))[:20]
    for key in ("sender_role_algorithm", "sender_role_confidence", "ocr_confidence"):
        value = message.get(key)
        if value not in (None, ""):
            result[key] = value
    image_understanding = sanitize_image_understanding(
        message.get("image_understanding")
        or ({"vision_summary": message.get("vision_summary")} if message.get("vision_summary") else {})
    )
    if image_understanding:
        result["image_understanding"] = image_understanding
        vision_summary = _clip_ledger_text(image_understanding.get("vision_summary"), limit=MAX_LEDGER_MESSAGE_CHARS)
        if vision_summary:
            result["vision_summary"] = vision_summary
    return result


def merge_recent_messages(
    existing: list[dict[str, Any]] | None,
    additions: list[dict[str, Any]] | None,
    *,
    limit: int = MAX_LEDGER_RECENT_MESSAGES,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for raw in list(existing or []) + list(additions or []):
        message = sanitize_ledger_message(raw)
        if not message:
            continue
        identity = str(message.get("identity") or message.get("id") or "").strip()
        if not identity:
            identity = stable_hash(message.get("sender"), message.get("type"), message.get("content"), message.get("time"), length=24)
            message["identity"] = identity
        if identity in seen:
            merged[seen[identity]] = message
            continue
        seen[identity] = len(merged)
        merged.append(message)
    return merged[-max(1, int(limit or MAX_LEDGER_RECENT_MESSAGES)) :]


def build_context_summary(messages: list[dict[str, Any]] | None) -> str:
    lines: list[str] = []
    for message in list(messages or [])[-MAX_LEDGER_CONTEXT_LINES:]:
        item = sanitize_ledger_message(message)
        if not item:
            continue
        sender = str(item.get("sender") or "").lower()
        if sender in {"customer", "user", "client"}:
            label = "客户"
        elif sender in {"self", "assistant", "service", "bot"}:
            label = "客服"
        else:
            label = "对话"
        content = str(item.get("content") or "").strip()
        if str(item.get("modality") or "") == "image":
            understanding = item.get("image_understanding") if isinstance(item.get("image_understanding"), dict) else {}
            vision_summary = _clip_ledger_text(
                understanding.get("vision_summary") or item.get("vision_summary"),
                limit=260,
            )
            if vision_summary:
                image_marker = content if content and content not in {"[图片]", "图片"} else "[图片]"
                content = f"{image_marker} 识图: {vision_summary}".strip()
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines[-MAX_LEDGER_CONTEXT_LINES:])


def _ledger_message_reference_values(message: dict[str, Any] | None) -> set[str]:
    source = message if isinstance(message, dict) else {}
    values: set[str] = set()
    for key in (
        "identity",
        "id",
        "message_id",
        "legacy_message_id",
        "canonical_input_id",
        "canonical_visual_id",
        "source_message_id",
        "pending_signal_id",
        "visual_occurrence_id",
    ):
        value = str(source.get(key) or "").strip()
        if value:
            values.add(value)
    return values


class SessionLedgerStore:
    """Append-only per-session ledger plus compact summary files."""

    def __init__(self, *, tenant_id: str | None = None, root: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.root = root or (tenant_runtime_root(self.tenant_id) / "customer_service" / "session_ledgers")

    def session_dir(self, session_key: str) -> Path:
        return self.root / safe_filename(session_key)

    def events_path(self, session_key: str) -> Path:
        return self.session_dir(session_key) / "events.jsonl"

    def summary_path(self, session_key: str) -> Path:
        return self.session_dir(session_key) / "summary.json"

    def load_summary(self, session_key: str) -> dict[str, Any]:
        path = self.summary_path(session_key)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return scrub_legacy_image_storage(data) if isinstance(data, dict) else {}

    def save_summary(self, session_key: str, summary: dict[str, Any]) -> None:
        path = self.summary_path(session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = scrub_legacy_image_storage(dict(summary))
        payload["session_key"] = session_key
        payload["updated_at"] = utcnow_iso()
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def append_event(self, session_key: str, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        safe_payload = scrub_legacy_image_storage(dict(payload))
        event = {
            "event_id": "ledger_" + stable_hash(session_key, event_type, utcnow_iso(), safe_payload, length=24),
            "event_type": event_type,
            "session_key": session_key,
            "created_at": utcnow_iso(),
            **safe_payload,
        }
        path = self.events_path(session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def record_capture(
        self,
        *,
        session_key: str,
        target_name: str,
        conversation_type: str,
        capture_id: str,
        messages: list[dict[str, Any]],
        batch: list[dict[str, Any]],
        history_backfill: dict[str, Any],
        context_version: int,
    ) -> None:
        if not session_key:
            return
        sanitized_messages = [item for item in (sanitize_ledger_message(raw) for raw in messages) if item]
        sanitized_batch = [item for item in (sanitize_ledger_message(raw) for raw in batch) if item]
        # File-backed visual assets are retired.  The event retains the text
        # turn and any later textual understanding, but never an image path,
        # crop identity, image hash, thumbnail, or asset reference.
        visual_assets: list[dict[str, Any]] = []
        message_ids = [
            str(item.get("identity") or item.get("canonical_input_id") or item.get("id") or "")
            for item in sanitized_batch
            if str(item.get("identity") or item.get("canonical_input_id") or item.get("id") or "")
        ]
        self.append_event(
            session_key,
            "capture_recorded",
            {
                "target_name": target_name,
                "conversation_type": conversation_type,
                "capture_id": capture_id,
                "context_version": context_version,
                "message_ids": message_ids,
                "message_count": len(messages),
                "batch_count": len(batch),
                "batch_messages": sanitized_batch[-MAX_LEDGER_EVENT_MESSAGES:],
                "visual_assets": visual_assets,
                "history_continuity": str(history_backfill.get("history_continuity") or ""),
                "history_backfill": history_backfill,
            },
        )
        summary = self.load_summary(session_key)
        recent_messages = merge_recent_messages(
            summary.get("recent_messages") if isinstance(summary.get("recent_messages"), list) else [],
            sanitized_messages,
        )
        summary.update(
            {
                "display_name": target_name,
                "target_name": target_name,
                "conversation_type": conversation_type,
                "last_capture_id": capture_id,
                "last_capture_at": utcnow_iso(),
                "last_captured_message_id": message_ids[-1] if message_ids else summary.get("last_captured_message_id", ""),
                "last_captured_content_keys": [
                    str(item.get("content_key") or "")
                    for item in sanitized_batch
                    if str(item.get("content_key") or "")
                ][-20:],
                "last_unreplied_capture_id": capture_id if sanitized_batch else summary.get("last_unreplied_capture_id", ""),
                "last_unreplied_message_ids": message_ids[-20:] if sanitized_batch else summary.get("last_unreplied_message_ids", []),
                "last_unreplied_content_keys": [
                    str(item.get("content_key") or "")
                    for item in sanitized_batch
                    if str(item.get("content_key") or "")
                ][-20:] if sanitized_batch else summary.get("last_unreplied_content_keys", []),
                "recent_messages": recent_messages,
                "context_summary": build_context_summary(recent_messages),
                "last_history_continuity": str(history_backfill.get("history_continuity") or ""),
                "context_version": int(context_version or 0),
            }
        )
        # A pending image signal is not "processed" merely because its text
        # placeholder was captured.  It is committed only after the current
        # clipboard transaction produced a textual understanding below.
        summary.setdefault("processed_visual_pending_signal_ids", [])
        self.save_summary(session_key, summary)

    def record_multimodal_enrichment(
        self,
        *,
        session_key: str,
        target_name: str,
        capture_id: str = "",
        source: str,
        enrichments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Merge delayed voice/image semantics into already captured messages."""

        if not session_key:
            return {"ok": False, "reason": "session_key_missing", "updated_count": 0}
        summary = self.load_summary(session_key)
        recent_messages = [
            item
            for item in (summary.get("recent_messages") or [])
            if isinstance(item, dict)
        ]
        updated_ids: list[str] = []
        completed_visual_signal_ids: list[str] = []
        event_enrichments: list[dict[str, Any]] = []
        for enrichment in enrichments or []:
            if not isinstance(enrichment, dict):
                continue
            modality = str(enrichment.get("modality") or "").strip().lower()
            references: set[str] = set()
            for ref in enrichment.get("message_refs") or enrichment.get("source_messages") or []:
                if isinstance(ref, dict):
                    references.update(_ledger_message_reference_values(ref))
                else:
                    text = str(ref or "").strip()
                    if text:
                        references.add(text)
            understanding = sanitize_image_understanding(enrichment.get("image_understanding"))
            transcript = _clip_ledger_text(
                enrichment.get("voice_transcription_text") or enrichment.get("transcript"),
                limit=MAX_LEDGER_MESSAGE_CHARS,
            )
            matched = 0
            candidate_indexes: list[int] = []
            for index, message in enumerate(recent_messages):
                if references and not references.intersection(_ledger_message_reference_values(message)):
                    continue
                if modality and ledger_message_modality(message) != modality:
                    continue
                candidate_indexes.append(index)
            if modality == "image":
                raw_image_indexes = [
                    index
                    for index in candidate_indexes
                    if str(recent_messages[index].get("type") or "").strip().lower() in {"image", "picture", "photo"}
                    and not recent_messages[index].get("is_customer_image_proxy")
                ]
                if raw_image_indexes:
                    candidate_indexes = raw_image_indexes
            for index in candidate_indexes:
                message = recent_messages[index]
                next_message = dict(message)
                if modality == "image" and understanding:
                    next_message["modality"] = "image"
                    next_message["source_type"] = str(next_message.get("source_type") or "visual_capture")
                    next_message["image_understanding"] = understanding
                    if understanding.get("vision_summary"):
                        next_message["vision_summary"] = understanding.get("vision_summary")
                elif modality == "voice" and transcript:
                    next_message["modality"] = "voice"
                    next_message["source_type"] = "voice_transcription"
                    next_message["voice_transcribed"] = True
                    next_message["voice_transcription_text"] = transcript
                    next_message["voice_transcribed_at"] = str(
                        enrichment.get("voice_transcribed_at") or utcnow_iso()
                    )
                    if not str(next_message.get("content") or "").strip():
                        next_message["content"] = transcript
                else:
                    continue
                sanitized = sanitize_ledger_message(next_message)
                if not sanitized:
                    continue
                recent_messages[index] = sanitized
                matched += 1
                identity = str(sanitized.get("identity") or sanitized.get("id") or "").strip()
                if identity and identity not in updated_ids:
                    updated_ids.append(identity)
                if modality == "image" and str(understanding.get("vision_summary") or "").strip():
                    signal_id = str(sanitized.get("pending_signal_id") or "").strip()
                    if signal_id and signal_id not in completed_visual_signal_ids:
                        completed_visual_signal_ids.append(signal_id)
            event_enrichments.append(
                {
                    "modality": modality,
                    "references": sorted(references)[:20],
                    "matched_count": matched,
                    "vision_summary": _clip_ledger_text(understanding.get("vision_summary"), limit=300),
                    "voice_transcription_text": transcript,
                    "reason": str(understanding.get("reason") or enrichment.get("reason") or ""),
                }
            )
        if updated_ids:
            summary["recent_messages"] = recent_messages[-MAX_LEDGER_RECENT_MESSAGES:]
            summary["context_summary"] = build_context_summary(summary["recent_messages"])
            summary["last_multimodal_enrichment_at"] = utcnow_iso()
            summary["last_multimodal_enrichment_source"] = str(source or "")
            previous_visual_signal_ids = [
                str(item or "").strip()
                for item in summary.get("processed_visual_pending_signal_ids") or []
                if str(item or "").strip()
            ]
            summary["processed_visual_pending_signal_ids"] = list(
                dict.fromkeys(previous_visual_signal_ids + completed_visual_signal_ids)
            )[-500:]
            self.save_summary(session_key, summary)
        event = self.append_event(
            session_key,
            "multimodal_context_enriched",
            {
                "target_name": target_name,
                "capture_id": capture_id,
                "source": str(source or ""),
                "updated_message_ids": updated_ids,
                "updated_count": len(updated_ids),
                "enrichments": event_enrichments[:MAX_LEDGER_EVENT_MESSAGES],
            },
        )
        return {
            "ok": True,
            "updated_count": len(updated_ids),
            "updated_message_ids": updated_ids,
            "event_id": event.get("event_id"),
        }

    def merge_session_alias_context(
        self,
        *,
        canonical_session_key: str,
        alias_session_keys: list[str],
        target_name: str,
    ) -> dict[str, Any]:
        """Merge context from inferred-type aliases after unique-name repair."""

        aliases = [
            str(item or "").strip()
            for item in alias_session_keys or []
            if str(item or "").strip() and str(item or "").strip() != canonical_session_key
        ]
        if not canonical_session_key or not aliases:
            return {"ok": True, "merged_alias_count": 0, "recent_message_count": 0}
        canonical = self.load_summary(canonical_session_key)
        recent = canonical.get("recent_messages") if isinstance(canonical.get("recent_messages"), list) else []
        alias_summaries: list[tuple[str, dict[str, Any]]] = []
        for alias_key in aliases:
            summary = self.load_summary(alias_key)
            if isinstance(summary, dict) and summary:
                alias_summaries.append((alias_key, summary))
        alias_summaries.sort(
            key=lambda item: str(item[1].get("last_capture_at") or item[1].get("updated_at") or "")
        )
        merged_aliases: list[str] = []
        for alias_key, summary in alias_summaries:
            additions = summary.get("recent_messages") if isinstance(summary.get("recent_messages"), list) else []
            if additions:
                recent = merge_recent_messages(recent, additions)
                merged_aliases.append(alias_key)
        if not merged_aliases:
            return {"ok": True, "merged_alias_count": 0, "recent_message_count": len(recent)}
        canonical.update(
            {
                "display_name": target_name or canonical.get("display_name") or "",
                "target_name": target_name or canonical.get("target_name") or "",
                "recent_messages": recent,
                "context_summary": build_context_summary(recent),
                "merged_session_aliases": list(
                    dict.fromkeys([*(canonical.get("merged_session_aliases") or []), *merged_aliases])
                )[-20:],
                "last_session_alias_merge_at": utcnow_iso(),
            }
        )
        self.save_summary(canonical_session_key, canonical)
        event = self.append_event(
            canonical_session_key,
            "session_alias_context_merged",
            {
                "target_name": target_name,
                "alias_session_keys": merged_aliases,
                "merged_alias_count": len(merged_aliases),
                "recent_message_count": len(recent),
            },
        )
        return {
            "ok": True,
            "merged_alias_count": len(merged_aliases),
            "recent_message_count": len(recent),
            "event_id": event.get("event_id"),
        }

    def record_reply_sent(
        self,
        *,
        session_key: str,
        target_name: str,
        reply_id: str,
        input_message_ids: list[str],
        input_content_keys: list[str] | None = None,
        reply_text: str,
        send_result: dict[str, Any] | None = None,
    ) -> None:
        if not session_key:
            return
        reply_message = sanitize_ledger_message(
            {
                "id": reply_id,
                "sender": "assistant",
                "type": "text",
                "content": reply_text,
                "time": utcnow_iso(),
            }
        )
        self.append_event(
            session_key,
            "reply_sent",
            {
                "target_name": target_name,
                "reply_id": reply_id,
                "input_message_ids": list(input_message_ids or []),
                "input_content_keys": list(input_content_keys or []),
                "reply_message": reply_message or {},
                "reply_digest": stable_hash(reply_text, length=24) if reply_text else "",
                "send_ok": bool((send_result or {}).get("ok", True)),
            },
        )
        summary = self.load_summary(session_key)
        recent_messages = merge_recent_messages(
            summary.get("recent_messages") if isinstance(summary.get("recent_messages"), list) else [],
            [reply_message] if reply_message else [],
        )
        summary.update(
            {
                "display_name": target_name,
                "target_name": target_name,
                "last_reply_at": utcnow_iso(),
                "last_processed_message_id": (input_message_ids or [""])[-1],
                "last_processed_content_keys": list(input_content_keys or [])[-20:],
                "last_replied_message_id": (input_message_ids or [""])[-1],
                "last_successful_reply_digest": stable_hash(reply_text, length=24) if reply_text else "",
                "last_reply_id": reply_id,
                "last_unreplied_capture_id": "",
                "last_unreplied_message_ids": [],
                "last_unreplied_content_keys": [],
                "recent_messages": recent_messages,
                "context_summary": build_context_summary(recent_messages),
                "last_successful_reply_anchor": {
                    "message_ids": list(input_message_ids or [])[-20:],
                    "message_content_keys": list(input_content_keys or [])[-20:],
                    "reply_content_key": stable_hash(reply_text, length=24) if reply_text else "",
                    "reply_text_sample": str(reply_text or "").strip()[:160],
                    "processed_at": utcnow_iso(),
                    "send_verified": bool((send_result or {}).get("verified", (send_result or {}).get("ok", True))),
                },
            }
        )
        self.save_summary(session_key, summary)
