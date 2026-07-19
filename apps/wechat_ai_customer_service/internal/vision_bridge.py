"""Host-side compatibility bridge for the optional visual capability.

The bridge preserves the application's existing internal call shapes while
depending only on the neutral optional-capability dispatcher.  Positive image
logic, state, providers, clipboard access, OCR, and UI actions stay inside the
mounted plugin.  Defaults are absence-safe and never author visible replies.
"""

from __future__ import annotations

import copy
from typing import Any

from apps.wechat_ai_customer_service.optional_plugins.dispatch import (
    invoke_optional_capability,
)


_CAPABILITY = "vision"


def _invoke(operation: str, context: dict[str, Any], default: Any) -> Any:
    return invoke_optional_capability(
        _CAPABILITY,
        operation,
        context,
        default=default,
    )


def customer_image_capture_trigger(
    *,
    payload: dict[str, Any] | None,
    pending_signal: dict[str, Any] | None = None,
    pending_signal_kind: str = "",
    target_state: dict[str, Any] | None = None,
    recent_message_limit: int = 6,
) -> dict[str, Any]:
    signal = pending_signal if isinstance(pending_signal, dict) else {}
    default = {
        "should_run": False,
        "reason": "vision_capability_unavailable",
        "pending_signal_kind": str(
            pending_signal_kind or signal.get("pending_signal_kind") or ""
        ).strip().lower(),
        "pending_signal_id": str(signal.get("pending_signal_id") or ""),
        "evidence_count": 0,
    }
    result = _invoke(
        "should_run",
        {
            "payload": payload,
            "pending_signal": pending_signal,
            "pending_signal_kind": pending_signal_kind,
            "target_state": target_state,
            "recent_message_limit": recent_message_limit,
        },
        default,
    )
    return dict(result) if isinstance(result, dict) else default


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
    default = {
        "enabled": False,
        "applied": False,
        "adoptable": False,
        "reason": "vision_capability_unavailable",
    }
    result = _invoke(
        "run",
        {
            "connector": connector,
            "target": target,
            "config": config,
            "payload": payload,
            "target_state": target_state,
            "batch": batch,
            "combined": combined,
        },
        default,
    )
    return dict(result) if isinstance(result, dict) else default


def maybe_capture_self_image_context(
    *,
    connector: Any,
    target: Any,
    config: dict[str, Any],
    messages: list[dict[str, Any]],
    target_state: dict[str, Any],
    combined: str = "",
) -> dict[str, Any]:
    default = {
        "enabled": False,
        "applied": False,
        "context_only": True,
        "reason": "vision_self_image_context_unavailable",
    }
    result = _invoke(
        "capture_self_context",
        {
            "connector": connector,
            "target": target,
            "config": config,
            "messages": messages,
            "target_state": target_state,
            "combined": combined,
        },
        default,
    )
    return dict(result) if isinstance(result, dict) else default


def observe_current_surface(
    *,
    connector: Any,
    target: Any,
    side_filter: str = "all",
    max_images: int = 8,
) -> dict[str, Any]:
    default = {
        "ok": False,
        "state": "vision_current_surface_observer_unavailable",
        "reason": "vision_current_surface_observer_unavailable",
        "assets": [],
        "messages": [],
    }
    result = _invoke(
        "observe_current_surface",
        {
            "connector": connector,
            "target": target,
            "side_filter": side_filter,
            "max_images": max_images,
        },
        default,
    )
    return dict(result) if isinstance(result, dict) else default


def prepare_scheduler_capture(**kwargs: Any) -> dict[str, Any]:
    default = {
        "messages": [
            dict(item)
            for item in (kwargs.get("messages") or [])
            if isinstance(item, dict)
        ],
        "history_meta": copy.deepcopy(
            kwargs.get("history_meta")
            if isinstance(kwargs.get("history_meta"), dict)
            else {}
        ),
        "self_image_context": {
            "enabled": False,
            "applied": False,
            "context_only": True,
            "reason": "vision_self_image_context_unavailable",
        },
        "customer_image_assets": {},
        "visual_image_assets": {
            "ok": False,
            "state": "vision_capability_unavailable",
            "reason": "vision_capability_unavailable",
            "assets": [],
            "messages": [],
        },
        "visual_capture_trigger": {
            "should_run": False,
            "reason": "vision_capability_unavailable",
            "pending_signal_kind": str(kwargs.get("pending_signal_kind") or ""),
            "pending_signal_id": str(kwargs.get("pending_signal_id") or ""),
            "evidence_count": 0,
        },
        "pending_signal_consumed": False,
    }
    result = _invoke("prepare_scheduler_capture", dict(kwargs), default)
    return dict(result) if isinstance(result, dict) else default


def build_brain_safe_image_proxy_messages(
    sources: list[dict[str, Any]] | None,
    *,
    target_name: str = "",
    session_key: str = "",
    content: str = "",
) -> list[dict[str, Any]]:
    result = _invoke(
        "build_brain_safe_image_proxy_messages",
        {
            "sources": sources,
            "target_name": target_name,
            "session_key": session_key,
            "content": content,
        },
        [],
    )
    return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def augment_text_with_visual_query(
    combined: str,
    visual_bridge_input: dict[str, Any] | None,
) -> str:
    result = _invoke(
        "augment_text_with_visual_query",
        {"combined": combined, "visual_bridge_input": visual_bridge_input},
        str(combined or ""),
    )
    return str(result or "")


def compact_customer_image_brain_bridge(
    value: dict[str, Any] | None,
) -> dict[str, Any]:
    result = _invoke(
        "compact_customer_image_brain_bridge",
        {"value": value},
        {},
    )
    return dict(result) if isinstance(result, dict) else {}


def resolve_visual_brain_turn_text(
    combined: str,
    visual_bridge_input: dict[str, Any] | None,
) -> str:
    result = _invoke(
        "resolve_visual_brain_turn_text",
        {"combined": combined, "visual_bridge_input": visual_bridge_input},
        str(combined or ""),
    )
    return str(result or "")


def visual_image_side(message: dict[str, Any]) -> str:
    return str(_invoke("visual_image_side", {"message": message}, "") or "")


def customer_visual_image_sources(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = _invoke("customer_visual_image_sources", {"sources": sources}, [])
    return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def self_visual_image_sources(
    sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = _invoke("self_visual_image_sources", {"sources": sources}, [])
    return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def customer_image_proxy_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = _invoke("customer_image_proxy_messages", {"messages": messages}, [])
    return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def visual_bounds_key(value: Any) -> str:
    return str(_invoke("visual_bounds_key", {"value": value}, "") or "")


def visual_image_identity_keys(message: dict[str, Any]) -> set[str]:
    result = _invoke("visual_image_identity_keys", {"message": message}, set())
    return {str(item) for item in result} if isinstance(result, (set, list, tuple)) else set()


def target_state_seen_visual_identity_keys(
    target_state: dict[str, Any],
) -> set[str]:
    result = _invoke(
        "target_state_seen_visual_identity_keys",
        {"target_state": target_state},
        set(),
    )
    return {str(item) for item in result} if isinstance(result, (set, list, tuple)) else set()


def filter_fresh_customer_visual_sources(
    sources: list[dict[str, Any]],
    *,
    target_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    default = (
        [],
        {
            "seen_key_count": 0,
            "input_count": len(sources),
            "fresh_count": 0,
            "filtered_count": 0,
            "filtered": [],
            "reason": "vision_capability_unavailable",
        },
    )
    result = _invoke(
        "filter_fresh_customer_visual_sources",
        {"sources": sources, "target_state": target_state},
        default,
    )
    if not isinstance(result, tuple) or len(result) != 2:
        return default
    fresh, meta = result
    return (
        [dict(item) for item in fresh if isinstance(item, dict)] if isinstance(fresh, list) else [],
        dict(meta) if isinstance(meta, dict) else dict(default[1]),
    )


def image_message_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = _invoke("image_message_refs", {"items": items}, [])
    return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []


def planner_customer_image_enrichment(
    capture: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    value = _invoke(
        "planner_customer_image_enrichment",
        {"capture": capture, "result": result},
        {},
    )
    return dict(value) if isinstance(value, dict) else {}


def is_structural_visual_occurrence(message: dict[str, Any]) -> bool:
    return bool(_invoke("is_structural_visual_occurrence", {"message": message}, False))


def resolve_pending_visual_occurrence(
    messages: list[dict[str, Any]],
    *,
    target_state: dict[str, Any],
    explicit_image_pending: bool,
    pending_signal_id: str,
) -> dict[str, Any]:
    default = {
        "state": "vision_capability_unavailable",
        "direction": "",
        "occurrence": {},
    }
    value = _invoke(
        "resolve_pending_visual_occurrence",
        {
            "messages": messages,
            "target_state": target_state,
            "explicit_image_pending": explicit_image_pending,
            "pending_signal_id": pending_signal_id,
        },
        default,
    )
    return dict(value) if isinstance(value, dict) else default


def confirmed_customer_image_placeholder(
    resolution: dict[str, Any],
    *,
    target_name: str,
    session_key: str,
    pending_signal_id: str,
) -> dict[str, Any]:
    value = _invoke(
        "confirmed_customer_image_placeholder",
        {
            "resolution": resolution,
            "target_name": target_name,
            "session_key": session_key,
            "pending_signal_id": pending_signal_id,
        },
        {},
    )
    return dict(value) if isinstance(value, dict) else {}


def image_capture_unavailable_message(
    *,
    target_name: str,
    session_key: str,
    pending_signal_id: str,
    pending_signal: dict[str, Any] | None,
    reason: str,
) -> dict[str, Any]:
    value = _invoke(
        "image_capture_unavailable_message",
        {
            "target_name": target_name,
            "session_key": session_key,
            "pending_signal_id": pending_signal_id,
            "pending_signal": pending_signal,
            "reason": reason,
        },
        {},
    )
    return dict(value) if isinstance(value, dict) else {}
