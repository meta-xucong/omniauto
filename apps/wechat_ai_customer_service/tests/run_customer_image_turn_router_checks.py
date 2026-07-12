from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image, ImageDraw


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
ADAPTERS_ROOT = APP_ROOT / "adapters"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT, ADAPTERS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_image_turn_router as router_module  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import session_split_x  # noqa: E402


def main() -> int:
    checks = [
        check_customer_image_capture_trigger_is_metadata_only,
        check_router_detects_customer_image_region_and_builds_bridge,
        check_router_uses_payload_saved_image_without_sidecar,
        check_router_saves_pending_image_signal_and_builds_safe_proxy,
        check_router_skips_when_visual_region_missing,
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


def check_customer_image_capture_trigger_is_metadata_only() -> None:
    normal = router_module.customer_image_capture_trigger(
        payload={
            "messages": [
                {
                    "type": "text",
                    "sender": "customer",
                    "content": "比亚迪秦PLUS还有现车吗",
                }
            ]
        },
        pending_signal={
            "pending_signal_kind": "normal",
            "pending_signal_text": "比亚迪秦PLUS还有现车吗",
        },
    )
    assert_true(normal.get("should_run") is False, f"normal text should not invoke image module: {normal}")

    image = router_module.customer_image_capture_trigger(
        payload={"messages": []},
        pending_signal={"pending_signal_kind": "image_capture", "pending_signal_text": "[图片]"},
    )
    assert_true(image.get("should_run") is True, f"image signal should invoke image module: {image}")

    already_processed = router_module.customer_image_capture_trigger(
        payload={"messages": []},
        pending_signal={
            "pending_signal_id": "pending-image-1",
            "pending_signal_kind": "image_capture",
            "pending_signal_text": "[图片]",
        },
        target_state={
            "conversation_context": {
                "ledger_recent_messages": [{"pending_signal_id": "pending-image-1"}],
            }
        },
    )
    assert_true(already_processed.get("should_run") is False, f"same image signal should not re-enter image module: {already_processed}")
    assert_equal(
        already_processed.get("reason"),
        "pending_image_signal_already_processed",
        "same pending image signal should expose a terminal dedupe reason",
    )

    recent_self_image = router_module.customer_image_capture_trigger(
        payload={
            "messages": [
                {"type": "text", "sender": "customer", "content": "收到"},
                {"type": "image", "sender": "self", "content": "[图片]"},
            ]
        },
        pending_signal={"pending_signal_kind": "normal", "pending_signal_text": ""},
    )
    assert_true(recent_self_image.get("should_run") is True, f"recent self image should be archived: {recent_self_image}")


class FakeConnector:
    def call_compat_sidecar(self, args: list[str], *, allow_failure: bool = False, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError(f"unexpected compat sidecar call: {args} {kwargs}")


class FakeImageSaveConnector:
    def __init__(self, saved_path: Path) -> None:
        self.saved_path = saved_path
        self.calls: list[dict[str, Any]] = []

    def save_customer_image(self, target: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"target": target, **kwargs})
        return {
            "ok": True,
            "state": "image_saved",
            "assets": [
                {
                    "asset_id": "asset-pending-1",
                    "message_id": "visual_msg_pending_1",
                    "message_type": "image",
                    "target_name": target,
                    "session_key": str(kwargs.get("session_key") or ""),
                    "saved_image_path": str(self.saved_path),
                    "source_preview": str(kwargs.get("source_preview") or ""),
                    "captured_at": "2026-07-06T12:00:00",
                }
            ],
            "messages": [
                {
                    "message_id": "visual_msg_pending_1",
                    "type": "image",
                    "message_type": "image",
                    "sender": "customer",
                    "content": "[图片]",
                    "asset_id": "asset-pending-1",
                    "image_assets": ["asset-pending-1"],
                    "saved_image_path": str(self.saved_path),
                    "source_preview": str(kwargs.get("source_preview") or ""),
                    "captured_at": "2026-07-06T12:00:00",
                }
            ],
        }


def check_router_detects_customer_image_region_and_builds_bridge() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        screenshot_path = Path(tmp_dir) / "wechat.png"
        build_synthetic_screenshot(screenshot_path, include_visual_region=True)
        original_understanding = router_module.maybe_run_customer_image_understanding
        original_catalog_assist = router_module.build_customer_image_catalog_assist
        try:
            router_module.maybe_run_customer_image_understanding = lambda **kwargs: {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "图片主体是一辆白色轿车",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.93},
                "intent_hints": {"wants_catalog_match": True, "wants_similar_recommendation": True},
                "bridge": {"normalized_vehicle_query": "比亚迪 秦PLUS DM-i", "catalog_lookup_mode": "vehicle_exact_then_similar"},
                "source_messages": [{"message_id": "m1", "asset_id": "a1", "message_type": "image"}],
            }
            router_module.build_customer_image_catalog_assist = lambda **kwargs: {
                "applied": True,
                "normalized_vehicle_query": "比亚迪 秦PLUS DM-i",
                "preferred_candidate_ids": ["car-1", "car-2"],
                "catalog_candidates_preview": [{"id": "car-1", "name": "比亚迪 秦PLUS DM-i"}],
                "exact_candidate_id": "car-1",
                "exact_candidate_name": "比亚迪 秦PLUS DM-i",
                "similar_recommendation_allowed": True,
                "conversation_context_patch": {"last_customer_need_text": "比亚迪 秦PLUS DM-i"},
            }
            result = router_module.maybe_route_customer_image_turn(
                connector=FakeConnector(),
                target=SimpleNamespace(name="客户A", exact=True, session_key="wx:test"),
                config={},
                payload={"ok": True, "adapter": "win32_ocr", "state": "messages_ocr", "screenshot_path": str(screenshot_path), "messages": []},
                target_state={},
                batch=[],
                combined="",
            )
        finally:
            router_module.maybe_run_customer_image_understanding = original_understanding
            router_module.build_customer_image_catalog_assist = original_catalog_assist
    assert_true(result.get("applied") is True, f"router should apply: {result}")
    assets = (result.get("customer_image_assets") or {}).get("assets") or []
    assert_true(bool(assets), f"router should produce at least one asset: {result}")
    asset = assets[0]
    assert_true(Path(str(asset.get("bubble_crop_path") or "")).exists(), f"crop path should exist: {asset}")
    bridge = result.get("visual_bridge_input") if isinstance(result.get("visual_bridge_input"), dict) else {}
    catalog_assist = bridge.get("catalog_assist") if isinstance(bridge.get("catalog_assist"), dict) else {}
    assert_equal(str(catalog_assist.get("normalized_vehicle_query") or ""), "比亚迪 秦PLUS DM-i", "bridge should include normalized query")
    proxy_batch = result.get("proxy_batch") or []
    assert_true(bool(proxy_batch), "router should create proxy batch for image-only turn")


def check_router_uses_payload_saved_image_without_sidecar() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.jpg"
        Image.new("RGB", (96, 64), (220, 220, 220)).save(saved_path)
        original_understanding = router_module.maybe_run_customer_image_understanding
        original_catalog_assist = router_module.build_customer_image_catalog_assist
        try:
            router_module.maybe_run_customer_image_understanding = lambda **kwargs: {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "图片里是一辆白色轿车",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.91},
                "intent_hints": {"wants_catalog_match": True},
                "bridge": {"normalized_vehicle_query": "特斯拉 Model 3"},
                "source_messages": [{"message_id": "visual_msg_saved_1", "asset_id": "asset-saved-1", "message_type": "image"}],
            }
            router_module.build_customer_image_catalog_assist = lambda **kwargs: {
                "applied": True,
                "normalized_vehicle_query": "特斯拉 Model 3",
                "preferred_candidate_ids": ["tesla-model3-1"],
                "catalog_candidates_preview": [{"id": "tesla-model3-1", "name": "特斯拉 Model 3"}],
                "similar_recommendation_allowed": True,
                "conversation_context_patch": {"last_customer_need_text": "特斯拉 Model 3"},
            }
            result = router_module.maybe_route_customer_image_turn(
                connector=FakeConnector(),
                target=SimpleNamespace(name="新数据测试", exact=True, session_key="wx:saved"),
                config={},
                payload={
                    "ok": True,
                    "adapter": "win32_ocr",
                    "state": "messages_ocr",
                    "messages": [
                        {
                            "message_id": "visual_msg_saved_1",
                            "type": "text",
                            "sender": "customer",
                            "content": "客户发来了一张图片",
                            "asset_id": "asset-saved-1",
                            "image_assets": ["asset-saved-1"],
                            "saved_image_path": str(saved_path),
                            "captured_at": "2026-07-06T12:00:00",
                        }
                    ],
                },
                target_state={},
                batch=[],
                combined="",
            )
        finally:
            router_module.maybe_run_customer_image_understanding = original_understanding
            router_module.build_customer_image_catalog_assist = original_catalog_assist
    assert_true(result.get("applied") is True, f"saved image payload should route: {result}")
    assert_equal(result.get("source_reason"), "direct_image_message", "saved_image_path should count as direct image")
    proxy = (result.get("proxy_batch") or [{}])[0]
    assert_equal(proxy.get("type"), "text", "proxy should remain text for scheduler/Brain filters")
    assert_true(not proxy.get("message_type"), f"proxy must not expose non-text message_type: {proxy}")
    assert_equal(str(proxy.get("saved_image_path") or ""), str(saved_path), "proxy should keep saved image path")


def check_router_saves_pending_image_signal_and_builds_safe_proxy() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "pending.jpg"
        Image.new("RGB", (120, 80), (210, 210, 210)).save(saved_path)
        connector = FakeImageSaveConnector(saved_path)
        original_understanding = router_module.maybe_run_customer_image_understanding
        original_catalog_assist = router_module.build_customer_image_catalog_assist
        try:
            router_module.maybe_run_customer_image_understanding = lambda **kwargs: {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "图片里是一辆特斯拉 Model 3",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.94},
                "intent_hints": {"wants_catalog_match": True},
                "bridge": {"normalized_vehicle_query": "特斯拉 Model 3"},
                "source_messages": [{"message_id": "visual_msg_pending_1", "asset_id": "asset-pending-1", "message_type": "image"}],
            }
            router_module.build_customer_image_catalog_assist = lambda **kwargs: {
                "applied": True,
                "normalized_vehicle_query": "特斯拉 Model 3",
                "preferred_candidate_ids": ["tesla-model3-1"],
                "catalog_candidates_preview": [{"id": "tesla-model3-1", "name": "特斯拉 Model 3"}],
                "similar_recommendation_allowed": True,
                "conversation_context_patch": {"last_customer_need_text": "特斯拉 Model 3"},
            }
            result = router_module.maybe_route_customer_image_turn(
                connector=connector,
                target=SimpleNamespace(name="新数据测试", exact=True, session_key="wx:pending"),
                config={},
                payload={
                    "ok": True,
                    "adapter": "win32_ocr",
                    "state": "messages_ocr",
                    "messages": [],
                    "pending_signal": {
                        "pending_signal_id": "sig-img-1",
                        "pending_signal_text": "许聪:[图片]",
                    },
                },
                target_state={},
                batch=[],
                combined="",
            )
        finally:
            router_module.maybe_run_customer_image_understanding = original_understanding
            router_module.build_customer_image_catalog_assist = original_catalog_assist
    assert_true(result.get("applied") is True, f"pending image signal should route: {result}")
    assert_equal(result.get("source_reason"), "empty_capture_image_pending", "empty text batch should use pending image source")
    assert_equal(len(connector.calls), 1, f"image-save should be called exactly once: {connector.calls}")
    call = connector.calls[0]
    assert_equal(call.get("source_preview"), "许聪:[图片]", "source preview should be passed to image save")
    assert_equal(call.get("speaker_name"), "许聪", "speaker should be parsed from preview")
    proxy = (result.get("proxy_batch") or [{}])[0]
    assert_equal(proxy.get("type"), "text", "pending image proxy should be text")
    assert_true(not proxy.get("message_type"), f"pending proxy must not expose non-text message_type: {proxy}")
    assert_equal(str(proxy.get("saved_image_path") or ""), str(saved_path), "pending proxy should keep saved image path")


def check_router_skips_when_visual_region_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        screenshot_path = Path(tmp_dir) / "wechat_blank.png"
        build_synthetic_screenshot(screenshot_path, include_visual_region=False)
        result = router_module.maybe_route_customer_image_turn(
            connector=FakeConnector(),
            target=SimpleNamespace(name="客户A", exact=True, session_key="wx:test"),
            config={},
            payload={"ok": True, "adapter": "win32_ocr", "state": "messages_ocr", "screenshot_path": str(screenshot_path), "messages": []},
            target_state={},
            batch=[],
            combined="",
        )
    assert_true(result.get("applied") is False, f"blank screenshot should not produce image turn: {result}")


def build_synthetic_screenshot(path: Path, *, include_visual_region: bool) -> None:
    width, height = 980, 860
    image = Image.new("RGB", (width, height), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    split = session_split_x(width)
    draw.rectangle([0, 0, split, height], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, width - 8, height - 95], fill=(255, 255, 255))
    if include_visual_region:
        left = split + 40
        top = 260
        right = left + 220
        bottom = top + 180
        for index in range(0, 220, 10):
            color = (40 + (index % 120), 90 + (index % 80), 160 + (index % 60))
            draw.rectangle([left + index, top, min(right, left + index + 10), bottom], fill=color)
    image.save(path)


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
