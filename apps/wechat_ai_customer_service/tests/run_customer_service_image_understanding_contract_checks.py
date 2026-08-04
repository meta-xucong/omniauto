from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.clipboard_payload import (  # noqa: E402
    EphemeralClipboardImage,
    _CF_DIB,
    _decode_native_clipboard_value,
    _encode_ephemeral_image,
    read_current_clipboard_image,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.understanding.normalize import (  # noqa: E402
    normalize_customer_image_understanding_result,
)
from customer_image_understanding import maybe_run_customer_image_understanding  # noqa: E402
from customer_image_understanding_provider import (  # noqa: E402
    ImagePayloadError,
    build_anthropic_messages_vision_payload,
    build_openai_chat_vision_payload,
    data_url_from_image_path,
    run_customer_image_understanding_provider,
)
from customer_service_prompt_archive import archive_prompt_event  # noqa: E402


def main() -> int:
    checks = [
        check_current_clipboard_reader_accepts_only_same_generation_bitmap,
        check_native_windows_clipboard_png_and_dib_decode_in_memory,
        check_provider_payload_uses_memory_image_only,
        check_provider_and_workflow_reject_file_paths,
        check_image_archive_events_are_hard_disabled,
        check_released_payload_cannot_reach_provider,
        check_high_information_1080p_is_compressed_before_provider_limit,
        check_empty_vision_summary_cannot_be_completed,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - test harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            break
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _clipboard_bitmap() -> Image.Image:
    return Image.new("RGB", (96, 64), (60, 135, 215))


def _ephemeral_image() -> EphemeralClipboardImage:
    buffer = io.BytesIO()
    _clipboard_bitmap().save(buffer, format="PNG")
    return EphemeralClipboardImage(bytearray(buffer.getvalue()), "image/png", 96, 64)


def check_current_clipboard_reader_accepts_only_same_generation_bitmap() -> None:
    result = read_current_clipboard_image(
        {"clipboard_sequence_after": 40},
        clipboard_reader=_clipboard_bitmap,
        sequence_provider=lambda: 40,
    )
    assert_true(result.get("ok") is True, f"current bitmap should be accepted: {result}")
    payload = result.get("image")
    assert_true(isinstance(payload, EphemeralClipboardImage), "clipboard image must stay an ephemeral object")
    assert_true(bool(payload.image_bytes), "ephemeral payload needs in-memory image bytes")
    payload.release()
    assert_true(payload.released and not payload.image_bytes, "release must clear image bytes")

    stale = read_current_clipboard_image(
        {"clipboard_sequence_after": 40},
        clipboard_reader=_clipboard_bitmap,
        sequence_provider=lambda: 39,
    )
    assert_equal(stale.get("reason"), "clipboard_sequence_not_current", "stale clipboard generation must fail")
    file_list = read_current_clipboard_image(
        {"clipboard_sequence_after": 40},
        clipboard_reader=lambda: ["C:/old.png"],
        sequence_provider=lambda: 40,
    )
    assert_equal(file_list.get("reason"), "clipboard_current_content_not_bitmap", "clipboard file list must not be read")


def check_native_windows_clipboard_png_and_dib_decode_in_memory() -> None:
    source = _clipboard_bitmap()
    png_buffer = io.BytesIO()
    bmp_buffer = io.BytesIO()
    try:
        source.save(png_buffer, format="PNG")
        source.save(bmp_buffer, format="BMP")
        png_image = _decode_native_clipboard_value(
            format_id=0,
            format_name="image/png",
            value=png_buffer.getvalue(),
        )
        assert_true(isinstance(png_image, Image.Image), "native image/png clipboard bytes must decode in memory")
        assert_equal(png_image.size, (96, 64), "native PNG must retain image dimensions")
        png_image.close()

        dib_image = _decode_native_clipboard_value(
            format_id=_CF_DIB,
            format_name="",
            value=bmp_buffer.getvalue()[14:],
        )
        assert_true(isinstance(dib_image, Image.Image), "native CF_DIB clipboard bytes must decode in memory")
        assert_equal(dib_image.size, (96, 64), "native DIB must retain image dimensions")
        dib_image.close()

        rejected = _decode_native_clipboard_value(
            format_id=0,
            format_name="UniformResourceLocatorW",
            value=b"https://example.invalid/old.png",
        )
        assert_equal(rejected, None, "URL/file-style clipboard formats must never become vision input")
    finally:
        source.close()
        png_buffer.close()
        bmp_buffer.close()


def check_provider_payload_uses_memory_image_only() -> None:
    payload = _ephemeral_image()
    openai = build_openai_chat_vision_payload(
        model="vision-test",
        prompt="recognize",
        image_paths=[],
        image_payloads=[payload],
    )
    content = openai["messages"][0]["content"]
    url = content[1]["image_url"]["url"]
    assert_true(url.startswith("data:image/png;base64,"), "OpenAI request should embed the memory payload")
    assert_true("path" not in json.dumps(openai).lower(), "provider request must not contain filesystem data")
    anthropic = build_anthropic_messages_vision_payload(
        model="vision-test",
        prompt="recognize",
        image_paths=[],
        image_payloads=[payload],
    )
    source = anthropic["messages"][0]["content"][1]["source"]
    assert_equal(source.get("type"), "base64", "Anthropic request should embed the memory payload")
    payload.release()


def check_provider_and_workflow_reject_file_paths() -> None:
    try:
        data_url_from_image_path("C:/historical-crop.png")
    except ImagePayloadError as exc:
        assert_equal(str(exc), "legacy_image_path_input_rejected", "path facade must reject before filesystem access")
    else:
        raise AssertionError("legacy file path was accepted")

    provider = run_customer_image_understanding_provider(
        api_key="unused",
        base_url="http://127.0.0.1:1",
        model="vision-test",
        request_style="openai_chat_vision",
        prompt="recognize",
        image_paths=["C:/historical-crop.png"],
        timeout_seconds=1,
    )
    assert_equal(provider.get("error"), "legacy_image_path_input_rejected", "provider must reject a local path before any request")
    workflow = maybe_run_customer_image_understanding(
        config={"customer_image_understanding": {"enabled": True}},
        customer_text="",
        image_assets=[{"saved_image_path": "C:/historical-crop.png"}],
        source_reason="legacy",
    )
    assert_equal(workflow.get("reason"), "legacy_image_path_input_rejected", "workflow must not profile historical image files")


def check_image_archive_events_are_hard_disabled() -> None:
    for kind in (
        "customer_image_understanding_prompt",
        "customer_image_understanding_retry_prompt",
        "customer_image_understanding_result",
        "customer_image_understanding_error",
        "customer_image_turn_bridge",
    ):
        archived = archive_prompt_event(kind, {"image_bytes": "not-real", "saved_image_path": "C:/old.png"})
        assert_equal(archived.get("archived"), False, f"{kind} must never persist image event data")
        assert_equal(archived.get("reason"), "kind_disabled", f"{kind} must expose the hard archive block")


def check_released_payload_cannot_reach_provider() -> None:
    payload = _ephemeral_image()
    payload.release()
    result = run_customer_image_understanding_provider(
        api_key="unused",
        base_url="http://127.0.0.1:1",
        model="vision-test",
        request_style="openai_chat_vision",
        prompt="recognize",
        image_paths=[],
        image_payloads=[payload],
        timeout_seconds=1,
    )
    assert_equal(result.get("error"), "customer_image_understanding_image_payload_invalid", "released image cannot be sent to a provider")


def check_high_information_1080p_is_compressed_before_provider_limit() -> None:
    image = Image.effect_noise((1920, 1080), 96.0).convert("RGB")
    try:
        payload = _encode_ephemeral_image(
            image,
            source_limits={
                "max_encoded_source_bytes": 12 * 1024 * 1024,
                "max_decoded_pixels": 20_000_000,
                "max_decoded_rgba_bytes": 80 * 1024 * 1024,
                "max_provider_payload_bytes": 3 * 1024 * 1024,
                "max_provider_edge_px": 2048,
            },
        )
    finally:
        image.close()
    assert_true(payload is not None, "high-information 1080p image must be compressed in memory")
    assert_true(
        0 < len(payload.image_bytes) <= 3 * 1024 * 1024,
        "provider payload must satisfy the post-compression limit",
    )
    assert_equal((payload.width, payload.height), (1920, 1080), "valid 1080p dimensions must be retained")
    payload.release()


def check_empty_vision_summary_cannot_be_completed() -> None:
    result = normalize_customer_image_understanding_result(
        {
            "applied": True,
            "adoptable": True,
            "reason": "provider_returned_structured_empty_result",
            "vision_summary": "  ",
            "classification": {
                "is_vehicle": False,
                "vehicle_confidence": 0.0,
                "unknown": True,
            },
        },
        enabled=True,
        provider="test-provider",
        request_style="openai_chat_vision",
        model="test-model",
    )
    assert_equal(result.get("applied"), False, "empty summary must never be a completed Vision result")
    assert_equal(result.get("adoptable"), False, "empty summary must never reach the Brain as adoptable")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
