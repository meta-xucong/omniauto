"""Stable generic failure reasons for the optional Vision capability."""

VISION_IMAGE_OBSERVATION_FAILED = "vision_image_observation_failed"
VISION_IMAGE_SLOT_RECONFIRM_FAILED = "vision_image_slot_reconfirm_failed"
VISION_IMAGE_CLIPBOARD_CLEAR_FAILED = "vision_image_clipboard_clear_failed"
VISION_IMAGE_OBSERVATION_TRUNCATED = "vision_image_observation_truncated"
VISION_IMAGE_UNDERSTANDING_SCHEMA_INVALID = (
    "vision_image_understanding_schema_invalid"
)


__all__ = [
    "VISION_IMAGE_CLIPBOARD_CLEAR_FAILED",
    "VISION_IMAGE_OBSERVATION_FAILED",
    "VISION_IMAGE_OBSERVATION_TRUNCATED",
    "VISION_IMAGE_SLOT_RECONFIRM_FAILED",
    "VISION_IMAGE_UNDERSTANDING_SCHEMA_INVALID",
]
