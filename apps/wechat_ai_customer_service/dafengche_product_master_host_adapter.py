"""WeChat host bindings for the portable Dafengche product-master core.

This module is intentionally thin: it supplies the current product-master
storage facade to the reusable core but does not parse source vehicle fields,
author replies, or participate in RPA scheduling.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.product_master import ProductMasterStore
from apps.wechat_ai_customer_service.vehicle_image_retrieval_jobs import enqueue_vehicle_image_index
from packages.dafengche_product_master.repository import MirrorRepository
from packages.vehicle_image_retrieval import source_picture_fingerprint, vehicle_pictures


class ProductMasterStoreMirrorRepository(MirrorRepository):
    """Adapt the existing ``ProductMasterStore`` to the portable repository port."""

    def __init__(self, store: ProductMasterStore) -> None:
        self.store = store

    def get_by_binding(self, *, shop_code: str, car_id: str) -> dict[str, Any] | None:
        for record in self.store.list_items(include_archived=True):
            source = record.get("source") if isinstance(record.get("source"), dict) else {}
            binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
            if str(binding.get("shopCode") or "") == str(shop_code) and str(binding.get("carId") or "") == str(car_id):
                return copy.deepcopy(record)
        return None

    def upsert(self, record: dict[str, Any]) -> None:
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        binding = source.get("binding") if isinstance(source.get("binding"), dict) else {}
        shop_code = str(binding.get("shopCode") or "").strip()
        car_id = str(binding.get("carId") or "").strip()
        previous = self.get_by_binding(shop_code=shop_code, car_id=car_id) if shop_code and car_id else None
        previous_fingerprint = source_picture_fingerprint(vehicle_pictures(previous))
        next_fingerprint = source_picture_fingerprint(vehicle_pictures(record))
        result = self.store.save_item(record)
        if not result.get("ok"):
            raise ValueError(f"unable to save Dafengche mirror record: {result.get('problems') or result.get('message') or result}")
        # The source mirror remains authoritative.  Only after the source
        # payload is durably saved do we request a non-blocking derived index.
        # Any optional vision/configuration failure is intentionally isolated
        # from the official sync transaction.
        if previous_fingerprint != next_fingerprint:
            try:
                enqueue_vehicle_image_index(
                    str(record.get("id") or ""),
                    tenant_id=self.store.tenant_id,
                    cause="dafengche_sync",
                )
            except Exception:
                pass

    def list_records(self) -> list[dict[str, Any]]:
        return self.store.list_items(include_archived=True)

    def append_audit(self, event: dict[str, Any]) -> None:
        root = (self.store.root / "dafengche_sync_audit").resolve()
        if self.store.root.resolve() not in root.parents:
            raise ValueError("Dafengche audit path escapes product-master root")
        created_at = str(event.get("observed_at") or datetime.now().isoformat(timespec="seconds"))
        digest = hashlib.sha256(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
        filename = f"{created_at.replace(':', '-').replace('+', '_')}_{digest}.json"
        path = root / filename
        root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
