from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
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
from apps.wechat_ai_customer_service.optional_plugins.vision.capture import wechat as vision_wechat_capture  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.occurrence_store import VisualOccurrenceStore  # noqa: E402
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import session_split_x  # noqa: E402


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


class _ListLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(self.format(record))


def _install_vision_capture_log_probe() -> tuple[logging.Logger, _ListLogHandler, int]:
    logger = logging.getLogger(vision_wechat_capture.__name__)
    handler = _ListLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    return logger, handler, previous_level


def _assert_internal_log_is_private(messages: list[str]) -> None:
    serialized = "\n".join(messages).lower()
    for token in ("bounds", "cache", "claim", "visual_anchor", "visual_stable", "visual_structural"):
        assert_true(token not in serialized, f"internal vision audit log leaked private field {token}: {messages}")


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
    def scroll_chat_to_latest(_hwnd: int, *, attempts: int = 16) -> None:
        del attempts
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


def _args(
    operation: str,
    *,
    side_filter: str = "all",
    pending_signal_id: str = "pending-image-1",
    pending_observation_id: str = "",
    source_preview: str = "[图片]",
) -> argparse.Namespace:
    return argparse.Namespace(
        operation=operation,
        target="Customer A",
        session_key="wx:vision-worker",
        conversation_type="private",
        exact=True,
        source_preview=source_preview,
        speaker_name="",
        pending_signal_id=pending_signal_id,
        pending_observation_id=pending_observation_id,
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
        _args("copy-current-image", side_filter="customer", pending_signal_id="", pending_observation_id=""),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"clipboard transaction failed: {result}")
    transaction = result.get("transaction") or {}
    assert_true(transaction.get("clipboard_sequence_after") == 42, "copy must prove a new clipboard generation")
    assert_true(transaction.get("visual_side") == "customer", "copy must preserve direction proof")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "copy must use one bounded right-click and one Copy click")
    assert_true(host.capture_artifact_dirs == [None, None], "copy transaction must not persist screenshots")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    for token in ("visual_anchor", "visual_stable", "visual_structural", "cache", "screenshot_path"):
        assert_true(token not in serialized, f"copy response leaked private vision field {token}: {result}")


def _visual_message_id(target: str, side: str, occurrence_index: int, observed_time: str = "") -> str:
    identity_seed = json.dumps(
        {
            "target": target,
            "side": side,
            "time": observed_time,
            "occurrence_index": occurrence_index,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:20]
    return f"visual_{side}_context_{digest}"


class PendingBacksearchFakeHost(FakeGenericWeChatHost):
    def __init__(self) -> None:
        super().__init__()
        self.latest_surface = Image.new("RGB", (980, 860), (247, 247, 247))
        latest_draw = ImageDraw.Draw(self.latest_surface)
        split = session_split_x(980)
        latest_draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
        latest_draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
        self.history_surface = self.latest_surface.copy()
        history_draw = ImageDraw.Draw(self.history_surface)
        history_draw.rectangle([split + 42, 250, split + 282, 470], fill=(30, 120, 190))
        self.surface = self.latest_surface
        self.page = "latest"
        self.scroll_ops: list[str] = []

    def scroll_chat_to_latest(self, _hwnd: int, *, attempts: int = 16) -> None:
        del attempts
        self.page = "latest"
        self.scroll_ops.append("latest")

    def scroll_chat_history(self, _hwnd: int, load_times: int, *, wheel_units: int = 8, delay_seconds: float = 0.18) -> None:
        del load_times, wheel_units, delay_seconds
        self.page = "history"
        self.scroll_ops.append("history")

    def capture_wechat(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        return (self.history_surface if self.page == "history" else self.latest_surface), ""

    def parse_messages_from_ocr(self, _items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        del target
        if self.page != "history":
            return [
                {
                    "id": "text-after-image",
                    "message_id": "text-after-image",
                    "type": "text",
                    "content": "这是什么车？",
                    "bubble_rect": {"left": 410, "top": 510, "right": 650, "bottom": 550},
                }
            ]
        return [
            {
                "id": "text-after-image",
                "message_id": "text-after-image",
                "type": "text",
                "content": "这是什么车？",
                "bubble_rect": {"left": 410, "top": 510, "right": 650, "bottom": 550},
            }
        ]


def check_worker_pending_observe_records_private_store_without_public_leak() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        previous = os.environ.get("WECHAT_VISION_OCCURRENCE_STORE_DIR")
        os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = tmp
        try:
            host = PendingBacksearchFakeHost()
            host.latest_surface = host.history_surface
            result = run_operation(
                _args(
                    "observe-current-surface",
                    side_filter="all",
                    pending_signal_id="pending-image-1",
                    pending_observation_id="observation-1",
                    source_preview="这是什么车？",
                ),
                host_ops=host,
            )
            assert_true(result.get("ok") is True, f"pending surface observation failed: {result}")
            serialized = json.dumps(result, ensure_ascii=False).lower()
            for token in ("visual_anchor", "visual_stable", "visual_structural", "bounds", "cache", "claim_id"):
                assert_true(token not in serialized, f"surface observation leaked private field {token}: {result}")
            store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
            claimed = store.claim_best_match(
                {
                    "session_key": "wx:vision-worker",
                    "target_identity": "Customer A",
                    "conversation_type": "private",
                    "pending_signal_id": "pending-image-1",
                    "pending_observation_id": "observation-1",
                    "side_filter": "customer",
                    "source_preview": "这是什么车？",
                }
            )
            assert_true(claimed.get("ok") is True, f"private store should hold a claimable bound occurrence: {claimed}")
        finally:
            if previous is None:
                os.environ.pop("WECHAT_VISION_OCCURRENCE_STORE_DIR", None)
            else:
                os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = previous


def check_worker_pending_copy_uses_bounded_backsearch_and_restores_latest() -> None:
    host = PendingBacksearchFakeHost()
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="pending-image-1",
            pending_observation_id="observation-1",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"pending backsearch copy failed: {result}")
    assert_true("history" in host.scroll_ops, f"bounded backsearch should scroll history: {host.scroll_ops}")
    assert_true(host.scroll_ops and host.scroll_ops[-1] == "latest", f"copy must restore latest after backsearch: {host.scroll_ops}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 1, "backsearch copy should operate on the recovered image once")


def check_worker_signal_only_pending_copy_keeps_legacy_latest_visible_behavior() -> None:
    host = PendingBacksearchFakeHost()
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="pending-image-1",
            pending_observation_id="",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is False, f"signal-only path should keep legacy current-visible behavior: {result}")
    assert_true(result.get("reason") == "customer_image_target_not_found", f"signal-only legacy path should not backsearch: {result}")
    assert_true("history" not in host.scroll_ops, f"signal-only legacy path must not scroll history: {host.scroll_ops}")


def check_worker_observation_only_pending_copy_uses_bounded_backsearch() -> None:
    host = PendingBacksearchFakeHost()
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="",
            pending_observation_id="observation-1",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is True, f"observation-only pending copy should be pending-aware: {result}")
    assert_true("history" in host.scroll_ops, f"observation-only pending copy must backsearch: {host.scroll_ops}")
    assert_true(host.scroll_ops and host.scroll_ops[-1] == "latest", f"observation-only copy must restore latest: {host.scroll_ops}")


def check_worker_without_pending_keeps_legacy_latest_visible_behavior() -> None:
    host = PendingBacksearchFakeHost()
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="",
            pending_observation_id="",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is False, f"no-pending path should not backsearch into history: {result}")
    assert_true(result.get("reason") == "customer_image_target_not_found", f"no-pending path should keep current-visible failure: {result}")
    assert_true("history" not in host.scroll_ops, f"no-pending legacy path must not scroll history: {host.scroll_ops}")


def check_worker_pending_backsearch_screenshot_budget_fails_closed_and_restores_latest() -> None:
    host = PendingBacksearchFakeHost()
    host.history_surface = host.latest_surface
    original = vision_wechat_capture.VISION_PENDING_MAX_BACKSEARCH_SCREENSHOTS
    vision_wechat_capture.VISION_PENDING_MAX_BACKSEARCH_SCREENSHOTS = 2
    try:
        result = run_operation(
            _args(
                "copy-current-image",
                side_filter="customer",
                pending_signal_id="pending-image-1",
                pending_observation_id="observation-1",
                source_preview="这是什么车？",
            ),
            host_ops=host,
        )
    finally:
        vision_wechat_capture.VISION_PENDING_MAX_BACKSEARCH_SCREENSHOTS = original
    assert_true(result.get("ok") is False, f"budget exhaustion should fail closed: {result}")
    assert_true(result.get("reason") == "vision_image_backsearch_budget_exhausted", f"unexpected budget reason: {result}")
    assert_true(host.scroll_ops and host.scroll_ops[-1] == "latest", f"budget failure must restore latest: {host.scroll_ops}")


class MenuFailureRetryFakeHost(FakeGenericWeChatHost):
    def __init__(self) -> None:
        super().__init__()
        self.menu_missing = self.surface.copy()
        split = session_split_x(980)
        self.surface = Image.new("RGB", (980, 860), (247, 247, 247))
        draw = ImageDraw.Draw(self.surface)
        draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
        draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
        draw.rectangle([split + 42, 170, split + 282, 330], fill=(30, 120, 190))
        draw.rectangle([split + 42, 420, split + 282, 620], fill=(40, 140, 80))
        self.menu_captures = 0

    def parse_messages_from_ocr(self, _items: list[dict[str, Any]], _size: tuple[int, int], *, target: str) -> list[dict[str, Any]]:
        del target
        return [
            {
                "id": "text-after-image",
                "message_id": "text-after-image",
                "type": "text",
                "content": "这是什么车？",
                "bubble_rect": {"left": 410, "top": 675, "right": 650, "bottom": 715},
            }
        ]

    def capture_wechat_window_visible_screen(self, _hwnd: int, *, artifact_dir: str | None, label: str) -> tuple[Image.Image, str]:
        self.capture_artifact_dirs.append(artifact_dir)
        self.menu_captures += 1
        return (self.menu_missing if self.menu_captures == 1 else self.menu), ""

    def run_ocr(self, image: Image.Image) -> list[dict[str, Any]]:
        if image is self.menu_missing:
            return []
        return super().run_ocr(image)


def check_worker_menu_failure_excludes_candidate_and_retries_next() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        previous = os.environ.get("WECHAT_VISION_OCCURRENCE_STORE_DIR")
        os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = tmp
        try:
            store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
            store.record_occurrences(
                [
                    {
                        "session_key": "wx:vision-worker",
                        "target_identity": "Customer A",
                        "conversation_type": "private",
                        "pending_signal_id": "pending-image-1",
                        "pending_observation_id": "observation-1",
                        "side": "customer",
                        "structural_message_id": _visual_message_id("Customer A", "customer", 0),
                        "following_text_id": "text-after-image",
                        "following_text": "这是什么车？",
                        "bounds": [410, 170, 650, 330],
                    }
                ],
                {},
            )
            host = MenuFailureRetryFakeHost()
            host.generations = [41, 42, 43]
            result = run_operation(
                _args(
                    "copy-current-image",
                    side_filter="customer",
                    pending_signal_id="pending-image-1",
                    pending_observation_id="observation-1",
                    source_preview="这是什么车？",
                ),
                host_ops=host,
            )
            assert_true(result.get("ok") is True, f"copy should retry after menu failure: {result}")
            assert_true(host.right_clicks == 2 and host.menu_clicks == 1, "first menu failure should exclude candidate and retry next")
        finally:
            if previous is None:
                os.environ.pop("WECHAT_VISION_OCCURRENCE_STORE_DIR", None)
            else:
                os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = previous


class RestoreFailureFakeHost(PendingBacksearchFakeHost):
    def scroll_chat_to_latest(self, _hwnd: int, *, attempts: int = 16) -> None:
        del attempts
        if "history" in self.scroll_ops:
            self.scroll_ops.append("latest_failed")
            raise RuntimeError("restore latest failed")
        super().scroll_chat_to_latest(_hwnd)


def _stored_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def check_worker_restore_failure_releases_claim_and_fails_closed_without_public_leak() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        previous = os.environ.get("WECHAT_VISION_OCCURRENCE_STORE_DIR")
        os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = tmp
        try:
            store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
            store.record_occurrences(
                [
                    {
                        "session_key": "wx:vision-worker",
                        "target_identity": "Customer A",
                        "conversation_type": "private",
                        "pending_signal_id": "pending-image-1",
                        "pending_observation_id": "observation-1",
                        "side": "customer",
                        "structural_message_id": _visual_message_id("Customer A", "customer", 0),
                        "following_text_id": "text-after-image",
                        "following_text": "这是什么车？",
                        "bounds": [410, 250, 650, 470],
                    }
                ],
                {},
            )
            host = RestoreFailureFakeHost()
            logger, handler, previous_level = _install_vision_capture_log_probe()
            try:
                result = run_operation(
                    _args(
                        "copy-current-image",
                        side_filter="customer",
                        pending_signal_id="pending-image-1",
                        pending_observation_id="observation-1",
                        source_preview="这是什么车？",
                    ),
                    host_ops=host,
                )
            finally:
                logger.removeHandler(handler)
                logger.setLevel(previous_level)
            assert_true(result.get("ok") is False, f"restore failure should fail closed: {result}")
            assert_true(result.get("reason") == "image_clipboard_copy_failed", f"restore failure should use generic public reason: {result}")
            serialized = json.dumps(result, ensure_ascii=False).lower()
            assert_true("restore" not in serialized and "claim" not in serialized and "bounds" not in serialized, f"restore failure leaked internals: {result}")
            assert_true(
                any("vision_pending_backsearch_restore_failed" in message for message in handler.messages),
                f"restore failure should leave internal audit log: {handler.messages}",
            )
            _assert_internal_log_is_private(handler.messages)
            records = _stored_records(root)
            assert_true(records and not bool(records[0].get("consumed")), f"restore failure must not consume claim: {records}")
            assert_true(not list(root.glob("*.claim")), "restore failure should release active claim")
        finally:
            if previous is None:
                os.environ.pop("WECHAT_VISION_OCCURRENCE_STORE_DIR", None)
            else:
                os.environ["WECHAT_VISION_OCCURRENCE_STORE_DIR"] = previous


class PostRestoreTargetChangeFakeHost(PendingBacksearchFakeHost):
    def __init__(self) -> None:
        super().__init__()
        self.restored_after_history = False

    def scroll_chat_to_latest(self, _hwnd: int, *, attempts: int = 16) -> None:
        del attempts
        if "history" in self.scroll_ops:
            self.restored_after_history = True
        super().scroll_chat_to_latest(_hwnd)

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
        assert_true(target == "Customer A" and exact, "worker must preserve exact target identity")
        assert_true(artifact_dir is None, "target validation may not persist screenshots")
        if self.restored_after_history:
            return {"ok": False, "session_key": "wx:other", "conversation_type": conversation_type}
        return {"ok": True, "session_key": session_key, "conversation_type": conversation_type}


def check_worker_post_restore_target_change_fails_closed_without_public_leak() -> None:
    host = PostRestoreTargetChangeFakeHost()
    logger, handler, previous_level = _install_vision_capture_log_probe()
    try:
        result = run_operation(
            _args(
                "copy-current-image",
                side_filter="customer",
                pending_signal_id="pending-image-1",
                pending_observation_id="observation-1",
                source_preview="这是什么车？",
            ),
            host_ops=host,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
    assert_true(result.get("ok") is False, f"post-restore target change should fail closed: {result}")
    assert_true(result.get("reason") == "image_clipboard_copy_failed", f"post-restore target change should be generic publicly: {result}")
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert_true("target_changed" not in serialized and "restore" not in serialized and "bounds" not in serialized, f"post-restore failure leaked internals: {result}")
    assert_true(
        any("vision_pending_backsearch_post_restore_target_validation_failed" in message for message in handler.messages),
        f"post-restore target change should leave internal audit log: {handler.messages}",
    )
    _assert_internal_log_is_private(handler.messages)


class CopyValidationAbortFakeHost(PendingBacksearchFakeHost):
    def __init__(self, *, fail_at: int) -> None:
        super().__init__()
        self.fail_at = int(fail_at)
        self.validation_count = 0

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
        assert_true(target == "Customer A" and exact, "worker must preserve exact target identity")
        assert_true(artifact_dir is None, "target validation may not persist screenshots")
        self.validation_count += 1
        if self.validation_count >= self.fail_at:
            return {"ok": False, "session_key": "wx:other", "conversation_type": conversation_type}
        return {"ok": True, "session_key": session_key, "conversation_type": conversation_type}


def check_worker_revalidates_target_before_right_click() -> None:
    host = CopyValidationAbortFakeHost(fail_at=6)
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="pending-image-1",
            pending_observation_id="observation-1",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is False, f"target change before right-click should fail closed: {result}")
    assert_true(result.get("reason") == "vision_target_changed_during_image_backsearch", f"unexpected pre-right-click reason: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "target must be revalidated before right-click")


def check_worker_revalidates_target_before_menu_click() -> None:
    host = CopyValidationAbortFakeHost(fail_at=7)
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="pending-image-1",
            pending_observation_id="observation-1",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is False, f"target change before menu click should fail closed: {result}")
    assert_true(result.get("reason") == "vision_target_changed_during_image_backsearch", f"unexpected pre-menu-click reason: {result}")
    assert_true(host.right_clicks == 1 and host.menu_clicks == 0, "target must be revalidated before menu click")


class TargetChangeAbortFakeHost(PendingBacksearchFakeHost):
    def __init__(self) -> None:
        super().__init__()
        self.validation_count = 0

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
        assert_true(target == "Customer A" and exact, "worker must preserve exact target identity")
        assert_true(artifact_dir is None, "target validation may not persist screenshots")
        self.validation_count += 1
        if self.validation_count >= 4:
            return {"ok": False, "session_key": "wx:other", "conversation_type": conversation_type}
        return {"ok": True, "session_key": session_key, "conversation_type": conversation_type}


def check_worker_pending_backsearch_aborts_on_target_change_and_restores_latest() -> None:
    host = TargetChangeAbortFakeHost()
    result = run_operation(
        _args(
            "copy-current-image",
            side_filter="customer",
            pending_signal_id="pending-image-1",
            pending_observation_id="observation-1",
            source_preview="这是什么车？",
        ),
        host_ops=host,
    )
    assert_true(result.get("ok") is False, f"target change should abort pending copy: {result}")
    assert_true(result.get("reason") == "vision_target_changed_during_image_backsearch", f"unexpected abort reason: {result}")
    assert_true(host.right_clicks == 0 and host.menu_clicks == 0, "target change must abort before image operation")
    assert_true(host.scroll_ops and host.scroll_ops[-1] == "latest", f"target-change abort must restore latest: {host.scroll_ops}")


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
    assert_true("--pending-observation-id" not in calls[0], f"old worker command shape should not gain empty observation flag: {calls}")


def main() -> int:
    checks = [
        check_worker_observes_both_directions_without_artifacts,
        check_worker_copies_current_customer_image_without_sidecar_action,
        check_worker_pending_observe_records_private_store_without_public_leak,
        check_worker_pending_copy_uses_bounded_backsearch_and_restores_latest,
        check_worker_signal_only_pending_copy_keeps_legacy_latest_visible_behavior,
        check_worker_observation_only_pending_copy_uses_bounded_backsearch,
        check_worker_without_pending_keeps_legacy_latest_visible_behavior,
        check_worker_pending_backsearch_screenshot_budget_fails_closed_and_restores_latest,
        check_worker_menu_failure_excludes_candidate_and_retries_next,
        check_worker_restore_failure_releases_claim_and_fails_closed_without_public_leak,
        check_worker_post_restore_target_change_fails_closed_without_public_leak,
        check_worker_revalidates_target_before_right_click,
        check_worker_revalidates_target_before_menu_click,
        check_worker_pending_backsearch_aborts_on_target_change_and_restores_latest,
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
