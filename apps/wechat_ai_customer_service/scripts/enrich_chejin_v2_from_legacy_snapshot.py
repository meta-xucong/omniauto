"""Fill only directly evidenced Dafengche-shaped fields from a V1 snapshot.

This is a one-way historical migration aid for records created by
``migrate_chejin_v1_to_v2_manual.py``.  It never turns the preserved V1
snapshot into a runtime data source and it does not guess fields from a model
name.  Each value written to the V2 payload retains its exact V1 source path
and matching text in ``extensions.manual.field_provenance``.

The default mode is read-only and prints the complete proposed change set.
Use ``--apply`` only after reviewing that output.  Re-running after a
successful apply makes no changes: existing V2 values are never overwritten.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
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
DEFAULT_BATCH_ID = "chejin_v2_legacy_snapshot_enrichment_20260713"
LEGACY_INGEST_CHANNEL = "legacy_v1_migration"
ENRICHMENT_SOURCE = "legacy_v1_snapshot_enrichment"
PAYLOAD_PROVENANCE_PREFIX = "source_payloads.vehicle_detail.payload."

LICENSE_DATE_RE = re.compile(r"(?<!\d)(?P<year>20\d{2})年(?:(?P<month>\d{1,2})月)?上牌")
MILEAGE_RE = re.compile(r"表显\s*(?P<value>\d+(?:\.\d+)?)\s*万公里")
DISPLACEMENT_RE = re.compile(r"(?<![\d.])(?P<value>\d+(?:\.\d+)?\s*[TL])(?![A-Za-z0-9.])", re.IGNORECASE)
COLOR_RE = re.compile(r"(?:^|[，,、；;\s])(?P<value>[\u4e00-\u9fffA-Za-z0-9]{1,12})车漆")


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich migrated V2 Chejin vehicles from their preserved V1 snapshots.")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID, help="Tenant to process (default: chejin).")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID, help="Stable audit batch id for this enrichment.")
    parser.add_argument("--apply", action="store_true", help="Persist changes. Without this flag the script is read-only.")
    args = parser.parse_args()

    report = enrich_store(
        ProductMasterStore(tenant_id=str(args.tenant_id)),
        batch_id=str(args.batch_id),
        apply=bool(args.apply),
        enriched_at=utc_now(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


def enrich_store(
    store: ProductMasterStore,
    *,
    batch_id: str,
    apply: bool,
    enriched_at: str,
) -> dict[str, Any]:
    """Plan or persist a missing-only enrichment for historical V2 records."""

    planned_updates: list[dict[str, Any]] = []
    unchanged_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    failures: list[dict[str, Any]] = []
    field_counts: Counter[str] = Counter()
    retired_data_shadow_cleanup_ids: list[str] = []

    for record in store.list_items(include_archived=True):
        plan = plan_legacy_snapshot_enrichment(record, batch_id=batch_id, enriched_at=enriched_at)
        record_id = str(record.get("id") or "")
        if plan["state"] == "skipped":
            skipped.append({"id": record_id, "reason": str(plan["reason"])})
            continue
        if plan["state"] == "unchanged":
            unchanged_ids.append(record_id)
            continue

        fields = plan["fields"]
        removed_retired_data_shadow = bool(plan.get("removed_retired_data_shadow"))
        planned_updates.append({"id": record_id, "fields": fields, "removed_retired_data_shadow": removed_retired_data_shadow})
        field_counts.update(str(field["path"]) for field in fields)
        if removed_retired_data_shadow:
            retired_data_shadow_cleanup_ids.append(record_id)
        if not apply:
            continue
        saved = store.save_item(plan["record"])
        if not saved.get("ok"):
            failures.append({"id": record_id, "problems": copy.deepcopy(saved.get("problems") or saved.get("message") or saved)})

    report = {
        "ok": not failures,
        "tenant_id": store.tenant_id,
        "product_master_root": str(store.root),
        "batch_id": batch_id,
        "mode": "apply" if apply else "dry_run",
        "enriched_at": enriched_at,
        "policy": {
            "eligibility": "V2 manual records marked legacy_v1_migration with a preserved legacy_v1_record snapshot",
            "write_rule": "write only directly matched values into currently blank Dafengche-shaped fields",
            "source_order": {
                "registration_date": ["data.specs"],
                "mileage": ["data.specs"],
                "displacement": ["data.specs", "data.name"],
                "gearbox": ["data.name", "data.specs"],
                "exterior_color": ["data.specs"],
            },
            "never_inferred": [
                "brandName",
                "seriesName",
                "modelName",
                "vehicleCondition",
                "interiorColor",
                "carId",
                "shopCode",
                "VIN",
                "plate",
                "operationPhase",
                "photos",
            ],
            "does_not_overwrite_existing_v2_fields": True,
        },
        "records_with_planned_updates": len(planned_updates),
        "records_written": len(planned_updates) - len(failures) if apply else 0,
        "retired_data_shadow_cleanup_ids": retired_data_shadow_cleanup_ids,
        "unchanged_ids": unchanged_ids,
        "skipped": skipped,
        "field_counts": dict(sorted(field_counts.items())),
        "planned_updates": planned_updates,
        "failures": failures,
    }
    if apply:
        audit_dir = (store.root / "migration_audit").resolve()
        if store.root.resolve() not in audit_dir.parents:
            raise ValueError("migration audit path escapes product-master root")
        write_json(audit_dir / f"{batch_id}.json", report)
    return report


def plan_legacy_snapshot_enrichment(record: dict[str, Any], *, batch_id: str, enriched_at: str) -> dict[str, Any]:
    """Return a changed copy plus its evidence, without mutating ``record``."""

    if not _is_legacy_v1_migrated_manual_vehicle(record):
        return {"state": "skipped", "reason": "not_a_legacy_v1_migrated_manual_v2_vehicle"}
    data = _legacy_snapshot_data(record)
    if not data:
        return {"state": "skipped", "reason": "legacy_snapshot_data_missing"}

    candidates = extract_legacy_snapshot_candidates(data)
    result = copy.deepcopy(record)
    removed_retired_data_shadow = "data" in result
    # A V2 record may retain an empty V1-shaped shell from an earlier import.
    # It has no authority and is removed only after the compatibility snapshot
    # has already been verified above.
    result.pop("data", None)
    detail_snapshot = _mapping(_mapping(result.get("source_payloads")).get("vehicle_detail"))
    detail = _mapping(detail_snapshot.get("payload"))
    fields: list[dict[str, Any]] = []
    for path, candidate in candidates.items():
        if not _is_blank(_value_at(detail, path)):
            continue
        _set_value_at(detail, path, candidate["value"])
        fields.append({"path": path, **copy.deepcopy(candidate)})

    if not fields and not removed_retired_data_shadow:
        return {"state": "unchanged", "record": result, "fields": []}

    if fields:
        detail_snapshot["payload"] = detail
        detail_snapshot["content_hash"] = content_hash(detail)
        detail_snapshot["enriched_at"] = enriched_at
        payloads = _mapping(result.get("source_payloads"))
        payloads["vehicle_detail"] = detail_snapshot
        result["source_payloads"] = payloads

    extensions = _mapping(result.get("extensions"))
    manual = _mapping(extensions.get("manual"))
    provenance = _mapping(manual.get("field_provenance"))
    for field in fields:
        provenance[f"{PAYLOAD_PROVENANCE_PREFIX}{field['path']}"] = {
            "source": ENRICHMENT_SOURCE,
            "original_path": field["original_path"],
            "recorded_at": enriched_at,
            "evidence": field["evidence"],
        }
    manual["field_provenance"] = provenance
    extensions["manual"] = manual
    compatibility = _mapping(extensions.get("compatibility"))
    compatibility["legacy_snapshot_enrichment"] = {
        "batch_id": batch_id,
        "source": ENRICHMENT_SOURCE,
        "enriched_at": enriched_at,
        "field_count": len(fields),
        "retired_data_shadow_removed": removed_retired_data_shadow,
    }
    extensions["compatibility"] = compatibility
    result["extensions"] = extensions

    metadata = _mapping(result.get("metadata"))
    metadata["updated_at"] = enriched_at
    metadata["legacy_snapshot_enriched_at"] = enriched_at
    metadata["legacy_snapshot_enrichment_batch"] = batch_id
    result["metadata"] = metadata
    return {
        "state": "planned",
        "record": result,
        "fields": fields,
        "removed_retired_data_shadow": removed_retired_data_shadow,
    }


def extract_legacy_snapshot_candidates(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract only values with an explicit textual counterpart in the V1 data."""

    specs = _text(data.get("specs"))
    name = _text(data.get("name"))
    result: dict[str, dict[str, Any]] = {}

    date_match = LICENSE_DATE_RE.search(specs)
    if date_match:
        month = date_match.group("month")
        if month is None or 1 <= int(month) <= 12:
            value = date_match.group("year") if month is None else f"{date_match.group('year')}-{int(month):02d}"
            _add_candidate(result, "baseCarInfo.firstLicensePlateDate", value, "data.specs", date_match.group(0))

    mileage_match = MILEAGE_RE.search(specs)
    if mileage_match:
        _add_candidate(result, "baseCarInfo.mileage", float(mileage_match.group("value")), "data.specs", mileage_match.group(0))

    displacement_match, displacement_path = _first_match(DISPLACEMENT_RE, ((specs, "data.specs"), (name, "data.name")))
    if displacement_match:
        _add_candidate(
            result,
            "carModelParam.displacement",
            displacement_match.group("value").upper().replace(" ", ""),
            displacement_path,
            displacement_match.group(0),
        )

    gearbox_value, gearbox_path, gearbox_evidence = _gearbox_from_legacy_text(name, specs)
    if gearbox_value:
        _add_candidate(result, "carModelParam.gearbox", gearbox_value, gearbox_path, gearbox_evidence)

    color_match = COLOR_RE.search(specs)
    if color_match:
        _add_candidate(result, "baseCarInfo.exteriorColor", color_match.group("value"), "data.specs", color_match.group(0).strip("，,、；; "))
    return result


def _gearbox_from_legacy_text(name: str, specs: str) -> tuple[str | None, str, str]:
    """Prefer a title's explicit subtype, then a specification's explicit wording."""

    for text, path in ((name, "data.name"), (specs, "data.specs")):
        upper = text.upper()
        if "CVT" in upper:
            return "CVT", path, _gearbox_evidence(text, "CVT")
        if "DSG" in upper:
            return "DSG", path, _gearbox_evidence(text, "DSG")
        if "双离合" in text:
            return "双离合", path, _gearbox_evidence(text, "双离合")
    for text, path in ((specs, "data.specs"), (name, "data.name")):
        if "自动挡" in text or "自动两驱" in text or "自动四驱" in text:
            return "自动", path, _gearbox_evidence(text, "自动")
    return None, "", ""


def _gearbox_evidence(text: str, token: str) -> str:
    index = text.upper().find(token.upper())
    if index < 0:
        return token
    return text[max(0, index - 8) : index + len(token) + 8]


def _first_match(pattern: re.Pattern[str], sources: tuple[tuple[str, str], ...]) -> tuple[re.Match[str] | None, str]:
    for text, path in sources:
        match = pattern.search(text)
        if match:
            return match, path
    return None, ""


def _add_candidate(result: dict[str, dict[str, Any]], path: str, value: Any, original_path: str, evidence: str) -> None:
    if path not in result:
        result[path] = {"value": value, "original_path": original_path, "evidence": evidence}


def _is_legacy_v1_migrated_manual_vehicle(record: dict[str, Any]) -> bool:
    source = _mapping(record.get("source"))
    marker = _mapping(source.get("marker"))
    return (
        int(record.get("schema_version") or 1) >= 2
        and str(source.get("type") or "") == "manual"
        and str(marker.get("ingest_channel") or "") == LEGACY_INGEST_CHANNEL
    )


def _legacy_snapshot_data(record: dict[str, Any]) -> dict[str, Any]:
    extensions = _mapping(record.get("extensions"))
    compatibility = _mapping(extensions.get("compatibility"))
    snapshot = _mapping(compatibility.get("legacy_v1_record"))
    return _mapping(snapshot.get("data"))


def _mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
