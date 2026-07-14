"""Portable mirror, manual-record and customer-evidence application service."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from .client import CAR_DETAIL_API, CAR_PICTURES_API, DafengcheReadOnlyClient
from .projection import CustomerEvidencePolicy, project_customer_evidence
from .repository import MirrorRepository


@dataclass(frozen=True)
class DafengcheSyncScope:
    app_id: str
    operator: str
    shop_code: str
    operation_phases: tuple[str, ...]


class DafengcheProductMaster:
    """Application service that mirrors source payloads and emits safe evidence."""

    def __init__(
        self,
        *,
        repository: MirrorRepository,
        client: DafengcheReadOnlyClient | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.client = client
        self._now = now or (lambda: datetime.now(timezone.utc))

    def sync(self, scope: DafengcheSyncScope) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError("Dafengche sync requires an explicitly configured read-only client")
        if not scope.app_id or not scope.operator or not scope.shop_code:
            raise ValueError("Dafengche sync scope requires app_id, operator and shop_code")
        shop_payload = self.client.get_shop(app_id=scope.app_id, shop_code=scope.shop_code)
        car_ids: list[str] = []
        car_id_list_payloads: list[dict[str, Any]] = []
        for phase in scope.operation_phases:
            car_id_payload = self.client.list_car_ids(
                app_id=scope.app_id,
                operator=scope.operator,
                shop_code=scope.shop_code,
                operation_phase=phase,
            )
            car_id_list_payloads.append(
                {
                    "operationPhase": phase,
                    "payload": copy.deepcopy(car_id_payload),
                    "content_hash": content_hash(car_id_payload),
                }
            )
            car_ids.extend(_extract_car_ids(car_id_payload))
        synced: list[str] = []
        skipped: list[str] = []
        observed_at = _iso(self._now())
        for car_id in _unique(car_ids):
            detail = self.client.get_car_detail(app_id=scope.app_id, operator=scope.operator, car_id=car_id)
            if not isinstance(detail, dict):
                skipped.append(car_id)
                continue
            pictures = self.client.get_car_pictures(app_id=scope.app_id, car_id=car_id)
            existing = self.repository.get_by_binding(shop_code=scope.shop_code, car_id=car_id)
            record = build_dafengche_vehicle_record(
                shop_code=scope.shop_code,
                car_id=car_id,
                detail=detail,
                pictures=pictures,
                observed_at=observed_at,
                existing=existing,
            )
            self.repository.upsert(record)
            synced.append(record["id"])
        event = {
            "type": "dafengche_sync_completed",
            "shopCode": scope.shop_code,
            "observed_at": observed_at,
            "shop_payload": copy.deepcopy(shop_payload),
            "shop_payload_hash": content_hash(shop_payload),
            "car_id_list_payloads": car_id_list_payloads,
            "synced_record_ids": synced,
            "skipped_car_ids": skipped,
        }
        self.repository.append_audit(event)
        return copy.deepcopy(event)

    def list_customer_evidence(
        self,
        *,
        shop_code: str | None,
        policy: CustomerEvidencePolicy | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        result = []
        for record in self.repository.list_records():
            evidence = project_customer_evidence(record, shop_code=shop_code, policy=policy, now=now or self._now())
            if evidence:
                result.append(evidence)
        return result

    def read_mirror(self, *, shop_code: str | None = None) -> list[dict[str, Any]]:
        """Return exact records for an already-authorized host/admin caller."""

        records = []
        for record in self.repository.list_records():
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
            if shop_code and str(binding.get("shopCode") or "") != str(shop_code):
                continue
            records.append(copy.deepcopy(record))
        return records

    def save_manual_vehicle(
        self,
        *,
        record_id: str,
        vehicle_detail_payload: dict[str, Any],
        pictures_payload: Any = None,
        field_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = create_manual_vehicle(
            record_id=record_id,
            vehicle_detail_payload=vehicle_detail_payload,
            pictures_payload=pictures_payload,
            observed_at=_iso(self._now()),
            field_provenance=field_provenance,
        )
        self.repository.upsert(record)
        self.repository.append_audit({"type": "manual_vehicle_saved", "record_id": record_id, "observed_at": _iso(self._now())})
        return copy.deepcopy(record)

    def bind_manual_vehicle(
        self,
        *,
        record_id: str,
        shop_code: str,
        car_id: str,
        operator: str,
        explicit_confirmation: bool,
    ) -> dict[str, Any]:
        """Record an operator-confirmed binding; never infer it from vehicle text."""

        if not explicit_confirmation:
            raise ValueError("manual vehicle binding requires explicit operator confirmation")
        record = next((item for item in self.repository.list_records() if str(item.get("id") or "") == str(record_id)), None)
        if not isinstance(record, dict):
            raise KeyError(f"manual vehicle not found: {record_id}")
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        if str(source.get("type") or "") != "manual":
            raise ValueError("only an unbound manual vehicle may be explicitly bound")
        source["binding"] = {"shopCode": str(shop_code), "carId": str(car_id), "state": "bound"}
        record["source"] = source
        extensions = record.setdefault("extensions", {})
        manual = extensions.setdefault("manual", {})
        manual["binding_confirmation"] = {
            "operator": str(operator),
            "confirmed_at": _iso(self._now()),
            "shopCode": str(shop_code),
            "carId": str(car_id),
        }
        self.repository.upsert(record)
        self.repository.append_audit(
            {
                "type": "manual_vehicle_binding_confirmed",
                "record_id": str(record_id),
                "shopCode": str(shop_code),
                "carId": str(car_id),
                "operator": str(operator),
                "observed_at": _iso(self._now()),
            }
        )
        return copy.deepcopy(record)


def build_dafengche_vehicle_record(
    *,
    shop_code: str,
    car_id: str,
    detail: dict[str, Any],
    pictures: Any,
    observed_at: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create v2 mirror envelope while preserving upstream payloads verbatim."""

    if not shop_code or not car_id:
        raise ValueError("shop_code and car_id are required for a Dafengche binding")
    prior = copy.deepcopy(existing) if isinstance(existing, dict) else {}
    metadata = prior.get("metadata") if isinstance(prior.get("metadata"), dict) else {}
    prior_source = prior.get("source") if isinstance(prior.get("source"), dict) else {}
    prior_marker = prior_source.get("marker") if isinstance(prior_source.get("marker"), dict) else {}
    record = {
        "schema_version": 2,
        "category_id": "products",
        "id": str(prior.get("id") or mirror_record_id(shop_code, car_id)),
        "status": str(prior.get("status") or "active"),
        "source": {
            "type": "dafengche",
            "provider": "dafengche",
            "marker": {
                **copy.deepcopy(prior_marker),
                "ingest_channel": "dafengche_api",
                "original_source_type": str(prior_marker.get("original_source_type") or "dafengche"),
                "recorded_at": str(prior_marker.get("recorded_at") or observed_at),
                "last_observed_at": observed_at,
            },
            "binding": {"shopCode": str(shop_code), "carId": str(car_id), "state": "bound"},
        },
        "source_payloads": {
            "vehicle_detail": _snapshot(CAR_DETAIL_API, detail, observed_at),
            "vehicle_pictures": _snapshot(CAR_PICTURES_API, pictures, observed_at),
        },
        "extensions": copy.deepcopy(prior.get("extensions") if isinstance(prior.get("extensions"), dict) else {}),
        "runtime": copy.deepcopy(prior.get("runtime") if isinstance(prior.get("runtime"), dict) else {}),
        "metadata": {
            **copy.deepcopy(metadata),
            "created_at": str(metadata.get("created_at") or observed_at),
            "updated_at": observed_at,
            "source_last_synced_at": observed_at,
        },
    }
    return record


def create_manual_vehicle(
    *,
    record_id: str,
    vehicle_detail_payload: dict[str, Any],
    pictures_payload: Any = None,
    observed_at: str | None = None,
    field_provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an unbound manual v2 record using the same source-payload shape."""

    if not record_id:
        raise ValueError("manual vehicle record_id is required")
    timestamp = observed_at or _iso(datetime.now(timezone.utc))
    return {
        "schema_version": 2,
        "category_id": "products",
        "id": str(record_id),
        "status": "active",
        "source": {
            "type": "manual",
            "provider": "manual",
            "marker": {
                "ingest_channel": "manual_input",
                "original_source_type": "manual",
                "recorded_at": timestamp,
            },
            "binding": {"state": "unbound"},
        },
        "source_payloads": {
            "vehicle_detail": _snapshot("manual.dafengche_shaped_vehicle_detail", vehicle_detail_payload, timestamp),
            "vehicle_pictures": _snapshot("manual.dafengche_shaped_vehicle_pictures", pictures_payload or [], timestamp),
        },
        "extensions": {"manual": {"field_provenance": copy.deepcopy(field_provenance or {})}},
        "runtime": {},
        "metadata": {"created_at": timestamp, "updated_at": timestamp},
    }


def mirror_record_id(shop_code: str, car_id: str) -> str:
    digest = hashlib.sha256(f"{shop_code}\u0000{car_id}".encode("utf-8")).hexdigest()[:24]
    return f"dafengche_{digest}"


def content_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _snapshot(api: str, payload: Any, observed_at: str) -> dict[str, Any]:
    return {"api": api, "payload": copy.deepcopy(payload), "pulled_at": observed_at, "content_hash": content_hash(payload)}


def _extract_car_ids(payload: Any) -> list[str]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        values = payload.get("carIds") or payload.get("ids") or payload.get("list") or []
    else:
        values = []
    result: list[str] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("carId") or value.get("id")
        text = str(value or "").strip()
        if text:
            result.append(text)
    return result


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds")
