"""Focused offline checks for the single-Brain context/latency cleanup.

No upstream model or WeChat process is used.  The checks exercise the private
prompt projection and exceptional reviewer selector while preserving all
existing external payload contracts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
os.environ.setdefault("WECHAT_CLOUD_REQUIRED", "0")
os.environ.setdefault("WECHAT_CLOUD_STRICT_ONLINE", "0")

import customer_service_brain as brain_module  # noqa: E402
import customer_service_quality_reviewer as reviewer_module  # noqa: E402
from customer_service_brain_contract import normalize_brain_plan  # noqa: E402


def main() -> int:
    checks: list[Callable[[], dict[str, Any]]] = [
        check_polluted_context_keeps_recent_bidirectional_history,
        check_current_message_priority_is_one_general_semantic_rule,
        check_recent_history_compaction_keeps_latest_complete_turns,
        check_reviewer_ignores_wording_shape_and_context_phrases,
        check_reviewer_ignores_legacy_soft_handoff_advisories,
        check_reviewer_keeps_fact_and_hard_risk_boundaries,
        check_prompt_does_not_require_turn_semantics_schema,
        check_truncated_empty_fact_placeholder_is_not_a_claim,
        check_evidence_delay_does_not_shrink_brain_transport_budget,
        check_polluted_multi_round_sequence_keeps_each_current_turn,
        check_parallel_session_histories_remain_isolated,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            details = check()
            results.append({"name": check.__name__, "ok": True, "details": details})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def brain_settings() -> dict[str, Any]:
    return brain_module.effective_brain_settings(
        {
            "customer_service_brain": {
                "enabled": True,
                "mode": "brain_first",
                "provider": "manual_json",
                "history_char_budget": 2000,
            }
        }
    )


def polluted_evidence_pack() -> dict[str, Any]:
    history_lines = [
        "[客户] 先看看奥迪A4L",
        "[客服] A4L资料我整理下",
        "[客户] 又想问蔚来ES6",
        "[客服] ES6也可以对比",
        "[客户图片] 图片理解：一辆白色高尔夫，客户发送",
        "[客户] 这张图先不管",
        "[客服图片] 图片理解：一张奥迪A4L外观图，客服发送",
        "[客户] 你们几点下班",
        "[客服] 营业时间我按门店资料确认",
        "[客户] 再看看Polo",
        "[客服] Polo资料已收到",
        "[客户] 其实还是问A4L",
        "[客户图片] 图片理解：一辆黑色轿车，客户发送",
        "[客服图片] 图片理解：奥迪A4L内饰图，客服发送",
        "[客户] 奥迪A4L详细信息发我",
    ]
    return {
        "conversation": {
            "history_text": "\n".join(history_lines),
            "conversation_summary": "测试会话频繁切换车型，摘要只作背景。",
            "current_batch_text": "[客户] 奥迪A4L详细信息发我",
            "raw_conversation_id": "conv-polluted",
        },
        "audit_summary": {},
    }


def check_polluted_context_keeps_recent_bidirectional_history() -> dict[str, Any]:
    pack = polluted_evidence_pack()
    recovery = {
        "schema_version": 1,
        "applied": True,
        "mode": "latest_turn_only_candidate",
        "latest_message_ids": ["m-current"],
        "latest_customer_text": "奥迪A4L详细信息发我",
        "latest_message_type": "text",
    }
    brain_input = brain_module.build_brain_input(
        settings=brain_settings(),
        target_name="许聪",
        target_state={
            "conversation_context": {
                "last_product_id": "chejin_polo_2018_15l",
                "recent_product_ids": ["chejin_es6", "chejin_audi_a4l_2018_40tfsi"],
            }
        },
        batch=[{"id": "m-current", "sender": "customer", "content": "奥迪A4L详细信息发我"}],
        combined="奥迪A4L详细信息发我",
        raw_capture={
            "conversation": {"conversation_id": "conv-polluted", "chat_type": "private"},
            "context_recovery": recovery,
        },
        evidence_pack=pack,
    )
    conversation = brain_input.get("conversation") or {}
    current = brain_input.get("current_message") or {}
    assert current.get("clean_text") == "奥迪A4L详细信息发我"
    assert current.get("message_ids") == ["m-current"]
    assert (current.get("context_recovery") or {}).get("applied") is True
    assert "客服发送" in str(conversation.get("history_text") or "")
    assert "客户发送" in str(conversation.get("history_text") or "")
    assert (conversation.get("context") or {}).get("last_product_id") == "chejin_polo_2018_15l"

    slim = brain_module.slim_brain_input_for_prompt(brain_input, settings=brain_settings())
    prompt_history = str((slim.get("conversation") or {}).get("history_text") or "")
    assert "奥迪A4L内饰图" in prompt_history
    assert "黑色轿车" in prompt_history
    assert "先看看奥迪A4L" not in prompt_history
    return {"prompt_history_lines": len(prompt_history.splitlines()), "policy": current.get("context_priority_policy")}


def check_current_message_priority_is_one_general_semantic_rule() -> dict[str, Any]:
    social = brain_module.current_message_context_priority_policy({"must_reply": True, "category": "greeting"})
    business = brain_module.current_message_context_priority_policy({"must_reply": False, "category": ""})
    assert social == business
    assert social.startswith("current_message_first_semantic_context")
    assert "由Brain判断当前消息与历史的自然关系" in social
    assert "任何上下文断裂都不得导致沉默" in social
    assert "greeting" not in social
    assert "category" not in social
    return {"policy_chars": len(social)}


def check_recent_history_compaction_keeps_latest_complete_turns() -> dict[str, Any]:
    history = "\n".join(f"turn-{index:02d}-" + ("x" * 12) for index in range(20))
    compacted = brain_module._compact_recent_history_text(history, max_chars=180, max_turns=8)
    lines = compacted.splitlines()
    assert lines[-1].startswith("turn-19-")
    assert not any(line.startswith("turn-00-") for line in lines)
    assert len(compacted) <= 180
    assert len(lines) <= 8
    return {"chars": len(compacted), "lines": len(lines), "first": lines[0], "last": lines[-1]}


def safe_plan() -> dict[str, Any]:
    return normalize_brain_plan(
        {
            "can_answer": True,
            "answer_mode": "direct_answer",
            "evidence_used": {"common_sense_topics": ["conversation"]},
            "facts_claimed": [],
            "reply_segments": [
                "我明白您这轮问的是新的问题，我先按这条直接回答。",
                "前面的车型只在确实相关时参考，不会强行接回去。",
                "如果您指的是某张图，我只需要再确认一次是哪张。",
            ],
            "recommended_action": "send_reply",
            "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        }
    )


def check_reviewer_ignores_wording_shape_and_context_phrases() -> dict[str, Any]:
    should_review = reviewer_module.should_invoke_semantic_reviewer(
        plan=safe_plan(),
        current_message="不是，我刚才问的是另一台；另外这张图也不是前面那辆，你直接回答最近这条。？",
        evidence_pack={},
        deterministic_quality={
            "ok": True,
            "errors": [],
            "warnings": ["context_advisory:relative_context_product_drift", "split_reply_over_soft_total_limit"],
        },
        settings={"semantic_reviewer_long_reply_chars": 40},
    )
    assert should_review is False
    return {"invoked": should_review}


def check_reviewer_ignores_legacy_soft_handoff_advisories() -> dict[str, Any]:
    should_review = reviewer_module.should_invoke_semantic_reviewer(
        plan=safe_plan(),
        current_message="你觉得今天晚上吃火锅还是烤肉？",
        evidence_pack={
            "safety": {
                "must_handoff": True,
                "allowed_auto_reply": False,
                "reasons": ["no_relevant_business_evidence"],
            }
        },
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings={},
    )
    assert should_review is False
    return {"invoked": should_review, "reason": "soft_advisory_not_hard_safety"}


def check_reviewer_keeps_fact_and_hard_risk_boundaries() -> dict[str, Any]:
    ungrounded = safe_plan()
    ungrounded["answer_mode"] = "recommend_from_catalog"
    ungrounded["evidence_used"] = {"common_sense_topics": ["style"]}
    missing_authority = reviewer_module.should_invoke_semantic_reviewer(
        plan=ungrounded,
        current_message="推荐一台",
        evidence_pack={},
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings={},
    )
    risky = safe_plan()
    risky["risk"] = {"risk_level": "high", "risk_tags": ["price_commitment"], "needs_handoff": False}
    hard_risk = reviewer_module.should_invoke_semantic_reviewer(
        plan=risky,
        current_message="保证最低价吗",
        evidence_pack={},
        deterministic_quality={"ok": True, "errors": [], "warnings": []},
        settings={},
    )
    assert missing_authority is True
    assert hard_risk is True
    return {"missing_authority": missing_authority, "hard_risk": hard_risk}


def check_prompt_does_not_require_turn_semantics_schema() -> dict[str, Any]:
    assert "turn_semantics" not in brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT
    assert "intent schema" not in brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT.lower()
    assert "reply_segments(list[str]，1到3条非空完整句" in brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT
    assert "不要先写分析" in brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT
    assert "understanding、reply_strategy、self_check、reason都是可选字段" in brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT
    return {"schema_chars": len(brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT)}


def check_truncated_empty_fact_placeholder_is_not_a_claim() -> dict[str, Any]:
    plan = normalize_brain_plan(
        {
            "reply_segments": ["这台车商品库报价8.68万。"],
            "evidence_used": {"product_ids": ["product-1"]},
            "facts_claimed": [
                {
                    "fact_type": "price",
                    "value": "8.68万",
                    "source_level": "product_master",
                    "source_id": "product-1",
                },
                {"fact_type": "price", "value": "", "source_level": "", "source_id": ""},
            ],
            "recommended_action": "send_reply",
        }
    )
    assert len(plan.get("facts_claimed") or []) == 1
    assert (plan.get("facts_claimed") or [])[0].get("source_id") == "product-1"
    return {"retained_claims": 1, "dropped_empty_placeholders": 1}


def check_evidence_delay_does_not_shrink_brain_transport_budget() -> dict[str, Any]:
    captured: dict[str, Any] = {}
    clock = [100.0]
    original_monotonic = brain_module.time.monotonic
    original_evidence = brain_module.build_reply_evidence_pack
    original_run_brain_llm = brain_module.run_brain_llm

    def fake_monotonic() -> float:
        return clock[0]

    def fake_evidence(**kwargs: Any) -> dict[str, Any]:
        captured["evidence_text"] = kwargs.get("combined")
        clock[0] += 20.0
        return {
            "conversation": {"context": {}, "history": [], "history_count": 0},
            "knowledge": {"evidence": {"products": []}},
            "audit_summary": {},
            "safety": {},
            "intent_tags": [],
        }

    def fake_run_brain_llm(*, settings: dict[str, Any], brain_input: dict[str, Any]) -> dict[str, Any]:
        captured["settings"] = dict(settings)
        return {"ok": False, "error": "probe_after_budget_capture"}

    config = {
        "customer_service_brain": {
            "enabled": True,
            "mode": "brain_first",
            "provider": "openai",
            "timeout_seconds": 12,
            "large_prompt_timeout_seconds": 15,
            "very_large_prompt_timeout_seconds": 20,
            "fallback_timeout_seconds": 12,
            "quality_repair_timeout_seconds": 8,
            "semantic_reviewer_timeout_seconds": 8,
        }
    }
    try:
        brain_module.time.monotonic = fake_monotonic
        brain_module.build_reply_evidence_pack = fake_evidence
        brain_module.run_brain_llm = fake_run_brain_llm
        brain_module.maybe_run_customer_service_brain(
            config=config,
            target_name="许聪",
            target_state={"conversation_context": {}},
            batch=[
                {"id": "m-stock", "sender": "customer", "content": "现车还在吗"},
                {"id": "m-ping", "sender": "customer", "content": "在吗"},
            ],
            combined="客户连续补充同一个需求：\n- 现车还在吗\n- 在吗",
            decision={},
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={"conversation": {"conversation_id": "conv-budget", "chat_type": "private"}},
            customer_profile=None,
        )
    finally:
        brain_module.time.monotonic = original_monotonic
        brain_module.build_reply_evidence_pack = original_evidence
        brain_module.run_brain_llm = original_run_brain_llm

    effective = captured.get("settings") or {}
    assert captured.get("evidence_text") == "现车还在吗\n在吗"
    assert effective.get("timeout_seconds") == 12
    assert effective.get("fallback_timeout_seconds") == 12
    assert float(effective.get("_brain_turn_deadline_monotonic") or 0.0) > clock[0]
    return {
        "simulated_evidence_seconds": 20,
        "primary_timeout_seconds": effective.get("timeout_seconds"),
        "fallback_timeout_seconds": effective.get("fallback_timeout_seconds"),
        "evidence_text": captured.get("evidence_text"),
    }


def build_turn_input(*, conversation_id: str, history_text: str, message_id: str, current_text: str) -> dict[str, Any]:
    return brain_module.build_brain_input(
        settings=brain_settings(),
        target_name="许聪",
        target_state={"conversation_context": {"last_product_id": "historical-product"}},
        batch=[{"id": message_id, "sender": "customer", "content": current_text}],
        combined=current_text,
        raw_capture={"conversation": {"conversation_id": conversation_id, "chat_type": "private"}},
        evidence_pack={
            "conversation": {
                "history_text": history_text,
                "conversation_summary": "历史很长且可能包含已经过时的话题。",
                "current_batch_text": f"[客户] {current_text}",
                "raw_conversation_id": conversation_id,
            },
            "audit_summary": {},
        },
    )


def check_polluted_multi_round_sequence_keeps_each_current_turn() -> dict[str, Any]:
    history = str((polluted_evidence_pack().get("conversation") or {}).get("history_text") or "")
    turns = [
        "奥迪A4L详细信息发我",
        "换个问题，蔚来ES6呢",
        "这张无关图片是什么",
        "你们几点下班",
        "现在只说大众Polo的价格",
    ]
    observed: list[str] = []
    for index, current_text in enumerate(turns):
        brain_input = build_turn_input(
            conversation_id="conv-polluted-rounds",
            history_text=history,
            message_id=f"m-round-{index}",
            current_text=current_text,
        )
        current = brain_input.get("current_message") or {}
        assert current.get("clean_text") == current_text
        assert current.get("message_ids") == [f"m-round-{index}"]
        slim = brain_module.slim_brain_input_for_prompt(brain_input, settings=brain_settings())
        assert ((slim.get("current_message") or {}).get("clean_text")) == current_text
        assert reviewer_module.should_invoke_semantic_reviewer(
            plan=safe_plan(),
            current_message=current_text,
            evidence_pack={},
            deterministic_quality={"ok": True, "errors": [], "warnings": ["context_advisory:history_noise"]},
            settings={},
        ) is False
        observed.append(current_text)
        history = f"{history}\n[客户] {current_text}\n[客服] 本轮由Brain生成并完成最终润色。"
    return {"turn_count": len(observed), "last_current": observed[-1], "reviewer_calls_required": 0}


def check_parallel_session_histories_remain_isolated() -> dict[str, Any]:
    first = build_turn_input(
        conversation_id="conv-a",
        history_text="[客户] 只在A会话出现的奥迪A4L暗号",
        message_id="m-a",
        current_text="继续说这台",
    )
    second = build_turn_input(
        conversation_id="conv-b",
        history_text="[客户] 只在B会话出现的蔚来ES6暗号",
        message_id="m-b",
        current_text="继续说这台",
    )
    first_history = str((first.get("conversation") or {}).get("history_text") or "")
    second_history = str((second.get("conversation") or {}).get("history_text") or "")
    assert "A会话出现" in first_history and "B会话出现" not in first_history
    assert "B会话出现" in second_history and "A会话出现" not in second_history
    assert ((first.get("current_message") or {}).get("message_ids")) == ["m-a"]
    assert ((second.get("current_message") or {}).get("message_ids")) == ["m-b"]
    return {"sessions": 2, "isolated": True}


if __name__ == "__main__":
    raise SystemExit(main())
