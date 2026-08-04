from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
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
from apps.wechat_ai_customer_service.optional_plugins.vision.integrations.wechat_group_worker import (  # noqa: E402
    run_private_request,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.visual_collector import (  # noqa: E402
    acquire_current_turn_visual_group,
    locate_current_turn_visual_group,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture import visual_collector  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.integrations import wechat_current  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.clipboard_payload import (  # noqa: E402
    EphemeralClipboardImage,
)
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
        self.sequence = 41
        self.copy_pending = False
        self.right_clicks = 0
        self.menu_clicks = 0
        self.history_scrolls = 0
        self.latest_restores = 0
        self.last_right_click_bounds: list[int] = []
        self.cleared_sequences: list[int] = []

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

    def scroll_chat_history(self, _hwnd: int, load_times: int) -> None:
        self.history_scrolls += int(load_times or 1)

    def restore_latest(self) -> None:
        self.latest_restores += 1

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
        if self.copy_pending:
            self.sequence += 1
            self.copy_pending = False
        return self.sequence

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
        self.last_right_click_bounds = [int(value) for value in bounds[:4]]
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
        self.copy_pending = True
        return {"ok": True, "bounds": bounds, "action_name": action_name}

    def read_current_bitmap(self) -> Image.Image:
        bounds = self.last_right_click_bounds or [550, 250, 790, 470]
        return self.surface.crop(tuple(bounds))

    def clear_current_clipboard_image(
        self,
        expected_sequence: int,
    ) -> dict[str, Any]:
        if int(expected_sequence) != self.sequence:
            return {"ok": False, "reason": "clipboard_sequence_not_current_for_clear"}
        self.cleared_sequences.append(int(expected_sequence))
        return {"ok": True}

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
    assert_true(host.cleared_sequences == [], "copy-only operation must leave the generation for its caller to consume")
    assert_true(host.capture_artifact_dirs == [None, None], "copy transaction must not persist screenshots")


def check_common_menu_observer_is_preferred_over_legacy_capture() -> None:
    class CommonMenuHost(FakeGenericWeChatHost):
        def __init__(self) -> None:
            super().__init__()
            self.menu_waits = 0
            self.menu_observations = 0

        def wait_for_wechat_context_menu_stable(self) -> int:
            self.menu_waits += 1
            return 1800

        def observe_wechat_context_menu(
            self,
            _hwnd: int,
            *,
            anchor_screen: tuple[int, int],
            artifact_dir: str | None,
            label: str,
        ) -> dict[str, Any]:
            assert_true(artifact_dir is None, "menu observation must stay transient")
            assert_true(label, "menu observation label is required")
            self.menu_observations += 1
            x, y = anchor_screen
            return {
                "ok": True,
                "image_size": (1920, 1080),
                "local_ocr_items": [
                    {
                        "text": "复制",
                        "left": x + 20,
                        "top": y + 10,
                        "right": x + 80,
                        "bottom": y + 40,
                        "center_x": x + 50,
                        "center_y": y + 25,
                        "confidence": 0.95,
                    }
                ],
            }

        def human_window_image_right_click_in_bounds(
            self,
            hwnd: int,
            x: int,
            y: int,
            *,
            bounds: list[int],
            action_name: str,
        ) -> dict[str, Any]:
            result = super().human_window_image_right_click_in_bounds(
                hwnd,
                x,
                y,
                bounds=bounds,
                action_name=action_name,
            )
            return {**result, "screen_x": 700, "screen_y": 420}

    host = CommonMenuHost()
    result = run_operation(
        _args("copy-current-image", side_filter="customer"),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"common menu copy failed: {result}")
    assert_true(host.menu_waits == 1 and host.menu_observations == 1, "common menu path must run once")
    assert_true(host.capture_artifact_dirs == [None], "legacy menu capture must not run when common observer exists")


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


def check_worker_locates_current_customer_visual_group_without_copy() -> None:
    host = FakeGenericWeChatHost()
    result = run_private_request(
        {
            "target": "Customer A",
            "session_key": "wx:vision-worker",
            "conversation_type": "private",
            "exact": True,
            "explicit_image_pending": True,
            "max_images": 3,
        },
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"current visual locate failed: {result}")
    messages = result.get("messages") or []
    assert_true(len(messages) == 1 and messages[0].get("visual_side") == "customer", f"locate must select the customer image only: {messages}")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert_true(
        "_vision_bounds" not in serialized
        and "_vision_has_self_message_after" not in serialized
        and "_vision_occurrence_ordinal" not in serialized
        and "_vision_transaction_ordinal" not in serialized,
        "locate must not leak private geometry or transaction ordinal fields",
    )
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "locate-only worker must not copy images")
    assert_true(host.history_scrolls == 0, "current-frame locate must not scroll")


def check_public_observe_current_surface_keeps_single_frame_semantics() -> None:
    host = BacksearchHost()
    result = run_operation(
        _args("observe-current-surface", side_filter="customer"),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"public observe must keep old behavior: {result}")
    assert_true(host.history_scrolls == 0 and host.latest_restores == 0, "public observe-current-surface must not backsearch or restore")
    assert_true((result.get("messages") or []) == [], "public observe must return only the first-frame observation")


class BacksearchHost(FakeGenericWeChatHost):
    def __init__(self) -> None:
        super().__init__()
        self.empty_surface = Image.new("RGB", (980, 860), (247, 247, 247))
        draw = ImageDraw.Draw(self.empty_surface)
        split = session_split_x(980)
        draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
        draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
        self.surface_index = 0

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        return (self.empty_surface if self.surface_index == 0 else self.surface), ""

    def scroll_chat_history(self, _hwnd: int, load_times: int) -> None:
        super().scroll_chat_history(_hwnd, load_times)
        self.surface_index = 1

    @staticmethod
    def scroll_to_latest_before_read_enabled() -> bool:
        return False

    def scroll_chat_to_latest(self, _hwnd: int) -> None:
        self.latest_restores += 1


def check_worker_locate_backsearch_restores_latest_without_copy() -> None:
    host = AnchorBacksearchHost()
    result = run_private_request(
        {
            "target": "Customer A",
            "session_key": "wx:vision-worker",
            "conversation_type": "private",
            "exact": True,
            "explicit_image_pending": False,
            "anchor_text_key": "现在想换这台",
            "anchor_message_id": "scheduler-anchor-id",
            "max_images": 3,
        },
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"backsearch visual locate failed: {result}")
    locate = result.get("locate") or {}
    assert_true(locate.get("scroll_steps") == 1, f"locate must scroll only until the first match: {locate}")
    assert_true(locate.get("snapshot_count") == 2, f"locate must capture current frame before history: {locate}")
    assert_true(locate.get("restored_to_latest") is True and host.latest_restores == 1, "locate must restore latest after scrolling")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "backsearch locate must not copy images")


def check_explicit_unanchored_single_image_only_uses_current_frame() -> None:
    host = BacksearchHost()
    result = run_private_request(
        {
            "target": "Customer A",
            "session_key": "wx:vision-worker",
            "conversation_type": "private",
            "exact": True,
            "explicit_image_pending": True,
            "max_images": 3,
        },
        host_ops=host,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"unanchored history image must not be guessed: {result}")
    assert_true(host.history_scrolls == 0 and host.latest_restores == 0, "explicit no-anchor current-frame miss must not scroll")


def _surface_with_customer_images(image_rows: list[tuple[int, int]]) -> Image.Image:
    surface = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(surface)
    split = session_split_x(980)
    draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
    for index, (top, bottom) in enumerate(image_rows):
        draw.rectangle([split + 42, top, split + 282, bottom], fill=(30 + index * 30, 120, 190))
    return surface


class AnchorBacksearchHost(FakeGenericWeChatHost):
    def __init__(self) -> None:
        super().__init__()
        self.surface_index = 0
        self.empty_surface = _surface_with_customer_images([])
        self.anchor_surface = _surface_with_customer_images([(250, 450)])
        self.validation_results = [True, True, True]
        self.restore_fails = False

    @staticmethod
    def scroll_to_latest_before_read_enabled() -> bool:
        return False

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        return (self.empty_surface if self.surface_index == 0 else self.anchor_surface), ""

    def parse_messages_from_ocr(self, _items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        if self.surface_index == 0:
            return []
        return [
            {
                "id": "ocr-drift-anchor",
                "message_id": "ocr-drift-anchor",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "现在想换这台",
                "bubble_rect": {"left": 410, "top": 500, "right": 720, "bottom": 550},
            }
        ]

    def scroll_chat_history(self, _hwnd: int, load_times: int) -> None:
        super().scroll_chat_history(_hwnd, load_times)
        self.surface_index = 1

    def scroll_chat_to_latest(self, _hwnd: int) -> None:
        self.latest_restores += 1
        if self.restore_fails:
            raise RuntimeError("restore failed")

    def validate_active_send_target_for_identity(
        self,
        _hwnd: int,
        target: str,
        *,
        exact: bool,
        artifact_dir: str | None,
        session_key: str,
        conversation_type: str,
    ) -> dict[str, Any]:
        assert_true(target == "Customer A" and exact and artifact_dir is None, "collector must validate exact target without artifacts")
        ok = self.validation_results.pop(0) if self.validation_results else True
        return {"ok": ok, "session_key": session_key, "conversation_type": conversation_type}


def check_collector_normal_anchor_backsearch_rebinds_ocr_id_and_restores() -> None:
    host = AnchorBacksearchHost()
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    assert_true(result.get("ok") is True, f"normal anchor backsearch failed: {result}")
    assert_true((result.get("locate") or {}).get("scroll_steps") == 1, "normal anchor locate must use bounded backsearch")
    messages = result.get("messages") or []
    assert_true(len(messages) == 1, f"normal anchor locate must return exactly one rebound structural image: {messages}")
    assert_true(messages[0].get("_vision_following_text_id") == "scheduler-anchor-id", "OCR-id drift must rebind to the scheduler body anchor id")
    assert_true(host.latest_restores == 1 and host.right_clicks == 0 and host.menu_clicks == 0, "locate must restore without copy")


class MultiImageHost(FakeGenericWeChatHost):
    def __init__(
        self,
        rows: list[tuple[int, int]],
        *,
        with_self_boundary: bool = False,
        fresh_rows: list[tuple[int, int]] | None = None,
        time_texts: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.surface = _surface_with_customer_images(rows)
        self.with_self_boundary = with_self_boundary
        self.fresh_surface = _surface_with_customer_images(fresh_rows) if fresh_rows else None
        self.capture_count = 0
        self.time_texts = list(time_texts or [])

    @staticmethod
    def scroll_to_latest_before_read_enabled() -> bool:
        return False

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        self.capture_count += 1
        if self.fresh_surface is not None and self.capture_count >= 2:
            self.surface = self.fresh_surface
        return self.surface, ""

    def run_ocr(self, image: Image.Image) -> list[dict[str, Any]]:
        if image is self.menu:
            return super().run_ocr(image)
        if self.time_texts:
            index = max(0, min(self.capture_count - 1, len(self.time_texts) - 1))
            return [
                {
                    "text": self.time_texts[index],
                    "center_x": 640,
                    "center_y": 180,
                    "top": 172,
                    "bottom": 188,
                    "confidence": 0.95,
                }
            ]
        return []

    def parse_messages_from_ocr(self, _items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        if not self.with_self_boundary:
            return []
        return [
            {
                "id": "self-boundary",
                "message_id": "self-boundary",
                "type": "text",
                "sender": "self",
                "sender_role": "self",
                "content": "上一轮回复",
                "bubble_rect": {"left": 710, "top": 110, "right": 920, "bottom": 150},
            }
        ]


def check_collector_rejects_explicit_two_images_without_turn_boundary() -> None:
    result = locate_current_turn_visual_group(
        sidecar_ops=MultiImageHost([(210, 340), (390, 520)]),
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"unbounded two-image turn must fail closed: {result}")


def check_collector_keeps_ordered_two_or_three_image_group_after_self_boundary() -> None:
    result = locate_current_turn_visual_group(
        sidecar_ops=MultiImageHost([(210, 320), (360, 470), (510, 620)], with_self_boundary=True),
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    messages = result.get("messages") or []
    assert_true(result.get("ok") is True and len(messages) == 3, f"same-turn three-image group must remain complete: {result}")
    assert_true("_vision_bounds" not in json.dumps(messages, ensure_ascii=False), "ordered group must not leak private geometry")


def check_collector_rejects_four_image_group_without_truncating() -> None:
    result = locate_current_turn_visual_group(
        sidecar_ops=MultiImageHost([(170, 260), (290, 380), (410, 500), (530, 620)], with_self_boundary=True),
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"four-image group must fail instead of truncating: {result}")


def check_collector_restore_failure_returns_no_messages() -> None:
    host = AnchorBacksearchHost()
    host.restore_fails = True
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_restore_failed", f"restore failure must fail closed: {result}")
    assert_true(result.get("messages") == [], "restore failure must return no messages")


def check_collector_no_match_after_scroll_still_reports_restore_success() -> None:
    host = AnchorBacksearchHost()
    host.anchor_surface = host.empty_surface
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_scroll_steps=1,
        max_snapshots=2,
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"no-match locate must fail closed: {result}")
    assert_true((result.get("locate") or {}).get("restored_to_latest") is True, "no-match after scroll must still record successful restore")


def check_normal_locate_short_cap_is_enforced() -> None:
    host = AnchorBacksearchHost()
    host.anchor_surface = host.empty_surface
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_scroll_steps=2,
        max_snapshots=3,
        max_seconds=6.0,
        max_images=3,
    )
    locate = result.get("locate") or {}
    assert_true(result.get("ok") is False and result.get("messages") == [], f"short capped no-match must fail closed: {result}")
    assert_true(locate.get("scroll_steps") == 2 and locate.get("snapshot_count") == 3, f"normal short cap must stop at 2/3: {locate}")


def check_explicit_locate_default_cap_allows_more_than_normal_short_cap() -> None:
    host = AnchorBacksearchHost()
    host.empty_surface = _surface_with_customer_images([])
    host.anchor_surface = host.empty_surface
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    locate = result.get("locate") or {}
    assert_true(result.get("ok") is False, f"explicit no-match must fail closed: {result}")
    assert_true(
        locate.get("scroll_steps") == 6
        and 3 < int(locate.get("snapshot_count") or 0) <= 8,
        f"explicit default cap must remain broader than the normal 2/3 short cap: {locate}",
    )


def check_collector_target_change_during_backsearch_returns_no_messages() -> None:
    host = AnchorBacksearchHost()
    host.validation_results = [True, False]
    result = locate_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"target drift must fail before returning candidates: {result}")
    assert_true(host.latest_restores == 0, "target drift after scroll must not restore the wrong conversation")


def _assert_private_payloads(result: dict[str, Any], expected_count: int) -> list[dict[str, Any]]:
    payloads = result.get("_private_image_payloads") or []
    assert_true(result.get("ok") is True, f"acquire must succeed: {result}")
    assert_true(len(payloads) == expected_count, f"acquire must return {expected_count} private payloads: {result}")
    for payload in payloads:
        assert_true(str(payload.get("data") or ""), "private worker payload must carry encoded image data")
        assert_true(str(payload.get("mime_type") or "") == "image/png", "private payload must be png")
    return payloads


def check_private_worker_acquires_current_single_image_fast_path() -> None:
    host = FakeGenericWeChatHost()
    result = run_private_request(
        {
            "mode": "acquire",
            "target": "Customer A",
            "session_key": "wx:vision-worker",
            "conversation_type": "private",
            "exact": True,
            "explicit_image_pending": True,
            "max_images": 3,
        },
        host_ops=host,
    )
    _assert_private_payloads(result, 1)
    locate = result.get("locate") or {}
    assert_true(locate.get("scroll_steps") == 0 and locate.get("snapshot_count") == 1, f"single-image fast path must use one selected frame: {locate}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "single-image acquire must right-click/menu exactly once")
    assert_true(host.latest_restores == 0, "current-frame fast path must not restore")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert_true(
        "_vision_occurrence_ordinal" not in serialized
        and "_vision_transaction_ordinal" not in serialized,
        "acquire result must not leak transaction-local ordinal fields",
    )


def check_collector_acquires_three_image_group_in_chat_order() -> None:
    host = MultiImageHost(
        [(210, 320), (360, 470), (510, 620)],
        with_self_boundary=True,
        fresh_rows=[(218, 330), (372, 486), (526, 642)],
        time_texts=["10:01", "10:02"],
    )
    original_match = visual_collector.match_visual_occurrence_groups
    matched_ids: list[tuple[list[str], list[str]]] = []

    def wrapped_match(known: list[dict[str, Any]], current: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
        matched_ids.append(
            (
                [str(item.get("structural_message_id") or "") for item in known],
                [str(item.get("structural_message_id") or "") for item in current],
            )
        )
        return original_match(known, current, **kwargs)

    visual_collector.match_visual_occurrence_groups = wrapped_match
    try:
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
    finally:
        visual_collector.match_visual_occurrence_groups = original_match
    _assert_private_payloads(result, 3)
    locate = result.get("locate") or {}
    assert_true(locate.get("scroll_steps") == 0 and locate.get("snapshot_count") == 2, f"multi-image group must use one fresh reanchor: {locate}")
    assert_true(host.right_clicks == 3 and host.menu_clicks == 3, "three-image group must copy each image exactly once")
    assert_true(host.capture_count == 2, "three-image acquire must prove the jittered fresh frame still matches")
    assert_true(
        any(known != current for known, current in matched_ids),
        f"fresh reanchor test must include structural id/time jitter: {matched_ids}",
    )


def check_collector_acquires_backsearched_image_then_restores() -> None:
    host = AnchorBacksearchHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    _assert_private_payloads(result, 1)
    locate = result.get("locate") or {}
    assert_true(locate.get("scroll_steps") == 1 and locate.get("snapshot_count") == 3, f"backsearch acquire must reanchor once: {locate}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1 and host.latest_restores == 1, "backsearch acquire must copy once and restore")


class FreshMismatchHost(MultiImageHost):
    def __init__(self) -> None:
        super().__init__([(210, 320), (360, 470)], with_self_boundary=True)
        self.capture_count = 0

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        self.capture_count += 1
        if self.capture_count >= 2:
            return _surface_with_customer_images([(210, 320), (360, 470), (510, 620)]), ""
        return self.surface, ""


def check_fresh_reanchor_group_change_fails_before_click() -> None:
    host = FreshMismatchHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"fresh group change must fail closed: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "fresh mismatch must fail before physical copy")


class ClipboardFailureHost(FakeGenericWeChatHost):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode
        self.mismatches = 0

    def clipboard_sequence_number(self) -> int:
        if self.mode == "unchanged":
            self.copy_pending = False
            return self.sequence
        return super().clipboard_sequence_number()

    def read_current_bitmap(self) -> Any:
        if self.mode == "nonbitmap":
            return "not-an-image"
        if self.mode in {"mismatch_once", "mismatch_always"}:
            if self.mode == "mismatch_once" and self.mismatches >= 1:
                return super().read_current_bitmap()
            self.mismatches += 1
            return Image.new("RGB", (60, 180), (255, 255, 255))
        return super().read_current_bitmap()


def check_clipboard_failures_return_no_private_payloads() -> None:
    for mode, reason in (
        ("unchanged", "clipboard_sequence_unchanged_after_copy"),
        ("nonbitmap", "clipboard_current_content_not_bitmap"),
        ("mismatch_always", "clipboard_image_fingerprint_mismatch"),
    ):
        host = ClipboardFailureHost(mode)
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
        assert_true(result.get("ok") is False and result.get("reason") == reason, f"{mode} must fail closed: {result}")
        assert_true(not result.get("_private_image_payloads"), f"{mode} must not return partial payloads")
        assert_true(host.cleared_sequences == [], f"{mode} must not clear an unconfirmed clipboard generation")


def check_fingerprint_mismatch_retries_same_occurrence_once() -> None:
    host = ClipboardFailureHost("mismatch_once")
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    _assert_private_payloads(result, 1)
    assert_true((result.get("locate") or {}).get("snapshot_count") == 2, f"explicit single-image mismatch retry must use exactly one fresh snapshot: {result}")
    assert_true(host.right_clicks == 2 and host.menu_clicks == 2, "fingerprint mismatch may retry the same occurrence once")
    assert_true(len(host.cleared_sequences) == 1, "only the confirmed retry generation may be cleared")


class SecondImageFailureHost(MultiImageHost):
    def __init__(self) -> None:
        super().__init__([(210, 320), (360, 470)], with_self_boundary=True)

    def read_current_bitmap(self) -> Any:
        if self.menu_clicks >= 2:
            return "not-an-image"
        return super().read_current_bitmap()


def check_second_image_failure_returns_zero_payloads() -> None:
    host = SecondImageFailureHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    assert_true(result.get("ok") is False, f"second image failure must fail whole group: {result}")
    assert_true(not result.get("_private_image_payloads"), "partial group payloads must not be committed")


def check_acquire_restore_failure_drops_copied_payloads() -> None:
    host = AnchorBacksearchHost()
    host.restore_fails = True
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_restore_failed", f"restore failure must fail after acquire: {result}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "test must cover copy before restore failure")
    assert_true(not result.get("_private_image_payloads") and not result.get("transaction"), "restore failure must not commit copied payloads")


def check_wire_payload_limits_fail_without_partial_result() -> None:
    original_wire = visual_collector.MAX_GROUP_WIRE_BYTES
    original_single = visual_collector.MAX_IMAGE_PAYLOAD_BYTES
    try:
        visual_collector.MAX_GROUP_WIRE_BYTES = 16
        result = acquire_current_turn_visual_group(
            sidecar_ops=FakeGenericWeChatHost(),
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
        assert_true(result.get("ok") is False and result.get("reason") == "visual_group_wire_payload_too_large", f"wire limit must fail closed: {result}")
        assert_true(not result.get("_private_image_payloads"), "wire limit must not return private payloads")

        visual_collector.MAX_GROUP_WIRE_BYTES = original_wire
        visual_collector.MAX_IMAGE_PAYLOAD_BYTES = 10
        result = acquire_current_turn_visual_group(
            sidecar_ops=FakeGenericWeChatHost(),
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
        assert_true(result.get("ok") is False and result.get("reason") == "clipboard_current_image_invalid", f"single payload limit must fail closed: {result}")
        assert_true(not result.get("_private_image_payloads"), "single payload limit must not return private payloads")
    finally:
        visual_collector.MAX_GROUP_WIRE_BYTES = original_wire
        visual_collector.MAX_IMAGE_PAYLOAD_BYTES = original_single


def _controlled_frame(occurrences: list[dict[str, Any]], *, size: tuple[int, int] = (980, 860)) -> dict[str, Any]:
    screenshot = Image.new("RGB", size, (247, 247, 247))
    messages: list[dict[str, Any]] = []
    for index, occurrence in enumerate(occurrences):
        bounds = occurrence.get("bounds") or [420, 160 + index * 140, 660, 280 + index * 140]
        message_id = str(occurrence.get("structural_message_id") or occurrence.get("message_id") or f"img-{index}")
        item = {
            "message_id": message_id,
            "id": message_id,
            "visual_side": "customer",
            "_vision_bounds": list(bounds),
        }
        messages.append(item)
    return {
        "ok": True,
        "state": "vision_visual_group_selected",
        "reason": "visual_group_selected",
        "messages": [dict(item) for item in messages],
        "_private_messages": [dict(item) for item in messages],
        "_occurrences": [dict(item) for item in occurrences],
        "_screenshot": screenshot,
    }


def check_fresh_reanchor_uses_global_matcher_for_ambiguous_keys() -> None:
    request_scope = {
        "session_key": "wx:vision-worker",
        "target_identity": "Customer A",
        "conversation_type": "private",
        "side": "customer",
    }
    first_occurrences = [
        {
            **request_scope,
            "session_key": "wx:vision-worker",
            "target_identity": "Customer A",
            "conversation_type": "private",
            "structural_message_id": "image-a",
            "visual_structural_key": "struct-x",
            "visual_stable_key": "stable-y",
            "bounds": [420, 200, 660, 320],
        },
        {
            **request_scope,
            "session_key": "wx:vision-worker",
            "target_identity": "Customer A",
            "conversation_type": "private",
            "structural_message_id": "image-b",
            "visual_structural_key": "struct-z",
            "source_message_id": "source-s",
            "bounds": [420, 360, 660, 480],
        },
    ]
    ambiguous_fresh_occurrences = [
        {
            **request_scope,
            "structural_message_id": "fresh-1",
            "visual_structural_key": "struct-x",
            "source_message_id": "source-s",
            "bounds": [420, 200, 660, 320],
        },
        {
            **request_scope,
            "structural_message_id": "fresh-2",
            "visual_structural_key": "struct-z",
            "visual_stable_key": "stable-y",
            "bounds": [420, 360, 660, 480],
        },
    ]
    frames = [_controlled_frame(first_occurrences), _controlled_frame(ambiguous_fresh_occurrences)]
    original_capture = visual_collector._capture_visual_group_frame
    host = FakeGenericWeChatHost()

    def fake_capture(**_kwargs: Any) -> dict[str, Any]:
        return frames.pop(0)

    visual_collector._capture_visual_group_frame = fake_capture
    try:
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
    finally:
        visual_collector._capture_visual_group_frame = original_capture
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_reanchor_mismatch", f"ambiguous global reanchor must fail: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "ambiguous fresh match must fail before physical copy")


class NormalCurrentImageHost(FakeGenericWeChatHost):
    def parse_messages_from_ocr(self, _items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        return [
            {
                "id": "normal-anchor",
                "message_id": "normal-anchor",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "现在想换这台",
                "bubble_rect": {"left": 410, "top": 690, "right": 720, "bottom": 740},
            }
        ]


class NormalFreshDisappearsHost(NormalCurrentImageHost):
    def __init__(self) -> None:
        super().__init__()
        self.capture_count = 0

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        self.capture_count += 1
        if self.capture_count >= 2:
            return _surface_with_customer_images([]), ""
        return self.surface, ""


def check_normal_current_single_image_requires_fresh_reanchor() -> None:
    host = NormalCurrentImageHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="normal-anchor",
        max_images=3,
    )
    _assert_private_payloads(result, 1)
    locate = result.get("locate") or {}
    assert_true(locate.get("snapshot_count") == 2 and locate.get("scroll_steps") == 0, f"normal current single image must fresh-reanchor before click: {locate}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "normal current single image should copy only after fresh reanchor")


def check_normal_current_single_image_fresh_change_fails_before_click() -> None:
    host = NormalFreshDisappearsHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="normal-anchor",
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("messages") == [], f"normal fresh disappearance must fail closed: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "normal fresh mismatch must fail before physical copy")


class BacksearchMismatchHost(AnchorBacksearchHost):
    def read_current_bitmap(self) -> Any:
        return Image.new("RGB", (60, 180), (255, 255, 255))


def check_mismatch_retry_respects_normal_snapshot_budget() -> None:
    host = BacksearchMismatchHost()
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=False,
        anchor_text_key="现在想换这台",
        anchor_message_id="scheduler-anchor-id",
        max_scroll_steps=2,
        max_snapshots=3,
        max_seconds=6.0,
        max_images=3,
    )
    locate = result.get("locate") or {}
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_snapshot_budget_exhausted", f"normal mismatch retry must stop at snapshot budget: {result}")
    assert_true(locate.get("snapshot_count") == 3, f"normal mismatch retry must not take a fourth screenshot: {locate}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "normal mismatch may try the original copy once only")


def check_acquire_elapsed_budget_blocks_click() -> None:
    original_now = visual_collector._now
    host = FakeGenericWeChatHost()
    times = iter([0.0, 0.0, 10.0])

    def fake_now() -> float:
        return next(times, 10.0)

    visual_collector._now = fake_now
    try:
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_seconds=1.0,
            max_images=3,
        )
    finally:
        visual_collector._now = original_now
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_time_budget_exhausted", f"elapsed budget must stop before right-click: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "elapsed budget must not allow physical copy")


def check_menu_elapsed_budget_blocks_menu_click_after_right_click() -> None:
    original_now = visual_collector._now
    host = FakeGenericWeChatHost()
    times = iter([0.0, 0.0, 0.0, 2.0])

    def fake_now() -> float:
        return next(times, 2.0)

    visual_collector._now = fake_now
    try:
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_seconds=1.0,
            max_images=3,
        )
    finally:
        visual_collector._now = original_now
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_time_budget_exhausted", f"menu elapsed budget must fail: {result}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 0, "timeout after menu OCR must not click the menu")


class ActionValidationHost(FakeGenericWeChatHost):
    def __init__(self, validation_results: list[bool]) -> None:
        super().__init__()
        self.validation_results = list(validation_results)

    def validate_active_send_target_for_identity(
        self,
        _hwnd: int,
        target: str,
        *,
        exact: bool,
        artifact_dir: str | None,
        session_key: str,
        conversation_type: str,
    ) -> dict[str, Any]:
        assert_true(target == "Customer A" and exact and artifact_dir is None, "acquire must validate exact target without artifacts")
        ok = self.validation_results.pop(0) if self.validation_results else True
        return {"ok": ok, "session_key": session_key, "conversation_type": conversation_type}


def check_target_drift_after_right_click_blocks_menu_click() -> None:
    host = ActionValidationHost([True, True, False])
    result = acquire_current_turn_visual_group(
        sidecar_ops=host,
        hwnd=100,
        target_name="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        explicit_image_pending=True,
        max_images=3,
    )
    assert_true(result.get("ok") is False and result.get("reason") == "vision_target_changed_during_visual_group_locate", f"menu pre-click target drift must fail: {result}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 0, "target drift after menu OCR must not click the menu")


def check_missing_crop_fingerprint_fails_before_right_click() -> None:
    original_crop = visual_collector._crop_fingerprint
    host = FakeGenericWeChatHost()
    visual_collector._crop_fingerprint = lambda *_args, **_kwargs: {}
    try:
        result = acquire_current_turn_visual_group(
            sidecar_ops=host,
            hwnd=100,
            target_name="Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
    finally:
        visual_collector._crop_fingerprint = original_crop
    assert_true(result.get("ok") is False and result.get("reason") == "visual_group_candidate_fingerprint_missing", f"missing crop fingerprint must fail: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "missing crop fingerprint must fail before right-click")


def check_clipboard_fingerprint_distinguishes_same_size_red_and_blue() -> None:
    red = Image.new("RGB", (160, 120), (255, 0, 0))
    blue = Image.new("RGB", (160, 120), (0, 0, 255))
    assert_true(
        not visual_collector._fingerprint_matches(
            visual_collector._image_fingerprint(red),
            visual_collector._image_fingerprint(blue),
        ),
        "same-size red and blue images must not pass clipboard fingerprint",
    )


def check_clipboard_fingerprint_allows_scaled_lightly_compressed_same_image() -> None:
    base = Image.new("RGB", (160, 120), (20, 120, 210))
    draw = ImageDraw.Draw(base)
    draw.rectangle([35, 25, 120, 95], fill=(230, 180, 40))
    buffer = io.BytesIO()
    base.resize((320, 240), Image.Resampling.LANCZOS).save(buffer, format="JPEG", quality=82)
    buffer.seek(0)
    with Image.open(buffer) as compressed:
        compressed.load()
        assert_true(
            visual_collector._fingerprint_matches(
                visual_collector._image_fingerprint(base),
                visual_collector._image_fingerprint(compressed),
            ),
            "scaled/lightly compressed same image should remain a clipboard fingerprint match",
        )


def check_clipboard_fingerprint_rejects_same_center_different_perimeter() -> None:
    first = Image.new("RGB", (240, 180), (220, 30, 30))
    second = Image.new("RGB", (240, 180), (30, 30, 220))
    for image in (first, second):
        ImageDraw.Draw(image).rectangle([54, 40, 186, 140], fill=(230, 230, 230))
    assert_true(
        not visual_collector._fingerprint_matches(
            visual_collector._image_fingerprint(first),
            visual_collector._image_fingerprint(second),
        ),
        "matching center content must not hide different image perimeters",
    )


def check_parent_facade_decodes_and_strips_private_wire_payload() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), (40, 90, 160)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    calls: list[dict[str, Any]] = []
    original_runner = wechat_current._run_private_group_worker
    previous_lock_disabled = os.environ.get("WECHAT_RPA_LOCK_DISABLED")

    def runner(_connector: Any, request: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(request))
        return {
            "ok": True,
            "state": "vision_visual_group_acquired",
            "messages": [],
            "transaction": {"status": "clipboard_read", "image_count": 1},
            "_private_image_payloads": [
                {"mime_type": "image/png", "width": 32, "height": 24, "data": encoded}
            ],
        }

    wechat_current._run_private_group_worker = runner
    os.environ["WECHAT_RPA_LOCK_DISABLED"] = "1"
    try:
        result = wechat_current._acquire_current_visual_group(
            SimpleNamespace(timeout_seconds=5),
            "Customer A",
            session_key="wx:vision-worker",
            conversation_type="private",
            explicit_image_pending=True,
            max_images=3,
        )
    finally:
        wechat_current._run_private_group_worker = original_runner
        if previous_lock_disabled is None:
            os.environ.pop("WECHAT_RPA_LOCK_DISABLED", None)
        else:
            os.environ["WECHAT_RPA_LOCK_DISABLED"] = previous_lock_disabled
    images = result.get("_ephemeral_clipboard_images") or []
    assert_true(calls and calls[0].get("mode") == "acquire", f"parent facade must call private acquire worker: {calls}")
    assert_true(len(images) == 1 and isinstance(images[0], EphemeralClipboardImage), f"parent facade must decode private wire payload: {result}")
    assert_true("_private_image_payloads" not in result, "parent facade must strip base64 wire payload")
    images[0].release()


def check_parent_facade_rejects_empty_or_oversized_private_payload_list() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (24, 24), (80, 120, 160)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    for payloads in ([], [{"mime_type": "image/png", "width": 24, "height": 24, "data": encoded} for _ in range(4)]):
        result = wechat_current._decode_private_image_payloads(
            {
                "ok": True,
                "state": "vision_visual_group_acquired",
                "messages": [],
                "_private_image_payloads": payloads,
            }
        )
        assert_true(result.get("ok") is False and not result.get("_ephemeral_clipboard_images"), f"invalid private payload count must fail closed: {result}")


def main() -> int:
    checks = [
        check_worker_observes_both_directions_without_artifacts,
        check_worker_copies_current_customer_image_without_sidecar_action,
        check_common_menu_observer_is_preferred_over_legacy_capture,
        check_production_integration_calls_vision_worker_not_sidecar_action,
        check_worker_locates_current_customer_visual_group_without_copy,
        check_public_observe_current_surface_keeps_single_frame_semantics,
        check_worker_locate_backsearch_restores_latest_without_copy,
        check_explicit_unanchored_single_image_only_uses_current_frame,
        check_collector_normal_anchor_backsearch_rebinds_ocr_id_and_restores,
        check_collector_rejects_explicit_two_images_without_turn_boundary,
        check_collector_keeps_ordered_two_or_three_image_group_after_self_boundary,
        check_collector_rejects_four_image_group_without_truncating,
        check_collector_restore_failure_returns_no_messages,
        check_collector_no_match_after_scroll_still_reports_restore_success,
        check_normal_locate_short_cap_is_enforced,
        check_explicit_locate_default_cap_allows_more_than_normal_short_cap,
        check_collector_target_change_during_backsearch_returns_no_messages,
        check_private_worker_acquires_current_single_image_fast_path,
        check_collector_acquires_three_image_group_in_chat_order,
        check_collector_acquires_backsearched_image_then_restores,
        check_fresh_reanchor_group_change_fails_before_click,
        check_clipboard_failures_return_no_private_payloads,
        check_fingerprint_mismatch_retries_same_occurrence_once,
        check_second_image_failure_returns_zero_payloads,
        check_acquire_restore_failure_drops_copied_payloads,
        check_wire_payload_limits_fail_without_partial_result,
        check_fresh_reanchor_uses_global_matcher_for_ambiguous_keys,
        check_normal_current_single_image_requires_fresh_reanchor,
        check_normal_current_single_image_fresh_change_fails_before_click,
        check_mismatch_retry_respects_normal_snapshot_budget,
        check_acquire_elapsed_budget_blocks_click,
        check_menu_elapsed_budget_blocks_menu_click_after_right_click,
        check_target_drift_after_right_click_blocks_menu_click,
        check_missing_crop_fingerprint_fails_before_right_click,
        check_clipboard_fingerprint_distinguishes_same_size_red_and_blue,
        check_clipboard_fingerprint_allows_scaled_lightly_compressed_same_image,
        check_clipboard_fingerprint_rejects_same_center_different_perimeter,
        check_parent_facade_decodes_and_strips_private_wire_payload,
        check_parent_facade_rejects_empty_or_oversized_private_payload_list,
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
