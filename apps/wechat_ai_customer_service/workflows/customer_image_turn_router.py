from __future__ import annotations

import copy
from typing import Any

from apps.wechat_ai_customer_service.workflows.customer_image_brain_bridge import (
    build_customer_image_brain_bridge,
)
from apps.wechat_ai_customer_service.workflows.customer_image_catalog_assist import (
    build_customer_image_catalog_assist,
)
from apps.wechat_ai_customer_service.workflows.customer_image_understanding import (
    maybe_run_customer_image_understanding,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.clipboard_payload import (
    read_current_clipboard_image,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.trigger import image_preview_text
from apps.wechat_ai_customer_service.optional_plugins.vision.trigger import (
    pending_image_signal_was_processed,
)


def customer_image_capture_trigger(
    *,
    payload: dict[str, Any] | None,
    pending_signal: dict[str, Any] | None = None,
    pending_signal_kind: str = "",
    target_state: dict[str, Any] | None = None,
    recent_message_limit: int = 6,
) -> dict[str, Any]:
    """Decide whether the independent image module should be invoked.

    This is intentionally a cheap metadata-only gate. It never opens WeChat,
    reads the clipboard, calls OCR, or calls an LLM. The scheduler uses it to
    keep ordinary text captures out of the image RPA path while still allowing
    image signals and recent image bubbles to enter the existing image router.
    """

    from apps.wechat_ai_customer_service.optional_plugins.vision.trigger import (
        customer_image_capture_trigger as trigger,
    )

    return trigger(
        payload=payload,
        pending_signal=pending_signal,
        pending_signal_kind=pending_signal_kind,
        target_state=target_state,
        recent_message_limit=recent_message_limit,
    )


def _current_image_pending_signal(
    payload: dict[str, Any] | None,
    target_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return only a currently pending image signal; never inspect old assets."""
    source = payload if isinstance(payload, dict) else {}
    for container in (source, target_state if isinstance(target_state, dict) else {}):
        for key in ("pending_signal", "session_monitor_pending_signal", "_session_monitor_pending_signal"):
            signal = container.get(key) if isinstance(container, dict) else None
            if not isinstance(signal, dict):
                continue
            kind = str(signal.get("pending_signal_kind") or "").strip().lower()
            text = str(signal.get("pending_signal_text") or signal.get("preview_content") or "").strip()
            if kind in {"image_capture", "media_capture"} or image_preview_text(text):
                return dict(signal)
    return {}


def _public_clipboard_transaction(value: dict[str, Any] | None) -> dict[str, Any]:
    transaction = value if isinstance(value, dict) else {}
    return {
        "source": "clipboard_current_transaction",
        "status": str(transaction.get("status") or ""),
        "captured_at": str(transaction.get("captured_at") or ""),
        "right_click_ok": bool(transaction.get("right_click_ok", False)),
        "menu_copy_confirmed": bool(transaction.get("menu_copy_confirmed", False)),
        "clipboard_sequence_changed": bool(transaction.get("clipboard_sequence_changed", False)),
        "clipboard_content_read": bool(transaction.get("clipboard_content_read", False)),
        "clipboard_image_valid": bool(transaction.get("clipboard_image_valid", False)),
    }


def _self_image_context_candidate(messages: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Return the newest explicit self-side image envelope, never a file asset."""

    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
        visual_side = str(message.get("visual_side") or "").strip().lower()
        if sender not in {"self", "assistant", "service", "bot", "outbound"} and visual_side != "self":
            continue
        message_type = str(message.get("type") or message.get("message_type") or "").strip().lower()
        content = str(message.get("content") or "").strip()
        explicit_visual = bool(message.get("is_self_image") or message.get("is_visual_image"))
        if message_type not in {"image", "picture", "photo"} and not (
            visual_side == "self" and (explicit_visual or image_preview_text(content))
        ):
            continue
        source_message_id = str(
            message.get("message_id")
            or message.get("id")
            or message.get("source_message_id")
            or ""
        ).strip()
        if source_message_id:
            return {**message, "source_message_id": source_message_id}
    return {}


def _self_image_context_was_recorded(target_state: dict[str, Any] | None, source_message_id: str) -> bool:
    state = target_state if isinstance(target_state, dict) else {}
    clean_id = str(source_message_id or "").strip()
    if not clean_id:
        return False
    context = state.get("conversation_context") if isinstance(state.get("conversation_context"), dict) else {}
    sources: list[Any] = []
    for container in (state, context):
        for key in ("ledger_recent_messages", "recent_messages", "visual_recent_messages"):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, list):
                sources.extend(value)
    for message in sources:
        if not isinstance(message, dict):
            continue
        message_ids = {
            str(message.get(key) or "").strip()
            for key in ("id", "message_id", "source_message_id", "identity")
        }
        sender = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
        understanding = message.get("image_understanding") if isinstance(message.get("image_understanding"), dict) else {}
        if clean_id in message_ids and sender in {"self", "assistant", "service", "bot", "outbound"} and understanding:
            return True
    return False


def maybe_capture_self_image_context(
    *,
    connector: Any,
    target: Any,
    config: dict[str, Any],
    messages: list[dict[str, Any]],
    target_state: dict[str, Any],
    combined: str = "",
) -> dict[str, Any]:
    """Understand a self image as durable conversation context, never a reply turn."""

    candidate = _self_image_context_candidate(messages)
    if not candidate:
        return {"enabled": True, "applied": False, "context_only": True, "reason": "self_image_context_missing"}
    source_message_id = str(candidate.get("source_message_id") or "").strip()
    if _self_image_context_was_recorded(target_state, source_message_id):
        return {"enabled": True, "applied": False, "context_only": True, "reason": "self_image_context_already_recorded"}
    transaction_runner = getattr(connector, "run_self_clipboard_image_transaction", None)
    if not callable(transaction_runner):
        return {"enabled": True, "applied": False, "context_only": True, "reason": "self_clipboard_current_transaction_unsupported"}
    transaction_result = transaction_runner(
        str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        source_preview=str(candidate.get("content") or ""),
        pending_signal_id=source_message_id,
        consume_current_clipboard=read_current_clipboard_image,
    )
    transaction_result = transaction_result if isinstance(transaction_result, dict) else {}
    ephemeral_image = transaction_result.pop("_ephemeral_clipboard_image", None)
    public_transaction = _public_clipboard_transaction(
        transaction_result.get("transaction") if isinstance(transaction_result, dict) else {}
    )
    if not transaction_result.get("ok") or ephemeral_image is None:
        return {
            "enabled": True,
            "applied": False,
            "context_only": True,
            "reason": str(transaction_result.get("reason") or transaction_result.get("state") or "self_clipboard_current_transaction_failed"),
            "clipboard_transaction": public_transaction,
        }
    try:
        understanding = maybe_run_customer_image_understanding(
            config=config,
            customer_text=str(combined or "").strip() or "客服发送了一张图片",
            image_assets=[{"message_id": source_message_id, "message_type": "image", "source": "clipboard_current_transaction"}],
            source_reason="self_clipboard_current_transaction",
            image_payloads=[ephemeral_image],
            ephemeral_clipboard=True,
        )
    finally:
        releaser = getattr(ephemeral_image, "release", None)
        if callable(releaser):
            releaser()
    return {
        "enabled": True,
        "applied": bool(understanding.get("applied") or understanding.get("vision_summary")),
        "context_only": True,
        "reason": str(understanding.get("reason") or "self_image_context_ready"),
        "clipboard_transaction": public_transaction,
        "image_understanding": understanding,
        "enrichment": {
            "modality": "image",
            "message_refs": [{"message_id": source_message_id}],
            "image_understanding": understanding,
            "reason": "self_clipboard_current_transaction",
        },
    }


def maybe_route_customer_image_turn(
    *,
    connector: Any,
    target: Any,
    config: dict[str, Any],
    payload: dict[str, Any],
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
) -> dict[str, Any]:
    image_pending_signal = _current_image_pending_signal(payload, target_state)
    if not image_pending_signal:
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "current_image_pending_signal_missing",
        }
    pending_signal_id = str(image_pending_signal.get("pending_signal_id") or "").strip()
    if pending_signal_id and pending_image_signal_was_processed(target_state, pending_signal_id):
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "pending_image_signal_already_processed",
        }
    transaction_runner = getattr(connector, "run_customer_clipboard_image_transaction", None)
    if not callable(transaction_runner):
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "clipboard_current_transaction_unsupported",
        }
    transaction_result = transaction_runner(
        str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        source_preview=str(image_pending_signal.get("pending_signal_text") or image_pending_signal.get("preview_content") or ""),
        speaker_name=str(image_pending_signal.get("speaker_name") or image_pending_signal.get("group_member_name") or ""),
        pending_signal_id=pending_signal_id,
        consume_current_clipboard=read_current_clipboard_image,
    )
    transaction_result = transaction_result if isinstance(transaction_result, dict) else {}
    ephemeral_image = transaction_result.pop("_ephemeral_clipboard_image", None)
    public_transaction = _public_clipboard_transaction(
        transaction_result.get("transaction") if isinstance(transaction_result, dict) else {}
    )
    if not transaction_result.get("ok") or ephemeral_image is None:
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": str(transaction_result.get("reason") or transaction_result.get("state") or "clipboard_current_transaction_failed"),
            "clipboard_transaction": public_transaction,
        }
    source_reason = "clipboard_current_transaction"
    source_message_id = pending_signal_id or f"clipboard_image:{str(getattr(target, 'session_key', '') or target.name or 'target')}"
    image_assets = [{
        "message_id": source_message_id,
        "message_type": "image",
        "source": "clipboard_current_transaction",
    }]
    try:
        understanding = maybe_run_customer_image_understanding(
            config=config,
            customer_text=combined,
            image_assets=image_assets,
            source_reason=source_reason,
            image_payloads=[ephemeral_image],
            ephemeral_clipboard=True,
        )
    finally:
        releaser = getattr(ephemeral_image, "release", None)
        if callable(releaser):
            releaser()
    catalog_assist = build_customer_image_catalog_assist(
        understanding=understanding,
        customer_text=combined,
        target_state=target_state,
    )
    visual_bridge_input = build_customer_image_brain_bridge(
        understanding,
        catalog_assist,
        source_reason=source_reason,
    )
    target_state_for_brain = copy.deepcopy(target_state)
    conversation_context = target_state_for_brain.setdefault("conversation_context", {})
    if isinstance(conversation_context, dict):
        conversation_context.update(catalog_assist.get("conversation_context_patch") or {})
    visual_context_state = target_state_for_brain.setdefault("visual_context_state", {})
    visual_context_patch = {
        "last_visual_bridge_input": visual_bridge_input,
        "last_visual_reason": understanding.get("reason"),
        "last_visual_summary": understanding.get("vision_summary"),
        "last_visual_updated_at": (visual_bridge_input.get("conversation_visual_context") or {}).get("updated_at", ""),
    }
    if isinstance(visual_context_state, dict):
        visual_context_state.update(visual_context_patch)
    proxy_batch = [
        {
            "id": f"visual_proxy:{source_message_id}",
            "message_id": f"visual_proxy:{source_message_id}",
            "type": "text",
            "sender": "customer",
            "sender_role": "customer",
            "content": str(combined or "").strip() or "客户发来了一张图片",
            "pending_signal_id": pending_signal_id,
            "visual_turn_kind": "customer_image",
            "is_customer_image_proxy": True,
            "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction"],
        }
    ]
    return {
        "enabled": True,
        "applied": True,
        "adoptable": True,
        "reason": "customer_image_turn_ready",
        "source_reason": source_reason,
        "customer_image_assets": {
            "ok": True,
            "state": "clipboard_vision_text_ready",
            "assets": [],
            "messages": [],
            "transaction": public_transaction,
        },
        "clipboard_transaction": public_transaction,
        "customer_image_understanding": understanding,
        "customer_image_catalog_assist": catalog_assist,
        "visual_bridge_input": visual_bridge_input,
        "target_state_for_brain": target_state_for_brain,
        "conversation_context_patch": dict(catalog_assist.get("conversation_context_patch") or {}),
        "visual_context_state_patch": visual_context_patch,
        "combined_text_override": str(combined or "").strip() or "客户发来了一张图片",
        "proxy_batch": proxy_batch,
    }
