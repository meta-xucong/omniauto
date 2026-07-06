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
from listen_and_reply import TargetConfig, process_target  # noqa: E402


def main() -> int:
    checks = [
        check_process_target_routes_image_only_turn_to_brain_with_visual_bridge_input,
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
            "conversation_context_patch": {"last_customer_need_text": "比亚迪 秦PLUS DM-i"},
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


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
