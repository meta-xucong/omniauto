from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def voice_message_merge_key(message: dict[str, Any]) -> str:
    if not isinstance(message, dict):
        return ""
    identity = str(message.get("message_id") or message.get("id") or "").strip()
    if identity:
        return f"id:{identity}"
    content = re.sub(r"\s+", "", str(message.get("content") or "")).strip().lower()
    sender = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
    msg_type = str(message.get("type") or "text").strip().lower()
    return f"content:{sender}:{msg_type}:{content}" if content else ""


def voice_transcription_envelope(
    message: dict[str, Any],
    *,
    merged_from_sidecar: bool,
) -> dict[str, Any]:
    merged = dict(message)
    content = " ".join(str(merged.get("content") or "").split()).strip()
    merged.setdefault("type", "text")
    merged["modality"] = "voice"
    merged["source_type"] = "voice_transcription"
    merged["voice_transcribed"] = True
    merged["voice_transcription_text"] = content
    merged.setdefault(
        "voice_source_message_id",
        str(
            merged.get("source_message_id")
            or merged.get("message_id")
            or merged.get("id")
            or ""
        ),
    )
    merged.setdefault("voice_transcribed_at", datetime.now().isoformat(timespec="seconds"))
    flags = [str(item) for item in (merged.get("quality_flags") or []) if str(item)]
    if merged_from_sidecar and "voice_transcription_merged_from_sidecar" not in flags:
        flags.append("voice_transcription_merged_from_sidecar")
    merged["quality_flags"] = flags
    return merged


def voice_transcription_audit_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        if (
            str(item.get("source_type") or "").strip() != "voice_transcription"
            and not item.get("voice_transcribed")
        ):
            continue
        content = " ".join(
            str(item.get("voice_transcription_text") or item.get("content") or "").split()
        ).strip()
        if not content:
            continue
        result.append(
            {
                "id": str(item.get("id") or item.get("message_id") or ""),
                "sender": str(item.get("sender") or ""),
                "sender_role": str(item.get("sender_role") or ""),
                "content": content[:600],
                "source_type": "voice_transcription",
                "modality": "voice",
                "voice_transcribed_at": str(item.get("voice_transcribed_at") or ""),
            }
        )
    return result[-20:]


def merge_voice_transcription_messages(
    payload: dict[str, Any],
    voice_transcription: dict[str, Any],
) -> dict[str, Any]:
    """Merge voice-to-text messages when the follow-up OCR read misses them."""

    if not isinstance(payload, dict) or not isinstance(voice_transcription, dict):
        return payload
    if not voice_transcription.get("attempted"):
        return payload
    voice_messages = [
        item
        for item in (
            voice_transcription.get("new_messages")
            or voice_transcription.get("transcribed_messages")
            or []
        )
        if isinstance(item, dict)
        and str(item.get("content") or "").strip()
        and str(item.get("type") or "text").strip().lower() == "text"
    ]
    if not voice_messages:
        return payload
    messages = [item for item in (payload.get("messages") or []) if isinstance(item, dict)]
    existing_indexes = {
        voice_message_merge_key(item): index
        for index, item in enumerate(messages)
        if voice_message_merge_key(item)
    }
    appended: list[dict[str, Any]] = []
    annotated_count = 0
    for item in voice_messages:
        key = voice_message_merge_key(item)
        if key and key in existing_indexes:
            existing_index = existing_indexes[key]
            existing = dict(messages[existing_index])
            source = voice_transcription_envelope(item, merged_from_sidecar=True)
            for field in (
                "modality",
                "source_type",
                "voice_transcribed",
                "voice_transcription_text",
                "voice_source_message_id",
                "voice_transcribed_at",
            ):
                existing[field] = source.get(field)
            flags = [str(value) for value in (existing.get("quality_flags") or []) if str(value)]
            for value in source.get("quality_flags") or []:
                if value not in flags:
                    flags.append(value)
            existing["quality_flags"] = flags
            messages[existing_index] = existing
            annotated_count += 1
            continue
        merged = voice_transcription_envelope(item, merged_from_sidecar=True)
        appended.append(merged)
        if key:
            existing_indexes[key] = len(messages) + len(appended) - 1
    if appended or annotated_count:
        payload["messages"] = [*messages, *appended]
        payload["voice_transcription_merge"] = {
            "appended_count": len(appended),
            "annotated_existing_count": annotated_count,
            "source_state": voice_transcription.get("state"),
        }
    return payload
