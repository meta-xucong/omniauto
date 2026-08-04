from __future__ import annotations

import copy
from typing import Any

from .projection.context import merge_conversation_context_patch
from .projection.brain import (
    build_customer_image_brain_bridge,
)
from .projection.catalog import (
    build_customer_image_catalog_assist,
)
from .understanding.service import (
    maybe_run_customer_image_understanding,
)
from .clipboard_payload import (
    read_current_clipboard_image,
)
from .capture.wechat import DEFAULT_MAX_VISIBLE_IMAGE_CANDIDATES
from .trigger import image_preview_text
from .trigger import (
    pending_image_signal_was_processed,
)


class _VisionEvidenceUnavailable(RuntimeError):
    """Private Vision fail-stop used before Brain receives a required image turn."""


def _run_current_clipboard_image_transaction(
    *,
    connector: Any,
    target: str,
    exact: bool,
    session_key: str,
    source_preview: str,
    speaker_name: str = "",
    pending_signal_id: str = "",
    side_filter: str,
) -> dict[str, Any]:
    """Call the Vision-owned WeChat binding, never a Connector image facade."""

    from .integrations.wechat_current import run_clipboard_image_transaction

    return run_clipboard_image_transaction(
        connector,
        target,
        exact=exact,
        session_key=session_key,
        source_preview=source_preview,
        speaker_name=speaker_name,
        pending_signal_id=pending_signal_id,
        side_filter=side_filter,
        consume_current_clipboard=read_current_clipboard_image,
    )


def _run_current_visual_group_acquire(
    *,
    connector: Any,
    target: str,
    exact: bool,
    session_key: str,
    conversation_type: str,
    explicit_image_pending: bool,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    max_images: int = 3,
    max_scroll_steps: int | None = None,
    max_snapshots: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    """Acquire the current customer visual group through the Vision private worker."""

    from .integrations.wechat_current import _acquire_current_visual_group

    return _acquire_current_visual_group(
        connector,
        target,
        exact=exact,
        session_key=session_key,
        conversation_type=conversation_type,
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        max_images=max_images,
        max_scroll_steps=max_scroll_steps,
        max_snapshots=max_snapshots,
        max_seconds=max_seconds,
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

    def pending_signals(container: dict[str, Any]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for key in ("pending_signal", "session_monitor_pending_signal", "_session_monitor_pending_signal"):
            signal = container.get(key) if isinstance(container, dict) else None
            if isinstance(signal, dict):
                signals.append(signal)
        return signals

    payload_signals = pending_signals(source)
    signal_sources = payload_signals or pending_signals(target_state if isinstance(target_state, dict) else {})
    for signal in signal_sources:
        kind = str(signal.get("pending_signal_kind") or "").strip().lower()
        text = str(signal.get("pending_signal_text") or signal.get("preview_content") or "").strip()
        if kind in {"image_capture", "media_capture"} or image_preview_text(text):
            return dict(signal)
    # Phase-one structural recovery: the sidebar may already show the text
    # sent immediately after an image.  The scheduler-confirmed customer
    # occurrence is still bound to that same pending signal id, so accept the
    # existing normal signal without changing its kind or outer contract.
    occurrence_signal_id = ""
    for message in reversed(source.get("messages") or []):
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("type") or message.get("message_type") or "").strip().lower()
        side = str(
            message.get("visual_side")
            or message.get("sender")
            or message.get("sender_role")
            or ""
        ).strip().lower()
        if (
            message_type in {"image", "picture", "photo"}
            and side == "customer"
            and str(message.get("source_adapter") or "").strip()
            == "win32_ocr_structural_image_observer"
        ):
            occurrence_signal_id = str(message.get("pending_signal_id") or "").strip()
            if occurrence_signal_id:
                break
    if occurrence_signal_id:
        for signal in signal_sources:
            signal_id = str(signal.get("pending_signal_id") or "").strip()
            if signal_id and signal_id != occurrence_signal_id:
                continue
            recovered = dict(signal)
            recovered["pending_signal_id"] = occurrence_signal_id
            return recovered
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


def _is_customer_image_proxy(message: dict[str, Any]) -> bool:
    if not isinstance(message, dict):
        return False
    side = str(
        message.get("visual_side")
        or message.get("sender")
        or message.get("sender_role")
        or ""
    ).strip().lower()
    return (
        bool(message.get("is_customer_image_proxy"))
        and str(message.get("visual_turn_kind") or "").strip() == "customer_image"
        and side in {"", "customer"}
    )


def _current_customer_image_proxy(
    payload: dict[str, Any] | None,
    batch: list[dict[str, Any]] | None,
    pending_signal_id: str = "",
    *,
    batch_only: bool = False,
) -> dict[str, Any]:
    """Return an already-selected current-turn image proxy, never a history asset."""

    clean_signal_id = str(pending_signal_id or "").strip()
    sources: list[Any] = [batch or []]
    if not batch_only:
        source = payload if isinstance(payload, dict) else {}
        sources.append(source.get("messages") or [])
    for messages in sources:
        if not isinstance(messages, list):
            continue
        for message in reversed(messages):
            if not isinstance(message, dict) or not _is_customer_image_proxy(message):
                continue
            message_signal_id = str(message.get("pending_signal_id") or "").strip()
            if clean_signal_id and message_signal_id != clean_signal_id:
                continue
            if clean_signal_id or message_signal_id:
                return dict(message)
    return {}


def _clean_text_anchor(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _customer_text_anchor_from_batch(batch: list[dict[str, Any]] | None) -> tuple[str, str]:
    for message in batch or []:
        if not isinstance(message, dict) or _is_customer_image_proxy(message):
            continue
        sender = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
        if sender != "customer":
            continue
        content = _clean_text_anchor(message.get("content") or message.get("text") or "")
        if not content:
            continue
        message_id = str(message.get("message_id") or message.get("id") or "").strip()
        return content, message_id
    return "", ""


def _release_ephemeral_images(images: list[Any]) -> None:
    for image in images:
        releaser = getattr(image, "release", None)
        if callable(releaser):
            releaser()


def _understanding_has_required_visual_result(understanding: dict[str, Any]) -> bool:
    if not isinstance(understanding, dict):
        return False
    return (
        understanding.get("applied") is True
        and understanding.get("adoptable") is True
        and bool(str(understanding.get("vision_summary") or "").strip())
    )


def _image_assets_for_group(
    *,
    image_count: int,
    source_message_id: str,
    acquired_messages: list[Any],
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    fallback_source_id = str(source_message_id or "clipboard_image").strip() or "clipboard_image"
    for index in range(image_count):
        acquired = acquired_messages[index] if index < len(acquired_messages) and isinstance(acquired_messages[index], dict) else {}
        message_id = str(
            acquired.get("message_id")
            or acquired.get("id")
            or acquired.get("source_message_id")
            or ""
        ).strip()
        if not message_id:
            message_id = fallback_source_id if image_count == 1 else f"{fallback_source_id}:image:{index + 1}"
        assets.append(
            {
                "message_id": message_id,
                "message_type": "image",
                "source": "clipboard_current_transaction",
            }
        )
    return assets


def _confirmed_customer_image_occurrence(
    payload: dict[str, Any] | None,
    pending_signal_id: str,
) -> dict[str, Any]:
    """Return only a scheduler-confirmed customer structural occurrence."""

    source = payload if isinstance(payload, dict) else {}
    clean_signal_id = str(pending_signal_id or "").strip()
    for message in reversed(source.get("messages") or []):
        if not isinstance(message, dict):
            continue
        message_type = str(message.get("type") or message.get("message_type") or "").strip().lower()
        if message_type not in {"image", "picture", "photo"}:
            continue
        if str(message.get("source_adapter") or "").strip() != "win32_ocr_structural_image_observer":
            continue
        side = str(message.get("visual_side") or message.get("sender") or message.get("sender_role") or "").strip().lower()
        if side != "customer":
            continue
        message_signal_id = str(message.get("pending_signal_id") or "").strip()
        if clean_signal_id and message_signal_id != clean_signal_id:
            continue
        return dict(message)
    return {}


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
    transaction_result = _run_current_clipboard_image_transaction(
        connector=connector,
        target=str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        source_preview=str(candidate.get("content") or ""),
        pending_signal_id=source_message_id,
        side_filter="self",
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
    from .result_schema import (
        image_result_schema,
        image_understanding_completed,
    )

    completed = image_understanding_completed(
        understanding,
        image_result_schema(
            config,
            "customer_image_understanding_v1",
        ),
    )
    return {
        "enabled": True,
        "applied": completed,
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


def _route_strict_customer_image_group_turn(
    *,
    connector: Any,
    target: Any,
    config: dict[str, Any],
    payload: dict[str, Any],
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    image_pending_signal: dict[str, Any],
    proxy_message: dict[str, Any],
    pending_signal_id: str,
) -> dict[str, Any]:
    kind = str(image_pending_signal.get("pending_signal_kind") or "").strip().lower()
    preview = str(image_pending_signal.get("pending_signal_text") or image_pending_signal.get("preview_content") or "").strip()
    explicit_image_pending = kind in {"image_capture", "media_capture"} or image_preview_text(preview)
    anchor_text_key, anchor_message_id = _customer_text_anchor_from_batch(batch)
    acquire_limits = (
        {}
        if explicit_image_pending
        else {"max_scroll_steps": 2, "max_snapshots": 3, "max_seconds": 6.0}
    )
    acquired = _run_current_visual_group_acquire(
        connector=connector,
        target=str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        conversation_type=str(getattr(target, "conversation_type", "") or ""),
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        max_images=3,
        **acquire_limits,
    )
    acquired = acquired if isinstance(acquired, dict) else {}
    ephemeral_images = list(acquired.pop("_ephemeral_clipboard_images", []) or [])
    acquired.pop("_ephemeral_clipboard_image", None)
    public_transaction = _public_clipboard_transaction(
        acquired.get("transaction") if isinstance(acquired, dict) else {}
    )
    try:
        if not acquired.get("ok") or not (1 <= len(ephemeral_images) <= 3):
            raise _VisionEvidenceUnavailable("vision_required_image_acquire_failed")
        source_reason = "clipboard_current_transaction"
        source_message_id = str(
            proxy_message.get("source_message_id")
            or proxy_message.get("message_id")
            or proxy_message.get("id")
            or pending_signal_id
            or f"clipboard_image:{str(getattr(target, 'session_key', '') or target.name or 'target')}"
        ).strip()
        image_assets = _image_assets_for_group(
            image_count=len(ephemeral_images),
            source_message_id=source_message_id,
            acquired_messages=[item for item in (acquired.get("messages") or []) if isinstance(item, dict)],
        )
        try:
            understanding = maybe_run_customer_image_understanding(
                config=config,
                customer_text=combined,
                image_assets=image_assets,
                source_reason=source_reason,
                image_payloads=ephemeral_images,
                ephemeral_clipboard=True,
            )
        except Exception as exc:  # noqa: BLE001 - strict required vision must stop before Brain
            raise _VisionEvidenceUnavailable("customer_image_understanding_provider_failed") from exc
        if not _understanding_has_required_visual_result(understanding):
            raise _VisionEvidenceUnavailable("customer_image_understanding_provider_failed")
        try:
            from .vehicle_retrieval.integration import match_customer_image_to_product_master

            vehicle_image_match = match_customer_image_to_product_master(
                understanding,
                ephemeral_images[0],
                config,
            )
        except Exception as exc:  # noqa: BLE001 - optional retrieval must never block image understanding
            vehicle_image_match = {
                "matched": False,
                "reason": "vehicle_image_retrieval_adapter_failed",
                "error_type": type(exc).__name__,
                "candidates": [],
            }
        catalog_assist = build_customer_image_catalog_assist(
            understanding=understanding,
            customer_text=combined,
            target_state=target_state,
        )
        from .vehicle_retrieval.integration import merge_vehicle_image_match_into_catalog_assist

        catalog_assist = merge_vehicle_image_match_into_catalog_assist(catalog_assist, vehicle_image_match)
        visual_bridge_input = build_customer_image_brain_bridge(
            understanding,
            catalog_assist,
            source_reason=source_reason,
            vehicle_image_retrieval=vehicle_image_match,
        )
        target_state_for_brain = copy.deepcopy(target_state)
        conversation_context = target_state_for_brain.setdefault("conversation_context", {})
        if isinstance(conversation_context, dict):
            merged_context = merge_conversation_context_patch(
                conversation_context,
                catalog_assist.get("conversation_context_patch") or {},
            )
            conversation_context.clear()
            conversation_context.update(merged_context)
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
            "vehicle_image_retrieval": vehicle_image_match,
            "visual_bridge_input": visual_bridge_input,
            "target_state_for_brain": target_state_for_brain,
            "conversation_context_patch": dict(catalog_assist.get("conversation_context_patch") or {}),
            "visual_context_state_patch": visual_context_patch,
            "combined_text_override": str(combined or "").strip() or "客户发来了一张图片",
            "proxy_batch": proxy_batch,
        }
    finally:
        _release_ephemeral_images(ephemeral_images)


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
    bootstrap_proxy = _current_customer_image_proxy(payload, batch, "", batch_only=True)
    if not image_pending_signal and bootstrap_proxy:
        proxy_signal_id = str(bootstrap_proxy.get("pending_signal_id") or "").strip()
        if proxy_signal_id:
            image_pending_signal = {
                "pending_signal_id": proxy_signal_id,
                "pending_signal_kind": "image_capture",
                "pending_signal_text": "[图片]",
            }
    if not image_pending_signal:
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "current_image_pending_signal_missing",
        }
    pending_signal_id = str(image_pending_signal.get("pending_signal_id") or "").strip()
    strict_proxy = _current_customer_image_proxy(payload, batch, pending_signal_id, batch_only=True)
    if strict_proxy:
        if pending_signal_id and pending_image_signal_was_processed(target_state, pending_signal_id):
            return {
                "enabled": True,
                "applied": False,
                "adoptable": False,
                "reason": "pending_image_signal_already_processed",
            }
        return _route_strict_customer_image_group_turn(
            connector=connector,
            target=target,
            config=config,
            payload=payload,
            target_state=target_state,
            batch=batch,
            combined=combined,
            image_pending_signal=image_pending_signal,
            proxy_message=strict_proxy,
            pending_signal_id=pending_signal_id,
        )
    confirmed_occurrence = _confirmed_customer_image_occurrence(payload, pending_signal_id)
    if not confirmed_occurrence:
        try:
            from .integrations.wechat_current import observe_current_surface
            from .occurrence import resolve_pending_visual_occurrence

            observed = observe_current_surface(
                connector,
                str(target.name or ""),
                exact=bool(target.exact),
                session_key=str(getattr(target, "session_key", "") or ""),
                conversation_type=str(getattr(target, "conversation_type", "") or ""),
                side_filter="all",
                max_images=DEFAULT_MAX_VISIBLE_IMAGE_CANDIDATES,
            )
            resolution = resolve_pending_visual_occurrence(
                [item for item in (observed.get("messages") or []) if isinstance(item, dict)],
                target_state=target_state,
                explicit_image_pending=True,
                pending_signal_id=pending_signal_id,
            )
            if str(resolution.get("state") or "") == "customer_confirmed":
                confirmed_occurrence = (
                    resolution.get("occurrence")
                    if isinstance(resolution.get("occurrence"), dict)
                    else {}
                )
            elif str(resolution.get("state") or "") == "self_confirmed":
                return {
                    "enabled": True,
                    "applied": False,
                    "adoptable": False,
                    "context_only": True,
                    "reason": "current_image_direction_is_self",
                }
        except Exception:
            confirmed_occurrence = {}
    if not confirmed_occurrence:
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "current_image_structural_occurrence_missing",
        }
    if pending_signal_id and pending_image_signal_was_processed(target_state, pending_signal_id):
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "pending_image_signal_already_processed",
        }
    transaction_result = _run_current_clipboard_image_transaction(
        connector=connector,
        target=str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        source_preview=str(image_pending_signal.get("pending_signal_text") or image_pending_signal.get("preview_content") or ""),
        speaker_name=str(image_pending_signal.get("speaker_name") or image_pending_signal.get("group_member_name") or ""),
        pending_signal_id=pending_signal_id,
        side_filter="customer",
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
    source_message_id = str(
        confirmed_occurrence.get("message_id")
        or confirmed_occurrence.get("id")
        or pending_signal_id
        or f"clipboard_image:{str(getattr(target, 'session_key', '') or target.name or 'target')}"
    )
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
        try:
            from .vehicle_retrieval.integration import match_customer_image_to_product_master

            vehicle_image_match = match_customer_image_to_product_master(
                understanding,
                ephemeral_image,
                config,
            )
        except Exception as exc:  # noqa: BLE001 - optional retrieval must never block image understanding
            vehicle_image_match = {
                "matched": False,
                "reason": "vehicle_image_retrieval_adapter_failed",
                "error_type": type(exc).__name__,
                "candidates": [],
            }
    finally:
        releaser = getattr(ephemeral_image, "release", None)
        if callable(releaser):
            releaser()
    catalog_assist = build_customer_image_catalog_assist(
        understanding=understanding,
        customer_text=combined,
        target_state=target_state,
    )
    from .vehicle_retrieval.integration import merge_vehicle_image_match_into_catalog_assist

    catalog_assist = merge_vehicle_image_match_into_catalog_assist(catalog_assist, vehicle_image_match)
    visual_bridge_input = build_customer_image_brain_bridge(
        understanding,
        catalog_assist,
        source_reason=source_reason,
        vehicle_image_retrieval=vehicle_image_match,
    )
    target_state_for_brain = copy.deepcopy(target_state)
    conversation_context = target_state_for_brain.setdefault("conversation_context", {})
    if isinstance(conversation_context, dict):
        merged_context = merge_conversation_context_patch(
            conversation_context,
            catalog_assist.get("conversation_context_patch") or {},
        )
        conversation_context.clear()
        conversation_context.update(merged_context)
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
        "vehicle_image_retrieval": vehicle_image_match,
        "visual_bridge_input": visual_bridge_input,
        "target_state_for_brain": target_state_for_brain,
        "conversation_context_patch": dict(catalog_assist.get("conversation_context_patch") or {}),
        "visual_context_state_patch": visual_context_patch,
        "combined_text_override": str(combined or "").strip() or "客户发来了一张图片",
        "proxy_batch": proxy_batch,
    }
