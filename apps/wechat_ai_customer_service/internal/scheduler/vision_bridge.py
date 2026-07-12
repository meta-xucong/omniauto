from __future__ import annotations

from typing import Any


def visual_image_side(message: dict[str, Any]) -> str:
    side = str(message.get("visual_side") or "").strip().lower()
    if side in {"customer", "self"}:
        return side
    sender = str(message.get("sender") or message.get("sender_role") or "").strip().lower()
    if sender in {"customer", "self"}:
        return sender
    return ""


def customer_visual_image_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in sources
        if isinstance(item, dict) and visual_image_side(item) == "customer"
    ]


def self_visual_image_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in sources
        if isinstance(item, dict) and visual_image_side(item) == "self"
    ]


def customer_image_proxy_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in messages or []:
        if not isinstance(item, dict) or not item.get("is_customer_image_proxy"):
            continue
        if str(item.get("visual_turn_kind") or "").strip() != "customer_image":
            continue
        if visual_image_side(item) == "self":
            continue
        if not str(item.get("saved_image_path") or "").strip():
            continue
        result.append(item)
    return result


def visual_bounds_key(value: Any) -> str:
    try:
        bounds = [int(float(item)) for item in list(value or [])[:4]]
    except (TypeError, ValueError):
        return ""
    if len(bounds) != 4:
        return ""
    return ",".join(str(item) for item in bounds)


def visual_image_identity_keys(message: dict[str, Any]) -> set[str]:
    if not isinstance(message, dict):
        return set()
    keys: set[str] = set()

    def add(prefix: str, value: Any) -> None:
        text = str(value or "").strip()
        if text:
            keys.add(f"{prefix}:{text}")

    add("visual_occurrence", message.get("visual_occurrence_id"))
    add("pending_signal", message.get("pending_signal_id"))
    add("visual_msg", message.get("message_id") or message.get("id") or message.get("identity"))
    add("visual_msg", message.get("canonical_visual_id") or message.get("canonical_input_id"))
    add("source_msg", message.get("source_message_id"))
    side = visual_image_side(message) or str(message.get("visual_side") or "").strip().lower() or "unknown"
    bounds = visual_bounds_key(message.get("bubble_bounds"))
    if bounds:
        add(
            "sha_bounds",
            f"{side}:{message.get('sha256')}:{bounds}" if message.get("sha256") else "",
        )
        add(
            "asset_bounds",
            f"{side}:{message.get('asset_id')}:{bounds}" if message.get("asset_id") else "",
        )
        add(
            "path_bounds",
            f"{side}:{message.get('saved_image_path')}:{bounds}"
            if message.get("saved_image_path")
            else "",
        )
    return keys


def target_state_seen_visual_identity_keys(target_state: dict[str, Any]) -> set[str]:
    state = target_state if isinstance(target_state, dict) else {}
    seen: set[str] = set()
    for item in state.get("processed_message_ids") or []:
        value = str(item or "").strip()
        if value:
            seen.add(f"visual_msg:{value}")
            seen.add(f"source_msg:{value}")
    context = state.get("conversation_context") if isinstance(state.get("conversation_context"), dict) else {}
    recent_sources: list[Any] = []
    for key in ("ledger_recent_messages", "recent_messages"):
        value = context.get(key) if isinstance(context, dict) else None
        if isinstance(value, list):
            recent_sources.extend(value)
    for key in ("ledger_recent_messages", "recent_messages", "visual_recent_messages"):
        value = state.get(key)
        if isinstance(value, list):
            recent_sources.extend(value)
    for item in recent_sources:
        if isinstance(item, dict):
            seen.update(visual_image_identity_keys(item))
    return seen


def filter_fresh_customer_visual_sources(
    sources: list[dict[str, Any]],
    *,
    target_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen = target_state_seen_visual_identity_keys(target_state)
    fresh: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        keys = visual_image_identity_keys(source)
        pending_signal_key = str(source.get("pending_signal_id") or "").strip()
        pending_signal_seen = bool(
            pending_signal_key and f"pending_signal:{pending_signal_key}" in seen
        )
        pending_signal_is_source_identity = bool(
            pending_signal_key and not source.get("_pending_signal_id_attached_by_scheduler")
        )
        occurrence_value = str(source.get("visual_occurrence_id") or "").strip()
        occurrence_seen = bool(
            occurrence_value and f"visual_occurrence:{occurrence_value}" in seen
        )
        if pending_signal_is_source_identity and not pending_signal_seen:
            already_seen = False
        elif occurrence_seen:
            already_seen = True
        elif pending_signal_key:
            already_seen = pending_signal_seen
        else:
            already_seen = bool(keys and seen.intersection(keys))
        if already_seen:
            filtered.append(
                {
                    "message_id": str(source.get("message_id") or source.get("id") or ""),
                    "visual_occurrence_id": occurrence_value,
                    "asset_id": str(source.get("asset_id") or ""),
                    "pending_signal_id": pending_signal_key,
                    "reason": "visual_image_already_seen",
                }
            )
            continue
        fresh.append(source)
    return fresh, {
        "seen_key_count": len(seen),
        "input_count": len(sources),
        "fresh_count": len(fresh),
        "filtered_count": len(filtered),
        "filtered": filtered[:20],
    }


def image_message_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        ref = {
            key: str(item.get(key) or "").strip()
            for key in (
                "id",
                "message_id",
                "source_message_id",
                "visual_occurrence_id",
                "asset_id",
                "saved_image_path",
            )
            if str(item.get(key) or "").strip()
        }
        identity = "|".join(sorted(ref.values()))
        if not ref or identity in seen:
            continue
        seen.add(identity)
        refs.append(ref)
    return refs[:20]


def planner_customer_image_enrichment(
    capture: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    event = result.get("event") if isinstance(result.get("event"), dict) else {}
    image_turn = (
        event.get("customer_image_turn")
        if isinstance(event.get("customer_image_turn"), dict)
        else {}
    )
    understanding = (
        image_turn.get("customer_image_understanding")
        if isinstance(image_turn.get("customer_image_understanding"), dict)
        else {}
    )
    if not understanding:
        return {}
    assets_payload = (
        capture.get("customer_image_assets")
        if isinstance(capture.get("customer_image_assets"), dict)
        else {}
    )
    refs = image_message_refs(
        [
            item
            for item in [
                *(assets_payload.get("messages") or []),
                *(assets_payload.get("assets") or []),
                *(understanding.get("source_messages") or []),
            ]
            if isinstance(item, dict)
        ]
    )
    if not refs:
        refs = image_message_refs(
            [
                item
                for item in (capture.get("messages") or [])
                if isinstance(item, dict) and visual_image_side(item) == "customer"
            ]
        )
    return {
        "modality": "image",
        "message_refs": refs,
        "image_understanding": understanding,
        "reason": str(
            image_turn.get("source_reason")
            or understanding.get("reason")
            or "customer_image_planner"
        ),
    }
