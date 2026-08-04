"""Current WeChat host binding for the vision-owned clipboard transaction.

All image-specific action construction, clipboard state, and customer/self
selection live here.  The shared connector supplies only generic transport and
the process-wide RPA lock primitives.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from ..capture.wechat import DEFAULT_MAX_VISIBLE_IMAGE_CANDIDATES


_WORKER_MODULE = (
    "apps.wechat_ai_customer_service.optional_plugins.vision.integrations.wechat_worker"
)
_GROUP_WORKER_MODULE = (
    "apps.wechat_ai_customer_service.optional_plugins.vision.integrations.wechat_group_worker"
)


def _worker_python(connector: Any) -> str:
    return str(
        getattr(connector, "compat_sidecar_python", "")
        or getattr(connector, "sidecar_python", "")
        or sys.executable
    )


def _worker_root(connector: Any) -> Path:
    configured = getattr(connector, "root", None)
    return Path(configured) if configured else Path(__file__).resolve().parents[5]


def _worker_failure(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "adapter": "win32_ocr",
        "state": state,
        "reason": reason,
        "assets": [],
        "messages": [],
        **extra,
    }


def _run_worker_module(
    connector: Any,
    module: str,
    args: list[str],
    *,
    stdin_payload: str | None = None,
    state_prefix: str = "vision_wechat_worker",
) -> dict[str, Any]:
    command = [_worker_python(connector), "-m", module, *args]
    timeout = max(5.0, float(getattr(connector, "timeout_seconds", 90.0) or 90.0))
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    worker_env = os.environ.copy()
    # PR #28 deliberately remains byte-immutable.  Its generic Win32 host
    # defaults fixed-origin normalization off, while OmniAuto's existing
    # physical-coordinate contract requires it on.  The normal Connector path
    # receives this host policy from ``wechat_pr28_runtime_adapter``; Vision
    # starts its own worker and therefore must carry the same additive default
    # at this external binding.  An explicit operator setting still wins.
    worker_env.setdefault("WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN", "1")
    try:
        completed = subprocess.run(
            command,
            cwd=str(_worker_root(connector)),
            env=worker_env,
            input=stdin_payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=creationflags,
        )
    except subprocess.TimeoutExpired as exc:
        return _worker_failure(
            f"{state_prefix}_timeout",
            f"{state_prefix}_timeout",
            error=repr(exc),
        )
    except Exception as exc:  # noqa: BLE001 - optional worker fails closed.
        return _worker_failure(
            f"{state_prefix}_failed",
            f"{state_prefix}_failed",
            error=repr(exc),
        )
    stdout = str(completed.stdout or "").strip()
    try:
        payload = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict) or not payload:
        return _worker_failure(
            f"{state_prefix}_invalid_response",
            f"{state_prefix}_invalid_response",
            returncode=int(completed.returncode),
            stderr=str(completed.stderr or "").strip()[-2000:],
        )
    payload.setdefault("adapter", "win32_ocr")
    payload.setdefault("assets", [])
    payload.setdefault("messages", [])
    if completed.returncode and payload.get("ok"):
        payload["ok"] = False
        payload["state"] = f"{state_prefix}_exit_mismatch"
        payload["reason"] = f"{state_prefix}_exit_mismatch"
    return payload


def _run_vision_worker(connector: Any, args: list[str]) -> dict[str, Any]:
    return _run_worker_module(connector, _WORKER_MODULE, list(args))


def _run_private_group_worker(connector: Any, request: dict[str, Any]) -> dict[str, Any]:
    return _run_worker_module(
        connector,
        _GROUP_WORKER_MODULE,
        [],
        stdin_payload=json.dumps(dict(request or {}), ensure_ascii=False),
        state_prefix="vision_visual_group_worker",
    )


def observe_current_surface(
    connector: Any,
    target: str,
    exact: bool = True,
    *,
    session_key: str = "",
    conversation_type: str = "",
    side_filter: str = "all",
    max_images: int = 8,
) -> dict[str, Any]:
    """Return text-only structural image envelopes from the current chat."""

    from apps.wechat_ai_customer_service.adapters.wechat_connector import (
        any_weixin_process,
        attach_rpa_lock_meta,
        rpa_lock_timeout_payload,
        rpa_lock_timeout_seconds,
        wechat_rpa_lock,
    )

    clean_side = str(side_filter or "all").strip().lower()
    if clean_side not in {"customer", "self", "all"}:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_current_surface_side_invalid",
            "reason": "vision_current_surface_side_invalid",
            "assets": [],
            "messages": [],
        }
    if not target:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_current_surface_target_missing",
            "reason": "target_missing",
            "assets": [],
            "messages": [],
        }
    worker_args = [
        "observe-current-surface",
        "--target",
        str(target),
        "--side-filter",
        clean_side,
        "--max-images",
        str(
            max(
                1,
                min(
                    int(max_images or 8),
                    DEFAULT_MAX_VISIBLE_IMAGE_CANDIDATES,
                ),
            )
        ),
    ]
    if exact:
        worker_args.append("--exact")
    from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (
        physical_rpa_identity_kwargs,
    )

    physical_identity = physical_rpa_identity_kwargs(
        {"session_key": session_key, "conversation_type": conversation_type}
    )
    for value, flag in (
        (session_key, "--session-key"),
        (physical_identity.get("conversation_type"), "--conversation-type"),
    ):
        clean = str(value or "").strip()
        if clean:
            worker_args.extend([flag, clean])
    lock_timeout = rpa_lock_timeout_seconds("vision_current_surface_observation", default=45.0)
    try:
        with wechat_rpa_lock(
            "vision_current_surface_observation",
            timeout_seconds=lock_timeout,
        ) as lock_meta:
            result = _run_vision_worker(connector, worker_args)
            result.setdefault("transport_priority", "rpa_first")
            attach_rpa_lock_meta(result, lock_meta)
            return result
    except TimeoutError as exc:
        return {
            "ok": False,
            "online": bool(any_weixin_process()),
            "adapter": "win32_ocr",
            "state": "vision_current_surface_lock_timeout",
            "reason": "vision_current_surface_lock_timeout",
            "target": target,
            "exact": exact,
            "assets": [],
            "messages": [],
            "error": repr(exc),
            "transport_priority": "rpa_first",
            "rpa_lock": rpa_lock_timeout_payload(
                exc,
                action="vision_current_surface_observation",
                timeout_seconds=lock_timeout,
            ),
        }


def locate_current_visual_group(
    connector: Any,
    target: str,
    exact: bool = True,
    *,
    session_key: str = "",
    conversation_type: str = "",
    explicit_image_pending: bool = False,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    max_images: int = 1,
    max_scroll_steps: int | None = None,
    max_snapshots: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    """Vision-private locate-only wrapper around the bundled worker."""

    from apps.wechat_ai_customer_service.adapters.wechat_connector import (
        any_weixin_process,
        attach_rpa_lock_meta,
        rpa_lock_timeout_payload,
        rpa_lock_timeout_seconds,
        wechat_rpa_lock,
    )

    if not target:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_visual_group_target_missing",
            "reason": "target_missing",
            "assets": [],
            "messages": [],
        }
    if not str(session_key or "").strip() or not str(conversation_type or "").strip():
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_visual_group_scope_missing",
            "reason": "visual_group_request_scope_missing",
            "assets": [],
            "messages": [],
        }
    request = {
        "target": str(target),
        "exact": bool(exact),
        "session_key": str(session_key),
        "conversation_type": str(conversation_type),
        "explicit_image_pending": bool(explicit_image_pending),
        "anchor_text_key": str(anchor_text_key or ""),
        "anchor_message_id": str(anchor_message_id or ""),
        "max_images": max(1, min(int(max_images or 1), 3)),
    }
    if max_scroll_steps is not None:
        request["max_scroll_steps"] = int(max_scroll_steps)
    if max_snapshots is not None:
        request["max_snapshots"] = int(max_snapshots)
    if max_seconds is not None:
        request["max_seconds"] = float(max_seconds)
    lock_timeout = rpa_lock_timeout_seconds("vision_current_visual_group_locate", default=45.0)
    try:
        with wechat_rpa_lock(
            "vision_current_visual_group_locate",
            timeout_seconds=lock_timeout,
        ) as lock_meta:
            result = _run_private_group_worker(connector, request)
            result.setdefault("transport_priority", "rpa_first")
            attach_rpa_lock_meta(result, lock_meta)
            return result
    except TimeoutError as exc:
        return {
            "ok": False,
            "online": bool(any_weixin_process()),
            "adapter": "win32_ocr",
            "state": "vision_current_visual_group_locate_lock_timeout",
            "reason": "vision_current_visual_group_locate_lock_timeout",
            "target": target,
            "exact": exact,
            "assets": [],
            "messages": [],
            "error": repr(exc),
            "transport_priority": "rpa_first",
            "rpa_lock": rpa_lock_timeout_payload(
                exc,
                action="vision_current_visual_group_locate",
                timeout_seconds=lock_timeout,
            ),
        }


def _decode_private_image_payloads(result: dict[str, Any]) -> dict[str, Any]:
    from apps.wechat_ai_customer_service.optional_plugins.vision.clipboard_payload import (
        EphemeralClipboardImage,
    )
    from apps.wechat_ai_customer_service.optional_plugins.vision.understanding.provider import (
        MAX_IMAGE_PAYLOAD_BYTES,
        MAX_IMAGE_SOURCE_BYTES,
    )

    payloads = result.pop("_private_image_payloads", None)
    if not isinstance(payloads, list) or not 1 <= len(payloads) <= 3:
        result["ok"] = False
        result["state"] = "vision_visual_group_acquire_failed"
        result["reason"] = "visual_group_private_payload_missing"
        return result
    decoded: list[EphemeralClipboardImage] = []
    total_wire = 0
    try:
        for payload in payloads:
            if not isinstance(payload, dict):
                raise ValueError("visual_group_private_payload_invalid")
            encoded = str(payload.get("data") or "")
            total_wire += len(encoded.encode("ascii", errors="ignore"))
            if total_wire > MAX_IMAGE_SOURCE_BYTES:
                raise ValueError("visual_group_wire_payload_too_large")
            raw = base64.b64decode(encoded.encode("ascii"), validate=True)
            if not raw or len(raw) > MAX_IMAGE_PAYLOAD_BYTES:
                raise ValueError("visual_group_private_payload_invalid")
            decoded.append(
                EphemeralClipboardImage(
                    image_bytes=bytearray(raw),
                    mime_type=str(payload.get("mime_type") or "image/png"),
                    width=max(0, int(payload.get("width") or 0)),
                    height=max(0, int(payload.get("height") or 0)),
                )
            )
    except Exception as exc:  # noqa: BLE001 - private wire failures fail closed.
        for image in decoded:
            image.release()
        result["ok"] = False
        result["state"] = "vision_visual_group_acquire_failed"
        result["reason"] = str(exc) or "visual_group_private_payload_invalid"
        return result
    result["_ephemeral_clipboard_images"] = decoded
    if decoded:
        result["_ephemeral_clipboard_image"] = decoded[0]
    return result


def _acquire_current_visual_group(
    connector: Any,
    target: str,
    exact: bool = True,
    *,
    session_key: str = "",
    conversation_type: str = "",
    explicit_image_pending: bool = False,
    anchor_text_key: str = "",
    anchor_message_id: str = "",
    max_images: int = 1,
    max_scroll_steps: int | None = None,
    max_snapshots: int | None = None,
    max_seconds: float | None = None,
) -> dict[str, Any]:
    """Vision-private acquire wrapper; does not call a provider or Brain."""

    if not target:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_visual_group_target_missing",
            "reason": "target_missing",
            "assets": [],
            "messages": [],
        }
    if not str(session_key or "").strip() or not str(conversation_type or "").strip():
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "vision_visual_group_scope_missing",
            "reason": "visual_group_request_scope_missing",
            "assets": [],
            "messages": [],
        }
    request = {
        "mode": "acquire",
        "target": str(target),
        "exact": bool(exact),
        "session_key": str(session_key),
        "conversation_type": str(conversation_type),
        "explicit_image_pending": bool(explicit_image_pending),
        "anchor_text_key": str(anchor_text_key or ""),
        "anchor_message_id": str(anchor_message_id or ""),
        "max_images": max(1, min(int(max_images or 1), 3)),
    }
    if max_scroll_steps is not None:
        request["max_scroll_steps"] = int(max_scroll_steps)
    if max_snapshots is not None:
        request["max_snapshots"] = int(max_snapshots)
    if max_seconds is not None:
        request["max_seconds"] = float(max_seconds)
    from apps.wechat_ai_customer_service.adapters.wechat_connector import (
        any_weixin_process,
        attach_rpa_lock_meta,
        rpa_lock_timeout_payload,
        rpa_lock_timeout_seconds,
        wechat_rpa_lock,
    )

    lock_timeout = rpa_lock_timeout_seconds("vision_current_visual_group_acquire", default=45.0)
    try:
        with wechat_rpa_lock(
            "vision_current_visual_group_acquire",
            timeout_seconds=lock_timeout,
        ) as lock_meta:
            acquired = _run_private_group_worker(connector, request)
            acquired.setdefault("transport_priority", "rpa_first")
            attach_rpa_lock_meta(acquired, lock_meta)
            acquired = _decode_private_image_payloads(acquired) if acquired.get("ok") else acquired
            acquired.pop("_private_image_payloads", None)
            return acquired
    except TimeoutError as exc:
        return {
            "ok": False,
            "online": bool(any_weixin_process()),
            "adapter": "win32_ocr",
            "state": "vision_current_visual_group_acquire_lock_timeout",
            "reason": "vision_current_visual_group_acquire_lock_timeout",
            "target": target,
            "exact": exact,
            "assets": [],
            "messages": [],
            "error": repr(exc),
            "transport_priority": "rpa_first",
            "rpa_lock": rpa_lock_timeout_payload(
                exc,
                action="vision_current_visual_group_acquire",
                timeout_seconds=lock_timeout,
            ),
        }


def run_clipboard_image_transaction(
    connector: Any,
    target: str,
    exact: bool = True,
    *,
    session_key: str = "",
    source_preview: str = "",
    speaker_name: str = "",
    pending_signal_id: str = "",
    side_filter: str = "customer",
    consume_current_clipboard: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from apps.wechat_ai_customer_service.adapters.wechat_connector import (
        any_weixin_process,
        attach_rpa_lock_meta,
        rpa_lock_timeout_payload,
        rpa_lock_timeout_seconds,
        wechat_rpa_lock,
    )

    clean_side_filter = str(side_filter or "customer").strip().lower()
    if clean_side_filter not in {"customer", "self"}:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "image_clipboard_copy_side_invalid",
            "reason": "image_clipboard_side_filter_invalid",
            "assets": [],
            "messages": [],
        }
    if not target:
        return {
            "ok": False,
            "adapter": "win32_ocr",
            "state": "image_clipboard_copy_target_missing",
            "reason": "target_missing",
            "assets": [],
            "messages": [],
        }
    args = ["copy-current-image", "--target", target, "--side-filter", clean_side_filter]
    clean_session_key = str(session_key or "").strip()
    if clean_session_key:
        args.extend(["--session-key", clean_session_key])
    if exact:
        args.append("--exact")
    for value, flag in (
        (source_preview, "--source-preview"),
        (speaker_name, "--speaker-name"),
        (pending_signal_id, "--pending-signal-id"),
    ):
        clean = str(value or "").strip()
        if clean:
            args.extend([flag, clean])
    lock_timeout = rpa_lock_timeout_seconds("image_clipboard_transaction", default=45.0)
    try:
        with wechat_rpa_lock("image_clipboard_transaction", timeout_seconds=lock_timeout) as lock_meta:
            primary = _run_vision_worker(connector, args)
            primary.setdefault("adapter", "win32_ocr")
            primary.setdefault("transport_priority", "rpa_first")
            attach_rpa_lock_meta(primary, lock_meta)
            if not primary.get("ok"):
                return primary
            if not callable(consume_current_clipboard):
                primary["ok"] = False
                primary["state"] = "image_clipboard_consumer_missing"
                primary["reason"] = "image_clipboard_consumer_missing"
                return primary
            transaction = primary.get("transaction") if isinstance(primary.get("transaction"), dict) else {}
            try:
                consumed = consume_current_clipboard(dict(transaction))
            except Exception as exc:  # noqa: BLE001
                consumed = {"ok": False, "reason": "clipboard_current_read_failed", "error": repr(exc)}
            if not isinstance(consumed, dict) or not consumed.get("ok"):
                primary["ok"] = False
                primary["state"] = "image_clipboard_current_read_failed"
                primary["reason"] = str((consumed or {}).get("reason") or "clipboard_current_read_failed")
                primary["transaction"] = {
                    **transaction,
                    "status": "failed",
                    "clipboard_content_read": False,
                }
                return primary
            primary["_ephemeral_clipboard_image"] = consumed.get("image")
            primary["transaction"] = {
                **transaction,
                "status": "clipboard_read",
                "clipboard_content_read": True,
                "clipboard_image_valid": True,
            }
            return primary
    except TimeoutError as exc:
        return {
            "ok": False,
            "online": bool(any_weixin_process()),
            "adapter": "win32_ocr",
            "state": "image_clipboard_transaction_lock_timeout",
            "reason": "image_clipboard_transaction_lock_timeout",
            "target": target,
            "exact": exact,
            "assets": [],
            "messages": [],
            "error": repr(exc),
            "transport_priority": "rpa_first",
            "rpa_lock": rpa_lock_timeout_payload(
                exc,
                action="image_clipboard_transaction",
                timeout_seconds=lock_timeout,
            ),
        }


def run_self_clipboard_image_transaction(
    connector: Any,
    target: str,
    exact: bool = True,
    *,
    session_key: str = "",
    source_preview: str = "",
    pending_signal_id: str = "",
    consume_current_clipboard: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return run_clipboard_image_transaction(
        connector,
        target,
        exact=exact,
        session_key=session_key,
        source_preview=source_preview,
        pending_signal_id=pending_signal_id,
        side_filter="self",
        consume_current_clipboard=consume_current_clipboard,
    )
