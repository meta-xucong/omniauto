"""Host-neutral current-image acquisition transaction.

This module owns image direction, bubble/menu selection and clipboard
freshness. Hosts provide generic frame/action/clipboard ports only.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from ..clipboard_payload import ephemeral_image_from_memory
from ..ports import VisionHostPorts
from .wechat import detect_visual_image_bubbles, find_copy_menu_item


def _failure(reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "vision_port_transaction_failed",
        "reason": str(reason or "vision_port_transaction_failed"),
        "assets": [],
        "messages": [],
        **extra,
    }


def acquire_current_image_via_ports(
    ports: VisionHostPorts,
    request: dict[str, Any] | None,
) -> dict[str, Any]:
    """Acquire exactly one current bitmap while holding the host RPA lease."""

    data = dict(request or {})
    required = (
        ports.conversation_target,
        ports.window_frame,
        ports.ui_action,
        ports.clipboard,
    )
    if any(item is None for item in required):
        return _failure("vision_host_ports_incomplete")
    side_filter = str(data.get("side_filter") or "customer").strip().lower()
    if side_filter not in {"customer", "self", "all"}:
        return _failure("image_clipboard_side_filter_invalid")
    lease = (
        ports.rpa_lease.lease("vision_current_image", timeout_seconds=float(data.get("lock_timeout_seconds") or 45.0))
        if ports.rpa_lease is not None
        else nullcontext({"acquired": True, "source": "vision_port_noop_lease"})
    )
    try:
        with lease:
            target_proof = ports.conversation_target.confirm_target(dict(data))
            if not isinstance(target_proof, dict) or target_proof.get("ok") is not True:
                return _failure("vision_target_confirmation_failed")
            frame = ports.window_frame.capture_frame({**data, "phase": "image_candidate"})
            if not isinstance(frame, dict) or frame.get("ok") is not True:
                return _failure("vision_window_frame_unavailable")
            surface = frame.get("image")
            image_size = getattr(surface, "size", None) or tuple(frame.get("image_size") or ())
            if surface is None or len(image_size) != 2:
                return _failure("vision_window_frame_invalid")
            bubbles = detect_visual_image_bubbles(
                surface,
                messages=[item for item in (frame.get("messages") or []) if isinstance(item, dict)],
                max_images=max(1, int(data.get("max_images") or 8)),
                side_filter=side_filter,
                time_markers=[item for item in (frame.get("time_markers") or []) if isinstance(item, dict)],
            )
            if not bubbles:
                return _failure("image_bubble_not_found")
            bubble = dict(bubbles[-1])
            direction = str(bubble.get("side") or "").strip().lower()
            if direction not in {"customer", "self"}:
                return _failure("image_direction_ambiguous")
            anchor = bubble.get("anchor") if isinstance(bubble.get("anchor"), dict) else {}
            sequence_before = ports.clipboard.sequence_number()
            ports.ui_action.right_click(int(anchor.get("x") or 0), int(anchor.get("y") or 0))
            menu_frame = ports.window_frame.capture_frame({**data, "phase": "image_context_menu"})
            if not isinstance(menu_frame, dict) or menu_frame.get("ok") is not True:
                return _failure("image_context_menu_unavailable")
            menu_surface = menu_frame.get("image")
            menu_size = getattr(menu_surface, "size", None) or tuple(menu_frame.get("image_size") or image_size)
            copy_item = find_copy_menu_item(
                [item for item in (menu_frame.get("ocr_items") or []) if isinstance(item, dict)],
                tuple(menu_size),
            )
            if not copy_item:
                return _failure("image_context_menu_copy_item_missing")
            ports.ui_action.click(int(copy_item.get("x") or 0), int(copy_item.get("y") or 0))
            sequence_after = ports.clipboard.sequence_number()
            if sequence_before is None or sequence_after is None or int(sequence_after) == int(sequence_before):
                return _failure("clipboard_sequence_unchanged_after_copy")
            payload = ephemeral_image_from_memory(
                ports.clipboard.read_current_bitmap(),
                mime_type=str(data.get("mime_type") or "image/png"),
            )
            if payload is None:
                return _failure("clipboard_current_content_not_bitmap")
            return {
                "ok": True,
                "state": "image_clipboard_copied",
                "direction": direction,
                "occurrence": {
                    "sender": direction,
                    "sender_role": direction,
                    "visual_side": direction,
                    "pending_signal_id": str(data.get("pending_signal_id") or ""),
                    "message_id": str(data.get("message_id") or data.get("pending_signal_id") or "memory-current-image"),
                },
                "target_proof": dict(target_proof),
                "transaction": {
                    "status": "clipboard_read",
                    "right_click_ok": True,
                    "menu_copy_confirmed": True,
                    "clipboard_sequence_changed": True,
                    "clipboard_content_read": True,
                    "clipboard_image_valid": True,
                    "visual_side": direction,
                },
                "_ephemeral_clipboard_image": payload,
            }
    except TimeoutError as exc:
        return _failure("image_clipboard_transaction_lock_timeout", error_type=type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - host failures are normalized
        return _failure("vision_port_transaction_exception", error_type=type(exc).__name__)
