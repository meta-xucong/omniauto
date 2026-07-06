from __future__ import annotations

import json
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

from apps.wechat_ai_customer_service.adapters.wechat_image_save_capture import (  # noqa: E402
    build_image_message_from_asset,
    build_saved_image_asset,
    detect_customer_image_bubbles,
    detect_visual_image_bubbles,
    execute_wechat_image_save,
    find_copy_menu_item,
    find_save_menu_item,
    image_preview_text,
    parse_preview_speaker,
    save_clipboard_image_to_path,
    wait_for_file_stable,
)
from apps.wechat_ai_customer_service.adapters.wechat_win32_ocr.geometry import session_split_x  # noqa: E402


def main() -> int:
    checks = [
        check_image_preview_and_speaker_parsing,
        check_saved_image_asset_and_message_contract,
        check_detect_customer_image_bubble_prefers_customer_side,
        check_detect_visual_image_bubbles_keeps_both_sides,
        check_find_save_menu_item_supports_chinese_and_english,
        check_find_copy_menu_item_supports_wechat_menu,
        check_save_clipboard_image_to_path_writes_png,
        check_execute_image_save_prefers_clipboard_copy,
        check_execute_image_save_crop_mode_archives_both_sides_without_clicks,
        check_wait_for_file_stable_reports_missing_file,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def check_image_preview_and_speaker_parsing() -> None:
    assert_true(image_preview_text("许聪:[图片]"), "group image preview should be detected")
    assert_true(image_preview_text("发送了一张图片"), "plain image preview should be detected")
    assert_equal(parse_preview_speaker("许聪:[图片]"), "许聪", "speaker should be parsed from preview")
    assert_equal(parse_preview_speaker("[图片]"), "", "single-chat preview should not invent speaker")


def check_saved_image_asset_and_message_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        image_path = Path(tmp_dir) / "car.jpg"
        Image.new("RGB", (64, 48), (240, 240, 240)).save(image_path)
        asset = build_saved_image_asset(
            saved_image_path=image_path,
            target_name="新数据测试",
            session_key="wx:test",
            speaker_name="许聪",
            source_preview="许聪:[图片]",
        )
        message = build_image_message_from_asset(asset)
    assert_true(str(asset.get("saved_image_path") or "").endswith("car.jpg"), f"asset should keep saved path: {asset}")
    assert_equal(asset.get("message_type"), "image", "asset message_type should be image")
    assert_equal(message.get("type"), "image", "raw image-save message should be image")
    assert_equal(message.get("sender_role"), "customer", "image message should be customer-authored")
    assert_true(bool(message.get("image_assets")), "message should reference asset")


def check_detect_customer_image_bubble_prefers_customer_side() -> None:
    image = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    split = session_split_x(980)
    draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
    draw.rectangle([split + 42, 260, split + 262, 440], fill=(30, 120, 190))
    draw.rectangle([810, 500, 940, 640], fill=(190, 80, 50))
    bubbles = detect_customer_image_bubbles(image, messages=[], max_images=1)
    assert_true(bool(bubbles), "customer-side visual bubble should be found")
    assert_equal(bubbles[0].get("side"), "customer", "detected bubble should be customer side")
    assert_true(int((bubbles[0].get("anchor") or {}).get("x") or 0) < 760, f"anchor should be on customer side: {bubbles}")


def check_detect_visual_image_bubbles_keeps_both_sides() -> None:
    image = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    split = session_split_x(980)
    draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
    draw.rectangle([split + 42, 250, split + 282, 450], fill=(30, 120, 190))
    draw.rectangle([760, 500, 940, 660], fill=(190, 80, 50))
    bubbles = detect_visual_image_bubbles(image, messages=[], max_images=8, side_filter="all")
    sides = {str(item.get("side") or "") for item in bubbles}
    assert_true("customer" in sides, f"customer visual bubble should be found: {bubbles}")
    assert_true("self" in sides, f"self visual bubble should be found: {bubbles}")


def check_find_save_menu_item_supports_chinese_and_english() -> None:
    chinese = find_save_menu_item(
        [{"text": "另存为...", "left": 500, "top": 300, "right": 570, "bottom": 326, "center_x": 535, "center_y": 313, "confidence": 0.9}],
        (980, 860),
    )
    english = find_save_menu_item(
        [{"text": "Save Image", "left": 500, "top": 300, "right": 590, "bottom": 326, "center_x": 545, "center_y": 313, "confidence": 0.9}],
        (980, 860),
    )
    assert_true(bool(chinese), "Chinese save menu item should be detected")
    assert_true(bool(english), "English save menu item should be detected")
    preferred = find_save_menu_item(
        [
            {"text": "保存图片", "left": 500, "top": 260, "right": 570, "bottom": 286, "center_x": 535, "center_y": 273, "confidence": 0.99},
            {"text": "另存为...", "left": 500, "top": 300, "right": 570, "bottom": 326, "center_x": 535, "center_y": 313, "confidence": 0.7},
        ],
        (980, 860),
    )
    assert_equal(str((preferred or {}).get("text") or ""), "另存为...", "Save As should win because it allows choosing the dedicated image folder")


def check_find_copy_menu_item_supports_wechat_menu() -> None:
    copy_item = find_copy_menu_item(
        [
            {"text": "复制", "left": 600, "top": 488, "right": 636, "bottom": 508, "confidence": 0.95},
            {"text": "另存为...", "left": 604, "top": 884, "right": 672, "bottom": 904, "confidence": 0.9},
        ],
        (980, 960),
    )
    assert_true(bool(copy_item), f"WeChat copy menu item should be detected: {copy_item}")
    assert_equal(str((copy_item or {}).get("text") or ""), "复制", "copy should be selected before save-as fallback")


def check_save_clipboard_image_to_path_writes_png() -> None:
    class Ops:
        @staticmethod
        def grab_clipboard_image() -> Image.Image:
            return Image.new("RGB", (80, 60), (230, 230, 230))

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "copied.png"
        result = save_clipboard_image_to_path(Ops(), path)
        assert_true(bool(result.get("ok")), f"clipboard image should be written: {result}")
        with Image.open(path) as saved:
            assert_equal((saved.width, saved.height), (80, 60), "saved clipboard image should keep dimensions")


def check_execute_image_save_prefers_clipboard_copy() -> None:
    screenshot = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(screenshot)
    split = session_split_x(980)
    draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
    draw.rectangle([split + 88, 330, split + 308, 560], fill=(80, 150, 210))
    menu = screenshot.copy()
    draw_menu = ImageDraw.Draw(menu)
    draw_menu.rectangle([560, 468, 762, 904], fill=(255, 255, 255), outline=(220, 220, 220))

    class Win32Con:
        VK_ESCAPE = 0x1B

    class Win32Gui:
        @staticmethod
        def GetWindowRect(_hwnd: int) -> tuple[int, int, int, int]:
            return (0, 0, 980, 860)

    class Ops:
        win32con = Win32Con()
        win32gui = Win32Gui()
        clipboard_reads = 0

        @staticmethod
        def capture_wechat(_hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat") -> tuple[Image.Image, str]:
            return screenshot, str(Path(artifact_dir or ".") / f"{label}.png")

        @staticmethod
        def capture_wechat_window_visible_screen(_hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat_visible") -> tuple[Image.Image, str]:
            return menu, str(Path(artifact_dir or ".") / f"{label}.png")

        @staticmethod
        def run_ocr(image: Image.Image) -> list[dict[str, Any]]:
            if image is menu:
                return [{"text": "复制", "left": 600, "top": 488, "right": 636, "bottom": 508, "confidence": 0.95}]
            return []

        @staticmethod
        def get_window_geometry(_hwnd: int) -> dict[str, Any]:
            return {"width": 980, "height": 860}

        @staticmethod
        def parse_messages_from_ocr(_items: list[dict[str, Any]], _image_size: tuple[int, int], *, target: str = "") -> list[dict[str, Any]]:
            return []

        @staticmethod
        def blocking_screen_reason(_items: list[dict[str, Any]]) -> str:
            return ""

        @staticmethod
        def human_window_image_right_click_in_bounds(_hwnd: int, x: int, y: int, *, bounds: list[int], action_name: str = "") -> dict[str, Any]:
            return {"ok": True, "x": x, "y": y, "bounds": bounds}

        @staticmethod
        def humanized_action_sleep(_minimum: int, _maximum: int) -> None:
            return None

        @staticmethod
        def human_screen_click(x: int, y: int, *, action_name: str = "") -> dict[str, Any]:
            return {"ok": True, "screen_x": x, "screen_y": y, "action_name": action_name}

        @classmethod
        def grab_clipboard_image(cls) -> Image.Image:
            cls.clipboard_reads += 1
            return Image.new("RGB", (120, 90), (245, 245, 245))

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = execute_wechat_image_save(
            hwnd=100,
            probe={"ok": True},
            target_name="新数据测试",
            session_key="wx:test",
            artifact_dir=tmp_dir,
            tenant_id="chejin",
            source_preview="许聪:[图片]",
            speaker_name="许聪",
            sidecar_ops=Ops,
        )
    assert_true(bool(result.get("ok")), f"clipboard-first image save should succeed: {result}")
    asset = (result.get("assets") or [{}])[0]
    assert_equal(asset.get("save_method"), "context_menu_copy_clipboard", "clipboard copy should be the primary save method")
    assert_equal(asset.get("speaker_name"), "许聪", "asset should preserve image speaker")
    assert_true(str(asset.get("saved_image_path") or "").endswith(".png"), "clipboard image should be stored as PNG")
    assert_equal(Ops.clipboard_reads, 1, "clipboard should be read exactly once on success")


def check_execute_image_save_crop_mode_archives_both_sides_without_clicks() -> None:
    screenshot = Image.new("RGB", (980, 860), (247, 247, 247))
    draw = ImageDraw.Draw(screenshot)
    split = session_split_x(980)
    draw.rectangle([0, 0, split, 860], fill=(240, 240, 240))
    draw.rectangle([split + 12, 90, 972, 760], fill=(255, 255, 255))
    draw.rectangle([split + 50, 260, split + 290, 470], fill=(30, 120, 190))
    draw.rectangle([740, 500, 940, 690], fill=(190, 80, 50))

    class Ops:
        right_clicks = 0

        @staticmethod
        def capture_wechat(_hwnd: int, *, artifact_dir: str | None = None, label: str = "wechat") -> tuple[Image.Image, str]:
            return screenshot, str(Path(artifact_dir or ".") / f"{label}.png")

        @staticmethod
        def run_ocr(_image: Image.Image) -> list[dict[str, Any]]:
            return []

        @staticmethod
        def get_window_geometry(_hwnd: int) -> dict[str, Any]:
            return {"width": 980, "height": 860}

        @staticmethod
        def parse_messages_from_ocr(_items: list[dict[str, Any]], _image_size: tuple[int, int], *, target: str = "") -> list[dict[str, Any]]:
            return []

        @staticmethod
        def blocking_screen_reason(_items: list[dict[str, Any]]) -> str:
            return ""

        @classmethod
        def human_window_image_right_click_in_bounds(cls, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
            cls.right_clicks += 1
            return {"ok": False}

    with tempfile.TemporaryDirectory() as tmp_dir:
        result = execute_wechat_image_save(
            hwnd=100,
            probe={"ok": True},
            target_name="新数据测试",
            session_key="wx:test",
            artifact_dir=tmp_dir,
            tenant_id="chejin",
            capture_mode="crop",
            side_filter="all",
            max_images=8,
            sidecar_ops=Ops,
        )
        assets = [item for item in (result.get("assets") or []) if isinstance(item, dict)]
        paths = [Path(str(item.get("saved_image_path") or "")) for item in assets]
        assert_true(all(path.is_file() for path in paths), f"crop assets should be saved: {assets}")
    sides = {str(item.get("visual_side") or "") for item in assets}
    assert_true(bool(result.get("ok")), f"crop mode should succeed: {result}")
    assert_equal(result.get("state"), "visual_bubbles_archived", "crop mode should report archive state")
    assert_true("customer" in sides and "self" in sides, f"both visual sides should be archived: {assets}")
    assert_equal(Ops.right_clicks, 0, "crop mode must not use context-menu right click")


def check_wait_for_file_stable_reports_missing_file() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        result = wait_for_file_stable(Path(tmp_dir) / "missing.jpg", timeout_seconds=0.2, quiet_period_seconds=0.05)
    assert_true(result.get("ok") is False, f"missing file should fail: {result}")
    assert_equal(result.get("reason"), "image_file_unstable", "failure reason should be stable")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
