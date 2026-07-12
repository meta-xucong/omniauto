from __future__ import annotations

import copy
import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import (
    chat_header_cutoff_y,
    session_split_x,
)
from apps.wechat_ai_customer_service.adapters.wechat_image_save_capture import (
    build_image_message_from_asset,
    image_preview_text,
    parse_preview_speaker,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "customer_image_understanding"
DEFAULT_BOTTOM_EXCLUDE_PX = 95


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sanitize_name(value: str) -> str:
    keep = [char if char.isalnum() else "_" for char in str(value or "").strip()]
    compact = "".join(keep).strip("_")
    return compact or "target"


def visual_artifact_dir(*, target_name: str, session_key: str = "") -> Path:
    target_part = sanitize_name(session_key or target_name)
    path = RUNTIME_ROOT / target_part
    path.mkdir(parents=True, exist_ok=True)
    return path


def target_state_image_pending_signal(target_state: dict[str, Any] | None) -> dict[str, Any]:
    state = target_state if isinstance(target_state, dict) else {}
    candidates: list[dict[str, Any]] = []
    for key in ("pending_signal", "latest_pending_signal", "session_monitor_pending_signal", "_session_monitor_pending_signal"):
        value = state.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    if any(key in state for key in ("pending_signal_text", "preview_content", "unread_detected", "pending_since", "last_unread_badge")):
        candidates.append(state)
    for item in candidates:
        pending_text = str(item.get("pending_signal_text") or item.get("preview_content") or "").strip()
        if image_preview_text(pending_text):
            return item
    return {}


def payload_image_pending_signal(payload: dict[str, Any] | None, target_state: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    for key in ("pending_signal", "session_monitor_pending_signal", "_session_monitor_pending_signal"):
        value = source.get(key)
        if isinstance(value, dict):
            pending_text = str(value.get("pending_signal_text") or value.get("preview_content") or "").strip()
            if image_preview_text(pending_text):
                return value
    for key in ("pending_signal_text", "preview_content", "source_preview"):
        if image_preview_text(source.get(key)):
            return source
    return target_state_image_pending_signal(target_state)


def build_brain_safe_image_proxy_message(
    source: dict[str, Any],
    *,
    target_name: str = "",
    session_key: str = "",
    content: str = "客户发来了一张图片",
) -> dict[str, Any]:
    """Represent an image turn as text for Brain routing without losing the asset link.

    The global message filters intentionally reject ``message_type=image``.  This
    proxy keeps the customer-visible authoring path text-only while carrying the
    saved image path for the existing customer_image_* understanding pipeline.
    """

    item = source if isinstance(source, dict) else {}
    asset_id = str(item.get("asset_id") or "")
    if not asset_id:
        image_assets = [str(value) for value in (item.get("image_assets") or []) if str(value)]
        asset_id = image_assets[0] if image_assets else ""
    source_message_type = str(item.get("source_message_type") or item.get("message_type") or item.get("type") or "image").strip() or "image"
    saved_path = str(item.get("saved_image_path") or item.get("bubble_crop_path") or item.get("thumbnail_path") or "").strip()
    raw_message_id = str(item.get("message_id") or item.get("id") or item.get("message_uuid") or "")
    if item.get("is_customer_image_proxy") and raw_message_id:
        message_id = raw_message_id
    else:
        occurrence_seed = "|".join(
            [
                raw_message_id,
                asset_id,
                saved_path,
                str(item.get("pending_signal_id") or ""),
                str(item.get("captured_at") or ""),
                str(item.get("source_preview") or item.get("pending_signal_text") or ""),
            ]
        ).strip("|")
        message_id = f"visual_proxy:{hashlib.sha1((occurrence_seed or str(item)).encode('utf-8')).hexdigest()[:16]}"
    flags = ["synthetic_visual_turn"]
    proxy = {
        "id": message_id,
        "message_id": message_id,
        "type": "text",
        "sender": str(item.get("sender") or "customer"),
        "sender_role": str(item.get("sender_role") or "customer"),
        "content": str(content or "").strip() or "客户发来了一张图片",
        "source_message_type": source_message_type,
        "visual_turn_kind": "customer_image",
        "is_customer_image_proxy": True,
        "quality_flags": flags,
    }
    if raw_message_id and raw_message_id != message_id:
        proxy["source_message_id"] = raw_message_id
    if asset_id:
        proxy["asset_id"] = asset_id
        proxy["image_assets"] = [asset_id]
    if saved_path:
        proxy["saved_image_path"] = saved_path
    for key in (
        "speaker_name",
        "group_member_name",
        "source_preview",
        "pending_signal_text",
        "pending_signal_id",
        "captured_at",
        "conversation_id",
        "visual_side",
        "visual_occurrence_id",
        "wechat_message_time",
        "visual_index",
        "visual_observation_id",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            proxy[key] = value
    bounds = [int(value) for value in (item.get("bubble_bounds") or [])[:4]]
    if bounds:
        proxy["bubble_bounds"] = bounds
    if target_name:
        proxy["target_name"] = str(target_name)
    elif item.get("target_name"):
        proxy["target_name"] = str(item.get("target_name") or "")
    if session_key:
        proxy["session_key"] = str(session_key)
    elif item.get("session_key"):
        proxy["session_key"] = str(item.get("session_key") or "")
    return proxy


def build_brain_safe_image_proxy_messages(
    sources: list[dict[str, Any]],
    *,
    target_name: str = "",
    session_key: str = "",
    content: str = "客户发来了一张图片",
) -> list[dict[str, Any]]:
    return [
        build_brain_safe_image_proxy_message(
            item,
            target_name=target_name,
            session_key=session_key,
            content=content,
        )
        for item in sources
        if isinstance(item, dict)
    ]


def assets_from_payload_messages(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    source = payload if isinstance(payload, dict) else {}
    result: list[dict[str, Any]] = []
    for message in source.get("messages") or []:
        if not isinstance(message, dict):
            continue
        saved_path = str(message.get("saved_image_path") or "").strip()
        if not saved_path:
            continue
        asset_id = str(message.get("asset_id") or "")
        if not asset_id:
            image_assets = [str(item) for item in (message.get("image_assets") or []) if str(item)]
            asset_id = image_assets[0] if image_assets else ""
        result.append(
            {
                "asset_id": asset_id or str(message.get("message_id") or message.get("id") or ""),
                "message_id": str(message.get("message_id") or message.get("id") or ""),
                "message_type": "image",
                "target_name": str(message.get("target_name") or ""),
                "conversation_id": str(message.get("conversation_id") or ""),
                "session_key": str(message.get("session_key") or ""),
                "speaker_name": str(message.get("speaker_name") or message.get("group_member_name") or ""),
                "sender": str(message.get("sender") or message.get("sender_role") or ""),
                "sender_role": str(message.get("sender_role") or message.get("sender") or ""),
                "visual_side": str(message.get("visual_side") or ""),
                "visual_occurrence_id": str(message.get("visual_occurrence_id") or ""),
                "wechat_message_time": str(message.get("wechat_message_time") or ""),
                "visual_index": int(message.get("visual_index") or 0),
                "visual_observation_id": str(message.get("visual_observation_id") or ""),
                "bubble_bounds": [int(value) for value in (message.get("bubble_bounds") or [])[:4]],
                "saved_image_path": saved_path,
                "source_preview": str(message.get("pending_signal_text") or message.get("source_preview") or ""),
                "captured_at": str(message.get("captured_at") or ""),
                "pending_signal_id": str(message.get("pending_signal_id") or ""),
            }
        )
    return result


def customer_scoped_image_asset(asset: dict[str, Any]) -> bool:
    side = str(asset.get("visual_side") or "").strip().lower()
    sender = str(asset.get("sender") or asset.get("sender_role") or "").strip().lower()
    if side == "self" or sender in {"self", "assistant", "agent", "me", "outbound"}:
        return False
    return True


def call_image_save_sidecar(
    connector: Any,
    *,
    target_name: str,
    exact: bool,
    session_key: str,
    artifact_dir: Path,
    pending_signal: dict[str, Any],
) -> dict[str, Any]:
    source_preview = str(pending_signal.get("pending_signal_text") or pending_signal.get("preview_content") or "").strip()
    speaker_name = parse_preview_speaker(source_preview, pending_signal.get("speaker_name") or pending_signal.get("group_member_name") or "")
    pending_signal_id = str(pending_signal.get("pending_signal_id") or "").strip()
    tenant_id = str(os.getenv("WECHAT_KNOWLEDGE_TENANT") or "").strip()
    save_method = getattr(connector, "save_customer_image", None)
    if callable(save_method):
        return save_method(
            target_name,
            exact=exact,
            session_key=session_key,
            artifact_dir=str(artifact_dir),
            source_preview=source_preview,
            speaker_name=speaker_name,
            pending_signal_id=pending_signal_id,
            tenant_id=tenant_id,
            max_images=1,
        )
    compat_call = getattr(connector, "call_compat_sidecar", None)
    if not callable(compat_call):
        return {"ok": False, "state": "image_save_unsupported", "reason": "compat_sidecar_image_save_not_supported", "assets": [], "messages": []}
    args = ["image-save", "--target", target_name]
    if exact:
        args.append("--exact")
    clean_session_key = str(session_key or "").strip()
    if clean_session_key:
        args.extend(["--session-key", clean_session_key])
    args.extend(["--artifact-dir", str(artifact_dir)])
    if source_preview:
        args.extend(["--source-preview", source_preview])
    if speaker_name:
        args.extend(["--speaker-name", speaker_name])
    if pending_signal_id:
        args.extend(["--pending-signal-id", pending_signal_id])
    if tenant_id:
        args.extend(["--tenant-id", tenant_id])
    return compat_call(args, allow_failure=True)


def capture_messages_with_artifact(
    connector: Any,
    *,
    target_name: str,
    exact: bool,
    session_key: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    args = ["messages", "--target", target_name]
    if exact:
        args.append("--exact")
    clean_session_key = str(session_key or "").strip()
    if clean_session_key:
        args.extend(["--session-key", clean_session_key])
    args.extend(["--artifact-dir", str(artifact_dir)])
    return connector.call_compat_sidecar(args, allow_failure=True)


def detect_customer_image_region(
    screenshot_path: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    image_path = Path(str(screenshot_path or ""))
    if not image_path.exists():
        return {"ok": False, "reason": "screenshot_path_missing"}
    with Image.open(image_path) as screenshot:
        image = screenshot.convert("RGB")
        width, height = image.size
        split_x = session_split_x(width)
        top = chat_header_cutoff_y(height)
        bottom = height - max(DEFAULT_BOTTOM_EXCLUDE_PX, int(height * 0.10))
        left = min(width - 1, split_x + 12)
        if bottom <= top or width <= left:
            return {"ok": False, "reason": "chat_surface_invalid"}
        crop = image.crop((left, top, width, bottom))
        scale = min(1.0, 180.0 / max(1, crop.width), 240.0 / max(1, crop.height))
        small_w = max(24, int(crop.width * scale))
        small_h = max(24, int(crop.height * scale))
        small = crop.resize((small_w, small_h), Image.Resampling.BILINEAR)
        block = 4
        grid_w = max(1, small.width // block)
        grid_h = max(1, small.height // block)
        blocked: set[tuple[int, int]] = set()
        for message in messages:
            if not isinstance(message, dict):
                continue
            rect = message.get("bubble_rect") if isinstance(message.get("bubble_rect"), dict) else {}
            if not rect:
                continue
            rect_left = max(left, int(rect.get("left") or 0) - 10) - left
            rect_top = max(top, int(rect.get("top") or 0) - 10) - top
            rect_right = min(width, int(rect.get("right") or 0) + 10) - left
            rect_bottom = min(bottom, int(rect.get("bottom") or 0) + 10) - top
            if rect_right <= rect_left or rect_bottom <= rect_top:
                continue
            sx0 = max(0, int(rect_left * scale) // block)
            sy0 = max(0, int(rect_top * scale) // block)
            sx1 = min(grid_w - 1, max(0, int(rect_right * scale) // block))
            sy1 = min(grid_h - 1, max(0, int(rect_bottom * scale) // block))
            for sy in range(sy0, sy1 + 1):
                for sx in range(sx0, sx1 + 1):
                    blocked.add((sx, sy))
        active = [[False for _ in range(grid_w)] for _ in range(grid_h)]
        for sy in range(grid_h):
            for sx in range(grid_w):
                if (sx, sy) in blocked:
                    continue
                box = (
                    sx * block,
                    sy * block,
                    min(small.width, (sx + 1) * block),
                    min(small.height, (sy + 1) * block),
                )
                tile = small.crop(box)
                stat = ImageStat.Stat(tile)
                color_spread = sum(float(value) for value in (stat.stddev or [0.0, 0.0, 0.0])) / 3.0
                mean = stat.mean or [0.0, 0.0, 0.0]
                color_delta = max(mean) - min(mean)
                active[sy][sx] = color_spread >= 18.0 or color_delta >= 26.0
        visited: set[tuple[int, int]] = set()
        components: list[dict[str, Any]] = []
        for sy in range(grid_h):
            for sx in range(grid_w):
                if not active[sy][sx] or (sx, sy) in visited:
                    continue
                queue = [(sx, sy)]
                visited.add((sx, sy))
                cells: list[tuple[int, int]] = []
                while queue:
                    cx, cy = queue.pop()
                    cells.append((cx, cy))
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if nx < 0 or ny < 0 or nx >= grid_w or ny >= grid_h:
                            continue
                        if not active[ny][nx] or (nx, ny) in visited:
                            continue
                        visited.add((nx, ny))
                        queue.append((nx, ny))
                min_x = min(cell[0] for cell in cells)
                max_x = max(cell[0] for cell in cells)
                min_y = min(cell[1] for cell in cells)
                max_y = max(cell[1] for cell in cells)
                left_px = left + int((min_x * block) / scale)
                top_px = top + int((min_y * block) / scale)
                right_px = left + int(min(crop.width, ((max_x + 1) * block) / scale))
                bottom_px = top + int(min(crop.height, ((max_y + 1) * block) / scale))
                box_width = max(0, right_px - left_px)
                box_height = max(0, bottom_px - top_px)
                area = box_width * box_height
                if box_width < 90 or box_height < 90 or area < 14000:
                    continue
                center_x = (left_px + right_px) / 2.0
                customer_side = center_x <= (split_x + (width - split_x) * 0.56)
                score = area + (bottom_px * 8) + (6000 if customer_side else -6000)
                components.append(
                    {
                        "bounds": [left_px, top_px, right_px, bottom_px],
                        "width": box_width,
                        "height": box_height,
                        "area": area,
                        "side": "customer" if customer_side else "self",
                        "score": score,
                    }
                )
        if not components:
            return {"ok": False, "reason": "no_visual_region_detected"}
        components.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        best = components[0]
        return {"ok": True, "reason": "visual_region_detected", "candidate_count": len(components), **best}


def maybe_collect_customer_image_assets(
    connector: Any,
    *,
    target_name: str,
    exact: bool,
    session_key: str,
    payload: dict[str, Any],
    target_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    artifact_dir = visual_artifact_dir(target_name=target_name, session_key=session_key)
    source_payload = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    explicit_customer_assets = (
        source_payload.get("customer_image_assets")
        if isinstance(source_payload.get("customer_image_assets"), dict)
        else {}
    )
    if explicit_customer_assets.get("ok") and explicit_customer_assets.get("assets"):
        assets = [
            item
            for item in (explicit_customer_assets.get("assets") or [])
            if isinstance(item, dict)
        ]
        messages = [
            item
            for item in (explicit_customer_assets.get("messages") or [])
            if isinstance(item, dict)
        ]
        if not messages:
            messages = [build_image_message_from_asset(item) for item in assets]
        for asset in assets:
            asset.setdefault("target_name", target_name)
            asset.setdefault("session_key", session_key)
        return {
            "applied": True,
            "reason": "scheduler_customer_image_assets_ready",
            "artifact_dir": str(artifact_dir),
            "source_payload": {
                "state": str(source_payload.get("state") or ""),
                "adapter": str(source_payload.get("adapter") or ""),
            },
            "assets": assets,
            "messages": build_brain_safe_image_proxy_messages(
                messages,
                target_name=target_name,
                session_key=session_key,
            ),
        }
    payload_assets = [
        item
        for item in assets_from_payload_messages(source_payload)
        if customer_scoped_image_asset(item)
    ]
    if payload_assets:
        for asset in payload_assets:
            asset.setdefault("target_name", target_name)
            asset.setdefault("session_key", session_key)
        return {
            "applied": True,
            "reason": "payload_saved_image_asset_ready",
            "artifact_dir": str(artifact_dir),
            "source_payload": {
                "state": str(source_payload.get("state") or ""),
                "adapter": str(source_payload.get("adapter") or ""),
            },
            "assets": payload_assets,
            "messages": build_brain_safe_image_proxy_messages(
                [
                    item
                    for item in (source_payload.get("messages") or [])
                    if isinstance(item, dict)
                    and str(item.get("saved_image_path") or "").strip()
                    and customer_scoped_image_asset(item)
                ],
                target_name=target_name,
                session_key=session_key,
            ),
        }
    pending_signal = payload_image_pending_signal(source_payload, target_state)
    if pending_signal:
        saved = call_image_save_sidecar(
            connector,
            target_name=target_name,
            exact=exact,
            session_key=session_key,
            artifact_dir=artifact_dir,
            pending_signal=pending_signal,
        )
        if isinstance(saved, dict) and saved.get("ok") and saved.get("assets"):
            assets = [item for item in (saved.get("assets") or []) if isinstance(item, dict)]
            for asset in assets:
                asset.setdefault("message_type", "image")
                asset.setdefault("target_name", target_name)
                asset.setdefault("session_key", session_key)
                asset.setdefault("source_preview", str(pending_signal.get("pending_signal_text") or pending_signal.get("preview_content") or ""))
                if pending_signal.get("pending_signal_id"):
                    asset.setdefault("pending_signal_id", str(pending_signal.get("pending_signal_id") or ""))
            messages = [item for item in (saved.get("messages") or []) if isinstance(item, dict)]
            if not messages:
                messages = [build_image_message_from_asset(item) for item in assets]
            messages = build_brain_safe_image_proxy_messages(
                messages,
                target_name=target_name,
                session_key=session_key,
            )
            return {
                "applied": True,
                "reason": "wechat_image_saved",
                "artifact_dir": str(artifact_dir),
                "source_payload": {
                    "state": str(source_payload.get("state") or ""),
                    "adapter": str(source_payload.get("adapter") or ""),
                },
                "pending_signal": dict(pending_signal),
                "assets": assets,
                "messages": messages,
                "image_save": saved,
            }
        return {
            "applied": False,
            "reason": str((saved or {}).get("reason") or (saved or {}).get("state") or "wechat_image_save_failed"),
            "artifact_dir": str(artifact_dir),
            "source_payload": {
                "state": str(source_payload.get("state") or ""),
                "adapter": str(source_payload.get("adapter") or ""),
            },
            "pending_signal": dict(pending_signal),
            "assets": [],
            "messages": [],
            "image_save": saved if isinstance(saved, dict) else {"ok": False, "state": "image_save_invalid_result"},
        }
    screenshot_path = str(source_payload.get("screenshot_path") or "").strip()
    messages = [item for item in source_payload.get("messages", []) or [] if isinstance(item, dict)]
    if not screenshot_path or not Path(screenshot_path).exists():
        compat_call = getattr(connector, "call_compat_sidecar", None)
        if not callable(compat_call):
            return {
                "applied": False,
                "reason": "compat_sidecar_capture_not_supported",
                "artifact_dir": str(artifact_dir),
                "source_payload": {
                    "state": str(source_payload.get("state") or ""),
                    "adapter": str(source_payload.get("adapter") or ""),
                },
                "assets": [],
            }
        refreshed = capture_messages_with_artifact(
            connector,
            target_name=target_name,
            exact=exact,
            session_key=session_key,
            artifact_dir=artifact_dir,
        )
        if isinstance(refreshed, dict):
            source_payload = refreshed
            screenshot_path = str(refreshed.get("screenshot_path") or "").strip()
            messages = [item for item in refreshed.get("messages", []) or [] if isinstance(item, dict)]
    if not screenshot_path or not Path(screenshot_path).exists():
        return {
            "applied": False,
            "reason": "screenshot_unavailable",
            "artifact_dir": str(artifact_dir),
            "source_payload": {
                "state": str(source_payload.get("state") or ""),
                "adapter": str(source_payload.get("adapter") or ""),
            },
            "assets": [],
        }
    detected = detect_customer_image_region(screenshot_path, messages)
    if not detected.get("ok"):
        return {
            "applied": False,
            "reason": str(detected.get("reason") or "visual_region_missing"),
            "artifact_dir": str(artifact_dir),
            "screenshot_path": screenshot_path,
            "source_payload": {
                "state": str(source_payload.get("state") or ""),
                "adapter": str(source_payload.get("adapter") or ""),
            },
            "assets": [],
        }
    bounds = [int(value) for value in (detected.get("bounds") or [])[:4]]
    with Image.open(Path(screenshot_path)) as raw:
        image = raw.convert("RGB")
        crop = image.crop(tuple(bounds))
        digest = hashlib.sha1(f"{target_name}|{session_key}|{screenshot_path}|{bounds}".encode("utf-8")).hexdigest()[:16]
        crop_path = artifact_dir / f"customer_image_crop_{digest}.jpg"
        thumb_path = artifact_dir / f"customer_image_thumb_{digest}.jpg"
        crop.save(crop_path, format="JPEG", quality=90)
        thumbnail = crop.copy()
        thumbnail.thumbnail((512, 512), Image.Resampling.LANCZOS)
        thumbnail.save(thumb_path, format="JPEG", quality=88)
        asset = {
            "asset_id": f"visual_asset_{digest}",
            "message_id": f"visual_asset_message_{digest}",
            "conversation_id": str(source_payload.get("conversation_id") or ""),
            "target_name": target_name,
            "message_type": "image",
            "turn_capture_path": screenshot_path,
            "bubble_crop_path": str(crop_path),
            "thumbnail_path": str(thumb_path),
            "captured_at": now_iso(),
            "width": int(crop.width),
            "height": int(crop.height),
            "bounds": bounds,
            "side": str(detected.get("side") or "customer"),
            "sha1": digest,
        }
    return {
        "applied": True,
        "reason": "customer_image_asset_ready",
        "artifact_dir": str(artifact_dir),
        "screenshot_path": screenshot_path,
        "source_payload": {
            "state": str(source_payload.get("state") or ""),
            "adapter": str(source_payload.get("adapter") or ""),
        },
        "assets": [asset],
    }
