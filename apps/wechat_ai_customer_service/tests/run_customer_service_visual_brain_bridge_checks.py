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
from apps.wechat_ai_customer_service.optional_plugins.registry import (  # noqa: E402
    register_optional_capability,
    reset_optional_capabilities_for_tests,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.projection.message import (  # noqa: E402
    build_brain_safe_image_proxy_message,
)
from apps.wechat_ai_customer_service.optional_plugins.vision import runtime as vision_runtime  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.plugin import BuiltinVisionPlugin  # noqa: E402
from listen_and_reply import TargetConfig, process_target  # noqa: E402


def main() -> int:
    checks = [
        check_private_vision_evidence_failure_stops_before_brain_ready_send,
        check_builtin_vision_group_acquire_failure_stops_before_brain_ready_send,
        check_private_vision_failure_plugin_leaves_plain_text_unchanged,
        check_missing_vision_plugin_leaves_plain_text_unchanged,
        check_custom_vision_plugin_ready_turn_still_reaches_brain,
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


class MessageConnector:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.messages = [copy.deepcopy(item) for item in messages]
        self.send_calls = 0

    def get_messages(self, target: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "target": target,
            "exact": exact,
            "adapter": "win32_ocr",
            "state": "messages_ocr",
            "messages": [copy.deepcopy(item) for item in self.messages],
        }

    def send_message(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.send_calls += 1
        return {"ok": True, "verified": True}


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


class VisionEvidenceUnavailable(RuntimeError):
    pass


class FailingImageOnlyVisionPlugin:
    capability = "vision"
    name = "failing_image_only_vision"

    def __init__(self) -> None:
        self.run_calls = 0
        self.confirmed_image_payload = False

    def available(self) -> bool:
        return True

    def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"should_run": False, "reason": "test_plugin_runtime_only"}

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        self.run_calls += 1
        payload = context.get("payload") if isinstance(context.get("payload"), dict) else {}
        messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
        batch = context.get("batch") if isinstance(context.get("batch"), list) else []
        self.confirmed_image_payload = any(
            isinstance(item, dict) and bool(item.get("is_customer_image_proxy"))
            for item in [*messages, *batch]
        )
        if self.confirmed_image_payload:
            raise VisionEvidenceUnavailable("vision_private_required_image_evidence_failed")
        return {
            "enabled": True,
            "applied": False,
            "adoptable": False,
            "reason": "no_current_customer_image_turn",
        }


class ReadyCustomVisionPlugin:
    capability = "vision"
    name = "ready_custom_vision"

    def available(self) -> bool:
        return True

    def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"should_run": True, "reason": "custom_vision_ready"}

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "enabled": True,
            "applied": True,
            "adoptable": True,
            "reason": "customer_image_turn_ready",
            "visual_bridge_input": {
                "present": True,
                "vision_summary": "自定义视觉插件识别到一张白色车辆图片",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.91},
                "catalog_assist": {"normalized_vehicle_query": "白色车辆"},
            },
            "target_state_for_brain": {
                "conversation_context": {"last_customer_need_text": "白色车辆"},
                "visual_context_state": {"last_visual_summary": "自定义视觉插件识别到一张白色车辆图片"},
            },
            "combined_text_override": "客户发来了一张图片",
            "proxy_batch": [
                {
                    "id": "visual_proxy:custom",
                    "message_id": "visual_proxy:custom",
                    "type": "text",
                    "sender": "customer",
                    "sender_role": "customer",
                    "content": "客户发来了一张图片",
                }
            ],
            "conversation_context_patch": {"last_customer_need_text": "白色车辆"},
            "visual_context_state_patch": {"last_visual_summary": "自定义视觉插件识别到一张白色车辆图片"},
        }


def brain_first_test_config() -> dict[str, Any]:
    return {
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


def customer_text_message(message_id: str = "text-1", content: str = "这台车还有吗") -> dict[str, Any]:
    return {
        "id": message_id,
        "message_id": message_id,
        "type": "text",
        "sender": "customer",
        "sender_role": "customer",
        "content": content,
    }


def run_process_target_with_brain_probe(
    *,
    connector: Any,
    config: dict[str, Any] | None = None,
    send: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    captured: dict[str, Any] = {"calls": 0}
    original_brain = workflow_module.maybe_run_customer_service_brain
    original_intent = workflow_module.maybe_analyze_intent
    try:
        def fake_brain(**kwargs: Any) -> dict[str, Any]:
            captured["calls"] = int(captured.get("calls") or 0) + 1
            captured.update(kwargs)
            return {
                "enabled": True,
                "mode": "brain_first",
                "applied": True,
                "adoptable": True,
                "visible_reply_owner": "brain",
                "raw_reply_text": "我这边帮你看一下。",
                "rule_name": "customer_service_brain_reply",
                "reason": "brain_ready_for_test",
            }

        workflow_module.maybe_run_customer_service_brain = fake_brain
        workflow_module.maybe_analyze_intent = lambda **_kwargs: {"needs_handoff": False}
        result = process_target(
            connector=connector,
            target=TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=8, session_key="wx:test"),
            config=copy.deepcopy(config or brain_first_test_config()),
            rules={},
            state={"targets": {}},
            send=send,
            write_data=False,
            allow_fallback_send=False,
            mark_dry_run=False,
        )
        return result, captured
    finally:
        workflow_module.maybe_run_customer_service_brain = original_brain
        workflow_module.maybe_analyze_intent = original_intent


def check_private_vision_evidence_failure_stops_before_brain_ready_send() -> None:
    reset_optional_capabilities_for_tests()
    plugin = FailingImageOnlyVisionPlugin()
    register_optional_capability("vision", plugin=plugin)
    connector = MessageConnector(
        [
            build_brain_safe_image_proxy_message(
                {
                    "pending_signal_id": "pending-image-1",
                    "pending_signal_kind": "image_capture",
                    "pending_signal_text": "[图片]",
                },
                target_name="客户A",
                session_key="wx:test",
            )
        ]
    )
    brain_calls = {"count": 0}
    original_brain = workflow_module.maybe_run_customer_service_brain
    original_intent = workflow_module.maybe_analyze_intent
    try:
        workflow_module.maybe_run_customer_service_brain = lambda **_kwargs: brain_calls.__setitem__("count", brain_calls["count"] + 1) or {
            "enabled": True,
            "mode": "brain_first",
            "applied": True,
            "adoptable": True,
            "visible_reply_owner": "brain",
            "raw_reply_text": "不应生成这条回复",
            "rule_name": "customer_service_brain_reply",
            "reason": "unexpected_brain_call",
        }
        workflow_module.maybe_analyze_intent = lambda **_kwargs: {"needs_handoff": False}
        raised = False
        try:
            process_target(
                connector=connector,
                target=TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=8, session_key="wx:test"),
                config=brain_first_test_config(),
                rules={},
                state={"targets": {}},
                send=True,
                write_data=False,
                allow_fallback_send=False,
                mark_dry_run=False,
            )
        except VisionEvidenceUnavailable:
            raised = True
    finally:
        workflow_module.maybe_run_customer_service_brain = original_brain
        workflow_module.maybe_analyze_intent = original_intent
        reset_optional_capabilities_for_tests()
    assert_true(raised, "private Vision evidence failure must propagate through the neutral dispatch seam")
    assert_true(plugin.confirmed_image_payload, "test must represent a current required image payload")
    assert_equal(brain_calls["count"], 0, "Brain must not run after required Vision evidence failure")
    assert_equal(connector.send_calls, 0, "send must not run after required Vision evidence failure")


def check_builtin_vision_group_acquire_failure_stops_before_brain_ready_send() -> None:
    reset_optional_capabilities_for_tests()
    register_optional_capability("vision", plugin=BuiltinVisionPlugin())
    connector = MessageConnector(
        [
            build_brain_safe_image_proxy_message(
                {
                    "pending_signal_id": "pending-image-runtime",
                    "pending_signal_kind": "image_capture",
                    "pending_signal_text": "[图片]",
                },
                target_name="客户A",
                session_key="wx:test",
            )
        ]
    )
    brain_calls = {"count": 0}
    provider_calls = {"count": 0}
    acquire_calls = {"count": 0}
    original_brain = workflow_module.maybe_run_customer_service_brain
    original_intent = workflow_module.maybe_analyze_intent
    original_acquire = vision_runtime._run_current_visual_group_acquire
    original_understanding = vision_runtime.maybe_run_customer_image_understanding
    try:
        workflow_module.maybe_run_customer_service_brain = lambda **_kwargs: brain_calls.__setitem__("count", brain_calls["count"] + 1) or {
            "enabled": True,
            "mode": "brain_first",
            "applied": True,
            "adoptable": True,
            "visible_reply_owner": "brain",
            "raw_reply_text": "不应生成这条回复",
            "rule_name": "customer_service_brain_reply",
            "reason": "unexpected_brain_call",
        }
        workflow_module.maybe_analyze_intent = lambda **_kwargs: {"needs_handoff": False}

        def fake_acquire(**_kwargs: Any) -> dict[str, Any]:
            acquire_calls["count"] += 1
            return {
                "ok": False,
                "reason": "visual_group_not_found",
                "transaction": {"status": "visual_group_not_found"},
                "_ephemeral_clipboard_images": [],
            }

        def fake_understanding(**_kwargs: Any) -> dict[str, Any]:
            provider_calls["count"] += 1
            return {}

        vision_runtime._run_current_visual_group_acquire = fake_acquire
        vision_runtime.maybe_run_customer_image_understanding = fake_understanding
        raised = False
        try:
            process_target(
                connector=connector,
                target=TargetConfig(name="客户A", enabled=True, exact=True, allow_self_for_test=False, max_batch_messages=8, session_key="wx:test"),
                config=brain_first_test_config(),
                rules={},
                state={"targets": {}},
                send=True,
                write_data=False,
                allow_fallback_send=False,
                mark_dry_run=False,
            )
        except vision_runtime._VisionEvidenceUnavailable:
            raised = True
    finally:
        workflow_module.maybe_run_customer_service_brain = original_brain
        workflow_module.maybe_analyze_intent = original_intent
        vision_runtime._run_current_visual_group_acquire = original_acquire
        vision_runtime.maybe_run_customer_image_understanding = original_understanding
        reset_optional_capabilities_for_tests()
    assert_true(raised, "built-in Vision acquire failure must propagate through neutral dispatch")
    assert_equal(acquire_calls["count"], 1, "built-in Vision must attempt the strict group acquire once")
    assert_equal(provider_calls["count"], 0, "provider must not run when strict acquire fails")
    assert_equal(brain_calls["count"], 0, "Brain must not run after built-in Vision acquire failure")
    assert_equal(connector.send_calls, 0, "send must not run after built-in Vision acquire failure")


def check_private_vision_failure_plugin_leaves_plain_text_unchanged() -> None:
    reset_optional_capabilities_for_tests()
    plugin = FailingImageOnlyVisionPlugin()
    register_optional_capability("vision", plugin=plugin)
    try:
        result, captured = run_process_target_with_brain_probe(
            connector=MessageConnector([customer_text_message()])
        )
    finally:
        reset_optional_capabilities_for_tests()
    assert_equal(plugin.run_calls, 1, "Vision runtime seam should still be invoked once")
    assert_true(not plugin.confirmed_image_payload, "plain text must not be treated as required image evidence")
    assert_equal(captured.get("calls"), 1, "Brain should still handle an ordinary text turn")
    assert_true(bool(result.get("customer_service_brain_adopted")), f"ordinary text should remain Brain-authored: {result}")


def check_missing_vision_plugin_leaves_plain_text_unchanged() -> None:
    reset_optional_capabilities_for_tests()
    register_optional_capability(
        "vision",
        factory_path="apps.wechat_ai_customer_service.optional_plugins.missing:create_plugin",
    )
    try:
        result, captured = run_process_target_with_brain_probe(
            connector=MessageConnector([customer_text_message(message_id="text-no-vision", content="你好")])
        )
    finally:
        reset_optional_capabilities_for_tests()
    assert_equal(captured.get("calls"), 1, "Brain should still handle text when Vision plugin is absent")
    assert_true(bool(result.get("customer_service_brain_adopted")), f"missing Vision plugin should not block text: {result}")
    assert_equal(
        str((result.get("customer_image_turn") or {}).get("reason") or ""),
        "vision_capability_unavailable",
        "missing Vision plugin should preserve the absence-safe reason",
    )


def check_custom_vision_plugin_ready_turn_still_reaches_brain() -> None:
    reset_optional_capabilities_for_tests()
    register_optional_capability("vision", plugin=ReadyCustomVisionPlugin())
    try:
        result, captured = run_process_target_with_brain_probe(
            connector=MessageConnector([])
        )
    finally:
        reset_optional_capabilities_for_tests()
    assert_equal(captured.get("calls"), 1, "custom Vision ready turn should still reach Brain")
    assert_true(bool(captured.get("visual_bridge_input")), f"custom Vision bridge input should reach Brain: {captured}")
    assert_true(bool(result.get("customer_service_brain_adopted")), f"custom Vision ready turn should remain adoptable: {result}")
    assert_true(bool(result.get("brain_visual_context_used")), f"custom Vision evidence should be recorded as used: {result}")


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
