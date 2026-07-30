"""Private Vision worker for locate-only visual group collection.

This module is intentionally not added to the public ``wechat_worker`` CLI.
The parent Vision integration sends one JSON request on stdin and receives one
JSON response on stdout.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import Any

from .wechat_worker import _failure, _load_default_host, _prepare_target


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _prepare_args(request: dict[str, Any]) -> argparse.Namespace:
    conversation_type = _clean(request.get("conversation_type"))
    try:
        from apps.wechat_ai_customer_service.adapters.wechat_pr28_runtime_adapter import (
            physical_rpa_identity_kwargs,
        )

        physical_identity = physical_rpa_identity_kwargs(
            {
                "session_key": _clean(request.get("session_key")),
                "conversation_type": conversation_type,
            }
        )
        physical_conversation_type = _clean(physical_identity.get("conversation_type"))
    except Exception:  # pragma: no cover - custom host fallback.
        physical_conversation_type = conversation_type
    return argparse.Namespace(
        target=_clean(request.get("target")),
        session_key=_clean(request.get("session_key")),
        conversation_type=physical_conversation_type,
        exact=bool(request.get("exact", True)),
    )


def run_private_request(
    request: dict[str, Any],
    *,
    host_ops: Any | None = None,
) -> dict[str, Any]:
    from apps.wechat_ai_customer_service.optional_plugins.vision.capture.visual_collector import (
        acquire_current_turn_visual_group,
        locate_current_turn_visual_group,
    )

    host = host_ops or _load_default_host()
    prepared = _prepare_target(_prepare_args(request), host)
    if not prepared.get("ok"):
        return prepared
    collector = (
        acquire_current_turn_visual_group
        if _clean(request.get("mode")).lower() == "acquire"
        else locate_current_turn_visual_group
    )
    return collector(
        sidecar_ops=host,
        hwnd=int(prepared.get("hwnd") or 0),
        target_name=_clean(prepared.get("target")),
        session_key=_clean(prepared.get("session_key")),
        conversation_type=_clean(request.get("conversation_type")),
        explicit_image_pending=bool(request.get("explicit_image_pending")),
        anchor_text_key=_clean(request.get("anchor_text_key")),
        anchor_message_id=_clean(request.get("anchor_message_id")),
        exact=bool(request.get("exact", True)),
        side_filter="customer",
        max_images=max(1, min(int(request.get("max_images") or 3), 3)),
        max_scroll_steps=request.get("max_scroll_steps"),
        max_snapshots=request.get("max_snapshots"),
        max_seconds=request.get("max_seconds"),
    )


def main() -> int:
    captured = io.StringIO()
    try:
        raw = sys.stdin.read()
        request = json.loads(raw) if raw.strip() else {}
        if not isinstance(request, dict):
            request = {}
        with contextlib.redirect_stdout(captured):
            payload = run_private_request(request)
    except Exception as exc:  # noqa: BLE001
        payload = _failure(
            "vision_visual_group_worker_failed",
            "vision_visual_group_worker_failed",
            error=repr(exc),
        )
    logs = captured.getvalue().strip()
    if logs:
        payload["library_stdout"] = logs
    print(json.dumps(payload, ensure_ascii=True))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
