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
from apps.wechat_ai_customer_service.admin_backend.services.product_master_excel_import import VEHICLE_COLUMNS, _simple_field_label
from apps.wechat_ai_customer_service.admin_backend.api import product_console as product_console_api
from apps.wechat_ai_customer_service.admin_backend.auth_context import AuthTenantMiddleware
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id
from apps.wechat_ai_customer_service.product_master import ProductMasterStore
from apps.wechat_ai_customer_service.scripts.enrich_chejin_v2_from_legacy_snapshot import plan_legacy_snapshot_enrichment
from apps.wechat_ai_customer_service.scripts.fill_chejin_v2_vehicle_test_fields import plan_vehicle_test_field_fill
from packages.dafengche_product_master import apply_admin_vehicle_update, build_admin_vehicle_view
from packages.dafengche_product_master.contract import VEHICLE_DETAIL_FIELD_GROUP_SPECS


def main() -> int:
    checks = [
        check_v2_admin_view_uses_authoritative_vehicle_fields,
        check_manual_update_preserves_v2_and_records_provenance,
        check_dafengche_source_fields_are_read_only,
        check_generic_manual_input_converts_to_v2_at_storage_boundary,
        check_legacy_snapshot_enrichment_is_evidenced_and_idempotent,
        check_explicit_test_field_fill_is_missing_only_and_reversible,
        check_manual_vehicle_image_upload_uses_v2_picture_payload,
        check_image_upload_response_is_shallow_and_frontend_preserves_full_detail,
        check_product_console_v2_write_and_compatibility_output,
        check_local_vehicle_draft_and_create_contract,
        check_v2_admin_view_api_contract,
        check_local_vehicle_create_api_contract,
        check_local_vehicle_http_round_trip_persists_before_refresh,
        check_chejin_manual_vehicle_admin_view_round_trip_keeps_tenant_context,
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
                    "carOwnerInfo": {
                        "phoneNumber": "OWNER-PHONE-DO-NOT-LIST",
                        "identify": "OWNER-ID-CARD-DO-NOT-LIST",
                        "bankId": "OWNER-BANK-ID-DO-NOT-LIST",
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
    hidden_user_paths = {
        "carId",
        "orgId",
        "shopCode",
        "owner",
        "creator",
        "baseCarInfo.name",
        "baseCarInfo.name.brandCode",
        "baseCarInfo.name.seriesCode",
        "baseCarInfo.name.modelCode",
        "baseCarInfo.area",
        "baseCarInfo.area.cityCode",
        "baseCarInfo.area.provinceCode",
        "baseCarInfo.registerArea",
        "baseCarInfo.registerArea.cityCode",
        "baseCarInfo.registerArea.provinceCode",
        "baseCarInfo.detectReportPdf",
        "carOwnerInfo",
    }
    expected_paths = {spec.path for _group_id, _label, specs in VEHICLE_DETAIL_FIELD_GROUP_SPECS for spec in specs} - hidden_user_paths
    canonical_paths = {field["path"] for group in view["dafengche_field_groups"] if group["id"] != "other_fields" for field in group["fields"]}
    assert_equal(canonical_paths, expected_paths, "admin user-facing matrix must keep readable Dafengche fields while hiding technical code/system rows")
    assert_true(hidden_user_paths.isdisjoint(canonical_paths), "user-facing admin matrix must not expose code/source identity fields")
    title_row = next(field for group in view["dafengche_field_groups"] for field in group["fields"] if field["path"] == "baseCarInfo.name.displayValue")
    assert_equal(title_row["value"], "凯美瑞 2.0G", "legacy scalar baseCarInfo.name must project into canonical displayValue")
    assert_equal(title_row.get("source_path"), "baseCarInfo.name", "legacy scalar name must be marked as a compatibility projection")
    assert_true(title_row.get("editable") is True and title_row.get("required") is True, "displayValue is the only required editable source field")
    brand_row = next(field for group in view["dafengche_field_groups"] for field in group["fields"] if field["path"] == "baseCarInfo.name.brandName")
    assert_equal(brand_row["value"], "丰田", "legacy baseCarInfo.brandName must project into canonical nested brandName")
    assert_equal(brand_row.get("source_path"), "baseCarInfo.brandName", "legacy top-level brand must be marked as compatibility projection")
    object_name_record = v2_vehicle()
    object_base = object_name_record["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]
    object_base["name"] = {"brandName": "丰田", "seriesName": "凯美瑞", "modelName": "2.0G"}
    object_name_view = build_admin_vehicle_view(object_name_record, include_raw=True)
    object_title_row = next(field for group in object_name_view["dafengche_field_groups"] for field in group["fields"] if field["path"] == "baseCarInfo.name.displayValue")
    assert_equal(object_title_row["value"], "丰田 凯美瑞 2.0G", "name object without displayValue must project a readable display name")
    assert_true(not isinstance(object_title_row["value"], dict), "name object without displayValue must not become a JSON value in the editable title control")
    for path in ("baseCarInfo.vinNumber", "carOwnerInfo.phoneNumber", "carPriceInfo.purchasePrice"):
        row = next(field for group in view["dafengche_field_groups"] for field in group["fields"] if field["path"] == path)
        assert_true(row.get("restricted") is True, f"restricted field must stay restricted for customer evidence: {path}")
        assert_true(row.get("editable") is True, f"manual admin must still be able to edit restricted local source field: {path}")
    other_group = next(group for group in view["dafengche_field_groups"] if group["id"] == "other_fields")
    assert_true(any(field["path"] == "carModelParam.gearbox" for field in other_group["fields"]), "unknown raw payload fields must remain retained in backend projection")
    assert_true(all(field.get("editable") is not True for field in other_group["fields"]), "unknown raw fields must be read-only and excluded from patch collection")
    assert_true(view["raw_source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["vinNumber"], "admin raw audit must retain payload")


def check_manual_update_preserves_v2_and_records_provenance() -> None:
    updated = apply_admin_vehicle_update(
        v2_vehicle(),
        {
            "vehicle_detail_patch": {
                "baseCarInfo": {"name": {"displayValue": "凯美瑞 2.5G", "brandName": "丰田", "seriesName": "凯美瑞", "modelName": "2.5G"}},
                "carPriceInfo": {"salePrice": 14.28},
            },
            "annotations": {"shipping_policy": "到店看车请预约"},
            "manual_annotations": {"sku": "CAMRY-001-R"},
        },
        observed_at="2026-07-13T02:00:00+00:00",
    )
    payload = updated["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(payload["baseCarInfo"]["name"]["displayValue"], "凯美瑞 2.5G", "manual name must update canonical nested payload")
    assert_equal(payload["baseCarInfo"]["name"]["brandName"], "丰田", "manual brand must stay under baseCarInfo.name")
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


def check_image_upload_response_is_shallow_and_frontend_preserves_full_detail() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = ProductConsoleService()
        service.store.product_master = ProductMasterStore(tenant_id="product_console_upload_shallow_check", root=Path(directory) / "product_master")  # type: ignore[assignment]
        service.compiler.compile_to_disk = lambda: None  # type: ignore[assignment]
        record = v2_vehicle()
        service.store.product_master.save_item(record)
        detail = service.detail(record["id"])["item"]
        assert_true(
            len(detail.get("admin_view", {}).get("dafengche_field_groups") or []) > 0,
            "full product detail must include editable Dafengche field groups before image upload",
        )
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAFAAH/e+m+7wAAAABJRU5ErkJggg==")
        original_enqueue = product_console_service_module.enqueue_vehicle_image_index
        product_console_service_module.enqueue_vehicle_image_index = lambda product_id, *, tenant_id, cause: {"accepted": True, "state": "queued", "reason": "fixture"}  # type: ignore[assignment]
        try:
            result = service.upload_vehicle_image(record["id"], filename="upload.png", content=png, content_type="image/png")
        finally:
            product_console_service_module.enqueue_vehicle_image_index = original_enqueue  # type: ignore[assignment]
        response_groups = result.get("item", {}).get("admin_view", {}).get("dafengche_field_groups") or []
        assert_equal(response_groups, [], "image upload response is intentionally a shallow catalog-style item")

    app_js = (APP_ROOT / "admin_backend" / "static" / "app.js").read_text(encoding="utf-8")
    upload_source = app_js.split("async function uploadProductV2VehicleImages", 1)[1].split("async function refreshSelectedProductDetailSnapshot", 1)[0]
    reorder_source = app_js.split("async function reorderProductV2VehicleImage", 1)[1].split("function vehiclePicturePayloadForEdit", 1)[0]
    delete_source = app_js.split("async function deleteProductV2VehicleImage", 1)[1].split("function compactObject", 1)[0]
    assert_true(
        "state.selectedProduct = payload.item" not in upload_source
        and "state.selectedProduct = payload.item" not in reorder_source
        and "state.selectedProduct = payload.item" not in delete_source,
        "image operations must not replace a full editing detail with the shallow upload response item",
    )
    assert_true(
        "refreshSelectedProductDetailSnapshot(productId, productTenantId)" in upload_source
        and "refreshSelectedProductDetailSnapshot(productId, productTenantId)" in reorder_source
        and "refreshSelectedProductDetailSnapshot(productId, productTenantId)" in delete_source,
        "image operations must refresh the full detail snapshot instead of re-rendering from a shallow response",
    )
    assert_true(
        "headers: tenantScopedHeaders(productTenantId)" in upload_source
        and "headers: tenantScopedHeaders(productTenantId)" in reorder_source
        and "headers: tenantScopedHeaders(productTenantId)" in delete_source,
        "image operations must preserve the current product tenant context",
    )
    assert_true(
        "if (pendingImageUpload) await pendingImageUpload;" in app_js,
        "saving while images are uploading must wait for the upload task before collecting the final save request",
    )


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
    assert_true("source_payloads" not in displayed, "catalog must not expose raw V2 source payloads at top level")
    assert_true("extensions" not in displayed, "catalog must not expose internal V2 extension snapshots at top level")
    assert_true("raw_source_payloads" not in displayed["admin_view"], "catalog must not expose raw admin payloads")
    displayed_text = str(displayed)
    assert_true("carOwnerInfo" not in displayed_text, "catalog admin view must not expose the owner-info object")
    for restricted in ("OWNER-PHONE-DO-NOT-LIST", "OWNER-ID-CARD-DO-NOT-LIST", "OWNER-BANK-ID-DO-NOT-LIST"):
        assert_true(restricted not in displayed_text, f"catalog admin view leaked owner field: {restricted}")
    detail = service.detail(record["id"])
    assert_true("raw_source_payloads" in detail["item"]["admin_view"], "detail must retain raw payloads for authenticated audit")
    assert_true("OWNER-PHONE-DO-NOT-LIST" in str(detail["item"]["admin_view"]["raw_source_payloads"]), "detail raw audit view must retain owner info")
    result = service.update_admin_view(record["id"], {"vehicle_detail_patch": {"baseCarInfo": {"name": {"displayValue": "凯美瑞 2.5G"}}}})
    assert_equal(result["operation"], "update_admin_view", "must use V2 operation")
    assert_true(saved and "data" not in saved[-1], "V2 console save must not persist generic data")
    assert_equal(saved[-1]["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["name"]["displayValue"], "凯美瑞 2.5G", "V2 console save must update canonical nested field")


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


def check_local_vehicle_create_api_contract() -> None:
    class FakeProductConsoleService:
        def local_vehicle_draft(self) -> dict:
            return {"ok": True, "mode": "local_manual_vehicle", "item": {"id": "manual_vehicle_draft"}}

        def create_local_vehicle(self, payload: dict) -> dict:
            assert_equal(payload["vehicle_detail_patch"]["baseCarInfo"]["name"]["displayValue"], "API 新车", "create API must retain vehicle patch")
            return {"ok": True, "operation": "create_local_vehicle", "item": {"id": "manual_vehicle_api_001"}}

    original_service = product_console_api.ProductConsoleService
    product_console_api.ProductConsoleService = FakeProductConsoleService
    try:
        app = FastAPI()
        app.include_router(product_console_api.router)
        client = TestClient(app)
        draft = client.get("/api/product-console/local-vehicle-draft")
        created = client.post(
            "/api/product-console/products",
            json={"vehicle_detail_patch": {"baseCarInfo": {"name": {"displayValue": "API 新车"}}}},
        )
    finally:
        product_console_api.ProductConsoleService = original_service
    assert_equal(draft.status_code, 200, "local vehicle draft API route must be available")
    assert_equal(draft.json().get("mode"), "local_manual_vehicle", "draft API must return the manual mode")
    assert_equal(created.status_code, 200, "local vehicle create API route must be available")
    assert_equal(created.json().get("operation"), "create_local_vehicle", "create API must return service result")


def check_local_vehicle_http_round_trip_persists_before_refresh() -> None:
    """Exercise the real draft/create/detail/catalog route chain in isolation."""

    class FakeAuthService:
        def resolve_context(self, *, authorization: str = "", tenant_id: str | None = None, dev_role: str = "", dev_user_id: str = ""):
            from apps.wechat_ai_customer_service.auth import AuthService

            return AuthService().implicit_admin_context(tenant_id=tenant_id)

    with tempfile.TemporaryDirectory() as directory:
        service = ProductConsoleService()
        service.store.product_master = ProductMasterStore(
            tenant_id="product_console_http_round_trip",
            root=Path(directory) / "product_master",
        )  # type: ignore[assignment]
        service.compiler.compile_to_disk = lambda: None  # type: ignore[assignment]

        original_service = product_console_api.service
        product_console_api.service = lambda: service  # type: ignore[assignment]
        try:
            app = FastAPI()
            app.include_router(product_console_api.router)
            app.add_middleware(AuthTenantMiddleware, auth_service=FakeAuthService())
            client = TestClient(app)

            draft = client.get("/api/product-console/local-vehicle-draft")
            assert_equal(draft.status_code, 200, "draft route must be readable before login")
            created = client.post(
                "/api/product-console/products",
                headers={"X-Tenant-ID": "product_console_http_round_trip"},
                json={
                    "vehicle_detail_patch": {
                        "baseCarInfo": {
                            "name": {"displayValue": "HTTP 闭环测试车", "brandName": "测试品牌"},
                            "mileage": 1.2,
                        },
                        "carPriceInfo": {"salePrice": 8.8},
                    },
                    "annotations": {"specs": "保存后应可立即重新读取"},
                },
            )
            assert_equal(created.status_code, 200, "real create route must persist the vehicle")
            created_item = created.json().get("item") or {}
            product_id = str(created_item.get("id") or "")
            assert_true(product_id.startswith("manual_vehicle_"), "create route must return generated local vehicle id")

            detail = client.get(f"/api/product-console/products/{product_id}", headers={"X-Tenant-ID": "product_console_http_round_trip"})
            assert_equal(detail.status_code, 200, "created vehicle detail must be readable immediately")
            detail_item = detail.json().get("item") or {}
            detail_name = ((detail_item.get("admin_view") or {}).get("summary") or {}).get("name")
            assert_equal(detail_name, "HTTP 闭环测试车", "detail route must read the just-persisted vehicle")

            catalog = client.get("/api/product-console/catalog?include_archived=true", headers={"X-Tenant-ID": "product_console_http_round_trip"})
            assert_equal(catalog.status_code, 200, "catalog refresh must remain available after create")
            assert_true(any(str(item.get("id") or "") == product_id for item in (catalog.json().get("items") or [])), "catalog must include the created vehicle")
        finally:
            product_console_api.service = original_service  # type: ignore[assignment]


def check_chejin_manual_vehicle_admin_view_round_trip_keeps_tenant_context() -> None:
    class FakeAuthService:
        def resolve_context(self, *, authorization: str = "", tenant_id: str | None = None, dev_role: str = "", dev_user_id: str = ""):
            from apps.wechat_ai_customer_service.auth import AuthService

            return AuthService().implicit_admin_context(tenant_id=tenant_id)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        product_id = "chejin_audi_a4l_2018_40tfsi"
        record = v2_vehicle()
        record["id"] = product_id
        record["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["name"] = {
            "displayValue": "奥迪 A4L 2018 40TFSI",
            "brandName": "奥迪",
            "seriesName": "A4L",
            "modelName": "40TFSI",
        }
        record["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["area"] = {"cityName": ""}
        record["source_payloads"]["vehicle_detail"]["payload"]["baseCarInfo"]["carDetailForDisplay"] = ""
        ProductMasterStore(tenant_id="chejin", root=root / "chejin" / "product_master").save_item(record)

        def scoped_service() -> ProductConsoleService:
            service = ProductConsoleService()
            tenant_id = active_tenant_id()
            service.store.product_master = ProductMasterStore(tenant_id=tenant_id, root=root / tenant_id / "product_master")  # type: ignore[assignment]
            service.compiler.compile_to_disk = lambda: None  # type: ignore[assignment]
            return service

        original_service = product_console_api.service
        product_console_api.service = scoped_service  # type: ignore[assignment]
        try:
            app = FastAPI()
            app.include_router(product_console_api.router)
            app.add_middleware(AuthTenantMiddleware, auth_service=FakeAuthService())
            client = TestClient(app)

            saved = client.put(
                f"/api/product-console/products/{product_id}/admin-view",
                headers={"X-Tenant-ID": "chejin"},
                json={
                    "vehicle_detail_patch": {
                        "baseCarInfo": {
                            "name": {"displayValue": "奥迪 A4L 已更新"},
                            "area": {"cityName": "南京"},
                            "carDetailForDisplay": "新增填写的车况描述",
                        }
                    }
                },
            )
            assert_equal(saved.status_code, 200, "chejin tenant admin-view save must succeed")
            assert_equal(saved.headers.get("x-tenant-id"), "chejin", "middleware must keep chejin tenant on save response")

            detail = client.get(f"/api/product-console/products/{product_id}", headers={"X-Tenant-ID": "chejin"})
            assert_equal(detail.status_code, 200, "chejin tenant detail refresh must find the saved product")
            title = (((detail.json().get("item") or {}).get("admin_view") or {}).get("vehicle") or {}).get("title")
            assert_equal(title, "奥迪 A4L 已更新", "detail refresh must read the saved chejin vehicle")
            raw = (((detail.json().get("item") or {}).get("admin_view") or {}).get("raw_source_payloads") or {}).get("vehicle_detail", {}).get("payload", {})
            assert_equal(raw.get("baseCarInfo", {}).get("area", {}).get("cityName"), "南京", "empty city field must save and read back in the same tenant")
            assert_equal(raw.get("baseCarInfo", {}).get("carDetailForDisplay"), "新增填写的车况描述", "empty editable text field must save and read back in the same tenant")

            wrong_tenant = client.get(f"/api/product-console/products/{product_id}", headers={"X-Tenant-ID": "default"})
            assert_equal(wrong_tenant.status_code, 404, "default tenant must not globally find chejin vehicle")
        finally:
            product_console_api.service = original_service  # type: ignore[assignment]


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


def check_local_vehicle_draft_and_create_contract() -> None:
    with tempfile.TemporaryDirectory() as directory:
        service = ProductConsoleService()
        service.store.product_master = ProductMasterStore(
            tenant_id="product_console_create_check",
            root=Path(directory) / "product_master",
        )  # type: ignore[assignment]
        draft = service.local_vehicle_draft()
        draft_item = draft.get("item") or {}
        assert_equal(draft.get("mode"), "local_manual_vehicle", "new vehicle draft mode")
        assert_equal((draft_item.get("admin_view") or {}).get("record_kind"), "vehicle_v2", "new vehicle draft must use V2 admin view")
        assert_true((draft_item.get("admin_view") or {}).get("capabilities", {}).get("can_edit_vehicle_source") is True, "new vehicle draft must expose editable vehicle fields")

        created = service.create_local_vehicle(
            {
                "vehicle_detail_patch": {
                    "baseCarInfo": {
                        "name": {"displayValue": "测试新车", "brandName": "测试品牌"},
                        "mileage": 3.2,
                    },
                    "carPriceInfo": {"salePrice": 12.8},
                },
                "annotations": {"specs": "测试资料"},
                "manual_annotations": {"inventory": 1},
            }
        )
        item = created.get("item") or {}
        created_id = str(item.get("id") or "")
        persisted = service.get_product_item(created_id, include_archived=True) or {}
        detail = (((persisted.get("source_payloads") or {}).get("vehicle_detail") or {}).get("payload") or {})
        assert_true(str(item.get("id") or "").startswith("manual_vehicle_"), "new local vehicle id must be generated by the server")
        assert_equal((item.get("source") or {}).get("type"), "manual", "new vehicle source")
        assert_equal(((item.get("source") or {}).get("binding") or {}).get("state"), "unbound", "new vehicle binding")
        assert_true("source_payloads" not in item, "public create response must not expose raw source payloads")
        assert_equal(((detail.get("baseCarInfo") or {}).get("name") or {}).get("displayValue"), "测试新车", "new vehicle nested display name")
        assert_equal((item.get("data") or {}).get("name"), "测试新车", "compatibility projection name")
        assert_equal((item.get("admin_view") or {}).get("summary", {}).get("name"), "测试新车", "created response must expose the new vehicle summary")
        try:
            service.create_local_vehicle({"vehicle_detail_patch": {"baseCarInfo": {"name": {}}}})
        except ValueError as exc:
            assert_true("车辆展示名称不能为空" in str(exc), "new vehicle must require a display name")
        else:
            raise AssertionError("new vehicle without a display name must fail")


def check_frontend_uses_v2_console_contract() -> None:
    app_js = (APP_ROOT / "admin_backend" / "static" / "app.js").read_text(encoding="utf-8")
    styles_css = (APP_ROOT / "admin_backend" / "static" / "styles.css").read_text(encoding="utf-8")
    index_html = (APP_ROOT / "admin_backend" / "static" / "index.html").read_text(encoding="utf-8")
    assert_true("product-new-local-vehicle" in index_html and "新增本地车辆" in index_html, "product catalog must expose a manual new vehicle entry")
    assert_true("/api/product-console/local-vehicle-draft" in app_js and "state.productDetailMode = \"new\"" in app_js, "new vehicle entry must load a V2 draft form")
    assert_true('isCreating ? "/api/product-console/products"' in app_js and 'method: isCreating ? "POST" : "PUT"' in app_js, "new vehicle save must use the V2 create route")
    assert_true("refreshCreatedProductAfterSave(createdId, productTenantId)" in app_js, "new vehicle save must not wait on detail/catalog refresh before ending save")
    assert_true(
        'fetch(path, {headers: apiHeaders()})' in app_js and 'window.location.href = "/api/product-console/local-vehicle-excel-template"' not in app_js,
        "Excel template download must use the authenticated fetch path instead of unauthenticated navigation",
    )
    assert_true(
        'local-vehicle-excel-import/preview' in app_js and 'headers: apiHeaders(), body: form' in app_js,
        "Excel preview upload must carry the authenticated request headers",
    )
    assert_true("/admin-view" in app_js and "saveProductV2DetailForm" in app_js, "frontend must save V2 through product-console endpoint")
    assert_true("productAdminView" in app_js and "历史外部镜像" in app_js, "frontend must render V2 source metadata without expanding sync semantics")
    assert_true("dafengcheFieldGroupsHtml" in app_js and "productVisibleVehicleFieldGroups" in app_js, "frontend must render vehicle field groups through the business-facing facade")
    assert_true(
        "productSystemVehicleFieldGroups" in app_js
        and "车源识别（辅助确认）" in app_js
        and "其他保留信息（系统）" not in app_js
        and "其他大风车字段" not in app_js,
        "uncategorized raw fallback fields must not be shown in the product console UI",
    )
    assert_true(
        '<small>${escapeHtml(field?.path || "")}</small>' not in app_js
        and "公开售价 · carPriceInfo.salePrice" not in app_js
        and "车辆图片 · vehicle_pictures.payload" not in app_js
        and "完整原始载荷 JSON" not in app_js,
        "ordinary vehicle UI must not expose internal paths or raw payload labels",
    )
    assert_true("dafengcheFieldValueHtml" in app_js and "vehicle-card-facts" in app_js, "missing Dafengche values must remain visibly blank in fixed card fields")
    assert_true("vehicle-advanced-panel" in app_js and ">高级选项<" in app_js, "operational material must stay behind a collapsed Advanced section")
    assert_true("vehicle-v2-editor-groups" in app_js and "vehicleV2PictureEditorHtml" in app_js, "V2 editor must group editable vehicle fields and expose picture editing")
    detail_form = app_js.split("function renderProductV2Detail", 1)[1].split("function dafengcheFieldValueHtml", 1)[0]
    detail_main, detail_advanced = detail_form.split('<details class="vehicle-advanced-panel">', 1)
    assert_true('open class="vehicle-advanced-panel"' not in detail_form, "V2 detail advanced panel must remain collapsed by default")
    assert_true("车辆字段内容" in detail_main and "车辆图片" in detail_main, "V2 detail main area must keep standard vehicle fields and pictures visible")
    assert_true("车源识别" not in detail_main, "source identity must not be a core vehicle section")
    assert_true("车源识别（辅助确认）" in app_js and "dafengcheFieldGroupsHtml(systemFieldGroups)" in detail_advanced, "source identity must move behind the advanced auxiliary confirmation section")
    for label in ("客户常用叫法", "核心参数/车况补充", "专属知识与话术"):
        assert_true(label not in detail_main, f"local extension detail content must not appear in the ordinary detail area: {label}")
        assert_true(label in detail_advanced, f"local extension detail content must stay behind advanced panel: {label}")
    assert_true(
        '<details class="vehicle-v2-advanced-editor">' in app_js
        and 'open class="vehicle-v2-advanced-editor"' not in app_js
        and "高级选项（一般不用）" in app_js,
        "V2 editor advanced options must default collapsed with a business-language summary",
    )
    edit_form = app_js.split("function productV2EditFormHtml", 1)[1].split("function vehicleV2EditorGroupHtml", 1)[0]
    edit_main, edit_advanced = edit_form.split('<details class="vehicle-v2-advanced-editor">', 1)
    assert_true(
        "vehicleV2RawFieldGroupsEditorHtml(visibleFieldGroups, canEditVehicle)" in edit_main
        and "Array.isArray(view.dafengche_field_groups)" in edit_form
        and "productVisibleVehicleFieldGroups(fieldGroups)" in edit_form
        and "productSystemVehicleFieldGroups(fieldGroups)" in edit_form,
        "V2 editor must use the same raw field matrix while splitting core business fields from auxiliary source identity",
    )
    assert_true("车源识别" not in edit_main and "vehicleV2RawFieldGroupsEditorHtml(systemFieldGroups, false)" in edit_advanced, "source identity must be auxiliary and read-only in edit mode too")
    assert_true("vehicleV2PictureEditorHtml" in edit_main and 'id="product-v2-image-files" type="file"' in app_js, "image upload must remain a visible core editor action")
    for label in (
        "客户可见补充",
        "客户回复话术",
        "本地管理字段",
        "内部备注",
        "精准触发知识（强触发）",
        "商品专属问答",
        "商品专属规则",
        "商品专属解释",
    ):
        assert_true(label not in edit_main, f"local extension group must not appear in the main editor area: {label}")
        assert_true(label in edit_advanced, f"local extension group must stay available inside collapsed advanced editor: {label}")
    assert_true(
        '<small>${escapeHtml(path)}</small>' not in app_js
        and 'source_payloads.vehicle_pictures.payload</small>' not in app_js,
        "V2 edit controls must not show internal field paths or source payload variable names",
    )
    assert_true(
        "vehicleV2RawFieldControlHtml" in app_js
        and "data-dafengche-path" in app_js
        and "data-dafengche-editable" in app_js
        and "vehicleRawGroupLabel" in app_js,
        "V2 editor must render original source fields from row metadata instead of hard-coded input IDs",
    )
    raw_control_source = app_js.split("function vehicleV2RawFieldControlHtml", 1)[1].split("function productV2FieldInput", 1)[0]
    assert_true("wide-field" not in raw_control_source, "raw Dafengche controls must not force every long/object value to full-width rows")
    assert_true("readonly aria-readonly" in raw_control_source, "raw read-only fields should remain scrollable/copyable without entering patch")
    assert_true(
        ".vehicle-v2-raw-field textarea" in styles_css
        and "max-height: 96px" in styles_css
        and ".vehicle-v2-raw-field.is-object-value textarea" in styles_css
        and "max-height: 124px" in styles_css
        and "overflow: auto" in styles_css,
        "raw field editor must cap long text/object height with internal scrolling",
    )
    assert_true(
        "grid-template-columns: repeat(4, minmax(0, 1fr))" in styles_css
        and "grid-template-columns: repeat(2, minmax(0, 1fr))" in styles_css
        and "@media (max-width: 768px)" in styles_css
        and ".vehicle-v2-editor-grid {\n    grid-template-columns: 1fr;" in styles_css
        and "overflow-wrap: anywhere" in styles_css
        and ".vehicle-v2-raw-field.is-readonly" in styles_css,
        "raw field editor must use compact desktop/tablet/mobile grouping, wrapping labels, and subdued read-only styling",
    )
    assert_true(
        'rawVehicleDetailPatchValue("baseCarInfo.name.displayValue")' in app_js
        and 'throw new Error("车辆展示名称不能为空。")' in app_js,
        "V2 editor must block empty canonical display name before calling the API",
    )
    v2_save_source = app_js.split("async function saveProductV2DetailForm", 1)[1].split("function refreshProductAfterSave", 1)[0]
    assert_true(
        "productDetailTenantId" in app_js
        and 'if (state.activeTenantId && !headers["X-Tenant-ID"])' in app_js
        and "tenantScopedHeaders(productTenantId)" in app_js
        and "refreshSelectedProductDetailSnapshot(original.id, productTenantId)" in v2_save_source
        and "refreshProductAfterSave(original.id, productTenantId, {refreshDetail: false})" in v2_save_source,
        "V2 save must preserve tenant context and load the full detail before rendering view mode",
    )
    assert_true(
        "function runProductDetailSave" in app_js
        and 'setProductSaveStatus("保存中...", "loading")' in app_js
        and 'setProductSaveStatus("已保存", "ok")' in app_js
        and 'setProductSaveStatus(`保存失败：${error?.message || "未知错误"}`, "error")' in app_js
        and 'setProductSaveStatus("已保存，刷新失败", "warning")' in app_js,
        "product editor save must show loading, success, refresh-warning, and failure states",
    )
    assert_true(
        "updateProductDetailSaveControls()" in app_js
        and "saveButton.disabled = loading" in app_js
        and "root.querySelector(\".product-detail-cancel\")?.toggleAttribute(\"disabled\", loading)" in app_js
        and "保存中..." in app_js
        and "product-detail-save" in app_js,
        "product editor save must disable duplicate actions and restore controls without re-rendering typed input",
    )
    assert_true(
        "state.selectedProduct = payload.item" not in v2_save_source
        and "state.selectedProduct = payload.item" in app_js
        and "state.productDetailRequestId += 1" in app_js
        and "preserveSelected: true" in app_js,
        "V2 save must not render the shallow save response item, while full detail refreshes remain guarded",
    )
    assert_true(
        "filter((field) => vehicleValuePresent(field?.value))" in app_js
        and "dafengcheFieldGroupsHtml(visibleFieldGroups)" in app_js
        and "空白字段不显示" in app_js,
        "V2 view mode must show filled readable Dafengche fields and hide blank rows",
    )
    assert_true(
        "车辆编号由系统记录身份，编辑页不单独修改；Excel 导入时车辆编号为必填" in app_js,
        "V2 editor must explain vehicle id is a stable system identity while Excel still requires it",
    )
    assert_true(
        "setNestedPatchValue(patch, path, value)" in app_js
        and "document.querySelectorAll(\"[data-dafengche-path][data-dafengche-editable='true']\")" in app_js,
        "V2 save patch must be generated from editable matrix rows only",
    )
    assert_true("uploadProductV2VehicleImages" in app_js and "FormData" in app_js, "V2 editor must submit vehicle image uploads as multipart data")
    assert_true('id="product-v2-image-files" type="file"' in app_js and " multiple " in app_js, "V2 image input must support selecting multiple files")
    assert_true("Array.from(input?.files || [])" in app_js and "for (const file of files)" in app_js, "V2 image upload must process selected files one by one")
    assert_true("appendVehicleImageUploadPreview" in app_js and "URL.createObjectURL(file)" in app_js, "V2 image upload must preview every selected image before upload completes")
    assert_true("vehicle-image-main-badge" in app_js and "设为主图" in app_js, "V2 image editor must make the first image the visible main image")
    assert_true("data-vehicle-image-order-id" in app_js and "reorderProductV2VehicleImage" in app_js, "V2 image editor must expose order editing controls")
    assert_true("vehicle_pictures_patch: pictures" in app_js and "/admin-view" in app_js, "V2 image ordering must reuse the existing admin-view save route")
    assert_true("data-vehicle-image-remove-id" in app_js and 'method: "DELETE"' in app_js, "manual V2 image editor must expose an explicit delete action")
    assert_true("逐张预览并上传" in app_js and "vehicle-image-uploading-label" in app_js, "manual V2 image editor must render immediate upload feedback")
    assert_true("productDetailRequestId" in app_js and "state.selectedProduct?.id !== productId" in app_js, "stale vehicle-image responses must not reopen an old selected car")
    assert_true("productDetailModalOpenRequested" in app_js and "state.productDetailRequestId += 1" in app_js, "closing the vehicle detail must invalidate pending automatic reopen actions")
    assert_true(
        "await loadProductDetail(item?.id, {open: true});" in app_js,
        "clicking a vehicle card must explicitly request the detail modal to open",
    )
    shell_render_index = app_js.find("renderProductDetailOpeningShell(item);")
    immediate_open_index = app_js.find("openProductDetailModal();")
    detail_fetch_index = app_js.find("await loadProductDetail(item?.id, {open: true});")
    assert_true(
        shell_render_index >= 0 and immediate_open_index >= 0 and detail_fetch_index >= 0 and shell_render_index < immediate_open_index < detail_fetch_index,
        "clicking a vehicle card must render a lightweight opening shell and open the modal before waiting for the detail fetch",
    )
    assert_true("function renderProductDetailOpeningShell" in app_js and "正在加载完整车辆资料" in app_js, "vehicle detail opening shell must remain lightweight and user-visible")
    assert_true(
        "if (shouldOpenModal) openProductDetailModal();" in app_js,
        "current detail loads must honor the captured open intent after the stale-request guard passes",
    )
    assert_true("product-catalog-source-filter" in index_html, "frontend must expose source filtering")


def assert_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
