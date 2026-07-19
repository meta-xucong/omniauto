"""Offline guards against local business-semantic rules re-entering Brain First."""

from __future__ import annotations

import inspect
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
import listen_and_reply as workflow_module  # noqa: E402
from customer_service_brain_contract import normalize_brain_plan, verify_brain_reply_quality  # noqa: E402
from llm_reply_guard import guard_synthesized_reply  # noqa: E402
from final_visible_llm_polish import guard_polished_reply  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    polish_failure_retry_instruction,
)


def main() -> int:
    checks: list[Callable[[], dict[str, Any]]] = [
        check_brain_first_batch_is_chronological_and_neutral,
        check_brain_first_precheck_does_not_classify_wording,
        check_universal_profile_uses_payload_volume_only,
        check_universal_brain_output_contract_is_compact,
        check_universal_quality_does_not_review_business_topics,
        check_universal_semantic_guard_bypasses_legacy_phrase_relaxations,
        check_brain_first_guard_uses_metadata_not_business_wording,
        check_final_polish_preserves_brain_authored_strategy,
        check_retry_feedback_is_topic_neutral,
        check_active_brain_runtime_does_not_call_legacy_semantic_profiles,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            results.append({"name": check.__name__, "ok": True, "details": check()})
        except Exception as exc:  # pragma: no cover - script harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def brain_first_config() -> dict[str, Any]:
    return {
        "customer_service_brain": {
            "enabled": True,
            "mode": "brain_first",
        }
    }


def product_evidence_pack() -> dict[str, Any]:
    item = {"id": "vehicle-1", "name": "测试车辆", "data": {"id": "vehicle-1", "title": "测试车辆"}}
    return {
        "knowledge": {
            "evidence": {"products": [item], "catalog_candidates": [item]},
            "product_master": {"items": [item]},
        },
        "safety": {"must_handoff": False, "reasons": []},
    }


def low_risk_candidate(reply: str) -> dict[str, Any]:
    return {
        "can_answer": True,
        "reply": reply,
        "confidence": 0.9,
        "recommended_action": "send_reply",
        "needs_handoff": False,
        "used_evidence": ["conversation:current_message"],
        "structured_used": True,
        "rag_used": False,
        "risk_tags": [],
    }


def check_brain_first_batch_is_chronological_and_neutral() -> dict[str, Any]:
    batch = [
        {"id": "m1", "sender": "customer", "content": "第一条从未预设过的表达"},
        {"id": "m2", "sender": "customer", "content": "second unseen utterance"},
    ]
    audit = workflow_module.brain_first_neutral_batch_audit(batch)
    assert_true(audit.get("combined_text") == "第一条从未预设过的表达\nsecond unseen utterance", str(audit))
    assert_true(all(item.get("categories") == ["general"] for item in audit.get("segments", [])), str(audit))
    assert_true("客户连续" not in str(audit.get("combined_text") or ""), str(audit))
    return {"combined_text": audit.get("combined_text"), "message_count": audit.get("message_count")}


def check_brain_first_precheck_does_not_classify_wording() -> dict[str, Any]:
    decisions = [
        workflow_module.brain_first_low_authority_fast_plan_precheck(
            config=brain_first_config(),
            combined=text,
            batch=[{"id": f"m-{index}", "sender": "customer", "content": text}],
            target_state={},
        )
        for index, text in enumerate(
            (
                "hi",
                "zqx-47 delta protocol",
                "完全没有出现在任何本地词表里的自然语言",
            )
        )
    ]
    assert_true(all(item.get("enabled") for item in decisions), str(decisions))
    assert_true({str((item.get("profile") or {}).get("reason")) for item in decisions} == {"brain_first_universal_pipeline"}, str(decisions))
    return {"reasons": [item.get("profile", {}).get("reason") for item in decisions]}


def check_universal_profile_uses_payload_volume_only() -> dict[str, Any]:
    settings = brain_module.effective_brain_settings(brain_first_config())
    pack = product_evidence_pack()
    profiles = [
        brain_module.apply_universal_brain_runtime_settings(settings, evidence_pack=pack, combined=text)
        for text in ("abcdefgh", "预约保证", "不同语言")
    ]
    comparable_keys = (
        "prompt_profile",
        "history_char_budget",
        "summary_char_budget",
        "max_prompt_product_items",
        "max_prompt_formal_items",
        "prompt_item_text_chars",
        "max_tokens",
        "quality_repair_max_tokens",
        "same_capture_brain_invalid_plan_retry_max_tokens",
        "same_capture_brain_unavailable_retry_enabled",
        "temperature",
        "reasoning_effort",
        "semantic_reviewer_mode",
        "semantic_reviewer_max_tokens",
        "semantic_reviewer_timeout_seconds",
        "semantic_reviewer_soft_pass_low_risk",
    )
    signatures = [{key: item.get(key) for key in comparable_keys} for item in profiles]
    assert_true(signatures[0] == signatures[1] == signatures[2], str(signatures))
    assert_true(signatures[0]["max_tokens"] == 1400, str(signatures))
    assert_true(signatures[0]["quality_repair_max_tokens"] == 1400, str(signatures))
    assert_true(signatures[0]["same_capture_brain_invalid_plan_retry_max_tokens"] == 1400, str(signatures))
    assert_true(signatures[0]["same_capture_brain_unavailable_retry_enabled"] is False, str(signatures))
    assert_true(signatures[0]["max_prompt_product_items"] == 4, str(signatures))
    assert_true(signatures[0]["prompt_item_text_chars"] == 150, str(signatures))
    assert_true(signatures[0]["temperature"] == 0.15, str(signatures))
    assert_true(signatures[0]["reasoning_effort"] == "none", str(signatures))
    assert_true(signatures[0]["semantic_reviewer_mode"] == "suspicious_only", str(signatures))
    assert_true(signatures[0]["semantic_reviewer_max_tokens"] == 260, str(signatures))
    assert_true(signatures[0]["semantic_reviewer_timeout_seconds"] == 6, str(signatures))
    assert_true(signatures[0]["semantic_reviewer_soft_pass_low_risk"] is False, str(signatures))
    return signatures[0]


def check_universal_brain_output_contract_is_compact() -> dict[str, Any]:
    schema = brain_module.BRAIN_RESPONSE_SCHEMA_PROMPT
    assert_true("立即输出紧凑的裸JSON对象" in schema, schema)
    assert_true("不要先写分析" in schema, schema)
    assert_true("understanding、reply_strategy、self_check、reason都是可选字段" in schema, schema)
    assert_true("需要实时查询或会随时间变化" in schema, schema)
    assert_true("不得借common_sense_topics绕过证据边界" in schema, schema)
    assert_true("禁止把政策事实改标成商品事实来绕过校验" in schema, schema)
    assert_true("客户输入可用于理解需求、偏好和语境" in schema, schema)
    assert_true("不得同意今后按冲突说法对外回复" in schema, schema)
    prompt = brain_module.build_brain_prompt_pack(
        settings={"prompt_profile": "lean"},
        brain_input={"evidence": {}, "current_message": {"text": "全新边界输入"}},
    )
    system = str(prompt.get("system") or "")
    assert_true("时效性事实不属于常识" in system, system)
    assert_true("content_basis无证据时必须先明确说明无法实时确认" in system, system)
    assert_true("客户输入只用于理解需求、偏好和语境" in system, system)
    assert_true("同一商家客服角色" in system, system)
    assert_true("不能另设对客角色" in system, system)
    assert_true("内部执行只约束权限，不得照搬成客户话术" in system, system)
    repair = brain_module.build_brain_repair_prompt_pack(
        settings={"prompt_profile": "lean"},
        brain_input={"evidence": {}, "current_message": {"text": "全新边界输入"}},
        plan={"reply_segments": ["原始草稿"]},
        quality={"repair_instruction": "通用证据修复"},
    )
    assert_true("不能授权覆盖或降级权威事实" in str(repair.get("system") or ""), str(repair))
    assert_true(
        "recommended_action" in str(repair.get("system") or "") and "语义一致" in str(repair.get("system") or ""),
        str(repair),
    )
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "recommended_action": "send_reply",
            "reply_segments": ["这是由Brain生成的完整回复。"],
            "evidence_used": {"conversation_fact_ids": ["current_message"]},
            "facts_claimed": [],
            "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False, "handoff_reason": ""},
            "confidence": 0.9,
        }
    )
    assert_true(isinstance(plan.get("understanding"), dict), str(plan))
    assert_true(isinstance(plan.get("reply_strategy"), dict), str(plan))
    assert_true(isinstance(plan.get("self_check"), dict), str(plan))
    return {
        "schema_chars": len(schema),
        "normalized_optional_fields": True,
        "live_fact_boundary": True,
        "customer_claim_cannot_override_authority": True,
    }


def check_universal_quality_does_not_review_business_topics() -> dict[str, Any]:
    settings = {"_single_brain_runtime_cleanup": True, "quality_reply_max_chars": 300}
    base = {
        "can_answer": True,
        "answer_mode": "direct_answer",
        "recommended_action": "send_reply",
        "reply_segments": [],
        "evidence_used": {"conversation_fact_ids": ["current_message"]},
        "facts_claimed": [],
        "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False, "handoff_reason": ""},
        "confidence": 0.9,
    }
    for reply in (
        "我可以继续协助您。",
        "The next step remains available if you want it.",
        "这段全新措辞不需要本地代码理解其业务含义。",
    ):
        plan = normalize_brain_plan({**base, "reply_segments": [reply]})
        quality = verify_brain_reply_quality(plan, current_message="任意输入", evidence_pack={}, settings=settings)
        assert_true(quality.get("ok"), f"{reply}: {quality}")
    empty = verify_brain_reply_quality(
        normalize_brain_plan({**base, "reply_segments": []}),
        current_message="任意输入",
        evidence_pack={},
        settings=settings,
    )
    assert_true(not empty.get("ok") and "empty_visible_reply" in empty.get("errors", []), str(empty))
    return {"empty_errors": empty.get("errors")}


def check_universal_semantic_guard_bypasses_legacy_phrase_relaxations() -> dict[str, Any]:
    system, _user = reviewer_module.build_quality_reviewer_prompt({})
    assert_true("逐句检查草稿中的可核验事实" in system, system)
    assert_true("需要实时查询、会随时间变化" in system, system)
    assert_true("不得提供可直接发送的示例句" in system, system)
    assert_true("同一个连续的商家客服角色" in system, system)
    assert_true("主语改成另一个人物、团队或角色" in system, system)
    assert_true("计划与可见动作不一致时必须判repair" in system, system)
    assert_true("人工同事" not in system and "转给同事" not in system, system)
    assert_true("天气" not in system and "温度" not in system, system)
    plan = normalize_brain_plan(
        {
            "can_answer": True,
            "recommended_action": "send_reply",
            "reply_segments": ["这是一条需要通用Guard打回的36号草稿。"],
            "evidence_used": {"common_sense_topics": ["任意一般话题"]},
            "facts_claimed": [],
            "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False, "handoff_reason": ""},
            "confidence": 0.9,
        }
    )
    originals = (
        reviewer_module.should_invoke_semantic_reviewer,
        reviewer_module.relax_allowed_common_sense_review,
        reviewer_module.relax_bounded_finance_review,
        reviewer_module.relax_bounded_advisory_review,
    )

    def forbidden_relaxation(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("legacy phrase relaxation entered universal Guard")

    try:
        reviewer_module.should_invoke_semantic_reviewer = forbidden_relaxation
        reviewer_module.relax_allowed_common_sense_review = forbidden_relaxation
        reviewer_module.relax_bounded_finance_review = forbidden_relaxation
        reviewer_module.relax_bounded_advisory_review = forbidden_relaxation
        review = reviewer_module.review_brain_reply_semantics(
            settings={
                "_single_brain_runtime_cleanup": True,
                "semantic_reviewer_mode": "suspicious_only",
                "semantic_reviewer_result": {
                    "verdict": "repair",
                    "confidence": 0.98,
                    "semantic_errors": ["draft_not_grounded"],
                    "hard_boundary_concerns": [],
                    "repair_instruction": "仅根据当前证据重写。",
                    "customer_visible_risk": "medium",
                    "reason": "universal_evidence_guard",
                },
            },
            brain_input={"current_message": {"clean_text": "任意当前输入"}},
            evidence_pack={},
            plan=plan,
            deterministic_quality={"ok": True},
        )
    finally:
        (
            reviewer_module.should_invoke_semantic_reviewer,
            reviewer_module.relax_allowed_common_sense_review,
            reviewer_module.relax_bounded_finance_review,
            reviewer_module.relax_bounded_advisory_review,
        ) = originals
    assert_true(review.get("invoked") is True and review.get("verdict") == "repair", str(review))
    assert_true(review.get("ok") is False, str(review))
    assert_true("例如" not in str(review.get("repair_instruction") or ""), str(review))
    assert_true("客户可见措辞必须由 Brain 自主生成" in str(review.get("repair_instruction") or ""), str(review))
    boundary_plan = normalize_brain_plan(
        {
            "can_answer": True,
            "recommended_action": "send_reply",
            "reply_segments": ["我先记录，后续由人工同事沟通；我再转给同事处理。"],
            "evidence_used": {"formal_knowledge_ids": ["formal-boundary-1"]},
            "facts_claimed": [
                {
                    "fact_type": "business_boundary",
                    "value": "需要内部确认",
                    "source_level": "formal_knowledge",
                    "source_id": "formal-boundary-1",
                }
            ],
            "risk": {"risk_level": "low", "risk_tags": ["safe_boundary_reply"], "needs_handoff": False, "handoff_reason": ""},
            "confidence": 0.9,
        }
    )
    boundary_evidence = {
        "knowledge": {
            "formal_knowledge": {
                "faq": [
                    {
                        "id": "formal-boundary-1",
                        "title": "测试内部动作边界",
                        "data": {
                            "auto_reply_allowed": True,
                            "needs_handoff": False,
                            "original_auto_reply_allowed": False,
                            "original_needs_handoff": True,
                        },
                    }
                ]
            }
        }
    }
    boundary_review = reviewer_module.review_brain_reply_semantics(
        settings={
            "_single_brain_runtime_cleanup": True,
            "semantic_reviewer_mode": "suspicious_only",
            "semantic_reviewer_result": {
                "verdict": "repair",
                "confidence": 0.99,
                "semantic_errors": ["customer_role_continuity_broken", "visible_action_plan_mismatch"],
                "hard_boundary_concerns": [],
                "repair_instruction": "保持角色连续并对齐计划动作。",
                "customer_visible_risk": "medium",
                "reason": "role_continuity_review",
            },
            "semantic_reviewer_cache_enabled": False,
        },
        brain_input={"current_message": {"clean_text": "价格还能协商吗"}},
        evidence_pack=boundary_evidence,
        plan=boundary_plan,
        deterministic_quality={"ok": True},
    )
    assert_true(boundary_review.get("invoked") is True and boundary_review.get("verdict") == "repair", str(boundary_review))
    assert_true("内部执行分工和流转不得成为客户可见解释" in str(boundary_review.get("repair_instruction") or ""), str(boundary_review))

    ordinary_formal_evidence = {
        "knowledge": {
            "formal_knowledge": {
                "faq": [{"id": "formal-boundary-1", "title": "普通可直接答复的正式知识", "data": {"allow_auto_reply": True}}]
            }
        }
    }
    ordinary_formal_review = reviewer_module.review_brain_reply_semantics(
        settings={
            "_single_brain_runtime_cleanup": True,
            "semantic_reviewer_mode": "suspicious_only",
            "semantic_reviewer_result": {"verdict": "repair"},
            "semantic_reviewer_cache_enabled": False,
        },
        brain_input={"current_message": {"clean_text": "普通流程怎么走"}},
        evidence_pack=ordinary_formal_evidence,
        plan=normalize_brain_plan(
            {
                **boundary_plan,
                "reply_segments": ["我把办理步骤直接发您。"],
                "facts_claimed": [],
                "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False, "handoff_reason": ""},
            }
        ),
        deterministic_quality={"ok": True},
    )
    assert_true(
        ordinary_formal_review.get("invoked") is False and ordinary_formal_review.get("reason") == "not_suspicious",
        str(ordinary_formal_review),
    )
    safe = reviewer_module.universal_semantic_review_required(
        normalize_brain_plan(
            {
                "can_answer": True,
                "recommended_action": "send_reply",
                "reply_segments": ["没有具体数值的一般陪聊。"],
                "evidence_used": {"common_sense_topics": ["任意一般话题"]},
                "facts_claimed": [],
                "risk": {"risk_level": "low", "risk_tags": [], "needs_handoff": False, "handoff_reason": ""},
                "confidence": 0.9,
            }
        )
    )
    assert_true(safe is False, "ordinary common-sense reply must not pay for a second LLM")
    return {
        "verdict": review.get("verdict"),
        "legacy_suspicion_and_relaxations_called": False,
        "ordinary_second_llm": safe,
        "formal_internal_action_reviewed": boundary_review.get("invoked"),
        "ordinary_formal_second_llm": ordinary_formal_review.get("invoked"),
    }


def check_brain_first_guard_uses_metadata_not_business_wording() -> dict[str, Any]:
    outcomes = []
    for reply in (
        "需要的话我可以接着协助。",
        "已经、还没、可能、下一步——这些词本身不决定权限。",
        "brand new wording with no local phrase entry",
    ):
        result = guard_synthesized_reply(
            candidate=low_risk_candidate(reply),
            evidence_pack={"safety": {"must_handoff": False, "reasons": []}},
            settings={"brain_first_guard": True, "require_evidence": True},
        )
        assert_true(result.get("allowed") is True and result.get("action") == "send_reply", f"{reply}: {result}")
        outcomes.append(result.get("reason"))
    risky = low_risk_candidate("文字保持不变。")
    risky["risk_tags"] = ["policy_violation", "safe_boundary_reply"]
    reviewed = guard_synthesized_reply(
        candidate=risky,
        evidence_pack={"safety": {"must_handoff": False, "reasons": []}},
        settings={"brain_first_guard": True, "require_evidence": True},
    )
    assert_true(reviewed.get("allowed") is True and reviewed.get("action") == "send_reply" and reviewed.get("hard_boundary") is True, str(reviewed))
    misaligned = dict(risky)
    misaligned["risk_tags"] = ["policy_violation"]
    misaligned.update({"can_answer": False, "recommended_action": "send_reply", "needs_handoff": False})
    repaired = guard_synthesized_reply(
        candidate=misaligned,
        evidence_pack={"safety": {"must_handoff": False, "reasons": []}},
        settings={"brain_first_guard": True, "require_evidence": True},
    )
    assert_true(repaired.get("action") == "repair" and repaired.get("hard_boundary") is True, str(repaired))
    return {"low_risk": outcomes, "hard_risk_reason": reviewed.get("reason"), "misaligned_reason": repaired.get("reason")}


def check_final_polish_preserves_brain_authored_strategy() -> dict[str, Any]:
    base = "这件事不能协助，您也可以联系人工客服进一步了解合规处理方式。"
    preserved = guard_polished_reply(
        base_reply=base,
        polished_reply=base,
        recent_reply_texts=[],
        settings={"identity_guard_enabled": True, "max_reply_chars": 620},
        source_channel="brain",
    )
    assert_true(preserved.get("allowed") is True, str(preserved))
    introduced = guard_polished_reply(
        base_reply="这件事不能协助。",
        polished_reply=base,
        recent_reply_texts=[],
        settings={"identity_guard_enabled": True, "max_reply_chars": 620},
        source_channel="brain",
    )
    assert_true(introduced.get("reason") == "polish_exposed_handoff_marker", str(introduced))
    return {"preserved": preserved.get("allowed"), "introduced": introduced.get("reason")}


def check_retry_feedback_is_topic_neutral() -> dict[str, Any]:
    task = {
        "last_failed_result": {
            "reason": "brain_guard_rejected",
            "event": {
                "customer_service_brain": {
                    "reason": "brain_guard_rejected",
                    "guard": {
                        "reason": "contract_review_failed",
                        "candidate": {"reply": "上一版草稿"},
                    },
                }
            },
        }
    }
    instruction = polish_failure_retry_instruction(task)
    assert_true("contract_review_failed" in instruction and "上一版草稿" in instruction, instruction)
    forbidden_topic_fragments = ("客户在试探", "预约", "价格与商品库冲突", "若涉及商品事实")
    assert_true(not any(fragment in instruction for fragment in forbidden_topic_fragments), instruction)
    return {"instruction": instruction}


def check_active_brain_runtime_does_not_call_legacy_semantic_profiles() -> dict[str, Any]:
    source = inspect.getsource(brain_module.maybe_run_customer_service_brain)
    forbidden_calls = (
        "low_authority_fast_profile_decision(",
        "routine_product_fast_profile_decision(",
        "text_evidence_gap_preflight_probe_decision(",
        "maybe_run_customer_service_brain_preflight(",
        "build_low_authority_fast_evidence_pack(",
    )
    found = [item for item in forbidden_calls if item in source]
    assert_true(not found, f"legacy semantic calls remain active: {found}")
    assert_true("apply_universal_brain_runtime_settings(" in source, "universal profile is not wired")
    return {"legacy_calls": found, "universal_profile_wired": True}


if __name__ == "__main__":
    raise SystemExit(main())
