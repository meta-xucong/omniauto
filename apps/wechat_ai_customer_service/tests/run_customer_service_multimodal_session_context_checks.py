from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows", APP_ROOT / "adapters"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (
    CustomerServiceSchedulerRuntime,
    ManagedListenerSchedulerBridge,
    _merge_voice_transcription_messages,
    _planner_customer_image_enrichment,
    _voice_transcription_audit_messages,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (
    SchedulerConfig,
    SchedulerStateStore,
    enqueue_media_context_task,
    enqueue_pending_session,
    mark_media_context_started,
    record_capture_result,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_session_ledger import (
    SessionLedgerStore,
    stable_session_key,
)
from apps.wechat_ai_customer_service.admin_backend.services.session_monitor import SessionMonitor, SessionState
from apps.wechat_ai_customer_service.workflows.customer_image_asset_store import (
    maybe_collect_customer_image_assets,
)


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def test_ledger_preserves_both_side_multimodal_envelopes() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:rpa:v1:test-multimodal"
        messages = [
            {
                "id": "customer-text",
                "sender": "customer",
                "sender_role": "group_member",
                "type": "text",
                "content": "客户文字",
                "speaker_name": "许聪",
            },
            {
                "id": "self-text",
                "sender": "self",
                "sender_role": "self",
                "type": "text",
                "content": "客服人工文字",
            },
            {
                "id": "customer-voice",
                "sender": "customer",
                "sender_role": "customer",
                "type": "text",
                "content": "客户语音正文",
                "source_type": "voice_transcription",
                "voice_transcribed": True,
            },
            {
                "id": "self-voice",
                "sender": "self",
                "sender_role": "self",
                "type": "text",
                "content": "客服语音正文",
                "source_type": "voice_transcription",
                "voice_transcribed": True,
            },
            {
                "id": "customer-image",
                "sender": "customer",
                "sender_role": "customer",
                "type": "image",
                "content": "[图片]",
                "asset_id": "asset-customer",
                "visual_side": "customer",
                "saved_image_path": str(Path(temp_dir) / "customer.png"),
            },
            {
                "id": "self-image",
                "sender": "self",
                "sender_role": "self",
                "type": "image",
                "content": "[图片]",
                "asset_id": "asset-self",
                "visual_side": "self",
                "saved_image_path": str(Path(temp_dir) / "self.png"),
            },
        ]
        ledger.record_capture(
            session_key=session_key,
            target_name="测试群",
            conversation_type="group",
            capture_id="capture-1",
            messages=messages,
            batch=[messages[0], messages[2], messages[4]],
            history_backfill={},
            context_version=1,
        )
        summary = ledger.load_summary(session_key)
        recent = summary.get("recent_messages") or []
        by_id = {item.get("id"): item for item in recent}
        assert_equal(by_id["customer-text"].get("sender_role"), "group_member", "group peer role should persist")
        assert_equal(by_id["self-text"].get("sender"), "self", "self text should persist")
        assert_equal(by_id["customer-voice"].get("modality"), "voice", "customer voice modality should persist")
        assert_equal(by_id["self-voice"].get("voice_transcription_text"), "客服语音正文", "self transcript should persist")

        customer_result = ledger.record_multimodal_enrichment(
            session_key=session_key,
            target_name="测试群",
            capture_id="capture-1",
            source="customer_image_planner",
            enrichments=[
                {
                    "modality": "image",
                    "message_refs": [{"asset_id": "asset-customer"}],
                    "image_understanding": {
                        "applied": True,
                        "vision_summary": "一辆白色奥迪 A4L",
                        "classification": {"is_vehicle": True},
                    },
                }
            ],
        )
        self_result = ledger.record_multimodal_enrichment(
            session_key=session_key,
            target_name="测试群",
            capture_id="capture-1",
            source="self_image_context_task",
            enrichments=[
                {
                    "modality": "image",
                    "message_refs": [{"asset_id": "asset-self"}],
                    "image_understanding": {
                        "applied": True,
                        "vision_summary": "客服发出的一张车辆报价截图",
                        "classification": {"is_vehicle": True},
                    },
                }
            ],
        )
        assert_equal(customer_result.get("updated_count"), 1, "customer image should enrich one source message")
        assert_equal(self_result.get("updated_count"), 1, "self image should enrich one source message")
        summary = ledger.load_summary(session_key)
        by_id = {item.get("id"): item for item in summary.get("recent_messages") or []}
        assert_equal(
            (by_id["customer-image"].get("image_understanding") or {}).get("vision_summary"),
            "一辆白色奥迪 A4L",
            "customer vision summary should use dedicated image_understanding field",
        )
        assert_equal(
            (by_id["self-image"].get("image_understanding") or {}).get("vision_summary"),
            "客服发出的一张车辆报价截图",
            "self vision summary should use the same field",
        )
        assert_true("一辆白色奥迪 A4L" in str(summary.get("context_summary") or ""), "vision summary should enter compact context")
        assert_true("客服发出的一张车辆报价截图" in str(summary.get("context_summary") or ""), "self vision summary should enter compact context")


def test_voice_duplicate_merge_keeps_both_side_transcription_provenance() -> None:
    payload = {
        "messages": [
            {"id": "voice-customer", "sender": "customer", "sender_role": "customer", "type": "text", "content": "客户说想看车"},
            {"id": "voice-self", "sender": "self", "sender_role": "self", "type": "text", "content": "我说稍后发资料"},
        ]
    }
    voice_transcription = {
        "attempted": True,
        "ok": True,
        "state": "voice_transcription_completed",
        "new_messages": [
            {"id": "voice-customer", "sender": "customer", "sender_role": "customer", "type": "text", "content": "客户说想看车"},
            {"id": "voice-self", "sender": "self", "sender_role": "self", "type": "text", "content": "我说稍后发资料"},
        ],
    }
    merged = _merge_voice_transcription_messages(payload, voice_transcription)
    assert_equal(len(merged.get("messages") or []), 2, "duplicate transcript OCR should not append duplicate messages")
    assert_equal((merged.get("voice_transcription_merge") or {}).get("annotated_existing_count"), 2, "both messages should be annotated")
    for message in merged.get("messages") or []:
        assert_equal(message.get("source_type"), "voice_transcription", "voice provenance should survive duplicate merge")
        assert_equal(message.get("modality"), "voice", "voice modality should survive duplicate merge")
        assert_true(message.get("voice_transcription_text"), "voice transcript body should be retained")
    audit = _voice_transcription_audit_messages(merged.get("messages") or [])
    assert_equal(len(audit), 2, "both-side transcript bodies should be auditable")
    assert_equal({item.get("sender") for item in audit}, {"customer", "self"}, "audit should preserve both speakers")


def test_customer_image_asset_collection_excludes_self_history() -> None:
    payload = {
        "messages": [
            {"id": "customer-image", "sender": "customer", "visual_side": "customer", "saved_image_path": "customer.png"},
            {"id": "self-image", "sender": "self", "visual_side": "self", "saved_image_path": "self.png"},
        ],
        "customer_image_assets": {
            "ok": True,
            "assets": [
                {"message_id": "customer-image", "asset_id": "asset-customer", "sender": "customer", "visual_side": "customer", "saved_image_path": "customer.png"}
            ],
            "messages": [
                {"id": "customer-image", "message_id": "customer-image", "sender": "customer", "visual_side": "customer", "saved_image_path": "customer.png"}
            ],
        },
    }
    collected = maybe_collect_customer_image_assets(
        object(),
        target_name="测试会话",
        exact=True,
        session_key="session-customer-only",
        payload=payload,
        target_state={},
    )
    assert_equal(collected.get("reason"), "scheduler_customer_image_assets_ready", "scheduler customer scope should win")
    assert_equal(len(collected.get("assets") or []), 1, "self history image must not enter customer vision request")
    assert_equal((collected.get("assets") or [{}])[0].get("message_id"), "customer-image", "customer image should remain")
    legacy_collected = maybe_collect_customer_image_assets(
        object(),
        target_name="测试会话",
        exact=True,
        session_key="session-customer-only",
        payload={"messages": payload["messages"]},
        target_state={},
    )
    assert_equal(len(legacy_collected.get("assets") or []), 1, "legacy payload path should also exclude self images")
    assert_equal((legacy_collected.get("assets") or [{}])[0].get("message_id"), "customer-image", "legacy path should retain only customer image")


def test_planner_image_result_builds_source_bound_enrichment() -> None:
    capture = {
        "customer_image_assets": {
            "assets": [
                {"message_id": "customer-image", "asset_id": "asset-customer", "saved_image_path": "customer.png"}
            ]
        },
        "messages": [
            {"id": "customer-image", "sender": "customer", "visual_side": "customer", "type": "image", "asset_id": "asset-customer"}
        ],
    }
    result = {
        "event": {
            "customer_image_turn": {
                "source_reason": "direct_image_message",
                "customer_image_understanding": {
                    "applied": True,
                    "vision_summary": "一辆蔚来 ES6",
                    "source_messages": [{"message_id": "customer-image", "asset_id": "asset-customer"}],
                },
            }
        }
    }
    enrichment = _planner_customer_image_enrichment(capture, result)
    assert_equal(enrichment.get("modality"), "image", "planner enrichment should be image-scoped")
    assert_equal((enrichment.get("image_understanding") or {}).get("vision_summary"), "一辆蔚来 ES6", "vision result should be retained")
    refs = enrichment.get("message_refs") or []
    assert_true(any(item.get("asset_id") == "asset-customer" for item in refs), "enrichment must bind to source asset")


def test_managed_bridge_persists_customer_planner_image_semantics() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:rpa:v1:customer-image-planner"
        source_message = {
            "id": "planner-image-source",
            "message_id": "planner-image-source",
            "sender": "customer",
            "sender_role": "customer",
            "visual_side": "customer",
            "type": "image",
            "content": "[图片]",
            "asset_id": "planner-image-asset",
            "saved_image_path": str(Path(temp_dir) / "planner.png"),
        }
        ledger.record_capture(
            session_key=session_key,
            target_name="客户图片会话",
            conversation_type="private",
            capture_id="planner-capture",
            messages=[source_message],
            batch=[],
            history_backfill={},
            context_version=1,
        )
        bridge = object.__new__(ManagedListenerSchedulerBridge)
        bridge.ledger = ledger
        bridge._planner_done(
            {
                "capture_id": "planner-capture",
                "session_key": session_key,
                "target_name": "客户图片会话",
                "messages": [source_message],
                "customer_image_assets": {"assets": [source_message], "messages": [source_message]},
            },
            {},
            {
                "event": {
                    "customer_image_turn": {
                        "source_reason": "direct_image_message",
                        "customer_image_understanding": {
                            "applied": True,
                            "vision_summary": "一辆白色丰田凌派",
                            "source_messages": [{"message_id": "planner-image-source", "asset_id": "planner-image-asset"}],
                        },
                    }
                }
            },
        )
        summary = ledger.load_summary(session_key)
        recent = summary.get("recent_messages") or []
        assert_equal(
            ((recent[0].get("image_understanding") or {}).get("vision_summary") if recent else ""),
            "一辆白色丰田凌派",
            "managed bridge planner callback should persist customer image semantics",
        )


def test_self_image_context_task_never_creates_reply_work() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        state_path = Path(temp_dir) / "scheduler.json"
        store = SchedulerStateStore(tenant_id="test", path=state_path)
        state = store.empty_state()
        enqueue_pending_session(
            state,
            "自方图片会话",
            session_key="wx:rpa:v1:self-image",
            conversation_type="private",
        )
        store.save(state)
        planner_calls: list[str] = []
        ledger = SessionLedgerStore(tenant_id="test", root=store.ledger_root)

        def capture_fn(_session: dict[str, Any]) -> dict[str, Any]:
            return {
                "ok": True,
                "session_key": "wx:rpa:v1:self-image",
                "messages": [
                    {
                        "id": "self-image-only",
                        "message_id": "self-image-only",
                        "sender": "self",
                        "sender_role": "self",
                        "visual_side": "self",
                        "type": "image",
                        "content": "[图片]",
                        "asset_id": "self-asset-only",
                        "saved_image_path": str(Path(temp_dir) / "self-only.png"),
                    }
                ],
                "batch": [],
                "batch_authoritative": True,
            }

        def planner_fn(_capture: dict[str, Any], _task: dict[str, Any]) -> dict[str, Any]:
            planner_calls.append("called")
            return {"ok": True, "reply_text": "不应生成"}

        def media_fn(task: dict[str, Any]) -> dict[str, Any]:
            asset = task.get("image_asset") or {}
            return {
                "ok": True,
                "reason": "self_image_context_understood",
                "message_refs": [{"asset_id": asset.get("asset_id"), "message_id": asset.get("message_id")}],
                "image_understanding": {
                    "applied": True,
                    "vision_summary": "我方发送的一张车辆资料图",
                    "classification": {"is_vehicle": True},
                },
            }

        def media_done(task: dict[str, Any], result: dict[str, Any]) -> None:
            persisted = ledger.record_multimodal_enrichment(
                session_key=str(task.get("session_key") or ""),
                target_name=str(task.get("target_name") or ""),
                capture_id=str(task.get("capture_id") or ""),
                source="self_image_context_task",
                enrichments=[
                    {
                        "modality": "image",
                        "message_refs": result.get("message_refs") or [],
                        "image_understanding": result.get("image_understanding") or {},
                    }
                ],
            )
            assert_equal(persisted.get("updated_count"), 1, "self image semantic result should update the source ledger message")

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True),
            capture_fn=capture_fn,
            plan_reply_fn=planner_fn,
            media_context_fn=media_fn,
            media_context_done_fn=media_done,
        )
        try:
            for _index in range(20):
                runtime.tick(allow_send=False)
                current = store.load()
                tasks = current.get("media_context_tasks") or {}
                if tasks and all(item.get("status") == "completed" for item in tasks.values()):
                    break
                time.sleep(0.01)
        finally:
            runtime.shutdown()
        current = store.load()
        assert_equal(planner_calls, [], "self-only image must not enqueue Brain reply planning")
        assert_equal(current.get("llm_tasks") or {}, {}, "self-only image must not create LLM reply tasks")
        assert_equal(current.get("ready_replies") or {}, {}, "self-only image must not create ready replies")
        media_tasks = current.get("media_context_tasks") or {}
        assert_true(media_tasks, "self-only image should create a context enrichment task")
        assert_true(all(item.get("status") == "completed" for item in media_tasks.values()), f"media context task should complete: {media_tasks}")
        summary = ledger.load_summary("wx:rpa:v1:self-image")
        recent = summary.get("recent_messages") or []
        assert_equal(
            ((recent[0].get("image_understanding") or {}).get("vision_summary") if recent else ""),
            "我方发送的一张车辆资料图",
            "self image semantics should be durable",
        )


def test_orphaned_self_image_context_task_recovers_after_restart() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        store = SchedulerStateStore(tenant_id="test", path=Path(temp_dir) / "scheduler.json")
        state = store.empty_state()
        image_message = {
            "id": "restart-self-image",
            "message_id": "restart-self-image",
            "sender": "self",
            "sender_role": "self",
            "visual_side": "self",
            "type": "image",
            "content": "[图片]",
            "asset_id": "restart-self-asset",
            "saved_image_path": str(Path(temp_dir) / "restart-self.png"),
        }
        capture = record_capture_result(
            state,
            "重启恢复会话",
            messages=[image_message],
            batch=[],
            conversation_type="private",
            session_key="wx:rpa:v1:restart-self-image",
        )
        task = enqueue_media_context_task(
            state,
            str(capture.get("capture_id") or ""),
            image_asset=image_message,
        )
        mark_media_context_started(state, str(task.get("task_id") or ""))
        store.save(state)
        ledger = SessionLedgerStore(tenant_id="test", root=store.ledger_root)

        def media_done(recovered_task: dict[str, Any], result: dict[str, Any]) -> None:
            persisted = ledger.record_multimodal_enrichment(
                session_key=str(recovered_task.get("session_key") or ""),
                target_name=str(recovered_task.get("target_name") or ""),
                capture_id=str(recovered_task.get("capture_id") or ""),
                source="self_image_context_task",
                enrichments=[
                    {
                        "modality": "image",
                        "message_refs": result.get("message_refs") or [],
                        "image_understanding": result.get("image_understanding") or {},
                    }
                ],
            )
            assert_equal(persisted.get("updated_count"), 1, "recovered task should persist to its source message")

        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True),
            capture_fn=lambda _session: {"ok": True, "messages": [], "batch": [], "batch_authoritative": True},
            plan_reply_fn=lambda _capture, _task: {"ok": False, "reason": "not_expected"},
            media_context_fn=lambda recovered_task: {
                "ok": True,
                "message_refs": [{"asset_id": (recovered_task.get("image_asset") or {}).get("asset_id")}],
                "image_understanding": {"vision_summary": "重启后恢复的我方图片语义"},
            },
            media_context_done_fn=media_done,
        )
        try:
            for _index in range(20):
                runtime.tick(allow_send=False)
                current = store.load()
                current_task = (current.get("media_context_tasks") or {}).get(task.get("task_id")) or {}
                if current_task.get("status") == "completed":
                    break
                time.sleep(0.01)
        finally:
            runtime.shutdown()
        current_task = ((store.load().get("media_context_tasks") or {}).get(task.get("task_id")) or {})
        assert_equal(current_task.get("status"), "completed", "orphaned media task should be recovered and completed")
        summary = ledger.load_summary("wx:rpa:v1:restart-self-image")
        assert_true("重启后恢复的我方图片语义" in str(summary.get("context_summary") or ""), "recovered semantics should enter context")


class _SessionListConnector:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self.sessions = sessions

    def list_sessions(self) -> dict[str, Any]:
        return {"ok": True, "sessions": self.sessions}


def test_unique_display_name_reuses_session_key_across_type_drift() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        monitor = SessionMonitor(
            tenant_id="test",
            state_path=Path(temp_dir) / "monitor.json",
            whitelist={"新数据测试"},
            initial_preview_can_raise_unread=True,
        )
        monitor._ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        monitor.poll(
            _SessionListConnector(
                [{"name": "新数据测试", "content": "第一条", "time": "10:00", "conversation_type": "group"}]
            )
        )
        first_sessions = monitor.all_sessions()
        assert_equal(len(first_sessions), 1, "first unique session should create one identity")
        first_key = first_sessions[0].get("session_key")
        monitor.reset_unread(str(first_key or ""))
        monitor.poll(
            _SessionListConnector(
                [{"name": "新数据测试", "content": "第二条", "time": "10:01", "conversation_type": "private"}]
            )
        )
        second_sessions = monitor.all_sessions()
        assert_equal(len(second_sessions), 1, "inferred type drift must not split a unique display name")
        assert_equal(second_sessions[0].get("session_key"), first_key, "unique display name should retain its original session key")


def test_historical_type_split_merges_context_into_canonical_session() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        monitor = SessionMonitor(
            tenant_id="test",
            state_path=Path(temp_dir) / "monitor.json",
            whitelist={"新数据测试"},
        )
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        monitor._ledger = ledger
        group_key = stable_session_key("新数据测试", conversation_type="group")
        private_key = stable_session_key("新数据测试", conversation_type="private")
        monitor._sessions = {
            group_key: SessionState(name="新数据测试", session_key=group_key, conversation_type="group", first_seen_at="2026-07-10T09:00:00"),
            private_key: SessionState(name="新数据测试", session_key=private_key, conversation_type="private", first_seen_at="2026-07-10T09:10:00"),
        }
        ledger.record_capture(
            session_key=group_key,
            target_name="新数据测试",
            conversation_type="group",
            capture_id="group-capture",
            messages=[{"id": "group-history", "sender": "customer", "type": "text", "content": "群类型历史内容"}],
            batch=[],
            history_backfill={},
            context_version=1,
        )
        ledger.record_capture(
            session_key=private_key,
            target_name="新数据测试",
            conversation_type="private",
            capture_id="private-capture",
            messages=[{"id": "private-history", "sender": "self", "type": "text", "content": "私聊类型历史内容"}],
            batch=[],
            history_backfill={},
            context_version=1,
        )
        monitor.poll(
            _SessionListConnector(
                [{"name": "新数据测试", "content": "当前消息", "time": "10:02", "conversation_type": "private"}]
            )
        )
        sessions = monitor.all_sessions()
        assert_equal(len(sessions), 1, "historical inferred-type split should collapse for a uniquely visible name")
        canonical_key = str(sessions[0].get("session_key") or "")
        summary = ledger.load_summary(canonical_key)
        contents = [str(item.get("content") or "") for item in summary.get("recent_messages") or []]
        assert_true("群类型历史内容" in contents, f"group alias context should be retained: {contents}")
        assert_true("私聊类型历史内容" in contents, f"private alias context should be retained: {contents}")
        assert_true(summary.get("merged_session_aliases"), "canonical ledger should record merged aliases")


def test_multimodal_enrichment_event_is_auditable() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        ledger = SessionLedgerStore(tenant_id="test", root=Path(temp_dir) / "ledgers")
        session_key = "wx:rpa:v1:audit"
        ledger.record_capture(
            session_key=session_key,
            target_name="审计会话",
            conversation_type="private",
            capture_id="capture-audit",
            messages=[{"id": "image-audit", "sender": "customer", "type": "image", "content": "[图片]", "asset_id": "asset-audit"}],
            batch=[],
            history_backfill={},
            context_version=1,
        )
        ledger.record_multimodal_enrichment(
            session_key=session_key,
            target_name="审计会话",
            capture_id="capture-audit",
            source="customer_image_planner",
            enrichments=[
                {
                    "modality": "image",
                    "message_refs": [{"asset_id": "asset-audit"}],
                    "image_understanding": {"vision_summary": "审计识图摘要", "reason": "ok"},
                }
            ],
        )
        events = [
            json.loads(line)
            for line in ledger.events_path(session_key).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        enrichment_events = [item for item in events if item.get("event_type") == "multimodal_context_enriched"]
        assert_true(enrichment_events, "multimodal enrichment should append an audit event")
        assert_equal(enrichment_events[-1].get("updated_count"), 1, "audit event should report the updated source message")
        assert_equal((enrichment_events[-1].get("enrichments") or [{}])[0].get("vision_summary"), "审计识图摘要", "audit should retain compact vision summary")


def main() -> int:
    tests = [
        test_ledger_preserves_both_side_multimodal_envelopes,
        test_voice_duplicate_merge_keeps_both_side_transcription_provenance,
        test_customer_image_asset_collection_excludes_self_history,
        test_planner_image_result_builds_source_bound_enrichment,
        test_managed_bridge_persists_customer_planner_image_semantics,
        test_self_image_context_task_never_creates_reply_work,
        test_orphaned_self_image_context_task_recovers_after_restart,
        test_unique_display_name_reuses_session_key_across_type_drift,
        test_historical_type_split_merges_context_into_canonical_session,
        test_multimodal_enrichment_event_is_auditable,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"All {len(tests)} unified multimodal session context checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
