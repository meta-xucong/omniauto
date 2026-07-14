"""Retired image-asset compatibility facade.

Customer-service vision has one supported acquisition route only: the
target-validated right-click Copy operation followed by an in-memory read of
the freshly changed Windows clipboard.  This module deliberately contains no
file, screenshot, crop, thumbnail, archive, or image-save implementation.

The old import paths remain as fail-closed compatibility facades so external
callers cannot silently revive a historical image-reading route.
"""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "customer_image_understanding"
_IMAGE_PREVIEW_MARKERS = ("[图片]", "[image]", "图片", "image")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sanitize_name(value: str) -> str:
    keep = [char if char.isalnum() else "_" for char in str(value or "").strip()]
    compact = "".join(keep).strip("_")
    return compact or "target"


def visual_artifact_dir(*, target_name: str, session_key: str = "") -> Path:
    """Compatibility-only path calculation; callers must not create or use it."""

    return RUNTIME_ROOT / sanitize_name(session_key or target_name)


def image_preview_text(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and any(marker in text for marker in _IMAGE_PREVIEW_MARKERS))


def parse_preview_speaker(source_preview: str, explicit_speaker: str = "") -> str:
    explicit = str(explicit_speaker or "").strip()
    if explicit:
        return explicit
    text = str(source_preview or "").strip()
    for separator in (":", "："):
        if separator in text:
            candidate = text.split(separator, 1)[0].strip()
            if candidate and not image_preview_text(candidate):
                return candidate
    return ""


def _image_pending_signal(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    preview = str(source.get("pending_signal_text") or source.get("preview_content") or source.get("content") or "").strip()
    if not image_preview_text(preview) and str(source.get("pending_signal_kind") or "").strip().lower() not in {
        "image_capture",
        "media_capture",
    }:
        return {}
    return source


def target_state_image_pending_signal(target_state: dict[str, Any] | None) -> dict[str, Any]:
    state = target_state if isinstance(target_state, dict) else {}
    for key in (
        "pending_signal",
        "latest_pending_signal",
        "session_monitor_pending_signal",
        "_session_monitor_pending_signal",
    ):
        signal = _image_pending_signal(state.get(key))
        if signal:
            return copy.deepcopy(signal)
    signal = _image_pending_signal(state)
    return copy.deepcopy(signal) if signal else {}


def payload_image_pending_signal(
    payload: dict[str, Any] | None,
    target_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    for key in ("pending_signal", "session_monitor_pending_signal", "_session_monitor_pending_signal"):
        signal = _image_pending_signal(source.get(key))
        if signal:
            return copy.deepcopy(signal)
    return target_state_image_pending_signal(target_state)


def build_brain_safe_image_proxy_message(
    source: dict[str, Any] | None,
    *,
    target_name: str = "",
    session_key: str = "",
    content: str = "",
) -> dict[str, Any]:
    """Build text-only image context; never attach a file or image payload."""

    item = source if isinstance(source, dict) else {}
    pending_signal = _image_pending_signal(item) or _image_pending_signal(item.get("pending_signal"))
    pending_signal_id = str(
        item.get("pending_signal_id")
        or pending_signal.get("pending_signal_id")
        or item.get("source_message_id")
        or item.get("message_id")
        or item.get("id")
        or ""
    ).strip()
    message_id = pending_signal_id or f"clipboard_image_pending:{sanitize_name(session_key or target_name)}"
    source_preview = str(
        item.get("content")
        or item.get("source_preview")
        or pending_signal.get("pending_signal_text")
        or pending_signal.get("preview_content")
        or "[图片]"
    ).strip()
    speaker_name = parse_preview_speaker(
        source_preview,
        str(item.get("speaker_name") or item.get("group_member_name") or pending_signal.get("speaker_name") or ""),
    )
    proxy_content = str(content or "").strip() or "客户发送了一张图片"
    return {
        "id": f"clipboard_image_pending:{message_id}",
        "message_id": f"clipboard_image_pending:{message_id}",
        "source_message_id": message_id,
        "type": "image",
        "message_type": "image",
        "sender": "customer",
        "sender_role": "customer",
        "content": proxy_content,
        "original_content": source_preview,
        "target_name": str(target_name or item.get("target_name") or ""),
        "session_key": str(session_key or item.get("session_key") or pending_signal.get("session_key") or ""),
        "speaker_name": speaker_name,
        "group_member_name": speaker_name,
        "is_customer_image_proxy": True,
        "visual_turn_kind": "customer_image",
        "image_capture_pending": True,
        "pending_signal_id": pending_signal_id,
        "pending_signal_kind": "image_capture",
        "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
        "source": "clipboard_current_transaction",
    }


def build_brain_safe_image_proxy_messages(
    sources: list[dict[str, Any]] | None,
    *,
    target_name: str = "",
    session_key: str = "",
    content: str = "",
) -> list[dict[str, Any]]:
    return [
        build_brain_safe_image_proxy_message(
            source,
            target_name=target_name,
            session_key=session_key,
            content=content,
        )
        for source in (sources or [])
        if isinstance(source, dict)
    ]


def assets_from_payload_messages(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Historical asset payloads are intentionally unreadable."""

    del payload
    return []


def customer_scoped_image_asset(asset: dict[str, Any] | None) -> bool:
    del asset
    return False


def _legacy_image_read_rejected(reason: str = "legacy_image_reading_retired") -> dict[str, Any]:
    return {
        "ok": False,
        "applied": False,
        "reason": reason,
        "assets": [],
        "messages": [],
        "source": "clipboard_current_transaction_required",
    }


def call_image_save_sidecar(
    connector: Any,
    *,
    target_name: str,
    exact: bool = True,
    session_key: str = "",
    artifact_dir: str | Path | None = None,
    pending_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del connector, target_name, exact, session_key, artifact_dir, pending_signal
    return _legacy_image_read_rejected("legacy_image_save_retired")


def capture_messages_with_artifact(
    connector: Any,
    *,
    target_name: str,
    exact: bool = True,
    session_key: str = "",
    artifact_dir: str | Path | None = None,
) -> dict[str, Any]:
    del connector, target_name, exact, session_key, artifact_dir
    return _legacy_image_read_rejected("legacy_image_capture_retired")


def detect_customer_image_region(screenshot_path: str, messages: list[dict[str, Any]] | None) -> dict[str, Any]:
    del screenshot_path, messages
    return _legacy_image_read_rejected("legacy_image_crop_detection_rejected")


def maybe_collect_customer_image_assets(
    connector: Any,
    *,
    target_name: str,
    exact: bool = True,
    session_key: str = "",
    payload: dict[str, Any] | None = None,
    target_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Hard reject all screenshot/path/archive image collection routes."""

    del connector, target_name, exact, session_key, payload, target_state
    return _legacy_image_read_rejected("legacy_image_asset_storage_rejected")
