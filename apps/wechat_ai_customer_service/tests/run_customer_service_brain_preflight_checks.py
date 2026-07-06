from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, APP_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_service_brain as brain_module  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context  # noqa: E402
from customer_service_brain_preflight import (  # noqa: E402
    augment_evidence_text_with_brain_preflight_queries,
    brain_preflight_requires_authoritative_evidence,
    maybe_run_customer_service_brain_preflight,
    normalize_customer_service_brain_preflight_plan,
)


TENANT_ID = "chejin"
QINPLUS_ID = "chejin_qinplus_2022_dmi55"
A4L_ID = "chejin_audi_a4l_2018_40tfsi"


def main() -> int:
    checks = [
        check_preflight_plan_normalization_requires_product_master,
        check_text_without_visual_context_does_not_trigger_preflight,
        check_short_social_text_gap_skips_preflight,
        check_text_product_with_existing_evidence_does_not_need_preflight,
        check_short_text_product_gap_uses_llm_preflight_query,
        check_visual_turn_preflight_forces_product_master_evidence,
        check_recent_visual_followup_reuses_visual_context_for_product_master,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            with tenant_context(TENANT_ID):
                check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def brain_plan_for_qinplus() -> dict[str, Any]:
    return {
        "can_answer": True,
        "understanding": {
            "user_intent": "询问图片里这款车是否有库存和型号",
            "normalized_entities": [{"raw": "图片里的车", "normalized": "比亚迪秦PLUS DM-i", "entity_type": "product"}],
        },
        "answer_mode": "quote_product_fact",
        "reply_strategy": {"style": "concise_human", "source": "product_master"},
        "evidence_used": {"product_ids": [QINPLUS_ID]},
        "facts_claimed": [
            {
                "fact_type": "product_name",
                "value": "2022款比亚迪秦PLUS DM-i 55KM",
                "source_level": "product_master",
                "source_id": QINPLUS_ID,
            },
            {
                "fact_type": "price",
                "value": "8.68万",
                "source_level": "product_master",
                "source_id": QINPLUS_ID,
            },
            {
                "fact_type": "inventory",
                "value": "1台",
                "source_level": "product_master",
                "source_id": QINPLUS_ID,
            },
        ],
        "reply_segments": [
            "这台库里对应的是2022款比亚迪秦PLUS DM-i 55KM。",
            "目前标价8.68万，库里还有1台，适合通勤省油这个方向。",
        ],
        "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        "recommended_action": "send_reply",
        "confidence": 0.88,
        "reason": "商品库命中图片车型。",
    }


def brain_plan_for_a4l() -> dict[str, Any]:
    return {
        "can_answer": True,
        "understanding": {
            "user_intent": "询问奥迪A4L是否有车源",
            "normalized_entities": [{"raw": "奥迪a四l", "normalized": "奥迪A4L", "entity_type": "product"}],
        },
        "answer_mode": "quote_product_fact",
        "reply_strategy": {"style": "concise_human", "source": "product_master"},
        "evidence_used": {"product_ids": [A4L_ID]},
        "facts_claimed": [
            {
                "fact_type": "product_name",
                "value": "2018款奥迪A4L 40 TFSI 进取型",
                "source_level": "product_master",
                "source_id": A4L_ID,
            },
            {
                "fact_type": "price",
                "value": "14.5万",
                "source_level": "product_master",
                "source_id": A4L_ID,
            },
            {
                "fact_type": "inventory",
                "value": "1台",
                "source_level": "product_master",
                "source_id": A4L_ID,
            },
        ],
        "reply_segments": [
            "有的，库里对应2018款奥迪A4L 40 TFSI进取型。",
            "目前标价14.5万，还有1台，南京门店看车需提前确认排期。",
        ],
        "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False},
        "recommended_action": "send_reply",
        "confidence": 0.88,
        "reason": "商品库命中A4L。",
    }


def preflight_plan_for_qinplus(*, uses_recent_visual_context: bool = False) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "customer_goal": "客户想确认图片里的车源情况",
        "business_intent": "product_availability",
        "requires_product_master": True,
        "requires_formal_knowledge": False,
        "requires_current_context": True,
        "low_authority_fast_allowed": False,
        "normalized_product_queries": ["比亚迪秦PLUS DM-i"],
        "evidence_lookup_mode": "product_master_exact_then_similar",
        "context_resolution": {
            "uses_visual_bridge": not uses_recent_visual_context,
            "uses_recent_visual_context": uses_recent_visual_context,
            "ambiguous_reference": False,
        },
        "brain_guidance": "先查商品库，再由 Brain 回复。",
        "confidence": 0.86,
        "reason": "图片车型线索需要商品库授权。",
    }


def preflight_plan_for_a4l() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "customer_goal": "客户想确认奥迪A4L有没有车源",
        "business_intent": "product_availability",
        "requires_product_master": True,
        "requires_formal_knowledge": False,
        "requires_current_context": False,
        "low_authority_fast_allowed": False,
        "normalized_product_queries": ["奥迪A4L"],
        "evidence_lookup_mode": "product_master_exact_then_similar",
        "context_resolution": {
            "uses_visual_bridge": False,
            "uses_recent_visual_context": False,
            "ambiguous_reference": False,
        },
        "brain_guidance": "把客户口语里的奥迪a四l按奥迪A4L查商品库。",
        "confidence": 0.84,
        "reason": "短文字里有车型口语混写，需要商品库授权。",
    }


def visual_bridge_for_qinplus() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "present": True,
        "vision_summary": "图片主体是一辆比亚迪秦PLUS DM-i 风格的白色轿车。",
        "classification": {"is_vehicle": True, "vehicle_confidence": 0.91, "unknown": False},
        "catalog_assist": {
            "normalized_vehicle_query": "比亚迪秦PLUS DM-i",
            "catalog_lookup_mode": "vehicle_exact_then_similar",
            "preferred_candidate_ids": [QINPLUS_ID],
            "candidate_names": ["2022款比亚迪秦PLUS DM-i 55KM"],
            "exact_candidate_id": QINPLUS_ID,
            "exact_candidate_name": "2022款比亚迪秦PLUS DM-i 55KM",
        },
        "intent_hints": {
            "wants_catalog_match": True,
            "wants_similar_recommendation": True,
            "needs_clarification": False,
        },
        "policy": "visual bridge input is advisory only; product facts must still be grounded in product_master",
    }


def base_config(
    *,
    preflight_candidate: dict[str, Any],
    mode: str = "adaptive",
    brain_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "customer_service_brain": {
            "enabled": True,
            "mode": "brain_first",
            "provider": "manual_json",
            "brain_plan": brain_plan or brain_plan_for_qinplus(),
            "min_confidence": 0.2,
            "require_evidence": True,
            "include_evidence_pack_in_audit": True,
            "include_brain_input_in_audit": True,
            "blocking_shadow_enabled": True,
            "preflight": {
                "enabled": True,
                "mode": mode,
                "provider": "manual_json",
                "candidate": preflight_candidate,
            },
        },
        "llm_reply_synthesis": {
            "enabled": True,
            "provider": "manual_json",
            "min_confidence": 0.2,
            "require_evidence": True,
            "max_catalog_candidates": 8,
        },
        "final_visible_llm_polish": {"enabled": False},
    }


def run_brain_case(
    *,
    combined: str,
    batch: list[dict[str, Any]],
    target_state: dict[str, Any],
    visual_bridge_input: dict[str, Any] | None,
    preflight_candidate: dict[str, Any],
    brain_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return brain_module.maybe_run_customer_service_brain(
        config=base_config(preflight_candidate=preflight_candidate, brain_plan=brain_plan),
        target_name="新数据测试",
        target_state=target_state,
        batch=batch,
        combined=combined,
        decision=None,
        reply_text="",
        intent_assist={},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        raw_capture={
            "conversation": {"conversation_id": "conv_preflight_qinplus", "chat_type": "group"},
            "messages": batch,
        },
        visual_bridge_input=visual_bridge_input,
    )


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def product_master_ids(event: dict[str, Any]) -> list[str]:
    pack = event.get("evidence_pack") if isinstance(event.get("evidence_pack"), dict) else {}
    knowledge = pack.get("knowledge") if isinstance(pack.get("knowledge"), dict) else {}
    product_master = knowledge.get("product_master") if isinstance(knowledge.get("product_master"), dict) else {}
    return [
        str(item.get("id") or "")
        for item in (product_master.get("items") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    ]


def check_preflight_plan_normalization_requires_product_master() -> None:
    plan = normalize_customer_service_brain_preflight_plan(
        {
            "requires_product_master": "true",
            "low_authority_fast_allowed": "false",
            "normalized_product_query": "比亚迪秦PLUS DM-i",
            "confidence": 1.8,
        }
    )
    assert_true(plan["requires_product_master"], f"product master should be required: {plan}")
    assert_true(not plan["low_authority_fast_allowed"], f"low authority fast should be blocked: {plan}")
    assert_equal(plan["normalized_product_queries"], ["比亚迪秦PLUS DM-i"], "query should normalize")
    assert_equal(plan["confidence"], 1.0, "confidence should be clamped")


def check_text_without_visual_context_does_not_trigger_preflight() -> None:
    preflight = maybe_run_customer_service_brain_preflight(
        config=base_config(preflight_candidate=preflight_plan_for_qinplus()),
        settings=brain_module.effective_brain_settings(base_config(preflight_candidate=preflight_plan_for_qinplus())),
        target_name="新数据测试",
        target_state={"conversation_context": {}},
        batch=[{"id": "m-hello", "sender": "许聪", "content": "你好"}],
        combined="你好",
        visual_bridge_input={},
    )
    assert_true(not preflight.get("applied"), f"plain text without visual context should not trigger: {preflight}")
    assert_true(not brain_preflight_requires_authoritative_evidence(preflight), f"plain text should not require evidence: {preflight}")
    assert_equal(augment_evidence_text_with_brain_preflight_queries("你好", preflight), "你好", "plain text should not be augmented")


def check_short_social_text_gap_skips_preflight() -> None:
    config = base_config(preflight_candidate=preflight_plan_for_a4l())
    settings = brain_module.effective_brain_settings(config)
    social = brain_module.text_evidence_gap_preflight_probe_decision(
        config=config,
        settings=settings,
        combined="在？",
        batch=[{"id": "m-social", "sender": "许聪", "content": "在？"}],
        target_state={"conversation_context": {}},
        evidence_pack=None,
        fast_profile={"enabled": True, "reason": "short_low_authority_turn"},
    )
    assert_true(not social.get("enabled"), f"short social ping must not trigger text-gap preflight: {social}")
    assert_equal(social.get("reason"), "social_turn_not_text_evidence_gap", "social ping should have explicit skip reason")
    product = brain_module.text_evidence_gap_preflight_probe_decision(
        config=config,
        settings=settings,
        combined="奥迪a四l有吗",
        batch=[{"id": "m-product", "sender": "许聪", "content": "奥迪a四l有吗"}],
        target_state={"conversation_context": {}},
        evidence_pack=None,
        fast_profile={"enabled": True, "reason": "short_low_authority_turn"},
    )
    assert_true(product.get("enabled"), f"short product-like text should still trigger text-gap preflight: {product}")


def check_text_product_with_existing_evidence_does_not_need_preflight() -> None:
    event = run_brain_case(
        combined="秦PLUS多少钱",
        batch=[{"id": "m-text-qinplus", "sender": "许聪", "content": "秦PLUS多少钱"}],
        target_state={"conversation_context": {}},
        visual_bridge_input={},
        preflight_candidate=preflight_plan_for_qinplus(),
    )
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"known text product should reply: {event}")
    assert_true(QINPLUS_ID in product_master_ids(event), f"existing text evidence should retrieve QinPLUS: {product_master_ids(event)}")
    assert_true(not (event.get("brain_preflight") or {}).get("applied"), f"known text evidence should not need preflight: {event.get('brain_preflight')}")
    assert_equal(
        (event.get("text_evidence_gap_preflight_probe_after_evidence") or {}).get("reason"),
        "product_master_already_present",
        "existing product evidence should skip text-gap preflight",
    )


def check_short_text_product_gap_uses_llm_preflight_query() -> None:
    event = run_brain_case(
        combined="奥迪a四l有吗",
        batch=[{"id": "m-text-a4l-gap", "sender": "许聪", "content": "奥迪a四l有吗"}],
        target_state={"conversation_context": {}},
        visual_bridge_input={},
        preflight_candidate=preflight_plan_for_a4l(),
        brain_plan=brain_plan_for_a4l(),
    )
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"text product gap should recover via preflight: {event}")
    assert_true((event.get("brain_preflight_text_gap") or {}).get("applied"), f"text gap preflight should apply: {event.get('brain_preflight_text_gap')}")
    assert_equal((event.get("low_authority_fast_profile") or {}).get("reason"), "brain_preflight_requires_evidence", "text gap should block empty fast evidence")
    assert_true(A4L_ID in product_master_ids(event), f"text gap should retrieve A4L product master: {product_master_ids(event)}")
    current = (((event.get("brain_input") or {}).get("current_message") or {}) if isinstance(event.get("brain_input"), dict) else {})
    assert_equal(current.get("clean_text"), "奥迪a四l有吗", "text gap preflight must keep original clean_text")


def check_visual_turn_preflight_forces_product_master_evidence() -> None:
    event = run_brain_case(
        combined="这款有吗",
        batch=[{"id": "m-img-qinplus", "sender": "许聪", "content": "这款有吗"}],
        target_state={"conversation_context": {}},
        visual_bridge_input=visual_bridge_for_qinplus(),
        preflight_candidate=preflight_plan_for_qinplus(),
    )
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"Brain should reply with product evidence: {event}")
    assert_true((event.get("brain_preflight") or {}).get("applied"), f"preflight should apply: {event.get('brain_preflight')}")
    assert_equal((event.get("low_authority_fast_profile") or {}).get("reason"), "brain_preflight_requires_evidence", "preflight should block empty fast profile")
    assert_true(QINPLUS_ID in product_master_ids(event), f"product master should include QinPLUS: {product_master_ids(event)}")
    current = (((event.get("brain_input") or {}).get("current_message") or {}) if isinstance(event.get("brain_input"), dict) else {})
    assert_equal(current.get("clean_text"), "这款有吗", "preflight must not pollute Brain clean_text")
    assert_true("Brain Preflight商品查询线索" not in str(current.get("clean_text") or ""), "query hint should stay out of clean_text")


def check_recent_visual_followup_reuses_visual_context_for_product_master() -> None:
    bridge = visual_bridge_for_qinplus()
    event = run_brain_case(
        combined="型号发我",
        batch=[{"id": "m-followup-model", "sender": "许聪", "content": "型号发我"}],
        target_state={
            "conversation_context": {},
            "visual_context_state": {
                "last_visual_summary": "图片主体是一辆比亚迪秦PLUS DM-i。",
                "last_visual_bridge_input": bridge,
            },
        },
        visual_bridge_input={},
        preflight_candidate=preflight_plan_for_qinplus(uses_recent_visual_context=True),
    )
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"follow-up should still reach Brain reply: {event}")
    preflight_plan = ((event.get("brain_preflight") or {}).get("plan") or {})
    assert_true((preflight_plan.get("context_resolution") or {}).get("uses_recent_visual_context"), f"preflight should use recent visual context: {preflight_plan}")
    assert_true(QINPLUS_ID in product_master_ids(event), f"follow-up should retrieve QinPLUS product master: {product_master_ids(event)}")
    current = (((event.get("brain_input") or {}).get("current_message") or {}) if isinstance(event.get("brain_input"), dict) else {})
    assert_equal(current.get("clean_text"), "型号发我", "recent visual follow-up must keep original clean_text")


if __name__ == "__main__":
    raise SystemExit(main())
