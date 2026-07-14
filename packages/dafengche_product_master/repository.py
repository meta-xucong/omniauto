"""Storage port and in-memory reference implementation for the portable core."""

from __future__ import annotations

import copy
from typing import Any, Protocol


class MirrorRepository(Protocol):
    def get_by_binding(self, *, shop_code: str, car_id: str) -> dict[str, Any] | None:
        """Return the current record for an explicit Dafengche binding."""

    def upsert(self, record: dict[str, Any]) -> None:
        """Persist a whole mirror envelope atomically."""

    def list_records(self) -> list[dict[str, Any]]:
        """Return current records only; history belongs to host audit storage."""

    def append_audit(self, event: dict[str, Any]) -> None:
        """Persist a non-customer-visible sync or operator audit event."""


class InMemoryMirrorRepository:
    """Reference host adapter used by portability tests and local integrations."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self.audit_events: list[dict[str, Any]] = []

    def get_by_binding(self, *, shop_code: str, car_id: str) -> dict[str, Any] | None:
        for record in self._records.values():
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
            if str(binding.get("shopCode") or "") == str(shop_code) and str(binding.get("carId") or "") == str(car_id):
                return copy.deepcopy(record)
        return None

    def upsert(self, record: dict[str, Any]) -> None:
        record_id = str(record.get("id") or "")
        if not record_id:
            raise ValueError("mirror record id is required")
        self._records[record_id] = copy.deepcopy(record)

    def list_records(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(item) for item in self._records.values()]

    def append_audit(self, event: dict[str, Any]) -> None:
        self.audit_events.append(copy.deepcopy(event))
