from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    ManagedListenerSchedulerBridge,
    _planner_customer_image_enrichment,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_session_ledger import (  # noqa: E402
    SessionLedgerStore,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (  # noqa: E402
    SchedulerStateStore,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.projection.message import (  # noqa: E402
    build_brain_safe_image_proxy_message,
)


def main() -> int:
    checks = [
        test_retired_asset_collection_export_is_absent,
        test_text_only_vision_result_can_be_bound_to_the_current_turn,
        test_ledger_keeps_textual_vision_summary_without_image_path,
        test_customer_image_vision_text_is_bound_and_exposed_to_history_context,
        test_scheduler_self_image_context_callback_persists_without_reply_work,
        test_scheduler_structural_self_image_is_context_only_and_bound,
        test_legacy_ledger_and_scheduler_state_are_scrubbed_on_read_and_write,
    ]
    for test in checks:
        test()
        print(f"PASS {test.__name__}")
    return 0


def test_retired_asset_collection_export_is_absent() -> None:
    assert_true(
        not globals().get("maybe_collect_customer_image_assets"),
        "retired path-based image collector must not be imported",
    )
    proxy = build_brain_safe_image_proxy_message(
        {"message_id": "clipboard-current", "content": "[图片]"},
        target_name="Customer A",
        session_key="wx:current-image",
    )
    assert_equal(proxy.get("source"), "clipboard_current_transaction", "current Vision proxy remains available")


def test_text_only_vision_result_can_be_bound_to_the_current_turn() -> None:
    capture = {
        "customer_image_assets": {"assets": [], "messages": []},
        "messages": [
            {
                "id": "clipboard_image_pending:one",
                "message_id": "clipboard_image_pending:one",
                "type": "text",
                "sender": "customer",
                "pending_signal_id": "image-one",
                "image_capture_pending": True,
                "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
            }
        ],
    }
    result = {
        "event": {
            "customer_image_turn": {
                "source_reason": "clipboard_current_transaction",
                "customer_image_understanding": {
                    "applied": True,
                    "vision_summary": "recognized vehicle",
                    "source_messages": [{"message_id": "image-one", "message_type": "image"}],
                },
            }
        }
    }
    enrichment = _planner_customer_image_enrichment(capture, result)
    assert_equal(enrichment.get("modality"), "image", "textual vision result remains image-scoped")
    assert_equal((enrichment.get("image_understanding") or {}).get("vision_summary"), "recognized vehicle", "only textual understanding is retained")
    encoded = json.dumps(enrichment, ensure_ascii=False)
    assert_true("saved_image_path" not in encoded and "image_bytes" not in encoded, "planner enrichment must not contain image storage data")


def test_ledger_keeps_textual_vision_summary_without_image_path() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:clipboard-text"
        message = {
            "id": "clipboard_image_pending:one",
            "type": "text",
            "sender": "customer",
            "content": "customer sent an image",
            "pending_signal_id": "image-one",
            "image_capture_pending": True,
            "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
            "saved_image_path": "C:/must-not-persist.png",
        }
        ledger.record_capture(
            session_key=session_key,
            target_name="Customer A",
            conversation_type="private",
            capture_id="capture-one",
            messages=[message],
            batch=[message],
            history_backfill={},
            context_version=1,
        )
        summary = ledger.load_summary(session_key)
        recent = summary.get("recent_messages") or []
        assert_true(recent and "saved_image_path" not in recent[0], f"ledger must strip retired image paths: {recent}")
        assert_equal(recent[0].get("pending_signal_id"), "image-one", "dedupe/audit signal should remain")


def test_customer_image_vision_text_is_bound_and_exposed_to_history_context() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:customer-image-history"
        placeholder = {
            "id": "clipboard_image_pending:customer-one",
            "message_id": "clipboard_image_pending:customer-one",
            "type": "text",
            "sender": "customer",
            "content": "客户发来了一张图片",
            "pending_signal_id": "customer-image-one",
            "image_capture_pending": True,
            "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
        }
        ledger.record_capture(
            session_key=session_key,
            target_name="Customer A",
            conversation_type="private",
            capture_id="capture-customer-image",
            messages=[placeholder],
            batch=[placeholder],
            history_backfill={},
            context_version=1,
        )
        capture = {"customer_image_assets": {"assets": [], "messages": []}, "messages": [placeholder]}
        planner_result = {
            "event": {
                "customer_image_turn": {
                    "source_reason": "clipboard_current_transaction",
                    "customer_image_understanding": {
                        "applied": True,
                        "vision_summary": "客户发送了一张奥迪A4L外观图片",
                        "source_messages": [{"message_id": "customer-image-one", "message_type": "image"}],
                    },
                }
            }
        }
        enrichment = _planner_customer_image_enrichment(capture, planner_result)
        persisted = ledger.record_multimodal_enrichment(
            session_key=session_key,
            target_name="Customer A",
            capture_id="capture-customer-image",
            source="customer_image_planner",
            enrichments=[enrichment],
        )
        summary = ledger.load_summary(session_key)
    recent = summary.get("recent_messages") or []
    assert_equal(persisted.get("updated_count"), 1, "customer image understanding must bind to the text placeholder")
    assert_equal(recent[0].get("modality"), "image", "placeholder must become an image-context record")
    assert_equal(recent[0].get("vision_summary"), "客户发送了一张奥迪A4L外观图片", "vision text must persist in history")
    assert_true("奥迪A4L外观图片" in str(summary.get("context_summary") or ""), "future Brain context summary must include vision text")
    assert_equal(summary.get("processed_visual_pending_signal_ids"), ["customer-image-one"], "image signal becomes processed only after text enrichment")


def test_scheduler_self_image_context_callback_persists_without_reply_work() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:self-image-history"
        self_image = {
            "id": "self-image-one",
            "message_id": "self-image-one",
            "type": "image",
            "sender": "self",
            "content": "[图片]",
            "visual_side": "self",
        }
        ledger.record_capture(
            session_key=session_key,
            target_name="Customer A",
            conversation_type="private",
            capture_id="capture-self-image",
            messages=[self_image],
            batch=[],
            history_backfill={},
            context_version=1,
        )
        bridge_shell = SimpleNamespace(ledger=ledger, session_monitor=None)
        ManagedListenerSchedulerBridge._capture_done(
            bridge_shell,
            {"session_key": session_key, "target_name": "Customer A"},
            {
                "self_image_context": {
                    "applied": True,
                    "context_only": True,
                    "enrichment": {
                        "modality": "image",
                        "message_refs": [{"message_id": "self-image-one"}],
                        "image_understanding": {
                            "applied": True,
                            "vision_summary": "客服发送了一张车辆外观图",
                        },
                    },
                }
            },
            {"session_key": session_key, "target_name": "Customer A", "capture_id": "capture-self-image"},
        )
        summary = ledger.load_summary(session_key)
    recent = summary.get("recent_messages") or []
    assert_equal(recent[0].get("sender"), "self", "self image stays a self-side history message")
    assert_equal(recent[0].get("vision_summary"), "客服发送了一张车辆外观图", "self image text must persist")
    assert_true("客服发送了一张车辆外观图" in str(summary.get("context_summary") or ""), "future Brain context must retain the self image description")


def test_scheduler_structural_self_image_is_context_only_and_bound() -> None:
    class SelfImageConnector:
        def get_messages(self, target: str, exact: bool = True, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "adapter": "win32_ocr",
                "state": "messages_ocr",
                "target": target,
                "exact": exact,
                "messages": [
                    {
                        "id": "visual_self_context_surface_one",
                        "message_id": "visual_self_context_surface_one",
                        "type": "image",
                        "message_type": "image",
                        "sender": "self",
                        "sender_role": "self",
                        "visual_side": "self",
                        "visual_turn_kind": "self_image",
                        "is_self_image": True,
                        "content": "[图片]",
                        "time": "05:38",
                        "source_adapter": "win32_ocr_structural_image_observer",
                    }
                ],
            }

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        config_path = root / "listener_config.json"
        config_path.write_text(
            json.dumps(
                {
                    "state_path": str(root / "workflow_state.json"),
                    "audit_log_path": str(root / "audit.jsonl"),
                    "targets": [{"name": "Customer A", "enabled": True, "exact": True}],
                    "history_backfill": {"enabled": False},
                    "raw_messages": {"enabled": False},
                    "customer_profiles": {"enabled": False},
                    "voice_transcription": {"enabled": False},
                    "concurrency_scheduler": {"enabled": True},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bridge = ManagedListenerSchedulerBridge(
            tenant_id="unit_structural_self_context",
            config_path=config_path,
            allow_send=False,
            write_data=False,
        )
        bridge.ledger = SessionLedgerStore(tenant_id="unit_structural_self_context", root=root / "ledger")
        bridge.connector = SelfImageConnector()
        bridge.session_monitor = SimpleNamespace(
            all_sessions=lambda: [
                {
                    "name": "Customer A",
                    "session_key": "wx:self-structural",
                    "pending_signal_id": "self-image-signal-one",
                    "pending_signal_kind": "image_capture",
                    "pending_signal_text": "[图片]",
                    "preview_content": "[图片]",
                }
            ]
        )

        observed: dict[str, Any] = {}

        def fake_self_context(**kwargs: Any) -> dict[str, Any]:
            observed.update(kwargs)
            message = (kwargs.get("messages") or [])[0]
            return {
                "enabled": True,
                "applied": True,
                "context_only": True,
                "reason": "self_image_context_ready",
                "enrichment": {
                    "modality": "image",
                    "message_refs": [{"message_id": message.get("message_id")}],
                    "image_understanding": {
                        "applied": True,
                        "vision_summary": "客服发送了一张小女孩穿艾莎裙的照片",
                    },
                },
            }

        bridge._workflow["maybe_capture_self_image_context"] = fake_self_context
        try:
            result = bridge._capture_session(
                {
                    "target_name": "Customer A",
                    "name": "Customer A",
                    "exact": True,
                    "conversation_type": "private",
                    "session_key": "wx:self-structural",
                }
            )
            assert_equal(result.get("batch"), [], "self image must not enter the customer reply batch")
            assert_true(result.get("pending_signal_consumed") is False, "customer image event must not be consumed by a visible old self image")
            assert_true(not any(item.get("is_customer_image_proxy") for item in (result.get("messages") or [])), "self image must not create a customer proxy")
            assert_true(not observed, "self context must not run unless the customer explicitly asks about a self image")
        finally:
            bridge.shutdown()


def test_legacy_ledger_and_scheduler_state_are_scrubbed_on_read_and_write() -> None:
    legacy_path = "C:/retired-capture.png"
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        ledger = SessionLedgerStore(tenant_id="test", root=root / "ledgers")
        session_key = "wx:legacy-state"
        summary_path = ledger.summary_path(session_key)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            json.dumps(
                {
                    "recent_messages": [
                        {
                            "content": "customer sent an image",
                            "saved_image_path": legacy_path,
                            "image_assets": ["asset-old"],
                            "image_understanding": {"vision_summary": "a vehicle dashboard"},
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        restored = ledger.load_summary(session_key)
        encoded_restored = json.dumps(restored, ensure_ascii=False)
        assert_true(legacy_path not in encoded_restored and "image_assets" not in encoded_restored, "legacy ledger data must be inert on read")
        assert_equal(
            restored["recent_messages"][0]["image_understanding"]["vision_summary"],
            "a vehicle dashboard",
            "textual understanding remains available",
        )
        ledger.append_event(session_key, "legacy_replay", {"nested": {"saved_image_path": legacy_path}})
        assert_true(legacy_path not in ledger.events_path(session_key).read_text(encoding="utf-8"), "events may not persist legacy paths")

        state_store = SchedulerStateStore(tenant_id="test", path=root / "scheduler_state.json")
        state = state_store.empty_state()
        state["captures"] = {"capture-old": {"messages": [{"saved_image_path": legacy_path, "content": "old"}]}}
        state_store.save(state)
        raw_state = (root / "scheduler_state.json").read_text(encoding="utf-8")
        restored_state = state_store.load()
        assert_true(legacy_path not in raw_state, "scheduler state may not write legacy paths")
        assert_true(legacy_path not in json.dumps(restored_state, ensure_ascii=False), "scheduler state may not expose legacy paths")


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
