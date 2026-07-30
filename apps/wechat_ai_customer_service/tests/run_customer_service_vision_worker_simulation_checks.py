from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.integrations.wechat_worker import (  # noqa: E402
    run_operation,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.integrations import wechat_current  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import session_split_x  # noqa: E402


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


class _Win32Con:
    VK_ESCAPE = 0x1B


class FakeGenericWeChatHost:
    _WIN32_IMPORT_ERROR = ""
    DEFAULT_QUICK_LOGIN_AUTO_ENTER = False
    win32con = _Win32Con()
    win32gui = None

    def __init__(self) -> None:
        self.surface = Image.new("RGB", (980, 860), (247, 247, 247))
        draw = ImageDraw.Draw(self.surface)
        split = session_split_x(980)
        draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
        draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
        draw.rectangle([split + 42, 250, split + 282, 470], fill=(30, 120, 190))
        draw.rectangle([760, 500, 940, 660], fill=(190, 80, 50))
        self.menu = self.surface.copy()
        self.capture_artifact_dirs: list[str | None] = []
        self.generations = [41, 42]
        self.right_clicks = 0
        self.menu_clicks = 0

    @staticmethod
    def configure_dpi_awareness() -> None:
        return None

    @staticmethod
    def ensure_visible_wechat_window(*, interactive: bool) -> dict[str, Any]:
        assert_true(interactive, "vision worker target preparation must be interactive")
        return {"visible_main_windows": [{"hwnd": 100, "title": "WeChat"}]}

    @staticmethod
    def select_primary_visible_main_window(probe: dict[str, Any]) -> dict[str, Any]:
        return dict(probe["visible_main_windows"][0])

    @staticmethod
    def dismiss_blank_foreground_window_before_activation(_hwnd: int, *, artifact_dir: str | None) -> dict[str, Any]:
        assert_true(artifact_dir is None, "vision worker may not allocate an artifact directory")
        return {"attempted": False}

    @staticmethod
    def activate_window(_hwnd: int) -> None:
        return None

    @staticmethod
    def normalize_wechat_window(_hwnd: int) -> dict[str, Any]:
        return {"ok": True, "applied": False}

    @staticmethod
    def ensure_quick_login_if_available(_hwnd: int, *, artifact_dir: str | None, auto_enter: bool) -> dict[str, Any]:
        assert_true(artifact_dir is None and not auto_enter, "quick-login probe must stay artifact-free")
        return {"attempted": False}

    @staticmethod
    def env_flag(_name: str, *, default: bool) -> bool:
        return default

    @staticmethod
    def humanized_action_sleep(_minimum: int, _maximum: int) -> None:
        return None

    @staticmethod
    def normalize_identity_conversation_type(value: str) -> str:
        return str(value or "")

    @staticmethod
    def validate_active_send_target_for_identity(
        _hwnd: int,
        target: str,
        *,
        exact: bool,
        artifact_dir: str | None,
        session_key: str,
        conversation_type: str,
    ) -> dict[str, Any]:
        assert_true(target == "Customer A" and exact, "worker must preserve exact target identity")
        assert_true(artifact_dir is None, "target validation may not persist screenshots")
        return {"ok": True, "session_key": session_key, "conversation_type": conversation_type}

    @staticmethod
    def open_chat_for_identity(*_args: Any, **_kwargs: Any) -> bool:
        raise AssertionError("already-confirmed target must not be reopened")

    @staticmethod
    def scroll_to_latest_before_read_enabled() -> bool:
        return True

    @staticmethod
    def scroll_chat_to_latest(_hwnd: int) -> None:
        return None

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        return self.surface, ""

    def capture_wechat_window_visible_screen(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        return self.menu, ""

    def run_ocr(self, image: Image.Image) -> list[dict[str, Any]]:
        if image is self.menu:
            return [{"text": "复制", "left": 600, "top": 488, "right": 636, "bottom": 508, "confidence": 0.95}]
        return []

    @staticmethod
    def parse_messages_from_ocr(_items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def blocking_screen_reason(_items: list[dict[str, Any]]) -> str:
        return ""

    @staticmethod
    def get_window_geometry(_hwnd: int) -> dict[str, int]:
        return {"width": 980, "height": 860}

    def clipboard_sequence_number(self) -> int:
        if len(self.generations) > 1:
            return self.generations.pop(0)
        return self.generations[0]

    def human_window_image_right_click_in_bounds(
        self,
        _hwnd: int,
        _x: int,
        _y: int,
        *,
        bounds: list[int],
        action_name: str,
    ) -> dict[str, Any]:
        self.right_clicks += 1
        return {"ok": True, "bounds": bounds, "action_name": action_name}

    def human_window_image_click_in_bounds(
        self,
        _hwnd: int,
        _x: int,
        _y: int,
        *,
        bounds: list[int],
        action_name: str,
    ) -> dict[str, Any]:
        self.menu_clicks += 1
        return {"ok": True, "bounds": bounds, "action_name": action_name}

    @staticmethod
    def key_press(_key: int) -> None:
        return None


def _args(operation: str, *, side_filter: str = "all") -> argparse.Namespace:
    return argparse.Namespace(
        operation=operation,
        target="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        exact=True,
        source_preview="[图片]",
        speaker_name="",
        pending_signal_id="pending-image-1",
        side_filter=side_filter,
        max_images=8,
    )


def check_worker_observes_both_directions_without_artifacts() -> None:
    host = FakeGenericWeChatHost()
    result = run_operation(_args("observe-current-surface"), host_ops=host)
    assert_true(result.get("ok") is True, f"surface observation failed: {result}")
    messages = result.get("messages") or []
    sides = {str(item.get("visual_side") or "") for item in messages}
    assert_true(sides == {"customer", "self"}, f"worker lost image direction: {messages}")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert_true("bounds" not in serialized and "screenshot_path" not in serialized, "worker leaked geometry or screenshot metadata")
    assert_true(host.capture_artifact_dirs == [None], "surface observation must be transient")


def check_worker_copies_current_customer_image_without_sidecar_action() -> None:
    host = FakeGenericWeChatHost()
    result = run_operation(
        _args("copy-current-image", side_filter="customer"),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"clipboard transaction failed: {result}")
    transaction = result.get("transaction") or {}
    assert_true(transaction.get("clipboard_sequence_after") == 42, "copy must prove a new clipboard generation")
    assert_true(transaction.get("visual_side") == "customer", "copy must preserve direction proof")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "copy must use one bounded right-click and one Copy click")
    assert_true(host.capture_artifact_dirs == [None, None], "copy transaction must not persist screenshots")


def check_production_integration_calls_vision_worker_not_sidecar_action() -> None:
    class ConnectorWithoutSidecarImageAction:
        timeout_seconds = 5

    calls: list[list[str]] = []
    original_runner = wechat_current._run_vision_worker
    previous_lock_disabled = os.environ.get("WECHAT_RPA_LOCK_DISABLED")
    wechat_current._run_vision_worker = lambda _connector, args: (
        calls.append(list(args))
        or {
            "ok": True,
            "state": "image_clipboard_copied",
            "assets": [],
            "messages": [],
            "transaction": {
                "status": "copied",
                "clipboard_sequence_changed": True,
                "clipboard_sequence_after": 91,
                "visual_side": "customer",
            },
        }
    )
    os.environ["WECHAT_RPA_LOCK_DISABLED"] = "1"
    try:
        result = wechat_current.run_clipboard_image_transaction(
            ConnectorWithoutSidecarImageAction(),
            "Customer A",
            session_key="wx:vision-integration",
            pending_signal_id="pending-image-2",
            consume_current_clipboard=lambda transaction: {
                "ok": transaction.get("clipboard_sequence_after") == 91,
                "image": bytearray(b"ephemeral"),
            },
        )
    finally:
        wechat_current._run_vision_worker = original_runner
        if previous_lock_disabled is None:
            os.environ.pop("WECHAT_RPA_LOCK_DISABLED", None)
        else:
            os.environ["WECHAT_RPA_LOCK_DISABLED"] = previous_lock_disabled
    assert_true(result.get("ok") is True, f"production integration failed: {result}")
    assert_true(calls and calls[0][0] == "copy-current-image", f"vision-owned worker was not used: {calls}")
    assert_true("image-clipboard-copy" not in calls[0], f"retired Sidecar action leaked into integration: {calls}")


def main() -> int:
    checks = [
        check_worker_observes_both_directions_without_artifacts,
        check_worker_copies_current_customer_image_without_sidecar_action,
        check_production_integration_calls_vision_worker_not_sidecar_action,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
