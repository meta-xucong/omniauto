"""Populate missing Chejin V2 vehicle fields with explicitly marked test data.

This tool exists only to verify that the WeChat customer-service evidence path
can read the complete V2 field surface.  It never overwrites a real value,
never fabricates a Dafengche binding, and records ``test_fixture_fill`` on
every value it creates.  Run with ``--remove`` to delete only values created
by this tool later.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.product_master import ProductMasterStore, write_json  # noqa: E402
from packages.dafengche_product_master.service import content_hash  # noqa: E402


DEFAULT_TENANT_ID = "chejin"
DEFAULT_BATCH_ID = "chejin_v2_wechat_recognition_test_fields_20260713"
TEST_FILL_SOURCE = "test_fixture_fill"
PAYLOAD_PROVENANCE_PREFIX = "source_payloads.vehicle_detail.payload."


def main() -> int:
    parser = argparse.ArgumentParser(description="Fill or remove explicitly marked V2 vehicle test fields.")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID, help="Tenant to process (default: chejin).")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID, help="Stable test batch id for audit and cleanup.")
    parser.add_argument("--remove", action="store_true", help="Remove only values created by this test-fill source.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag the script is read-only.")
    args = parser.parse_args()
    report = fill_store(
        ProductMasterStore(tenant_id=str(args.tenant_id)),
        batch_id=str(args.batch_id),
        apply=bool(args.apply),
        remove=bool(args.remove),
        observed_at=utc_now(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


def fill_store(
    store: ProductMasterStore,
    *,
    batch_id: str,
    apply: bool,
    remove: bool,
    observed_at: str,
) -> dict[str, Any]:
    updated: list[dict[str, Any]] = []
    unchanged_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    failures: list[dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    candidates = sorted(store.list_items(include_archived=True), key=lambda item: str(item.get("id") or ""))
    for ordinal, record in enumerate(candidates, start=1):
        plan = plan_vehicle_test_field_fill(
            record,
            ordinal=ordinal,
            batch_id=batch_id,
            observed_at=observed_at,
            remove=remove,
        )
        record_id = str(record.get("id") or "")
        if plan["state"] == "skipped":
            skipped.append({"id": record_id, "reason": str(plan["reason"])})
            continue
        if plan["state"] == "unchanged":
            unchanged_ids.append(record_id)
            continue
        fields = plan["fields"]
        updated.append({"id": record_id, "fields": fields})
        field_counts.update(str(field["path"]) for field in fields)
        if not apply:
            continue
        saved = store.save_item(plan["record"])
        if not saved.get("ok"):
            failures.append({"id": record_id, "problems": copy.deepcopy(saved.get("problems") or saved.get("message") or saved)})

    action = "remove" if remove else "fill_missing"
    report = {
        "ok": not failures,
        "tenant_id": store.tenant_id,
        "product_master_root": str(store.root),
        "batch_id": batch_id,
        "mode": "apply" if apply else "dry_run",
        "action": action,
        "observed_at": observed_at,
        "policy": {
            "test_only": True,
            "source": TEST_FILL_SOURCE,
            "writes_only_to_blank_manual_v2_fields": not remove,
            "removes_only_values_with_matching_field_provenance": remove,
            "never_touches": ["source.binding", "carId", "shopCode", "VIN", "plate", "photos", "existing_v2_values"],
        },
        "records_with_planned_updates": len(updated),
        "records_written": len(updated) - len(failures) if apply else 0,
        "field_counts": dict(sorted(field_counts.items())),
        "updated": updated,
        "unchanged_ids": unchanged_ids,
        "skipped": skipped,
        "failures": failures,
    }
    if apply:
        audit_dir = (store.root / "migration_audit").resolve()
        if store.root.resolve() not in audit_dir.parents:
            raise ValueError("test-field audit path escapes product-master root")
        write_json(audit_dir / f"{batch_id}_{action}.json", report)
    return report


def plan_vehicle_test_field_fill(
    record: dict[str, Any],
    *,
    ordinal: int,
    batch_id: str,
    observed_at: str,
    remove: bool,
) -> dict[str, Any]:
    """Return a changed V2 manual record without mutating the supplied object."""

    source = _mapping(record.get("source"))
    if int(record.get("schema_version") or 1) < 2 or str(source.get("type") or "") != "manual":
        return {"state": "skipped", "reason": "not_a_manual_v2_vehicle"}
    result = copy.deepcopy(record)
    payloads = _mapping(result.get("source_payloads"))
    detail_snapshot = _mapping(payloads.get("vehicle_detail"))
    detail = _mapping(detail_snapshot.get("payload"))
    extensions = _mapping(result.get("extensions"))
    manual = _mapping(extensions.get("manual"))
    provenance = _mapping(manual.get("field_provenance"))
    fields: list[dict[str, Any]] = []

    if remove:
        for full_path, entry in list(provenance.items()):
            if not isinstance(entry, dict) or str(entry.get("source") or "") != TEST_FILL_SOURCE:
                continue
            if not full_path.startswith(PAYLOAD_PROVENANCE_PREFIX):
                continue
            path = full_path.removeprefix(PAYLOAD_PROVENANCE_PREFIX)
            if _remove_value_at(detail, path):
                fields.append({"path": path, "action": "removed_test_value"})
            provenance.pop(full_path, None)
    else:
        for path, value in test_vehicle_values(ordinal).items():
            if not _is_blank(_value_at(detail, path)):
                continue
            _set_value_at(detail, path, value)
            provenance[f"{PAYLOAD_PROVENANCE_PREFIX}{path}"] = {
                "source": TEST_FILL_SOURCE,
                "recorded_at": observed_at,
                "batch_id": batch_id,
                "test_only": True,
            }
            fields.append({"path": path, "value": copy.deepcopy(value), "action": "filled_test_value"})

    if not fields:
        return {"state": "unchanged", "record": result, "fields": []}

    detail_snapshot["payload"] = detail
    detail_snapshot["content_hash"] = content_hash(detail)
    detail_snapshot["test_filled_at"] = observed_at if not remove else detail_snapshot.get("test_filled_at")
    payloads["vehicle_detail"] = detail_snapshot
    result["source_payloads"] = payloads
    manual["field_provenance"] = provenance
    test_marker = _mapping(manual.get("test_fixture"))
    if remove:
        test_marker["last_removed_at"] = observed_at
    else:
        test_marker.update({"enabled": True, "batch_id": batch_id, "filled_at": observed_at, "purpose": "wechat_customer_service_field_recognition"})
    manual["test_fixture"] = test_marker
    extensions["manual"] = manual
    result["extensions"] = extensions
    metadata = _mapping(result.get("metadata"))
    metadata["updated_at"] = observed_at
    metadata["test_fixture_last_action"] = "removed" if remove else "filled"
    metadata["test_fixture_batch"] = batch_id
    result["metadata"] = metadata
    return {"state": "planned", "record": result, "fields": fields}


def test_vehicle_values(ordinal: int) -> dict[str, Any]:
    """Return visible, unmistakably synthetic values for one vehicle row."""

    code = f"{ordinal:02d}"
    base_price = round(10 + ordinal * 0.37, 2)
    return {
        "operationPhase": "TEST_SALE",
        "baseCarInfo.carName": f"测试车辆-{code}",
        "baseCarInfo.brandName": f"测试品牌-{code}",
        "baseCarInfo.seriesName": f"测试车系-{code}",
        "baseCarInfo.modelName": f"测试车型-{code}",
        "baseCarInfo.firstLicensePlateDate": "2022-01",
        "baseCarInfo.mileage": round(1 + ordinal * 0.1, 1),
        "baseCarInfo.vehicleCondition": "测试车况：良好",
        "baseCarInfo.exteriorColor": "测试深灰色",
        "baseCarInfo.color": "测试深灰色",
        "baseCarInfo.interiorColor": "测试黑色",
        "carModelParam.gearbox": "测试自动",
        "carModelParam.gearBox": "测试自动",
        "carModelParam.displacement": "测试动力",
        "carPriceInfo.salePrice": base_price,
        "carPriceInfo.purchasePrice": round(base_price - 2, 2),
        "carPriceInfo.salesPrice": base_price,
        "carPriceInfo.managerPrice": round(base_price - 0.5, 2),
        "carPriceInfo.wholesalePrice": round(base_price - 1, 2),
        "carLicenseInfo.licenseStatus": "测试手续正常",
    }


def _mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _value_at(value: Any, path: str) -> Any:
    current = value
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _set_value_at(value: dict[str, Any], path: str, replacement: Any) -> None:
    current = value
    parts = path.split(".")
    for key in parts[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[parts[-1]] = copy.deepcopy(replacement)


def _remove_value_at(value: dict[str, Any], path: str) -> bool:
    current = value
    parts = path.split(".")
    for key in parts[:-1]:
        if not isinstance(current, dict) or not isinstance(current.get(key), dict):
            return False
        current = current[key]
    if not isinstance(current, dict) or parts[-1] not in current:
        return False
    current.pop(parts[-1], None)
    return True


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
