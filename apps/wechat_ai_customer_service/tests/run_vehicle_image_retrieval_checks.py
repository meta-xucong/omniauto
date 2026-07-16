"""Focused contract checks for the portable vehicle-image retrieval module."""

from __future__ import annotations

import copy
import io
import tempfile
import threading
import time
import sys
from pathlib import Path
from typing import Any

from PIL import Image


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.api import product_console as product_console_api
from apps.wechat_ai_customer_service.optional_plugins.registry import (
    register_optional_capability,
    reset_optional_capabilities_for_tests,
)
from apps.wechat_ai_customer_service.vehicle_image_retrieval_integration import (
    index_product_vehicle_images,
    match_customer_image_to_product_master,
    merge_vehicle_image_match_into_catalog_assist,
)
from apps.wechat_ai_customer_service.vehicle_image_retrieval_jobs import VehicleImageIndexTaskQueue
from apps.wechat_ai_customer_service.workflows.customer_image_brain_bridge import build_customer_image_brain_bridge
from apps.wechat_ai_customer_service.product_master import ProductMasterStore
from packages.vehicle_image_retrieval import (
    apply_vehicle_image_index,
    build_customer_query_descriptor,
    current_vehicle_image_index_state,
    match_vehicle_image_records,
    picture_ref,
)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def jpeg_bytes(color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (64, 40), color=color)
    stream = io.BytesIO()
    image.save(stream, format="JPEG", quality=90)
    return stream.getvalue()


def base_record(product_id: str = "a4l-001") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "category_id": "products",
        "id": product_id,
        "status": "active",
        "source": {
            "type": "manual",
            "provider": "manual",
            "marker": {
                "ingest_channel": "manual_input",
                "original_source_type": "manual",
                "recorded_at": "2026-07-16T00:00:00+00:00",
            },
            "binding": {"state": "unbound"},
        },
        "source_payloads": {
            "vehicle_detail": {
                "api": "manual.dafengche_shaped_vehicle_detail",
                "pulled_at": "2026-07-16T00:00:00+00:00",
                "content_hash": "sha256:detail",
                "payload": {"baseCarInfo": {"name": "2018款奥迪 A4L"}},
            },
            "vehicle_pictures": {
                "api": "manual.dafengche_shaped_vehicle_pictures",
                "pulled_at": "2026-07-16T00:00:00+00:00",
                "content_hash": "sha256:pictures",
                "payload": [
                    {
                        "pictureId": "img_a4l_front",
                        "pictureNumber": 1,
                        "pictureUrl": "/api/product-console/products/a4l-001/images/img_a4l_front",
                        "source": "manual_upload",
                        "assetFile": "img_a4l_front.jpg",
                        "mimeType": "image/jpeg",
                    },
                    {
                        "pictureId": "img_a4l_rear",
                        "pictureNumber": 2,
                        "pictureUrl": "/api/product-console/products/a4l-001/images/img_a4l_rear",
                        "source": "manual_upload",
                        "assetFile": "img_a4l_rear.jpg",
                        "mimeType": "image/jpeg",
                    },
                ],
            },
        },
        "extensions": {},
        "runtime": {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
        "metadata": {"created_at": "2026-07-16T00:00:00+00:00", "updated_at": "2026-07-16T00:00:00+00:00"},
    }


def descriptor(summary: str = "白色奥迪 A4L 左前45度外观") -> dict[str, Any]:
    return {
        "summary": summary,
        "keywords": ["奥迪", "A4L", "白色", "三厢轿车", "左前45度"],
        "identity_terms": ["奥迪", "A4L"],
        "view": "left_front",
        "scene_terms": ["室外"],
        "ocr_text": [],
    }


def test_core_preserves_source_and_supports_multi_image() -> None:
    original = base_record()
    source_before = copy.deepcopy(original["source_payloads"])
    pictures = original["source_payloads"]["vehicle_pictures"]["payload"]
    indexed = apply_vehicle_image_index(
        original,
        [
            {"picture_ref": picture_ref(pictures[0]), "perceptual_hash": "0123456789abcdef", "descriptor": descriptor()},
            {"picture_ref": picture_ref(pictures[1]), "perceptual_hash": "fedcba9876543210", "descriptor": descriptor("白色奥迪 A4L 车尾")},
        ],
        indexed_at="2026-07-16T00:00:01+00:00",
    )
    assert_true(indexed["source_payloads"] == source_before, "index must not alter Dafengche-shaped source payload")
    state = current_vehicle_image_index_state(indexed)
    assert_true(state["current"] and state["indexed_image_count"] == 2, "all pictures must be indexed independently")


def test_core_requires_visual_similarity_for_auto_bind() -> None:
    record = base_record()
    pictures = record["source_payloads"]["vehicle_pictures"]["payload"]
    indexed = apply_vehicle_image_index(
        record,
        [
            {"picture_ref": picture_ref(pictures[0]), "perceptual_hash": "0123456789abcdef", "descriptor": descriptor()},
            {"picture_ref": picture_ref(pictures[1]), "perceptual_hash": "fedcba9876543210", "descriptor": descriptor("白色奥迪 A4L 车尾")},
        ],
    )
    query = build_customer_query_descriptor(
        {
            "vision_summary": "一辆白色奥迪 A4L 三厢轿车",
            "entities": {"brand_candidates": ["奥迪"], "series_candidates": ["A4L"], "model_clues": ["白色"]},
            "bridge": {"normalized_vehicle_query": "奥迪 A4L"},
        }
    )
    exact = match_vehicle_image_records([indexed], query, query_perceptual_hash="0123456789abcdef")
    assert_true(exact["matched"], "same visual fingerprint should bind the vehicle")
    semantic_only = match_vehicle_image_records([indexed], query, query_perceptual_hash="")
    assert_true(not semantic_only["matched"], "same model terms alone must not bind a specific inventory vehicle")


def test_stale_source_is_never_used() -> None:
    record = base_record()
    picture = record["source_payloads"]["vehicle_pictures"]["payload"][0]
    indexed = apply_vehicle_image_index(record, [{"picture_ref": picture_ref(picture), "perceptual_hash": "0123456789abcdef", "descriptor": descriptor()}])
    indexed["source_payloads"]["vehicle_pictures"]["payload"].append({"pictureId": "img_new", "pictureUrl": "https://example.invalid/new.jpg"})
    state = current_vehicle_image_index_state(indexed)
    assert_true(state["status"] == "stale" and not state["current"], "new source picture must invalidate the old index")
    query = build_customer_query_descriptor({"vision_summary": "白色奥迪 A4L", "entities": {"brand_candidates": ["奥迪"], "series_candidates": ["A4L"]}})
    result = match_vehicle_image_records([indexed], query, query_perceptual_hash="0123456789abcdef")
    assert_true(not result["matched"] and result["skipped_stale_record_count"] == 1, "stale index must be skipped")


class FakeVehicleImagePlugin:
    name = "fake_vehicle_image_retrieval"
    capability = "vehicle_image_retrieval"

    def available(self) -> bool:
        return True

    def should_run(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"run": True}

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        raw = bytes(context.get("_image_bytes") or b"")
        marker = "0123456789abcdef" if raw == b"front-image" else "fedcba9876543210"
        if context.get("operation") == "fingerprint":
            return {"ok": True, "perceptual_hash": marker}
        return {"ok": True, "perceptual_hash": marker, "descriptor": descriptor()}


def test_host_adapter_indexes_multi_image_and_enriches_existing_bridge() -> None:
    reset_optional_capabilities_for_tests()
    register_optional_capability("vehicle_image_retrieval", plugin=FakeVehicleImagePlugin())
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "product_master"
            store = ProductMasterStore(root=root, tenant_id="vehicle-image-test")
            record = base_record()
            assets = root / "assets" / record["id"]
            assets.mkdir(parents=True, exist_ok=True)
            (assets / "img_a4l_front.jpg").write_bytes(b"front-image")
            (assets / "img_a4l_rear.jpg").write_bytes(b"rear-image")
            assert_true(store.save_item(record)["ok"], "fixture V2 record must save")
            config = {"vehicle_image_retrieval": {"enabled": True, "match_threshold": 0.86, "minimum_visual_similarity": 0.82}}
            indexed = index_product_vehicle_images(record["id"], store=store, config=config)
            assert_true(indexed["ok"] and indexed["indexed_count"] == 2, "host adapter must index every manual image")
            match = match_customer_image_to_product_master(
                {"vision_summary": "白色奥迪 A4L", "entities": {"brand_candidates": ["奥迪"], "series_candidates": ["A4L"]}},
                {"image_bytes": b"front-image", "released": False},
                config,
                store=store,
            )
            assert_true(match["matched"] and match["candidates"][0]["product_id"] == record["id"], "current customer image should resolve local V2 product")
            merged = merge_vehicle_image_match_into_catalog_assist({"preferred_candidate_ids": [], "catalog_candidates_preview": [], "conversation_context_patch": {}}, match)
            assert_true(merged["exact_candidate_id"] == record["id"], "high-confidence match must enter existing catalog evidence seam")
            bridge = build_customer_image_brain_bridge({}, merged, vehicle_image_retrieval=match)
            assert_true(bridge["vehicle_image_retrieval"]["matched"], "Brain bridge must carry evidence, not customer wording")
    finally:
        reset_optional_capabilities_for_tests()


def test_portable_core_has_no_host_or_image_dependencies() -> None:
    source = (Path(__file__).resolve().parents[3] / "packages" / "vehicle_image_retrieval" / "service.py").read_text(encoding="utf-8")
    forbidden = ("apps.wechat_ai_customer_service", "PIL", "urllib", "Path(", "open(")
    assert_true(not any(item in source for item in forbidden), "portable core may not depend on host, image IO, or network")


def test_background_index_queue_coalesces_without_blocking_callers() -> None:
    started = threading.Event()
    release_first_run = threading.Event()
    calls: list[tuple[str, str]] = []

    def runner(product_id: str, tenant_id: str) -> dict[str, Any]:
        calls.append((product_id, tenant_id))
        if len(calls) == 1:
            started.set()
            assert_true(release_first_run.wait(timeout=2), "fixture must release the first queued job")
        return {"ok": True, "reason": "indexed", "indexed_count": 2, "source_count": 2, "state": {"status": "ready", "current": True}}

    queue = VehicleImageIndexTaskQueue(runner=runner)
    try:
        first = queue.enqueue("a4l-001", tenant_id="queue-check", cause="manual_upload")
        assert_true(first["accepted"] and first["state"] == "queued", "enqueue must return before the index worker completes")
        assert_true(started.wait(timeout=2), "background worker should start asynchronously")
        second = queue.enqueue("a4l-001", tenant_id="queue-check", cause="dafengche_sync")
        assert_true(second["accepted"] and second["reason"] == "vehicle_image_index_coalesced", "same vehicle must coalesce while already running")
        release_first_run.set()
        deadline = time.monotonic() + 3
        status = queue.status("a4l-001", tenant_id="queue-check")
        while status["state"] != "completed" and time.monotonic() < deadline:
            time.sleep(0.02)
            status = queue.status("a4l-001", tenant_id="queue-check")
        assert_true(status["state"] == "completed", "newer request must receive a final completed index run")
        assert_true(len(calls) == 2, "coalesced source change requires exactly one follow-up refresh")
        assert_true(set(status["causes"]) == {"manual_upload", "dafengche_sync"}, "job audit must retain both trigger causes")
    finally:
        release_first_run.set()
        queue.shutdown()


def test_optional_plugin_isolated_and_internal_api_is_exposed() -> None:
    plugin_root = Path(__file__).resolve().parents[1] / "optional_plugins" / "vehicle_image_retrieval"
    source = "\n".join(path.read_text(encoding="utf-8") for path in plugin_root.glob("*.py"))
    forbidden = ("optional_plugins.vision", "customer_image_understanding", "optional_plugins.voice")
    assert_true(not any(item in source for item in forbidden), "retrieval plugin must not import voice or chat-vision implementation")
    routes = {(str(getattr(route, "path", "")), frozenset(getattr(route, "methods", set()))) for route in product_console_api.router.routes}
    assert_true(("/api/product-console/products/{product_id}/vehicle-image-retrieval", frozenset({"GET"})) in routes, "status API must remain internal and explicit")
    assert_true(("/api/product-console/products/{product_id}/vehicle-image-retrieval/index", frozenset({"POST"})) in routes, "index API must remain internal and explicit")


def main() -> None:
    checks = [
        test_core_preserves_source_and_supports_multi_image,
        test_core_requires_visual_similarity_for_auto_bind,
        test_stale_source_is_never_used,
        test_host_adapter_indexes_multi_image_and_enriches_existing_bridge,
        test_portable_core_has_no_host_or_image_dependencies,
        test_background_index_queue_coalesces_without_blocking_callers,
        test_optional_plugin_isolated_and_internal_api_is_exposed,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print(f"vehicle image retrieval checks passed: {len(checks)}")


if __name__ == "__main__":
    main()
