"""Customer-safe evidence projection for Dafengche mirror records."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .contract import VEHICLE_CUSTOMER_VISIBLE_FIELD_PATHS


DETAIL_ROOT = "source_payloads.vehicle_detail.payload"
PICTURES_ROOT = "source_payloads.vehicle_pictures.payload"
DEFAULT_CUSTOMER_VISIBLE_PATHS = frozenset(
    {f"{DETAIL_ROOT}.{path}" for path in VEHICLE_CUSTOMER_VISIBLE_FIELD_PATHS}
    | {
        # Historical manual records used these compatibility paths before the
        # official contract audit.  Keep reading them without turning them into
        # new canonical storage fields.
        f"{DETAIL_ROOT}.baseCarInfo.carName",
        f"{DETAIL_ROOT}.baseCarInfo.brandName",
        f"{DETAIL_ROOT}.baseCarInfo.seriesName",
        f"{DETAIL_ROOT}.baseCarInfo.modelName",
        f"{DETAIL_ROOT}.baseCarInfo.exteriorColor",
        f"{DETAIL_ROOT}.baseCarInfo.interiorColor",
        f"{DETAIL_ROOT}.carModelParam.gearbox",
        f"{DETAIL_ROOT}.carModelParam.gearBox",
        f"{DETAIL_ROOT}.carModelParam.displacement",
        PICTURES_ROOT,
    }
)


@dataclass(frozen=True)
class CustomerEvidencePolicy:
    """Host-configurable allowlist; deny-by-default for source payload fields.

    ``max_age_seconds`` applies to official Dafengche mirror data.  Manual V2
    records are explicitly maintained by an operator, so their default
    lifecycle is governed by their record status (for example ``active`` or
    ``archived``), not by the last upstream-payload timestamp.  A host that
    needs a review/expiry window for manual records can opt into one through
    ``manual_max_age_seconds`` without weakening official mirror freshness.
    """

    allowed_paths: frozenset[str] = field(default_factory=lambda: DEFAULT_CUSTOMER_VISIBLE_PATHS)
    max_age_seconds: int | None = 24 * 60 * 60
    require_shop_scope: bool = True
    allowed_operation_phases: frozenset[str] = field(default_factory=frozenset)
    allow_manual_unbound: bool = True
    manual_max_age_seconds: int | None = None

    def allows(self, path: str) -> bool:
        return path in self.allowed_paths


def project_customer_evidence(
    record: dict[str, Any],
    *,
    shop_code: str | None,
    policy: CustomerEvidencePolicy | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build the existing generic product-evidence shape without exposing raw data.

    The returned mapping is a projection, never a reference to an upstream
    payload. Restricted paths such as VIN, plate, owner and internal prices are
    absent by construction.
    """

    policy = policy or CustomerEvidencePolicy()
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    source_type = str(source.get("type") or "")
    binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
    bound_shop_code = str(binding.get("shopCode") or "")
    if source_type == "dafengche":
        if policy.require_shop_scope and not shop_code:
            return None
        if shop_code and bound_shop_code != str(shop_code):
            return None
    elif source_type == "manual":
        if not policy.allow_manual_unbound:
            return None
        if bound_shop_code:
            if policy.require_shop_scope and not shop_code:
                return None
            if shop_code and bound_shop_code != str(shop_code):
                return None
    else:
        return None
    if str(record.get("status") or "active") not in {"active", "approved", "published"}:
        return None
    if not _is_fresh(record, policy=policy, now=now):
        return None

    detail = _mapping_at(record, DETAIL_ROOT)
    if not detail:
        return None
    operation_phase = _allowed_value(record, f"{DETAIL_ROOT}.operationPhase", policy)
    if policy.allowed_operation_phases and str(operation_phase or "") not in policy.allowed_operation_phases:
        return None
    operation_phase_label = _customer_operation_phase_label(
        operation_phase,
        untrusted=_current_state_field_is_untrusted(record, f"{DETAIL_ROOT}.operationPhase"),
    )

    name = _first_allowed_text(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.name.displayValue",
        f"{DETAIL_ROOT}.baseCarInfo.carName",
    )
    raw_name = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.name", policy)
    if not name and isinstance(raw_name, str):
        name = raw_name.strip()
    brand = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.name.brandName",
        f"{DETAIL_ROOT}.baseCarInfo.brandName",
    )
    series = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.name.seriesName",
        f"{DETAIL_ROOT}.baseCarInfo.seriesName",
    )
    model_name = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.name.modelName",
        f"{DETAIL_ROOT}.baseCarInfo.modelName",
    )
    if not name:
        name = " ".join(str(value).strip() for value in (brand, series, model_name) if str(value or "").strip())
    if not name:
        return None

    year = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.firstLicensePlateDate", policy)
    mileage = _numeric_text_value(_allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.mileage", policy))
    condition = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.vehicleCondition", policy)
    display_description = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.carDetailForDisplay", policy)
    stock_status = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.stockStatus", policy)
    stock_status_label = _customer_stock_status_label(
        stock_status,
        untrusted=_current_state_field_is_untrusted(record, f"{DETAIL_ROOT}.baseCarInfo.stockStatus"),
    )
    exterior_color = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.exteriorColor",
        f"{DETAIL_ROOT}.baseCarInfo.color",
    )
    interior_color = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.interiorColor",
        f"{DETAIL_ROOT}.baseCarInfo.innerColor",
    )
    transmission = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.carModelParam.gearbox",
        f"{DETAIL_ROOT}.carModelParam.gearBox",
        f"{DETAIL_ROOT}.carModelParam.gearBoxType",
    )
    displacement = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.carModelParam.displacement",
        f"{DETAIL_ROOT}.carModelParam.engineVolumeLiter",
    )
    car_body = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.carBody", policy)
    seat_number = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.seatNumber", policy)
    emission_standard = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.emissionStandard", policy)
    fuel_type = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.fuelType", policy)
    highlights = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.highlightsConfiguration", policy)
    keys_count = _allowed_value(record, f"{DETAIL_ROOT}.carLicenseInfo.keysCount", policy)
    transfer_total = _allowed_value(record, f"{DETAIL_ROOT}.carLicenseInfo.transferTotal", policy)
    location = _customer_location_value(record, policy)
    production_date = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.productionDate", policy)
    use_type = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.useType", policy)
    video_summary = _customer_media_availability_label(_allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.video", policy))
    weidian_upshelf = _customer_flag_label(_allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.weidianIsUpshelf", policy))
    up_shelf_date = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.upShelfDate", policy)
    sale_price = _allowed_value(record, f"{DETAIL_ROOT}.carPriceInfo.salePrice", policy)
    annotations = _customer_visible_annotations(record)

    specs_parts = []
    for label, value in (
        ("车况", condition),
        ("外观颜色", exterior_color),
        ("内饰颜色", interior_color),
        ("变速箱", transmission),
        ("排量", displacement),
        ("燃料", fuel_type),
        ("排放", emission_standard),
        ("车身结构", car_body),
        ("座位数", seat_number),
        ("钥匙数", keys_count),
        ("过户次数", transfer_total),
        ("所在地", location),
        ("出厂日期", production_date),
        ("使用性质", use_type),
        ("车辆视频", video_summary),
        ("微店上架状态", weidian_upshelf),
        ("微店上架时间", up_shelf_date),
        ("库存状态", stock_status_label),
        ("业务阶段", operation_phase_label),
    ):
        if value not in (None, ""):
            specs_parts.append(f"{label}:{value}")
    if isinstance(highlights, list) and highlights:
        specs_parts.append("亮点配置:" + "、".join(str(item).strip() for item in highlights if str(item or "").strip()))
    elif highlights not in (None, "", [], {}):
        specs_parts.append(f"亮点配置:{highlights}")
    if display_description not in (None, ""):
        specs_parts.append(f"车辆描述:{display_description}")
    aliases = _unique_texts((name, brand, series, model_name, *(annotations.get("aliases") or [])))
    evidence = {
        "id": record.get("id"),
        "category_id": "products",
        "authority_level": "product_master",
        "name": name,
        "category": annotations.get("category") or "used_car",
        "aliases": aliases,
        "brand": brand,
        "model": model_name or series,
        "year": year,
        "mileage": mileage,
        "color": exterior_color,
        "transmission": transmission,
        "location": location,
        "price": sale_price,
        "stock": stock_status_label,
        "availability": operation_phase_label,
        "stock_status": stock_status_label,
        "operation_phase": operation_phase_label,
        "specs": _customer_specs_text(annotations.get("specs"), specs_parts),
        "source_type": source_type,
        "source_updated_at": _detail_pulled_at(record),
    }
    for key in ("shipping_policy", "warranty_policy", "risk_rules", "additional_details"):
        value = annotations.get(key)
        if value not in (None, "", [], {}):
            evidence[key] = copy.deepcopy(value)
    photos = _customer_picture_urls(record, policy)
    if photos:
        evidence["photos"] = photos
    return {key: copy.deepcopy(value) for key, value in evidence.items() if value not in (None, "", [], {})}


def project_legacy_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """Return a safe generic ``data`` projection for legacy product consumers.

    This compatibility view is derived from the same allowlist as customer
    evidence and deliberately does not copy any source payload fields.
    """

    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    if str(source.get("type") or "") not in {"dafengche", "manual"}:
        return copy.deepcopy(record) if isinstance(record, dict) else None
    legacy_snapshot = _legacy_v1_snapshot(record)
    if legacy_snapshot is not None:
        legacy_snapshot["id"] = record.get("id") or legacy_snapshot.get("id")
        legacy_snapshot["category_id"] = "products"
        legacy_snapshot["status"] = record.get("status") or legacy_snapshot.get("status") or "active"
        return legacy_snapshot
    evidence = project_customer_evidence(
        record,
        shop_code=None,
        policy=CustomerEvidencePolicy(require_shop_scope=False, max_age_seconds=None),
    )
    if not evidence:
        return None
    return {
        "schema_version": 1,
        "category_id": "products",
        "id": record.get("id"),
        "status": record.get("status") or "active",
        "source": {"type": "dafengche_compatibility_projection"},
        "data": {
            "name": evidence.get("name"),
            "category": evidence.get("category"),
            "aliases": copy.deepcopy(evidence.get("aliases") if isinstance(evidence.get("aliases"), list) else []),
            "specs": evidence.get("specs"),
            "price": evidence.get("price"),
            "additional_details": {
                key: evidence.get(key)
                for key in ("brand", "model", "year", "mileage", "color", "transmission", "availability", "photos", "source_updated_at")
                if evidence.get(key) not in (None, "", [], {})
            },
        },
        "runtime": copy.deepcopy(record.get("runtime") if isinstance(record.get("runtime"), dict) else {}),
        "metadata": {"projection_source_updated_at": evidence.get("source_updated_at")},
    }


def _is_fresh(record: dict[str, Any], *, policy: CustomerEvidencePolicy, now: datetime | None) -> bool:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    is_manual = str(source.get("type") or "") == "manual"
    max_age_seconds = policy.manual_max_age_seconds if is_manual else policy.max_age_seconds
    if max_age_seconds is None:
        return True
    observed = _manual_updated_at(record) if is_manual else _detail_pulled_at(record)
    if not observed:
        return False
    try:
        observed_at = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return (current - observed_at).total_seconds() <= max_age_seconds


def _detail_pulled_at(record: dict[str, Any]) -> str:
    snapshot = _mapping_at(record, "source_payloads.vehicle_detail")
    return str(snapshot.get("pulled_at") or "") if snapshot else ""


def _manual_updated_at(record: dict[str, Any]) -> str:
    """Return the newest auditable manual-maintenance timestamp when present."""

    candidates = [
        _detail_pulled_at(record),
        _value_at(record, "source.marker.recorded_at"),
        _value_at(record, "source_payloads.vehicle_detail.enriched_at"),
        _value_at(record, "metadata.updated_at"),
    ]
    provenance = _value_at(record, "extensions.manual.field_provenance")
    if isinstance(provenance, dict):
        candidates.extend(
            value.get("recorded_at")
            for value in provenance.values()
            if isinstance(value, dict)
        )
    dated: list[tuple[datetime, str]] = []
    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        dated.append((parsed, text))
    return max(dated, default=(datetime.min.replace(tzinfo=timezone.utc), ""))[1]


def _allowed_value(record: dict[str, Any], path: str, policy: CustomerEvidencePolicy) -> Any:
    return _value_at(record, path) if policy.allows(path) else None


def _first_allowed_value(record: dict[str, Any], policy: CustomerEvidencePolicy, *paths: str) -> Any:
    for path in paths:
        value = _allowed_value(record, path, policy)
        if value not in (None, ""):
            return value
    return None


def _first_allowed_text(record: dict[str, Any], policy: CustomerEvidencePolicy, *paths: str) -> str:
    value = _first_allowed_value(record, policy, *paths)
    return str(value).strip() if value not in (None, "") else ""


def _numeric_text_value(value: Any) -> Any:
    """Normalize a numeric text input only in the derived evidence view."""

    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return value
    try:
        number = float(text)
    except ValueError:
        return value
    return int(number) if number.is_integer() else number


def _customer_location_value(record: dict[str, Any], policy: CustomerEvidencePolicy) -> str | None:
    display_path = f"{DETAIL_ROOT}.baseCarInfo.area.displayValue"
    display = _allowed_value(record, display_path, policy)
    if display not in (None, ""):
        return str(display).strip()
    if not policy.allows(display_path):
        return None
    # ``cityName``/``provinceName`` are source-internal components, while
    # ``area.displayValue`` is the customer-visible field.  When old/local
    # manual records only have the components, derive the same readable
    # display value without exposing codes or broadening the public allowlist.
    province = str(_value_at(record, f"{DETAIL_ROOT}.baseCarInfo.area.provinceName") or "").strip()
    city = str(_value_at(record, f"{DETAIL_ROOT}.baseCarInfo.area.cityName") or "").strip()
    if province and city:
        if province == city or city in province:
            return province
        if province in city:
            return city
        return f"{province}{city}"
    return province or city or None


def _customer_operation_phase_label(value: Any, *, untrusted: bool = False) -> str | None:
    if untrusted:
        return "待核实" if str(value or "").strip() else None
    return _readable_code_label(
        value,
        {
            "sale": "在售",
            "selling": "在售",
            "on_sale": "在售",
            "test_sale": "在售",
            "sold": "已售",
            "prepare": "整备中",
            "preparing": "整备中",
            "pending": "待上架",
            "reserved": "已预订",
            "off_shelf": "已下架",
            "offline": "已下架",
            "archived": "已归档",
        },
    )


def _customer_stock_status_label(value: Any, *, untrusted: bool = False) -> str | None:
    if untrusted:
        return "待核实" if str(value or "").strip() else None
    return _readable_code_label(
        value,
        {
            "1": "在库",
            "in_stock": "在库",
            "available": "在库",
            "sale": "在库",
            "0": "无库存",
            "out_of_stock": "无库存",
            "sold_out": "无库存",
            "2": "已预订",
            "reserved": "已预订",
            "3": "已售",
            "sold": "已售",
            "archived": "已归档",
        },
    )


def _current_state_field_is_untrusted(record: dict[str, Any], path: str) -> bool:
    """Return true when a status-like value is only a test/migration fill.

    Current availability/stock facts are operational claims.  A V2 manual
    vehicle can retain migration/test payloads for audit, but those placeholders
    must not authorize customer-visible "in stock" or "on sale" assertions.
    """

    provenance = _value_at(record, "extensions.manual.field_provenance")
    if isinstance(provenance, dict):
        relative = path[len(f"{DETAIL_ROOT}.") :] if path.startswith(f"{DETAIL_ROOT}.") else path
        for key in (path, relative):
            marker = provenance.get(key)
            if isinstance(marker, dict):
                if _provenance_marks_test_or_migration(marker):
                    return True
                if str(marker.get("source") or "") == "manual_admin_edit":
                    return False
    return _looks_like_test_placeholder(_value_at(record, path))


def _looks_like_test_placeholder(value: Any) -> bool:
    text = str(value or "").strip().lower()
    if not text:
        return False
    normalized = text.replace("-", "_").replace(" ", "_")
    return normalized.startswith("test_") or normalized.endswith("_test") or "_test_" in normalized


def _provenance_marks_test_or_migration(marker: dict[str, Any]) -> bool:
    values = [
        marker.get("source"),
        marker.get("action"),
        marker.get("ingest_channel"),
        marker.get("original_source_type"),
        marker.get("batch_id"),
        marker.get("reason"),
    ]
    text = " ".join(str(value or "").strip().lower() for value in values if str(value or "").strip())
    if marker.get("test_only") is True:
        return True
    return any(term in text for term in ("filled_test_value", "test_fixture_fill", "legacy_v1_migration"))


def _customer_flag_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in {"1", "true", "yes", "y", "on", "up", "upshelf", "shelf", "online"}:
        return "已上架"
    if normalized in {"0", "false", "no", "n", "off", "down", "downshelf", "offline"}:
        return "未上架"
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    return "待核实"


def _customer_media_availability_label(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return "可提供" if _contains_safe_public_media_reference(value) else None


def _contains_safe_public_media_reference(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        if text.startswith(("https://", "http://")):
            return True
        if any(marker in text for marker in ("\\", "/", ":", "assetFile")):
            return False
        return any("\u4e00" <= char <= "\u9fff" for char in text)
    if isinstance(value, dict):
        return any(_contains_safe_public_media_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_safe_public_media_reference(child) for child in value)
    return bool(value)


def _readable_code_label(value: Any, mapping: dict[str, str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.lower().replace("-", "_").replace(" ", "_")
    if normalized in mapping:
        return mapping[normalized]
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    if all(char.isalnum() or char == "_" for char in normalized):
        return "待核实"
    return text


def _customer_specs_text(base_specs: Any, spec_parts: Iterable[Any]) -> str | None:
    parts: list[str] = []
    for part in spec_parts:
        text = str(part or "").strip()
        if text and text not in parts:
            parts.append(text)
    if isinstance(base_specs, list):
        parts.extend(_unique_texts(base_specs))
    elif base_specs not in (None, "", [], {}):
        text = str(base_specs).strip()
        if text:
            parts.append(text)
    return "；".join(parts) if parts else None


def _customer_picture_urls(record: dict[str, Any], policy: CustomerEvidencePolicy) -> list[str]:
    if not policy.allows(PICTURES_ROOT):
        return []
    pictures = _value_at(record, PICTURES_ROOT)
    if not isinstance(pictures, list):
        return []
    urls: list[str] = []
    for picture in pictures:
        if not isinstance(picture, dict):
            continue
        for key in ("pictureBig", "bigPictureUrl", "bigPictureLink", "pictureUrl", "pictureLink", "url"):
            value = str(picture.get(key) or "").strip()
            if value.startswith(("https://", "http://")):
                urls.append(value)
                break
    return _unique_texts(urls)[:12]


def _customer_visible_annotations(record: dict[str, Any]) -> dict[str, Any]:
    extensions = record.get("extensions") if isinstance(record.get("extensions"), dict) else {}
    wechat = extensions.get("wechat_customer_service") if isinstance(extensions.get("wechat_customer_service"), dict) else {}
    annotations = wechat.get("customer_visible_annotations")
    return copy.deepcopy(annotations) if isinstance(annotations, dict) else {}


def _legacy_v1_snapshot(record: dict[str, Any]) -> dict[str, Any] | None:
    extensions = record.get("extensions") if isinstance(record.get("extensions"), dict) else {}
    compatibility = extensions.get("compatibility") if isinstance(extensions.get("compatibility"), dict) else {}
    payload = compatibility.get("legacy_v1_record")
    return copy.deepcopy(payload) if isinstance(payload, dict) else None


def _mapping_at(value: dict[str, Any], path: str) -> dict[str, Any]:
    item = _value_at(value, path)
    return item if isinstance(item, dict) else {}


def _value_at(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _unique_texts(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result
