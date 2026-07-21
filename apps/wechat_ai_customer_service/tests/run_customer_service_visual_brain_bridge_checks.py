from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import listen_and_reply as workflow_module  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    merge_scheduler_conversation_context,
)
from listen_and_reply import TargetConfig, process_target  # noqa: E402


def main() -> int:
    checks = [
        check_process_target_routes_image_only_turn_to_brain_with_visual_bridge_input,
        check_image_product_binding_reaches_followup_brain_without_previous_product_facts,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


class FakeConnector:
    def get_messages(self, target: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "target": target,
            "exact": exact,
            "adapter": "win32_ocr",
            "state": "messages_ocr",
            "messages": [],
        }


class FollowupConnector:
    def get_messages(self, target: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "target": target,
            "exact": exact,
            "adapter": "win32_ocr",
            "state": "messages_ocr",
            "messages": [
                {
                    "id": "followup-stock-1",
                    "message_id": "followup-stock-1",
                    "type": "text",
                    "sender": "customer",
                    "content": "现车还在吗",
                }
            ],
        }


def check_process_target_routes_image_only_turn_to_brain_with_visual_bridge_input() -> None:
    captured: dict[str, Any] = {}
    original_route = workflow_module.maybe_route_customer_image_turn
    original_brain = workflow_module.maybe_run_customer_service_brain
    original_intent = workflow_module.maybe_analyze_intent
    try:
        workflow_module.maybe_route_customer_image_turn = lambda **kwargs: {
            "enabled": True,
            "applied": True,
            "adoptable": True,
            "reason": "customer_image_turn_ready",
            "visual_bridge_input": {
                "present": True,
                "vision_summary": "图片主体是一辆白色轿车",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.93},
                "catalog_assist": {"normalized_vehicle_query": "比亚迪 秦PLUS DM-i", "candidate_names": ["比亚迪 秦PLUS DM-i"]},
            },
            "target_state_for_brain": {
                "conversation_context": {"last_customer_need_text": "比亚迪 秦PLUS DM-i"},
                "visual_context_state": {"last_visual_summary": "图片主体是一辆白色轿车"},
            },
            "combined_text_override": "客户发来了一张图片",
            "proxy_batch": [
                {
                    "id": "visual_proxy:test",
                    "message_id": "visual_proxy:test",
                    "type": "text",
                    "sender": "customer",
                    "sender_role": "customer",
                    "content": "客户发来了一张图片",
                }
            ],
            "conversation_context_patch": {
                "last_customer_need_text": "比亚迪 秦PLUS DM-i",
                "last_product_id": "chejin_qinplus_2022_dmi55",
                "last_product_name": "2022款比亚迪秦PLUS DM-i 55KM",
                "recent_product_ids": ["chejin_qinplus_2022_dmi55"],
            },
            "visual_context_state_patch": {"last_visual_summary": "图片主体是一辆白色轿车"},
        }

        def fake_brain(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "enabled": True,
                "mode": "brain_first",
                "applied": True,
                "adoptable": True,
                "visible_reply_owner": "brain",
                "raw_reply_text": "我这边先帮你看看这台车",
                "rule_name": "customer_service_brain_reply",
                "reason": "customer_image_turn_ready",
            }

        workflow_module.maybe_run_customer_service_brain = fake_brain
        workflow_module.maybe_analyze_intent = lambda **kwargs: {"needs_handoff": False}
        config = {
            "_local_customer_service_settings": {
                "enabled": True,
                "record_messages": False,
                "reply_mode": "manual_assist",
            },
            "raw_messages": {"enabled": False},
            "product_knowledge": {"enabled": False},
            "auto_voice_transcription": {"enabled": False},
            "customer_service_brain": {"enabled": True, "mode": "brain_first", "fallback_to_legacy_on_error": False},
            "reply": {"allow_fallback_send": False},
        }
        target = TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=8, session_key="wx:test")
        state = {"targets": {}}
        result = process_target(
            connector=FakeConnector(),
            target=target,
            config=copy.deepcopy(config),
            rules={},
            state=state,
            send=False,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=True,
        )
    finally:
        workflow_module.maybe_route_customer_image_turn = original_route
        workflow_module.maybe_run_customer_service_brain = original_brain
        workflow_module.maybe_analyze_intent = original_intent
    assert_true(bool(captured.get("visual_bridge_input")), f"visual bridge input should be passed to brain: {captured}")
    assert_equal(
        str(((captured.get("visual_bridge_input") or {}).get("catalog_assist") or {}).get("normalized_vehicle_query") or ""),
        "比亚迪 秦PLUS DM-i",
        "brain should receive normalized vehicle query",
    )
    assert_equal(
        str((captured.get("target_state") or {}).get("conversation_context", {}).get("last_customer_need_text") or ""),
        "比亚迪 秦PLUS DM-i",
        "brain target_state should receive image-derived conversation context",
    )
    assert_true(bool(result.get("customer_service_brain_adopted")), f"process_target should adopt brain reply: {result}")
    assert_true(bool(result.get("brain_visual_context_used")), f"event should record bridge usage: {result}")
    context_update = result.get("conversation_context_update") if isinstance(result.get("conversation_context_update"), dict) else {}
    assert_equal(
        context_update.get("last_product_id"),
        "chejin_qinplus_2022_dmi55",
        "image-derived product binding must leave the current turn as a persistent scheduler context update",
    )
    assert_equal(
        result.get("conversation_context_update_source"),
        "customer_image_turn",
        "image-derived context source must remain auditable even when no later reply evidence adds fields",
    )


def check_image_product_binding_reaches_followup_brain_without_previous_product_facts() -> None:
    scheduler_state: dict[str, Any] = {"sessions": {}, "events": []}
    merge_scheduler_conversation_context(
        scheduler_state,
        "客户A",
        {
            "last_product_id": "old-audi-a4l",
            "last_product_name": "奥迪A4L",
            "last_unit_price": 25.8,
            "last_product_source": "product_master",
            "last_shipping_city": "南京",
        },
        session_key="wx:followup",
        now="2026-07-18T14:00:00",
    )
    merge_scheduler_conversation_context(
        scheduler_state,
        "客户A",
        {
            "last_product_id": "chejin_hengyi_2019_es6",
            "last_product_name": "2019款蔚来ES6",
            "recent_product_ids": ["chejin_hengyi_2019_es6"],
            "vehicle_image_match": {"product_id": "chejin_hengyi_2019_es6", "similarity": 1.0},
        },
        session_key="wx:followup",
        now="2026-07-18T14:00:01",
    )
    persisted_context = next(iter(scheduler_state["sessions"].values()))["conversation_context"]
    observed: dict[str, Any] = {}
    original_route = workflow_module.maybe_route_customer_image_turn
    original_brain = workflow_module.maybe_run_customer_service_brain
    original_intent = workflow_module.maybe_analyze_intent
    try:
        workflow_module.maybe_route_customer_image_turn = lambda **_kwargs: {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "current_image_pending_signal_missing",
        }

        def fake_brain(**kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            return {
                "enabled": True,
                "mode": "brain_first",
                "applied": True,
                "adoptable": True,
                "visible_reply_owner": "brain",
                "raw_reply_text": "我按这台蔚来ES6帮你核实当前库存状态。",
                "rule_name": "customer_service_brain_reply",
                "reason": "followup_product_context_ready",
            }

        workflow_module.maybe_run_customer_service_brain = fake_brain
        workflow_module.maybe_analyze_intent = lambda **_kwargs: {"needs_handoff": False}
        config = {
            "_local_customer_service_settings": {"enabled": True, "record_messages": False, "reply_mode": "manual_assist"},
            "raw_messages": {"enabled": False},
            "product_knowledge": {"enabled": False},
            "auto_voice_transcription": {"enabled": False},
            "customer_service_brain": {"enabled": True, "mode": "brain_first", "fallback_to_legacy_on_error": False},
            "reply": {"allow_fallback_send": False},
        }
        result = process_target(
            connector=FollowupConnector(),
            target=TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=8, session_key="wx:followup"),
            config=config,
            rules={},
            state={"targets": {"wx:followup": {"conversation_context": copy.deepcopy(persisted_context)}}},
            send=False,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=True,
        )
    finally:
        workflow_module.maybe_route_customer_image_turn = original_route
        workflow_module.maybe_run_customer_service_brain = original_brain
        workflow_module.maybe_analyze_intent = original_intent
    followup_context = (observed.get("target_state") or {}).get("conversation_context") or {}
    assert_equal(followup_context.get("last_product_id"), "chejin_hengyi_2019_es6", "follow-up Brain must receive the image-matched product id")
    assert_equal(followup_context.get("last_product_name"), "2019款蔚来ES6", "follow-up Brain must receive the image-matched product name")
    assert_true("last_unit_price" not in followup_context, "follow-up Brain must not receive the previous Audi price")
    assert_true("last_product_source" not in followup_context, "follow-up Brain must not receive the previous Audi authority label")
    assert_equal(followup_context.get("last_shipping_city"), "南京", "stable customer preference must survive into the follow-up")
    assert_true(bool(result.get("customer_service_brain_adopted")), f"follow-up must remain Brain-authored and adoptable: {result}")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
