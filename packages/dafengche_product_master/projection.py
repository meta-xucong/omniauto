"""Customer-safe evidence projection for Dafengche mirror records."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable


DETAIL_ROOT = "source_payloads.vehicle_detail.payload"
PICTURES_ROOT = "source_payloads.vehicle_pictures.payload"
DEFAULT_CUSTOMER_VISIBLE_PATHS = frozenset(
    {
        f"{DETAIL_ROOT}.operationPhase",
        f"{DETAIL_ROOT}.baseCarInfo.name",
        f"{DETAIL_ROOT}.baseCarInfo.carName",
        f"{DETAIL_ROOT}.baseCarInfo.brandName",
        f"{DETAIL_ROOT}.baseCarInfo.seriesName",
        f"{DETAIL_ROOT}.baseCarInfo.modelName",
        f"{DETAIL_ROOT}.baseCarInfo.firstLicensePlateDate",
        f"{DETAIL_ROOT}.baseCarInfo.mileage",
        f"{DETAIL_ROOT}.baseCarInfo.vehicleCondition",
        f"{DETAIL_ROOT}.baseCarInfo.exteriorColor",
        f"{DETAIL_ROOT}.baseCarInfo.interiorColor",
        f"{DETAIL_ROOT}.baseCarInfo.color",
        f"{DETAIL_ROOT}.carModelParam.gearbox",
        f"{DETAIL_ROOT}.carModelParam.gearBox",
        f"{DETAIL_ROOT}.carModelParam.displacement",
        f"{DETAIL_ROOT}.carPriceInfo.salePrice",
        PICTURES_ROOT,
    }
)


@dataclass(frozen=True)
class CustomerEvidencePolicy:
    """Host-configurable allowlist; deny-by-default for source payload fields."""

    allowed_paths: frozenset[str] = field(default_factory=lambda: DEFAULT_CUSTOMER_VISIBLE_PATHS)
    max_age_seconds: int | None = 24 * 60 * 60
    require_shop_scope: bool = True
    allowed_operation_phases: frozenset[str] = field(default_factory=frozenset)
    allow_manual_unbound: bool = True

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

    name = _first_allowed_text(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.name",
        f"{DETAIL_ROOT}.baseCarInfo.carName",
    )
    brand = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.brandName", policy)
    series = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.seriesName", policy)
    model_name = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.modelName", policy)
    if not name:
        name = " ".join(str(value).strip() for value in (brand, series, model_name) if str(value or "").strip())
    if not name:
        return None

    year = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.firstLicensePlateDate", policy)
    mileage = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.mileage", policy)
    condition = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.vehicleCondition", policy)
    exterior_color = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.baseCarInfo.exteriorColor",
        f"{DETAIL_ROOT}.baseCarInfo.color",
    )
    interior_color = _allowed_value(record, f"{DETAIL_ROOT}.baseCarInfo.interiorColor", policy)
    transmission = _first_allowed_value(
        record,
        policy,
        f"{DETAIL_ROOT}.carModelParam.gearbox",
        f"{DETAIL_ROOT}.carModelParam.gearBox",
    )
    displacement = _allowed_value(record, f"{DETAIL_ROOT}.carModelParam.displacement", policy)
    sale_price = _allowed_value(record, f"{DETAIL_ROOT}.carPriceInfo.salePrice", policy)
    annotations = _customer_visible_annotations(record)

    specs_parts = []
    for label, value in (("车况", condition), ("外观颜色", exterior_color), ("内饰颜色", interior_color), ("变速箱", transmission), ("排量", displacement)):
        if value not in (None, ""):
            specs_parts.append(f"{label}:{value}")
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
        "price": sale_price,
        "availability": operation_phase,
        "specs": annotations.get("specs") or "；".join(specs_parts),
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
    if policy.max_age_seconds is None:
        return True
    observed = _detail_pulled_at(record)
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
    return (current - observed_at).total_seconds() <= policy.max_age_seconds


def _detail_pulled_at(record: dict[str, Any]) -> str:
    snapshot = _mapping_at(record, "source_payloads.vehicle_detail")
    return str(snapshot.get("pulled_at") or "") if snapshot else ""


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
        for key in ("bigPictureUrl", "bigPictureLink", "pictureUrl", "pictureLink", "url"):
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
