from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import (
    chat_header_cutoff_y,
    session_split_x,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BOTTOM_EXCLUDE_PX = 95
IMAGE_PREVIEW_TOKENS = ("[图片]", "[照片]", "[Image]", "图片", "照片", "发送了一张图片")
SAVE_MENU_TOKENS = (
    "另存为",
    "保存图片",
    "保存到",
    "保存",
    "saveas",
    "save as",
    "saveimage",
    "save image",
)
COPY_IMAGE_MENU_TOKENS = (
    "复制图片",
    "复制",
    "copyimage",
    "copy image",
    "copy",
)
CHAT_TIME_RE = re.compile(
    r"^(?:(?:昨天|前天|星期[一二三四五六日天])\s*)?(?:[01]?\d|2[0-3]):[0-5]\d$"
)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_path_part(value: Any, *, default: str = "session") -> str:
    text = re.sub(r"[^\w.-]+", "_", str(value or "").strip(), flags=re.UNICODE).strip("._")
    return text[:96] or default


def image_preview_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text).lower()
    return any(re.sub(r"\s+", "", token).lower() in compact for token in IMAGE_PREVIEW_TOKENS)


def parse_preview_speaker(source_preview: Any, explicit_speaker: Any = "") -> str:
    explicit = str(explicit_speaker or "").strip()
    if explicit:
        return explicit
    text = str(source_preview or "").strip()
    if not text:
        return ""
    for sep in (":", "："):
        if sep not in text:
            continue
        left, right = text.split(sep, 1)
        if image_preview_text(right):
            return left.strip()
    return ""


def extract_chat_time_markers(
    ocr_items: list[dict[str, Any]] | None,
    image_size: tuple[int, int],
) -> list[dict[str, Any]]:
    """Extract centered WeChat time separators without treating them as messages."""
    width, height = image_size
    split_x = session_split_x(width)
    header_cutoff = chat_header_cutoff_y(height)
    markers: list[dict[str, Any]] = []
    for item in ocr_items or []:
        text = re.sub(r"\s+", "", str(item.get("text") or "").strip())
        if not text or not CHAT_TIME_RE.fullmatch(text):
            continue
        center_x = float(item.get("center_x") or 0.0)
        center_y = float(item.get("center_y") or 0.0)
        if center_y < header_cutoff or center_y > height - DEFAULT_BOTTOM_EXCLUDE_PX:
            continue
        # Session-list times live left of the chat split. Chat separators are
        # centered in the conversation pane and have compact OCR boxes.
        if center_x < split_x or center_x > width - 80:
            continue
        markers.append(
            {
                "text": text,
                "top": int(float(item.get("top") or center_y)),
                "bottom": int(float(item.get("bottom") or center_y)),
                "center_y": center_y,
            }
        )
    return sorted(markers, key=lambda item: float(item.get("center_y") or 0.0))


def nearest_chat_time_marker(
    bubble_bounds: list[int] | tuple[int, int, int, int] | None,
    markers: list[dict[str, Any]] | None,
) -> str:
    """Attach the latest visible time separator above a visual bubble."""
    bounds = [int(value) for value in list(bubble_bounds or [])[:4]]
    if len(bounds) != 4:
        return ""
    bubble_top = bounds[1]
    candidates = [
        item
        for item in (markers or [])
        if isinstance(item, dict) and float(item.get("center_y") or 0.0) <= bubble_top
    ]
    if not candidates:
        return ""
    return str(candidates[-1].get("text") or "").strip()


def image_asset_runtime_dir(
    *,
    tenant_id: str = "",
    target_name: str = "",
    session_key: str = "",
    date_text: str = "",
) -> Path:
    tenant = safe_path_part(tenant_id or "default", default="default")
    session = safe_path_part(session_key or target_name or "target", default="target")
    day = safe_path_part(date_text or datetime.now().strftime("%Y%m%d"), default="date")
    return PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "tenants" / tenant / "customer_service" / "image_assets" / session / day


def resolve_artifact_dir(
    artifact_dir: str | Path | None,
    *,
    tenant_id: str = "",
    target_name: str = "",
    session_key: str = "",
) -> Path:
    if artifact_dir:
        path = Path(artifact_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
    else:
        path = image_asset_runtime_dir(tenant_id=tenant_id, target_name=target_name, session_key=session_key)
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as raw:
        return int(raw.width), int(raw.height)


def wait_for_file_stable(path: Path, *, timeout_seconds: float = 8.0, quiet_period_seconds: float = 0.45) -> dict[str, Any]:
    deadline = time.time() + max(0.2, float(timeout_seconds or 0.2))
    last_size = -1
    last_changed = time.time()
    while time.time() <= deadline:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and size == last_size and (time.time() - last_changed) >= quiet_period_seconds:
                return {"ok": True, "path": str(path), "size_bytes": int(size)}
            if size != last_size:
                last_size = size
                last_changed = time.time()
        time.sleep(0.12)
    return {
        "ok": False,
        "path": str(path),
        "reason": "image_file_unstable",
        "size_bytes": int(last_size if last_size > 0 else 0),
    }


def save_asset_metadata(asset: dict[str, Any], meta_path: Path) -> None:
    meta_path.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_saved_image_asset(
    *,
    saved_image_path: str | Path,
    target_name: str,
    session_key: str = "",
    conversation_type: str = "",
    speaker_name: str = "",
    source_preview: str = "",
    save_method: str = "context_menu_save_as",
    captured_at: str = "",
    bubble_anchor: dict[str, Any] | None = None,
    bubble_bounds: list[int] | tuple[int, int, int, int] | None = None,
    visual_side: str = "customer",
    sender: str = "",
    sender_role: str = "",
    visual_occurrence_id: str = "",
    pending_signal_id: str = "",
    wechat_message_time: str = "",
    visual_index: int = 0,
    diagnostic_path: str = "",
) -> dict[str, Any]:
    path = Path(saved_image_path)
    digest = file_sha256(path)
    width, height = image_dimensions(path)
    short = digest[:12]
    clean_side = str(visual_side or "").strip().lower()
    if clean_side not in {"customer", "self"}:
        clean_side = "customer"
    resolved_captured_at = str(captured_at or now_iso())
    clean_pending_signal_id = str(pending_signal_id or "").strip()
    clean_message_time = str(wechat_message_time or "").strip()
    clean_visual_index = max(0, int(visual_index or 0))
    event_identity = clean_pending_signal_id or clean_message_time
    occurrence_seed_payload = {
        "sha256": digest,
        "target_name": str(target_name or ""),
        "session_key": str(session_key or ""),
        "bubble_anchor": bubble_anchor or {},
        "bubble_bounds": list(bubble_bounds or []),
        "visual_side": clean_side,
    }
    # Capture time is observation metadata, not message identity. A durable
    # pending signal or WeChat-rendered message time is required to distinguish
    # a second send of identical image bytes from repeated polling.
    if event_identity:
        occurrence_seed_payload.update(
            {
                "event_identity": event_identity,
                "visual_index": clean_visual_index,
            }
        )
    occurrence_seed = json.dumps(occurrence_seed_payload, ensure_ascii=False, sort_keys=True)
    occurrence = str(visual_occurrence_id or "").strip() or f"visual_occurrence_wx_{hashlib.sha256(occurrence_seed.encode('utf-8')).hexdigest()[:16]}"
    message_id = f"visual_msg_wx_{occurrence.replace('visual_occurrence_wx_', '', 1)[:16]}"
    observation_seed = json.dumps(
        {
            "saved_image_path": str(path),
            "captured_at": resolved_captured_at,
            "visual_index": clean_visual_index,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    observation_id = f"visual_observation_wx_{hashlib.sha256(observation_seed.encode('utf-8')).hexdigest()[:16]}"
    resolved_sender = str(sender or sender_role or "").strip().lower()
    if resolved_sender not in {"customer", "self"}:
        resolved_sender = "self" if clean_side == "self" else "customer"
    return {
        "asset_id": f"visual_asset_wx_{short}",
        "message_id": message_id,
        "message_type": "image",
        "target_name": str(target_name or ""),
        "conversation_type": str(conversation_type or ""),
        "speaker_name": str(speaker_name or ""),
        "session_key": str(session_key or ""),
        "sender": resolved_sender,
        "sender_role": str(sender_role or resolved_sender),
        "visual_side": clean_side,
        "visual_occurrence_id": occurrence,
        "pending_signal_id": clean_pending_signal_id,
        "wechat_message_time": clean_message_time,
        "visual_index": clean_visual_index,
        "visual_observation_id": observation_id,
        "saved_image_path": str(path),
        "sha256": digest,
        "width": int(width),
        "height": int(height),
        "size_bytes": int(path.stat().st_size),
        "save_method": str(save_method or "context_menu_save_as"),
        "source_preview": str(source_preview or ""),
        "captured_at": resolved_captured_at,
        "bubble_anchor": dict(bubble_anchor or {}),
        "bubble_bounds": [int(value) for value in list(bubble_bounds or [])[:4]],
        "diagnostic_path": str(diagnostic_path or ""),
    }


def build_image_message_from_asset(asset: dict[str, Any]) -> dict[str, Any]:
    message_id = str(asset.get("message_id") or asset.get("asset_id") or "")
    sender = str(asset.get("sender") or asset.get("sender_role") or "").strip().lower()
    if sender not in {"customer", "self"}:
        sender = "self" if str(asset.get("visual_side") or "").strip().lower() == "self" else "customer"
    return {
        "id": message_id,
        "message_id": message_id,
        "type": "image",
        "message_type": "image",
        "sender": sender,
        "sender_role": sender,
        "content": "[图片]",
        "speaker_name": str(asset.get("speaker_name") or ""),
        "group_member_name": str(asset.get("speaker_name") or ""),
        "image_assets": [str(asset.get("asset_id") or "")],
        "asset_id": str(asset.get("asset_id") or ""),
        "saved_image_path": str(asset.get("saved_image_path") or ""),
        "visual_side": str(asset.get("visual_side") or sender),
        "visual_occurrence_id": str(asset.get("visual_occurrence_id") or ""),
        "pending_signal_id": str(asset.get("pending_signal_id") or ""),
        "wechat_message_time": str(asset.get("wechat_message_time") or ""),
        "visual_index": int(asset.get("visual_index") or 0),
        "visual_observation_id": str(asset.get("visual_observation_id") or ""),
        "bubble_bounds": [int(value) for value in (asset.get("bubble_bounds") or [])[:4]],
        "source_adapter": "win32_ocr",
        "captured_at": str(asset.get("captured_at") or ""),
        "time": str(asset.get("wechat_message_time") or asset.get("captured_at") or ""),
        "quality_flags": ["synthetic_visual_turn"],
    }


def _chat_bounds(width: int, height: int) -> tuple[int, int, int, int]:
    split = session_split_x(width)
    left = min(width - 1, split + 12)
    top = chat_header_cutoff_y(height)
    right = width - 8
    bottom = height - max(DEFAULT_BOTTOM_EXCLUDE_PX, int(height * 0.10))
    return left, top, right, bottom


def _covered_by_text(bounds: tuple[int, int, int, int], messages: list[dict[str, Any]]) -> bool:
    left, top, right, bottom = bounds
    area = max(1, (right - left) * (bottom - top))
    for message in messages:
        if not isinstance(message, dict):
            continue
        rect = message.get("bubble_rect") if isinstance(message.get("bubble_rect"), dict) else {}
        if not rect:
            continue
        ml = int(float(rect.get("left") or 0)) - 8
        mt = int(float(rect.get("top") or 0)) - 8
        mr = int(float(rect.get("right") or 0)) + 8
        mb = int(float(rect.get("bottom") or 0)) + 8
        overlap_left = max(left, ml)
        overlap_top = max(top, mt)
        overlap_right = min(right, mr)
        overlap_bottom = min(bottom, mb)
        if overlap_right <= overlap_left or overlap_bottom <= overlap_top:
            continue
        overlap = (overlap_right - overlap_left) * (overlap_bottom - overlap_top)
        if overlap / area >= 0.42:
            return True
    return False


def detect_visual_image_bubbles(
    screenshot: Image.Image,
    *,
    messages: list[dict[str, Any]] | None = None,
    max_images: int = 1,
    side_filter: str = "customer",
    time_markers: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    image = screenshot.convert("RGB")
    width, height = image.size
    left, top, right, bottom = _chat_bounds(width, height)
    if right <= left or bottom <= top:
        return []
    crop = image.crop((left, top, right, bottom))
    scale = min(1.0, 220.0 / max(1, crop.width), 300.0 / max(1, crop.height))
    small = crop.resize((max(32, int(crop.width * scale)), max(32, int(crop.height * scale))), Image.Resampling.BILINEAR)
    block = 5
    grid_w = max(1, small.width // block)
    grid_h = max(1, small.height // block)
    active = [[False for _ in range(grid_w)] for _ in range(grid_h)]
    for gy in range(grid_h):
        for gx in range(grid_w):
            box = (
                gx * block,
                gy * block,
                min(small.width, (gx + 1) * block),
                min(small.height, (gy + 1) * block),
            )
            stat = ImageStat.Stat(small.crop(box))
            mean = stat.mean or [0.0, 0.0, 0.0]
            spread = sum(float(value) for value in (stat.stddev or [0.0, 0.0, 0.0])) / 3.0
            delta = max(mean) - min(mean)
            active[gy][gx] = spread >= 16.0 or delta >= 24.0
    visited: set[tuple[int, int]] = set()
    candidates: list[dict[str, Any]] = []
    split = session_split_x(width)
    clean_side_filter = str(side_filter or "customer").strip().lower()
    if clean_side_filter not in {"customer", "self", "all"}:
        clean_side_filter = "customer"
    for gy in range(grid_h):
        for gx in range(grid_w):
            if not active[gy][gx] or (gx, gy) in visited:
                continue
            stack = [(gx, gy)]
            visited.add((gx, gy))
            cells: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or ny < 0 or nx >= grid_w or ny >= grid_h:
                        continue
                    if not active[ny][nx] or (nx, ny) in visited:
                        continue
                    visited.add((nx, ny))
                    stack.append((nx, ny))
            min_x = min(point[0] for point in cells)
            max_x = max(point[0] for point in cells)
            min_y = min(point[1] for point in cells)
            max_y = max(point[1] for point in cells)
            bounds = (
                left + int((min_x * block) / scale),
                top + int((min_y * block) / scale),
                left + int(min(crop.width, ((max_x + 1) * block) / scale)),
                top + int(min(crop.height, ((max_y + 1) * block) / scale)),
            )
            bw = bounds[2] - bounds[0]
            bh = bounds[3] - bounds[1]
            area = bw * bh
            if bw < 90 or bh < 90 or area < 14000:
                continue
            if _covered_by_text(bounds, messages or []):
                continue
            center_x = (bounds[0] + bounds[2]) / 2.0
            side = "customer" if center_x <= (split + (width - split) * 0.58) else "self"
            if clean_side_filter != "all" and side != clean_side_filter:
                continue
            score = area + bounds[3] * 12
            candidates.append(
                {
                    "bounds": [int(value) for value in bounds],
                    "width": int(bw),
                    "height": int(bh),
                    "area": int(area),
                    "side": side,
                    "score": float(score),
                    "anchor": {"x": int((bounds[0] + bounds[2]) / 2), "y": int((bounds[1] + bounds[3]) / 2)},
                    "wechat_message_time": nearest_chat_time_marker(bounds, time_markers),
                }
            )
    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return candidates[: max(1, min(int(max_images or 1), 8))]


def detect_customer_image_bubbles(
    screenshot: Image.Image,
    *,
    messages: list[dict[str, Any]] | None = None,
    max_images: int = 1,
) -> list[dict[str, Any]]:
    return detect_visual_image_bubbles(
        screenshot,
        messages=messages,
        max_images=max_images,
        side_filter="customer",
    )


def normalize_menu_text(value: Any) -> str:
    return re.sub(r"[\s.。…·\-_/\\\\]+", "", str(value or "")).lower()


def save_menu_priority(compact_text: str) -> int:
    compact = normalize_menu_text(compact_text)
    if "另存为" in compact or "saveas" in compact:
        return 3
    if "保存图片" in compact or "saveimage" in compact:
        return 2
    if "保存到" in compact or compact == "保存" or compact == "save":
        return 1
    return 0


def copy_menu_priority(compact_text: str) -> int:
    compact = normalize_menu_text(compact_text)
    if "复制图片" in compact or "copyimage" in compact:
        return 3
    if compact == "复制" or compact == "copy":
        return 2
    if "复制" in compact or "copy" in compact:
        return 1
    return 0


def _find_context_menu_item(
    ocr_items: list[dict[str, Any]],
    image_size: tuple[int, int],
    *,
    tokens: tuple[str, ...],
    priority_fn: Any,
) -> dict[str, Any] | None:
    width, height = image_size
    candidates: list[dict[str, Any]] = []
    normalized_tokens = [normalize_menu_text(token) for token in tokens]
    for item in ocr_items:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        compact = normalize_menu_text(text)
        if not compact:
            continue
        priority = int(priority_fn(compact) or 0)
        if priority <= 0 and not any(token and token in compact for token in normalized_tokens):
            continue
        left = max(0, int(float(item.get("left") or 0)) - 28)
        top = max(0, int(float(item.get("top") or 0)) - 12)
        right = min(width, int(float(item.get("right") or 0)) + 60)
        bottom = min(height, int(float(item.get("bottom") or 0)) + 14)
        if right <= left or bottom <= top:
            continue
        candidates.append(
            {
                "text": text,
                "bounds": [left, top, right, bottom],
                "x": int((left + right) / 2),
                "y": int((top + bottom) / 2),
                "confidence": float(item.get("confidence") or 0.0),
                "priority": int(priority or 1),
            }
        )
    if not candidates:
        return None
    return max(candidates, key=lambda item: (int(item.get("priority") or 0), float(item.get("confidence") or 0.0), int(item.get("y") or 0)))


def find_save_menu_item(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> dict[str, Any] | None:
    return _find_context_menu_item(
        ocr_items,
        image_size,
        tokens=SAVE_MENU_TOKENS,
        priority_fn=save_menu_priority,
    )


def find_copy_menu_item(ocr_items: list[dict[str, Any]], image_size: tuple[int, int]) -> dict[str, Any] | None:
    return _find_context_menu_item(
        ocr_items,
        image_size,
        tokens=COPY_IMAGE_MENU_TOKENS,
        priority_fn=copy_menu_priority,
    )


def planned_saved_image_path(
    artifact_dir: Path,
    *,
    target_name: str,
    session_key: str = "",
    source_preview: str = "",
    extension: str = ".jpg",
) -> Path:
    seed = json.dumps(
        {
            "target_name": target_name,
            "session_key": session_key,
            "source_preview": source_preview,
            "time": now_iso(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    ext = extension if str(extension).startswith(".") else f".{extension}"
    return artifact_dir / f"wx_image_{datetime.now().strftime('%H%M%S')}_{digest}{ext}"


def planned_visual_crop_path(
    artifact_dir: Path,
    *,
    target_name: str,
    session_key: str = "",
    visual_side: str = "customer",
    bounds: list[int] | tuple[int, int, int, int] | None = None,
    index: int = 0,
) -> Path:
    seed = json.dumps(
        {
            "target_name": target_name,
            "session_key": session_key,
            "visual_side": visual_side,
            "bounds": list(bounds or []),
            "time": now_iso(),
            "index": int(index),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    side = safe_path_part(visual_side or "visual", default="visual")
    return artifact_dir / f"wx_visual_{datetime.now().strftime('%H%M%S')}_{side}_{int(index):02d}_{digest}.png"


def clamp_bounds(bounds: list[int] | tuple[int, int, int, int], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
    width, height = image_size
    left, top, right, bottom = [int(value) for value in list(bounds)[:4]]
    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    return left, top, right, bottom


def save_visual_bubble_crop(
    screenshot: Image.Image,
    *,
    output_dir: Path,
    target_name: str,
    session_key: str = "",
    bubble: dict[str, Any],
    index: int = 0,
) -> dict[str, Any]:
    bounds = clamp_bounds([int(value) for value in (bubble.get("bounds") or [])[:4]], screenshot.size)
    side = str(bubble.get("side") or "customer").strip().lower()
    if side not in {"customer", "self"}:
        side = "customer"
    saved_path = planned_visual_crop_path(
        output_dir,
        target_name=target_name,
        session_key=session_key,
        visual_side=side,
        bounds=list(bounds),
        index=index,
    )
    crop = screenshot.crop(bounds)
    saved_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(saved_path, format="PNG")
    stable = wait_for_file_stable(saved_path, timeout_seconds=1.2, quiet_period_seconds=0.05)
    return {
        "ok": bool(stable.get("ok")),
        "path": str(saved_path),
        "bounds": [int(value) for value in bounds],
        "side": side,
        "width": int(crop.width),
        "height": int(crop.height),
        "file_stable": stable,
    }


def capture_context_menu_image(
    *,
    sidecar_ops: Any,
    hwnd: int,
    artifact_dir: str,
    label: str,
) -> tuple[Any, str, str]:
    visible_capture = getattr(sidecar_ops, "capture_wechat_window_visible_screen", None)
    if callable(visible_capture):
        try:
            image, path = visible_capture(hwnd, artifact_dir=artifact_dir, label=label)
            return image, path, "visible_window"
        except Exception:
            pass
    image, path = sidecar_ops.capture_wechat(hwnd, artifact_dir=artifact_dir, label=label)
    return image, path, "window_capture"


def _clipboard_image_value(sidecar_ops: Any) -> Any:
    grabber = getattr(sidecar_ops, "grab_clipboard_image", None)
    if callable(grabber):
        return grabber()
    image_grab = getattr(sidecar_ops, "ImageGrab", None)
    grabclipboard = getattr(image_grab, "grabclipboard", None)
    if callable(grabclipboard):
        return grabclipboard()
    from PIL import ImageGrab  # Imported lazily so non-Windows tests can stub sidecar_ops.

    return ImageGrab.grabclipboard()


def _clipboard_value_to_image(value: Any) -> tuple[Image.Image | None, dict[str, Any]]:
    if isinstance(value, Image.Image):
        return value.copy(), {"clipboard_source": "bitmap"}
    if isinstance(value, (list, tuple)):
        for item in value:
            path = Path(str(item or ""))
            if not path.is_file():
                continue
            try:
                with Image.open(path) as raw:
                    return raw.copy(), {"clipboard_source": "file", "clipboard_source_path": str(path)}
            except Exception:
                continue
        return None, {"clipboard_source": "file_list", "reason": "clipboard_file_list_without_readable_image"}
    if value is None:
        return None, {"clipboard_source": "empty", "reason": "clipboard_image_missing"}
    return None, {"clipboard_source": type(value).__name__, "reason": "clipboard_value_not_image"}


def save_clipboard_image_to_path(sidecar_ops: Any, saved_path: Path) -> dict[str, Any]:
    try:
        value = _clipboard_image_value(sidecar_ops)
        image, source = _clipboard_value_to_image(value)
        if image is None:
            return {"ok": False, "reason": str(source.get("reason") or "clipboard_image_missing"), **source}
        if image.width < 16 or image.height < 16:
            return {
                "ok": False,
                "reason": "clipboard_image_too_small",
                "width": int(image.width),
                "height": int(image.height),
                **source,
            }
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(saved_path, format="PNG")
        stable = wait_for_file_stable(saved_path, timeout_seconds=1.2, quiet_period_seconds=0.05)
        if not stable.get("ok"):
            return {"ok": False, "reason": str(stable.get("reason") or "clipboard_image_file_unstable"), "file_stable": stable, **source}
        return {
            "ok": True,
            "path": str(saved_path),
            "width": int(image.width),
            "height": int(image.height),
            "file_stable": stable,
            **source,
        }
    except Exception as exc:
        return {"ok": False, "reason": "clipboard_image_read_failed", "error": repr(exc)}


def click_context_menu_item(
    *,
    sidecar_ops: Any,
    hwnd: int,
    menu_target: dict[str, Any],
    action_name: str,
) -> dict[str, Any]:
    screen_click = getattr(sidecar_ops, "human_screen_click", None)
    win32gui = getattr(sidecar_ops, "win32gui", None)
    if callable(screen_click) and win32gui is not None:
        try:
            left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
            return screen_click(
                int(left) + int(menu_target.get("x") or 0),
                int(top) + int(menu_target.get("y") or 0),
                action_name=action_name,
            )
        except Exception:
            pass
    return sidecar_ops.human_window_image_click_in_bounds(
        hwnd,
        int(menu_target.get("x") or 0),
        int(menu_target.get("y") or 0),
        bounds=[int(value) for value in (menu_target.get("bounds") or [])[:4]],
        action_name=action_name,
    )


def build_image_saved_payload(
    *,
    saved_path: Path,
    target_name: str,
    session_key: str,
    source_preview: str,
    speaker_name: str,
    captured_at: str,
    anchor: dict[str, Any],
    screenshot_path: str,
    save_method: str,
    diagnostics: dict[str, Any],
    probe: dict[str, Any],
    bubble_bounds: list[int] | tuple[int, int, int, int] | None = None,
    visual_side: str = "customer",
    pending_signal_id: str = "",
    wechat_message_time: str = "",
    visual_index: int = 0,
) -> dict[str, Any]:
    resolved_speaker = parse_preview_speaker(source_preview, speaker_name)
    asset = build_saved_image_asset(
        saved_image_path=saved_path,
        target_name=target_name,
        session_key=session_key,
        conversation_type="",
        speaker_name=resolved_speaker,
        source_preview=source_preview,
        save_method=save_method,
        captured_at=captured_at,
        bubble_anchor=anchor,
        bubble_bounds=bubble_bounds,
        visual_side=visual_side,
        sender=visual_side,
        sender_role=visual_side,
        pending_signal_id=pending_signal_id,
        wechat_message_time=wechat_message_time,
        visual_index=visual_index,
        diagnostic_path=screenshot_path,
    )
    meta_path = saved_path.with_suffix(saved_path.suffix + ".meta.json")
    asset["meta_path"] = str(meta_path)
    save_asset_metadata(asset, meta_path)
    message = build_image_message_from_asset(asset)
    return {
        "ok": True,
        "online": True,
        "adapter": "win32_ocr",
        "state": "image_saved",
        "target": target_name,
        "session_key": session_key,
        "assets": [asset],
        "messages": [message],
        "diagnostics": diagnostics,
        "window_probe": probe,
    }


def build_visual_bubble_archive_payload(
    *,
    screenshot: Image.Image,
    screenshot_path: str,
    output_dir: Path,
    bubbles: list[dict[str, Any]],
    target_name: str,
    session_key: str,
    source_preview: str,
    speaker_name: str,
    captured_at: str,
    diagnostics: dict[str, Any],
    probe: dict[str, Any],
    pending_signal_id: str = "",
) -> dict[str, Any]:
    assets: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    resolved_speaker = parse_preview_speaker(source_preview, speaker_name)
    for index, bubble in enumerate(bubbles):
        crop_result = save_visual_bubble_crop(
            screenshot,
            output_dir=output_dir,
            target_name=target_name,
            session_key=session_key,
            bubble=bubble,
            index=index,
        )
        if not crop_result.get("ok"):
            failures.append({"bubble": bubble, "crop_result": crop_result})
            continue
        side = str(crop_result.get("side") or bubble.get("side") or "customer").strip().lower()
        if side not in {"customer", "self"}:
            side = "customer"
        bounds = [int(value) for value in (crop_result.get("bounds") or bubble.get("bounds") or [])[:4]]
        asset = build_saved_image_asset(
            saved_image_path=str(crop_result.get("path") or ""),
            target_name=target_name,
            session_key=session_key,
            conversation_type="",
            speaker_name=resolved_speaker if side == "customer" else "",
            source_preview=source_preview,
            save_method="visual_bubble_crop",
            captured_at=captured_at,
            bubble_anchor=dict(bubble.get("anchor") or {}),
            bubble_bounds=bounds,
            visual_side=side,
            sender=side,
            sender_role=side,
            pending_signal_id=pending_signal_id,
            wechat_message_time=str(bubble.get("wechat_message_time") or ""),
            visual_index=index,
            diagnostic_path=screenshot_path,
        )
        meta_path = Path(str(crop_result.get("path") or "")).with_suffix(Path(str(crop_result.get("path") or "")).suffix + ".meta.json")
        asset["meta_path"] = str(meta_path)
        save_asset_metadata(asset, meta_path)
        assets.append(asset)
        messages.append(build_image_message_from_asset(asset))
    return {
        "ok": bool(assets) or not bubbles,
        "online": True,
        "adapter": "win32_ocr",
        "state": "visual_bubbles_archived" if assets else "visual_bubbles_not_found",
        "target": target_name,
        "session_key": session_key,
        "assets": assets,
        "messages": messages,
        "failures": failures,
        "diagnostics": {
            **diagnostics,
            "screenshot_path": screenshot_path,
            "source_preview": source_preview,
            "visual_bubble_count": len(bubbles),
            "visual_asset_count": len(assets),
        },
        "window_probe": probe,
    }


def execute_wechat_image_save(
    *,
    hwnd: int,
    probe: dict[str, Any],
    target_name: str,
    session_key: str = "",
    exact: bool = True,
    artifact_dir: str | Path | None = None,
    tenant_id: str = "",
    source_preview: str = "",
    speaker_name: str = "",
    max_images: int = 1,
    side_filter: str = "customer",
    capture_mode: str = "context_menu",
    pending_signal_id: str = "",
    sidecar_ops: Any,
) -> dict[str, Any]:
    output_dir = resolve_artifact_dir(artifact_dir, tenant_id=tenant_id, target_name=target_name, session_key=session_key)
    captured_at = now_iso()
    screenshot, screenshot_path = sidecar_ops.capture_wechat(hwnd, artifact_dir=str(output_dir), label="image_save_before")
    ocr_items = sidecar_ops.run_ocr(screenshot)
    geometry = sidecar_ops.get_window_geometry(hwnd)
    image_size = getattr(screenshot, "size", (int(geometry.get("width") or 0), int(geometry.get("height") or 0)))
    messages = sidecar_ops.parse_messages_from_ocr(ocr_items, image_size, target=target_name)
    time_markers = extract_chat_time_markers(ocr_items, image_size)
    blocking_reason = sidecar_ops.blocking_screen_reason(ocr_items)
    if blocking_reason:
        return {
            "ok": False,
            "online": False if blocking_reason == "login_or_qr" else True,
            "adapter": "win32_ocr",
            "state": "image_save_blocked",
            "reason": blocking_reason,
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {"screenshot_path": screenshot_path, "source_preview": source_preview},
        }
    clean_side_filter = str(side_filter or "customer").strip().lower()
    if clean_side_filter not in {"customer", "self", "all"}:
        clean_side_filter = "customer"
    clean_capture_mode = str(capture_mode or "context_menu").strip().lower()
    if clean_capture_mode not in {"context_menu", "crop"}:
        clean_capture_mode = "context_menu"
    bubbles = detect_visual_image_bubbles(
        screenshot,
        messages=messages,
        max_images=max_images,
        side_filter=clean_side_filter,
        time_markers=time_markers,
    )
    if not bubbles:
        return {
            "ok": True if clean_capture_mode == "crop" else False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "visual_bubbles_not_found" if clean_capture_mode == "crop" else "image_save_failed",
            "reason": "image_bubble_not_found",
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {
                "screenshot_path": screenshot_path,
                "source_preview": source_preview,
                "ocr_items_count": len(ocr_items),
                "capture_mode": clean_capture_mode,
                "side_filter": clean_side_filter,
            },
        }
    if clean_capture_mode == "crop":
        return build_visual_bubble_archive_payload(
            screenshot=screenshot,
            screenshot_path=screenshot_path,
            output_dir=output_dir,
            bubbles=bubbles,
            target_name=target_name,
            session_key=session_key,
            source_preview=source_preview,
            speaker_name=speaker_name,
            captured_at=captured_at,
            diagnostics={
                "ocr_items_count": len(ocr_items),
                "capture_mode": clean_capture_mode,
                "side_filter": clean_side_filter,
                "time_markers": time_markers,
            },
            probe=probe,
            pending_signal_id=pending_signal_id,
        )
    bubble = bubbles[0]
    anchor = dict(bubble.get("anchor") or {})
    bounds = [int(value) for value in (bubble.get("bounds") or [])[:4]]
    right_click = sidecar_ops.human_window_image_right_click_in_bounds(
        hwnd,
        int(anchor.get("x") or 0),
        int(anchor.get("y") or 0),
        bounds=bounds,
        action_name="image_save_context_right_click",
    )
    sidecar_ops.humanized_action_sleep(360, 720)
    menu_screenshot, menu_path, menu_capture_method = capture_context_menu_image(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        artifact_dir=str(output_dir),
        label="image_save_context_menu",
    )
    menu_items = sidecar_ops.run_ocr(menu_screenshot)
    menu_size = getattr(menu_screenshot, "size", image_size)
    copy_target = find_copy_menu_item(menu_items, menu_size)
    saved_path = planned_saved_image_path(
        output_dir,
        target_name=target_name,
        session_key=session_key,
        source_preview=source_preview,
        extension=".png",
    )
    if right_click.get("ok") and copy_target:
        menu_click = click_context_menu_item(
            sidecar_ops=sidecar_ops,
            hwnd=hwnd,
            menu_target=copy_target,
            action_name="image_copy_menu_item_click",
        )
        sidecar_ops.humanized_action_sleep(260, 520)
        clipboard_save = save_clipboard_image_to_path(sidecar_ops, saved_path)
        if clipboard_save.get("ok"):
            diagnostics = {
                "screenshot_path": screenshot_path,
                "menu_screenshot_path": menu_path,
                "menu_capture_method": menu_capture_method,
                "bubble_anchor": anchor,
                "context_menu_label": copy_target.get("text"),
                "dialog_result": "clipboard_saved",
                "save_path": str(saved_path),
                "right_click": right_click,
                "menu_click": menu_click,
                "clipboard_save": clipboard_save,
            }
            return build_image_saved_payload(
                saved_path=saved_path,
                target_name=target_name,
                session_key=session_key,
                source_preview=source_preview,
                speaker_name=speaker_name,
                captured_at=captured_at,
                anchor=anchor,
                bubble_bounds=bounds,
                visual_side=str(bubble.get("side") or "customer"),
                screenshot_path=screenshot_path,
                save_method="context_menu_copy_clipboard",
                diagnostics=diagnostics,
                probe=probe,
                pending_signal_id=pending_signal_id,
                wechat_message_time=str(bubble.get("wechat_message_time") or ""),
                visual_index=0,
            )
        try:
            sidecar_ops.key_press(sidecar_ops.win32con.VK_ESCAPE)
        except Exception:
            pass
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "image_save_failed",
            "reason": str(clipboard_save.get("reason") or "clipboard_image_save_failed"),
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {
                "screenshot_path": screenshot_path,
                "menu_screenshot_path": menu_path,
                "menu_capture_method": menu_capture_method,
                "bubble_anchor": anchor,
                "context_menu_label": copy_target.get("text"),
                "right_click": right_click,
                "menu_click": menu_click,
                "clipboard_save": clipboard_save,
                "source_preview": source_preview,
                "menu_ocr_items_count": len(menu_items),
            },
        }
    menu_target = find_save_menu_item(menu_items, getattr(menu_screenshot, "size", image_size))
    if not right_click.get("ok") or not menu_target:
        try:
            sidecar_ops.key_press(sidecar_ops.win32con.VK_ESCAPE)
        except Exception:
            pass
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "image_save_failed",
            "reason": "image_context_menu_save_item_missing",
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {
                "screenshot_path": screenshot_path,
                "menu_screenshot_path": menu_path,
                "menu_capture_method": menu_capture_method,
                "bubble_anchor": anchor,
                "right_click": right_click,
                "source_preview": source_preview,
                "menu_ocr_items_count": len(menu_items),
            },
        }
    menu_click = click_context_menu_item(
        sidecar_ops=sidecar_ops,
        hwnd=hwnd,
        menu_target=menu_target,
        action_name="image_save_menu_item_click",
    )
    sidecar_ops.humanized_action_sleep(420, 820)
    saved_path = planned_saved_image_path(output_dir, target_name=target_name, session_key=session_key, source_preview=source_preview)
    try:
        sidecar_ops.clipboard_copy(str(saved_path))
        sidecar_ops.hotkey(sidecar_ops.win32con.VK_CONTROL, ord("V"))
        sidecar_ops.humanized_action_sleep(120, 260)
        sidecar_ops.key_press(sidecar_ops.win32con.VK_RETURN)
    except Exception as exc:
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "image_save_failed",
            "reason": "image_save_dialog_failed",
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {
                "screenshot_path": screenshot_path,
                "menu_screenshot_path": menu_path,
                "menu_capture_method": menu_capture_method,
                "bubble_anchor": anchor,
                "context_menu_label": menu_target.get("text"),
                "menu_click": menu_click,
                "save_path": str(saved_path),
                "error": repr(exc),
            },
        }
    stable = wait_for_file_stable(saved_path)
    if not stable.get("ok"):
        return {
            "ok": False,
            "online": True,
            "adapter": "win32_ocr",
            "state": "image_save_failed",
            "reason": str(stable.get("reason") or "image_file_unstable"),
            "target": target_name,
            "session_key": session_key,
            "assets": [],
            "messages": [],
            "diagnostics": {
                "screenshot_path": screenshot_path,
                "menu_screenshot_path": menu_path,
                "menu_capture_method": menu_capture_method,
                "bubble_anchor": anchor,
                "context_menu_label": menu_target.get("text"),
                "save_path": str(saved_path),
                "file_stable": stable,
            },
        }
    diagnostics = {
        "screenshot_path": screenshot_path,
        "menu_screenshot_path": menu_path,
        "menu_capture_method": menu_capture_method,
        "bubble_anchor": anchor,
        "context_menu_label": menu_target.get("text"),
        "dialog_result": "saved",
        "save_path": str(saved_path),
        "file_stable": stable,
        "right_click": right_click,
        "menu_click": menu_click,
    }
    return build_image_saved_payload(
        saved_path=saved_path,
        target_name=target_name,
        session_key=session_key,
        source_preview=source_preview,
        speaker_name=speaker_name,
        save_method="context_menu_save_as",
        captured_at=captured_at,
        anchor=anchor,
        bubble_bounds=bounds,
        visual_side=str(bubble.get("side") or "customer"),
        screenshot_path=screenshot_path,
        diagnostics=diagnostics,
        probe=probe,
    )
