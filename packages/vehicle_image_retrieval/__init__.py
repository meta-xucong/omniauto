"""Portable, host-neutral vehicle-image retrieval core.

The package accepts already-produced descriptors and fingerprints.  It never
opens images, calls a model, reads application state, or imports a host app.
"""

from .service import (
    DEFAULT_MATCH_THRESHOLD,
    DEFAULT_MIN_VISUAL_SIMILARITY,
    EXTENSION_KEY,
    apply_vehicle_image_index,
    build_customer_query_descriptor,
    current_vehicle_image_index_state,
    match_vehicle_image_records,
    picture_ref,
    source_picture_fingerprint,
    vehicle_pictures,
)

__all__ = [
    "DEFAULT_MATCH_THRESHOLD",
    "DEFAULT_MIN_VISUAL_SIMILARITY",
    "EXTENSION_KEY",
    "apply_vehicle_image_index",
    "build_customer_query_descriptor",
    "current_vehicle_image_index_state",
    "match_vehicle_image_records",
    "picture_ref",
    "source_picture_fingerprint",
    "vehicle_pictures",
]
