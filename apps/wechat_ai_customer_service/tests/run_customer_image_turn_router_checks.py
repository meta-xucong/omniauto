from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
for path in (PROJECT_ROOT, APP_ROOT, WORKFLOWS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import customer_image_turn_router as router_module  # noqa: E402
from apps.wechat_ai_customer_service.optional_plugins.vision.clipboard_payload import (  # noqa: E402
    EphemeralClipboardImage,
)


def main() -> int:
    checks = [
        check_trigger_requires_current_pending_signal,
        check_router_uses_one_ephemeral_clipboard_transaction,
        check_router_uses_group_acquire_for_current_image_proxy,
        check_router_uses_one_provider_call_for_three_acquired_images,
        check_router_group_acquire_failure_stops_before_provider,
        check_router_group_provider_failure_releases_images,
        check_router_group_empty_summary_releases_images,
        check_router_invalid_group_size_releases_images_without_provider,
        check_router_rejects_historical_saved_path,
        check_router_deduplicates_processed_pending_signal,
        check_unenriched_history_placeholder_does_not_block_first_clipboard_read,
        check_router_returns_copy_failure_without_fallback,
        check_self_image_context_is_text_only_and_never_reply_adoptable,
    ]
    results: list[dict[str, Any]] = []
    original_transaction = router_module._run_current_clipboard_image_transaction
    router_module._run_current_clipboard_image_transaction = _test_vision_transaction
    try:
        for check in checks:
            try:
                check()
                results.append({"name": check.__name__, "ok": True})
            except Exception as exc:  # pragma: no cover - test harness
                results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
                break
    finally:
        router_module._run_current_clipboard_image_transaction = original_transaction
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def _ephemeral_image(width: int = 96, height: int = 64, color: tuple[int, int, int] = (55, 125, 205)) -> EphemeralClipboardImage:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return EphemeralClipboardImage(bytearray(buffer.getvalue()), "image/png", width, height)


def _target() -> SimpleNamespace:
    return SimpleNamespace(name="Customer A", exact=True, session_key="wx:clipboard-check", conversation_type="private")


def _pending_payload(signal_id: str = "image-signal-1") -> dict[str, Any]:
    return {
        "pending_signal": {
            "pending_signal_id": signal_id,
            "pending_signal_kind": "image_capture",
            "pending_signal_text": "[图片]",
        },
        "messages": [
            {
                "id": f"visual-customer:{signal_id}",
                "message_id": f"visual-customer:{signal_id}",
                "type": "image",
                "message_type": "image",
                "sender": "customer",
                "sender_role": "customer",
                "visual_side": "customer",
                "visual_turn_kind": "customer_image",
                "pending_signal_id": signal_id,
                "content": "[图片]",
                "source_adapter": "win32_ocr_structural_image_observer",
            }
        ],
    }


def _current_image_proxy(signal_id: str = "image-signal-1") -> dict[str, Any]:
    return {
        "id": f"clipboard_image_pending:{signal_id}",
        "message_id": f"clipboard_image_pending:{signal_id}",
        "type": "text",
        "sender": "customer",
        "sender_role": "customer",
        "content": "客户发来了一张图片",
        "pending_signal_id": signal_id,
        "visual_turn_kind": "customer_image",
        "is_customer_image_proxy": True,
        "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction"],
    }


def _proxy_payload(signal_id: str = "image-signal-1") -> dict[str, Any]:
    return {
        "pending_signal": {
            "pending_signal_id": signal_id,
            "pending_signal_kind": "image_capture",
            "pending_signal_text": "[图片]",
        },
        "messages": [_current_image_proxy(signal_id)],
    }


class ClipboardConnector:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, Any]] = []
        self.image: EphemeralClipboardImage | None = None

    def run_current_clipboard_image_transaction(self, target: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"target": target, **kwargs})
        transaction = {
            "status": "copied",
            "captured_at": "2026-07-13T12:00:00",
            "right_click_ok": True,
            "menu_copy_confirmed": True,
            "clipboard_sequence_changed": True,
            "clipboard_sequence_after": 73,
        }
        if not self.ok:
            return {"ok": False, "state": "image_clipboard_copy_failed", "reason": "clipboard_sequence_unchanged_after_copy", "transaction": transaction}
        self.image = _ephemeral_image()
        return {"ok": True, "transaction": transaction, "_ephemeral_clipboard_image": self.image}


class SelfClipboardConnector(ClipboardConnector):
    pass


def _test_vision_transaction(**kwargs: Any) -> dict[str, Any]:
    """Inject the Vision-owned transaction seam without reviving production facades."""

    connector = kwargs["connector"]
    method = getattr(connector, "run_current_clipboard_image_transaction")
    return method(
        str(kwargs.get("target") or ""),
        exact=bool(kwargs.get("exact", True)),
        session_key=str(kwargs.get("session_key") or ""),
        source_preview=str(kwargs.get("source_preview") or ""),
        speaker_name=str(kwargs.get("speaker_name") or ""),
        pending_signal_id=str(kwargs.get("pending_signal_id") or ""),
        consume_current_clipboard=router_module.read_current_clipboard_image,
    )


def _group_acquire_result(images: list[EphemeralClipboardImage], *, ok: bool = True) -> dict[str, Any]:
    return {
        "ok": ok,
        "transaction": {
            "status": "copied",
            "captured_at": "2026-07-30T10:00:00",
            "clipboard_sequence_changed": ok,
            "clipboard_content_read": ok,
            "clipboard_image_valid": ok,
        },
        "messages": [
            {
                "id": f"visual-group-image-{index + 1}",
                "message_id": f"visual-group-image-{index + 1}",
                "type": "image",
                "sender": "customer",
                "visual_side": "customer",
            }
            for index, _image in enumerate(images)
        ],
        "_ephemeral_clipboard_images": images,
    }


def check_trigger_requires_current_pending_signal() -> None:
    historical = router_module.customer_image_capture_trigger(
        payload={"messages": [{"type": "image", "saved_image_path": "C:/old.png"}]},
        pending_signal={"pending_signal_kind": "normal"},
    )
    assert_equal(historical.get("should_run"), False, "historical image metadata must not trigger capture")
    current = router_module.customer_image_capture_trigger(
        payload={},
        pending_signal={"pending_signal_id": "p1", "pending_signal_kind": "image_capture", "pending_signal_text": "[图片]"},
    )
    assert_equal(current.get("should_run"), True, "current image pending signal should trigger capture")


def check_router_uses_one_ephemeral_clipboard_transaction() -> None:
    connector = ClipboardConnector()
    observed: dict[str, Any] = {}
    original_understanding = router_module.maybe_run_customer_image_understanding
    original_assist = router_module.build_customer_image_catalog_assist
    try:
        def fake_understanding(**kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            payloads = kwargs.get("image_payloads") or []
            assert_equal(len(payloads), 1, "one copied clipboard image must be passed to vision")
            assert_true(not payloads[0].released, "image must stay live until visual understanding returns")
            return {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "vehicle image recognized",
                "classification": {"is_vehicle": True, "vehicle_confidence": 0.91},
                "intent_hints": {"wants_catalog_match": True},
                "bridge": {"normalized_vehicle_query": "Audi A4L"},
                "source_messages": [{"message_id": "image-signal-1", "message_type": "image"}],
            }

        router_module.maybe_run_customer_image_understanding = fake_understanding
        router_module.build_customer_image_catalog_assist = lambda **_kwargs: {
            "applied": True,
            "normalized_vehicle_query": "Audi A4L",
            "conversation_context_patch": {
                "last_customer_need_text": "Audi A4L",
                "last_product_id": "new-audi-a4l",
                "last_product_name": "Audi A4L",
            },
        }
        result = router_module.maybe_route_customer_image_turn(
            connector=connector,
            target=_target(),
            config={},
            payload=_pending_payload(),
            target_state={
                "conversation_context": {
                    "last_product_id": "old-product",
                    "last_product_name": "Old Product",
                    "last_unit_price": 25.8,
                    "last_product_source": "product_master",
                    "last_shipping_city": "南京",
                }
            },
            batch=[],
            combined="",
        )
    finally:
        router_module.maybe_run_customer_image_understanding = original_understanding
        router_module.build_customer_image_catalog_assist = original_assist

    assert_true(result.get("applied") is True, f"clipboard image route should apply: {result}")
    assert_equal(len(connector.calls), 1, "one image signal must cause one transaction")
    assert_true(callable(connector.calls[0].get("consume_current_clipboard")), "connector must receive the vision-owned current clipboard reader")
    assert_equal(observed.get("ephemeral_clipboard"), True, "router must declare ephemeral clipboard mode")
    assert_equal(observed.get("image_paths"), None, "router may not send local image paths")
    assert_true(connector.image is not None and connector.image.released, "clipboard image bytes must be released before routing returns")
    brain_context = (result.get("target_state_for_brain") or {}).get("conversation_context") or {}
    assert_equal(brain_context.get("last_product_id"), "new-audi-a4l", "current image product must replace the prior product binding before Brain runs")
    assert_true("last_unit_price" not in brain_context, "current image turn must not carry the prior product price into Brain")
    assert_true("last_product_source" not in brain_context, "current image turn must not carry the prior product authority into Brain")
    assert_equal(brain_context.get("last_shipping_city"), "南京", "stable customer preferences must survive a product switch")
    assert_no_path_or_bytes(result)
    transaction = result.get("clipboard_transaction") or {}
    assert_equal(transaction.get("clipboard_sequence_changed"), True, "public audit keeps copy proof only")
    assert_true("clipboard_sequence_after" not in transaction, "raw clipboard generation is not persisted")


def check_router_uses_group_acquire_for_current_image_proxy() -> None:
    images = [_ephemeral_image()]
    acquire_calls: list[dict[str, Any]] = []
    observed: dict[str, Any] = {}
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        def fake_acquire(**kwargs: Any) -> dict[str, Any]:
            acquire_calls.append(kwargs)
            return _group_acquire_result(images)

        def fake_understanding(**kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            payloads = kwargs.get("image_payloads") or []
            assert_equal(payloads, images, "group acquire images must be handed to provider as-is")
            return {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "single current image recognized",
                "classification": {"is_vehicle": True},
            }

        router_module._run_current_visual_group_acquire = fake_acquire
        router_module.maybe_run_customer_image_understanding = fake_understanding
        proxy = _current_image_proxy()
        result = router_module.maybe_route_customer_image_turn(
            connector=ClipboardConnector(),
            target=_target(),
            config={},
            payload=_proxy_payload(),
            target_state={},
            batch=[proxy],
            combined="",
        )
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_true(result.get("applied") is True, f"group image route should apply: {result}")
    assert_equal(len(acquire_calls), 1, "current proxy must call group acquire exactly once")
    assert_equal(len(observed.get("image_payloads") or []), 1, "provider must be called once with one image payload")
    assert_true(images[0].released, "acquired image must be released after success")
    assert_no_path_or_bytes(result)


def check_router_uses_one_provider_call_for_three_acquired_images() -> None:
    images = [
        _ephemeral_image(90, 60, (200, 40, 40)),
        _ephemeral_image(91, 60, (40, 200, 40)),
        _ephemeral_image(92, 60, (40, 40, 200)),
    ]
    provider_calls: list[list[EphemeralClipboardImage]] = []
    acquire_calls: list[dict[str, Any]] = []
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        def fake_acquire(**kwargs: Any) -> dict[str, Any]:
            acquire_calls.append(kwargs)
            return _group_acquire_result(images)

        def fake_understanding(**kwargs: Any) -> dict[str, Any]:
            provider_calls.append(list(kwargs.get("image_payloads") or []))
            assert_equal([image.width for image in kwargs.get("image_payloads") or []], [90, 91, 92], "provider must preserve collector order")
            return {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "three ordered vehicle images recognized",
                "source_messages": kwargs.get("image_assets") or [],
            }

        router_module._run_current_visual_group_acquire = fake_acquire
        router_module.maybe_run_customer_image_understanding = fake_understanding
        proxy = _current_image_proxy()
        result = router_module.maybe_route_customer_image_turn(
            connector=ClipboardConnector(),
            target=_target(),
            config={},
            payload=_proxy_payload(),
            target_state={},
            batch=[
                proxy,
                {"id": "text-1", "message_id": "text-1", "type": "text", "sender": "customer", "content": "这个车有吗"},
                {"id": "text-2", "message_id": "text-2", "type": "text", "sender": "customer", "content": "想看看内饰"},
                {"id": "text-3", "message_id": "text-3", "type": "text", "sender": "customer", "content": "预算二十多"},
                {"id": "text-4", "message_id": "text-4", "type": "text", "sender": "customer", "content": "能贷款吗"},
                {"id": "text-5", "message_id": "text-5", "type": "text", "sender": "customer", "content": "今天能看车吗"},
            ],
            combined="这个车有吗\n想看看内饰\n预算二十多\n能贷款吗\n今天能看车吗",
        )
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_true(result.get("applied") is True, f"three-image group route should apply: {result}")
    assert_equal(len(provider_calls), 1, "three images must use one provider call")
    assert_equal(provider_calls[0], images, "provider must receive the full ordered group")
    assert_equal(acquire_calls[0].get("anchor_text_key"), "这个车有吗", "group acquire should receive the first current-turn text anchor")
    assert_true(all(image.released for image in images), "all acquired images must be released after success")
    assert_no_path_or_bytes(result)


def check_router_group_acquire_failure_stops_before_provider() -> None:
    provider_calls = 0
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        router_module._run_current_visual_group_acquire = lambda **_kwargs: _group_acquire_result([], ok=False)
        def fake_understanding(**_kwargs: Any) -> dict[str, Any]:
            nonlocal provider_calls
            provider_calls += 1
            return {}

        router_module.maybe_run_customer_image_understanding = fake_understanding
        try:
            router_module.maybe_route_customer_image_turn(
                connector=ClipboardConnector(),
                target=_target(),
                config={},
                payload=_proxy_payload(),
                target_state={},
                batch=[_current_image_proxy()],
                combined="",
            )
        except router_module._VisionEvidenceUnavailable:
            pass
        else:
            raise AssertionError("strict required image acquire failure must raise before Brain")
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_equal(provider_calls, 0, "provider must not run when acquire fails")


def check_router_group_provider_failure_releases_images() -> None:
    images = [_ephemeral_image(), _ephemeral_image(80, 80, (20, 20, 20))]
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        router_module._run_current_visual_group_acquire = lambda **_kwargs: _group_acquire_result(images)
        def failing_understanding(**_kwargs: Any) -> dict[str, Any]:
            raise TimeoutError("provider timeout")

        router_module.maybe_run_customer_image_understanding = failing_understanding
        try:
            router_module.maybe_route_customer_image_turn(
                connector=ClipboardConnector(),
                target=_target(),
                config={},
                payload=_proxy_payload(),
                target_state={},
                batch=[_current_image_proxy()],
                combined="",
            )
        except router_module._VisionEvidenceUnavailable:
            pass
        else:
            raise AssertionError("provider failure for required image must raise before Brain")
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_true(all(image.released for image in images), "provider exception must release all acquired images")


def check_router_group_empty_summary_releases_images() -> None:
    images = [_ephemeral_image()]
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        router_module._run_current_visual_group_acquire = lambda **_kwargs: _group_acquire_result(images)
        router_module.maybe_run_customer_image_understanding = lambda **_kwargs: {
            "applied": True,
            "adoptable": True,
            "reason": "vision_ready",
            "vision_summary": "",
        }
        try:
            router_module.maybe_route_customer_image_turn(
                connector=ClipboardConnector(),
                target=_target(),
                config={},
                payload=_proxy_payload(),
                target_state={},
                batch=[_current_image_proxy()],
                combined="",
            )
        except router_module._VisionEvidenceUnavailable:
            pass
        else:
            raise AssertionError("empty required vision summary must raise before Brain")
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_true(images[0].released, "empty-summary failure must release the acquired image")


def check_router_invalid_group_size_releases_images_without_provider() -> None:
    original_acquire = router_module._run_current_visual_group_acquire
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        for images in ([], [_ephemeral_image(60 + index, 50, (index * 30, 80, 120)) for index in range(4)]):
            provider_calls = 0

            def fake_acquire(**_kwargs: Any) -> dict[str, Any]:
                return _group_acquire_result(images)

            router_module._run_current_visual_group_acquire = fake_acquire

            def fake_understanding(**_kwargs: Any) -> dict[str, Any]:
                nonlocal provider_calls
                provider_calls += 1
                return {}

            router_module.maybe_run_customer_image_understanding = fake_understanding
            try:
                router_module.maybe_route_customer_image_turn(
                    connector=ClipboardConnector(),
                    target=_target(),
                    config={},
                    payload=_proxy_payload(),
                    target_state={},
                    batch=[_current_image_proxy()],
                    combined="",
                )
            except router_module._VisionEvidenceUnavailable:
                pass
            else:
                raise AssertionError("invalid group size must fail before provider")
            assert_equal(provider_calls, 0, "invalid image count must not call provider")
            assert_true(all(image.released for image in images), "invalid image count must still release acquired images")
    finally:
        router_module._run_current_visual_group_acquire = original_acquire
        router_module.maybe_run_customer_image_understanding = original_understanding


def check_router_rejects_historical_saved_path() -> None:
    result = router_module.maybe_route_customer_image_turn(
        connector=ClipboardConnector(),
        target=_target(),
        config={},
        payload={"messages": [{"type": "image", "saved_image_path": "C:/historical-crop.png"}]},
        target_state={},
        batch=[],
        combined="",
    )
    assert_equal(result.get("reason"), "current_image_pending_signal_missing", "saved-image history must not re-enter vision")


def check_router_deduplicates_processed_pending_signal() -> None:
    connector = ClipboardConnector()
    result = router_module.maybe_route_customer_image_turn(
        connector=connector,
        target=_target(),
        config={},
        payload=_pending_payload("seen-image"),
        target_state={"processed_visual_pending_signal_ids": ["seen-image"]},
        batch=[],
        combined="",
    )
    assert_equal(result.get("reason"), "pending_image_signal_already_processed", "processed signal must terminate without a new copy")
    assert_equal(connector.calls, [], "dedupe must happen before RPA")


def check_unenriched_history_placeholder_does_not_block_first_clipboard_read() -> None:
    connector = ClipboardConnector(ok=False)
    result = router_module.maybe_route_customer_image_turn(
        connector=connector,
        target=_target(),
        config={},
        payload=_pending_payload("first-image"),
        target_state={
            "conversation_context": {
                "ledger_recent_messages": [
                    {
                        "message_id": "clipboard_image_pending:first-image",
                        "pending_signal_id": "first-image",
                        "image_capture_pending": True,
                    }
                ]
            }
        },
        batch=[],
        combined="",
    )
    assert_equal(len(connector.calls), 1, "unenriched captured placeholder must still perform the first clipboard read")
    assert_equal(result.get("reason"), "clipboard_sequence_unchanged_after_copy", "test must reach the current-copy path rather than dedupe")


def check_router_returns_copy_failure_without_fallback() -> None:
    connector = ClipboardConnector(ok=False)
    result = router_module.maybe_route_customer_image_turn(
        connector=connector,
        target=_target(),
        config={},
        payload=_pending_payload(),
        target_state={},
        batch=[],
        combined="",
    )
    assert_equal(result.get("applied"), False, "failed current-copy transaction must not be adopted")
    assert_equal(result.get("reason"), "clipboard_sequence_unchanged_after_copy", "failure must remain explicit")
    assert_true("proxy_batch" not in result, "failed copy may not fall back to historical/crop proxy")


def check_self_image_context_is_text_only_and_never_reply_adoptable() -> None:
    connector = SelfClipboardConnector()
    original_understanding = router_module.maybe_run_customer_image_understanding
    try:
        def fake_understanding(**kwargs: Any) -> dict[str, Any]:
            payloads = kwargs.get("image_payloads") or []
            assert_equal(len(payloads), 1, "self image must use exactly one current clipboard payload")
            assert_true(not payloads[0].released, "self image stays in memory only until understanding completes")
            return {
                "applied": True,
                "adoptable": True,
                "reason": "vision_ready",
                "vision_summary": "客服发送了一张奥迪A4L外观图片",
                "source_messages": [{"message_id": "self-image-1", "message_type": "image"}],
            }

        router_module.maybe_run_customer_image_understanding = fake_understanding
        result = router_module.maybe_capture_self_image_context(
            connector=connector,
            target=_target(),
            config={},
            messages=[
                {
                    "id": "self-image-1",
                    "message_id": "self-image-1",
                    "type": "image",
                    "sender": "self",
                    "visual_side": "self",
                    "content": "[图片]",
                }
            ],
            target_state={},
        )
    finally:
        router_module.maybe_run_customer_image_understanding = original_understanding
    assert_true(result.get("applied") is True and result.get("context_only") is True, f"self image should produce context only: {result}")
    assert_true("proxy_batch" not in result and "visual_bridge_input" not in result, "self image must not become a customer reply turn")
    assert_equal((result.get("enrichment") or {}).get("message_refs"), [{"message_id": "self-image-1"}], "self vision text must bind to its own chat record")
    assert_true(connector.image is not None and connector.image.released, "self clipboard image bytes must be released")
    assert_no_path_or_bytes(result)


def assert_no_path_or_bytes(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert_true("path" not in str(key).lower(), f"result leaked path key {key}: {value}")
            assert_true("bytes" not in str(key).lower(), f"result leaked byte key {key}: {value}")
            assert_no_path_or_bytes(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_no_path_or_bytes(item)
    elif isinstance(value, (bytes, bytearray, memoryview)):
        raise AssertionError("result leaked binary image data")


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
