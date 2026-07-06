from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
for path in (PROJECT_ROOT, WORKFLOWS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from customer_image_brain_bridge import (  # noqa: E402
    augment_text_with_visual_query,
    build_customer_image_brain_bridge,
    resolve_visual_brain_turn_text,
)
from customer_image_understanding_contract import normalize_customer_image_understanding_result  # noqa: E402
from customer_image_understanding_provider import (  # noqa: E402
    build_anthropic_messages_vision_payload,
    build_openai_chat_vision_payload,
)


SAMPLE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def main() -> int:
    checks = [
        check_openai_chat_vision_payload_uses_data_url,
        check_anthropic_messages_vision_payload_uses_base64_image_source,
        check_visual_bridge_turn_text_fallback_for_image_only,
        check_augment_text_with_visual_query,
        check_normalize_customer_image_understanding_result_defaults,
        check_normalize_customer_image_understanding_result_handles_provider_shape_drift,
        check_saved_image_path_is_preferred_for_provider_input,
        check_image_understanding_prompt_includes_catalog_identity_candidates,
        check_image_understanding_dedupes_paths_and_uses_larger_budget,
        check_image_understanding_retries_after_non_json_response,
        check_image_understanding_archives_prompt_and_result,
        check_image_understanding_archive_failure_does_not_break_flow,
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


def check_openai_chat_vision_payload_uses_data_url() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "sample.png"
        image_path.write_bytes(SAMPLE_PNG)
        payload = build_openai_chat_vision_payload(
            model="test-model",
            prompt="识别图片",
            image_paths=[str(image_path)],
        )
    content = ((payload.get("messages") or [{}])[0] or {}).get("content") or []
    assert_true(isinstance(content, list) and len(content) == 2, f"unexpected content: {content}")
    image_part = content[1]
    assert_equal(str(image_part.get("type") or ""), "image_url", "openai payload should use image_url part")
    url = (((image_part.get("image_url") or {}) if isinstance(image_part, dict) else {}).get("url") or "")
    assert_true(str(url).startswith("data:image/png;base64,"), f"expected PNG data URL, got: {url!r}")


def check_anthropic_messages_vision_payload_uses_base64_image_source() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "sample.png"
        image_path.write_bytes(SAMPLE_PNG)
        payload = build_anthropic_messages_vision_payload(
            model="test-model",
            prompt="识别图片",
            image_paths=[str(image_path)],
        )
    content = ((payload.get("messages") or [{}])[0] or {}).get("content") or []
    assert_true(isinstance(content, list) and len(content) == 2, f"unexpected content: {content}")
    image_part = content[1]
    source = image_part.get("source") if isinstance(image_part, dict) else {}
    assert_equal(str(image_part.get("type") or ""), "image", "anthropic payload should use image part")
    assert_equal(str(source.get("type") or ""), "base64", "anthropic image source should be base64")
    assert_equal(str(source.get("media_type") or ""), "image/png", "anthropic media type should be png")
    assert_true(bool(source.get("data")), "anthropic image data should not be empty")


def check_visual_bridge_turn_text_fallback_for_image_only() -> None:
    bridge = build_customer_image_brain_bridge(
        {
            "classification": {"is_vehicle": True, "vehicle_confidence": 0.91},
            "vision_summary": "白色轿车",
            "source_messages": [{"message_id": "msg-1"}],
        },
        {"applied": True, "normalized_vehicle_query": "比亚迪 秦PLUS", "preferred_candidate_ids": ["car-1"]},
        source_reason="image_only_turn",
    )
    assert_equal(resolve_visual_brain_turn_text("", bridge), "客户发来了一张车辆图片", "vehicle image should produce vehicle placeholder")
    assert_equal(resolve_visual_brain_turn_text("这款有吗", bridge), "这款有吗", "existing user text should win")


def check_augment_text_with_visual_query() -> None:
    bridge = {
        "present": True,
        "vision_summary": "白色轿车",
        "catalog_assist": {"normalized_vehicle_query": "比亚迪 秦PLUS DM-i"},
    }
    text = augment_text_with_visual_query("这款有吗", bridge)
    assert_true("这款有吗" in text and "比亚迪 秦PLUS DM-i" in text, f"visual query should be appended: {text}")


def check_normalize_customer_image_understanding_result_defaults() -> None:
    payload = normalize_customer_image_understanding_result(
        {
            "applied": True,
            "vision_summary": "这是一辆白色轿车",
            "classification": {"is_vehicle": True, "vehicle_confidence": 0.88},
            "bridge": {"normalized_vehicle_query": "比亚迪 秦PLUS"},
        },
        enabled=True,
        provider="test-provider",
        request_style="openai_chat_vision",
        model="test-model",
        source_messages=[{"message_id": "m1", "asset_id": "a1", "message_type": "image"}],
        local_visual_profile={"width": 100, "height": 100},
    )
    assert_true(payload["applied"] is True, f"payload should be applied: {payload}")
    assert_equal(payload["provider"], "test-provider", "provider should be preserved")
    assert_equal(payload["bridge"]["normalized_vehicle_query"], "比亚迪 秦PLUS", "normalized query should survive")


def check_normalize_customer_image_understanding_result_handles_provider_shape_drift() -> None:
    payload = normalize_customer_image_understanding_result(
        {
            "applied": True,
            "vision_summary": "浅蓝色新能源SUV",
            "image_ocr_text": "绿牌车牌被遮挡",
            "classification": {"is_vehicle": True, "vehicle_confidence": 0.93},
            "entities": {
                "brand_candidates": "蔚来",
                "series_candidates": ["ES6"],
                "body_type": ["SUV"],
                "color": ["浅蓝色", "黑色车顶"],
            },
            "bridge": {"normalized_vehicle_query": "蔚来 ES6"},
            "catalog_alignment": {
                "selected_product_id": "chejin_hengyi_2019_es6",
                "selected_product_name": "2019款蔚来ES6 420KM 运动版",
                "alignment_confidence": 0.96,
            },
            "audit": {"catalog_identity_candidate_count": 1},
        },
        enabled=True,
        provider="test-provider",
        request_style="openai_chat_vision",
        model="test-model",
    )
    assert_equal(payload["image_ocr_text"], ["绿牌车牌被遮挡"], "string OCR should stay as one OCR item")
    assert_equal(payload["entities"]["brand_candidates"], ["蔚来"], "string brand should become one candidate")
    assert_equal(payload["entities"]["body_type"], "SUV", "list body_type should become a compact scalar")
    assert_equal(payload["entities"]["color"], "浅蓝色 黑色车顶", "list color should become a compact scalar")
    assert_equal(payload["catalog_alignment"]["selected_product_id"], "chejin_hengyi_2019_es6", "catalog alignment should survive")
    assert_equal(payload["audit"]["catalog_identity_candidate_count"], 1, "catalog candidate count should survive audit")


def check_saved_image_path_is_preferred_for_provider_input() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        crop_path = Path(tmp_dir) / "crop.png"
        saved_path.write_bytes(SAMPLE_PNG)
        crop_path.write_bytes(SAMPLE_PNG)
        captured: dict[str, Any] = {}
        original_provider = module.run_customer_image_understanding_provider
        try:
            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                captured.update(kwargs)
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "白色轿车",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.9},
                        "entities": {},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": "特斯拉 Model 3"},
                    },
                }

            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "openai_chat_vision",
                    }
                },
                customer_text="这款有吗",
                image_assets=[
                    {
                        "asset_id": "asset-1",
                        "message_id": "msg-1",
                        "saved_image_path": str(saved_path),
                        "bubble_crop_path": str(crop_path),
                    }
                ],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
    assert_true(result.get("applied") is True, f"understanding should apply: {result}")
    assert_equal(captured.get("image_paths"), [str(saved_path)], "saved_image_path should be preferred over crop path")


def check_image_understanding_prompt_includes_catalog_identity_candidates() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        saved_path.write_bytes(SAMPLE_PNG)
        captured: dict[str, Any] = {}
        original_provider = module.run_customer_image_understanding_provider
        original_catalog = module.catalog_identity_candidates_for_visual_prompt
        try:
            def fake_catalog() -> list[dict[str, Any]]:
                return [
                    {
                        "id": "chejin_hengyi_2019_es6",
                        "name": "2019款蔚来ES6 420KM 运动版",
                        "aliases": ["蔚来ES6", "ES6"],
                        "category": "二手车 新能源SUV",
                    }
                ]

            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                captured.update(kwargs)
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "浅蓝色蔚来ES6",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.99},
                        "entities": {"brand_candidates": ["蔚来"], "series_candidates": ["ES6"]},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": ""},
                        "catalog_alignment": {
                            "selected_product_id": "chejin_hengyi_2019_es6",
                            "selected_product_name": "2019款蔚来ES6 420KM 运动版",
                            "alignment_confidence": 0.96,
                        },
                    },
                }

            module.catalog_identity_candidates_for_visual_prompt = fake_catalog
            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "anthropic_messages_vision",
                    }
                },
                customer_text="这款车你们有吗？",
                image_assets=[{"asset_id": "asset-1", "message_id": "msg-1", "saved_image_path": str(saved_path)}],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
            module.catalog_identity_candidates_for_visual_prompt = original_catalog
    prompt = str(captured.get("prompt") or "")
    assert_true("catalog_candidates=" in prompt, f"prompt should include catalog candidate slate: {prompt}")
    assert_true("chejin_hengyi_2019_es6" in prompt and "蔚来ES6" in prompt, f"prompt should include product identity hints: {prompt}")
    assert_equal(result.get("bridge", {}).get("normalized_vehicle_query"), "蔚来 ES6", "alignment should stabilize visual query")
    assert_equal(result.get("catalog_alignment", {}).get("selected_product_id"), "chejin_hengyi_2019_es6", "alignment should be preserved")
    assert_equal(result.get("audit", {}).get("catalog_identity_candidate_count"), 1, "candidate count should be audited")


def check_image_understanding_dedupes_paths_and_uses_larger_budget() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        saved_path.write_bytes(SAMPLE_PNG)
        captured: dict[str, Any] = {}
        original_provider = module.run_customer_image_understanding_provider
        try:
            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                captured.update(kwargs)
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "浅蓝色新能源SUV",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.98},
                        "entities": {"brand_candidates": ["蔚来"], "series_candidates": ["ES6"]},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": "蔚来 ES6"},
                    },
                }

            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "anthropic_messages_vision",
                    }
                },
                customer_text="这款车你们有吗？",
                image_assets=[
                    {"asset_id": "asset-1", "message_id": "msg-1", "saved_image_path": str(saved_path)},
                    {"asset_id": "asset-1", "message_id": "proxy-1", "saved_image_path": str(saved_path)},
                ],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
    assert_true(result.get("applied") is True, f"understanding should apply: {result}")
    assert_equal(captured.get("image_paths"), [str(saved_path)], "duplicate visual/proxy paths should be sent once")
    assert_true(int(captured.get("max_tokens") or 0) >= 1800, f"image understanding should use larger output budget: {captured}")


def check_image_understanding_retries_after_non_json_response() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        saved_path.write_bytes(SAMPLE_PNG)
        calls: list[dict[str, Any]] = []
        original_provider = module.run_customer_image_understanding_provider
        try:
            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                calls.append(dict(kwargs))
                if len(calls) == 1:
                    return {
                        "ok": False,
                        "error": "customer_image_understanding_response_not_json_object",
                        "response_text": "",
                        "response_diagnostics": {"content_types": ["thinking"], "thinking_chars": 800},
                    }
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "浅蓝色蔚来ES6",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.99},
                        "entities": {"brand_candidates": ["蔚来"], "series_candidates": ["ES6"]},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": "蔚来 ES6", "catalog_lookup_mode": "strict_match"},
                    },
                }

            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "anthropic_messages_vision",
                        "max_tokens": 1800,
                    }
                },
                customer_text="我发的图片，是啥型号的车",
                image_assets=[{"asset_id": "asset-1", "message_id": "msg-1", "saved_image_path": str(saved_path)}],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
    assert_equal(len(calls), 2, f"non-json response should trigger one retry: {calls}")
    assert_true(result.get("applied") is True, f"retry result should apply: {result}")
    assert_equal(result.get("bridge", {}).get("normalized_vehicle_query"), "蔚来 ES6", "retry JSON should become brain bridge query")
    assert_true(result.get("audit", {}).get("retry_after_non_json") is True, f"retry audit should be preserved: {result}")


def check_image_understanding_archives_prompt_and_result() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        saved_path.write_bytes(SAMPLE_PNG)
        events: list[dict[str, Any]] = []
        original_provider = module.run_customer_image_understanding_provider
        original_archive = module.archive_prompt_event
        try:
            def fake_archive(kind: str, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
                events.append({"kind": kind, "payload": payload, "kwargs": kwargs})
                return {"ok": True, "archived": True}

            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "white sedan",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.95},
                        "entities": {"brand_candidates": ["Tesla"], "series_candidates": ["Model 3"]},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": "Tesla Model 3"},
                    },
                }

            module.archive_prompt_event = fake_archive
            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "anthropic_messages_vision",
                    }
                },
                customer_text="do we have this car",
                image_assets=[{"asset_id": "asset-1", "message_id": "msg-1", "saved_image_path": str(saved_path)}],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
            module.archive_prompt_event = original_archive
    kinds = [str(item.get("kind") or "") for item in events]
    assert_true(result.get("applied") is True, f"understanding should apply: {result}")
    assert_true("customer_image_understanding_prompt" in kinds, f"prompt archive event missing: {events}")
    assert_true("customer_image_understanding_result" in kinds, f"result archive event missing: {events}")
    prompt_payload = next(item["payload"] for item in events if item.get("kind") == "customer_image_understanding_prompt")
    assert_true(bool(prompt_payload.get("prompt")), f"prompt text should be archived: {prompt_payload}")
    assert_true(prompt_payload.get("image_paths") == [str(saved_path)], f"image paths should be archived: {prompt_payload}")
    assert_true("api_key" not in prompt_payload, f"archive payload should not include raw api key: {prompt_payload}")


def check_image_understanding_archive_failure_does_not_break_flow() -> None:
    from apps.wechat_ai_customer_service.workflows import customer_image_understanding as module

    with tempfile.TemporaryDirectory() as tmp_dir:
        saved_path = Path(tmp_dir) / "saved.png"
        saved_path.write_bytes(SAMPLE_PNG)
        original_provider = module.run_customer_image_understanding_provider
        original_archive = module.archive_prompt_event
        try:
            def failing_archive(*args: Any, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("archive unavailable")

            def fake_provider(**kwargs: Any) -> dict[str, Any]:
                return {
                    "ok": True,
                    "parsed": {
                        "vision_summary": "white sedan",
                        "classification": {"is_vehicle": True, "vehicle_confidence": 0.95},
                        "entities": {"brand_candidates": ["Tesla"], "series_candidates": ["Model 3"]},
                        "intent_hints": {"wants_catalog_match": True},
                        "bridge": {"normalized_vehicle_query": "Tesla Model 3"},
                    },
                }

            module.archive_prompt_event = failing_archive
            module.run_customer_image_understanding_provider = fake_provider
            result = module.maybe_run_customer_image_understanding(
                config={
                    "customer_image_understanding": {
                        "enabled": True,
                        "api_key": "test-key",
                        "base_url": "https://example.invalid/v1",
                        "model": "test-vision",
                        "request_style": "anthropic_messages_vision",
                    }
                },
                customer_text="do we have this car",
                image_assets=[{"asset_id": "asset-1", "message_id": "msg-1", "saved_image_path": str(saved_path)}],
                source_reason="direct_image_message",
            )
        finally:
            module.run_customer_image_understanding_provider = original_provider
            module.archive_prompt_event = original_archive
    assert_true(result.get("applied") is True, f"archive failures must not block image understanding: {result}")
    assert_equal(result.get("bridge", {}).get("normalized_vehicle_query"), "Tesla Model 3", "provider result should still flow through")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
