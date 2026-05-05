"""Structured intent assistant for WeChat customer-service messages.

The assistant is deliberately side-effect free. It returns JSON-shaped advice
that the guarded workflow can audit, compare with rule replies, or later route
through a human/LLM review path. It never operates WeChat directly.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from customer_data_capture import extract_customer_data
from apps.wechat_ai_customer_service.llm_config import read_secret, resolve_deepseek_base_url, resolve_deepseek_max_tokens, resolve_deepseek_tier_model
from apps.wechat_ai_customer_service.platform_understanding_rules import (
    intent_keywords,
    product_keywords,
    quantity_unit_pattern,
)


SCHEMA_VERSION = 1
ALLOWED_INTENTS = {
    "greeting",
    "small_talk",
    "quote_request",
    "quote_with_product_detail",
    "product_detail",
    "catalog_request",
    "company_info",
    "invoice_policy",
    "payment_policy",
    "logistics_policy",
    "after_sales_policy",
    "discount_request",
    "customer_data_complete",
    "customer_data_incomplete",
    "approval_required",
    "handoff_request",
    "unknown",
}
ALLOWED_ACTIONS = {
    "reply_greeting",
    "reply_small_talk",
    "ask_for_quote_details",
    "collect_contact_or_prepare_quote",
    "answer_from_evidence",
    "answer_company_info",
    "answer_invoice_policy",
    "answer_payment_policy",
    "answer_logistics_policy",
    "answer_after_sales_policy",
    "quote_from_product_knowledge",
    "ask_for_contact_fields",
    "capture_data_and_confirm",
    "ask_for_missing_fields",
    "handoff_for_approval",
    "handoff",
    "review_or_default_reply",
}
LLM_INTENT_RESPONSE_SCHEMA = {
    "schema_version": SCHEMA_VERSION,
    "type": "object",
    "required": [
        "intent",
        "confidence",
        "suggested_reply",
        "recommended_action",
        "safe_to_auto_send",
        "needs_handoff",
        "reason",
        "fields",
        "missing_fields",
    ],
    "properties": {
        "intent": {"type": "string", "enum": sorted(ALLOWED_INTENTS)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "suggested_reply": {"type": "string", "maxLength": 240},
        "recommended_action": {"type": "string", "enum": sorted(ALLOWED_ACTIONS)},
        "safe_to_auto_send": {"type": "boolean"},
        "needs_handoff": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 240},
        "fields": {"type": "object"},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


@dataclass(frozen=True)
class IntentAssistResult:
    enabled: bool
    mode: str
    intent: str
    confidence: float
    suggested_reply: str
    recommended_action: str
    safe_to_auto_send: bool
    needs_handoff: bool
    reason: str
    fields: dict[str, str]
    missing_fields: list[str]
    source: str = "heuristic"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--context-json", help="Optional JSON context from the workflow.")
    parser.add_argument("--emit-llm-prompt", action="store_true")
    parser.add_argument("--candidate-json", help="Validate an LLM candidate JSON string.")
    parser.add_argument("--candidate-file", type=Path, help="Validate an LLM candidate JSON file.")
    parser.add_argument("--call-deepseek", action="store_true", help="Call DeepSeek and validate the JSON response.")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    context = {}
    if args.context_json:
        context = json.loads(args.context_json)
    result = analyze_intent(args.text, context=context)
    if args.emit_llm_prompt:
        print_json(build_llm_prompt_pack(args.text, context=context, heuristic=result))
        return 0
    if args.candidate_json or args.candidate_file:
        if args.candidate_file:
            candidate = json.loads(args.candidate_file.read_text(encoding="utf-8"))
        else:
            candidate = json.loads(args.candidate_json or "{}")
        print_json(validate_llm_candidate(candidate, heuristic=result))
        return 0
    if args.call_deepseek:
        print_json(
            call_deepseek_advisory(
                args.text,
                context=context,
                heuristic=result,
                model=args.model,
                base_url=args.base_url,
                timeout=args.timeout,
            )
        )
        return 0
    print_json(asdict(result))
    return 0


def analyze_intent(text: str, context: dict[str, Any] | None = None) -> IntentAssistResult:
    context = context or {}
    normalized = normalize_text(text)
    data_capture = context.get("data_capture", {}) or {}
    if not data_capture:
        extraction = extract_customer_data(text, required_fields=context.get("required_fields") or ["name", "phone"])
        data_capture = {
            "is_customer_data": extraction.is_customer_data,
            "complete": extraction.complete,
            "fields": extraction.fields,
            "missing_required_fields": extraction.missing_required_fields,
        }
    fields = {
        str(key): str(value)
        for key, value in (data_capture.get("fields", {}) or {}).items()
        if value not in (None, "")
    }
    missing = [str(value) for value in data_capture.get("missing_required_fields", []) or []]

    if data_capture.get("is_customer_data"):
        if data_capture.get("complete"):
            return IntentAssistResult(
                enabled=True,
                mode="heuristic",
                intent="customer_data_complete",
                confidence=0.95,
                suggested_reply="客户资料已记录，我会尽快为您继续处理。",
                recommended_action="capture_data_and_confirm",
                safe_to_auto_send=True,
                needs_handoff=False,
                reason="structured_customer_fields_complete",
                fields=fields,
                missing_fields=[],
            )
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="customer_data_incomplete",
            confidence=0.9,
            suggested_reply=f"我看到了客户资料，但还缺少：{format_missing(missing)}。请补充后我再记录。",
            recommended_action="ask_for_missing_fields",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="structured_customer_fields_missing_required",
            fields=fields,
            missing_fields=missing,
        )

    if has_any(normalized, intent_keywords().get("handoff", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="handoff_request",
            confidence=0.85,
            suggested_reply="我已收到，这类问题我会转给人工继续处理。",
            recommended_action="handoff",
            safe_to_auto_send=True,
            needs_handoff=True,
            reason="handoff_or_sensitive_keyword",
            fields=fields,
            missing_fields=missing,
        )

    policy_result = analyze_policy_intent(normalized, fields, missing)
    if policy_result:
        return policy_result

    if needs_approval(normalized):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="approval_required",
            confidence=0.78,
            suggested_reply="这个价格/优惠我当前无法直接确认，我先帮您记录并请示上级，稍后给您准确回复。",
            recommended_action="handoff_for_approval",
            safe_to_auto_send=True,
            needs_handoff=True,
            reason="price_or_policy_approval_required",
            fields=fields,
            missing_fields=missing,
        )

    if has_quote_intent(normalized):
        if has_product_detail(normalized):
            return IntentAssistResult(
                enabled=True,
                mode="heuristic",
                intent="quote_with_product_detail",
                confidence=0.82,
                suggested_reply="收到，我会按您提供的产品和数量整理报价信息；如方便，也请补充联系人姓名和电话。",
                recommended_action="collect_contact_or_prepare_quote",
                safe_to_auto_send=True,
                needs_handoff=False,
                reason="quote_keyword_with_product_detail",
                fields=fields,
                missing_fields=missing,
            )
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="quote_request",
            confidence=0.86,
            suggested_reply="好的，请发我具体产品、数量和规格，我帮您确认报价。",
            recommended_action="ask_for_quote_details",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="quote_keyword",
            fields=fields,
            missing_fields=missing,
        )

    if has_product_detail(normalized):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="product_detail",
            confidence=0.72,
            suggested_reply="收到，请再补充联系人姓名和电话，我会一起记录。",
            recommended_action="ask_for_contact_fields",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="product_detail_without_required_contact",
            fields=fields,
            missing_fields=missing,
        )

    if has_any(normalized, intent_keywords().get("small_talk", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="small_talk",
            confidence=0.66,
            suggested_reply="没问题，您先慢慢看。需要价格、规格、发货或售后信息时，直接把商品和数量发我，我帮您核对。",
            recommended_action="reply_small_talk",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="small_talk_keyword",
            fields=fields,
            missing_fields=missing,
        )

    if has_any(normalized, intent_keywords().get("greeting", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="greeting",
            confidence=0.68,
            suggested_reply="你好，我在的，请问有什么可以帮您？",
            recommended_action="reply_greeting",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="greeting_keyword",
            fields=fields,
            missing_fields=missing,
        )

    return IntentAssistResult(
        enabled=True,
        mode="heuristic",
        intent="unknown",
        confidence=0.35,
        suggested_reply="收到，我先记录一下，稍后继续处理。",
        recommended_action="review_or_default_reply",
        safe_to_auto_send=False,
        needs_handoff=True,
        reason="no_confident_intent",
        fields=fields,
        missing_fields=missing,
    )


def analyze_policy_intent(
    normalized: str,
    fields: dict[str, str],
    missing: list[str],
) -> IntentAssistResult | None:
    if has_any(normalized, intent_keywords().get("company", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="company_info",
            confidence=0.82,
            suggested_reply="可以，我按公司资料回复您。",
            recommended_action="answer_company_info",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="company_info_keyword",
            fields=fields,
            missing_fields=missing,
        )
    if has_any(normalized, intent_keywords().get("invoice", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="invoice_policy",
            confidence=0.84,
            suggested_reply="可以，我按开票政策回复您。",
            recommended_action="answer_invoice_policy",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="invoice_policy_keyword",
            fields=fields,
            missing_fields=missing,
        )
    if has_any(normalized, intent_keywords().get("payment", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="payment_policy",
            confidence=0.82,
            suggested_reply="可以，我按付款和账户资料回复您。",
            recommended_action="answer_payment_policy",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="payment_policy_keyword",
            fields=fields,
            missing_fields=missing,
        )
    if has_any(normalized, intent_keywords().get("after_sales", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="after_sales_policy",
            confidence=0.78,
            suggested_reply="可以，我按售后政策回复您。",
            recommended_action="answer_after_sales_policy",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="after_sales_policy_keyword",
            fields=fields,
            missing_fields=missing,
        )
    if has_any(normalized, intent_keywords().get("shipping", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="logistics_policy",
            confidence=0.8,
            suggested_reply="可以，我按物流政策回复您。",
            recommended_action="answer_logistics_policy",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="logistics_policy_keyword",
            fields=fields,
            missing_fields=missing,
        )
    if has_any(normalized, intent_keywords().get("discount", [])):
        return IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="discount_request",
            confidence=0.78,
            suggested_reply="可以按公开阶梯价核算；超出公开政策的优惠需要请示。",
            recommended_action="quote_from_product_knowledge",
            safe_to_auto_send=True,
            needs_handoff=False,
            reason="discount_keyword",
            fields=fields,
            missing_fields=missing,
        )
    return None


def build_llm_prompt_pack(
    text: str,
    context: dict[str, Any] | None = None,
    heuristic: IntentAssistResult | None = None,
) -> dict[str, Any]:
    context = context or {}
    heuristic = heuristic or analyze_intent(text, context=context)
    return {
        "schema_version": SCHEMA_VERSION,
        "system": (
            "你是微信客服边界意图分析器，只输出符合 JSON schema 的对象。"
            "你不是最终拍板人，不要操作微信，不要生成多余解释。"
            "客服人设：谨慎、真实、礼貌、像真人微信客服，不端着，也不乱承诺。"
            "只能基于用户消息和 context 中的 evidence_pack、规则、资料抽取、产品知识、FAQ、服务人设做判断。"
            "evidence_pack 是本轮按需加载的证据包，优先级高于模型常识。"
            "边界处理规则："
            "1. 如果客户没有说标准商品名，但描述了用途、场景、规格或痛点，且 evidence 中有可关联产品/FAQ，"
            "可以用自然语言把客户说法关联到库内产品，再引用库内明确事实回复。"
            "2. 如果只是闲聊、寒暄、试探或轻度吐槽，回复要有人味，但要以客服身份轻轻带回商品、报价、资料收集或人工协助；"
            "不能假装朋友闲聊过头。"
            "3. 如果客户要求破例优惠、账期、月结、合同、退款赔偿、安装承诺、虚开发票、伪造资料、绕过规则，"
            "必须设置 needs_handoff=true，并建议请示上级或人工处理。"
            "4. 如果价格、库存、优惠、发货、售后政策在 context 中没有明确依据，必须 needs_handoff=true；不得编造答案。"
            "suggested_reply 必须简短、自然、适合微信发送，通常 1-3 句。"
        ),
        "user": {
            "message_text": text,
            "context": {
                "rule_decision": context.get("rule_decision", {}),
                "data_capture": context.get("data_capture", {}),
                "product_knowledge": context.get("product_knowledge", {}),
                "evidence_pack": context.get("evidence_pack", {}),
                "service_profile": context.get("service_profile", {}),
                "answer_policy": context.get("answer_policy", {}),
                "heuristic_intent": asdict(heuristic),
            },
            "task": (
                "判断客户意图，给出结构化 JSON 建议。"
                "如果可以自动回复，suggested_reply 就写最终可发送话术；"
                "如果需要人工，suggested_reply 写请示上级/人工接管的简短话术。"
            ),
        },
        "response_schema": LLM_INTENT_RESPONSE_SCHEMA,
    }


def validate_llm_candidate(
    candidate: dict[str, Any],
    heuristic: IntentAssistResult | None = None,
    max_reply_chars: int = 240,
) -> dict[str, Any]:
    errors = []
    if not isinstance(candidate, dict):
        return {"ok": False, "errors": ["candidate_must_be_object"], "candidate": candidate}

    required = LLM_INTENT_RESPONSE_SCHEMA["required"]
    allowed_keys = set(required)
    for key in candidate:
        if key not in allowed_keys:
            errors.append(f"unexpected_key:{key}")
    for key in required:
        if key not in candidate:
            errors.append(f"missing_{key}")

    intent = str(candidate.get("intent") or "")
    if intent and intent not in ALLOWED_INTENTS:
        errors.append(f"invalid_intent:{intent}")

    action = str(candidate.get("recommended_action") or "")
    if action and action not in ALLOWED_ACTIONS:
        errors.append(f"invalid_recommended_action:{action}")

    confidence = candidate.get("confidence")
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = -1
        errors.append("confidence_must_be_number")
    if confidence_value < 0 or confidence_value > 1:
        errors.append("confidence_out_of_range")

    reply = str(candidate.get("suggested_reply") or "")
    if len(reply) > max_reply_chars:
        errors.append("suggested_reply_too_long")
    if "\n" in reply and len(reply) > 80:
        errors.append("suggested_reply_should_be_short")

    reason = str(candidate.get("reason") or "")
    if len(reason) > 240:
        errors.append("reason_too_long")

    for key in ["safe_to_auto_send", "needs_handoff"]:
        if key in candidate and not isinstance(candidate.get(key), bool):
            errors.append(f"{key}_must_be_boolean")

    if "fields" in candidate and not isinstance(candidate.get("fields"), dict):
        errors.append("fields_must_be_object")
    if "missing_fields" in candidate and not isinstance(candidate.get("missing_fields"), list):
        errors.append("missing_fields_must_be_array")

    normalized = {
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence_value if confidence_value >= 0 else 0.0)),
        "suggested_reply": reply,
        "recommended_action": action,
        "safe_to_auto_send": bool(candidate.get("safe_to_auto_send")),
        "needs_handoff": bool(candidate.get("needs_handoff")),
        "reason": reason,
        "fields": {
            str(key): str(value)
            for key, value in (candidate.get("fields", {}) or {}).items()
            if value not in (None, "")
        }
        if isinstance(candidate.get("fields", {}), dict)
        else {},
        "missing_fields": [str(value) for value in candidate.get("missing_fields", []) or []]
        if isinstance(candidate.get("missing_fields", []), list)
        else [],
    }
    payload = {
        "ok": not errors,
        "schema_version": SCHEMA_VERSION,
        "errors": errors,
        "candidate": normalized,
    }
    if heuristic:
        payload["heuristic_compare"] = {
            "same_intent": normalized["intent"] == heuristic.intent,
            "heuristic_intent": heuristic.intent,
            "heuristic_action": heuristic.recommended_action,
            "llm_intent": normalized["intent"],
            "llm_action": normalized["recommended_action"],
            "reply_differs": bool(
                normalized["suggested_reply"]
                and normalized["suggested_reply"] != heuristic.suggested_reply
            ),
        }
    return payload


def call_deepseek_advisory(
    text: str,
    context: dict[str, Any] | None = None,
    heuristic: IntentAssistResult | None = None,
    model: str | None = None,
    base_url: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    api_key = read_secret("DEEPSEEK_API_KEY")
    selected_model = resolve_deepseek_tier_model(tier="flash", explicit_model=model, read_secret_fn=read_secret)
    selected_base_url = resolve_deepseek_base_url(explicit_base_url=base_url, read_secret_fn=read_secret)
    if not api_key:
        return {
            "ok": False,
            "provider": "deepseek",
            "error": "DEEPSEEK_API_KEY is not set",
            "model": selected_model,
            "base_url": selected_base_url,
        }

    heuristic = heuristic or analyze_intent(text, context=context)
    prompt_pack = build_llm_prompt_pack(text, context=context, heuristic=heuristic)
    response = post_deepseek_chat(
        api_key=api_key,
        base_url=selected_base_url,
        model=selected_model,
        prompt_pack=prompt_pack,
        timeout=timeout,
    )
    if not response.get("ok"):
        return response

    raw_text = str(response.get("response_text") or "")
    candidate = parse_json_object(raw_text)
    if candidate is None:
        response["ok"] = False
        response["error"] = "model_response_was_not_json_object"
        response["raw_response_text"] = raw_text[:1000]
        if apply_boundary_fallback(response, heuristic, "model_response_was_not_json_object"):
            response["raw_response_text"] = raw_text[:1000]
        return response

    response["validation"] = validate_llm_candidate(candidate, heuristic=heuristic)
    response["ok"] = bool(response["validation"].get("ok"))
    if not response["ok"]:
        apply_boundary_fallback(response, heuristic, "model_candidate_failed_schema_validation")
    return response


def apply_boundary_fallback(response: dict[str, Any], heuristic: IntentAssistResult, reason: str) -> bool:
    candidate = boundary_fallback_candidate(heuristic, reason)
    if not candidate:
        return False
    response["validation"] = validate_llm_candidate(candidate, heuristic=heuristic)
    response["ok"] = bool(response["validation"].get("ok"))
    response["fallback"] = "heuristic_boundary"
    response["fallback_reason"] = reason
    return bool(response["ok"])


def boundary_fallback_candidate(heuristic: IntentAssistResult, reason: str) -> dict[str, Any] | None:
    boundary_intents = {"approval_required", "handoff_request"}
    boundary_actions = {"handoff_for_approval", "handoff"}
    if not (
        heuristic.needs_handoff
        or heuristic.intent in boundary_intents
        or heuristic.recommended_action in boundary_actions
    ):
        return None

    intent = heuristic.intent if heuristic.intent in ALLOWED_INTENTS else "approval_required"
    action = heuristic.recommended_action if heuristic.recommended_action in ALLOWED_ACTIONS else "handoff"
    if intent == "approval_required":
        action = "handoff_for_approval"
    reply = str(heuristic.suggested_reply or "").strip()
    if not reply:
        reply = "这个需要我先请示上级确认，确认后再给您准确回复。"
    if len(reply) > 240:
        reply = reply[:237] + "..."
    try:
        confidence = float(heuristic.confidence)
    except (TypeError, ValueError):
        confidence = 0.78
    return {
        "intent": intent,
        "confidence": max(0.0, min(1.0, confidence)),
        "suggested_reply": reply,
        "recommended_action": action,
        "safe_to_auto_send": True,
        "needs_handoff": True,
        "reason": f"{reason}; fallback_to_heuristic_boundary",
        "fields": dict(heuristic.fields or {}),
        "missing_fields": list(heuristic.missing_fields or []),
    }


def post_deepseek_chat(
    api_key: str,
    base_url: str,
    model: str,
    prompt_pack: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    schema_text = json.dumps(prompt_pack["response_schema"], ensure_ascii=False)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt_pack["system"]},
            {
                "role": "user",
                "content": (
                    json.dumps(prompt_pack["user"], ensure_ascii=False)
                    + "\n\nJSON schema:\n"
                    + schema_text
                    + "\n\n只输出 JSON 对象，不要 Markdown，不要解释。"
                ),
            },
        ],
        "temperature": 0.2,
        "max_tokens": resolve_deepseek_max_tokens(1200, read_secret_fn=read_secret),
        "stream": False,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, timeout)) as response:
            raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return {
                "ok": True,
                "provider": "deepseek",
                "model": model,
                "base_url": base_url,
                "status": response.status,
                "response_text": content,
                "usage": data.get("usage", {}),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "provider": "deepseek",
            "model": model,
            "base_url": base_url,
            "status": exc.code,
            "error": summarize_error_body(body),
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": "deepseek",
            "model": model,
            "base_url": base_url,
            "error": repr(exc),
        }


def parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def summarize_error_body(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body[:500]


def normalize_text(text: str) -> str:
    replacements = {
        "：": ":",
        "，": ",",
        "。": ".",
        "；": ";",
        "\r\n": "\n",
        "\r": "\n",
    }
    normalized = text.lower()
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    return normalized.strip()


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text for keyword in keywords)


def has_quote_intent(text: str) -> bool:
    return has_any(text, product_keywords("quote") or intent_keywords().get("quote", []))


def has_product_detail(text: str) -> bool:
    if has_any(
        text,
        [*intent_keywords().get("product", []), *intent_keywords().get("scene_product", []), *product_keywords("spec")],
    ):
        return True
    return bool(re.search(rf"\d+\s*({quantity_unit_pattern()})", text, re.IGNORECASE))


def needs_approval(text: str) -> bool:
    if has_any(text, product_keywords("approval")):
        return True
    return bool(re.search(rf"按\s*\d+\s*(?:{quantity_unit_pattern()})?\s*的?价", text, re.IGNORECASE))


def format_missing(fields: list[str]) -> str:
    labels = {
        "name": "姓名",
        "phone": "电话",
        "address": "地址",
        "product": "产品",
        "quantity": "数量",
        "spec": "规格",
        "budget": "预算",
        "note": "备注",
    }
    values = [labels.get(field, field) for field in fields]
    return "、".join(values) or "必要信息"


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
