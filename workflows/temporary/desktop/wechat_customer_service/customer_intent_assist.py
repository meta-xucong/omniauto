"""Structured intent assistant for WeChat customer-service messages.

The assistant is deliberately side-effect free. It returns JSON-shaped advice
that the guarded workflow can audit, compare with rule replies, or later route
through a human/LLM review path. It never operates WeChat directly.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from customer_data_capture import extract_customer_data


SCHEMA_VERSION = 1
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
ALLOWED_INTENTS = {
    "greeting",
    "quote_request",
    "quote_with_product_detail",
    "product_detail",
    "customer_data_complete",
    "customer_data_incomplete",
    "approval_required",
    "handoff_request",
    "unknown",
}
ALLOWED_ACTIONS = {
    "reply_greeting",
    "ask_for_quote_details",
    "collect_contact_or_prepare_quote",
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

    if has_any(normalized, ["投诉", "退款", "退货", "赔偿", "生气", "不满意", "人工"]):
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

    if has_any(normalized, ["你好", "您好", "hello", "在吗"]):
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
            "你是微信客服意图分析器，只输出符合 JSON schema 的对象。"
            "你不是最终拍板人，不要操作微信，不要生成多余解释。"
            "只能基于用户消息和 context 中的规则、资料抽取、产品知识、FAQ、服务人设做判断。"
            "如果价格、库存、优惠、发货、售后政策在 context 中没有明确依据，或客户要求破例/让利/特批，"
            "必须设置 needs_handoff=true，并建议请示上级；不得编造答案。"
            "suggested_reply 必须简短、克制、像真实客服。"
        ),
        "user": {
            "message_text": text,
            "context": {
                "rule_decision": context.get("rule_decision", {}),
                "data_capture": context.get("data_capture", {}),
                "product_knowledge": context.get("product_knowledge", {}),
                "service_profile": context.get("service_profile", {}),
                "answer_policy": context.get("answer_policy", {}),
                "heuristic_intent": asdict(heuristic),
            },
            "task": "判断客户意图，给出结构化 JSON 建议。不要直接发送消息。",
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
    selected_model = model or read_secret("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    selected_base_url = base_url or read_secret("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
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
        return response

    response["validation"] = validate_llm_candidate(candidate, heuristic=heuristic)
    response["ok"] = bool(response["validation"].get("ok"))
    return response


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
        "temperature": 0,
        "max_tokens": 320,
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


def read_secret(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
            return str(registry_value)
    except Exception:
        return ""


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
    return has_any(text, ["价格", "报价", "多少钱", "费用", "单价", "总价"])


def has_product_detail(text: str) -> bool:
    if has_any(text, ["产品", "商品", "规格", "型号", "数量", "采购", "冰箱", "净水器"]):
        return True
    return bool(re.search(r"\d+\s*(个|件|台|套|箱|条|kg|千克|斤)", text, re.IGNORECASE))


def needs_approval(text: str) -> bool:
    approval_keywords = ["特批", "破例", "请示", "申请", "抹零", "送", "再便宜", "便宜点", "最低价"]
    if has_any(text, approval_keywords):
        return True
    return bool(re.search(r"按\s*\d+\s*(个|件|台|套|箱|条|把|瓶)?\s*的?价", text, re.IGNORECASE))


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
