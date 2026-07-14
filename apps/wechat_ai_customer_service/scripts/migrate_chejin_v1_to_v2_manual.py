"""Migrate Chejin's generic v1 vehicle records into auditable manual v2 records.

The conversion is deliberately conservative: it preserves the exact original
record as a compatibility snapshot and only maps the generic fields whose
meaning is known.  It does not invent a Dafengche ``carId``, shop binding, VIN,
plate, business phase, or API provenance.

Run with ``--apply`` only after reviewing the default dry-run report.  Repeated
runs are idempotent: records already at v2 are skipped.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.product_master import (  # noqa: E402
    ProductMasterStore,
    convert_generic_product_to_manual_v2,
    write_json,
)


DEFAULT_TENANT_ID = "chejin"
DEFAULT_BATCH_ID = "chejin_v1_to_v2_20260713"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert one tenant's v1 vehicle records into v2 manual vehicle records.")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID, help="Tenant to convert (default: chejin).")
    parser.add_argument("--batch-id", default=DEFAULT_BATCH_ID, help="Stable migration batch id recorded on every converted item.")
    parser.add_argument("--apply", action="store_true", help="Write the conversion. Without this flag the script is read-only.")
    args = parser.parse_args()

    store = ProductMasterStore(tenant_id=str(args.tenant_id))
    report = migrate_store(
        store,
        batch_id=str(args.batch_id),
        apply=bool(args.apply),
        migrated_at=utc_now(),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


def migrate_store(
    store: ProductMasterStore,
    *,
    batch_id: str,
    apply: bool,
    migrated_at: str,
) -> dict[str, Any]:
    """Convert only v1 records and optionally persist an auditable manifest."""

    candidates: list[dict[str, Any]] = []
    skipped_v2: list[str] = []
    for item in store.list_v1_items_for_migration(include_archived=True):
        item_id = str(item.get("id") or "")
        candidates.append(copy.deepcopy(item))
    for item in store.list_items(include_archived=True):
        skipped_v2.append(str(item.get("id") or ""))

    converted: list[str] = []
    failures: list[dict[str, Any]] = []
    for legacy in candidates:
        record = build_manual_v2_record(legacy, batch_id=batch_id, migrated_at=migrated_at)
        if not apply:
            converted.append(str(record["id"]))
            continue
        result = store.save_item(record)
        if result.get("ok"):
            converted.append(str(record["id"]))
        else:
            failures.append({"id": record["id"], "problems": copy.deepcopy(result.get("problems") or result.get("message") or result)})

    report = {
        "ok": not failures,
        "tenant_id": store.tenant_id,
        "product_master_root": str(store.root),
        "batch_id": batch_id,
        "mode": "apply" if apply else "dry_run",
        "migrated_at": migrated_at,
        "candidate_count": len(candidates),
        "converted_ids": converted,
        "already_v2_ids": skipped_v2,
        "failures": failures,
        "mapping_policy": {
            "source_type": "manual",
            "source_marker": "legacy_v1_migration",
            "binding": "unbound",
            "preserved_legacy_snapshot": True,
            "never_fabricated": ["shopCode", "carId", "VIN", "plate", "operationPhase", "dafengche_api_provenance"],
        },
    }
    if apply:
        audit_dir = (store.root / "migration_audit").resolve()
        if store.root.resolve() not in audit_dir.parents:
            raise ValueError("migration audit path escapes product-master root")
        write_json(audit_dir / f"{batch_id}.json", report)
    return report


def build_manual_v2_record(legacy: dict[str, Any], *, batch_id: str, migrated_at: str) -> dict[str, Any]:
    """Compatibility wrapper around the shared V1-input-to-V2 converter."""

    return convert_generic_product_to_manual_v2(
        legacy,
        observed_at=migrated_at,
        ingest_channel="legacy_v1_migration",
        migration_batch=batch_id,
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
