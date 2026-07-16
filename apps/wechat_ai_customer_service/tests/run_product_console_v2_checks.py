"""Focused contract checks for the V2 Dafengche product-console adapter."""

from __future__ import annotations

import base64
import copy
import os
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.services.product_console_service import ProductConsoleService
from apps.wechat_ai_customer_service.admin_backend.services import product_console_service as product_console_service_module
from apps.wechat_ai_customer_service.admin_backend.api import product_console as product_console_api
from apps.wechat_ai_customer_service.product_master import ProductMasterStore
from apps.wechat_ai_customer_service.scripts.enrich_chejin_v2_from_legacy_snapshot import plan_legacy_snapshot_enrichment
from apps.wechat_ai_customer_service.scripts.fill_chejin_v2_vehicle_test_fields import plan_vehicle_test_field_fill
from packages.dafengche_product_master import apply_admin_vehicle_update, build_admin_vehicle_view


def main() -> int:
    checks = [
        check_v2_admin_view_uses_authoritative_vehicle_fields,
        check_manual_update_preserves_v2_and_records_provenance,
        check_dafengche_source_fields_are_read_only,
        check_generic_manual_input_converts_to_v2_at_storage_boundary,
        check_legacy_snapshot_enrichment_is_evidenced_and_idempotent,
        check_explicit_test_field_fill_is_missing_only_and_reversible,
        check_manual_vehicle_image_upload_uses_v2_picture_payload,
        check_product_console_v2_write_and_compatibility_output,
        check_v2_admin_view_api_contract,
        check_v2_vehicle_image_api_contract,
        check_frontend_uses_v2_console_contract,
    ]
    failures: list[str] = []
    for check in checks:
        try:
            check()
            print(f"PASS {check.__name__}")
        except Exception as exc:  # pragma: no cover - script test runner
            failures.append(f"{check.__name__}: {exc!r}")
            print(f"FAIL {check.__name__}: {exc!r}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"PASS {len(checks)}/{len(checks)} product-console V2 checks")
    return 0


def v2_vehicle(*, source_type: str = "manual") -> dict:
    source = {
        "type": source_type,
        "provider": "dafengche" if source_type == "dafengche" else "manual",
        "marker": {
            "ingest_channel": "dafengche_api" if source_type == "dafengche" else "manual_input",
            "original_source_type": source_type,
            "recorded_at": "2026-07-13T00:00:00+00:00",
            "last_observed_at": "2026-07-13T01:00:00+00:00",
        },
        "binding": {"state": "bound", "shopCode": "SHOP-01", "carId": "CAR-01"} if source_type == "dafengche" else {"state": "unbound"},
    }
    return {
        "schema_version": 2,
        "category_id": "products",
        "id": f"{source_type}_camry_001",
        "status": "active",
        "source": source,
        "source_payloads": {
            "vehicle_detail": {
                "api": "fixture.vehicle.detail",
                "pulled_at": "2026-07-13T01:00:00+00:00",
                "content_hash": "sha256:before",
                "payload": {
                    "operationPhase": "SALE",
                    "baseCarInfo": {
                        "name": "凯美瑞 2.0G",
                        "brandName": "丰田",
                        "seriesName": "凯美瑞",
                        "modelName": "2.0G",
                        "firstLicensePlateDate": "2020-06",
                        "mileage": "4.2万公里",
                        "vinNumber": "DO-NOT-EXPOSE-TO-BRAIN",
                    },
                    "carModelParam": {"gearbox": "自动", "displacement": "2.0L"},
                    "carLicenseInfo": {"licenseStatus": "手续正常"},
                    "carPriceInfo": {"salePrice": 13.98, "purchasePrice": 9.8},
                },
            },
            "vehicle_pictures": {"api": "fixture.vehicle.pictures", "pulled_at": "2026-07-13T01:00:00+00:00", "content_hash": "sha256:pictures", "payload": [{"bigPictureUrl": "https://example.test/camry.jpg"}]},
        },
        "extensions": {
            "wechat_customer_service": {
                "customer_visible_annotations": {"category": "二手车/轿车", "aliases": ["凯美瑞", "丰田凯美瑞"], "specs": "一手车，保养记录完整"},
                "manual_annotations": {"sku": "CAMRY-001", "unit": "台", "inventory": 1},
                "manual_overrides": {},
            },
            "manual": {"field_provenance": {}},
        },
        "runtime": {"allow_auto_reply": True},
        "metadata": {"created_at": "2026-07-13T00:00:00+00:00", "updated_at": "2026-07-13T01:00:00+00:00"},
    }


def check_v2_admin_view_uses_authoritative_vehicle_fields() -> None:
    record = v2_vehicle()
    view = build_admin_vehicle_view(record, include_raw=True)
    assert_equal(view["record_kind"], "vehicle_v2", "must identify V2 vehicle")
    assert_equal(view["summary"]["name"], "凯美瑞 2.0G", "name must come from V2 payload")
    assert_equal(view["summary"]["price"], 13.98, "price must come from V2 payload")
    assert_equal(view["source"]["sync"]["state"], "manual", "manual source must be labelled")
    assert_equal(view["vehicle"]["carLicenseInfo"]["licenseStatus"], "手续正常", "license status must retain its Dafengche field")
    assert_true(view["vehicle"]["photos"] == ["https://example.test/camry.jpg"], "authorized pictures should project")
    card_fields = view["vehicle"]["card_fields"]
    assert_equal(len(card_fields), 6, "fixed card field set must include blanks instead of hiding them")
    assert_equal(next(field for field in card_fields if field["path"] == "baseCarInfo.firstLicensePlateDate")["value"], "2020-06", "card field must retain source value")
    price_group = next(group for group in view["dafengche_field_groups"] if group["id"] == "price_information")
    assert_equal(next(field for field in price_group["fields"] if field["path"] == "carPriceInfo.purchasePrice")["value"], 9.8, "admin detail must retain Dafengche internal price fields")
    assert_true(view["raw_source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["vinNumber"], "admin raw audit must retain payload")


def check_manual_update_preserves_v2_and_records_provenance() -> None:
    updated = apply_admin_vehicle_update(
        v2_vehicle(),
        {
            "vehicle_detail_patch": {"baseCarInfo": {"name": "凯美瑞 2.5G"}, "carPriceInfo": {"salePrice": 14.28}},
            "annotations": {"shipping_policy": "到店看车请预约"},
            "manual_annotations": {"sku": "CAMRY-001-R"},
        },
        observed_at="2026-07-13T02:00:00+00:00",
    )
    payload = updated["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(payload["baseCarInfo"]["name"], "凯美瑞 2.5G", "manual name must update canonical payload")
    assert_equal(payload["carPriceInfo"]["salePrice"], 14.28, "manual price must update canonical payload")
    assert_equal(payload["baseCarInfo"]["vinNumber"], "DO-NOT-EXPOSE-TO-BRAIN", "unknown/restricted fields must survive merge")
    assert_true("data" not in updated, "V2 edit must not create retired generic data")
    provenance = updated["extensions"]["manual"]["field_provenance"]
    assert_equal(provenance["source_payloads.vehicle_detail.payload.carPriceInfo.salePrice"]["source"], "manual_admin_edit", "manual edit provenance")
    assert_equal(updated["extensions"]["wechat_customer_service"]["customer_visible_annotations"]["shipping_policy"], "到店看车请预约", "annotation must persist separately")


def check_dafengche_source_fields_are_read_only() -> None:
    record = v2_vehicle(source_type="dafengche")
    try:
        apply_admin_vehicle_update(record, {"vehicle_detail_patch": {"carPriceInfo": {"salePrice": 1}}})
    except ValueError as exc:
        assert_true("read-only" in str(exc), "must explain authoritative source restriction")
    else:
        raise AssertionError("Dafengche source patch must be rejected")
    updated = apply_admin_vehicle_update(record, {"annotations": {"shipping_policy": "请先预约"}})
    assert_equal(updated["extensions"]["wechat_customer_service"]["customer_visible_annotations"]["shipping_policy"], "请先预约", "local annotation remains allowed")


def check_generic_manual_input_converts_to_v2_at_storage_boundary() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = ProductMasterStore(tenant_id="product_console_v2_check", root=Path(directory) / "product_master")
        saved = store.save_item(
            {
                "schema_version": 1,
                "category_id": "products",
                "id": "manual_generator_camry_001",
                "status": "active",
                "source": {"type": "ai_generator", "session_id": "gen_test"},
                "data": {"name": "手工录入凯美瑞", "price": 12.98, "sku": "MANUAL-001", "inventory": 1},
                "runtime": {"allow_auto_reply": True},
            }
        )
    record = saved.get("item") or {}
    assert_equal(record.get("schema_version"), 2, "generic input must save as V2")
    assert_equal((record.get("source") or {}).get("type"), "manual", "generic input must become a manual vehicle")
    assert_true("data" not in record, "generic input must not persist top-level data")
    detail = (((record.get("source_payloads") or {}).get("vehicle_detail") or {}).get("payload") or {})
    assert_equal((detail.get("baseCarInfo") or {}).get("name"), "手工录入凯美瑞", "name must map to Dafengche-shaped detail")
    assert_equal((detail.get("carPriceInfo") or {}).get("salePrice"), 12.98, "price must map to Dafengche-shaped detail")
    with tempfile.TemporaryDirectory() as directory:
        store = ProductMasterStore(tenant_id="product_console_v2_shadow_check", root=Path(directory) / "product_master")
        shadowed = v2_vehicle()
        shadowed["data"] = {"name": "retired shadow must not persist"}
        saved = store.save_item(shadowed)
    assert_true("data" not in (saved.get("item") or {}), "V2 storage boundary must remove a retired generic data shadow")


def check_legacy_snapshot_enrichment_is_evidenced_and_idempotent() -> None:
    record = v2_vehicle()
    record["source"]["marker"]["ingest_channel"] = "legacy_v1_migration"
    payload = record["source_payloads"]["vehicle_detail"]["payload"]
    payload["baseCarInfo"] = {"name": "2020款本田凌派180TURBO CVT舒适版"}
    payload["carModelParam"] = {}
    record["extensions"]["compatibility"] = {
        "legacy_v1_record": {
            "schema_version": 1,
            "data": {
                "name": "2020款本田凌派180TURBO CVT舒适版",
                "specs": "2020年9月上牌，表显6.8万公里，1.0T自动挡，白色车漆。",
            },
        }
    }
    record["data"] = {}
    planned = plan_legacy_snapshot_enrichment(
        record,
        batch_id="legacy_enrichment_test",
        enriched_at="2026-07-13T03:00:00+00:00",
    )
    assert_equal(planned["state"], "planned", "direct legacy matches must plan a V2 enrichment")
    enriched = planned["record"]
    assert_true("data" not in enriched, "historical cleanup must remove an empty retired V1 data shell")
    detail = enriched["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(detail["baseCarInfo"]["firstLicensePlateDate"], "2020-09", "month-preserving registration date must map")
    assert_equal(detail["baseCarInfo"]["mileage"], 6.8, "Dafengche mileage must retain numeric 万公里 value")
    assert_equal(detail["carModelParam"]["displacement"], "1.0T", "explicit displacement must map")
    assert_equal(detail["carModelParam"]["gearbox"], "CVT", "title's explicit gearbox subtype must win over generic automatic wording")
    assert_equal(detail["baseCarInfo"]["exteriorColor"], "白色", "explicit color phrase must map")
    provenance = enriched["extensions"]["manual"]["field_provenance"]
    assert_equal(
        provenance["source_payloads.vehicle_detail.payload.baseCarInfo.mileage"]["source"],
        "legacy_v1_snapshot_enrichment",
        "every enrichment field must retain its historical source",
    )
    assert_equal(
        provenance["source_payloads.vehicle_detail.payload.carModelParam.gearbox"]["original_path"],
        "data.name",
        "higher-precision gearbox subtype must identify its source",
    )
    rerun = plan_legacy_snapshot_enrichment(
        enriched,
        batch_id="legacy_enrichment_test",
        enriched_at="2026-07-13T04:00:00+00:00",
    )
    assert_equal(rerun["state"], "unchanged", "completed enrichment must be idempotent")


def check_explicit_test_field_fill_is_missing_only_and_reversible() -> None:
    record = v2_vehicle()
    payload = record["source_payloads"]["vehicle_detail"]["payload"]
    payload["baseCarInfo"].pop("brandName", None)
    payload["baseCarInfo"].pop("seriesName", None)
    payload["carModelParam"].pop("gearBox", None)
    original_name = payload["baseCarInfo"]["name"]
    planned = plan_vehicle_test_field_fill(
        record,
        ordinal=3,
        batch_id="test_field_fill_contract",
        observed_at="2026-07-13T05:00:00+00:00",
        remove=False,
    )
    assert_equal(planned["state"], "planned", "missing manual V2 fields must accept explicit test fill")
    filled = planned["record"]
    detail = filled["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(detail["baseCarInfo"]["brandName"], "测试品牌-03", "test field value must remain obvious")
    assert_equal(detail["baseCarInfo"]["name"], original_name, "test fill must never overwrite an existing V2 value")
    provenance = filled["extensions"]["manual"]["field_provenance"]
    assert_equal(provenance["source_payloads.vehicle_detail.payload.baseCarInfo.brandName"]["source"], "test_fixture_fill", "test data must retain a distinct source marker")
    removed = plan_vehicle_test_field_fill(
        filled,
        ordinal=3,
        batch_id="test_field_fill_contract",
        observed_at="2026-07-13T06:00:00+00:00",
        remove=True,
    )
    assert_equal(removed["state"], "planned", "test fill must be removable without touching real fields")
    restored = removed["record"]["source_payloads"]["vehicle_detail"]["payload"]
    assert_true("brandName" not in restored["baseCarInfo"], "remove must delete only the seeded field")
    assert_equal(restored["baseCarInfo"]["name"], original_name, "remove must retain original V2 values")


def check_manual_vehicle_image_upload_uses_v2_picture_payload() -> None:
    record_holder = {"item": v2_vehicle()}
    with tempfile.TemporaryDirectory() as directory:
        service = ProductConsoleService()
        service.store.product_master = ProductMasterStore(tenant_id="product_console_image_check", root=Path(directory) / "product_master")  # type: ignore[assignment]
        service.get_product_item = lambda product_id, include_archived=False: copy.deepcopy(record_holder["item"])  # type: ignore[assignment]

        def save(updated: dict, *, operation: str) -> dict:
            assert_true(operation in {"upload_vehicle_image", "delete_vehicle_image"}, "image write must use an explicit V2 operation")
            record_holder["item"] = copy.deepcopy(updated)
            return {"ok": True, "item": copy.deepcopy(updated), "operation": operation}

        service.save_v2_product_item = save  # type: ignore[assignment]
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAFAAH/e+m+7wAAAABJRU5ErkJggg==")
        queued: list[dict] = []
        original_enqueue = product_console_service_module.enqueue_vehicle_image_index
        product_console_service_module.enqueue_vehicle_image_index = lambda product_id, *, tenant_id, cause: queued.append(  # type: ignore[assignment]
            {"product_id": product_id, "tenant_id": tenant_id, "cause": cause}
        ) or {"accepted": True, "state": "queued", "reason": "fixture"}
        try:
            result = service.upload_vehicle_image(
                "manual_camry_001",
                filename="测试车辆.png",
                content=png,
                content_type="image/png",
            )
        finally:
            product_console_service_module.enqueue_vehicle_image_index = original_enqueue  # type: ignore[assignment]
        assert_equal(result["image"]["mime_type"], "image/png", "image MIME must come from binary signature")
        assert_equal(result["vehicle_image_retrieval_job"]["state"], "queued", "successful upload must request a background image index")
        assert_equal(queued, [{"product_id": "manual_camry_001", "tenant_id": "product_console_image_check", "cause": "manual_upload"}], "upload must enqueue the owning tenant only")
        pictures = record_holder["item"]["source_payloads"]["vehicle_pictures"]["payload"]
        assert_equal(len(pictures), 2, "manual upload must append to the original V2 picture payload")
        uploaded = pictures[-1]
        assert_true(str(uploaded["pictureUrl"]).startswith("/api/product-console/products/manual_camry_001/images/img_"), "manual image must use the authenticated product image route")
        view = build_admin_vehicle_view(record_holder["item"])
        assert_true(uploaded["pictureUrl"] in view["vehicle"]["photos"], "admin V2 view must project authenticated local images")
        path, mime_type = service.vehicle_image_file("manual_camry_001", uploaded["pictureId"])
        assert_true(path.is_file(), "uploaded image file must remain under the product-master asset root")
        assert_equal(mime_type, "image/png", "read route must retain MIME type")
        provenance = record_holder["item"]["extensions"]["manual"]["field_provenance"]
        assert_equal(provenance["source_payloads.vehicle_pictures.payload"]["source"], "manual_admin_image_upload", "image writes need V2 provenance")

        deleted_jobs: list[dict] = []
        original_enqueue = product_console_service_module.enqueue_vehicle_image_index
        product_console_service_module.enqueue_vehicle_image_index = lambda product_id, *, tenant_id, cause: deleted_jobs.append(  # type: ignore[assignment]
            {"product_id": product_id, "tenant_id": tenant_id, "cause": cause}
        ) or {"accepted": True, "state": "queued", "reason": "fixture"}
        try:
            deleted = service.delete_vehicle_image("manual_camry_001", uploaded["pictureId"])
        finally:
            product_console_service_module.enqueue_vehicle_image_index = original_enqueue  # type: ignore[assignment]
        assert_equal(deleted["operation"], "delete_vehicle_image", "image deletion must keep a distinct V2 operation")
        assert_equal(deleted["deleted_image_id"], uploaded["pictureId"], "delete response must identify the removed local image")
        assert_equal(deleted_jobs, [{"product_id": "manual_camry_001", "tenant_id": "product_console_image_check", "cause": "manual_delete"}], "delete must refresh the owning vehicle image index")
        assert_equal(len(record_holder["item"]["source_payloads"]["vehicle_pictures"]["payload"]), 1, "delete must remove only the selected V2 picture payload entry")
        assert_true(not path.exists(), "deleted local image binary must not remain addressable")

        synced = v2_vehicle(source_type="dafengche")
        service.get_product_item = lambda product_id, include_archived=False: copy.deepcopy(synced)  # type: ignore[assignment]
        try:
            service.upload_vehicle_image("dafengche_camry_001", filename="forbidden.png", content=png, content_type="image/png")
        except ValueError as exc:
            assert_true("read-only" in str(exc), "synchronized image source must remain read-only")
        else:
            raise AssertionError("synchronized vehicle image upload must be rejected")


def check_product_console_v2_write_and_compatibility_output() -> None:
    record = v2_vehicle()
    saved: list[dict] = []
    service = ProductConsoleService()
    service.store.list_items = lambda category_id, include_archived=False: [copy.deepcopy(record)] if category_id == "products" else []  # type: ignore[assignment]
    service.store.save_item = lambda category_id, item: saved.append(copy.deepcopy(item)) or {"ok": True, "item": copy.deepcopy(item)}  # type: ignore[assignment]
    service.compiler.compile_to_disk = lambda: None  # type: ignore[assignment]
    catalog = service.catalog(include_archived=True)
    displayed = catalog["items"][0]
    assert_equal(displayed["display"]["name"], "凯美瑞 2.0G", "legacy display must receive V2-derived value")
    assert_equal(displayed["data"]["price"], 13.98, "legacy output data must be a derived facade")
    assert_equal(catalog["vehicle_counts"]["manual"], 1, "V2 vehicle metrics must be additive")
    assert_true("raw_source_payloads" not in displayed["admin_view"], "catalog must not expose raw admin payloads")
    detail = service.detail(record["id"])
    assert_true("raw_source_payloads" in detail["item"]["admin_view"], "detail must retain raw payloads for authenticated audit")
    result = service.update_admin_view(record["id"], {"vehicle_detail_patch": {"baseCarInfo": {"name": "凯美瑞 2.5G"}}})
    assert_equal(result["operation"], "update_admin_view", "must use V2 operation")
    assert_true(saved and "data" not in saved[-1], "V2 console save must not persist generic data")
    assert_equal(saved[-1]["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["name"], "凯美瑞 2.5G", "V2 console save must update canonical field")


def check_v2_admin_view_api_contract() -> None:
    class FakeProductConsoleService:
        def update_admin_view(self, product_id: str, patch: dict) -> dict:
            assert_equal(product_id, "manual_camry_001", "API must retain product id")
            assert_equal(patch["annotations"]["shipping_policy"], "请先预约", "API must retain V2 patch payload")
            return {"ok": True, "operation": "update_admin_view", "item": {"id": product_id}}

    original_service = product_console_api.ProductConsoleService
    product_console_api.ProductConsoleService = FakeProductConsoleService
    try:
        app = FastAPI()
        app.include_router(product_console_api.router)
        response = TestClient(app).put(
            "/api/product-console/products/manual_camry_001/admin-view",
            json={"annotations": {"shipping_policy": "请先预约"}},
        )
    finally:
        product_console_api.ProductConsoleService = original_service
    assert_equal(response.status_code, 200, "V2 API route must be available")
    assert_equal(response.json().get("operation"), "update_admin_view", "V2 API must return service result unchanged")


def check_v2_vehicle_image_api_contract() -> None:
    class FakeProductConsoleService:
        def upload_vehicle_image(self, product_id: str, *, filename: str, content: bytes, content_type: str | None) -> dict:
            assert_equal(product_id, "manual_camry_001", "image API must retain product id")
            assert_equal(filename, "camry.png", "image API must retain uploaded filename")
            assert_equal(content_type, "image/png", "image API must retain declared MIME type")
            assert_true(content.startswith(b"\x89PNG"), "image API must retain binary payload")
            return {"ok": True, "operation": "upload_vehicle_image", "image": {"url": "/api/product-console/products/manual_camry_001/images/img_123"}}

        def delete_vehicle_image(self, product_id: str, image_id: str) -> dict:
            assert_equal(product_id, "manual_camry_001", "delete API must retain product id")
            assert_equal(image_id, "img_123", "delete API must retain exact image id")
            return {"ok": True, "operation": "delete_vehicle_image", "deleted_image_id": image_id}

    original_service = product_console_api.ProductConsoleService
    product_console_api.ProductConsoleService = FakeProductConsoleService
    try:
        app = FastAPI()
        app.include_router(product_console_api.router)
        response = TestClient(app).post(
            "/api/product-console/products/manual_camry_001/images",
            files={"file": ("camry.png", b"\x89PNG\r\n\x1a\nfixture", "image/png")},
        )
        deleted = TestClient(app).delete("/api/product-console/products/manual_camry_001/images/img_123")
    finally:
        product_console_api.ProductConsoleService = original_service
    assert_equal(response.status_code, 200, "V2 image upload API route must be available")
    assert_equal(response.json().get("operation"), "upload_vehicle_image", "V2 image upload route must return service result")
    assert_equal(deleted.status_code, 200, "V2 image delete API route must be available")
    assert_equal(deleted.json().get("operation"), "delete_vehicle_image", "V2 image delete route must return service result")


def check_frontend_uses_v2_console_contract() -> None:
    app_js = (APP_ROOT / "admin_backend" / "static" / "app.js").read_text(encoding="utf-8")
    index_html = (APP_ROOT / "admin_backend" / "static" / "index.html").read_text(encoding="utf-8")
    assert_true("/admin-view" in app_js and "saveProductV2DetailForm" in app_js, "frontend must save V2 through product-console endpoint")
    assert_true("productAdminView" in app_js and "大风车同步" in app_js, "frontend must render V2 source metadata")
    assert_true("dafengcheFieldGroupsHtml" in app_js and "baseCarInfo.name" in app_js, "frontend must render exact Dafengche field paths")
    assert_true("dafengcheFieldValueHtml" in app_js and "vehicle-card-facts" in app_js, "missing Dafengche values must remain visibly blank in fixed card fields")
    assert_true("vehicle-advanced-panel" in app_js and ">高级<" in app_js, "operational material must stay behind a collapsed Advanced section")
    assert_true("vehicle-v2-editor-groups" in app_js and "source_payloads.vehicle_pictures.payload" in app_js, "V2 editor must group original Dafengche paths and expose picture payload editing")
    assert_true("uploadProductV2VehicleImages" in app_js and "FormData" in app_js, "V2 editor must submit vehicle image uploads as multipart data")
    assert_true("data-vehicle-image-remove-id" in app_js and 'method: "DELETE"' in app_js, "manual V2 image editor must expose an explicit delete action")
    assert_true("选中后立即上传并显示" in app_js and "vehicle-image-uploading-label" in app_js, "manual V2 image editor must render immediate upload feedback")
    assert_true("productDetailRequestId" in app_js and "state.selectedProduct?.id !== productId" in app_js, "stale vehicle-image responses must not reopen an old selected car")
    assert_true("productDetailModalOpenRequested" in app_js and "state.productDetailRequestId += 1" in app_js, "closing the vehicle detail must invalidate pending automatic reopen actions")
    assert_true("product-catalog-source-filter" in index_html, "frontend must expose source filtering")


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
