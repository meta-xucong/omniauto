"""Lightweight Brain preflight for evidence-demand routing.

This module belongs to the customer-service Brain runtime.  It never authors
customer-visible wording; it only decides whether the next Brain turn needs
authoritative evidence before the Brain LLM writes the reply.
"""

from __future__ import annotations

import json
import time
from typing import Any

from apps.wechat_ai_customer_service.llm_config import (
    call_llm_request_with_failover,
    read_secret,
    resolve_effective_llm_provider,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_tier_model,
)
from llm_output_adapter import parse_llm_json_object


DEFAULT_PREFLIGHT_TIMEOUT_SECONDS = 3
DEFAULT_PREFLIGHT_FALLBACK_TIMEOUT_SECONDS = 2
DEFAULT_PREFLIGHT_MAX_TOKENS = 360
DEFAULT_PREFLIGHT_TEMPERATURE = 0.0
DEFAULT_CONTEXT_FOLLOWUP_MAX_CHARS = 80


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "..."


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return default


def _positive_int(value: Any, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(default if value in (None, "") else value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _float_0_1(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _unique_strings(values: Any, *, limit: int = 5, max_chars: int = 120) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    source_values = values if isinstance(values, list) else [values]
    for item in source_values:
        text = _clip(item, max_chars)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def effective_customer_service_brain_preflight_settings(
    *,
    config: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Merge flat, nested, and top-level preflight config."""

    config = config if isinstance(config, dict) else {}
    settings = settings if isinstance(settings, dict) else {}
    brain_config = _as_dict(config.get("customer_service_brain"))
    merged: dict[str, Any] = {
        "enabled": True,
        "mode": "adaptive",
        "provider": settings.get("provider") or "manual_json",
        "model": "",
        "base_url": "",
        "model_tier": "flash",
        "timeout_seconds": DEFAULT_PREFLIGHT_TIMEOUT_SECONDS,
        "fallback_timeout_seconds": DEFAULT_PREFLIGHT_FALLBACK_TIMEOUT_SECONDS,
        "max_tokens": DEFAULT_PREFLIGHT_MAX_TOKENS,
        "temperature": DEFAULT_PREFLIGHT_TEMPERATURE,
        "context_followup_max_chars": DEFAULT_CONTEXT_FOLLOWUP_MAX_CHARS,
        "text_evidence_gap_enabled": True,
        "text_evidence_gap_max_chars": 80,
        "text_evidence_gap_probe_short_low_authority": True,
        "visual_bridge_fast_preflight_enabled": True,
    }
    flat_key_map = {
        "preflight_enabled": "enabled",
        "preflight_mode": "mode",
        "preflight_provider": "provider",
        "preflight_model": "model",
        "preflight_base_url": "base_url",
        "preflight_model_tier": "model_tier",
        "preflight_timeout_seconds": "timeout_seconds",
        "preflight_fallback_timeout_seconds": "fallback_timeout_seconds",
        "preflight_max_tokens": "max_tokens",
        "preflight_temperature": "temperature",
        "preflight_context_followup_max_chars": "context_followup_max_chars",
        "preflight_candidate": "candidate",
        "preflight_plan": "candidate",
        "preflight_candidate_json_path": "candidate_json_path",
        "preflight_text_evidence_gap_enabled": "text_evidence_gap_enabled",
        "preflight_text_evidence_gap_max_chars": "text_evidence_gap_max_chars",
        "preflight_text_evidence_gap_probe_short_low_authority": "text_evidence_gap_probe_short_low_authority",
        "preflight_visual_bridge_fast_preflight_enabled": "visual_bridge_fast_preflight_enabled",
    }
    for old_key, new_key in flat_key_map.items():
        if old_key in settings:
            merged[new_key] = settings.get(old_key)
        if old_key in brain_config:
            merged[new_key] = brain_config.get(old_key)
    nested = _as_dict(settings.get("preflight")) or _as_dict(brain_config.get("preflight"))
    merged.update(nested)
    merged.update(_as_dict(config.get("customer_service_brain_preflight")))
    merged["enabled"] = _as_bool(merged.get("enabled"), default=True)
    merged["mode"] = str(merged.get("mode") or "adaptive").strip() or "adaptive"
    merged["provider"] = str(merged.get("provider") or settings.get("provider") or "manual_json").strip() or "manual_json"
    merged["model_tier"] = str(merged.get("model_tier") or "flash").strip() or "flash"
    merged["timeout_seconds"] = _positive_int(merged.get("timeout_seconds"), DEFAULT_PREFLIGHT_TIMEOUT_SECONDS, minimum=1)
    merged["fallback_timeout_seconds"] = _positive_int(
        merged.get("fallback_timeout_seconds"),
        DEFAULT_PREFLIGHT_FALLBACK_TIMEOUT_SECONDS,
        minimum=1,
    )
    merged["max_tokens"] = _positive_int(merged.get("max_tokens"), DEFAULT_PREFLIGHT_MAX_TOKENS, minimum=128)
    try:
        merged["temperature"] = float(merged.get("temperature", DEFAULT_PREFLIGHT_TEMPERATURE))
    except (TypeError, ValueError):
        merged["temperature"] = DEFAULT_PREFLIGHT_TEMPERATURE
    merged["context_followup_max_chars"] = _positive_int(
        merged.get("context_followup_max_chars"),
        DEFAULT_CONTEXT_FOLLOWUP_MAX_CHARS,
        minimum=1,
    )
    merged["text_evidence_gap_enabled"] = _as_bool(merged.get("text_evidence_gap_enabled"), default=True)
    merged["text_evidence_gap_max_chars"] = _positive_int(merged.get("text_evidence_gap_max_chars"), 80, minimum=1)
    merged["text_evidence_gap_probe_short_low_authority"] = _as_bool(
        merged.get("text_evidence_gap_probe_short_low_authority"),
        default=True,
    )
    merged["visual_bridge_fast_preflight_enabled"] = _as_bool(
        merged.get("visual_bridge_fast_preflight_enabled"),
        default=True,
    )
    return merged


def compact_visual_bridge_for_preflight(value: dict[str, Any] | None) -> dict[str, Any]:
    bridge = _as_dict(value)
    if not bridge:
        return {}
    classification = _as_dict(bridge.get("classification"))
    catalog_assist = _as_dict(bridge.get("catalog_assist"))
    intent_hints = _as_dict(bridge.get("intent_hints"))
    return {
        "present": bool(bridge.get("present")),
        "vision_summary": _clip(bridge.get("vision_summary"), 180),
        "classification": {
            "is_vehicle": bool(classification.get("is_vehicle", False)),
            "vehicle_confidence": _float_0_1(classification.get("vehicle_confidence")),
            "unknown": bool(classification.get("unknown", False)),
        },
        "catalog_assist": {
            "normalized_vehicle_query": _clip(catalog_assist.get("normalized_vehicle_query"), 140),
            "exact_candidate_name": _clip(catalog_assist.get("exact_candidate_name"), 100),
            "candidate_names": _unique_strings(catalog_assist.get("candidate_names"), limit=4, max_chars=100),
        },
        "intent_hints": {
            "wants_catalog_match": bool(intent_hints.get("wants_catalog_match", False)),
            "wants_similar_recommendation": bool(intent_hints.get("wants_similar_recommendation", False)),
            "needs_clarification": bool(intent_hints.get("needs_clarification", False)),
        },
    }


def recent_visual_bridge_from_state(target_state: dict[str, Any]) -> dict[str, Any]:
    visual_state = _as_dict(target_state.get("visual_context_state"))
    return _as_dict(visual_state.get("last_visual_bridge_input"))


def collect_visual_product_queries(
    visual_bridge_input: dict[str, Any] | None,
    *,
    target_state: dict[str, Any] | None = None,
) -> list[str]:
    queries: list[str] = []
    for bridge in (visual_bridge_input, recent_visual_bridge_from_state(_as_dict(target_state))):
        bridge = _as_dict(bridge)
        catalog_assist = _as_dict(bridge.get("catalog_assist"))
        for value in (
            catalog_assist.get("normalized_vehicle_query"),
            catalog_assist.get("exact_candidate_name"),
        ):
            queries.extend(_unique_strings(value, limit=1, max_chars=120))
        queries.extend(_unique_strings(catalog_assist.get("candidate_names"), limit=3, max_chars=120))
    return _unique_strings(queries, limit=5, max_chars=120)


def should_run_customer_service_brain_preflight(
    *,
    settings: dict[str, Any],
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    visual_bridge_input: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = str(settings.get("mode") or "adaptive").strip().lower()
    if mode in {"off", "disabled", "false"}:
        return {"enabled": False, "reason": "brain_preflight_mode_off"}
    if mode == "always":
        return {"enabled": True, "reason": "brain_preflight_mode_always"}
    bridge = _as_dict(visual_bridge_input)
    if bridge.get("present"):
        return {"enabled": True, "reason": "visual_bridge_present"}
    recent_queries = collect_visual_product_queries({}, target_state=target_state)
    clean = str(combined or "").strip()
    if recent_queries and clean and len(clean) <= int(settings.get("context_followup_max_chars") or DEFAULT_CONTEXT_FOLLOWUP_MAX_CHARS):
        return {"enabled": True, "reason": "recent_visual_context_short_followup"}
    if recent_queries and any(
        str(item.get("quality_flags") or "").find("synthetic_visual_turn") >= 0
        for item in (batch or [])
        if isinstance(item, dict)
    ):
        return {"enabled": True, "reason": "synthetic_visual_turn"}
    return {"enabled": False, "reason": "brain_preflight_not_triggered"}


def build_customer_service_brain_preflight_prompt(
    *,
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    visual_bridge_input: dict[str, Any] | None,
) -> dict[str, Any]:
    visual_state = _as_dict(target_state.get("visual_context_state"))
    conversation_context = _as_dict(target_state.get("conversation_context"))
    recent_visual_bridge = recent_visual_bridge_from_state(target_state)
    current_messages = [
        {
            "id": _clip(item.get("id") or item.get("message_id"), 80),
            "sender": _clip(item.get("sender") or item.get("speaker"), 40),
            "content": _clip(item.get("content"), 160),
            "type": _clip(item.get("type") or item.get("message_type"), 30),
            "quality_flags": item.get("quality_flags") or [],
        }
        for item in (batch or [])[:3]
        if isinstance(item, dict)
    ]
    system = (
        "你是 customer_service_brain 的轻量 Preflight 插件。"
        "你的任务不是回复客户，而是在 Brain 正式回复前判断是否必须先查询权威证据。"
        "重点判断客户当前文字、图片识别辅助包、最近视觉上下文之间的指代关系。"
        "如果客户在问某款车有没有、价格、型号、配置、推荐、对比、相似款，必须要求 product_master。"
        "如果客户用错别字、简称、英文数字混写或口语说车型，请给出少量最可能的商品库查询词。"
        "如果只是普通闲聊且不需要商品事实，可以允许 low_authority_fast。"
        "只输出裸 JSON 对象，不要 Markdown，不要解释。"
    )
    return {
        "schema_version": 1,
        "system": system,
        "user": {
            "task": "判断本 turn 需要哪些权威证据，并生成商品库检索线索。",
            "output_schema": {
                "customer_goal": "短句",
                "business_intent": "product_availability/product_price/product_model_info/product_recommendation/general_chat/other",
                "requires_product_master": "bool",
                "requires_formal_knowledge": "bool",
                "requires_current_context": "bool",
                "low_authority_fast_allowed": "bool",
                "normalized_product_queries": ["用于商品库检索的车型/车系/品牌线索"],
                "evidence_lookup_mode": "product_master_exact_then_similar/formal_knowledge/context_only/none",
                "context_resolution": {
                    "uses_visual_bridge": "bool",
                    "uses_recent_visual_context": "bool",
                    "ambiguous_reference": "bool",
                },
                "brain_guidance": "给 Brain 的内部建议，不可直接发客户",
                "confidence": "0-1",
                "reason": "短原因",
            },
            "target_name": _clip(target_name, 80),
            "current_message": {
                "combined": _clip(combined, 260),
                "messages": current_messages,
            },
            "visual_bridge_input": compact_visual_bridge_for_preflight(visual_bridge_input),
            "recent_visual_context": {
                "last_visual_summary": _clip(visual_state.get("last_visual_summary"), 180),
                "last_visual_bridge_input": compact_visual_bridge_for_preflight(recent_visual_bridge),
            },
            "conversation_context_hints": {
                "last_product_id": _clip(conversation_context.get("last_product_id"), 80),
                "last_product_name": _clip(conversation_context.get("last_product_name"), 120),
                "last_customer_need_text": _clip(conversation_context.get("last_customer_need_text"), 180),
                "recent_product_ids": conversation_context.get("recent_product_ids") or [],
            },
            "authority_policy": (
                "Preflight 只决定查证据；商品事实、价格、库存、车况必须由 product_master 授权，"
                "客户可见回复只能由 customer_service_brain 生成。"
            ),
        },
    }


def preflight_from_manual_json(settings: dict[str, Any]) -> dict[str, Any]:
    plan = (
        settings.get("brain_preflight_plan")
        or settings.get("preflight_plan")
        or settings.get("candidate")
    )
    if isinstance(plan, dict):
        return {"ok": True, "provider": "manual_json", "preflight_plan": plan}
    path_value = str(
        settings.get("brain_preflight_plan_json_path")
        or settings.get("preflight_plan_json_path")
        or settings.get("candidate_json_path")
        or ""
    ).strip()
    if not path_value:
        return {"ok": False, "provider": "manual_json", "error": "brain_preflight_plan_json_path_missing"}
    try:
        with open(path_value, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {"ok": False, "provider": "manual_json", "error": repr(exc)}
    plan = payload.get("brain_preflight_plan", payload.get("preflight_plan", payload.get("candidate", payload))) if isinstance(payload, dict) else {}
    if not isinstance(plan, dict):
        return {"ok": False, "provider": "manual_json", "error": "brain_preflight_plan_not_object"}
    return {"ok": True, "provider": "manual_json", "preflight_plan": plan}


def run_customer_service_brain_preflight_llm(
    *,
    settings: dict[str, Any],
    prompt: dict[str, Any],
) -> dict[str, Any]:
    provider = resolve_effective_llm_provider(settings.get("provider") or "manual_json", read_secret_fn=read_secret)
    if provider == "manual_json":
        return preflight_from_manual_json(settings)
    api_key = resolve_llm_api_key(provider=provider, read_secret_fn=read_secret)
    model = resolve_llm_tier_model(
        provider=provider,
        tier=str(settings.get("model_tier") or "flash"),
        explicit_model=str(settings.get("model") or ""),
        read_secret_fn=read_secret,
    )
    base_url = resolve_llm_base_url(
        provider=provider,
        explicit_base_url=str(settings.get("base_url") or ""),
        read_secret_fn=read_secret,
    )
    if not api_key:
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "base_url": base_url,
            "error": "LLM API key is not set",
        }
    messages = [
        {"role": "system", "content": str(prompt.get("system") or "")},
        {
            "role": "user",
            "content": json.dumps(prompt.get("user") or {}, ensure_ascii=False, separators=(",", ":")),
        },
    ]
    timeout_seconds = _positive_int(settings.get("timeout_seconds"), DEFAULT_PREFLIGHT_TIMEOUT_SECONDS, minimum=1)
    fallback_timeout_seconds = _positive_int(
        settings.get("fallback_timeout_seconds"),
        DEFAULT_PREFLIGHT_FALLBACK_TIMEOUT_SECONDS,
        minimum=1,
    )
    response = call_llm_request_with_failover(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        timeout=timeout_seconds,
        fallback_timeout=fallback_timeout_seconds,
        wall_timeout=timeout_seconds,
        fallback_wall_timeout=fallback_timeout_seconds,
        max_tokens=_positive_int(settings.get("max_tokens"), DEFAULT_PREFLIGHT_MAX_TOKENS, minimum=128),
        temperature=float(settings.get("temperature", DEFAULT_PREFLIGHT_TEMPERATURE)),
        tier=str(settings.get("model_tier") or "flash"),
        json_mode=True,
    )
    response["primary_provider"] = provider
    response["primary_model"] = model
    response["primary_base_url"] = base_url
    if not response.get("ok"):
        return response
    raw_text = str(response.get("response_text") or "")
    parsed = parse_llm_json_object(raw_text)
    if not isinstance(parsed, dict):
        response["ok"] = False
        response["error"] = "brain_preflight_response_not_json_object"
        response["raw_response_text"] = raw_text[:600]
        return response
    response["preflight_plan"] = parsed
    response["raw_response_text"] = raw_text[:600]
    return response


def normalize_customer_service_brain_preflight_plan(value: Any) -> dict[str, Any]:
    payload = _as_dict(value)
    if isinstance(payload.get("plan"), dict):
        payload = _as_dict(payload.get("plan"))
    queries = _unique_strings(
        payload.get("normalized_product_queries")
        or payload.get("product_queries")
        or payload.get("search_queries")
        or payload.get("normalized_product_query"),
        limit=5,
        max_chars=120,
    )
    requires_product_master = _as_bool(payload.get("requires_product_master"), default=False)
    requires_formal_knowledge = _as_bool(payload.get("requires_formal_knowledge"), default=False)
    requires_current_context = _as_bool(payload.get("requires_current_context"), default=False)
    if payload.get("low_authority_fast_allowed") is None:
        low_authority_fast_allowed = not (
            requires_product_master
            or requires_formal_knowledge
            or requires_current_context
            or bool(queries)
        )
    else:
        low_authority_fast_allowed = _as_bool(payload.get("low_authority_fast_allowed"), default=True)
    context_resolution = _as_dict(payload.get("context_resolution"))
    return {
        "schema_version": 1,
        "customer_goal": _clip(payload.get("customer_goal"), 120),
        "business_intent": _clip(payload.get("business_intent"), 80) or "other",
        "requires_product_master": requires_product_master,
        "requires_formal_knowledge": requires_formal_knowledge,
        "requires_current_context": requires_current_context,
        "low_authority_fast_allowed": low_authority_fast_allowed,
        "normalized_product_queries": queries,
        "evidence_lookup_mode": _clip(payload.get("evidence_lookup_mode"), 80) or (
            "product_master_exact_then_similar" if requires_product_master else "none"
        ),
        "context_resolution": {
            "uses_visual_bridge": _as_bool(context_resolution.get("uses_visual_bridge"), default=False),
            "uses_recent_visual_context": _as_bool(context_resolution.get("uses_recent_visual_context"), default=False),
            "ambiguous_reference": _as_bool(context_resolution.get("ambiguous_reference"), default=False),
        },
        "brain_guidance": _clip(payload.get("brain_guidance"), 220),
        "confidence": _float_0_1(payload.get("confidence"), default=0.0),
        "reason": _clip(payload.get("reason"), 120),
    }


def visual_bridge_evidence_guard_plan(
    *,
    visual_bridge_input: dict[str, Any] | None,
    target_state: dict[str, Any],
    trigger_reason: str,
) -> dict[str, Any]:
    queries = collect_visual_product_queries(visual_bridge_input, target_state=target_state)
    if not queries:
        return {}
    uses_visual = bool(_as_dict(visual_bridge_input).get("present"))
    return {
        "schema_version": 1,
        "customer_goal": "客户引用了图片或最近图片中的车辆",
        "business_intent": "visual_product_reference",
        "requires_product_master": True,
        "requires_formal_knowledge": False,
        "requires_current_context": True,
        "low_authority_fast_allowed": False,
        "normalized_product_queries": queries,
        "evidence_lookup_mode": "product_master_exact_then_similar",
        "context_resolution": {
            "uses_visual_bridge": uses_visual,
            "uses_recent_visual_context": not uses_visual,
            "ambiguous_reference": False,
        },
        "brain_guidance": "视觉车型线索必须先查询商品库；客户可见回复仍由 Brain 生成。",
        "confidence": 0.74,
        "reason": trigger_reason or "visual_bridge_evidence_guard",
    }


def visual_bridge_fast_preflight_plan(
    *,
    settings: dict[str, Any],
    visual_bridge_input: dict[str, Any] | None,
    target_state: dict[str, Any],
    trigger_reason: str,
) -> dict[str, Any]:
    if not _as_bool(settings.get("visual_bridge_fast_preflight_enabled"), default=True):
        return {}
    reason = str(trigger_reason or "").strip()
    bridge = _as_dict(visual_bridge_input)
    if bridge.get("present"):
        # A new visual turn must stand on its own visual query.  Do not borrow
        # the previous car context when the current image is unrelated/unclear.
        current_only_state: dict[str, Any] = {}
        if not collect_visual_product_queries(visual_bridge_input, target_state=current_only_state):
            return {}
        return visual_bridge_evidence_guard_plan(
            visual_bridge_input=visual_bridge_input,
            target_state=current_only_state,
            trigger_reason=reason or "visual_bridge_fast_preflight",
        )
    if reason not in {"recent_visual_context_short_followup", "synthetic_visual_turn"}:
        return {}
    return visual_bridge_evidence_guard_plan(
        visual_bridge_input={},
        target_state=target_state,
        trigger_reason=reason,
    )


def compact_llm_status(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result.get(key)
        for key in (
            "ok",
            "provider",
            "model",
            "status",
            "error",
            "primary_provider",
            "primary_model",
        )
        if result.get(key) not in (None, "", [], {})
    }


def maybe_run_customer_service_brain_preflight(
    *,
    config: dict[str, Any],
    settings: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    visual_bridge_input: dict[str, Any] | None = None,
    force_reason: str = "",
) -> dict[str, Any]:
    started_at = time.time()
    single_brain_runtime_cleanup = bool(settings.get("_single_brain_runtime_cleanup"))
    preflight_settings = effective_customer_service_brain_preflight_settings(config=config, settings=settings)
    payload: dict[str, Any] = {
        "enabled": bool(preflight_settings.get("enabled")),
        "applied": False,
        "reason": "",
    }
    if not payload["enabled"]:
        payload["reason"] = "brain_preflight_disabled"
        payload["duration_seconds"] = round(time.time() - started_at, 4)
        return payload
    if force_reason:
        trigger = {"enabled": True, "reason": str(force_reason)}
    else:
        trigger = should_run_customer_service_brain_preflight(
            settings=preflight_settings,
            target_state=target_state,
            batch=batch,
            combined=combined,
            visual_bridge_input=visual_bridge_input,
        )
    payload["trigger"] = trigger
    if not trigger.get("enabled"):
        payload["reason"] = str(trigger.get("reason") or "brain_preflight_not_triggered")
        payload["duration_seconds"] = round(time.time() - started_at, 4)
        return payload
    fast_plan = visual_bridge_fast_preflight_plan(
        settings=preflight_settings,
        visual_bridge_input=visual_bridge_input,
        target_state=target_state,
        trigger_reason=str(trigger.get("reason") or ""),
    )
    if fast_plan:
        payload.update(
            {
                "applied": True,
                "reason": "visual_bridge_fast_preflight",
                "provider": "local_visual_bridge",
                "plan": normalize_customer_service_brain_preflight_plan(fast_plan),
                "llm_status": {
                    "ok": True,
                    "provider": "local_visual_bridge",
                    "status": "visual_bridge_fast_preflight",
                },
            }
        )
        payload["duration_seconds"] = round(time.time() - started_at, 4)
        return payload
    if single_brain_runtime_cleanup:
        # The live Brain First path has one semantic owner.  Keep the existing
        # preflight projection as a no-op, while preserving the independently
        # callable compatibility API for external/direct callers.
        payload["trigger"] = {"enabled": False, "reason": "brain_preflight_not_triggered"}
        payload["reason"] = "brain_preflight_not_triggered"
        payload["duration_seconds"] = round(time.time() - started_at, 4)
        return payload
    prompt = build_customer_service_brain_preflight_prompt(
        target_name=target_name,
        target_state=target_state,
        batch=batch,
        combined=combined,
        visual_bridge_input=visual_bridge_input,
    )
    result = run_customer_service_brain_preflight_llm(settings=preflight_settings, prompt=prompt)
    payload["llm_status"] = compact_llm_status(result)
    if result.get("ok") and isinstance(result.get("preflight_plan"), dict):
        payload.update(
            {
                "applied": True,
                "reason": "brain_preflight_ready",
                "provider": result.get("provider") or result.get("primary_provider"),
                "model": result.get("model") or result.get("primary_model"),
                "plan": normalize_customer_service_brain_preflight_plan(result.get("preflight_plan")),
            }
        )
        payload["duration_seconds"] = round(time.time() - started_at, 4)
        return payload
    guard_plan = visual_bridge_evidence_guard_plan(
        visual_bridge_input=visual_bridge_input,
        target_state=target_state,
        trigger_reason=str(trigger.get("reason") or ""),
    )
    if guard_plan:
        payload.update(
            {
                "applied": True,
                "reason": "visual_bridge_evidence_guard",
                "plan": guard_plan,
                "llm_unavailable_guard": True,
            }
        )
    else:
        payload["reason"] = str(result.get("error") or result.get("reason") or "brain_preflight_llm_unavailable")
    payload["duration_seconds"] = round(time.time() - started_at, 4)
    return payload


def brain_preflight_requires_authoritative_evidence(preflight: dict[str, Any] | None) -> bool:
    payload = _as_dict(preflight)
    if not payload.get("applied"):
        return False
    plan = _as_dict(payload.get("plan"))
    if any(
        bool(plan.get(key))
        for key in (
            "requires_product_master",
            "requires_formal_knowledge",
            "requires_current_context",
        )
    ):
        return True
    if plan.get("low_authority_fast_allowed") is False and plan.get("normalized_product_queries"):
        return True
    return False


def augment_evidence_text_with_brain_preflight_queries(combined: str, preflight: dict[str, Any] | None) -> str:
    text = str(combined or "").strip()
    payload = _as_dict(preflight)
    if not payload.get("applied"):
        return text
    plan = _as_dict(payload.get("plan"))
    queries = _unique_strings(plan.get("normalized_product_queries"), limit=5, max_chars=120)
    if not queries:
        return text
    lines = [text] if text else []
    for query in queries:
        if query and query not in text:
            lines.append(f"Brain Preflight商品查询线索：{query}")
    return "\n".join(line for line in lines if line).strip()


def compact_brain_preflight_for_prompt(preflight: dict[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(preflight)
    if not payload:
        return {}
    plan = _as_dict(payload.get("plan"))
    compact: dict[str, Any] = {
        "applied": bool(payload.get("applied")),
        "reason": _clip(payload.get("reason"), 80),
        "policy": "Brain Preflight只提供证据需求和检索线索，不授权商品事实，不生成客户可见回复。",
    }
    if plan:
        compact["plan"] = {
            "customer_goal": _clip(plan.get("customer_goal"), 100),
            "business_intent": _clip(plan.get("business_intent"), 60),
            "requires_product_master": bool(plan.get("requires_product_master", False)),
            "requires_formal_knowledge": bool(plan.get("requires_formal_knowledge", False)),
            "requires_current_context": bool(plan.get("requires_current_context", False)),
            "low_authority_fast_allowed": bool(plan.get("low_authority_fast_allowed", True)),
            "normalized_product_queries": _unique_strings(plan.get("normalized_product_queries"), limit=4, max_chars=100),
            "evidence_lookup_mode": _clip(plan.get("evidence_lookup_mode"), 80),
            "context_resolution": _as_dict(plan.get("context_resolution")),
            "brain_guidance": _clip(plan.get("brain_guidance"), 180),
            "confidence": _float_0_1(plan.get("confidence"), default=0.0),
        }
    return compact
