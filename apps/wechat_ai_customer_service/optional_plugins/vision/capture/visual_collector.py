"""Vision-private current-turn visual occurrence locating and acquiring.

The collector owns one bounded capture/OCR/parse loop.  In locate mode it only
returns existing structural image messages.  In acquire mode it runs the same
loop, then performs the one allowed right-click/menu/clipboard copy sequence for
the selected visual group.  It never calls a model provider or persists state.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any, Callable

from PIL import Image, ImageOps

from ..clipboard_payload import EphemeralClipboardImage, read_current_clipboard_image
from ..understanding.provider import MAX_IMAGE_PAYLOAD_BYTES
from .surface import visual_image_envelopes_from_bubbles
from .visual_anchor import match_visual_occurrence_groups, select_current_turn_visual_group
from .wechat import (
    capture_context_menu_image,
    click_context_menu_item,
    clipboard_sequence_number,
    clamp_bounds,
    detect_visual_image_bubbles,
    extract_chat_time_markers,
    find_copy_menu_item,
)


MAX_LOCATE_SCROLL_STEPS = 6
MAX_LOCATE_SNAPSHOTS = 8
MAX_LOCATE_SECONDS = 12.0
MAX_GROUP_WIRE_BYTES = 12 * 1024 * 1024
MAX_DHASH_DISTANCE = 16
MAX_ASPECT_RATIO_RELATIVE_ERROR = 0.18
MAX_COLOR_GRID_AVG_DISTANCE = 48.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _now() -> float:
    return time.monotonic()


def _int_limit(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or _clean(value) == "":
        raw = default
    else:
        raw = int(value)
    return max(minimum, min(raw, maximum))


def _float_limit(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    if value is None or _clean(value) == "":
        raw = default
    else:
        raw = float(value)
    return max(minimum, min(raw, maximum))


def _locate_result(
    *,
    ok: bool,
    state: str,
    reason: str,
    scroll_steps: int,
    snapshot_count: int,
    restored_to_latest: bool,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "ok": bool(ok),
        "online": True,
        "adapter": "win32_ocr",
        "state": str(state or "vision_visual_group_locate_failed"),
        "reason": str(reason or state or "visual_group_no_candidate"),
        "assets": [],
        "messages": list(messages or []),
        "locate": {
            "scroll_steps": int(scroll_steps),
            "snapshot_count": int(snapshot_count),
            "restored_to_latest": bool(restored_to_latest),
        },
    }


def _strip_locator_private_fields(message: dict[str, Any]) -> dict[str, Any]:
    public = dict(message)
    public.pop("_vision_bounds", None)
    public.pop("_vision_has_self_message_after", None)
    public.pop("_vision_has_self_message_before", None)
    public.pop("_vision_following_text_key", None)
    public.pop("_vision_preceding_text_key", None)
    public.pop("_vision_occurrence_ordinal", None)
    public.pop("_vision_transaction_ordinal", None)
    return public


def _failure_payload(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "state": "vision_visual_group_acquire_failed",
        "reason": str(reason or "vision_visual_group_acquire_failed"),
    }


def _inset_bounds(bounds: list[int] | tuple[int, int, int, int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = clamp_bounds(bounds, image_size)
    width = right - left
    height = bottom - top
    inset_x = max(2, int(width * 0.04))
    inset_y = max(2, int(height * 0.04))
    if width - inset_x * 2 >= 24 and height - inset_y * 2 >= 24:
        return left + inset_x, top + inset_y, right - inset_x, bottom - inset_y
    return left, top, right, bottom


def _dhash64(image: Image.Image) -> int:
    resized = ImageOps.grayscale(image).resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(resized.getdata())
    value = 0
    for row in range(8):
        for col in range(8):
            value <<= 1
            if pixels[row * 9 + col] > pixels[row * 9 + col + 1]:
                value |= 1
    return value


def _image_fingerprint(image: Image.Image) -> dict[str, Any]:
    normalized = ImageOps.exif_transpose(image).convert("RGB")
    normalized.load()
    width, height = normalized.size
    if width <= 0 or height <= 0:
        return {}
    color_grid = [
        channel
        for pixel in normalized.resize((3, 3), Image.Resampling.LANCZOS).getdata()
        for channel in pixel[:3]
    ]
    return {
        "orientation": "portrait" if height > width else "landscape" if width > height else "square",
        "aspect_ratio": float(width) / float(height),
        "dhash64": _dhash64(normalized),
        "color_grid": color_grid,
    }


def _crop_fingerprint(screenshot: Image.Image, bounds: list[int] | tuple[int, int, int, int]) -> dict[str, Any]:
    left, top, right, bottom = _inset_bounds(bounds, getattr(screenshot, "size", (0, 0)))
    crop = screenshot.crop((left, top, right, bottom))
    try:
        return _image_fingerprint(crop)
    finally:
        try:
            crop.close()
        except Exception:
            pass


def _payload_fingerprint(payload: EphemeralClipboardImage) -> dict[str, Any]:
    try:
        with Image.open(io.BytesIO(bytes(payload.image_bytes))) as image:
            image.load()
            bounds = [0, 0, int(image.width), int(image.height)]
            left, top, right, bottom = _inset_bounds(bounds, image.size)
            crop = image.crop((left, top, right, bottom))
            try:
                return _image_fingerprint(crop)
            finally:
                crop.close()
    except Exception:
        return {}


def _hamming64(left: int, right: int) -> int:
    return int(left ^ right).bit_count()


def _color_grid_distance(left: Any, right: Any) -> float:
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right) or not left:
        return float("inf")
    try:
        return sum(abs(int(a) - int(b)) for a, b in zip(left, right)) / float(len(left))
    except (TypeError, ValueError):
        return float("inf")


def _fingerprint_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if not expected or not actual:
        return False
    if str(expected.get("orientation") or "") != str(actual.get("orientation") or ""):
        return False
    try:
        expected_ratio = float(expected.get("aspect_ratio") or 0.0)
        actual_ratio = float(actual.get("aspect_ratio") or 0.0)
    except (TypeError, ValueError):
        return False
    if expected_ratio <= 0.0 or actual_ratio <= 0.0:
        return False
    if abs(expected_ratio - actual_ratio) / max(expected_ratio, actual_ratio) > MAX_ASPECT_RATIO_RELATIVE_ERROR:
        return False
    if _color_grid_distance(expected.get("color_grid"), actual.get("color_grid")) > MAX_COLOR_GRID_AVG_DISTANCE:
        return False
    try:
        return _hamming64(int(expected.get("dhash64") or 0), int(actual.get("dhash64") or 0)) <= MAX_DHASH_DISTANCE
    except (TypeError, ValueError):
        return False


def _encode_payload_for_worker(payload: EphemeralClipboardImage) -> dict[str, Any] | None:
    raw = bytes(payload.image_bytes)
    if not raw or len(raw) > MAX_IMAGE_PAYLOAD_BYTES:
        return None
    return {
        "mime_type": str(payload.mime_type or "image/png"),
        "width": int(payload.width or 0),
        "height": int(payload.height or 0),
        "data": base64.b64encode(raw).decode("ascii"),
    }


def _menu_item_near_anchor(
    menu_item: dict[str, Any] | None,
    *,
    anchor: dict[str, Any],
    image_size: tuple[int, int],
) -> dict[str, Any] | None:
    if not menu_item:
        return None
    try:
        anchor_x = int(float(anchor.get("x") or 0))
        anchor_y = int(float(anchor.get("y") or 0))
        item_x = int(float(menu_item.get("x") or 0))
        item_y = int(float(menu_item.get("y") or 0))
    except (TypeError, ValueError):
        return None
    width, height = image_size
    if item_x < 0 or item_y < 0 or item_x > width or item_y > height:
        return None
    if abs(item_x - anchor_x) > 320 or abs(item_y - anchor_y) > 360:
        return None
    return dict(menu_item)


def _candidate_from_surface_message(
    message: dict[str, Any],
    *,
    request: dict[str, Any],
) -> dict[str, Any]:
    message_id = _clean(message.get("message_id") or message.get("id"))
    candidate = dict(message)
    candidate.update(
        {
            "session_key": _clean(request.get("session_key")),
            "target_identity": _clean(request.get("target_identity")),
            "conversation_type": _clean(request.get("conversation_type")),
            "structural_message_id": message_id,
            "source_message_id": _clean(message.get("source_message_id")),
            "visual_structural_key": message_id,
            "wechat_message_time": _clean(
                message.get("wechat_message_time")
                or message.get("screen_time_text")
                or message.get("time")
            ),
            "following_text_key": _clean(
                message.get("_vision_following_text_key")
                or message.get("_vision_following_text_id")
            ),
            "preceding_text_key": _clean(
                message.get("_vision_preceding_text_key")
                or message.get("_vision_preceding_text_id")
            ),
            "occurrence_ordinal": _clean(
                message.get("_vision_occurrence_ordinal")
                or message.get("occurrence_ordinal")
            ),
            "has_self_message_after": bool(
                message.get("has_self_message_after")
                or message.get("_vision_has_self_message_after")
            ),
            "bounds": message.get("_vision_bounds") or message.get("bounds") or [],
        }
    )
    return candidate


def _message_identity(message: dict[str, Any]) -> str:
    for key in ("message_id", "id", "legacy_message_id", "original_message_id", "canonical_input_id"):
        value = _clean(message.get(key))
        if value:
            return value
    return ""


def _message_side(message: dict[str, Any]) -> str:
    side = _clean(message.get("sender_role") or message.get("sender")).lower()
    if side in {"self", "assistant", "service", "bot"}:
        return "self"
    return side


def _text_key(value: Any) -> str:
    return "".join(_clean(value).split()).lower()


def _text_bounds(message: dict[str, Any]) -> tuple[int, int] | None:
    rect = message.get("bubble_rect") if isinstance(message.get("bubble_rect"), dict) else {}
    if not rect:
        return None
    try:
        top = int(float(rect.get("top") or 0))
        bottom = int(float(rect.get("bottom") or 0))
    except (TypeError, ValueError):
        return None
    if bottom <= top:
        return None
    return top, bottom


def _text_details(messages: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        if _clean(message.get("type") or "text").lower() != "text":
            continue
        identity = _message_identity(message)
        if not identity:
            continue
        bounds = _text_bounds(message)
        details[identity] = {
            "side": _message_side(message),
            "key": _text_key(message.get("content")),
            "top": bounds[0] if bounds else 0,
            "bottom": bounds[1] if bounds else 0,
        }
    return details


def _enrich_surface_relations(
    surface_messages: list[dict[str, Any]],
    text_details: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    self_rows = [
        item
        for item in text_details.values()
        if item.get("side") == "self"
    ]
    for message in surface_messages:
        item = dict(message)
        following_id = _clean(item.get("_vision_following_text_id"))
        preceding_id = _clean(item.get("_vision_preceding_text_id"))
        if following_id and following_id in text_details:
            item["_vision_following_text_key"] = _clean(text_details[following_id].get("key"))
        if preceding_id and preceding_id in text_details:
            item["_vision_preceding_text_key"] = _clean(text_details[preceding_id].get("key"))
        try:
            top = int(float((item.get("_vision_bounds") or [0, 0, 0, 0])[1]))
        except (TypeError, ValueError, IndexError):
            top = 0
        item["_vision_has_self_message_before"] = any(
            int(row.get("bottom") or 0) <= top + 6
            for row in self_rows
        )
        enriched.append(item)
    return enriched


def _turn_bound_surface_messages(
    surface_messages: list[dict[str, Any]],
    *,
    explicit_image_pending: bool,
    anchor_text_key: str,
    anchor_message_id: str,
    allow_unanchored_single: bool,
) -> tuple[list[dict[str, Any]], str]:
    customer_messages = [
        item
        for item in surface_messages
        if _clean(item.get("visual_side") or item.get("sender_role") or item.get("sender")).lower()
        == "customer"
        and not bool(item.get("_vision_has_self_message_after"))
    ]
    if anchor_text_key:
        matched: list[dict[str, Any]] = []
        for item in customer_messages:
            if _text_key(item.get("_vision_following_text_key")) != _text_key(anchor_text_key):
                continue
            rebound = dict(item)
            if anchor_message_id:
                rebound["_vision_following_text_id"] = anchor_message_id
            matched.append(rebound)
        if matched:
            return matched, "following_text_anchor"
        return [], "visual_group_anchor_not_found"

    if not explicit_image_pending:
        return [], "visual_group_anchor_missing"
    if allow_unanchored_single and len(customer_messages) == 1:
        return customer_messages, "explicit_single_current_image"
    boundary_messages = [
        item
        for item in customer_messages
        if bool(item.get("_vision_has_self_message_before"))
    ]
    if boundary_messages and len(boundary_messages) == len(customer_messages):
        return boundary_messages, "explicit_self_boundary_group"
    if customer_messages:
        return [], "visual_group_ambiguous"
    return [], "visual_group_no_candidate"


def _message_top(message: dict[str, Any]) -> int:
    try:
        return int(float((message.get("_vision_bounds") or message.get("bounds") or [0, 0, 0, 0])[1]))
    except (TypeError, ValueError, IndexError):
        return 0


def _with_transaction_ordinals(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = [(index, item) for index, item in enumerate(messages) if isinstance(item, dict)]
    ordered = sorted(indexed, key=lambda pair: (_message_top(pair[1]), pair[0]))
    ordinals = {index: str(ordinal) for ordinal, (index, _item) in enumerate(ordered)}
    enriched: list[dict[str, Any]] = []
    for index, item in indexed:
        next_item = dict(item)
        next_item["_vision_occurrence_ordinal"] = ordinals.get(index, "")
        enriched.append(next_item)
    return enriched


def _validate_target_still_active(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    session_key: str,
    conversation_type: str,
    exact: bool,
) -> str:
    validator = getattr(sidecar_ops, "validate_active_send_target_for_identity", None)
    if not callable(validator):
        return ""
    physical_conversation_type = _clean(conversation_type)
    try:
        from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (
            physical_rpa_identity_kwargs,
        )

        physical_identity = physical_rpa_identity_kwargs(
            {"session_key": session_key, "conversation_type": conversation_type}
        )
        physical_conversation_type = _clean(physical_identity.get("conversation_type"))
    except Exception:
        pass
    try:
        result = validator(
            hwnd,
            target_name,
            exact=bool(exact),
            artifact_dir=None,
            session_key=session_key,
            conversation_type=physical_conversation_type,
        )
    except Exception:
        return "vision_target_changed_during_visual_group_locate"
    if isinstance(result, dict) and result.get("ok"):
        return ""
    return "vision_target_changed_during_visual_group_locate"


def _capture_visual_group_frame(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    request: dict[str, Any],
    side_filter: str,
    max_images: int,
    label: str,
    explicit_image_pending: bool,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    allow_unanchored_single: bool = False,
) -> dict[str, Any]:
    screenshot, _unused_path = sidecar_ops.capture_wechat(
        hwnd,
        artifact_dir=None,
        label=label,
    )
    ocr_items = sidecar_ops.run_ocr(screenshot)
    image_size = tuple(getattr(screenshot, "size", (0, 0)))
    messages = sidecar_ops.parse_messages_from_ocr(
        ocr_items,
        image_size,
        target=target_name,
    )
    blocking_reason = sidecar_ops.blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "reason": str(blocking_reason),
            "state": "vision_visual_group_surface_blocked",
            "messages": [],
            "selection": {},
        }
    bubbles = detect_visual_image_bubbles(
        screenshot,
        messages=messages,
        max_images=8,
        side_filter=side_filter,
        time_markers=extract_chat_time_markers(ocr_items, image_size),
    )
    surface_messages = visual_image_envelopes_from_bubbles(
        bubbles,
        messages,
        target=target_name,
        include_private_details=True,
    )
    surface_messages = _enrich_surface_relations(
        surface_messages,
        _text_details(messages),
    )
    turn_messages, turn_reason = _turn_bound_surface_messages(
        surface_messages,
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        allow_unanchored_single=allow_unanchored_single,
    )
    if not turn_messages:
        return {
            "ok": False,
            "reason": turn_reason,
            "state": "vision_visual_group_not_found",
            "messages": [],
            "selection": {},
        }
    turn_messages = _with_transaction_ordinals(turn_messages)
    by_id = {
        _clean(item.get("message_id") or item.get("id")): item
        for item in turn_messages
        if isinstance(item, dict)
    }
    candidates = [
        _candidate_from_surface_message(item, request=request)
        for item in turn_messages
        if isinstance(item, dict)
    ]
    selection = select_current_turn_visual_group(
        candidates,
        request=request,
        max_images=max_images,
    )
    if not selection.get("ok"):
        return {
            "ok": False,
            "reason": str(selection.get("reason") or "visual_group_no_candidate"),
            "state": "vision_visual_group_not_found",
            "messages": [],
            "selection": selection,
        }
    selected_messages: list[dict[str, Any]] = []
    for occurrence in selection.get("occurrences") or []:
        if not isinstance(occurrence, dict):
            continue
        message_id = _clean(occurrence.get("structural_message_id"))
        source = by_id.get(message_id)
        if source:
            selected_messages.append(_strip_locator_private_fields(source))
    return {
        "ok": bool(selected_messages),
        "reason": "visual_group_selected" if selected_messages else "visual_group_no_candidate",
        "state": "vision_visual_group_selected" if selected_messages else "vision_visual_group_not_found",
        "messages": selected_messages,
        "selection": selection,
        "_private_messages": [
            by_id.get(_clean(item.get("structural_message_id")))
            for item in (selection.get("occurrences") or [])
            if isinstance(item, dict) and by_id.get(_clean(item.get("structural_message_id")))
        ],
        "_occurrences": [dict(item) for item in (selection.get("occurrences") or []) if isinstance(item, dict)],
        "_screenshot": screenshot,
    }


def _fresh_group_matches(
    known: list[dict[str, Any]],
    current: list[dict[str, Any]],
    request: dict[str, Any],
    max_images: int,
) -> bool:
    known_group = [dict(item) for item in known if isinstance(item, dict)]
    current_group = [dict(item) for item in current if isinstance(item, dict)]
    if not known_group or len(known_group) != len(current_group):
        return False
    if len(current_group) > max(1, int(max_images or 1)):
        return False
    match = match_visual_occurrence_groups(
        known_group,
        current_group,
        request=request,
        max_images=max_images,
    )
    if not match.get("ok") or match.get("status") != "no_delta":
        return False
    matches = [item for item in (match.get("matches") or []) if isinstance(item, dict)]
    if len(matches) != len(known_group) or len(matches) != len(current_group):
        return False
    def _match_index(item: dict[str, Any], key: str) -> int:
        try:
            return int(item.get(key))
        except (TypeError, ValueError):
            return -1

    ordered_current = [
        _match_index(item, "current_index")
        for item in sorted(matches, key=lambda item: _match_index(item, "known_index"))
    ]
    return ordered_current == list(range(len(known_group)))


def _fresh_reanchor_frame(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    request: dict[str, Any],
    side_filter: str,
    max_images: int,
    explicit_image_pending: bool,
    anchor_text_key: str,
    anchor_message_id: str,
    known_occurrences: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    frame = _capture_visual_group_frame(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        target_name=target_name,
        request=request,
        side_filter=side_filter,
        max_images=max_images,
        label=label,
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        allow_unanchored_single=bool(
            explicit_image_pending
            and not anchor_text_key
            and len(known_occurrences) == 1
        ),
    )
    if not frame.get("ok"):
        return frame
    current = [dict(item) for item in (frame.get("_occurrences") or []) if isinstance(item, dict)]
    if not _fresh_group_matches(known_occurrences, current, request, max_images):
        return {
            "ok": False,
            "reason": "visual_group_reanchor_mismatch",
            "state": "vision_visual_group_not_found",
            "messages": [],
            "selection": {},
        }
    return frame


def _read_clipboard_payload(
    *,
    sidecar_ops: Any,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    reader = getattr(sidecar_ops, "read_current_clipboard_bitmap", None)
    if not callable(reader):
        reader = getattr(sidecar_ops, "read_current_bitmap", None)
    return read_current_clipboard_image(
        transaction,
        clipboard_reader=reader if callable(reader) else None,
        sequence_provider=lambda: clipboard_sequence_number(sidecar_ops),
    )


def _copy_one_visual_message(
    *,
    sidecar_ops: Any,
    hwnd: int,
    screenshot: Image.Image,
    message: dict[str, Any],
    occurrence: dict[str, Any],
    index: int,
    validate_before_menu_click: Callable[[], str] | None = None,
) -> dict[str, Any]:
    bounds = [int(value) for value in (message.get("_vision_bounds") or message.get("bounds") or [])[:4]]
    if len(bounds) != 4:
        return _failure_payload("visual_group_candidate_bounds_missing")
    left, top, right, bottom = clamp_bounds(bounds, getattr(screenshot, "size", (0, 0)))
    if right <= left or bottom <= top:
        return _failure_payload("visual_group_candidate_bounds_missing")
    anchor = {"x": int((left + right) / 2), "y": int((top + bottom) / 2)}
    expected_fingerprint = _crop_fingerprint(screenshot, [left, top, right, bottom])
    if not expected_fingerprint:
        return _failure_payload("visual_group_candidate_fingerprint_missing")
    sequence_before = clipboard_sequence_number(sidecar_ops)
    if sequence_before is None:
        return _failure_payload("clipboard_sequence_unavailable")
    right_click = sidecar_ops.human_window_image_right_click_in_bounds(
        hwnd,
        int(anchor.get("x") or 0),
        int(anchor.get("y") or 0),
        bounds=[left, top, right, bottom],
        action_name="visual_group_image_context_right_click",
    )
    right_click = right_click if isinstance(right_click, dict) else {"ok": False}
    sleeper = getattr(sidecar_ops, "humanized_action_sleep", None)
    if callable(sleeper):
        sleeper(360, 720)
    try:
        menu_screenshot, _menu_path, _menu_capture_method = capture_context_menu_image(
            sidecar_ops=sidecar_ops,
            hwnd=hwnd,
            artifact_dir="",
            label=f"visual_group_context_menu_{index}",
        )
        menu_items = sidecar_ops.run_ocr(menu_screenshot)
        menu_size = getattr(menu_screenshot, "size", getattr(screenshot, "size", (0, 0)))
        copy_target = _menu_item_near_anchor(
            find_copy_menu_item(menu_items, menu_size),
            anchor=anchor,
            image_size=menu_size,
        )
    except Exception:
        copy_target = None
    if not right_click.get("ok") or not copy_target:
        try:
            sidecar_ops.key_press(sidecar_ops.win32con.VK_ESCAPE)
        except Exception:
            pass
        return _failure_payload("image_context_menu_copy_item_missing")
    if callable(validate_before_menu_click):
        menu_guard_reason = validate_before_menu_click()
        if menu_guard_reason:
            try:
                sidecar_ops.key_press(sidecar_ops.win32con.VK_ESCAPE)
            except Exception:
                pass
            return _failure_payload(menu_guard_reason)
    menu_click = click_context_menu_item(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        menu_target=copy_target,
        action_name="visual_group_image_copy_menu_click",
    )
    menu_click = menu_click if isinstance(menu_click, dict) else {"ok": False}
    if not menu_click.get("ok"):
        try:
            sidecar_ops.key_press(sidecar_ops.win32con.VK_ESCAPE)
        except Exception:
            pass
        return _failure_payload("image_context_menu_copy_click_failed")
    sequence_after: int | None = None
    for _attempt in range(6):
        if callable(sleeper):
            sleeper(80, 140)
        candidate_sequence = clipboard_sequence_number(sidecar_ops)
        if candidate_sequence is not None and candidate_sequence != sequence_before:
            sequence_after = candidate_sequence
            break
    if sequence_after is None:
        return _failure_payload("clipboard_sequence_unchanged_after_copy")
    transaction = {
        "status": "copied",
        "right_click_ok": True,
        "menu_copy_confirmed": True,
        "clipboard_sequence_changed": True,
        "clipboard_sequence_after": sequence_after,
        "visual_side": "customer",
    }
    read_result = _read_clipboard_payload(
        sidecar_ops=sidecar_ops,
        transaction=transaction,
    )
    payload = read_result.get("image") if isinstance(read_result, dict) else None
    if not isinstance(payload, EphemeralClipboardImage):
        return _failure_payload(str((read_result or {}).get("reason") or "clipboard_current_content_not_bitmap"))
    actual_fingerprint = _payload_fingerprint(payload)
    if not _fingerprint_matches(expected_fingerprint, actual_fingerprint):
        payload.release()
        return _failure_payload("clipboard_image_fingerprint_mismatch")
    encoded = _encode_payload_for_worker(payload)
    payload.release()
    if encoded is None:
        return _failure_payload("clipboard_current_image_invalid")
    encoded["message_id"] = _clean(occurrence.get("structural_message_id"))
    return {
        "ok": True,
        "state": "visual_group_image_copied",
        "reason": "visual_group_image_copied",
        "payload": encoded,
        "transaction": transaction,
    }


def _acquire_visual_group_payloads(
    *,
    sidecar_ops: Any,
    hwnd: int,
    frame: dict[str, Any],
    fresh_reanchor: Callable[[], dict[str, Any]],
    validate_before_right_click: Callable[[], str],
) -> dict[str, Any]:
    messages = [dict(item) for item in (frame.get("_private_messages") or []) if isinstance(item, dict)]
    occurrences = [dict(item) for item in (frame.get("_occurrences") or []) if isinstance(item, dict)]
    screenshot = frame.get("_screenshot")
    if not isinstance(screenshot, Image.Image) or not messages or len(messages) != len(occurrences):
        return _failure_payload("visual_group_acquire_selection_missing")
    payloads: list[dict[str, Any]] = []
    total_wire_bytes = 0

    for index, (message, occurrence) in enumerate(zip(messages, occurrences)):
        action_reason = validate_before_right_click()
        if action_reason:
            return _failure_payload(action_reason)
        copied = _copy_one_visual_message(
            sidecar_ops=sidecar_ops,
            hwnd=hwnd,
            screenshot=screenshot,
            message=message,
            occurrence=occurrence,
            index=index,
            validate_before_menu_click=validate_before_right_click,
        )
        if not copied.get("ok") and copied.get("reason") == "clipboard_image_fingerprint_mismatch":
            fresh = fresh_reanchor()
            if not fresh.get("ok"):
                return _failure_payload(str(fresh.get("reason") or "visual_group_reanchor_mismatch"))
            if fresh.get("ok"):
                fresh_messages = [dict(item) for item in (fresh.get("_private_messages") or []) if isinstance(item, dict)]
                fresh_occurrences = [dict(item) for item in (fresh.get("_occurrences") or []) if isinstance(item, dict)]
                fresh_screenshot = fresh.get("_screenshot")
                if len(fresh_messages) == len(messages) and len(fresh_occurrences) == len(occurrences) and isinstance(fresh_screenshot, Image.Image):
                    messages = fresh_messages
                    occurrences = fresh_occurrences
                    screenshot = fresh_screenshot
                    action_reason = validate_before_right_click()
                    if action_reason:
                        return _failure_payload(action_reason)
                    copied = _copy_one_visual_message(
                        sidecar_ops=sidecar_ops,
                        hwnd=hwnd,
                        screenshot=screenshot,
                        message=messages[index],
                        occurrence=occurrences[index],
                        index=index,
                        validate_before_menu_click=validate_before_right_click,
                    )
        if not copied.get("ok"):
            return _failure_payload(str(copied.get("reason") or "visual_group_image_copy_failed"))
        payload = copied.get("payload") if isinstance(copied.get("payload"), dict) else {}
        encoded = str(payload.get("data") or "")
        total_wire_bytes += len(encoded.encode("ascii", errors="ignore"))
        if total_wire_bytes > MAX_GROUP_WIRE_BYTES:
            return _failure_payload("visual_group_wire_payload_too_large")
        payloads.append(dict(payload))
    if not payloads:
        return _failure_payload("visual_group_acquire_selection_missing")
    return {
        "ok": True,
        "state": "vision_visual_group_acquired",
        "reason": "visual_group_acquired",
        "_private_image_payloads": payloads,
        "transaction": {
            "status": "clipboard_read",
            "image_count": len(payloads),
            "clipboard_sequence_changed": True,
            "clipboard_content_read": True,
            "clipboard_image_valid": True,
            "visual_side": "customer",
        },
    }


def _collect_current_turn_visual_group(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    session_key: str,
    conversation_type: str,
    side_filter: str = "customer",
    max_images: int = 3,
    explicit_image_pending: bool = False,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    exact: bool = True,
    max_scroll_steps: int = MAX_LOCATE_SCROLL_STEPS,
    max_snapshots: int = MAX_LOCATE_SNAPSHOTS,
    max_seconds: float = MAX_LOCATE_SECONDS,
    acquire: bool = False,
) -> dict[str, Any]:
    """Locate or acquire the current customer visual group using one collector loop."""

    request = {
        "session_key": _clean(session_key),
        "target_identity": _clean(target_name),
        "conversation_type": _clean(conversation_type),
    }
    if not all(request.values()):
        return _locate_result(
            ok=False,
            state="vision_visual_group_locate_failed",
            reason="visual_group_request_scope_missing",
            scroll_steps=0,
            snapshot_count=0,
            restored_to_latest=False,
        )

    clean_side = _clean(side_filter).lower() or "customer"
    if clean_side not in {"customer", "all"}:
        clean_side = "customer"
    image_limit = max(1, min(int(max_images or 1), 3))
    scroll_limit = _int_limit(
        max_scroll_steps,
        default=MAX_LOCATE_SCROLL_STEPS,
        minimum=0,
        maximum=MAX_LOCATE_SCROLL_STEPS,
    )
    snapshot_limit = _int_limit(
        max_snapshots,
        default=MAX_LOCATE_SNAPSHOTS,
        minimum=1,
        maximum=MAX_LOCATE_SNAPSHOTS,
    )
    seconds_limit = _float_limit(
        max_seconds,
        default=MAX_LOCATE_SECONDS,
        minimum=0.5,
        maximum=MAX_LOCATE_SECONDS,
    )
    started = _now()
    snapshot_count = 0
    scroll_steps = 0
    did_scroll = False
    restore_ok = True
    target_drift_detected = False
    result: dict[str, Any] | None = None

    def elapsed() -> float:
        return _now() - started

    def snapshot_budget_reason() -> str:
        if snapshot_count >= snapshot_limit:
            return "visual_group_snapshot_budget_exhausted"
        if elapsed() > seconds_limit:
            return "visual_group_time_budget_exhausted"
        return ""

    def validate_target_only() -> str:
        nonlocal target_drift_detected
        target_reason = _validate_target_still_active(
            sidecar_ops=sidecar_ops,
            hwnd=hwnd,
            target_name=target_name,
            session_key=session_key,
            conversation_type=conversation_type,
            exact=exact,
        )
        if target_reason:
            target_drift_detected = True
        return target_reason

    def validate_before_new_snapshot() -> str:
        return snapshot_budget_reason() or validate_target_only()

    def validate_before_right_click() -> str:
        if elapsed() > seconds_limit:
            return "visual_group_time_budget_exhausted"
        return validate_target_only()

    def fresh_reanchor_with_budget(
        *,
        known_occurrences: list[dict[str, Any]],
        label: str,
    ) -> dict[str, Any]:
        nonlocal snapshot_count
        budget_reason = validate_before_new_snapshot()
        if budget_reason:
            return {
                "ok": False,
                "reason": budget_reason,
                "state": "vision_visual_group_not_found",
                "messages": [],
                "selection": {},
            }
        fresh = _fresh_reanchor_frame(
            sidecar_ops=sidecar_ops,
            hwnd=hwnd,
            target_name=target_name,
            request=request,
            side_filter=clean_side,
            max_images=image_limit,
            explicit_image_pending=explicit_image_pending,
            anchor_text_key=anchor_text_key,
            anchor_message_id=anchor_message_id,
            known_occurrences=known_occurrences,
            label=label,
        )
        snapshot_count += 1
        return fresh

    try:
        while snapshot_count < snapshot_limit and elapsed() <= seconds_limit:
            target_reason = validate_target_only()
            if target_reason:
                result = _locate_result(
                    ok=False,
                    state="vision_visual_group_locate_failed",
                    reason=target_reason,
                    scroll_steps=scroll_steps,
                    snapshot_count=snapshot_count,
                    restored_to_latest=False,
                )
                break
            frame = _capture_visual_group_frame(
                sidecar_ops=sidecar_ops,
                hwnd=hwnd,
                target_name=target_name,
                request=request,
                side_filter=clean_side,
                max_images=image_limit,
                label=f"vision_visual_group_locate_{snapshot_count}",
                explicit_image_pending=explicit_image_pending,
                anchor_text_key=anchor_text_key,
                anchor_message_id=anchor_message_id,
                allow_unanchored_single=bool(explicit_image_pending and not anchor_text_key and snapshot_count == 0),
            )
            snapshot_count += 1
            if frame.get("ok"):
                selected_frame = frame
                if acquire:
                    fast_single_current = bool(
                        explicit_image_pending
                        and scroll_steps == 0
                        and len(frame.get("messages") or []) == 1
                    )
                    need_fresh_reanchor = not fast_single_current
                    if need_fresh_reanchor:
                        fresh = fresh_reanchor_with_budget(
                            known_occurrences=[
                                dict(item)
                                for item in (frame.get("_occurrences") or [])
                                if isinstance(item, dict)
                            ],
                            label="vision_visual_group_fresh_reanchor",
                        )
                        if not fresh.get("ok"):
                            result = _locate_result(
                                ok=False,
                                state="vision_visual_group_acquire_failed",
                                reason=str(fresh.get("reason") or "visual_group_reanchor_mismatch"),
                                scroll_steps=scroll_steps,
                                snapshot_count=snapshot_count,
                                restored_to_latest=False,
                            )
                            break
                        selected_frame = fresh
                    acquired = _acquire_visual_group_payloads(
                        sidecar_ops=sidecar_ops,
                        hwnd=hwnd,
                        frame=selected_frame,
                        fresh_reanchor=lambda: fresh_reanchor_with_budget(
                            known_occurrences=[
                                dict(item)
                                for item in (selected_frame.get("_occurrences") or [])
                                if isinstance(item, dict)
                            ],
                            label="vision_visual_group_fingerprint_retry_reanchor",
                        ),
                        validate_before_right_click=validate_before_right_click,
                    )
                    if not acquired.get("ok"):
                        result = _locate_result(
                            ok=False,
                            state="vision_visual_group_acquire_failed",
                            reason=str(acquired.get("reason") or "visual_group_acquire_failed"),
                            scroll_steps=scroll_steps,
                            snapshot_count=snapshot_count,
                            restored_to_latest=False,
                        )
                        break
                    result = _locate_result(
                        ok=True,
                        state="vision_visual_group_acquired",
                        reason="visual_group_acquired",
                        scroll_steps=scroll_steps,
                        snapshot_count=snapshot_count,
                        restored_to_latest=False,
                        messages=list(selected_frame.get("messages") or []),
                    )
                    result["transaction"] = dict(acquired.get("transaction") or {})
                    result["_private_image_payloads"] = list(acquired.get("_private_image_payloads") or [])
                    break
                result = _locate_result(
                    ok=True,
                    state="vision_visual_group_located",
                    reason="visual_group_selected",
                    scroll_steps=scroll_steps,
                    snapshot_count=snapshot_count,
                    restored_to_latest=False,
                    messages=list(frame.get("messages") or []),
                )
                break
            reason = str(frame.get("reason") or "")
            if explicit_image_pending and not anchor_text_key and snapshot_count == 1:
                break
            if reason and reason not in {"visual_group_no_candidate", "visual_group_anchor_not_found"}:
                result = _locate_result(
                    ok=False,
                    state="vision_visual_group_locate_failed",
                    reason=reason,
                    scroll_steps=scroll_steps,
                    snapshot_count=snapshot_count,
                    restored_to_latest=False,
                )
                break
            if scroll_steps >= scroll_limit or snapshot_count >= snapshot_limit:
                break
            scroll = getattr(sidecar_ops, "scroll_chat_history", None)
            if not callable(scroll):
                break
            scroll(hwnd, 1)
            did_scroll = True
            scroll_steps += 1
            sleeper = getattr(sidecar_ops, "humanized_action_sleep", None)
            if callable(sleeper):
                sleeper(120, 220)
    finally:
        restore_ok = not did_scroll
        if did_scroll:
            try:
                restore = getattr(sidecar_ops, "scroll_chat_to_latest", None)
                target_reason = _validate_target_still_active(
                    sidecar_ops=sidecar_ops,
                    hwnd=hwnd,
                    target_name=target_name,
                    session_key=session_key,
                    conversation_type=conversation_type,
                    exact=exact,
                )
                if not target_reason and not target_drift_detected and callable(restore):
                    restore(hwnd)
                    restore_ok = True
                elif target_reason or target_drift_detected:
                    restore_ok = False
            except Exception:
                restore_ok = False
        if result is not None:
            locate = result.get("locate") if isinstance(result.get("locate"), dict) else {}
            locate["restored_to_latest"] = bool(restore_ok)
            result["locate"] = locate
            if did_scroll and not restore_ok:
                result.pop("_private_image_payloads", None)
                result.pop("transaction", None)
                result.update(
                    {
                        "ok": False,
                        "state": "vision_visual_group_locate_failed",
                        "reason": "visual_group_restore_failed",
                        "messages": [],
                    }
                )

    if result is not None:
        return result
    if did_scroll and not restore_ok:
        return _locate_result(
            ok=False,
            state="vision_visual_group_locate_failed",
            reason="visual_group_restore_failed",
            scroll_steps=scroll_steps,
            snapshot_count=snapshot_count,
            restored_to_latest=False,
        )
    return _locate_result(
        ok=False,
        state="vision_visual_group_locate_failed",
        reason="visual_group_no_candidate",
        scroll_steps=scroll_steps,
        snapshot_count=snapshot_count,
        restored_to_latest=bool(restore_ok),
    )


def locate_current_turn_visual_group(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    session_key: str,
    conversation_type: str,
    side_filter: str = "customer",
    max_images: int = 3,
    explicit_image_pending: bool = False,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    exact: bool = True,
    max_scroll_steps: int = MAX_LOCATE_SCROLL_STEPS,
    max_snapshots: int = MAX_LOCATE_SNAPSHOTS,
    max_seconds: float = MAX_LOCATE_SECONDS,
) -> dict[str, Any]:
    return _collect_current_turn_visual_group(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        target_name=target_name,
        session_key=session_key,
        conversation_type=conversation_type,
        side_filter=side_filter,
        max_images=max_images,
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        exact=exact,
        max_scroll_steps=max_scroll_steps,
        max_snapshots=max_snapshots,
        max_seconds=max_seconds,
        acquire=False,
    )


def acquire_current_turn_visual_group(
    *,
    sidecar_ops: Any,
    hwnd: int,
    target_name: str,
    session_key: str,
    conversation_type: str,
    side_filter: str = "customer",
    max_images: int = 3,
    explicit_image_pending: bool = False,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    exact: bool = True,
    max_scroll_steps: int = MAX_LOCATE_SCROLL_STEPS,
    max_snapshots: int = MAX_LOCATE_SNAPSHOTS,
    max_seconds: float = MAX_LOCATE_SECONDS,
) -> dict[str, Any]:
    return _collect_current_turn_visual_group(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        target_name=target_name,
        session_key=session_key,
        conversation_type=conversation_type,
        side_filter=side_filter,
        max_images=max_images,
        explicit_image_pending=explicit_image_pending,
        anchor_text_key=anchor_text_key,
        anchor_message_id=anchor_message_id,
        exact=exact,
        max_scroll_steps=max_scroll_steps,
        max_snapshots=max_snapshots,
        max_seconds=max_seconds,
        acquire=True,
    )
