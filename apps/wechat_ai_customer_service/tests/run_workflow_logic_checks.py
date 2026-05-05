"""Focused workflow logic checks for the WeChat AI customer-service app.

These checks do not connect to WeChat. They exercise the guarded workflow with
an in-memory connector so regressions in batching, handoff arbitration, and
configured reply prefixes are caught before live smoke tests.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_intent_assist as customer_intent_assist_module  # noqa: E402
from customer_intent_assist import IntentAssistResult, call_deepseek_advisory  # noqa: E402
from customer_service_review_queue import build_review_queue  # noqa: E402
from knowledge_loader import build_evidence_pack  # noqa: E402
from listen_and_reply import (  # noqa: E402
    ReplyDecision,
    apply_local_customer_service_settings,
    build_operator_handoff_reply_text,
    configured_reply_prefix,
    is_bot_reply_content,
    load_config,
    load_rules,
    maybe_apply_llm_reply,
    parse_targets,
    process_target,
    resolve_path,
    select_batch,
    should_operator_handoff,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_settings import CustomerServiceSettings  # noqa: E402
from apps.wechat_ai_customer_service.llm_config import DEFAULT_DEEPSEEK_CONTEXT_WINDOW_TOKENS, resolve_deepseek_model, resolve_deepseek_tier_model  # noqa: E402
from wxauto4_sidecar import is_wechat_main_window  # noqa: E402


CONFIG_PATH = APP_ROOT / "configs" / "file_transfer_smoke.example.json"
BOUNDARY_CONFIG_PATH = APP_ROOT / "configs" / "file_transfer_boundary_llm.example.json"
TEST_ARTIFACTS = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts"


class FakeConnector:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = messages
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
        check_configured_bot_prefix_is_skipped,
        check_mixed_safety_batch_forces_handoff,
        check_incomplete_customer_data_is_completed_and_written,
        check_rate_limit_notice_and_backoff,
        check_auto_reply_disabled_blocks_runtime_send,
        check_customer_service_console_switches_take_effect,
        check_deepseek_v4_pro_is_default,
        check_llm_reply_application_guards,
        check_llm_boundary_fallback_on_invalid_model_output,
        check_review_queue_reports_pending_and_handoff_items,
        check_evidence_boundary_cases,
        check_after_sales_intent_preempts_duration_logistics,
        check_wechat_main_window_recognition,
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


def check_configured_bot_prefix_is_skipped() -> None:
    config = load_smoke_config()
    bot_content = "[OmniAuto文件助手测试] 商用冰箱 BX-200 参考价 999 元/台"
    other_config_bot_content = "[OmniAuto边界测试] 我是上一轮边界测试回复"
    assert_true(is_bot_reply_content(bot_content, config), "configured reply prefix should be treated as bot text")
    assert_true(
        is_bot_reply_content(other_config_bot_content, config),
        "other OmniAuto test prefixes should also be treated as bot text",
    )

    batch = select_batch(
        [
            {"id": "bot-1", "type": "text", "content": bot_content, "sender": "self"},
            {"id": "bot-2", "type": "text", "content": other_config_bot_content, "sender": "self"},
            {"id": "m-1", "type": "text", "content": "商用冰箱多少钱？", "sender": "self"},
        ],
        target_state={"processed_message_ids": [], "handoff_message_ids": []},
        allow_self_for_test=True,
        max_batch_messages=3,
        config=config,
    )
    assert_equal([item["id"] for item in batch], ["m-1"], "batch should exclude configured bot prefix")


def check_wechat_main_window_recognition() -> None:
    for title in ["微信", "Weixin", "WeChat"]:
        assert_true(
            is_wechat_main_window({"title": title, "class_name": "QWindowIcon"}),
            f"{title} main window should be recognized",
        )
    assert_true(
        not is_wechat_main_window({"title": "微信", "class_name": "LoginWindow"}),
        "non-main class should not be treated as main window",
    )
    assert_true(
        not is_wechat_main_window({"title": "登录", "class_name": "QWindowIcon"}),
        "login/secondary titles should not be treated as main window",
    )


def check_mixed_safety_batch_forces_handoff() -> None:
    config = load_smoke_config()
    rules = load_rules(resolve_path(config.get("rules_path")))
    target = parse_targets(config)[0]
    connector = FakeConnector(
        [
            {
                "id": "bot-1",
                "type": "text",
                "content": "[OmniAuto文件助手测试] 商用冰箱 BX-200 参考价 999 元/台",
                "sender": "self",
            },
            {
                "id": "m-discount",
                "type": "text",
                "content": "买7台冰箱能按20台价格吗？",
                "sender": "self",
            },
            {
                "id": "m-data",
                "type": "text",
                "content": "客户资料\n姓名：林晓晨\n电话：13800138001\n地址：上海市浦东新区张江路88号\n产品：商用冰箱\n数量：2台",
                "sender": "self",
            },
        ]
    )
    state: dict[str, Any] = {"version": 1, "targets": {}}

    event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=True,
        allow_fallback_send=False,
        mark_dry_run=False,
    )

    assert_equal(event.get("action"), "handoff_sent", "discount/data mixed batch should hand off")
    assert_equal(event.get("message_ids"), ["m-discount", "m-data"], "bot reply should not enter message ids")
    assert_true(connector.sent_texts, "handoff acknowledgement should be sent")
    assert_true("负责的同事核实" in connector.sent_texts[0], "sent text should be the natural handoff acknowledgement")
    assert_true("请示上级" not in connector.sent_texts[0], "handoff text should avoid the old formulaic acknowledgement")
    assert_true("客户资料已记录" not in connector.sent_texts[0], "data capture success should not override safety handoff")
    safety = event.get("intent_assist", {}).get("evidence", {}).get("safety", {})
    assert_true(bool(safety.get("must_handoff")), "evidence safety should require handoff")
    assert_true(
        "m-discount" in state["targets"][target.name]["handoff_message_ids"],
        "handoff ids should include the risk-bearing message",
    )
    assert_true(
        not event.get("data_capture", {}).get("write_result", {}).get("ok"),
        "customer data should not be auto-written when the batch requires handoff",
    )


def check_incomplete_customer_data_is_completed_and_written() -> None:
    config = load_smoke_config()
    workbook_path = TEST_ARTIFACTS / "workflow_logic_customer_leads.xlsx"
    remove_file(workbook_path)
    config.setdefault("data_capture", {})["workbook_path"] = str(workbook_path)
    rules = load_rules(resolve_path(config.get("rules_path")))
    target = parse_targets(config)[0]
    state: dict[str, Any] = {"version": 1, "targets": {}}
    connector = FakeConnector(
        [
            {
                "id": "lead-1",
                "type": "text",
                "content": "客户资料\n电话：13900001111\n地址：杭州市余杭区测试路 8 号\n产品：商用冰箱\n数量：2 台\n[live-regression:test:17:1]",
                "sender": "self",
            }
        ]
    )

    first_event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=True,
        allow_fallback_send=False,
        mark_dry_run=False,
    )

    assert_equal(first_event.get("action"), "sent", "incomplete lead should be answered with a missing-field prompt")
    assert_true("姓名" in connector.sent_texts[-1], "missing-field prompt should name the missing field")
    assert_true(not workbook_path.exists(), "incomplete lead should not be written to Excel")
    pending_items = state["targets"][target.name].get("pending_customer_data", [])
    assert_equal(len(pending_items), 1, "incomplete lead should create one pending data item")
    assert_equal(pending_items[0].get("status"), "waiting_for_fields", "pending item should wait for missing fields")

    connector.messages = [
        {
            "id": "lead-2",
            "type": "text",
            "content": "联系人：李补全\n[live-regression:test:18:1]",
            "sender": "self",
        }
    ]
    second_event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=True,
        allow_fallback_send=False,
        mark_dry_run=False,
    )

    assert_equal(second_event.get("action"), "sent", "completed lead should be acknowledged")
    assert_true("客户资料已记录" in connector.sent_texts[-1], "completed lead should send success reply")
    write_result = second_event.get("data_capture", {}).get("write_result", {})
    assert_true(bool(write_result.get("ok")), "completed lead should be written")
    assert_true(workbook_path.exists(), "Excel workbook should be created")
    workbook = load_workbook(workbook_path)
    sheet = workbook[config["data_capture"]["sheet_name"]]
    headers = [sheet.cell(row=1, column=index + 1).value for index in range(sheet.max_column)]
    row = {header: sheet.cell(row=2, column=index + 1).value for index, header in enumerate(headers)}
    assert_equal(row.get("name"), "李补全", "completed lead should keep the supplemented name")
    assert_equal(row.get("phone"), "13900001111", "completed lead should keep the original phone")
    assert_equal(
        state["targets"][target.name]["pending_customer_data"][-1].get("status"),
        "completed",
        "pending item should close after Excel write",
    )


def check_rate_limit_notice_and_backoff() -> None:
    config = load_smoke_config()
    config.setdefault("rate_limits", {}).update(
        {
            "max_replies_per_10_minutes": 1,
            "max_replies_per_hour": 100,
            "notice_customer": True,
            "notice_min_interval_seconds": 300,
        }
    )
    rules = load_rules(resolve_path(config.get("rules_path")))
    target = parse_targets(config)[0]
    connector = FakeConnector(
        [{"id": "rate-1", "type": "text", "content": "商用冰箱多少钱？", "sender": "self"}]
    )
    state: dict[str, Any] = {
        "version": 1,
        "targets": {
            target.name: {
                "processed_message_ids": [],
                "handoff_message_ids": [],
                "sent_replies": [],
                "reply_timestamps": [(datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")],
            }
        },
    }

    first_event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=False,
        allow_fallback_send=False,
        mark_dry_run=False,
    )
    assert_equal(first_event.get("action"), "rate_limit_notice_sent", "first blocked message should send a notice")
    assert_true("用量已超" in connector.sent_texts[-1], "notice should explain customer-facing rate limit")
    assert_true("rate_limit_backoff" in state["targets"][target.name], "rate-limit backoff should be recorded")

    second_event = process_target(
        connector=connector,  # type: ignore[arg-type]
        target=target,
        config=config,
        rules=rules,
        state=state,
        send=True,
        write_data=False,
        allow_fallback_send=False,
        mark_dry_run=False,
    )
    assert_equal(second_event.get("action"), "skipped", "same message should be skipped while backoff is active")
    assert_equal(second_event.get("reason"), "rate_limit_backoff_active", "skip reason should be explicit")
    assert_equal(len(connector.sent_texts), 1, "backoff should prevent duplicate rate-limit notices")


def check_auto_reply_disabled_blocks_runtime_send() -> None:
    config = load_boundary_config()
    decision = ReplyDecision(
        reply_text="raw internal policy answer",
        rule_name="faq_keyword_matched",
        matched=True,
        need_handoff=False,
        reason="faq_keyword_matched",
    )
    product_knowledge = {
        "matched": True,
        "reply_text": "raw internal policy answer",
        "needs_handoff": False,
        "auto_reply_allowed": False,
        "reason": "auto_reply_disabled",
    }
    assert_true(
        should_operator_handoff(decision, product_knowledge, fallback_allowed=True, intent_assist={}),
        "auto-reply disabled FAQ should force operator handoff",
    )
    reply = build_operator_handoff_reply_text(
        config,
        decision,
        product_knowledge,
        current_reply_text="raw internal policy answer",
        intent_assist={},
    )
    assert_true(
        "raw internal policy answer" not in reply,
        "auto-reply disabled FAQ should not send the stored answer before human review",
    )


def check_customer_service_console_switches_take_effect() -> None:
    tenant_id = "workflow_switch_probe"
    old_tenant = os.environ.get("WECHAT_KNOWLEDGE_TENANT")
    os.environ["WECHAT_KNOWLEDGE_TENANT"] = tenant_id
    settings_store = CustomerServiceSettings(tenant_id=tenant_id)
    remove_file(settings_store.settings_path)
    try:
        settings_store.save(
            {
                "enabled": False,
                "reply_mode": "full_auto",
                "record_messages": False,
                "auto_learn": False,
                "use_llm": False,
                "rag_enabled": False,
                "data_capture_enabled": False,
                "handoff_enabled": False,
                "operator_alert_enabled": False,
            }
        )
        disabled_config = apply_local_customer_service_settings(load_smoke_config())
        assert_true(disabled_config["raw_messages"]["enabled"] is False, "record-message switch should disable raw capture")
        assert_true(disabled_config["raw_messages"]["use_llm"] is False, "LLM switch should disable raw-message LLM learning")
        assert_true(disabled_config["intent_assist"]["enabled"] is False, "LLM switch should disable LLM-assisted intent analysis")
        assert_true(disabled_config["rag_response"]["enabled"] is False, "RAG reply switch should disable RAG response")
        assert_true(disabled_config["data_capture"]["enabled"] is False, "data-capture switch should disable customer data capture")
        assert_true(disabled_config["handoff"]["enabled"] is False, "handoff switch should disable operator handoff")
        assert_true(disabled_config["operator_alert"]["enabled"] is False, "operator-alert switch should disable operator alerts")

        disabled_event = process_target(
            connector=FakeConnector([{"id": "off-1", "type": "text", "content": "商用冰箱多少钱", "sender": "self"}]),  # type: ignore[arg-type]
            target=parse_targets(disabled_config)[0],
            config=disabled_config,
            rules=load_rules(resolve_path(disabled_config.get("rules_path"))),
            state={"version": 1, "targets": {}},
            send=True,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=False,
        )
        assert_equal(disabled_event.get("reason"), "customer_service_disabled", "master switch should stop replies")

        settings_store.save(
            {
                "enabled": True,
                "reply_mode": "record_only",
                "record_messages": True,
                "auto_learn": False,
                "use_llm": True,
                "rag_enabled": True,
                "data_capture_enabled": True,
                "handoff_enabled": True,
                "operator_alert_enabled": True,
            }
        )
        record_only_config = apply_local_customer_service_settings(load_smoke_config())
        assert_true(record_only_config["intent_assist"]["llm_advisory"]["enabled"] is True, "LLM switch should enable LLM advisory")
        assert_equal(record_only_config["intent_assist"]["llm_advisory"]["provider"], "deepseek", "LLM advisory should call configured model provider")
        assert_true(record_only_config["llm_reply_synthesis"]["enabled"] is True, "LLM switch should enable guarded reply synthesis")
        assert_equal(record_only_config["llm_reply_synthesis"]["provider"], "deepseek", "guarded reply synthesis should call configured model provider")
        record_only_event = process_target(
            connector=FakeConnector([{"id": "record-1", "type": "text", "content": "商用冰箱多少钱", "sender": "self"}]),  # type: ignore[arg-type]
            target=parse_targets(record_only_config)[0],
            config=record_only_config,
            rules=load_rules(resolve_path(record_only_config.get("rules_path"))),
            state={"version": 1, "targets": {}},
            send=True,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=False,
        )
        assert_equal(record_only_event.get("reason"), "record_only_mode", "record-only mode should capture but not reply")

        settings_store.save(
            {
                "enabled": True,
                "reply_mode": "full_auto",
                "record_messages": True,
                "auto_learn": False,
                "use_llm": True,
                "rag_enabled": True,
                "data_capture_enabled": True,
                "handoff_enabled": False,
                "operator_alert_enabled": False,
            }
        )
        no_handoff_config = apply_local_customer_service_settings(load_smoke_config())
        no_handoff_event = process_target(
            connector=FakeConnector([{"id": "risk-1", "type": "text", "content": "买10台冰箱能按20台价格吗？", "sender": "self"}]),  # type: ignore[arg-type]
            target=parse_targets(no_handoff_config)[0],
            config=no_handoff_config,
            rules=load_rules(resolve_path(no_handoff_config.get("rules_path"))),
            state={"version": 1, "targets": {}},
            send=True,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=False,
        )
        assert_equal(no_handoff_event.get("reason"), "operator_handoff_disabled", "handoff-off switch should block risky handoff replies")
    finally:
        remove_file(settings_store.settings_path)
        if old_tenant is None:
            os.environ.pop("WECHAT_KNOWLEDGE_TENANT", None)
        else:
            os.environ["WECHAT_KNOWLEDGE_TENANT"] = old_tenant


def check_deepseek_v4_pro_is_default() -> None:
    assert_equal(
        resolve_deepseek_model(read_secret_fn=lambda name: ""),
        "deepseek-v4-pro",
        "DeepSeek default model should use the 1M-context V4 Pro model",
    )
    assert_true(
        DEFAULT_DEEPSEEK_CONTEXT_WINDOW_TOKENS >= 1_000_000,
        "DeepSeek V4 Pro context-window metadata should document 1M-token support",
    )
    assert_equal(
        resolve_deepseek_tier_model(tier="flash", read_secret_fn=lambda name: ""),
        "deepseek-v4-flash",
        "DeepSeek Flash tier should use the cheaper V4 Flash model",
    )
    assert_equal(
        resolve_deepseek_tier_model(tier="pro", read_secret_fn=lambda name: ""),
        "deepseek-v4-pro",
        "DeepSeek Pro tier should keep the 1M-context V4 Pro model",
    )


def check_llm_reply_application_guards() -> None:
    config = load_boundary_config()
    config.setdefault("reply", {})["prefix"] = "[LLM测试] "
    decision = ReplyDecision(
        reply_text="这个问题我当前无法直接确认。",
        rule_name="no_rule_matched",
        matched=False,
        need_handoff=False,
        reason="no_rule_matched",
    )
    base_intent = {
        "evidence": {"product_ids": ["commercial_fridge_bx_200"], "safety": {"must_handoff": False}},
        "llm_advisory": {
            "result": {
                "validation": {
                    "ok": True,
                    "candidate": {
                        "intent": "product_selection",
                        "confidence": 0.83,
                        "recommended_action": "answer_from_evidence",
                        "safe_to_auto_send": True,
                        "needs_handoff": False,
                        "suggested_reply": "可以先看商用冰箱 BX-200，现货，适合小店放饮料。",
                        "reason": "matched_product_scene",
                    },
                }
            }
        },
    }
    applied = maybe_apply_llm_reply(
        config=config,
        decision=decision,
        reply_text="",
        intent_assist=copy.deepcopy(base_intent),
        product_knowledge={"matched": True},
        data_capture={"is_customer_data": False},
    )
    assert_true(bool(applied.get("applied")), "safe LLM candidate with evidence should be applied")
    assert_true(
        str(applied.get("reply_text") or "").startswith(configured_reply_prefix(config)),
        "applied LLM reply should keep configured prefix",
    )

    handoff_intent = copy.deepcopy(base_intent)
    handoff_intent["evidence"]["safety"]["must_handoff"] = True
    blocked_by_safety = maybe_apply_llm_reply(
        config=config,
        decision=decision,
        reply_text="",
        intent_assist=handoff_intent,
        product_knowledge={"matched": True},
        data_capture={"is_customer_data": False},
    )
    assert_true(not blocked_by_safety.get("applied"), "LLM must not override evidence safety handoff")
    assert_equal(
        blocked_by_safety.get("reason"),
        "handoff_required_before_llm_reply",
        "safety block reason should be explicit",
    )

    unsafe_intent = copy.deepcopy(base_intent)
    unsafe_intent["llm_advisory"]["result"]["validation"]["candidate"]["safe_to_auto_send"] = False
    blocked_by_candidate = maybe_apply_llm_reply(
        config=config,
        decision=decision,
        reply_text="",
        intent_assist=unsafe_intent,
        product_knowledge={"matched": True},
        data_capture={"is_customer_data": False},
    )
    assert_true(not blocked_by_candidate.get("applied"), "unsafe LLM candidate should not be applied")


def check_llm_boundary_fallback_on_invalid_model_output() -> None:
    original_read_secret = customer_intent_assist_module.read_secret
    original_post = customer_intent_assist_module.post_deepseek_chat
    try:
        customer_intent_assist_module.read_secret = (
            lambda name: "unit-test-key" if name == "DEEPSEEK_API_KEY" else ""
        )
        customer_intent_assist_module.post_deepseek_chat = lambda **kwargs: {
            "ok": True,
            "provider": "deepseek",
            "model": kwargs.get("model"),
            "base_url": kwargs.get("base_url"),
            "status": 200,
            "response_text": "这不是 JSON",
        }
        heuristic = IntentAssistResult(
            enabled=True,
            mode="heuristic",
            intent="approval_required",
            confidence=0.82,
            suggested_reply="这个优惠需要我先请示上级确认，确认后再给您准确回复。",
            recommended_action="handoff_for_approval",
            safe_to_auto_send=True,
            needs_handoff=True,
            reason="unit_test_boundary",
            fields={},
            missing_fields=[],
        )
        result = call_deepseek_advisory(
            "直接给我破例按最低价，再免安装费",
            context={},
            heuristic=heuristic,
            model="unit-test-model",
            base_url="https://example.test",
            timeout=1,
        )
    finally:
        customer_intent_assist_module.read_secret = original_read_secret
        customer_intent_assist_module.post_deepseek_chat = original_post

    assert_true(bool(result.get("ok")), "invalid LLM JSON should safely fall back for boundary cases")
    assert_equal(result.get("fallback"), "heuristic_boundary", "boundary fallback marker should be explicit")
    candidate = ((result.get("validation", {}) or {}).get("candidate", {}) or {})
    assert_true(bool(candidate.get("needs_handoff")), "boundary fallback must require handoff")
    assert_equal(
        candidate.get("recommended_action"),
        "handoff_for_approval",
        "boundary fallback should preserve approval action",
    )


def check_review_queue_reports_pending_and_handoff_items() -> None:
    TEST_ARTIFACTS.mkdir(parents=True, exist_ok=True)
    config_path = TEST_ARTIFACTS / "workflow_logic_review_queue_config.json"
    state_path = TEST_ARTIFACTS / "workflow_logic_review_queue_state.json"
    audit_path = TEST_ARTIFACTS / "workflow_logic_review_queue_audit.jsonl"
    config = load_smoke_config()
    config["state_path"] = str(state_path)
    config["audit_log_path"] = str(audit_path)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    state_payload = {
        "version": 1,
        "targets": {
            "文件传输助手": {
                "processed_message_ids": [],
                "handoff_message_ids": ["risk-1"],
                "pending_customer_data": [
                    {
                        "status": "waiting_for_fields",
                        "missing_required_fields": ["name"],
                        "missing_required_labels": ["姓名"],
                        "message_ids": ["lead-1"],
                        "raw_text": "电话：13900001111",
                        "fields": {"phone": "13900001111"},
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                ],
                "handoff_events": [
                    {
                        "status": "open",
                        "reason": "approval_required",
                        "message_ids": ["risk-1"],
                        "message_contents": ["能不能直接按 20 台价格给我？"],
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                    }
                ],
            }
        },
    }
    state_path.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_path.write_text("", encoding="utf-8")

    queue = build_review_queue(config_path=config_path, include_resolved=False, limit=20)
    assert_true(bool(queue.get("ok")), "review queue should build")
    counts = queue.get("counts", {})
    assert_equal(counts.get("open_pending_customer_data"), 1, "queue should report one open pending data item")
    assert_equal(counts.get("handoff"), 1, "queue should report one open handoff item")
    kinds = [item.get("kind") for item in queue.get("items", [])]
    assert_true("pending_customer_data" in kinds, "queue should include pending data item")
    assert_true("handoff" in kinds, "queue should include handoff item")


def check_evidence_boundary_cases() -> None:
    cases = [
        {
            "name": "fuzzy product scene maps to fridge",
            "text": "我开个小店，想找个能放饮料的冷柜，别太复杂",
            "expect_product": "commercial_fridge_bx_200",
            "expect_handoff": False,
        },
        {
            "name": "small talk remains safe",
            "text": "哈哈我先随便看看，你们客服回复还挺快的",
            "expect_style": "small_talk_service_pivot",
            "expect_handoff": False,
        },
        {
            "name": "unrelated travel request is no relevant evidence",
            "text": "你能帮我订明天去上海的机票和酒店吗",
            "expect_handoff": True,
            "expect_safety_reason_in": "no_relevant_business_evidence",
        },
        {
            "name": "weak policy answer match does not authorize unknown business-adjacent question",
            "text": "你们老板喜欢什么颜色的包装？\n[live-regression:test:19:1]",
            "expect_handoff": True,
            "expect_safety_reason_in": "no_relevant_business_evidence",
        },
        {
            "name": "unauthorized discount asks for approval",
            "text": "我买 7 台冰箱，你直接给我按 20 台价，再免安装费吧",
            "expect_product": "commercial_fridge_bx_200",
            "expect_handoff": True,
        },
    ]
    for case in cases:
        pack = build_evidence_pack(case["text"], context={})
        evidence = pack.get("evidence", {})
        safety = pack.get("safety", {})
        if case.get("expect_product"):
            assert_true(
                case["expect_product"] in [item.get("id") for item in evidence.get("products", []) or []],
                f"{case['name']} should map to expected product",
            )
        if case.get("expect_style"):
            assert_true(
                case["expect_style"] in [item.get("id") for item in evidence.get("style_examples", []) or []],
                f"{case['name']} should include expected style example",
            )
        assert_equal(
            bool(safety.get("must_handoff")),
            bool(case["expect_handoff"]),
            f"{case['name']} handoff classification",
        )
        if case.get("expect_safety_reason_in"):
            assert_equal(
                case["expect_safety_reason_in"] in (safety.get("reasons") or []),
                True,
                f"{case['name']} safety reason",
            )


def check_after_sales_intent_preempts_duration_logistics() -> None:
    result = customer_intent_assist_module.analyze_intent("商用冰箱保修多久？坏了怎么办？")
    assert_equal(result.intent, "after_sales_policy", "warranty duration should be after-sales, not logistics")


def load_smoke_config() -> dict[str, Any]:
    config = copy.deepcopy(load_config(CONFIG_PATH))
    config.setdefault("operator_alert", {})["enabled"] = False
    return config


def load_boundary_config() -> dict[str, Any]:
    config = copy.deepcopy(load_config(BOUNDARY_CONFIG_PATH))
    config.setdefault("operator_alert", {})["enabled"] = False
    return config


def remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
