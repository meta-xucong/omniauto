"""Guarded LLM reply synthesis for natural WeChat customer questions."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from apps.wechat_ai_customer_service.llm_config import (
    normalize_deepseek_model_tier,
    read_secret,
    resolve_deepseek_base_url,
    resolve_deepseek_max_tokens,
    resolve_deepseek_model,
    resolve_deepseek_tier_model,
    resolve_deepseek_timeout,
)
from apps.wechat_ai_customer_service.platform_safety_rules import enabled_prompt_instructions, load_platform_safety_rules
from customer_intent_assist import parse_json_object
from llm_reply_guard import guard_synthesized_reply
from reply_evidence_builder import build_reply_evidence_pack


DEFAULT_MAX_REPLY_CHARS = 520
DEFAULT_FLASH_PROFILE = {
    "max_history_messages": 12,
    "history_char_budget": 5000,
    "max_rag_hits": 3,
    "max_rag_text_chars": 360,
    "max_catalog_candidates": 5,
    "max_tokens": 1800,
    "temperature": 0.35,
}
DEFAULT_PRO_PROFILE = {
    "max_history_messages": 40,
    "history_char_budget": 12000,
    "max_rag_hits": 5,
    "max_rag_text_chars": 900,
    "max_catalog_candidates": 8,
    "max_tokens": 3200,
    "temperature": 0.38,
}
DEFAULT_PRO_INTENT_TAGS = {"payment", "invoice", "after_sales", "handoff", "customer_data"}
DEFAULT_PRO_SAFETY_REASONS = {
    "matched_faq_requires_handoff",
    "invoice_amount_entity",
    "contract_risk",
    "payment_boundary",
    "price_approval_required",
}
RUN_LLM_CALL_COUNT = 0


RESPONSE_SCHEMA = {
    "type": "object",
    "required": [
        "can_answer",
        "reply",
        "confidence",
        "recommended_action",
        "needs_handoff",
        "used_evidence",
        "rag_used",
        "structured_used",
        "uncertain_points",
        "risk_tags",
        "reason",
    ],
    "properties": {
        "can_answer": {"type": "boolean"},
        "reply": {"type": "string"},
        "confidence": {"type": "number"},
        "recommended_action": {"type": "string", "enum": ["send_reply", "handoff", "handoff_for_approval", "fallback_existing"]},
        "needs_handoff": {"type": "boolean"},
        "used_evidence": {"type": "array", "items": {"type": "string"}},
        "rag_used": {"type": "boolean"},
        "structured_used": {"type": "boolean"},
        "uncertain_points": {"type": "array", "items": {"type": "string"}},
        "risk_tags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
}


def maybe_synthesize_reply(
    *,
    config: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    decision: Any,
    reply_text: str,
    intent_assist: dict[str, Any],
    rag_reply: dict[str, Any],
    llm_reply: dict[str, Any],
    product_knowledge: dict[str, Any],
    data_capture: dict[str, Any],
    raw_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("llm_reply_synthesis", {}) or {}
    payload: dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "applied": False,
        "shadow_mode": bool(settings.get("shadow_mode", False)),
    }
    if not payload["enabled"]:
        payload["reason"] = "llm_reply_synthesis_disabled"
        return payload
    if data_capture.get("is_customer_data"):
        payload["reason"] = "customer_data_decision_is_deterministic"
        return payload

    flash_settings = synthesis_settings_for_tier(settings, "flash")
    evidence_pack = build_reply_evidence_pack(
        config=config_with_synthesis_settings(config, flash_settings),
        target_name=target_name,
        target_state=target_state,
        batch=batch,
        combined=combined,
        decision=decision,
        reply_text=reply_text,
        intent_assist=intent_assist,
        rag_reply=rag_reply,
        llm_reply=llm_reply,
        product_knowledge=product_knowledge,
        data_capture=data_capture,
        raw_capture=raw_capture,
    )
    model_route = select_synthesis_model_route(settings=settings, evidence_pack=evidence_pack)
    effective_settings = synthesis_settings_for_tier(settings, str(model_route.get("tier") or "pro"))
    if str(model_route.get("tier") or "") != "flash":
        evidence_pack = build_reply_evidence_pack(
            config=config_with_synthesis_settings(config, effective_settings),
            target_name=target_name,
            target_state=target_state,
            batch=batch,
            combined=combined,
            decision=decision,
            reply_text=reply_text,
            intent_assist=intent_assist,
            rag_reply=rag_reply,
            llm_reply=llm_reply,
            product_knowledge=product_knowledge,
            data_capture=data_capture,
            raw_capture=raw_capture,
        )
        model_route = select_synthesis_model_route(settings=settings, evidence_pack=evidence_pack)
        effective_settings = synthesis_settings_for_tier(settings, str(model_route.get("tier") or "pro"))
    payload["evidence_summary"] = evidence_pack.get("audit_summary", {})
    payload["intent_tags"] = evidence_pack.get("intent_tags", [])
    payload["model_tier"] = model_route.get("tier")
    payload["model_routing"] = model_route
    if settings.get("include_evidence_pack_in_audit", False):
        payload["evidence_pack"] = evidence_pack

    cost_skip = cost_control_skip_reason(settings=effective_settings, evidence_pack=evidence_pack, decision=decision)
    if cost_skip:
        payload["reason"] = cost_skip
        payload["cost_control"] = {"skipped": True, "reason": cost_skip}
        return payload

    result = synthesize_reply(settings=effective_settings, evidence_pack=evidence_pack, model_route=model_route)
    payload["provider"] = result.get("provider")
    payload["model"] = result.get("model")
    payload["model_tier"] = result.get("model_tier") or payload.get("model_tier")
    payload["model_routing"] = result.get("model_route") or payload.get("model_routing")
    if "usage" in result:
        payload["llm_usage"] = result.get("usage") or {}
    if "prompt_estimate" in result:
        payload["prompt_estimate"] = result.get("prompt_estimate") or {}
    payload["llm_status"] = {
        key: result.get(key)
        for key in ("ok", "error", "status", "fallback", "raw_response_text", "attempt", "max_attempts", "model_tier")
        if key in result
    }
    if not result.get("ok"):
        payload["reason"] = "llm_synthesis_unavailable"
        return payload

    candidate = result.get("candidate", {}) or {}
    guard = guard_synthesized_reply(candidate=candidate, evidence_pack=evidence_pack, settings=settings)
    payload["candidate"] = compact_candidate(candidate)
    payload["guard"] = guard_for_audit(guard)
    if payload["shadow_mode"]:
        payload["reason"] = "shadow_mode"
        return payload
    if not guard.get("allowed"):
        payload["reason"] = str(guard.get("reason") or "guard_rejected")
        return payload

    action = str(guard.get("action") or "")
    if action == "send_reply":
        raw_reply = truncate_reply(str(guard.get("reply") or ""), settings)
        payload.update(
            {
                "applied": True,
                "rule_name": "llm_synthesis_reply",
                "reason": str(guard.get("reason") or "guarded_llm_synthesis"),
                "needs_handoff": False,
                "raw_reply_text": raw_reply,
                "reply_text": raw_reply,
            }
        )
        return payload
    if action == "handoff":
        raw_reply = truncate_reply(str(guard.get("reply") or ""), settings)
        payload.update(
            {
                "applied": True,
                "rule_name": "llm_synthesis_handoff",
                "reason": str(guard.get("reason") or "llm_synthesis_handoff"),
                "needs_handoff": True,
                "raw_reply_text": raw_reply,
                "reply_text": raw_reply,
            }
        )
        return payload

    payload["reason"] = str(guard.get("reason") or "guard_fallback")
    return payload


def synthesize_reply(
    *,
    settings: dict[str, Any],
    evidence_pack: dict[str, Any],
    model_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = str(settings.get("provider") or "manual_json")
    if provider == "manual_json":
        return synthesize_from_manual_json(settings)
    if provider == "deepseek":
        return call_deepseek_synthesis(settings=settings, evidence_pack=evidence_pack, model_route=model_route)
    return {"ok": False, "provider": provider, "error": "unsupported_synthesis_provider"}


def synthesize_from_manual_json(settings: dict[str, Any]) -> dict[str, Any]:
    candidate = settings.get("candidate")
    if isinstance(candidate, dict):
        return {"ok": True, "provider": "manual_json", "candidate": candidate}
    path_value = str(settings.get("candidate_json_path") or "").strip()
    if not path_value:
        return {"ok": False, "provider": "manual_json", "error": "candidate_json_path_missing"}
    try:
        with open(path_value, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        return {"ok": False, "provider": "manual_json", "error": repr(exc)}
    candidate = payload.get("candidate", payload) if isinstance(payload, dict) else {}
    if not isinstance(candidate, dict):
        return {"ok": False, "provider": "manual_json", "error": "candidate_not_object"}
    return {"ok": True, "provider": "manual_json", "candidate": candidate}


def synthesis_settings_for_tier(settings: dict[str, Any], tier: str) -> dict[str, Any]:
    normalized = normalize_deepseek_model_tier(tier)
    profile = dict(DEFAULT_PRO_PROFILE if normalized == "pro" else DEFAULT_FLASH_PROFILE)
    configured_profiles = settings.get("profiles") if isinstance(settings.get("profiles"), dict) else {}
    configured_profile = configured_profiles.get(normalized) if isinstance(configured_profiles.get(normalized), dict) else {}
    profile.update(configured_profile)
    merged = dict(settings)
    merged.update(profile)
    merged["model_tier"] = normalized
    return merged


def config_with_synthesis_settings(config: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    next_config = dict(config)
    next_config["llm_reply_synthesis"] = settings
    return next_config


def select_synthesis_model_route(*, settings: dict[str, Any], evidence_pack: dict[str, Any]) -> dict[str, Any]:
    routing = settings.get("model_routing") if isinstance(settings.get("model_routing"), dict) else {}
    if not routing and str(settings.get("model") or "").strip():
        tier = infer_tier_from_model_name(str(settings.get("model") or ""))
        return {"tier": tier, "profile": tier, "reasons": ["legacy_explicit_model"]}
    if routing.get("enabled", True) is False:
        return {"tier": "pro", "profile": "pro", "reasons": ["legacy_model_routing_disabled"]}

    force = normalize_route_tier(routing.get("force_model_tier") or settings.get("force_model_tier"))
    if force:
        return {"tier": force, "profile": force, "reasons": ["forced_by_config"]}

    default_tier = normalize_route_tier(routing.get("default_tier") or settings.get("default_model_tier")) or "flash"
    reasons: list[str] = []
    intent_tags = {str(item) for item in evidence_pack.get("intent_tags", []) or [] if str(item)}
    safety = evidence_pack.get("safety") if isinstance(evidence_pack.get("safety"), dict) else {}
    safety_reasons = {str(item) for item in safety.get("reasons", []) or [] if str(item)}
    audit_summary = evidence_pack.get("audit_summary") if isinstance(evidence_pack.get("audit_summary"), dict) else {}
    pro_intents = set_from_config(routing.get("pro_intent_tags"), DEFAULT_PRO_INTENT_TAGS)
    pro_safety_reasons = set_from_config(routing.get("pro_safety_reasons"), DEFAULT_PRO_SAFETY_REASONS)

    if intent_tags & pro_intents:
        reasons.append("authority_or_handoff_intent")
    if safety_reasons & pro_safety_reasons:
        reasons.append("high_risk_safety_reason")
    if bool(safety.get("must_handoff")) and routing.get("pro_when_must_handoff", True) is not False:
        reasons.append("must_handoff_quality_priority")
    if (
        routing.get("pro_when_rag_only_authority", True) is not False
        and int(audit_summary.get("structured_evidence_count") or 0) <= 0
        and int(audit_summary.get("rag_hit_count") or 0) > 0
        and intent_tags & {"quote", "discount", "stock", "shipping", "invoice", "payment", "after_sales", "handoff"}
    ):
        reasons.append("rag_only_authority_topic")
    if (
        routing.get("pro_when_long_context", False) is True
        and int((evidence_pack.get("conversation") or {}).get("history_count") or 0) >= positive_int_from_config(routing.get("pro_min_history_count"), 80)
    ):
        reasons.append("long_conversation_context")
    if (
        routing.get("pro_when_long_message", False) is True
        and len(str(evidence_pack.get("current_message") or "")) >= positive_int_from_config(routing.get("pro_min_message_chars"), 420)
    ):
        reasons.append("long_or_complex_message")

    tier = "pro" if reasons else default_tier
    return {"tier": tier, "profile": tier, "reasons": reasons or ["default_flash_normal_service_reply"]}


def resolve_synthesis_model(*, settings: dict[str, Any], model_route: dict[str, Any]) -> str:
    routing = settings.get("model_routing") if isinstance(settings.get("model_routing"), dict) else {}
    tier = normalize_route_tier(model_route.get("tier") or settings.get("model_tier")) or "pro"
    if not routing and str(settings.get("model") or "").strip():
        return resolve_deepseek_model(explicit_model=str(settings.get("model") or ""), read_secret_fn=read_secret)
    if routing.get("enabled", True) is not False:
        explicit = str(routing.get(f"{tier}_model") or settings.get(f"{tier}_model") or "").strip()
        return resolve_deepseek_tier_model(tier=tier, explicit_model=explicit, read_secret_fn=read_secret)
    return resolve_deepseek_model(explicit_model=str(settings.get("model") or ""), read_secret_fn=read_secret)


def normalize_route_tier(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return normalize_deepseek_model_tier(text)


def infer_tier_from_model_name(model: str) -> str:
    text = str(model or "").lower()
    if "flash" in text:
        return "flash"
    return "pro"


def set_from_config(value: Any, default: set[str]) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value if str(item)}
    if isinstance(value, str) and value.strip():
        return {item.strip() for item in value.split(",") if item.strip()}
    return set(default)


def positive_int_from_config(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def cost_control_skip_reason(*, settings: dict[str, Any], evidence_pack: dict[str, Any], decision: Any) -> str:
    controls = settings.get("cost_controls") if isinstance(settings.get("cost_controls"), dict) else {}
    if controls.get("enabled", True) is False:
        return ""
    if cost_call_cap_reached(settings):
        return "llm_cost_cap_reached"
    if controls.get("skip_llm_when_deterministic_reply", False) and is_safe_deterministic_reply(settings, evidence_pack, decision):
        return "cost_control_skipped_safe_deterministic_reply"
    return ""


def is_safe_deterministic_reply(settings: dict[str, Any], evidence_pack: dict[str, Any], decision: Any) -> bool:
    if not bool(getattr(decision, "matched", False)):
        return False
    if bool(getattr(decision, "need_handoff", False)):
        return False
    safety = evidence_pack.get("safety") if isinstance(evidence_pack.get("safety"), dict) else {}
    if safety.get("must_handoff"):
        return False
    controls = settings.get("cost_controls") if isinstance(settings.get("cost_controls"), dict) else {}
    allowed_rules = set_from_config(controls.get("safe_deterministic_rule_names"), set())
    return bool(allowed_rules and str(getattr(decision, "rule_name", "") or "") in allowed_rules)


def cost_call_cap_reached(settings: dict[str, Any]) -> bool:
    controls = settings.get("cost_controls") if isinstance(settings.get("cost_controls"), dict) else {}
    cap = int(controls.get("max_llm_calls_per_run") or 0)
    return cap > 0 and RUN_LLM_CALL_COUNT >= cap


def note_llm_call(settings: dict[str, Any]) -> None:
    controls = settings.get("cost_controls") if isinstance(settings.get("cost_controls"), dict) else {}
    if controls.get("enabled", True) is False:
        return
    global RUN_LLM_CALL_COUNT
    RUN_LLM_CALL_COUNT += 1


def estimate_prompt_pack(prompt_pack: dict[str, Any]) -> dict[str, int]:
    user_text = json.dumps(prompt_pack.get("user", {}), ensure_ascii=False)
    schema_text = json.dumps(prompt_pack.get("response_schema", {}), ensure_ascii=False)
    char_count = len(str(prompt_pack.get("system") or "")) + len(user_text) + len(schema_text)
    return {"prompt_chars": char_count, "rough_prompt_tokens": max(1, char_count // 2)}


def call_deepseek_synthesis(
    *,
    settings: dict[str, Any],
    evidence_pack: dict[str, Any],
    model_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    api_key = read_secret("DEEPSEEK_API_KEY")
    model_route = model_route or select_synthesis_model_route(settings=settings, evidence_pack=evidence_pack)
    model = resolve_synthesis_model(settings=settings, model_route=model_route)
    base_url = resolve_deepseek_base_url(explicit_base_url=str(settings.get("base_url") or ""), read_secret_fn=read_secret)
    if not api_key:
        return {
            "ok": False,
            "provider": "deepseek",
            "model": model,
            "model_tier": model_route.get("tier"),
            "model_route": model_route,
            "base_url": base_url,
            "error": "DEEPSEEK_API_KEY is not set",
        }

    prompt_pack = build_synthesis_prompt_pack(evidence_pack, settings=settings)
    prompt_estimate = estimate_prompt_pack(prompt_pack)
    if cost_call_cap_reached(settings):
        return {
            "ok": False,
            "provider": "deepseek",
            "model": model,
            "model_tier": model_route.get("tier"),
            "model_route": model_route,
            "base_url": base_url,
            "prompt_estimate": prompt_estimate,
            "error": "llm_cost_cap_reached",
            "fallback": "existing_reply",
        }
    response = post_deepseek_synthesis_with_retry(
        settings=settings,
        api_key=api_key,
        base_url=base_url,
        model=model,
        prompt_pack=prompt_pack,
    )
    note_llm_call(settings)
    response["model"] = model
    response["model_tier"] = model_route.get("tier")
    response["model_route"] = model_route
    response["base_url"] = base_url
    response["prompt_estimate"] = prompt_estimate
    if not response.get("ok"):
        return response
    raw_text = str(response.get("response_text") or "")
    candidate = parse_json_object(raw_text)
    if candidate is None:
        response["ok"] = False
        response["error"] = "model_response_was_not_json_object"
        response["raw_response_text"] = raw_text[:1000]
        return response
    response["candidate"] = candidate
    return response


def post_deepseek_synthesis_with_retry(
    *,
    settings: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    prompt_pack: dict[str, Any],
) -> dict[str, Any]:
    retry_count = resolve_synthesis_retry_count(settings)
    attempts = retry_count + 1
    last_response: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        response = post_deepseek_synthesis(
            api_key=api_key,
            base_url=base_url,
            model=model,
            prompt_pack=prompt_pack,
            timeout=int(settings.get("timeout_seconds") or resolve_deepseek_timeout()),
            max_tokens=resolve_synthesis_max_tokens(settings),
            temperature=resolve_synthesis_temperature(settings),
        )
        response["attempt"] = attempt
        response["max_attempts"] = attempts
        if response.get("ok") or attempt >= attempts or not is_transient_synthesis_error(response):
            return response
        last_response = response
        time.sleep(min(1.5 * attempt, 5.0))
    return last_response or {"ok": False, "provider": "deepseek", "error": "deepseek_retry_exhausted", "attempt": attempts}


def build_synthesis_prompt_pack(evidence_pack: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    platform_rules_result = load_platform_safety_rules(settings)
    platform_rules = platform_rules_result.get("item", {})
    return {
        "schema_version": 1,
        "platform_safety_rules": {
            "ok": platform_rules_result.get("ok"),
            "path": platform_rules_result.get("path"),
            "title": platform_rules.get("title", "平台底线规则"),
            "description": platform_rules.get("description", ""),
        },
        "system": (
            "你是受控的微信客服综合回复器。你的目标不是套固定模板，"
            "而是像一位真实、克制、懂当前客户业务的客服一样，先听懂客户的真实意图，"
            "再结合客户自己的正式知识、商品库、商品专属规则、RAG经验、共享公共知识和历史上下文，"
            "组织一段自然、可信、可发送的微信回复。"
            "你必须让DeepSeek的理解能力充分发挥作用：要处理口语、错别字、上下文指代、含糊需求和比较型问题，"
            "并主动把RAG经验作为一等证据参与判断。"
            "不要假设客户所属行业；行业、商品、门店、流程和专属规则只能来自 evidence_pack。"
            "具体业务边界和回复规则来自 platform_safety_rules 与 evidence_pack。"
            "只输出JSON对象，不要Markdown。"
        ),
        "user": {
            "task": "根据证据包生成一条受控但自然的微信客服回复。",
            "rules": enabled_prompt_instructions(platform_rules),
            "platform_rules": enabled_prompt_instructions(platform_rules),
            "evidence_pack": evidence_pack,
        },
        "response_schema": RESPONSE_SCHEMA,
    }


def post_deepseek_synthesis(
    *,
    api_key: str,
    base_url: str,
    model: str,
    prompt_pack: dict[str, Any],
    timeout: int,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_pack["system"]},
            {
                "role": "user",
                "content": (
                    json.dumps(prompt_pack["user"], ensure_ascii=False)
                    + "\n\nJSON schema:\n"
                    + json.dumps(prompt_pack["response_schema"], ensure_ascii=False)
                    + "\n\n只输出JSON对象，不要Markdown，不要解释。"
                ),
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return {
                "ok": True,
                "provider": "deepseek",
                "status": response.status,
                "response_text": content,
                "usage": data.get("usage", {}),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "provider": "deepseek", "status": exc.code, "error": body[:1000]}
    except Exception as exc:
        return {"ok": False, "provider": "deepseek", "error": repr(exc)}


def truncate_reply(reply: str, settings: dict[str, Any]) -> str:
    max_chars = int(settings.get("max_reply_chars", DEFAULT_MAX_REPLY_CHARS) or DEFAULT_MAX_REPLY_CHARS)
    clean = " ".join(str(reply or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 1)].rstrip() + "..."


def resolve_synthesis_max_tokens(settings: dict[str, Any]) -> int:
    configured = settings.get("max_tokens")
    try:
        parsed = int(configured)
    except (TypeError, ValueError):
        parsed = 0
    if parsed > 0:
        return max(1200, parsed)
    return max(3000, resolve_deepseek_max_tokens(3000, read_secret_fn=read_secret))


def resolve_synthesis_temperature(settings: dict[str, Any]) -> float:
    try:
        parsed = float(settings.get("temperature", 0.38))
    except (TypeError, ValueError):
        parsed = 0.38
    return max(0.0, min(0.8, parsed))


def resolve_synthesis_retry_count(settings: dict[str, Any]) -> int:
    try:
        parsed = int(settings.get("retry_count", 2))
    except (TypeError, ValueError):
        parsed = 2
    return max(0, min(5, parsed))


def is_transient_synthesis_error(response: dict[str, Any]) -> bool:
    if response.get("ok"):
        return False
    try:
        status = int(response.get("status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    error = str(response.get("error") or "").lower()
    return any(marker in error for marker in ("incompleteread", "timed out", "timeout", "temporarily", "connection reset", "remote end"))


def compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "can_answer": candidate.get("can_answer"),
        "confidence": candidate.get("confidence"),
        "recommended_action": candidate.get("recommended_action"),
        "needs_handoff": candidate.get("needs_handoff"),
        "used_evidence": candidate.get("used_evidence", []),
        "rag_used": candidate.get("rag_used"),
        "structured_used": candidate.get("structured_used"),
        "uncertain_points": candidate.get("uncertain_points", []),
        "risk_tags": candidate.get("risk_tags", []),
        "reason": candidate.get("reason"),
        "reply": truncate_reply(str(candidate.get("reply") or ""), {"max_reply_chars": 700}),
    }


def guard_for_audit(guard: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed": guard.get("allowed"),
        "action": guard.get("action"),
        "reason": guard.get("reason"),
        "authority_tags": guard.get("authority_tags", []),
        "confidence": guard.get("confidence"),
        "min_confidence": guard.get("min_confidence"),
        "errors": guard.get("errors", []),
    }
