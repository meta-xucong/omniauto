from __future__ import annotations

from typing import Any


SELF_SENDERS = {"self", "assistant", "service", "bot", "agent", "outbound", "me", "客服"}
CUSTOMER_SENDERS = {"customer", "user", "client", "inbound", "客户"}

_PRODUCT_SCOPED_CONTEXT_KEYS = (
    "last_product_name",
    "last_product_unit",
    "last_product_source",
    "last_product_price",
    "last_unit_price",
    "last_quantity",
    "last_total",
    "vehicle_image_match",
)


def merge_conversation_context_patch(
    existing: dict[str, Any] | None,
    update: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge context without carrying product facts across a product switch.

    Product identity and its price/quantity/source fields are one authority
    binding.  Customer preferences remain durable, while facts belonging to a
    previous product are removed unless the new patch supplies replacements.
    """

    merged = dict(existing) if isinstance(existing, dict) else {}
    patch = dict(update) if isinstance(update, dict) else {}
    previous_product_id = str(merged.get("last_product_id") or "").strip()
    next_product_id = str(patch.get("last_product_id") or "").strip()
    if previous_product_id and next_product_id and previous_product_id != next_product_id:
        for key in _PRODUCT_SCOPED_CONTEXT_KEYS:
            merged.pop(key, None)
    merged.update(patch)
    return merged


def _ledger_recent_messages(target_state: dict[str, Any] | None) -> list[dict[str, Any]]:
    state = target_state if isinstance(target_state, dict) else {}
    context = state.get("conversation_context") if isinstance(state.get("conversation_context"), dict) else {}
    for container in (context, state):
        for key in ("ledger_recent_messages", "recent_messages"):
            value = container.get(key) if isinstance(container, dict) else None
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _vision_summary(message: dict[str, Any]) -> str:
    understanding = message.get("image_understanding") if isinstance(message.get("image_understanding"), dict) else {}
    text = " ".join(
        str(understanding.get("vision_summary") or message.get("vision_summary") or "").split()
    ).strip()
    return text[:600]


def _sender(message: dict[str, Any]) -> str:
    value = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
    if value in SELF_SENDERS:
        return "self"
    if value in CUSTOMER_SENDERS:
        return "customer"
    return ""


def _is_image(message: dict[str, Any]) -> bool:
    modality = str(message.get("modality") or "").strip().lower()
    message_type = str(message.get("type") or message.get("message_type") or "").strip().lower()
    return bool(
        modality == "image"
        or message_type in {"image", "picture", "photo"}
        or message.get("image_capture_pending")
        or str(message.get("visual_turn_kind") or "").strip() in {"customer_image", "self_image"}
    )


def trusted_recent_multimodal_messages(
    target_state: dict[str, Any] | None,
    *,
    limit: int = 4,
    max_intervening_messages: int = 2,
) -> list[dict[str, str]]:
    """Project recent enriched image records into ordinary text history.

    This module consumes only the existing ledger compatibility payload.  It
    never imports a vision provider, reads an image, or exposes image metadata.
    Unenriched structural/synthetic placeholders are removed before adjacency
    is calculated, so they cannot push a valid self image out of context.
    """

    meaningful: list[dict[str, Any]] = []
    for message in _ledger_recent_messages(target_state):
        if _is_image(message) and not _vision_summary(message):
            continue
        content = " ".join(str(message.get("content") or "").split()).strip()
        if _is_image(message) or content:
            meaningful.append(message)
    if not meaningful:
        return []

    result: list[dict[str, str]] = []
    start_index = max(0, len(meaningful) - max(1, int(max_intervening_messages or 0)) - 1)
    for message in meaningful[start_index:]:
        if not _is_image(message):
            continue
        summary = _vision_summary(message)
        sender = _sender(message)
        if not summary or sender not in {"customer", "self"}:
            continue
        message_id = str(
            message.get("identity")
            or message.get("canonical_input_id")
            or message.get("message_id")
            or message.get("id")
            or ""
        ).strip()
        label = "客服" if sender == "self" else "客户"
        result.append(
            {
                "id": message_id,
                "sender": sender,
                "time": str(message.get("time") or message.get("created_at") or "").strip(),
                "content": f"{label}此前发送的图片，识图理解：{summary}",
            }
        )
    return result[-max(1, int(limit or 1)) :]


def trusted_recent_multimodal_history_text(
    target_state: dict[str, Any] | None,
    *,
    limit: int = 4,
    max_intervening_messages: int = 2,
) -> str:
    lines: list[str] = []
    for item in trusted_recent_multimodal_messages(
        target_state,
        limit=limit,
        max_intervening_messages=max_intervening_messages,
    ):
        label = "客服" if item.get("sender") == "self" else "客户"
        lines.append(f"[{label}] {item.get('content') or ''}".strip())
    return "\n".join(lines)


def has_recent_trusted_multimodal_context(target_state: dict[str, Any] | None) -> bool:
    return bool(trusted_recent_multimodal_messages(target_state, limit=1))
