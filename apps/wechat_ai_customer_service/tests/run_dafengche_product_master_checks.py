"""Portable Dafengche product-master, Brain-contract and RPA-boundary checks."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
APP_ROOT = PROJECT_ROOT / "apps" / "wechat_ai_customer_service"
for import_root in (APP_ROOT / "workflows", APP_ROOT / "adapters", APP_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from apps.wechat_ai_customer_service import dafengche_product_master_host_adapter as host_adapter_module  # noqa: E402
from apps.wechat_ai_customer_service.dafengche_product_master_host_adapter import ProductMasterStoreMirrorRepository  # noqa: E402
from apps.wechat_ai_customer_service.product_master import ProductMasterStore, customer_evidence_item, write_json  # noqa: E402
from apps.wechat_ai_customer_service.scripts.migrate_chejin_v1_to_v2_manual import (  # noqa: E402
    build_manual_v2_record,
    migrate_store,
)
from apps.wechat_ai_customer_service.workflows.customer_service_brain import compact_product_item_for_brain_prompt  # noqa: E402
from apps.wechat_ai_customer_service.workflows import reply_evidence_builder as reply_evidence_builder_module  # noqa: E402
from packages.dafengche_product_master import (  # noqa: E402
    CAR_DETAIL_API,
    CAR_IDS_API,
    CAR_PICTURES_API,
    CAR_UPDATE_API,
    CUSTOMER_DETAIL_FIELD_PATHS,
    CUSTOMER_RESTRICTED_FIELD_PATHS,
    CUSTOMER_UPDATE_PARAM_FIELD_PATHS,
    OFFICIAL_CUSTOMER_API_NAME_STATUS,
    SHOP_API,
    VEHICLE_CUSTOMER_VISIBLE_FIELD_PATHS,
    VEHICLE_DETAIL_FIELD_PATHS,
    VEHICLE_PICTURE_FIELD_PATHS,
    VEHICLE_RESTRICTED_FIELD_PATHS,
    VEHICLE_UPDATE_PARAM_FIELD_PATHS,
    CustomerEvidencePolicy,
    DafengcheCredentials,
    DafengcheOpenPlatformClient,
    DafengcheProductMaster,
    DafengcheReadOnlyClient,
    DafengcheSyncScope,
    InMemoryMirrorRepository,
    build_signature,
    build_admin_vehicle_view,
    create_manual_vehicle,
    project_legacy_record,
)


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "dafengche"
NOW = datetime(2026, 7, 13, 9, 30, tzinfo=timezone.utc)


class FixtureTransport:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.requests: list[dict[str, str]] = []

    def post(self, _url: str, payload: Mapping[str, str], *, timeout_seconds: float) -> Mapping[str, Any]:
        assert_true(timeout_seconds > 0, "transport should receive a timeout")
        request = dict(payload)
        self.requests.append(request)
        api = request.get("api") or ""
        if api not in self.responses:
            return {"success": False, "message": f"unexpected api: {api}"}
        return {"success": True, "data": self.responses[api]}


def main() -> int:
    results = [
        check_portable_sync_and_raw_payload_retention(),
        check_official_contract_surface_and_write_intent_isolation(),
        check_customer_evidence_policy_and_cross_shop_isolation(),
        check_manual_vehicle_and_host_storage_adapter(),
        check_legacy_facade_and_brain_input_contract(),
        check_source_markers_and_v1_to_v2_manual_migration(),
        check_portable_core_and_rpa_forbidden_import_boundaries(),
    ]
    payload = {"ok": all(item["ok"] for item in results), "count": len(results), "results": results}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def check_portable_sync_and_raw_payload_retention() -> dict[str, Any]:
    detail = load_fixture("car_detail_car_1001.json")
    detail["futureVendorExtension"] = {"nested": [None, {"flag": True}]}
    transport = FixtureTransport(
        {
            SHOP_API: load_fixture("shop.json"),
            CAR_IDS_API: load_fixture("car_ids_sale.json"),
            CAR_DETAIL_API: detail,
            CAR_PICTURES_API: load_fixture("car_pictures_car_1001.json"),
        }
    )
    client = DafengcheReadOnlyClient(
        credentials=DafengcheCredentials(app_key="test-app-key", app_secret="test-app-secret"),
        transport=transport,
        now_seconds=lambda: 1_784_000_000,
    )
    repository = InMemoryMirrorRepository()
    service = DafengcheProductMaster(repository=repository, client=client, now=lambda: NOW)
    result = service.sync(DafengcheSyncScope("app-001", "operator-001", "SHOP-001", ("sale",)))
    assert_equal(len(result["synced_record_ids"]), 1, "one vehicle should be synced")
    record = repository.list_records()[0]
    raw_detail = record["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(raw_detail, detail, "vehicle-detail payload must be retained unchanged")
    assert_equal(raw_detail["futureVendorExtension"]["nested"][0], None, "unknown null field must remain intact")
    assert_equal(raw_detail["carOwnerInfo"]["phoneNumber"], "TEST-OWNER-PHONE-MUST-NOT-LEAK", "vehicle owner info must remain in the internal mirror")
    assert_equal(raw_detail["baseCarInfo"]["detectReportPdf"]["url"], "https://example.invalid/vehicles/CAR-1001/detect-report.pdf", "inspection report must remain in the internal mirror")
    assert_equal(repository.audit_events[0]["shop_payload"], load_fixture("shop.json"), "shop payload must remain auditable")
    assert_equal(repository.audit_events[0]["car_id_list_payloads"][0]["payload"], load_fixture("car_ids_sale.json"), "car-id list payload must remain auditable")
    assert_equal(record["source"]["marker"]["ingest_channel"], "dafengche_api", "API mirror must keep its source marker")
    request = transport.requests[0]
    unsigned = {key: value for key, value in request.items() if key != "sign"}
    assert_equal(request["sign"], build_signature(unsigned, "test-app-secret"), "request signature contract")
    assert_true(all("test-app-secret" not in json.dumps(item, ensure_ascii=False) for item in repository.audit_events), "secret must not enter audit events")
    return {"name": "portable_sync_and_raw_payload_retention", "ok": True, "record_id": record["id"]}


def check_official_contract_surface_and_write_intent_isolation() -> dict[str, Any]:
    required_vehicle_paths = {
        "baseCarInfo.name.brandName",
        "baseCarInfo.name.seriesName",
        "baseCarInfo.name.modelName",
        "baseCarInfo.name.displayValue",
        "baseCarInfo.area.displayValue",
        "baseCarInfo.registerArea.displayValue",
        "baseCarInfo.stockStatus",
        "baseCarInfo.carDetailForDisplay",
        "baseCarInfo.innerColor",
        "baseCarInfo.detectReportPdf.url",
        "carOwnerInfo.phoneNumber",
        "carOwnerInfo.identify",
        "carOwnerInfo.bankId",
        "carPriceInfo.newPrice",
        "carPriceInfo.exhibitionPrice",
        "carPriceInfo.retrofitPrice",
        "carModelParam.gearBoxType",
        "carModelParam.engineVolumeLiter",
        "carModelParam.fuelType",
        "carLicenseInfo.keysCount",
        "carLicenseInfo.transferTotal",
    }
    assert_true(required_vehicle_paths.issubset(VEHICLE_DETAIL_FIELD_PATHS), "vehicle detail contract must include every audited official path")
    assert_true({"pictureName", "pictureNumber", "pictureDescription", "pictureBig", "businessType"}.issubset(VEHICLE_PICTURE_FIELD_PATHS), "vehicle picture contract must use official picture fields")
    assert_true(
        {
            "updateParam.baseCarInfo.name.brandCode",
            "updateParam.carOwnerInfo.phoneNumber",
            "updateParam.carPriceInfo.salePrice",
            "updateParam.carModelParam.gearBoxType",
            "updateParam.carLicenseInfo.transferTotal",
        }.issubset(VEHICLE_UPDATE_PARAM_FIELD_PATHS),
        "vehicle update contract must include official writeback fields",
    )
    assert_true({"phone", "weichat", "identityCard", "budgetUp", "sellBrandSeries.brandName", "location.displayValue"}.issubset(CUSTOMER_DETAIL_FIELD_PATHS), "customer field contract must be recorded separately")
    assert_true(
        {"updateParam.phone", "updateParam.weichat", "updateParam.identityCard", "updateParam.sellBrandSeries.brandName", "updateParam.location.displayValue", "updateParam.recordId"}.issubset(CUSTOMER_UPDATE_PARAM_FIELD_PATHS),
        "customer updateParam field contract must be recorded separately",
    )
    assert_equal(
        OFFICIAL_CUSTOMER_API_NAME_STATUS["customer_detail"],
        "document_section_present_but_api_name_missing",
        "customer query section must not invent an API name",
    )
    assert_true("carOwnerInfo.phoneNumber" in VEHICLE_RESTRICTED_FIELD_PATHS, "vehicle owner phone must be restricted")
    assert_true("identityCard" in CUSTOMER_RESTRICTED_FIELD_PATHS, "customer identity card must be restricted")
    assert_true("baseCarInfo.name.displayValue" in VEHICLE_CUSTOMER_VISIBLE_FIELD_PATHS, "official display name may be customer visible")

    transport = FixtureTransport({CAR_UPDATE_API: "CAR-1001"})
    client = DafengcheOpenPlatformClient(
        credentials=DafengcheCredentials(app_key="test-app-key", app_secret="test-app-secret"),
        transport=transport,
        now_seconds=lambda: 1_784_000_000,
    )
    update_result = client.update_car(
        update_param={
            "appId": "app-001",
            "carId": "CAR-1001",
            "operator": "operator-001",
            "baseCarInfo": {"name": {"brandCode": "TOYOTA", "brandName": "丰田"}},
            "carOwnerInfo": {"phoneNumber": "TEST-OWNER-PHONE-MUST-NOT-LEAK"},
            "carPriceInfo": {"salePrice": 15.28},
            "carModelParam": {"gearBoxType": "自动"},
            "carLicenseInfo": {"transferTotal": 0},
        }
    )
    assert_equal(update_result, "CAR-1001", "explicit write client must return upstream update result")
    request_data = json.loads(transport.requests[0]["data"])
    assert_equal(transport.requests[0]["api"], CAR_UPDATE_API, "explicit write client must use the documented vehicle update API")
    assert_equal(request_data["updateParam"]["carOwnerInfo"]["phoneNumber"], "TEST-OWNER-PHONE-MUST-NOT-LEAK", "write payload must preserve official updateParam shape")

    repository, _service = synced_service()
    view = build_admin_vehicle_view(repository.list_records()[0], include_raw=False)
    list_text = json.dumps(view, ensure_ascii=False)
    for restricted in ("carOwnerInfo", "TEST-OWNER-PHONE-MUST-NOT-LEAK", "TEST-ID-CARD-MUST-NOT-LEAK", "TEST-BANK-ID-MUST-NOT-LEAK"):
        assert_true(restricted not in list_text, f"default admin/list view leaked restricted owner field: {restricted}")
    audit_view = build_admin_vehicle_view(repository.list_records()[0], include_raw=True)
    audit_text = json.dumps(audit_view, ensure_ascii=False)
    assert_true("TEST-OWNER-PHONE-MUST-NOT-LEAK" in audit_text, "authorized raw audit view must retain owner info")
    audit_paths = {
        str(field.get("path") or "")
        for group in audit_view["dafengche_field_groups"]
        for field in group["fields"]
        if isinstance(field, dict)
    }
    assert_true(VEHICLE_DETAIL_FIELD_PATHS.issubset(audit_paths), "admin audit field groups must expose every documented vehicle-detail path")
    sync_apis = [request["api"] for request in _service.client.transport.requests] if _service.client else []
    assert_true(CAR_UPDATE_API not in sync_apis, "mirror sync must remain read-only and never call vehicle update")
    return {"name": "official_contract_surface_and_write_intent_isolation", "ok": True}


def check_customer_evidence_policy_and_cross_shop_isolation() -> dict[str, Any]:
    repository, service = synced_service()
    evidence = service.list_customer_evidence(shop_code="SHOP-001")
    assert_equal(len(evidence), 1, "bound shop should receive one projected vehicle")
    item = evidence[0]
    assert_equal(item["name"], "2021款 丰田 凯美瑞 2.0G 豪华版", "customer evidence name")
    assert_equal(item["price"], 15.28, "only public salePrice should project")
    evidence_text = json.dumps(item, ensure_ascii=False)
    for restricted in (
        "TEST-VIN-MUST-NOT-LEAK",
        "TEST-PLATE-MUST-NOT-LEAK",
        "TEST-OWNER-ID-MUST-NOT-LEAK",
        "TEST-CREATOR-ID-MUST-NOT-LEAK",
        "TEST-SALESPERSON-ID-MUST-NOT-LEAK",
        "TEST-INTERNAL-REMARK-MUST-NOT-LEAK",
        "TEST-PAYEE-MUST-NOT-LEAK",
        "TEST-OWNER-ADDRESS-MUST-NOT-LEAK",
        "TEST-BANK-ID-MUST-NOT-LEAK",
        "TEST-ID-CARD-MUST-NOT-LEAK",
        "TEST-OWNER-PHONE-MUST-NOT-LEAK",
        "TEST-OWNER-NAME-MUST-NOT-LEAK",
        "TEST-OTHER-ACCOUNT-MUST-NOT-LEAK",
        "TEST-BANK-NAME-MUST-NOT-LEAK",
        "TEST-ENGINE-NUMBER-MUST-NOT-LEAK",
        "10.01",
        "14.5",
        "14.2",
        "13.9",
    ):
        assert_true(restricted not in evidence_text, f"restricted source field leaked: {restricted}")
    assert_equal(service.list_customer_evidence(shop_code="SHOP-OTHER"), [], "cross-shop evidence must be denied")
    assert_equal(service.list_customer_evidence(shop_code=None), [], "bound Dafengche vehicle requires explicit shop scope")
    stale_policy = CustomerEvidencePolicy(max_age_seconds=60)
    assert_equal(
        service.list_customer_evidence(shop_code="SHOP-001", policy=stale_policy, now=NOW + timedelta(minutes=2)),
        [],
        "stale vehicle facts must not enter customer evidence",
    )
    assert_equal(len(repository.audit_events), 1, "sync audit event should remain internal")
    return {"name": "customer_evidence_policy_and_cross_shop_isolation", "ok": True}


def check_manual_vehicle_and_host_storage_adapter() -> dict[str, Any]:
    manual = create_manual_vehicle(
        record_id="manual_camry_001",
        vehicle_detail_payload=load_fixture("car_detail_car_1001.json"),
        field_provenance={"baseCarInfo.name": {"operator": "admin", "source": "manual"}},
        observed_at=NOW.isoformat(timespec="seconds"),
    )
    assert_equal(manual["source"]["type"], "manual", "manual source type")
    assert_equal(manual["source"]["marker"]["ingest_channel"], "manual_input", "manual entry must keep its source marker")
    assert_equal(manual["source"]["binding"]["state"], "unbound", "manual vehicle stays unbound")
    manual_repository = InMemoryMirrorRepository()
    manual_service = DafengcheProductMaster(repository=manual_repository, now=lambda: NOW)
    saved_manual = manual_service.save_manual_vehicle(
        record_id="manual_service_vehicle_001",
        vehicle_detail_payload=load_fixture("car_detail_car_1001.json"),
        field_provenance={"baseCarInfo.name": {"operator": "admin", "source": "manual"}},
    )
    assert_equal(
        len(manual_service.list_customer_evidence(shop_code=None, now=NOW + timedelta(days=14))),
        1,
        "active manual V2 records must not inherit Dafengche mirror expiry",
    )
    assert_equal(
        manual_service.list_customer_evidence(
            shop_code=None,
            policy=CustomerEvidencePolicy(manual_max_age_seconds=60),
            now=NOW + timedelta(minutes=2),
        ),
        [],
        "hosts may opt into an explicit manual-review expiry without changing mirror freshness",
    )
    try:
        manual_service.bind_manual_vehicle(
            record_id=saved_manual["id"],
            shop_code="SHOP-001",
            car_id="CAR-1001",
            operator="admin",
            explicit_confirmation=False,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("manual binding must reject implicit confirmation")
    bound_manual = manual_service.bind_manual_vehicle(
        record_id=saved_manual["id"],
        shop_code="SHOP-001",
        car_id="CAR-1001",
        operator="admin",
        explicit_confirmation=True,
    )
    assert_equal(bound_manual["source"]["binding"]["carId"], "CAR-1001", "manual binding must use explicit car id")
    assert_equal(manual_service.list_customer_evidence(shop_code="SHOP-OTHER"), [], "explicitly bound manual vehicle must preserve shop isolation")
    with tempfile.TemporaryDirectory(prefix="dafengche_product_master_") as temp_dir:
        store = ProductMasterStore(root=Path(temp_dir))
        adapter = ProductMasterStoreMirrorRepository(store)
        adapter.upsert(manual)
        saved = store.get_item("manual_camry_001")
        assert_true(bool(saved), "host adapter must persist v2 manual record through existing facade")
        evidence_item = customer_evidence_item(saved or {}, shop_code=None)
        assert_true(isinstance(evidence_item, dict), "manual v2 item should yield customer-safe compatibility record")
        assert_true("source_payloads" not in json.dumps(evidence_item, ensure_ascii=False), "compatibility record must not expose raw payload")
        _repository, synced = synced_service()
        mirrored_record = _repository.list_records()[0]
        queued: list[dict[str, str]] = []
        original_enqueue = host_adapter_module.enqueue_vehicle_image_index
        host_adapter_module.enqueue_vehicle_image_index = lambda product_id, *, tenant_id, cause: queued.append(  # type: ignore[assignment]
            {"product_id": product_id, "tenant_id": tenant_id, "cause": cause}
        ) or {"accepted": True, "state": "queued"}
        try:
            adapter.upsert(mirrored_record)
            adapter.upsert(mirrored_record)
            changed_picture_record = json.loads(json.dumps(mirrored_record, ensure_ascii=False))
            changed_picture_record["source_payloads"]["vehicle_pictures"]["payload"].append(
                {"pictureId": "new-sync-picture", "pictureUrl": "https://cdn.example.invalid/new.jpg"}
            )
            adapter.upsert(changed_picture_record)
        finally:
            host_adapter_module.enqueue_vehicle_image_index = original_enqueue  # type: ignore[assignment]
        assert_equal(len(queued), 2, "Dafengche image source changes must enqueue one derived index, while an unchanged sync must not")
        assert_equal(queued[0]["cause"], "dafengche_sync", "Dafengche sync must retain its distinct index trigger cause")
        customer_items = store.list_customer_evidence_items(
            shop_code="SHOP-001",
            policy=CustomerEvidencePolicy(max_age_seconds=None),
        )
        bound_item = next((item for item in customer_items if item.get("id") == mirrored_record.get("id")), None)
        assert_true(isinstance(bound_item, dict) and isinstance(bound_item.get("customer_evidence"), dict), "bound v2 item should use customer-evidence bridge")
        assert_true("source_payloads" not in json.dumps(bound_item, ensure_ascii=False), "bound compatibility record must not expose raw payload")
        adapter.append_audit({"type": "manual_vehicle_saved", "observed_at": NOW.isoformat(timespec="seconds")})
        assert_true(any((store.root / "dafengche_sync_audit").glob("*.json")), "host audit should be kept with product master")
    return {"name": "manual_vehicle_and_host_storage_adapter", "ok": True}


def check_legacy_facade_and_brain_input_contract() -> dict[str, Any]:
    legacy = {
        "schema_version": 1,
        "category_id": "products",
        "id": "legacy_car_001",
        "status": "active",
        "source": {"type": "test_fixture"},
        "data": {"name": "Legacy Vehicle", "price": 9.8, "inventory": 1, "aliases": ["legacy"]},
    }
    projected_legacy = customer_evidence_item(legacy, shop_code=None)
    assert_equal(projected_legacy, legacy, "legacy product read contract must remain unchanged")
    _repository, service = synced_service()
    evidence = service.list_customer_evidence(shop_code="SHOP-001")[0]
    brain_input = compact_product_item_for_brain_prompt(evidence, max_text_chars=180)
    assert_equal(brain_input["id"], evidence["id"], "Brain retains existing product id input")
    assert_equal(brain_input["name"], evidence["name"], "Brain retains existing product name input")
    assert_equal(brain_input["price"], 15.28, "Brain sees authorized public price through existing field")
    brain_text = json.dumps(brain_input, ensure_ascii=False)
    assert_true("vin" not in brain_text.lower() and "plate" not in brain_text.lower(), "Brain compact input must not contain raw identifiers")
    projected_item = customer_evidence_item(
        _repository.list_records()[0],
        shop_code="SHOP-001",
        policy=CustomerEvidencePolicy(max_age_seconds=None),
    )
    assert_true(isinstance(projected_item, dict), "bound record should produce bridge item")
    legacy_projection = project_legacy_record(_repository.list_records()[0])
    assert_true(isinstance(legacy_projection, dict), "portable core should offer a compatibility projection")
    assert_true("source_payloads" not in json.dumps(legacy_projection, ensure_ascii=False), "compatibility projection must not copy source payload")
    original_runtime = reply_evidence_builder_module.KnowledgeRuntime

    class FakeRuntime:
        def list_customer_evidence_items(self, category_id: str, *, shop_code: str | None = None) -> list[dict[str, Any]]:
            assert_equal(category_id, "products", "catalog must query products through evidence seam")
            assert_equal(shop_code, "SHOP-001", "catalog must forward explicit shop scope")
            return [projected_item]

    try:
        reply_evidence_builder_module.KnowledgeRuntime = FakeRuntime
        candidates = reply_evidence_builder_module.catalog_product_candidates("凯美瑞报价", limit=3, context={"shopCode": "SHOP-001"})
        alias_matches = reply_evidence_builder_module.authoritative_catalog_alias_matches(
            "那台凯美瑞的详细信息发我看看",
            limit=3,
            context={"shopCode": "SHOP-001"},
        )
    finally:
        reply_evidence_builder_module.KnowledgeRuntime = original_runtime
    assert_equal(candidates[0]["price"], 15.28, "catalog should retain public-price field through unchanged evidence output")
    assert_true("source_payloads" not in json.dumps(candidates, ensure_ascii=False), "catalog must never receive raw source payload")
    assert_equal(alias_matches[0]["id"], projected_item["id"], "explicit customer alias should retain authoritative product evidence")
    assert_true(alias_matches[0]["matched_aliases"], "alias routing result should include the matched visible alias")
    return {"name": "legacy_facade_and_brain_input_contract", "ok": True}


def check_source_markers_and_v1_to_v2_manual_migration() -> dict[str, Any]:
    legacy = {
        "schema_version": 1,
        "category_id": "products",
        "id": "chejin_legacy_camry_001",
        "status": "active",
        "source": {"type": "test_fixture"},
        "data": {
            "name": "Legacy Camry",
            "sku": "LEGACY-CAMRY",
            "category": "used_car",
            "aliases": ["camry", "凯美瑞"],
            "specs": "2021年上牌，4.8万公里",
            "price": 8.98,
            "unit": "台",
            "inventory": 1,
            "shipping_policy": "到店看车",
            "warranty_policy": "按门店政策",
            "reply_templates": {"quote": "legacy only"},
            "risk_rules": ["价格以到店确认为准"],
        },
    }
    migrated_at = NOW.isoformat(timespec="seconds")
    direct = build_manual_v2_record(legacy, batch_id="test_v1_to_v2", migrated_at=migrated_at)
    assert_equal(direct["source"]["type"], "manual", "legacy conversion must be a manual record")
    assert_equal(direct["source"]["marker"]["ingest_channel"], "legacy_v1_migration", "legacy conversion marker")
    assert_equal(direct["source"]["binding"]["state"], "unbound", "legacy conversion must not fabricate binding")
    detail = direct["source_payloads"]["vehicle_detail"]["payload"]
    assert_equal(detail["baseCarInfo"]["name"], "Legacy Camry", "known name should map to Dafengche-shaped field")
    assert_equal(detail["carPriceInfo"]["salePrice"], 8.98, "known public price should map to Dafengche-shaped field")
    assert_true("operationPhase" not in detail, "inventory must not be fabricated into an upstream operation phase")
    assert_equal(direct["extensions"]["compatibility"]["legacy_v1_record"], legacy, "complete v1 snapshot must be retained")

    with tempfile.TemporaryDirectory(prefix="chejin_v1_to_v2_") as temp_dir:
        store = ProductMasterStore(root=Path(temp_dir), tenant_id="chejin")
        saved_new = store.save_item(legacy)
        assert_true(saved_new.get("ok") is True, "generic manual fixture must save")
        saved_v2 = store.get_item("chejin_legacy_camry_001")
        assert_equal(saved_v2["schema_version"], 2, "all generic manual writes must enter V2 directly")
        assert_equal(saved_v2["source"]["type"], "manual", "generic manual input must become manual V2")
        assert_equal(saved_v2["source"]["marker"]["ingest_channel"], "test_fixture", "converted input must retain source marker")
        quarantined = {**legacy, "id": "quarantined_v1_camry_001"}
        write_json(store.item_path("quarantined_v1_camry_001"), quarantined)
        assert_true(store.get_item("quarantined_v1_camry_001") is None, "runtime must not read quarantined V1 records")
        dry_run = migrate_store(store, batch_id="test_v1_to_v2", apply=False, migrated_at=migrated_at)
        assert_equal(dry_run["candidate_count"], 1, "dry run should discover exactly one v1 item")
        assert_true(not (store.root / "migration_audit").exists(), "dry run must not write audit files")
        applied = migrate_store(store, batch_id="test_v1_to_v2", apply=True, migrated_at=migrated_at)
        assert_equal(applied["converted_ids"], ["quarantined_v1_camry_001"], "apply should replace the v1 record by id")
        raw_v2 = store.get_item("quarantined_v1_camry_001")
        assert_equal(raw_v2["schema_version"], 2, "raw store must now hold v2")
        assert_equal(raw_v2["source"]["marker"]["ingest_channel"], "legacy_v1_migration", "stored v2 marker")
        customer_view = store.get_customer_evidence_item("quarantined_v1_camry_001")
        assert_true("legacy_v1_migration" not in json.dumps(customer_view, ensure_ascii=False), "internal source marker must not enter customer evidence")
        compatibility = store.get_compatibility_item("quarantined_v1_camry_001")
        assert_equal(compatibility["data"], legacy["data"], "generic callers must retain every legacy data field")
        assert_true("source_payloads" not in json.dumps(compatibility, ensure_ascii=False), "compatibility facade must not leak v2 raw source payload")
        rerun = migrate_store(store, batch_id="test_v1_to_v2", apply=True, migrated_at=migrated_at)
        assert_equal(rerun["candidate_count"], 0, "migration must be idempotent")
        assert_true((store.root / "migration_audit" / "test_v1_to_v2.json").exists(), "apply must leave a migration audit report")
    return {"name": "source_markers_and_v1_to_v2_manual_migration", "ok": True}


def check_portable_core_and_rpa_forbidden_import_boundaries() -> dict[str, Any]:
    core_root = PROJECT_ROOT / "packages" / "dafengche_product_master"
    forbidden_core = (
        "from apps.wechat_ai_customer_service",
        "import apps.wechat_ai_customer_service",
        "from workflows",
        "import workflows",
        "from admin_backend",
        "import admin_backend",
        "from knowledge_paths",
        "import knowledge_paths",
        "from storage",
        "import storage",
    )
    for path in core_root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_core:
            assert_true(token not in text, f"portable core forbidden dependency {token}: {path.name}")
    rpa_paths = [
        PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "adapters" / "wechat_connector.py",
        PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "adapters" / "wechat_win32_ocr_sidecar.py",
        PROJECT_ROOT / "apps" / "wechat_ai_customer_service" / "workflows" / "approved_outbound_send.py",
    ]
    forbidden_rpa = ("dafengche_product_master", "ProductMasterStore", "KnowledgeRuntime", "reply_evidence_builder", "customer_service_brain")
    for path in rpa_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_rpa:
            assert_true(token not in text, f"RPA boundary violation {token}: {path.name}")
    return {"name": "portable_core_and_rpa_forbidden_import_boundaries", "ok": True}


def synced_service() -> tuple[InMemoryMirrorRepository, DafengcheProductMaster]:
    transport = FixtureTransport(
        {
            SHOP_API: load_fixture("shop.json"),
            CAR_IDS_API: load_fixture("car_ids_sale.json"),
            CAR_DETAIL_API: load_fixture("car_detail_car_1001.json"),
            CAR_PICTURES_API: load_fixture("car_pictures_car_1001.json"),
        }
    )
    client = DafengcheReadOnlyClient(
        credentials=DafengcheCredentials(app_key="test-app-key", app_secret="test-app-secret"),
        transport=transport,
        now_seconds=lambda: 1_784_000_000,
    )
    repository = InMemoryMirrorRepository()
    service = DafengcheProductMaster(repository=repository, client=client, now=lambda: NOW)
    service.sync(DafengcheSyncScope("app-001", "operator-001", "SHOP-001", ("sale",)))
    return repository, service


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
