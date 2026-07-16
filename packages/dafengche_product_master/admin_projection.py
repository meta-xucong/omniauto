"""Admin-facing V2 vehicle projections and controlled mutation helpers.

The product-master core owns the only field-aware view of a Dafengche-shaped
vehicle record.  Hosts may render the returned projection in an admin console,
but must not copy these field mappings into their own UI or Brain/RPA layers.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Any

from .service import content_hash


V2_VEHICLE_SOURCE_TYPES = frozenset({"dafengche", "manual"})
ANNOTATION_FIELDS = frozenset(
    {
        "category",
        "aliases",
        "specs",
        "shipping_policy",
        "warranty_policy",
        "risk_rules",
        "additional_details",
    }
)
MANUAL_ANNOTATION_FIELDS = frozenset({"sku", "unit", "inventory", "price_tiers", "reply_templates"})

# The management console renders these fields in this exact order.  Values are
# deliberately retained as ``None`` when absent so an operator can distinguish
# an incomplete mirror from a field the UI merely chose not to render.
CARD_FIELD_SPECS = (
    ("baseCarInfo.firstLicensePlateDate", "上牌时间"),
    ("baseCarInfo.mileage", "表显里程"),
    ("carModelParam.gearbox", "变速箱"),
    ("carModelParam.displacement", "排量"),
    ("baseCarInfo.vehicleCondition", "车况"),
    ("baseCarInfo.exteriorColor", "外观颜色"),
)
DETAIL_FIELD_GROUP_SPECS = (
    (
        "vehicle_identity",
        "车源识别",
        (
            ("carId", "大风车车源 ID"),
            ("shopCode", "大风车店铺编码"),
            ("operationPhase", "业务阶段"),
        ),
    ),
    (
        "base_car_info",
        "基础车辆信息",
        (
            ("baseCarInfo.name", "车辆标题"),
            ("baseCarInfo.carName", "车辆名称"),
            ("baseCarInfo.brandName", "品牌"),
            ("baseCarInfo.seriesName", "车系"),
            ("baseCarInfo.modelName", "车型"),
            ("baseCarInfo.firstLicensePlateDate", "上牌时间"),
            ("baseCarInfo.mileage", "表显里程"),
            ("baseCarInfo.vehicleCondition", "车况"),
            ("baseCarInfo.exteriorColor", "外观颜色"),
            ("baseCarInfo.color", "车身颜色"),
            ("baseCarInfo.interiorColor", "内饰颜色"),
        ),
    ),
    (
        "model_parameters",
        "车型参数",
        (
            ("carModelParam.gearbox", "变速箱"),
            ("carModelParam.gearBox", "变速箱（备用字段）"),
            ("carModelParam.displacement", "排量"),
        ),
    ),
    (
        "price_information",
        "价格信息",
        (
            ("carPriceInfo.salePrice", "公开售价"),
            ("carPriceInfo.purchasePrice", "收购价"),
            ("carPriceInfo.salesPrice", "成交价"),
            ("carPriceInfo.managerPrice", "经理价"),
            ("carPriceInfo.wholesalePrice", "批发价"),
        ),
    ),
    (
        "license_information",
        "手续信息",
        (("carLicenseInfo.licenseStatus", "手续状态"),),
    ),
)


def is_v2_vehicle_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    return int(record.get("schema_version") or 1) >= 2 and str(source.get("type") or "") in V2_VEHICLE_SOURCE_TYPES


def build_admin_vehicle_view(record: dict[str, Any], *, include_raw: bool = False) -> dict[str, Any]:
    """Build a stable, presentation-oriented view without mutating ``record``.

    The canonical source fields retain their Dafengche paths in the stored
    envelope.  This projection is intentionally an admin read model: it is not
    customer evidence and must never be passed to the customer-service Brain.
    """

    if not is_v2_vehicle_record(record):
        return _legacy_admin_view(record)

    source = _mapping(record.get("source"))
    marker = _mapping(source.get("marker"))
    binding = _mapping(source.get("binding"))
    detail_snapshot = _mapping(_mapping(record.get("source_payloads")).get("vehicle_detail"))
    detail = _mapping(detail_snapshot.get("payload"))
    pictures_snapshot = _mapping(_mapping(record.get("source_payloads")).get("vehicle_pictures"))
    annotations, manual_annotations = _annotations(record)
    base = _mapping(detail.get("baseCarInfo"))
    model = _mapping(detail.get("carModelParam"))
    pricing = _mapping(detail.get("carPriceInfo"))
    license_info = _mapping(detail.get("carLicenseInfo"))
    source_type = str(source.get("type") or "")
    ingest_channel = str(marker.get("ingest_channel") or "")
    operation_phase = detail.get("operationPhase")
    name = _first_text(base.get("name"), base.get("carName"), _joined_text(base.get("brandName"), base.get("seriesName"), base.get("modelName")))
    photos = _picture_urls(pictures_snapshot.get("payload"))
    photo_entries = _picture_entries(pictures_snapshot.get("payload"))
    metadata = _mapping(record.get("metadata"))
    observed_at = str(marker.get("last_observed_at") or metadata.get("source_last_synced_at") or detail_snapshot.get("pulled_at") or "")
    sync = _sync_view(source_type, ingest_channel, observed_at, marker)
    view: dict[str, Any] = {
        "view_version": 1,
        "record_kind": "vehicle_v2",
        "summary": {
            "id": str(record.get("id") or ""),
            "name": name or str(record.get("id") or ""),
            "price": pricing.get("salePrice"),
            "category": annotations.get("category") or "used_car",
            "status": str(record.get("status") or "active"),
            "operation_phase": operation_phase,
            "photo_count": len(photos),
        },
        "vehicle": {
            "operationPhase": operation_phase,
            "title": base.get("name"),
            "baseCarInfo": {
                "name": base.get("name") or base.get("carName"),
                "carName": base.get("carName"),
                "brandName": base.get("brandName"),
                "seriesName": base.get("seriesName"),
                "modelName": base.get("modelName"),
                "firstLicensePlateDate": base.get("firstLicensePlateDate"),
                "mileage": base.get("mileage"),
                "vehicleCondition": base.get("vehicleCondition"),
                "exteriorColor": _first_value(base.get("exteriorColor"), base.get("color")),
                "color": base.get("color"),
                "interiorColor": base.get("interiorColor"),
            },
            "carModelParam": {
                "gearbox": _first_value(model.get("gearbox"), model.get("gearBox")),
                "gearBox": model.get("gearBox"),
                "displacement": model.get("displacement"),
            },
            "carLicenseInfo": {"licenseStatus": license_info.get("licenseStatus")},
            "carPriceInfo": {
                "salePrice": pricing.get("salePrice"),
                "purchasePrice": pricing.get("purchasePrice"),
                "salesPrice": pricing.get("salesPrice"),
                "managerPrice": pricing.get("managerPrice"),
                "wholesalePrice": pricing.get("wholesalePrice"),
            },
            "card_fields": _field_rows(detail, CARD_FIELD_SPECS),
            "photos": photos,
            # Additive admin projection: existing consumers keep ``photos``;
            # the V2 editor receives stable local picture identifiers needed
            # for authenticated deletion without exposing the raw payload.
            "photo_entries": photo_entries,
        },
        "source": {
            "type": source_type,
            "provider": str(source.get("provider") or source_type),
            "ingest_channel": ingest_channel,
            "original_source_type": str(marker.get("original_source_type") or source_type),
            "recorded_at": str(marker.get("recorded_at") or ""),
            "last_observed_at": str(marker.get("last_observed_at") or ""),
            "binding_state": str(binding.get("state") or "unbound"),
            "shop_code": str(binding.get("shopCode") or ""),
            "car_id": str(binding.get("carId") or ""),
            "detail_api": str(detail_snapshot.get("api") or ""),
            "detail_pulled_at": str(detail_snapshot.get("pulled_at") or ""),
            "sync": sync,
        },
        "annotations": annotations,
        "manual_annotations": manual_annotations,
        "capabilities": {
            "can_edit_vehicle_source": source_type == "manual",
            "can_edit_vehicle_pictures": source_type == "manual",
            "can_edit_annotations": True,
            "can_change_listing_status": True,
            "can_request_sync": False,
        },
    }
    if include_raw:
        view["raw_source_payloads"] = copy.deepcopy(record.get("source_payloads") if isinstance(record.get("source_payloads"), dict) else {})
        view["dafengche_field_groups"] = _dafengche_field_groups(detail)
    return view


def build_legacy_data_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Build an output-only generic-data facade for frozen legacy consumers.

    It is deliberately derived on demand and must never be persisted back into
    a V2 record.  Authoritative manual vehicle values win over a historical V1
    migration snapshot so UI/API consumers cannot see a stale shadow copy.
    """

    if not is_v2_vehicle_record(record):
        return copy.deepcopy(record.get("data") if isinstance(record.get("data"), dict) else {})
    view = build_admin_vehicle_view(record)
    annotations = _mapping(view.get("annotations"))
    manual = _mapping(view.get("manual_annotations"))
    vehicle = _mapping(view.get("vehicle"))
    base = _mapping(vehicle.get("baseCarInfo"))
    price = _mapping(vehicle.get("carPriceInfo"))
    snapshot = _legacy_snapshot_data(record)
    result = copy.deepcopy(snapshot)
    _set_if_present(result, "name", _first_value(base.get("name"), view.get("summary", {}).get("name") if isinstance(view.get("summary"), dict) else None))
    _set_if_present(result, "price", price.get("salePrice"))
    for field in ANNOTATION_FIELDS:
        if field in annotations:
            result[field] = copy.deepcopy(annotations[field])
    for field in MANUAL_ANNOTATION_FIELDS:
        if field in manual:
            result[field] = copy.deepcopy(manual[field])
    return result


def apply_admin_vehicle_update(record: dict[str, Any], patch: dict[str, Any], *, observed_at: str | None = None) -> dict[str, Any]:
    """Apply an admin edit while preserving V2 authority and raw payload shape.

    ``vehicle_detail_patch`` and ``vehicle_pictures_patch`` use the original
    Dafengche-shaped source-payload locations directly. They are accepted only
    for ``source.type=manual``. Bound Dafengche records may receive local
    annotations but never a disguised upstream rewrite.
    """

    if not is_v2_vehicle_record(record):
        raise ValueError("admin V2 vehicle update requires a V2 vehicle record")
    if not isinstance(patch, dict):
        raise ValueError("admin vehicle patch must be an object")
    result = copy.deepcopy(record)
    timestamp = observed_at or _now_iso()
    source = _mapping(result.get("source"))
    source_type = str(source.get("type") or "")
    vehicle_patch = patch.get("vehicle_detail_patch")
    pictures_patch = patch.get("vehicle_pictures_patch")
    if vehicle_patch not in (None, {}) and not isinstance(vehicle_patch, dict):
        raise ValueError("vehicle_detail_patch must be an object")
    if pictures_patch is not None and not isinstance(pictures_patch, list):
        raise ValueError("vehicle_pictures_patch must be an array")
    if (isinstance(vehicle_patch, dict) and vehicle_patch) or pictures_patch is not None:
        if source_type != "manual":
            raise ValueError("Dafengche synchronized vehicle facts and pictures are read-only; sync them from Dafengche or save local annotations instead")
    if isinstance(vehicle_patch, dict) and vehicle_patch:
        payloads = _mapping(result.get("source_payloads"))
        snapshot = _mapping(payloads.get("vehicle_detail"))
        detail = _mapping(snapshot.get("payload"))
        _deep_merge(detail, vehicle_patch)
        snapshot["payload"] = detail
        snapshot["pulled_at"] = timestamp
        snapshot["content_hash"] = content_hash(detail)
        payloads["vehicle_detail"] = snapshot
        result["source_payloads"] = payloads
        _record_manual_field_provenance(result, vehicle_patch, timestamp)
    if pictures_patch is not None:
        payloads = _mapping(result.get("source_payloads"))
        snapshot = _mapping(payloads.get("vehicle_pictures"))
        snapshot["payload"] = copy.deepcopy(pictures_patch)
        snapshot["pulled_at"] = timestamp
        snapshot["content_hash"] = content_hash(pictures_patch)
        payloads["vehicle_pictures"] = snapshot
        result["source_payloads"] = payloads
        _record_manual_picture_provenance(result, timestamp)

    annotations_patch = patch.get("annotations")
    manual_patch = patch.get("manual_annotations")
    if annotations_patch not in (None, {}) and not isinstance(annotations_patch, dict):
        raise ValueError("annotations must be an object")
    if manual_patch not in (None, {}) and not isinstance(manual_patch, dict):
        raise ValueError("manual_annotations must be an object")
    if isinstance(annotations_patch, dict) or isinstance(manual_patch, dict):
        extensions = _mapping(result.get("extensions"))
        wechat = _mapping(extensions.get("wechat_customer_service"))
        annotations = _mapping(wechat.get("customer_visible_annotations"))
        manual = _mapping(wechat.get("manual_annotations"))
        if isinstance(annotations_patch, dict):
            for key, value in annotations_patch.items():
                if key in ANNOTATION_FIELDS:
                    annotations[key] = copy.deepcopy(value)
        if isinstance(manual_patch, dict):
            for key, value in manual_patch.items():
                if key in MANUAL_ANNOTATION_FIELDS:
                    manual[key] = copy.deepcopy(value)
        wechat["customer_visible_annotations"] = annotations
        wechat["manual_annotations"] = manual
        wechat.setdefault("manual_overrides", {})
        extensions["wechat_customer_service"] = wechat
        result["extensions"] = extensions

    metadata = _mapping(result.get("metadata"))
    metadata["updated_at"] = timestamp
    if (isinstance(vehicle_patch, dict) and vehicle_patch) or pictures_patch is not None:
        metadata["manual_last_edited_at"] = timestamp
    result["metadata"] = metadata
    return result


def _legacy_admin_view(record: dict[str, Any]) -> dict[str, Any]:
    data = _mapping(record.get("data"))
    return {
        "view_version": 1,
        "record_kind": "legacy_generic",
        "summary": {
            "id": str(record.get("id") or ""),
            "name": str(data.get("name") or record.get("id") or ""),
            "price": data.get("price"),
            "category": data.get("category") or "",
            "status": str(record.get("status") or "active"),
            "operation_phase": "",
            "photo_count": 0,
        },
        "vehicle": {"operationPhase": "", "title": data.get("name"), "baseCarInfo": {}, "carModelParam": {}, "carLicenseInfo": {}, "carPriceInfo": {"salePrice": data.get("price")}, "card_fields": [], "photos": []},
        "source": {"type": "legacy", "provider": "legacy", "ingest_channel": "legacy", "binding_state": "unbound", "sync": {"state": "legacy", "label": "旧格式"}},
        "annotations": copy.deepcopy(data),
        "manual_annotations": {},
        "capabilities": {"can_edit_vehicle_source": False, "can_edit_annotations": True, "can_change_listing_status": True, "can_request_sync": False},
    }


def _annotations(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    extensions = _mapping(record.get("extensions"))
    wechat = _mapping(extensions.get("wechat_customer_service"))
    return _mapping(wechat.get("customer_visible_annotations")), _mapping(wechat.get("manual_annotations"))


def _legacy_snapshot_data(record: dict[str, Any]) -> dict[str, Any]:
    extensions = _mapping(record.get("extensions"))
    compatibility = _mapping(extensions.get("compatibility"))
    snapshot = _mapping(compatibility.get("legacy_v1_record"))
    return _mapping(snapshot.get("data"))


def _sync_view(source_type: str, ingest_channel: str, observed_at: str, marker: dict[str, Any]) -> dict[str, Any]:
    if source_type == "dafengche":
        return {"state": "synced", "label": "大风车同步", "observed_at": observed_at}
    if ingest_channel == "legacy_v1_migration":
        return {"state": "historical_migration", "label": "历史迁入", "observed_at": observed_at or str(marker.get("recorded_at") or "")}
    if source_type == "manual":
        return {"state": "manual", "label": "手动录入", "observed_at": observed_at or str(marker.get("recorded_at") or "")}
    return {"state": "unknown", "label": "来源待确认", "observed_at": observed_at}


def _record_manual_field_provenance(record: dict[str, Any], vehicle_patch: dict[str, Any], timestamp: str) -> None:
    extensions = _mapping(record.get("extensions"))
    manual = _mapping(extensions.get("manual"))
    provenance = _mapping(manual.get("field_provenance"))
    for path in _leaf_paths(vehicle_patch):
        provenance[f"source_payloads.vehicle_detail.payload.{path}"] = {
            "source": "manual_admin_edit",
            "recorded_at": timestamp,
        }
    manual["field_provenance"] = provenance
    extensions["manual"] = manual
    record["extensions"] = extensions


def _record_manual_picture_provenance(record: dict[str, Any], timestamp: str) -> None:
    extensions = _mapping(record.get("extensions"))
    manual = _mapping(extensions.get("manual"))
    provenance = _mapping(manual.get("field_provenance"))
    provenance["source_payloads.vehicle_pictures.payload"] = {
        "source": "manual_admin_image_upload",
        "recorded_at": timestamp,
    }
    manual["field_provenance"] = provenance
    extensions["manual"] = manual
    record["extensions"] = extensions


def _leaf_paths(value: Any, prefix: str = "") -> list[str]:
    if not isinstance(value, dict) or not value:
        return [prefix] if prefix else []
    paths: list[str] = []
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        paths.extend(_leaf_paths(child, path))
    return paths


def _deep_merge(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _picture_urls(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        for key in ("bigPictureUrl", "bigPictureLink", "pictureUrl", "pictureLink", "url"):
            url = str(item.get(key) or "").strip()
            if _is_admin_picture_url(url):
                if url not in urls:
                    urls.append(url)
                break
    return urls[:24]


def _picture_entries(value: Any) -> list[dict[str, Any]]:
    """Project safe photo controls while preserving the source payload verbatim."""

    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    urls_seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = next(
            (
                str(item.get(key) or "").strip()
                for key in ("bigPictureUrl", "bigPictureLink", "pictureUrl", "pictureLink", "url")
                if _is_admin_picture_url(str(item.get(key) or "").strip())
            ),
            "",
        )
        if not url or url in urls_seen:
            continue
        urls_seen.add(url)
        entries.append(
            {
                "url": url,
                "picture_id": str(item.get("pictureId") or ""),
                "picture_number": item.get("pictureNumber"),
                "filename": str(item.get("filename") or ""),
                "mime_type": str(item.get("mimeType") or ""),
            }
        )
        if len(entries) >= 24:
            break
    return entries


def _is_admin_picture_url(value: str) -> bool:
    """Allow remote Dafengche URLs and this authenticated host's image route."""

    return value.startswith(("https://", "http://", "/api/product-console/products/"))


def _field_rows(detail: dict[str, Any], specs: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    return [
        {"path": path, "label": label, "value": copy.deepcopy(_value_at(detail, path))}
        for path, label in specs
    ]


def _dafengche_field_groups(detail: dict[str, Any]) -> list[dict[str, Any]]:
    known_paths: set[str] = set()
    groups: list[dict[str, Any]] = []
    for group_id, label, specs in DETAIL_FIELD_GROUP_SPECS:
        known_paths.update(path for path, _ in specs)
        groups.append(
            {
                "id": group_id,
                "label": label,
                "fields": _field_rows(detail, specs),
            }
        )
    extra_rows = [
        {"path": path, "label": "其他字段", "value": copy.deepcopy(value)}
        for path, value in _flatten_payload(detail)
        if path not in known_paths
    ]
    if extra_rows:
        groups.append({"id": "other_fields", "label": "其他大风车字段", "fields": extra_rows})
    return groups


def _value_at(value: Any, path: str) -> Any:
    current = value
    for key in str(path or "").split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _flatten_payload(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        result: list[tuple[str, Any]] = []
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.extend(_flatten_payload(child, path))
        return result
    return [(prefix, value)] if prefix else []


def _mapping(value: Any) -> dict[str, Any]:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _first_value(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "")), None)


def _first_text(*values: Any) -> str:
    value = _first_value(*values)
    return str(value or "").strip()


def _joined_text(*values: Any) -> str:
    return " ".join(str(value).strip() for value in values if str(value or "").strip())


def _set_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value not in (None, ""):
        target[key] = copy.deepcopy(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
