from __future__ import annotations

import copy
from typing import Any

from apps.wechat_ai_customer_service.workflows.customer_image_asset_store import (
    payload_image_pending_signal,
    maybe_collect_customer_image_assets,
)
from apps.wechat_ai_customer_service.workflows.customer_image_brain_bridge import (
    build_customer_image_brain_bridge,
)
from apps.wechat_ai_customer_service.workflows.customer_image_catalog_assist import (
    build_customer_image_catalog_assist,
)
from apps.wechat_ai_customer_service.workflows.customer_image_understanding import (
    maybe_run_customer_image_understanding,
)
from apps.wechat_ai_customer_service.workflows.customer_service_prompt_archive import archive_prompt_event


IMAGE_MESSAGE_TYPES = {"image", "picture", "photo"}
FOLLOWUP_VISUAL_TERMS = (
    "这款",
    "这车",
    "这台",
    "有吗",
    "多少钱",
    "同款",
    "类似",
    "看看这",
    "图片",
    "看图",
)


def _has_direct_image_message(messages: list[dict[str, Any]]) -> bool:
    for item in messages:
        if not isinstance(item, dict):
            continue
        message_type = str(item.get("type") or item.get("message_type") or "").strip().lower()
        visual_type = str(item.get("message_type") or "").strip().lower()
        if message_type in IMAGE_MESSAGE_TYPES or visual_type in IMAGE_MESSAGE_TYPES or str(item.get("saved_image_path") or "").strip():
            return True
    return False


def _should_probe_visual_followup(combined: str) -> bool:
    text = str(combined or "").strip()
    if not text:
        return False
    if len(text) > 24:
        return False
    return any(term in text for term in FOLLOWUP_VISUAL_TERMS)


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
    messages = [item for item in (payload.get("messages") or []) if isinstance(item, dict)]
    direct_image_message = _has_direct_image_message(messages)
    image_pending_signal = payload_image_pending_signal(payload, target_state)
    source_reason = ""
    if direct_image_message:
        source_reason = "direct_image_message"
    elif image_pending_signal and not batch:
        source_reason = "empty_capture_image_pending"
    elif image_pending_signal:
        source_reason = "preview_image_message"
    elif not batch:
        source_reason = "no_text_batch_probe"
    elif _should_probe_visual_followup(combined):
        source_reason = "visual_followup_text_probe"
    if not source_reason:
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "image_probe_not_needed",
        }
    assets_result = maybe_collect_customer_image_assets(
        connector,
        target_name=str(target.name or ""),
        exact=bool(target.exact),
        session_key=str(getattr(target, "session_key", "") or ""),
        payload=payload,
        target_state=target_state,
    )
    if not assets_result.get("applied"):
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": str(assets_result.get("reason") or "customer_image_assets_unavailable"),
            "customer_image_assets": assets_result,
        }
    image_assets = [item for item in (assets_result.get("assets") or []) if isinstance(item, dict)]
    understanding = maybe_run_customer_image_understanding(
        config=config,
        customer_text=combined,
        image_assets=image_assets,
        source_reason=source_reason,
    )
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
    try:
        archive_prompt_event(
            "customer_image_turn_bridge",
            {
                "target_name": str(target.name or ""),
                "source_reason": source_reason,
                "customer_text": combined,
                "customer_image_assets": assets_result,
                "customer_image_understanding": understanding,
                "customer_image_catalog_assist": catalog_assist,
                "visual_bridge_input": visual_bridge_input,
            },
            config=config,
        )
    except Exception:
        pass
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
    proxy_message_id = ""
    if image_assets:
        proxy_message_id = str(image_assets[0].get("message_id") or image_assets[0].get("asset_id") or "")
    asset_messages = [item for item in (assets_result.get("messages") or []) if isinstance(item, dict)]
    if asset_messages:
        proxy_batch = asset_messages
    else:
        proxy_batch = [
            {
                "id": f"visual_proxy:{proxy_message_id or source_reason}",
                "message_id": f"visual_proxy:{proxy_message_id or source_reason}",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": str(combined or "").strip() or "客户发来了一张图片",
                "quality_flags": ["synthetic_visual_turn"],
            }
        ]
    return {
        "enabled": True,
        "applied": True,
        "adoptable": True,
        "reason": "customer_image_turn_ready",
        "source_reason": source_reason,
        "customer_image_assets": assets_result,
        "customer_image_understanding": understanding,
        "customer_image_catalog_assist": catalog_assist,
        "visual_bridge_input": visual_bridge_input,
        "target_state_for_brain": target_state_for_brain,
        "conversation_context_patch": dict(catalog_assist.get("conversation_context_patch") or {}),
        "visual_context_state_patch": visual_context_patch,
        "combined_text_override": str(combined or "").strip() or "客户发来了一张图片",
        "proxy_batch": proxy_batch,
    }
