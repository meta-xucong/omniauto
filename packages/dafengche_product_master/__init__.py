"""Portable, read-only Dafengche vehicle product-master core.

The package deliberately has no dependency on WeChat, RPA, a database driver,
or a particular scheduler. Hosts provide storage and transport through ports.
"""

from .client import (
    CAR_DETAIL_API,
    CAR_IDS_API,
    CAR_PICTURES_API,
    SHOP_API,
    DafengcheCredentials,
    DafengcheReadOnlyClient,
    DafengcheTransport,
    build_signature,
)
from .projection import CustomerEvidencePolicy, project_customer_evidence, project_legacy_record
from .admin_projection import apply_admin_vehicle_update, build_admin_vehicle_view, build_legacy_data_projection, is_v2_vehicle_record
from .repository import InMemoryMirrorRepository, MirrorRepository
from .service import DafengcheProductMaster, DafengcheSyncScope, create_manual_vehicle

__all__ = [
    "CAR_DETAIL_API",
    "CAR_IDS_API",
    "CAR_PICTURES_API",
    "SHOP_API",
    "CustomerEvidencePolicy",
    "DafengcheCredentials",
    "DafengcheProductMaster",
    "DafengcheReadOnlyClient",
    "DafengcheSyncScope",
    "DafengcheTransport",
    "InMemoryMirrorRepository",
    "MirrorRepository",
    "build_signature",
    "apply_admin_vehicle_update",
    "build_admin_vehicle_view",
    "build_legacy_data_projection",
    "create_manual_vehicle",
    "project_customer_evidence",
    "project_legacy_record",
    "is_v2_vehicle_record",
]
