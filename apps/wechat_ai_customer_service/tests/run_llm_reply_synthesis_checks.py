"""Focused checks for guarded LLM reply synthesis.

These checks are offline and do not call DeepSeek. They use manual JSON
candidates to prove the new synthesis layer can participate in the workflow,
that RAG evidence is passed to the LLM prompt, and that RAG-only evidence cannot
authorize sensitive commitments.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, APP_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import llm_reply_synthesis as synthesis_module  # noqa: E402
from customer_service_loop import load_rules  # noqa: E402
from listen_and_reply import ReplyDecision, load_config, parse_targets, process_target, resolve_path  # noqa: E402
from llm_reply_guard import guard_synthesized_reply  # noqa: E402
from llm_reply_synthesis import build_synthesis_prompt_pack, maybe_synthesize_reply  # noqa: E402


CONFIG_PATH = APP_ROOT / "configs" / "file_transfer_smoke.example.json"


@dataclass
class FakeConnector:
    messages: list[dict[str, Any]]

    def __post_init__(self) -> None:
        self.sent_texts: list[str] = []

    def get_messages(self, target: str, exact: bool = True) -> dict[str, Any]:
        return {"ok": True, "target": target, "exact": exact, "messages": self.messages}

    def send_text_and_verify(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        self.sent_texts.append(text)
        return {"ok": True, "verified": True, "target": target, "exact": exact, "text": text}


def main() -> int:
    result = run_checks()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def run_checks() -> dict[str, Any]:
    checks = [
        check_synthesis_applies_inside_process_target,
        check_rag_evidence_is_explicit_prompt_material,
        check_synthesis_prompt_is_domain_neutral,
        check_platform_safety_rules_are_visible_and_configurable,
        check_rag_only_authority_topic_forces_handoff,
        check_safe_llm_handoff_wording_is_preserved,
        check_shadow_mode_does_not_apply,
        check_deepseek_flash_pro_routing_and_cost_audit,
    ]
    results = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    return {"ok": not failures, "count": len(results), "failures": failures, "results": results}


def check_synthesis_applies_inside_process_target() -> None:
    config = load_test_config()
    config["llm_reply_synthesis"] = {
        "enabled": True,
        "provider": "manual_json",
        "candidate": {
            "can_answer": True,
            "reply": "这台商用冷柜适合小店放饮料，现有资料能确认基础型号和用途；如果您要价格和发货时间，我再按正式资料帮您核对。",
            "confidence": 0.86,
            "recommended_action": "send_reply",
            "needs_handoff": False,
            "used_evidence": ["product:commercial_fridge_bx_200", "faq:scene_product"],
            "rag_used": False,
            "structured_used": True,
            "uncertain_points": ["具体发货时间需按下单城市确认"],
            "risk_tags": [],
            "reason": "natural scene mapped to formal product evidence",
        },
    }
    rules = load_rules(resolve_path(config.get("rules_path")))
    target = parse_targets(config)[0]
    connector = FakeConnector(
        [
            {
                "id": "natural-1",
                "type": "text",
                "content": "我开个小店，想找个能放饮料的冷柜，别太复杂，有没有合适的？",
                "sender": "self",
            }
        ]
    )
    event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state={"version": 1, "targets": {}},
        send=False,
        write_data=False,
        allow_fallback_send=False,
        mark_dry_run=False,
    )
    synthesis = event.get("llm_reply_synthesis", {}) or {}
    assert_true(synthesis.get("applied"), "manual synthesis should apply inside process_target")
    assert_equal(event.get("decision", {}).get("rule_name"), "llm_synthesis_reply", "decision should be updated by synthesis")
    assert_true("小店放饮料" in event.get("decision", {}).get("reply_text", ""), "final reply should use synthesized natural text")


def check_rag_evidence_is_explicit_prompt_material() -> None:
    pack = synthetic_pack(intent_tags=["scene_product"], structured=True, rag=True)
    prompt = build_synthesis_prompt_pack(pack)
    payload = json.dumps(prompt["user"], ensure_ascii=False)
    assert_true("rag:rag_chunk_used_car_family" in payload or "rag_chunk_used_car_family" in payload, "prompt should include RAG chunk id")
    assert_true("家庭用车经验" in payload, "prompt should include RAG text")
    assert_true("RAG经验必须积极参与" in json.dumps(prompt, ensure_ascii=False), "prompt rules should emphasize RAG participation")


def check_synthesis_prompt_is_domain_neutral() -> None:
    prompt = build_synthesis_prompt_pack(synthetic_pack(intent_tags=["scene_product"], structured=True, rag=True))
    payload = json.dumps({"system": prompt["system"], "rules": prompt["user"]["rules"]}, ensure_ascii=False)
    forbidden = ["二手车微信销售场景", "车况", "水泡", "火烧", "试驾", "置换"]
    hits = [term for term in forbidden if term in payload]
    assert_true(not hits, f"generic synthesis prompt should not hard-code tenant domain terms: {hits}")
    assert_true("不要假设客户所属行业" in payload, "prompt should explicitly forbid hidden industry assumptions")


def check_platform_safety_rules_are_visible_and_configurable() -> None:
    custom_rules = {
        "schema_version": 1,
        "title": "Unit test visible safety rules",
        "prompt_rules": [
            {
                "id": "custom_visible_prompt_rule",
                "title": "Custom rule",
                "instruction": "自定义可见规则：不要承诺测试专用词。",
                "enabled": True,
            }
        ],
        "guard_terms": {
            "authority_tags": ["quote"],
            "commitment_terms": ["测试专用硬承诺"],
            "caution_terms": ["人工核实"],
            "formulaic_handoff_terms": [],
            "forbidden_reply_terms": [],
            "forbidden_safe_markers": [],
            "appointment_commitment_terms": [],
            "appointment_caution_terms": [],
            "sales_followup_actors": [],
            "sales_followup_actions": [],
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "platform_safety_rules.json"
        path.write_text(json.dumps(custom_rules, ensure_ascii=False, indent=2), encoding="utf-8")
        settings = {"platform_safety_rules_path": str(path)}
        prompt = build_synthesis_prompt_pack(synthetic_pack(intent_tags=["scene_product"], structured=True, rag=True), settings=settings)
        payload = json.dumps(prompt["user"], ensure_ascii=False)
        assert_true("自定义可见规则" in payload, "prompt should include visible platform safety rules from configured file")
        guard = guard_synthesized_reply(
            candidate={
                "can_answer": True,
                "reply": "我可以测试专用硬承诺，没问题。",
                "confidence": 0.9,
                "recommended_action": "send_reply",
                "needs_handoff": False,
                "used_evidence": ["product:test"],
                "rag_used": False,
                "structured_used": True,
                "uncertain_points": [],
                "risk_tags": [],
                "reason": "custom platform rule test",
            },
            evidence_pack=synthetic_pack(intent_tags=["scene_product"], structured=True, rag=False),
            settings=settings,
        )
        assert_equal(guard.get("reason"), "unsafe_commitment_without_caution", "custom visible guard term should be enforced")


def check_rag_only_authority_topic_forces_handoff() -> None:
    original_builder = synthesis_module.build_reply_evidence_pack
    try:
        synthesis_module.build_reply_evidence_pack = lambda **kwargs: synthetic_pack(
            intent_tags=["quote"],
            structured=False,
            rag=True,
        )
        result = maybe_synthesize_reply(
            config={
                "llm_reply_synthesis": {
                    "enabled": True,
                    "provider": "manual_json",
                    "candidate": {
                        "can_answer": True,
                        "reply": "根据经验这台车还能优惠很多，我可以直接给您最低价。",
                        "confidence": 0.91,
                        "recommended_action": "send_reply",
                        "needs_handoff": False,
                        "used_evidence": ["rag:rag_chunk_used_car_family"],
                        "rag_used": True,
                        "structured_used": False,
                        "uncertain_points": [],
                        "risk_tags": ["price_sensitive"],
                        "reason": "rag only price answer",
                    },
                    "require_structured_for_authority": True,
                }
            },
            target_name="文件传输助手",
            target_state={},
            batch=[],
            combined="这车最低多少钱？",
            decision=ReplyDecision("", "no_rule_matched", False, False, "no_rule_matched"),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={},
        )
    finally:
        synthesis_module.build_reply_evidence_pack = original_builder
    assert_true(result.get("applied"), "unsafe authority synthesis should apply as a handoff decision")
    assert_true(result.get("needs_handoff"), "RAG-only authority answer must force handoff")
    assert_equal(
        result.get("guard", {}).get("reason"),
        "authority_topic_without_structured_evidence",
        "guard should explain that formal evidence is required",
    )


def check_safe_llm_handoff_wording_is_preserved() -> None:
    original_builder = synthesis_module.build_reply_evidence_pack
    try:
        synthesis_module.build_reply_evidence_pack = lambda **kwargs: synthetic_pack(
            intent_tags=["payment", "quote"],
            structured=True,
            rag=True,
            must_handoff=True,
        )
        result = maybe_synthesize_reply(
            config={
                "llm_reply_synthesis": {
                    "enabled": True,
                    "provider": "manual_json",
                    "candidate": {
                        "can_answer": False,
                        "reply": "贷款能不能批、最低价能不能锁，我这边不能直接替销售和金融同事拍板；我先把您的预算和车型意向记下，让同事按资料给您准话。",
                        "confidence": 0.81,
                        "recommended_action": "handoff",
                        "needs_handoff": True,
                        "used_evidence": ["product:chejin_camry_2021_20g", "rag:rag_chunk_used_car_family"],
                        "rag_used": True,
                        "structured_used": True,
                        "uncertain_points": ["贷款审批", "最低成交价"],
                        "risk_tags": ["finance", "price_sensitive"],
                        "reason": "safe guarded handoff wording",
                    },
                    "require_structured_for_authority": True,
                }
            },
            target_name="文件传输助手",
            target_state={},
            batch=[],
            combined="你直接保证贷款包过，再给我锁最低价。",
            decision=ReplyDecision("", "no_rule_matched", False, False, "no_rule_matched"),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={},
        )
    finally:
        synthesis_module.build_reply_evidence_pack = original_builder
    assert_true(result.get("applied"), "safe handoff synthesis should apply")
    assert_true(result.get("needs_handoff"), "safe handoff synthesis should still require operator handoff")
    assert_true("不能直接" in str(result.get("raw_reply_text") or ""), "guard should preserve safe LLM handoff wording")


def check_shadow_mode_does_not_apply() -> None:
    original_builder = synthesis_module.build_reply_evidence_pack
    try:
        synthesis_module.build_reply_evidence_pack = lambda **kwargs: synthetic_pack(
            intent_tags=["scene_product"],
            structured=True,
            rag=True,
        )
        result = maybe_synthesize_reply(
            config={
                "llm_reply_synthesis": {
                    "enabled": True,
                    "provider": "manual_json",
                    "shadow_mode": True,
                    "candidate": {
                        "can_answer": True,
                        "reply": "可以先看凯美瑞，家用比较均衡。",
                        "confidence": 0.88,
                        "recommended_action": "send_reply",
                        "needs_handoff": False,
                        "used_evidence": ["product:chejin_camry_2021_20g", "rag:rag_chunk_used_car_family"],
                        "rag_used": True,
                        "structured_used": True,
                        "uncertain_points": [],
                        "risk_tags": [],
                        "reason": "shadow test",
                    },
                }
            },
            target_name="文件传输助手",
            target_state={},
            batch=[],
            combined="家用省心有推荐吗？",
            decision=ReplyDecision("", "no_rule_matched", False, False, "no_rule_matched"),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={},
        )
    finally:
        synthesis_module.build_reply_evidence_pack = original_builder
    assert_true(not result.get("applied"), "shadow mode should not change final reply")
    assert_equal(result.get("reason"), "shadow_mode", "shadow mode reason should be explicit")
    assert_true(result.get("guard", {}).get("action") == "send_reply", "shadow mode should still run guard")


def check_deepseek_flash_pro_routing_and_cost_audit() -> None:
    original_builder = synthesis_module.build_reply_evidence_pack
    original_read_secret = synthesis_module.read_secret
    original_post = synthesis_module.post_deepseek_synthesis
    captured: list[dict[str, Any]] = []

    def fake_read_secret(name: str) -> str:
        return "unit-test-key" if name == "DEEPSEEK_API_KEY" else ""

    def fake_post(**kwargs: Any) -> dict[str, Any]:
        captured.append(dict(kwargs))
        prompt = kwargs.get("prompt_pack") or {}
        payload = prompt.get("user") if isinstance(prompt.get("user"), dict) else {}
        evidence = payload.get("evidence_pack") if isinstance(payload.get("evidence_pack"), dict) else {}
        must_handoff = bool((evidence.get("safety") or {}).get("must_handoff"))
        candidate = {
            "can_answer": not must_handoff,
            "reply": "这条回复来自受控模型路由测试，普通问题可直接回答；风险问题会转人工确认。",
            "confidence": 0.86,
            "recommended_action": "handoff" if must_handoff else "send_reply",
            "needs_handoff": must_handoff,
            "used_evidence": evidence.get("evidence_ids", []),
            "rag_used": bool(((evidence.get("rag") or {}).get("hits"))),
            "structured_used": bool((evidence.get("audit_summary") or {}).get("structured_evidence_count")),
            "uncertain_points": ["需要人工确认"] if must_handoff else [],
            "risk_tags": ["manual_review"] if must_handoff else [],
            "reason": "unit test model routing candidate",
        }
        return {
            "ok": True,
            "provider": "deepseek",
            "status": 200,
            "response_text": json.dumps(candidate, ensure_ascii=False),
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168},
        }

    base_config = {
        "llm_reply_synthesis": {
            "enabled": True,
            "provider": "deepseek",
            "model_routing": {
                "enabled": True,
                "default_tier": "flash",
                "flash_model": "deepseek-v4-flash",
                "pro_model": "deepseek-v4-pro",
            },
            "cost_controls": {"enabled": True, "max_llm_calls_per_run": 0},
            "require_structured_for_authority": True,
        }
    }

    def call_with_pack(pack: dict[str, Any], text: str) -> dict[str, Any]:
        synthesis_module.build_reply_evidence_pack = lambda **kwargs: pack
        return maybe_synthesize_reply(
            config=base_config,
            target_name="文件传输助手",
            target_state={},
            batch=[],
            combined=text,
            decision=ReplyDecision("", "no_rule_matched", False, False, "no_rule_matched"),
            reply_text="",
            intent_assist={},
            rag_reply={},
            llm_reply={},
            product_knowledge={},
            data_capture={},
            raw_capture={},
        )

    try:
        synthesis_module.read_secret = fake_read_secret
        synthesis_module.post_deepseek_synthesis = fake_post
        normal = call_with_pack(synthetic_pack(intent_tags=["scene_product"], structured=True, rag=True), "家用省心有推荐吗")
        risky = call_with_pack(
            synthetic_pack(intent_tags=["payment", "quote"], structured=True, rag=True, must_handoff=True),
            "你直接保证贷款包过再锁最低价",
        )
    finally:
        synthesis_module.build_reply_evidence_pack = original_builder
        synthesis_module.read_secret = original_read_secret
        synthesis_module.post_deepseek_synthesis = original_post

    assert_equal(normal.get("model_tier"), "flash", "normal reply synthesis should use Flash")
    assert_equal(normal.get("model"), "deepseek-v4-flash", "normal reply synthesis should select flash model")
    assert_true((normal.get("llm_usage") or {}).get("total_tokens") == 168, "usage should be kept for cost audit")
    assert_true((normal.get("prompt_estimate") or {}).get("rough_prompt_tokens", 0) > 0, "prompt estimate should be recorded")
    assert_equal(risky.get("model_tier"), "pro", "risky authority synthesis should use Pro")
    assert_equal(risky.get("model"), "deepseek-v4-pro", "risky authority synthesis should select pro model")
    assert_true(len(captured) == 2, "fake DeepSeek should have been called exactly twice")


def synthetic_pack(*, intent_tags: list[str], structured: bool, rag: bool, must_handoff: bool = False) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "products": [],
        "faq": [],
        "policies": {},
        "product_scoped": [],
        "style_examples": [],
    }
    evidence_ids: list[str] = []
    if structured:
        evidence["products"].append({"id": "chejin_camry_2021_20g", "name": "2021款丰田凯美瑞2.0G豪华版", "price": 13.98, "stock": 1})
        evidence["faq"].append({"intent": "family_car", "answer": "适合家庭通勤，最终车况以检测报告为准。"})
        evidence_ids.extend(["product:chejin_camry_2021_20g", "faq:family_car"])
    rag_hits = []
    if rag:
        rag_hits.append(
            {
                "chunk_id": "rag_chunk_used_car_family",
                "source_id": "rag_source_family",
                "score": 0.74,
                "category": "chats",
                "source_type": "rag_experience",
                "product_id": "chejin_camry_2021_20g",
                "text": "家庭用车经验：客户重视省心、油耗和接送孩子时，可以优先解释空间、保养和检测报告。",
            }
        )
        evidence_ids.append("rag:rag_chunk_used_car_family")
    return {
        "schema_version": 1,
        "current_message": "自然问题",
        "conversation": {"history": [{"sender": "customer", "content": "预算十来万，家用省心。"}], "history_count": 1},
        "knowledge": {
            "intent_tags": intent_tags,
            "evidence": evidence,
            "rag_evidence": {"hits": rag_hits, "confidence": 0.74, "rag_can_authorize": False, "structured_priority": True},
            "safety": {"must_handoff": must_handoff, "allowed_auto_reply": not must_handoff, "reasons": ["manual_test"] if must_handoff else []},
        },
        "intent_tags": intent_tags,
        "safety": {"must_handoff": must_handoff, "allowed_auto_reply": not must_handoff, "reasons": ["manual_test"] if must_handoff else []},
        "rag": {"hits": rag_hits, "confidence": 0.74},
        "evidence_ids": evidence_ids,
        "audit_summary": {"structured_evidence_count": 2 if structured else 0, "rag_hit_count": len(rag_hits), "evidence_ids": evidence_ids},
    }


def load_test_config() -> dict[str, Any]:
    config = copy.deepcopy(load_config(CONFIG_PATH))
    config.setdefault("operator_alert", {})["enabled"] = False
    config.setdefault("raw_messages", {})["enabled"] = False
    config.setdefault("rag_response", {})["enabled"] = False
    config.setdefault("intent_assist", {})["enabled"] = False
    return config


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
