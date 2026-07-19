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
import customer_service_brain_preflight as preflight_module  # noqa: E402
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
        check_normal_text_turn_builds_evidence_once_without_preflight_llm,
        check_visual_fast_preflight_uses_bridge_without_llm,
        check_visual_fast_preflight_does_not_borrow_recent_context_for_new_unclear_image,
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


def visual_bridge_for_unrelated_image() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "present": True,
        "vision_summary": "unrelated outdoor image without a clear vehicle subject",
        "classification": {"is_vehicle": False, "vehicle_confidence": 0.05, "unknown": False},
        "catalog_assist": {
            "normalized_vehicle_query": "",
            "catalog_lookup_mode": "none",
            "preferred_candidate_ids": [],
            "candidate_names": [],
            "exact_candidate_id": "",
            "exact_candidate_name": "",
        },
        "intent_hints": {
            "wants_catalog_match": False,
            "wants_similar_recommendation": False,
            "needs_clarification": False,
        },
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
            "timeout_seconds": 12,
            "fallback_timeout_seconds": 10,
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
    assert_true(not social.get("enabled"), f"universal Brain path must not trigger text-gap preflight: {social}")
    assert_equal(social.get("reason"), "brain_first_universal_single_evidence_pipeline", "text gap must be a compatibility no-op")
    product = brain_module.text_evidence_gap_preflight_probe_decision(
        config=config,
        settings=settings,
        combined="奥迪a四l有吗",
        batch=[{"id": "m-product", "sender": "许聪", "content": "奥迪a四l有吗"}],
        target_state={"conversation_context": {}},
        evidence_pack=None,
        fast_profile={"enabled": True, "reason": "short_low_authority_turn"},
    )
    assert_true(not product.get("enabled"), f"product wording must not select a second semantic route: {product}")
    assert_equal(product.get("reason"), "brain_first_universal_single_evidence_pipeline", "product text must use the same Brain path")
    trade_in = brain_module.text_evidence_gap_preflight_probe_decision(
        config=config,
        settings=settings,
        combined="2018年朗逸置换怎么估价",
        batch=[{"id": "m-trade-in", "sender": "许聪", "content": "2018年朗逸置换怎么估价"}],
        target_state={"conversation_context": {}},
        evidence_pack={"knowledge": {"evidence": {"products": []}}},
        fast_profile={"enabled": False},
    )
    assert_true(not trade_in.get("enabled"), f"customer-owned trade-in must not trigger an inventory gap probe: {trade_in}")
    assert_equal(trade_in.get("reason"), "brain_first_universal_single_evidence_pipeline", "all text turns should share one evidence path")
    trade_in_fast = brain_module.text_evidence_gap_preflight_probe_decision(
        config=config,
        settings=settings,
        combined="你先给我估个准价，能抵多少车款？",
        batch=[{"id": "m-trade-in-fast", "sender": "许聪", "content": "你先给我估个准价，能抵多少车款？"}],
        target_state={"conversation_context": {}},
        fast_profile={"enabled": True, "reason": "short_low_authority_turn"},
    )
    assert_true(not trade_in_fast.get("enabled"), f"short trade-in follow-up must not pay an inventory preflight tail: {trade_in_fast}")
    assert_equal(trade_in_fast.get("reason"), "brain_first_universal_single_evidence_pipeline", "fast profile must not reactivate the old probe")


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
    assert_true(
        "text_evidence_gap_preflight_probe_after_evidence" not in event,
        "the universal path must not run a second post-evidence semantic probe",
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
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"text product gap should resolve through the single Brain/evidence path: {event}")
    text_gap = event.get("brain_preflight_text_gap") or {}
    assert_true(not text_gap.get("applied"), f"normal text turns must not add a preflight LLM call: {text_gap}")
    assert_true(
        "brain_preflight_text_gap" not in event,
        f"the universal event must not carry a second text-gap semantic stage: {text_gap}",
    )
    assert_true(A4L_ID in product_master_ids(event), f"text gap should retrieve A4L product master: {product_master_ids(event)}")
    current = (((event.get("brain_input") or {}).get("current_message") or {}) if isinstance(event.get("brain_input"), dict) else {})
    assert_equal(current.get("clean_text"), "奥迪a四l有吗", "text gap preflight must keep original clean_text")


def check_normal_text_turn_builds_evidence_once_without_preflight_llm() -> None:
    original_builder = brain_module.build_reply_evidence_pack
    original_fast_builder = brain_module.build_low_authority_fast_evidence_pack
    original_brain_llm = brain_module.run_brain_llm
    original_preflight_llm = preflight_module.run_customer_service_brain_preflight_llm
    calls = {"evidence": 0, "brain_llm": 0, "preflight_llm": 0, "brain_timeout": 0, "fallback_timeout": 0}

    def counted_builder(**kwargs: Any) -> dict[str, Any]:
        calls["evidence"] += 1
        return original_builder(**kwargs)

    def counted_fast_builder(**kwargs: Any) -> dict[str, Any]:
        calls["evidence"] += 1
        return original_fast_builder(**kwargs)

    def forbidden_preflight_llm(**_kwargs: Any) -> dict[str, Any]:
        calls["preflight_llm"] += 1
        raise AssertionError("normal Brain First text turn must not invoke a preflight LLM")

    def counted_brain_llm(**kwargs: Any) -> dict[str, Any]:
        calls["brain_llm"] += 1
        call_settings = kwargs.get("settings") if isinstance(kwargs.get("settings"), dict) else {}
        calls["brain_timeout"] = int(call_settings.get("timeout_seconds") or 0)
        calls["fallback_timeout"] = int(call_settings.get("fallback_timeout_seconds") or 0)
        return original_brain_llm(**kwargs)

    try:
        brain_module.build_reply_evidence_pack = counted_builder
        brain_module.build_low_authority_fast_evidence_pack = counted_fast_builder
        brain_module.run_brain_llm = counted_brain_llm
        preflight_module.run_customer_service_brain_preflight_llm = forbidden_preflight_llm
        event = run_brain_case(
            combined="奥迪a四l详细信息发我",
            batch=[{"id": "m-single-evidence", "sender": "许聪", "content": "奥迪a四l详细信息发我"}],
            target_state={"conversation_context": {"last_product_id": QINPLUS_ID}},
            visual_bridge_input={},
            preflight_candidate=preflight_plan_for_a4l(),
            brain_plan=brain_plan_for_a4l(),
        )
    finally:
        brain_module.build_reply_evidence_pack = original_builder
        brain_module.build_low_authority_fast_evidence_pack = original_fast_builder
        brain_module.run_brain_llm = original_brain_llm
        preflight_module.run_customer_service_brain_preflight_llm = original_preflight_llm

    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"single evidence path should remain sendable: {event}")
    assert_equal(calls["evidence"], 1, "one planner turn must build authoritative evidence exactly once")
    assert_equal(calls["brain_llm"], 1, "normal text turn must invoke the main Brain exactly once")
    assert_equal(calls["preflight_llm"], 0, "normal text turn must use zero preflight LLM calls")
    assert_equal(calls["brain_timeout"], 12, "evidence work must not shrink the configured primary Brain timeout")
    assert_equal(calls["fallback_timeout"], 10, "evidence work must not shrink the configured fallback Brain timeout")


def check_visual_fast_preflight_uses_bridge_without_llm() -> None:
    original_run = preflight_module.run_customer_service_brain_preflight_llm
    calls = {"count": 0}

    def fail_if_called(**kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        raise AssertionError("visual bridge fast preflight should not call LLM")

    config = base_config(preflight_candidate=preflight_plan_for_qinplus())
    settings = brain_module.effective_brain_settings(config)
    try:
        preflight_module.run_customer_service_brain_preflight_llm = fail_if_called
        preflight = maybe_run_customer_service_brain_preflight(
            config=config,
            settings=settings,
            target_name="target",
            target_state={"conversation_context": {}},
            batch=[{"id": "m-img-qinplus-fast", "sender": "customer", "content": "this one?"}],
            combined="this one?",
            visual_bridge_input=visual_bridge_for_qinplus(),
        )
    finally:
        preflight_module.run_customer_service_brain_preflight_llm = original_run

    assert_equal(calls["count"], 0, "visual bridge fast preflight must avoid extra preflight LLM")
    assert_true(preflight.get("applied"), f"visual fast preflight should apply: {preflight}")
    assert_equal(preflight.get("reason"), "visual_bridge_fast_preflight", "visual fast path should be explicit")
    assert_equal((preflight.get("llm_status") or {}).get("status"), "visual_bridge_fast_preflight", "audit should show local fast path")
    plan = preflight.get("plan") if isinstance(preflight.get("plan"), dict) else {}
    assert_true(plan.get("requires_product_master"), f"visual fast plan should require product master: {plan}")
    assert_true(bool(plan.get("normalized_product_queries")), f"visual fast plan should carry product queries: {plan}")


def check_visual_fast_preflight_does_not_borrow_recent_context_for_new_unclear_image() -> None:
    original_run = preflight_module.run_customer_service_brain_preflight_llm
    calls = {"count": 0}

    def fake_llm(**kwargs: Any) -> dict[str, Any]:
        calls["count"] += 1
        return {
            "ok": True,
            "provider": "unit_preflight",
            "model": "unit",
            "preflight_plan": {
                "customer_goal": "new unclear image",
                "business_intent": "general_chat",
                "requires_product_master": False,
                "requires_formal_knowledge": False,
                "requires_current_context": False,
                "low_authority_fast_allowed": True,
                "normalized_product_queries": [],
                "evidence_lookup_mode": "none",
                "context_resolution": {
                    "uses_visual_bridge": True,
                    "uses_recent_visual_context": False,
                    "ambiguous_reference": False,
                },
                "confidence": 0.8,
                "reason": "current visual has no vehicle query",
            },
        }

    config = base_config(preflight_candidate=preflight_plan_for_qinplus())
    settings = brain_module.effective_brain_settings(config)
    settings["_single_brain_runtime_cleanup"] = True
    try:
        preflight_module.run_customer_service_brain_preflight_llm = fake_llm
        preflight = maybe_run_customer_service_brain_preflight(
            config=config,
            settings=settings,
            target_name="target",
            target_state={
                "conversation_context": {},
                "visual_context_state": {"last_visual_bridge_input": visual_bridge_for_qinplus()},
            },
            batch=[{"id": "m-img-unrelated", "sender": "customer", "content": "[image]"}],
            combined="",
            visual_bridge_input=visual_bridge_for_unrelated_image(),
        )
    finally:
        preflight_module.run_customer_service_brain_preflight_llm = original_run

    assert_equal(calls["count"], 0, "single-Brain runtime must not add an LLM preflight for an unclear new image")
    assert_equal(preflight.get("reason"), "brain_preflight_not_triggered", "unclear new image should stay on the main Brain path")
    assert_true(not preflight.get("applied"), f"unclear current image must not borrow recent product context: {preflight}")


def check_visual_turn_preflight_forces_product_master_evidence() -> None:
    event = run_brain_case(
        combined="这款有吗",
        batch=[{"id": "m-img-qinplus", "sender": "许聪", "content": "这款有吗"}],
        target_state={"conversation_context": {}},
        visual_bridge_input=visual_bridge_for_qinplus(),
        preflight_candidate=preflight_plan_for_qinplus(),
    )
    assert_equal(event.get("rule_name"), "customer_service_brain_reply", f"Brain should reply with product evidence: {event}")
    assert_true(not (event.get("brain_preflight") or {}).get("applied"), f"visual input must stay on the universal Brain path: {event.get('brain_preflight')}")
    assert_equal(
        (event.get("brain_preflight") or {}).get("reason"),
        "brain_first_universal_single_evidence_pipeline",
        "the image plugin bridge must enrich the one evidence snapshot without a second semantic stage",
    )
    assert_equal((event.get("low_authority_fast_profile") or {}).get("reason"), "brain_first_universal_pipeline", "visual text must not select a topic profile")
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
    assert_equal(
        (event.get("brain_preflight") or {}).get("reason"),
        "brain_first_universal_single_evidence_pipeline",
        "recent visual follow-up must not reactivate semantic preflight",
    )
    assert_true(QINPLUS_ID in product_master_ids(event), f"follow-up should retrieve QinPLUS product master: {product_master_ids(event)}")
    current = (((event.get("brain_input") or {}).get("current_message") or {}) if isinstance(event.get("brain_input"), dict) else {})
    assert_equal(current.get("clean_text"), "型号发我", "recent visual follow-up must keep original clean_text")


if __name__ == "__main__":
    raise SystemExit(main())
