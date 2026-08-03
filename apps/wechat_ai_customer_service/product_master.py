"""Tenant product-master storage.

Product master data is the authoritative source for product facts such as
price, inventory, SKU, specs, and availability. It is intentionally separate
from formal business knowledge so RAG/candidate promotion cannot mutate product
facts through the generic knowledge path.
"""

from __future__ import annotations

import json
import os
import re
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import (
    LEGACY_KNOWLEDGE_BASE_ROOT,
    active_tenant_id,
    tenant_knowledge_base_root,
    tenant_product_master_root,
)
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config
from packages.dafengche_product_master.projection import (
    CustomerEvidencePolicy,
    project_customer_evidence,
    project_legacy_record,
)
from packages.dafengche_product_master.service import create_manual_vehicle


PRODUCT_MASTER_CATEGORY_ID = "products"
PRODUCT_MASTER_DB_LAYER = "product_master"
LEGACY_PRODUCT_DB_LAYER = "tenant"
SAFE_PRODUCT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


DEFAULT_PRODUCT_MASTER_SCHEMA: dict[str, Any] = {
    "schema_version": 2,
    "category_id": PRODUCT_MASTER_CATEGORY_ID,
    "display_name": "商品主数据",
    "description": "商品事实权威源：商品、车型、价格、库存、规格、物流、售后和禁用承诺。",
    "item_title_field": "name",
    "item_subtitle_field": "sku",
    "fields": [
        {"id": "name", "label": "商品名称", "type": "short_text", "required": True, "searchable": True, "form_order": 10},
        {"id": "sku", "label": "型号/SKU", "type": "short_text", "required": False, "searchable": True, "form_order": 20},
        {"id": "category", "label": "商品类目", "type": "short_text", "required": False, "searchable": True, "form_order": 30},
        {"id": "aliases", "label": "客户常用叫法", "type": "tags", "required": False, "searchable": True, "form_order": 40},
        {"id": "specs", "label": "规格参数", "type": "long_text", "required": False, "searchable": True, "form_order": 50},
        {"id": "price", "label": "基础价格", "type": "money", "required": False, "searchable": False, "form_order": 60},
        {"id": "unit", "label": "计价单位", "type": "short_text", "required": False, "searchable": False, "form_order": 70},
        {
            "id": "price_tiers",
            "label": "阶梯价格",
            "type": "table",
            "required": False,
            "form_order": 80,
            "columns": [
                {"id": "min_quantity", "label": "起订量", "type": "number"},
                {"id": "unit_price", "label": "单价", "type": "money"},
            ],
        },
        {"id": "inventory", "label": "库存", "type": "number", "required": False, "form_order": 90},
        {"id": "shipping_policy", "label": "发货/物流", "type": "long_text", "required": False, "searchable": True, "form_order": 100},
        {"id": "warranty_policy", "label": "售后/保修", "type": "long_text", "required": False, "searchable": True, "form_order": 110},
        {"id": "reply_templates", "label": "标准回复模板", "type": "object", "required": False, "form_order": 120},
        {"id": "risk_rules", "label": "风险与禁用承诺", "type": "tags", "required": False, "searchable": True, "form_order": 130},
        {"id": "additional_details", "label": "补充信息", "type": "object", "required": False, "searchable": True, "form_order": 140},
    ],
    "validation": {
        "unique_fields": ["id"],
        "unique_tag_fields": ["aliases"],
        "required_for_auto_reply": ["name"],
    },
}

DEFAULT_PRODUCT_MASTER_RESOLVER: dict[str, Any] = {
    "schema_version": 2,
    "category_id": PRODUCT_MASTER_CATEGORY_ID,
    "match_fields": ["name", "sku", "category", "aliases", "specs", "additional_details"],
    "intent_fields": ["reply_templates", "risk_rules", "shipping_policy", "warranty_policy", "additional_details"],
    "risk_fields": ["risk_rules"],
    "reply_fields": [
        "name",
        "sku",
        "category",
        "price",
        "unit",
        "price_tiers",
        "inventory",
        "shipping_policy",
        "warranty_policy",
        "reply_templates",
        "additional_details",
    ],
    "minimum_confidence": 0.45,
    "default_action": "answer_from_product_master",
}


def product_master_category_record() -> dict[str, Any]:
    return {
        "id": PRODUCT_MASTER_CATEGORY_ID,
        "name": "商品主数据",
        "kind": "product_master",
        "path": "product_master",
        "enabled": True,
        "participates_in_reply": True,
        "participates_in_learning": False,
        "participates_in_diagnostics": True,
        "scope": "product_master",
        "authority": "manual_product_master_only",
        "sort_order": 10,
    }


class ProductMasterStore:
    """Read/write facade for V2 product-master records.

    The public facade remains stable for existing callers, but V1 is no longer
    a persisted or runtime product format.  A legacy-shaped manual form input
    is converted at the write boundary into a V2 manual vehicle record.
    """

    def __init__(self, *, tenant_id: str | None = None, root: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.root = (root or tenant_product_master_root(self.tenant_id)).resolve()
        self.items_dir = self.root / "items"

    @property
    def schema_path(self) -> Path:
        return self.root / "schema.json"

    @property
    def resolver_path(self) -> Path:
        return self.root / "resolver.json"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def ensure_structure(self) -> None:
        self.items_dir.mkdir(parents=True, exist_ok=True)
        changed = False
        if not self.schema_path.exists():
            write_json(self.schema_path, DEFAULT_PRODUCT_MASTER_SCHEMA)
            changed = True
        if not self.resolver_path.exists():
            write_json(self.resolver_path, DEFAULT_PRODUCT_MASTER_RESOLVER)
            changed = True
        if changed or self._manifest_needs_refresh():
            self.write_manifest()

    def ensure_v2_contract(self) -> None:
        """Upgrade the local schema/resolver metadata without re-enabling V1."""

        self.ensure_structure()
        schema = read_json(self.schema_path, default=DEFAULT_PRODUCT_MASTER_SCHEMA)
        if isinstance(schema, dict) and int(schema.get("schema_version") or 1) < 2:
            upgraded_schema = deepcopy(schema)
            upgraded_schema["schema_version"] = 2
            upgraded_schema["record_storage_contract"] = "dafengche_product_master_v2"
            write_json(self.schema_path, upgraded_schema)
        resolver = read_json(self.resolver_path, default=DEFAULT_PRODUCT_MASTER_RESOLVER)
        if isinstance(resolver, dict) and int(resolver.get("schema_version") or 1) < 2:
            upgraded_resolver = deepcopy(resolver)
            upgraded_resolver["schema_version"] = 2
            upgraded_resolver["record_storage_contract"] = "dafengche_product_master_v2"
            write_json(self.resolver_path, upgraded_resolver)
        self.write_manifest()

    def load_schema(self) -> dict[str, Any]:
        self.ensure_structure()
        return read_json(self.schema_path, default=DEFAULT_PRODUCT_MASTER_SCHEMA)

    def load_resolver(self) -> dict[str, Any]:
        self.ensure_structure()
        return read_json(self.resolver_path, default=DEFAULT_PRODUCT_MASTER_RESOLVER)

    def list_items(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        db_items = self._list_db_items(include_archived=include_archived)
        if db_items:
            return db_items
        self.ensure_structure()
        return [
            item
            for item in self._list_file_items(self.items_dir, include_archived=include_archived)
            if is_v2_product_item(item)
        ]

    def get_item(self, product_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        validate_product_id(product_id)
        for item in self.list_items(include_archived=include_archived):
            if str(item.get("id") or "") == product_id:
                if not include_archived and str(item.get("status") or "active") == "archived":
                    return None
                return item
        return None

    def list_compatibility_items(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        """Return the stable v1-shaped view required by existing generic callers.

        Administrative and sync callers continue to use :meth:`list_items` and
        therefore see the exact v2 source mirror.  This method is deliberately
        a separate read facade so moving a record to v2 cannot make an existing
        consumer parse Dafengche source payloads.
        """

        items: list[dict[str, Any]] = []
        for item in self.list_items(include_archived=include_archived):
            projected = compatibility_product_item(item)
            if projected is not None:
                items.append(projected)
        return items

    def get_compatibility_item(self, product_id: str, *, include_archived: bool = False) -> dict[str, Any] | None:
        item = self.get_item(product_id, include_archived=include_archived)
        return compatibility_product_item(item) if item else None

    def list_customer_evidence_items(
        self,
        *,
        shop_code: str | None = None,
        policy: CustomerEvidencePolicy | None = None,
    ) -> list[dict[str, Any]]:
        """Return customer-safe product records without exposing source payloads.

        Only V2 Dafengche/manual records are eligible. They are projected by
        the portable product-master core and only enter this result after scope,
        field-policy, and freshness checks.
        """

        items: list[dict[str, Any]] = []
        for item in self.list_items():
            evidence_item = customer_evidence_item(item, shop_code=shop_code, policy=policy)
            if evidence_item is not None:
                items.append(evidence_item)
        return items

    def get_customer_evidence_item(
        self,
        product_id: str,
        *,
        shop_code: str | None = None,
        policy: CustomerEvidencePolicy | None = None,
    ) -> dict[str, Any] | None:
        item = self.get_item(product_id)
        return customer_evidence_item(item, shop_code=shop_code, policy=policy) if item else None

    def save_item(self, item: dict[str, Any]) -> dict[str, Any]:
        self.ensure_v2_contract()
        normalized = normalize_product_item(item)
        validation = validate_product_item(normalized, self.load_schema())
        if not validation["ok"]:
            return validation

        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.upsert_knowledge_item(self.tenant_id, PRODUCT_MASTER_DB_LAYER, PRODUCT_MASTER_CATEGORY_ID, normalized)
            if not config.mirror_files:
                return {"ok": True, "item": normalized}

        self.ensure_structure()
        path = self.item_path(str(normalized.get("id") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json(path, normalized)
        self.write_manifest()
        return {"ok": True, "item": normalized}

    def _save_items_batch_atomic(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Internal batch write used by deterministic importers.

        The existing public ``save_item`` contract remains unchanged.  This
        batch seam validates all records first, writes PostgreSQL records in a
        single transaction when the DB backend is active, and treats file
        mirrors as post-commit replicas in DB mode.
        """

        self.ensure_v2_contract()
        schema = self.load_schema()
        normalized_items: list[dict[str, Any]] = []
        problems: list[str] = []
        for index, item in enumerate(items, start=1):
            normalized = normalize_product_item(item)
            validation = validate_product_item(normalized, schema)
            if not validation["ok"]:
                item_id = str(normalized.get("id") or f"#{index}")
                for problem in validation.get("problems") or []:
                    problems.append(f"{item_id}: {problem}")
            normalized_items.append(normalized)
        seen_ids: set[str] = set()
        for normalized in normalized_items:
            item_id = str(normalized.get("id") or "")
            if item_id in seen_ids:
                problems.append(f"{item_id}: duplicate item id in batch")
            seen_ids.add(item_id)
        if problems:
            return {"ok": False, "problems": problems}

        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.upsert_knowledge_items_atomic(
                self.tenant_id,
                PRODUCT_MASTER_DB_LAYER,
                PRODUCT_MASTER_CATEGORY_ID,
                normalized_items,
            )
            mirror = {"ok": True, "mode": "not_requested"}
            if config.mirror_files:
                mirror = self._mirror_batch_files_after_db_commit(normalized_items)
            return {
                "ok": True,
                "items": normalized_items,
                "count": len(normalized_items),
                "storage": "postgres",
                "mirror_files": mirror,
            }

        return self._save_file_batch_atomic(normalized_items)

    def archive_item(self, product_id: str) -> dict[str, Any]:
        item = self.get_item(product_id, include_archived=True)
        if not item:
            return {"ok": False, "message": f"item not found: {PRODUCT_MASTER_CATEGORY_ID}/{product_id}"}
        item["status"] = "archived"
        item.setdefault("metadata", {})["updated_at"] = now()
        return self.save_item(item)

    def migrate_from_legacy(self, *, overwrite: bool = False) -> dict[str, Any]:
        """Explicitly convert quarantined V1 records into V2 manual vehicles.

        This is a migration-only reader.  Normal runtime reads never fall back
        to V1 files or the old knowledge database layer.
        """

        self.ensure_v2_contract()
        copied = []
        skipped = []
        for item in self._legacy_items_for_migration(include_archived=True):
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            target = self.item_path(item_id)
            existing = read_json(target, default=None)
            if isinstance(existing, dict) and is_v2_product_item(existing) and not overwrite:
                skipped.append(item_id)
                continue
            item = convert_generic_product_to_manual_v2(
                item,
                ingest_channel="legacy_v1_migration",
                migration_batch="product_master_legacy_v1_to_v2",
            )
            result = self.save_item(item)
            if result.get("ok"):
                copied.append(item_id)
            else:
                skipped.append(item_id)
        self.write_manifest(extra={"legacy_migrated_count": len(copied), "legacy_skipped_count": len(skipped)})
        return {"ok": True, "copied": copied, "skipped": skipped, "count": len(copied)}

    def list_v1_items_for_migration(self, *, include_archived: bool = True) -> list[dict[str, Any]]:
        """Return quarantined V1 records for an explicit migration tool only."""

        return [deepcopy(item) for item in self._legacy_items_for_migration(include_archived=include_archived)]

    def item_path(self, product_id: str) -> Path:
        validate_product_id(product_id)
        root = self.items_dir.resolve()
        path = (root / f"{product_id}.json").resolve()
        if root not in path.parents:
            raise ValueError(f"product path escapes product master root: {product_id}")
        return path

    def _save_file_batch_atomic(self, normalized_items: list[dict[str, Any]]) -> dict[str, Any]:
        snapshots = self._file_batch_snapshots(normalized_items)
        try:
            self.ensure_structure()
            for item in normalized_items:
                path = self.item_path(str(item.get("id") or ""))
                path.parent.mkdir(parents=True, exist_ok=True)
                write_json(path, item)
            self.write_manifest()
        except Exception:
            self._restore_file_batch_snapshots(snapshots)
            raise
        return {
            "ok": True,
            "items": normalized_items,
            "count": len(normalized_items),
            "storage": "files",
            "mirror_files": {"ok": True, "mode": "primary"},
        }

    def _mirror_batch_files_after_db_commit(self, normalized_items: list[dict[str, Any]]) -> dict[str, Any]:
        failed_ids: list[str] = []
        messages: list[str] = []
        try:
            self.ensure_structure()
            for item in normalized_items:
                item_id = str(item.get("id") or "")
                try:
                    path = self.item_path(item_id)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(path, item)
                except Exception as exc:  # noqa: BLE001 - continue collecting all failed mirror ids.
                    failed_ids.append(item_id)
                    messages.append(f"{item_id}: {exc}")
            if failed_ids:
                return {
                    "ok": False,
                    "mode": "post_commit_replica",
                    "reason": "mirror_files_failed",
                    "failed_ids": failed_ids,
                    "message": "; ".join(messages),
                }
            self.write_manifest()
        except Exception as exc:  # noqa: BLE001 - DB transaction is already committed; expose mirror status.
            return {
                "ok": False,
                "mode": "post_commit_replica",
                "reason": "mirror_files_failed",
                "failed_ids": [str(item.get("id") or "") for item in normalized_items],
                "message": str(exc),
            }
        return {"ok": True, "mode": "post_commit_replica"}

    def _file_batch_snapshots(self, normalized_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = []
        for item in normalized_items:
            path = self.item_path(str(item.get("id") or ""))
            snapshots.append({"path": path, "file_bytes": path.read_bytes() if path.exists() else None})
        return snapshots

    def _restore_file_batch_snapshots(self, snapshots: list[dict[str, Any]]) -> None:
        for snapshot in reversed(snapshots):
            path = snapshot["path"]
            file_bytes = snapshot.get("file_bytes")
            if file_bytes is None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(file_bytes)

    def write_manifest(self, extra: dict[str, Any] | None = None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 2,
            "authority": "product_master",
            "category_id": PRODUCT_MASTER_CATEGORY_ID,
            "tenant_id": self.tenant_id,
            "updated_at": now(),
            "items_path": "items",
            "compatibility": {
                "legacy_read_fallback": False,
                "legacy_items_require_explicit_migration": True,
                "new_writes_to_legacy": False,
                "v1_form_write_adapter": "manual_v2",
            },
        }
        if extra:
            payload.update(extra)
        write_json(self.manifest_path, payload)

    def _manifest_needs_refresh(self) -> bool:
        payload = read_json(self.manifest_path, default=None)
        if not isinstance(payload, dict):
            return True
        compatibility = payload.get("compatibility") if isinstance(payload.get("compatibility"), dict) else {}
        expected = {
            "schema_version": 2,
            "authority": "product_master",
            "category_id": PRODUCT_MASTER_CATEGORY_ID,
            "tenant_id": self.tenant_id,
            "items_path": "items",
        }
        for key, value in expected.items():
            if payload.get(key) != value:
                return True
        return (
            compatibility.get("legacy_read_fallback") is not False
            or compatibility.get("legacy_items_require_explicit_migration") is not True
            or compatibility.get("new_writes_to_legacy") is not False
            or compatibility.get("v1_form_write_adapter") != "manual_v2"
        )

    def _list_db_items(self, *, include_archived: bool) -> list[dict[str, Any]]:
        db = postgres_store(self.tenant_id)
        if not db:
            return []
        items = db.list_knowledge_items(
            self.tenant_id,
            layer=PRODUCT_MASTER_DB_LAYER,
            category_id=PRODUCT_MASTER_CATEGORY_ID,
            include_archived=include_archived,
        )
        return [item for item in items if is_v2_product_item(item)]

    def _legacy_root_candidates(self) -> list[Path]:
        tenant_root = tenant_knowledge_base_root(self.tenant_id) / PRODUCT_MASTER_CATEGORY_ID
        candidates = [tenant_root]
        if self.tenant_id == "default":
            candidates.append(LEGACY_KNOWLEDGE_BASE_ROOT / PRODUCT_MASTER_CATEGORY_ID)
        return candidates

    def _legacy_schema(self) -> dict[str, Any] | None:
        for root in self._legacy_root_candidates():
            payload = read_json(root / "schema.json", default=None)
            if isinstance(payload, dict):
                return payload
        return None

    def _legacy_resolver(self) -> dict[str, Any] | None:
        for root in self._legacy_root_candidates():
            payload = read_json(root / "resolver.json", default=None)
            if isinstance(payload, dict):
                return payload
        return None

    def _legacy_items(self, *, include_archived: bool) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root in self._legacy_root_candidates():
            for item in self._list_file_items(root / "items", include_archived=include_archived):
                item_id = str(item.get("id") or "")
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    items.append(item)
        return items

    def _legacy_items_for_migration(self, *, include_archived: bool) -> list[dict[str, Any]]:
        """Read V1 only from explicitly quarantined migration locations."""

        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        candidates = [
            *self._list_file_items(self.items_dir, include_archived=include_archived),
            *self._legacy_items(include_archived=include_archived),
        ]
        db = postgres_store(self.tenant_id)
        if db:
            for layer in (PRODUCT_MASTER_DB_LAYER, LEGACY_PRODUCT_DB_LAYER):
                candidates.extend(
                    db.list_knowledge_items(
                        self.tenant_id,
                        layer=layer,
                        category_id=PRODUCT_MASTER_CATEGORY_ID,
                        include_archived=include_archived,
                    )
                )
        for item in candidates:
            item_id = str(item.get("id") or "")
            if item_id and item_id not in seen and not is_v2_product_item(item):
                seen.add(item_id)
                items.append(item)
        return items

    def _list_file_items(self, root: Path, *, include_archived: bool) -> list[dict[str, Any]]:
        if not root.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.json")):
            payload = read_json(path, default=None)
            if not isinstance(payload, dict):
                continue
            if not include_archived and str(payload.get("status") or "active") == "archived":
                continue
            payload["category_id"] = PRODUCT_MASTER_CATEGORY_ID
            items.append(payload)
        return items


def normalize_product_item(item: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(item)
    timestamp = now()
    if not is_v2_product_item(result):
        return convert_generic_product_to_manual_v2(result, observed_at=timestamp)
    # ``data`` was the retired V1 persistence shape.  Compatibility readers
    # derive it on demand, but accepting it here would let an admin response
    # or historical file reintroduce a second, stale fact store into V2.
    result.pop("data", None)
    result["category_id"] = PRODUCT_MASTER_CATEGORY_ID
    result["schema_version"] = 2
    result.setdefault("status", "active")
    result["source"] = normalize_product_source(result.get("source"), recorded_at=timestamp)
    result.setdefault("runtime", {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"})
    metadata = result.setdefault("metadata", {})
    metadata.setdefault("created_at", timestamp)
    metadata["updated_at"] = timestamp
    metadata.setdefault("created_by", "admin")
    metadata.setdefault("updated_by", "admin")
    return result


def is_v2_product_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    return int(item.get("schema_version") or 1) >= 2 and str(source.get("type") or "") in {"dafengche", "manual"}


def convert_generic_product_to_manual_v2(
    item: dict[str, Any],
    *,
    observed_at: str | None = None,
    ingest_channel: str | None = None,
    migration_batch: str | None = None,
) -> dict[str, Any]:
    """Convert a generic product-form payload into a V2 manual vehicle record.

    This is the one permitted V1 boundary: it is an input adapter, never a
    stored/read runtime format.  Only facts with an unambiguous mapping are
    placed in the Dafengche-shaped detail payload; the full input remains in an
    internal compatibility snapshot for audit and frozen-call-site projection.
    """

    snapshot = deepcopy(item) if isinstance(item, dict) else {}
    data = snapshot.get("data") if isinstance(snapshot.get("data"), dict) else {}
    original_source = snapshot.get("source") if isinstance(snapshot.get("source"), dict) else {}
    timestamp = observed_at or now()
    channel = ingest_channel or _generic_input_ingest_channel(str(original_source.get("type") or ""))
    detail_payload: dict[str, Any] = {}
    field_provenance: dict[str, Any] = {}
    if data.get("name") not in (None, ""):
        detail_payload["baseCarInfo"] = {"name": deepcopy(data.get("name"))}
        field_provenance["source_payloads.vehicle_detail.payload.baseCarInfo.name"] = _manual_field_provenance(
            original_path="data.name",
            original_source=original_source,
            ingest_channel=channel,
            recorded_at=timestamp,
        )
    if "price" in data and data.get("price") is not None:
        detail_payload["carPriceInfo"] = {"salePrice": deepcopy(data.get("price"))}
        field_provenance["source_payloads.vehicle_detail.payload.carPriceInfo.salePrice"] = _manual_field_provenance(
            original_path="data.price",
            original_source=original_source,
            ingest_channel=channel,
            recorded_at=timestamp,
        )

    requested_id = str(snapshot.get("id") or "")
    record = create_manual_vehicle(
        record_id=requested_id or "invalid_manual_product_id",
        vehicle_detail_payload=detail_payload,
        pictures_payload=[],
        observed_at=timestamp,
        field_provenance=field_provenance,
    )
    record["id"] = requested_id
    record["status"] = str(snapshot.get("status") or "active")
    record["runtime"] = deepcopy(
        snapshot.get("runtime")
        if isinstance(snapshot.get("runtime"), dict)
        else {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"}
    )
    marker = {
        "ingest_channel": channel,
        "original_source_type": str(original_source.get("type") or "legacy_unclassified"),
        "recorded_at": timestamp,
    }
    if migration_batch:
        marker["migration_batch"] = str(migration_batch)
    record["source"]["marker"] = marker

    existing_extensions = snapshot.get("extensions") if isinstance(snapshot.get("extensions"), dict) else {}
    compatibility = deepcopy(existing_extensions.get("compatibility") if isinstance(existing_extensions.get("compatibility"), dict) else {})
    compatibility["legacy_v1_record"] = snapshot
    compatibility["input_adapter"] = "generic_product_form_to_manual_v2"
    if migration_batch:
        compatibility["migration"] = {
            "from_schema_version": int(snapshot.get("schema_version") or 1),
            "batch_id": str(migration_batch),
            "migrated_at": timestamp,
        }
    wechat_extension = deepcopy(
        existing_extensions.get("wechat_customer_service")
        if isinstance(existing_extensions.get("wechat_customer_service"), dict)
        else {}
    )
    wechat_extension["customer_visible_annotations"] = _generic_customer_visible_annotations(data)
    wechat_extension["manual_annotations"] = {
        key: deepcopy(data[key])
        for key in ("sku", "unit", "inventory", "price_tiers", "reply_templates")
        if key in data
    }
    wechat_extension.setdefault("manual_overrides", {})
    record["extensions"] = {
        **deepcopy(existing_extensions),
        "manual": deepcopy(record.get("extensions", {}).get("manual") if isinstance(record.get("extensions"), dict) else {}),
        "compatibility": compatibility,
        "wechat_customer_service": wechat_extension,
    }
    old_metadata = snapshot.get("metadata") if isinstance(snapshot.get("metadata"), dict) else {}
    record["metadata"] = {
        **deepcopy(old_metadata),
        "created_at": str(old_metadata.get("created_at") or timestamp),
        "updated_at": timestamp,
        "migrated_from_schema_version": int(snapshot.get("schema_version") or 1),
    }
    if migration_batch:
        record["metadata"]["migration_batch"] = str(migration_batch)
    return record


def _generic_input_ingest_channel(original_source_type: str) -> str:
    value = str(original_source_type or "").strip()
    return {
        "test_fixture": "test_fixture",
        "raw_upload": "raw_upload",
        "legacy_migration": "legacy_v1_migration",
    }.get(value, "manual_input")


def _manual_field_provenance(
    *,
    original_path: str,
    original_source: dict[str, Any],
    ingest_channel: str,
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "source": ingest_channel,
        "original_path": original_path,
        "original_source_type": str(original_source.get("type") or "legacy_unclassified"),
        "recorded_at": recorded_at,
    }


def _generic_customer_visible_annotations(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("category", "specs", "shipping_policy", "warranty_policy", "risk_rules", "additional_details"):
        if key in data and data[key] not in (None, "", [], {}):
            result[key] = deepcopy(data[key])
    aliases = data.get("aliases")
    if isinstance(aliases, list):
        result["aliases"] = deepcopy(aliases)
    elif aliases not in (None, ""):
        result["aliases"] = [deepcopy(aliases)]
    return result


def normalize_product_source(value: Any, *, recorded_at: str) -> dict[str, Any]:
    """Add the additive provenance marker used by every saved vehicle record.

    The marker never changes the original ``source.type`` contract.  It makes
    the ingestion route explicit for API mirrors, normal manual entry, and an
    auditable v1-to-v2 migration while allowing integrations to add future
    source types without being rejected.
    """

    source = deepcopy(value) if isinstance(value, dict) else {}
    source_type = str(source.get("type") or "manual").strip() or "manual"
    source["type"] = source_type
    if not source.get("provider"):
        source["provider"] = "dafengche" if source_type == "dafengche" else source_type
    marker = deepcopy(source.get("marker")) if isinstance(source.get("marker"), dict) else {}
    marker.setdefault("ingest_channel", _default_ingest_channel(source_type))
    marker.setdefault("original_source_type", source_type)
    marker.setdefault("recorded_at", recorded_at)
    source["marker"] = marker
    return source


def _default_ingest_channel(source_type: str) -> str:
    channels = {
        "dafengche": "dafengche_api",
        "manual": "manual_input",
        "test_fixture": "test_fixture",
        "raw_upload": "raw_upload",
        "admin_form": "admin_form",
    }
    return channels.get(str(source_type), "legacy_unclassified")


def customer_evidence_item(
    item: dict[str, Any],
    *,
    shop_code: str | None = None,
    policy: CustomerEvidencePolicy | None = None,
) -> dict[str, Any] | None:
    """Convert one product-master record into the pre-existing evidence shape.

    This is the only WeChat-side bridge from a v2 source mirror to the generic
    catalog contract consumed by legacy callers.  It intentionally keeps the
    raw Dafengche payload out of the returned item.
    """

    if not isinstance(item, dict):
        return None
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    if int(item.get("schema_version") or 1) < 2 or str(source.get("type") or "") not in {"dafengche", "manual"}:
        return deepcopy(item)
    evidence = project_customer_evidence(item, shop_code=shop_code, policy=policy)
    if not evidence:
        return None
    result = {
        "schema_version": 2,
        "category_id": PRODUCT_MASTER_CATEGORY_ID,
        "id": item.get("id"),
        "status": item.get("status") or "active",
        "source": {
            "type": source.get("type"),
            "provider": source.get("provider"),
            "binding": deepcopy(source.get("binding") if isinstance(source.get("binding"), dict) else {}),
        },
        "data": {
            "name": evidence.get("name"),
            "category": evidence.get("category"),
            "aliases": deepcopy(evidence.get("aliases") if isinstance(evidence.get("aliases"), list) else []),
            "specs": evidence.get("specs"),
            "price": evidence.get("price"),
        },
        "runtime": deepcopy(item.get("runtime") if isinstance(item.get("runtime"), dict) else {}),
        "metadata": {"source_updated_at": evidence.get("source_updated_at")},
        "customer_evidence": evidence,
    }
    return result


def compatibility_product_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Project v2 vehicle envelopes into the old generic product contract."""

    if not isinstance(item, dict):
        return None
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    if int(item.get("schema_version") or 1) < 2 or str(source.get("type") or "") not in {"dafengche", "manual"}:
        return deepcopy(item)
    return project_legacy_record(item)


def validate_product_item(item: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    problems: list[str] = []
    product_id = str(item.get("id") or "")
    if not product_id:
        problems.append("item id is required")
    elif not SAFE_PRODUCT_ID_RE.fullmatch(product_id):
        problems.append(f"unsafe product id: {product_id}")
    if item.get("category_id") != PRODUCT_MASTER_CATEGORY_ID:
        problems.append("item category_id must be products")
    source = item.get("source") if isinstance(item.get("source"), dict) else {}
    if int(item.get("schema_version") or 1) >= 2 and str(source.get("type") or "") in {"dafengche", "manual"}:
        marker = source.get("marker") if isinstance(source.get("marker"), dict) else {}
        for marker_field in ("ingest_channel", "original_source_type", "recorded_at"):
            if not str(marker.get(marker_field) or "").strip():
                problems.append(f"v2 vehicle source marker requires {marker_field}")
        source_payloads = item.get("source_payloads") if isinstance(item.get("source_payloads"), dict) else {}
        detail = source_payloads.get("vehicle_detail") if isinstance(source_payloads.get("vehicle_detail"), dict) else {}
        if not isinstance(detail.get("payload"), dict):
            problems.append("v2 vehicle_detail payload is required")
        binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
        if str(source.get("type")) == "dafengche" and (
            str(binding.get("state") or "") != "bound" or not binding.get("shopCode") or not binding.get("carId")
        ):
            problems.append("bound Dafengche vehicle requires shopCode and carId")
        if str(source.get("type")) == "manual" and str(binding.get("state") or "") not in {"unbound", "bound"}:
            problems.append("manual vehicle requires explicit binding state")
        return {"ok": not problems, "problems": problems}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    fields = {field["id"]: field for field in schema.get("fields", []) or [] if isinstance(field, dict) and field.get("id")}
    for field_id, field in fields.items():
        if field.get("required") and data.get(field_id) in (None, "", [], {}):
            problems.append(f"required field is missing: {field_id}")
    return {"ok": not problems, "problems": problems}


def validate_product_id(product_id: str) -> None:
    if not SAFE_PRODUCT_ID_RE.fullmatch(str(product_id or "")):
        raise ValueError(f"unsafe product id: {product_id}")


def read_json(path: Path, *, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    last_error: PermissionError | None = None
    for attempt in range(6):
        try:
            os.replace(temp_path, path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.08 * (attempt + 1))
    try:
        temp_path.unlink(missing_ok=True)
    finally:
        if last_error:
            raise last_error


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def postgres_store(tenant_id: str):
    config = load_storage_config()
    if not config.use_postgres or not config.postgres_configured:
        return None
    store = get_postgres_store(tenant_id=tenant_id, config=config)
    return store if store.available() else None
