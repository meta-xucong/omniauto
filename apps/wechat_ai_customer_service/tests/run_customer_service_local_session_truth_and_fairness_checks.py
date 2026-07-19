from __future__ import annotations

import inspect
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (
    CustomerServiceSchedulerRuntime,
    ManagedListenerSchedulerBridge,
    _remove_preview_only_synthetic_reply_inputs,
    mark_session_capture_failed,
    recover_pending_signal_batch_from_monitor,
)
from apps.wechat_ai_customer_service.admin_backend.services.bootstrap_scheduler_handoff import (
    bootstrap_row_has_current_unread_evidence,
    queue_verified_bootstrap_capture,
    resolve_unique_bootstrap_session_row,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (
    SchedulerConfig,
    SchedulerStateStore,
)
from apps.wechat_ai_customer_service.admin_backend.services.session_monitor import (
    SessionMonitor,
    SessionState,
    _normalized_preview_fragment,
)
from apps.wechat_ai_customer_service.admin_backend.services.session_runtime_reconciliation import (
    ACKNOWLEDGE,
    DEFER,
    ELIGIBLE,
    capture_observation_disposition,
    reconcile_stale_scheduler_pending_at_startup,
)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def assert_true(condition: Any, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def target(name: str, session_key: str, observation_id: str, priority: int) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        session_key=session_key,
        exact=True,
        priority_score=priority,
        unread_detected=True,
        session_age_seconds=0,
        conversation_type="private",
        pending_signal_kind="normal",
        pending_signal_text=f"{name}的新消息",
        last_message_time="20:10",
        unread_badge="visual_red_dot",
        session_observation_id=observation_id,
        pending_observation_id=observation_id,
    )


def check_exact_observation_reconciliation() -> None:
    now = datetime.now()
    future = (now + timedelta(seconds=30)).isoformat(timespec="seconds")
    state = {
        "sessions": {
            "wx:rpa:v1:cooling": {
                "session_key": "wx:rpa:v1:cooling",
                "target_name": "异常候选A",
                "pending_observation_id": "observation-a",
                "status": "capture_cooldown",
                "pending_capture": True,
                "risk_state": {"capture_retry_not_before": future},
            },
            "wx:rpa:v1:terminal": {
                "session_key": "wx:rpa:v1:terminal",
                "target_name": "异常候选B",
                "pending_observation_id": "observation-b",
                "status": "capture_failed",
                "pending_capture": False,
                "risk_state": {},
            },
        }
    }
    disposition, retry_seconds = capture_observation_disposition(
        state,
        target_name="异常候选A",
        session_key="wx:rpa:v1:cooling",
        pending_observation_id="observation-a",
        now=now,
    )
    assert_equal(disposition, DEFER, "same cooling observation should be deferred")
    assert_true(retry_seconds > 0, "cooldown should expose a positive delay")
    disposition, _ = capture_observation_disposition(
        state,
        target_name="异常候选B",
        session_key="wx:rpa:v1:terminal",
        pending_observation_id="observation-b",
        now=now,
    )
    assert_equal(disposition, ACKNOWLEDGE, "same terminal observation should be acknowledged")
    disposition, _ = capture_observation_disposition(
        state,
        target_name="异常候选B",
        session_key="wx:rpa:v1:terminal",
        pending_observation_id="observation-new",
        now=now,
    )
    assert_equal(disposition, ELIGIBLE, "a genuinely new observation must receive a fresh chance")
    disposition, _ = capture_observation_disposition(
        state,
        target_name="同名但不同目标",
        session_key="wx:rpa:v1:terminal",
        pending_observation_id="observation-b",
        now=now,
    )
    assert_equal(disposition, ELIGIBLE, "name mismatch must fail closed instead of suppressing a target")


class SessionListConnector:
    def __init__(self, sessions: list[dict[str, Any]]) -> None:
        self.sessions = sessions

    def list_sessions(self) -> dict[str, Any]:
        return {"ok": True, "sessions": [dict(item) for item in self.sessions]}


def session_row(
    *,
    name: str = "客户A",
    session_key: str = "wx:rpa:v1:customer-a",
    content: str = "想看看这台车",
    message_time: str = "22:10",
    unread_badge: str = "",
    observation_id: str = "sidebar-observation-a",
) -> dict[str, Any]:
    return {
        "name": name,
        "session_key": session_key,
        "conversation_type": "private",
        "content": content,
        "time": message_time,
        "unread_badge": unread_badge,
        "unread_signal": bool(unread_badge),
        "session_observation_id": observation_id,
        "row_fingerprint": {"row_y_bucket": 12, "duplicate_discriminator": ""},
    }


def check_startup_monitor_reauthenticates_persisted_pending() -> None:
    with tempfile.TemporaryDirectory() as temp:
        stale = SessionMonitor(state_path=Path(temp) / "stale.json", short_preview_can_raise_unread=True)
        stale._sessions = {
            "wx:rpa:v1:customer-a": SessionState(
                name="客户A",
                session_key="wx:rpa:v1:customer-a",
                unread_detected=True,
                pending_since="2026-07-19T20:00:00",
                last_detected_at="2026-07-19T20:00:00",
                pending_signal_text="旧进程遗留预览",
                pending_signal_kind="normal",
                pending_observation_id="old-pending",
            )
        }
        stale._restored_session_keys_at_startup = {"wx:rpa:v1:customer-a"}
        active = stale.poll(SessionListConnector([session_row(content="短问", unread_badge="")]))
        assert_equal(active, [], "old pending without a current red dot must become startup baseline")
        assert_true(
            not stale._sessions["wx:rpa:v1:customer-a"].unread_detected,
            "startup baseline must close the old logical pending level",
        )

        current = SessionMonitor(state_path=Path(temp) / "current.json")
        current._sessions = {
            "wx:rpa:v1:customer-a": SessionState(
                name="客户A",
                session_key="wx:rpa:v1:customer-a",
                unread_detected=True,
                pending_since="2026-07-19T20:00:00",
                pending_signal_text="待回复",
                pending_observation_id="old-pending",
            )
        }
        active = current.poll(SessionListConnector([session_row(unread_badge="visual_red_dot")]))
        assert_equal(len(active), 1, "a current physical unread badge must survive startup reconciliation")

        fresh_runtime = SessionMonitor(state_path=Path(temp) / "fresh.json", short_preview_can_raise_unread=True)
        active = fresh_runtime.poll(SessionListConnector([session_row(content="在吗", unread_badge="")]))
        assert_equal(len(active), 1, "new-runtime short-message compatibility must remain unchanged")


def check_badge_event_identity_ignores_ocr_preview_jitter() -> None:
    with tempfile.TemporaryDirectory() as temp:
        monitor = SessionMonitor(
            state_path=Path(temp) / "monitor.json",
            preview_change_confirmations=2,
            preview_change_can_raise_unread=False,
        )
        key = "wx:rpa:v1:customer-a"
        first = session_row(
            session_key=key,
            content="许聪：这个车，我记得",
            unread_badge="visual_red_dot",
            observation_id="raw-observation-one",
        )
        assert_equal(len(monitor.poll(SessionListConnector([first]))), 1, "first current badge should dispatch")
        monitor.reset_unread(key)
        jitter = session_row(
            session_key=key,
            content="许聪：这个车，我记得。许聪：这个车，我记得。",
            unread_badge="visual_red_dot",
            observation_id="raw-observation-two",
        )
        assert_equal(monitor.poll(SessionListConnector([jitter])), [], "same badge epoch OCR jitter must stay acknowledged")
        assert_equal(monitor.poll(SessionListConnector([jitter])), [], "confirmation hits must not recreate the same badge event")
        no_badge = dict(jitter)
        no_badge["unread_badge"] = ""
        no_badge["unread_signal"] = False
        monitor.poll(SessionListConnector([no_badge]))
        repeated_new_turn = dict(first)
        repeated_new_turn["observation_id"] = "raw-observation-three"
        assert_equal(
            len(monitor.poll(SessionListConnector([repeated_new_turn]))),
            1,
            "a falling/rising badge edge must dispatch even when customer text repeats",
        )
        assert_equal(
            _normalized_preview_fragment("哈哈，您太客气啦。哈哈，您太客气啦。"),
            "哈哈，您太客气啦",
            "adjacent duplicated OCR preview should normalize generically",
        )


def check_ambiguous_historical_session_keys_do_not_merge() -> None:
    with tempfile.TemporaryDirectory() as temp:
        monitor = SessionMonitor(state_path=Path(temp) / "monitor.json")
        monitor._sessions = {
            "wx:rpa:v1:private": SessionState(name="同名会话", session_key="wx:rpa:v1:private", conversation_type="private"),
            "wx:rpa:v1:group": SessionState(name="同名会话", session_key="wx:rpa:v1:group", conversation_type="group"),
        }
        resolved = monitor._reuse_unique_display_name_session_key(
            "同名会话",
            candidate_session_key="wx:rpa:v1:current",
        )
        assert_equal(resolved, "wx:rpa:v1:current", "ambiguous aliases must keep the current derived key")
        assert_equal(len(monitor._sessions), 2, "ambiguous historical sessions must not be merged or deleted")


def check_scheduler_startup_closes_only_old_unauthenticated_pending() -> None:
    started = datetime(2026, 7, 19, 22, 0, 0)
    state = {
        "sessions": {
            "wx:rpa:v1:old": {
                "session_key": "wx:rpa:v1:old",
                "target_name": "旧遗留",
                "pending_capture": True,
                "pending_reason": "session_signal_changed",
                "pending_signal_has_unread_evidence": True,
                "last_detected_at": "2026-07-19T20:00:00",
                "status": "capture_pending",
                "risk_state": {"capture_retry_not_before": "2026-07-19T23:00:00"},
            },
            "wx:rpa:v1:current": {
                "session_key": "wx:rpa:v1:current",
                "target_name": "同名会话",
                "pending_capture": True,
                "last_detected_at": "2026-07-19T20:00:00",
                "status": "capture_pending",
            },
            "wx:rpa:v1:same-name-stale": {
                "session_key": "wx:rpa:v1:same-name-stale",
                "target_name": "同名会话",
                "pending_capture": True,
                "last_detected_at": "2026-07-19T20:00:00",
                "status": "capture_pending",
            },
            "wx:rpa:v1:bootstrap": {
                "session_key": "wx:rpa:v1:bootstrap",
                "target_name": "刚完成启动读取",
                "pending_capture": True,
                "last_detected_at": "2026-07-19T21:59:30",
                "status": "capture_pending",
            },
            "wx:rpa:v1:brain": {
                "session_key": "wx:rpa:v1:brain",
                "target_name": "已有Brain任务",
                "pending_capture": True,
                "last_detected_at": "2026-07-19T20:00:00",
                "llm_inflight_task_id": "task-running",
                "status": "llm_queued",
            },
            "旧格式显示名桶": {
                "session_key": "wx:rpa:v1:legacy-active",
                "target_name": "旧格式显示名桶",
                "pending_capture": True,
                "last_detected_at": "2026-07-19T20:00:00",
                "llm_inflight_task_id": "legacy-task-reference",
                "status": "llm_queued",
            },
        },
        "llm_tasks": {
            "task-running": {
                "task_id": "task-running",
                "session_key": "wx:rpa:v1:brain",
                "target_name": "已有Brain任务",
                "status": "queued",
            }
        },
        "polish_tasks": {},
        "media_context_tasks": {},
        "ready_replies": {},
    }
    closed = reconcile_stale_scheduler_pending_at_startup(
        state,
        current_pending_identifiers={"wx:rpa:v1:current"},
        runtime_started_at=started,
    )
    assert_equal(
        closed,
        ["wx:rpa:v1:old", "wx:rpa:v1:same-name-stale"],
        "only exact current keys and active work should survive startup reconciliation",
    )
    assert_true(not state["sessions"]["wx:rpa:v1:old"]["pending_capture"], "old scheduler pending must become idle")
    assert_true(
        not state["sessions"]["wx:rpa:v1:same-name-stale"]["pending_capture"],
        "a stale keyed session must not survive merely because its display name matches a current session",
    )
    assert_true(state["sessions"]["wx:rpa:v1:bootstrap"]["pending_capture"], "fresh bootstrap handoff must survive")
    assert_true(state["sessions"]["wx:rpa:v1:brain"]["pending_capture"], "active Brain work must survive")
    assert_true(
        state["sessions"]["旧格式显示名桶"]["pending_capture"],
        "legacy name-keyed state with an active in-session task reference must survive",
    )


def check_scheduler_startup_reconciliation_store_failure_stays_fail_closed() -> None:
    bridge = object.__new__(ManagedListenerSchedulerBridge)
    bridge._startup_pending_reconciliation_complete = False
    bridge._runtime_started_at = "2026-07-19T22:00:00"

    def fail_update(_mutate: Any) -> None:
        raise RuntimeError("simulated_scheduler_store_failure")

    bridge.store = SimpleNamespace(update=fail_update)
    failed = False
    try:
        bridge._reconcile_stale_scheduler_pending_once([])
    except RuntimeError as exc:
        failed = str(exc) == "simulated_scheduler_store_failure"
    assert_true(failed, "a failed startup state mutation must stop the listener tick")
    assert_true(
        not bridge._startup_pending_reconciliation_complete,
        "a failed startup state mutation must remain retryable and never unlock foreground work",
    )


def check_verified_bootstrap_capture_queues_existing_scheduler_contract() -> None:
    row = session_row(unread_badge="visual_red_dot")
    assert_true(bootstrap_row_has_current_unread_evidence(row), "test row should carry current unread evidence")
    resolved = resolve_unique_bootstrap_session_row({"ok": True, "sessions": [row]}, target_name="客户A")
    assert_equal(resolved.get("session_key"), row["session_key"], "bootstrap should bind the unique exact row")
    assert_equal(
        resolve_unique_bootstrap_session_row({"ok": True, "sessions": [row, row]}, target_name="客户A"),
        {},
        "duplicate display rows must fail closed",
    )
    messages = [
        {"id": "customer-1", "sender": "customer", "type": "text", "content": "第一条问题", "time": "22:10"},
        {"id": "customer-2", "sender": "customer", "type": "text", "content": "第二条追问", "time": "22:10"},
        {"id": "self-1", "sender": "self", "type": "text", "content": "历史我方消息", "time": "22:09"},
    ]
    with tempfile.TemporaryDirectory() as temp:
        store = SchedulerStateStore(tenant_id="bootstrap_handoff_probe", path=Path(temp) / "scheduler.json")
        first = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row=row,
            messages=messages,
            batch=messages[:2],
            llm_timeout_seconds=30,
        )
        state = store.load()
        assert_true(first.get("queued"), f"verified bootstrap capture should queue: {first}")
        assert_equal(len(state.get("llm_tasks") or {}), 1, "bootstrap should use the existing queued LLM task shape")
        task = next(iter((state.get("llm_tasks") or {}).values()))
        assert_equal(task.get("session_key"), row["session_key"], "bootstrap task must retain exact session identity")
        capture = (state.get("captures") or {}).get((task.get("capture_ids") or [""])[0]) or {}
        assert_equal(capture.get("message_ids"), ["customer-1", "customer-2"], "only real customer occurrences enter Brain")

        second = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row=row,
            messages=messages,
            batch=messages[:2],
            llm_timeout_seconds=30,
        )
        assert_true(second.get("queued"), "idempotent replay should recognize the active batch")
        assert_equal(len(store.load().get("llm_tasks") or {}), 1, "bootstrap replay must not create a duplicate task")

        third = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row={**row, "unread_badge": "", "unread_signal": False},
            messages=messages + [
                {"id": "customer-3", "sender": "customer", "type": "text", "content": "任务运行期间的新追问", "time": "22:11"}
            ],
            batch=[{"id": "customer-3", "sender": "customer", "type": "text", "content": "任务运行期间的新追问", "time": "22:11"}],
        )
        assert_true(not third.get("queued"), "a retry signal alone must not claim that a new customer batch was durably queued")
        assert_equal(
            third.get("reason"),
            "bootstrap_new_batch_deferred_behind_active_work",
            "active work should fail closed with an explicit handoff reason",
        )

    no_unread = dict(row)
    no_unread["unread_badge"] = ""
    no_unread["unread_signal"] = False
    with tempfile.TemporaryDirectory() as temp:
        store = SchedulerStateStore(tenant_id="bootstrap_no_unread_probe", path=Path(temp) / "scheduler.json")
        result = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row=no_unread,
            messages=messages,
            batch=messages[:2],
        )
        assert_true(result.get("queued"), "verified chat-pane customer occurrences must survive a cleared unread badge")
        assert_equal(len(store.load().get("llm_tasks") or {}), 1, "badgeless verified customer messages should enter Scheduler")

    with tempfile.TemporaryDirectory() as temp:
        store = SchedulerStateStore(tenant_id="bootstrap_no_batch_probe", path=Path(temp) / "scheduler.json")
        result = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row=no_unread,
            messages=[],
            batch=[],
        )
        assert_true(not result.get("queued"), "a badgeless empty bootstrap must remain a passive baseline")
        assert_equal(store.load().get("llm_tasks"), {}, "an empty badgeless bootstrap must not create a Brain task")

    with tempfile.TemporaryDirectory() as temp:
        store = SchedulerStateStore(tenant_id="bootstrap_media_probe", path=Path(temp) / "scheduler.json")
        result = queue_verified_bootstrap_capture(
            store,
            target_name="客户A",
            session_row=row,
            messages=[],
            batch=[],
        )
        session = store.load()["sessions"][row["session_key"]]
        assert_true(result.get("queued"), "current unread media without text should remain pending for live plugins")
        assert_true(session.get("pending_capture"), "media fallback must use the existing Scheduler capture pending contract")


class FakeMonitor:
    def __init__(self, pending: list[SimpleNamespace]) -> None:
        self._pending = list(pending)
        self.acknowledged: set[str] = set()
        self.deferred: set[str] = set()

    def poll(self, connector: Any) -> list[Any]:
        return list(self._pending)

    def pending_targets(self, *, limit: int | None = None) -> list[SimpleNamespace]:
        active = [
            item
            for item in self._pending
            if item.session_key not in self.acknowledged and item.session_key not in self.deferred
        ]
        if limit is None:
            return active
        return active[: max(0, int(limit))]

    def select_dispatch_targets(self, *, limit: int | None = None) -> list[SimpleNamespace]:
        return self.pending_targets(limit=limit)

    def reset_unread(self, identifier: str, *, preserve_pending: bool = False, retry_after_seconds: float | None = None) -> None:
        if not preserve_pending:
            self.acknowledged.add(identifier)

    def _defer_pending_until(self, identifier: str, *, retry_not_before: str) -> None:
        assert_true(bool(retry_not_before), "deferred observation should retain its deadline")
        self.deferred.add(identifier)


def check_failed_targets_yield_before_dispatch_cap() -> None:
    bad_terminal = target("异常候选A", "wx:rpa:v1:bad-terminal", "observation-a", 80)
    bad_cooling = target("异常候选B", "wx:rpa:v1:bad-cooling", "observation-b", 70)
    good_a = target("真实客户A", "wx:rpa:v1:good-a", "observation-c", 60)
    good_b = target("真实客户B", "wx:rpa:v1:good-b", "observation-d", 50)
    monitor = FakeMonitor([bad_terminal, bad_cooling, good_a, good_b])
    future = (datetime.now() + timedelta(seconds=60)).isoformat(timespec="seconds")
    scheduler_state = {
        "sessions": {
            bad_terminal.session_key: {
                "session_key": bad_terminal.session_key,
                "target_name": bad_terminal.name,
                "pending_observation_id": bad_terminal.pending_observation_id,
                "status": "capture_failed",
                "pending_capture": False,
                "risk_state": {},
            },
            bad_cooling.session_key: {
                "session_key": bad_cooling.session_key,
                "target_name": bad_cooling.name,
                "pending_observation_id": bad_cooling.pending_observation_id,
                "status": "capture_cooldown",
                "pending_capture": True,
                "risk_state": {"capture_retry_not_before": future},
            },
        },
        "llm_tasks": {},
        "polish_tasks": {},
        "ready_replies": {},
    }
    bridge = object.__new__(ManagedListenerSchedulerBridge)
    bridge.session_monitor = monitor
    bridge.connector = SimpleNamespace()
    bridge.scheduler_config = SimpleNamespace(capture_max_sessions_per_round=2, max_pending_sessions=30)
    bridge.ignored_session_names = set()
    bridge.respond_all_unread_sessions = False
    bridge._last_capture_switch_delay_seconds = 0.0
    bridge._last_capture_signal_target = ""
    bridge._scheduler_state_for_read = lambda: scheduler_state

    signals = bridge._collect_session_signals()
    assert_equal(
        [item.get("session_key") for item in signals],
        [good_a.session_key, good_b.session_key],
        "failed/cooling observations must not consume the bounded dispatch window",
    )
    assert_true(bad_terminal.session_key in monitor.acknowledged, "terminal observation should be closed in Monitor")
    assert_true(bad_cooling.session_key in monitor.deferred, "cooling observation should remain pending but ineligible")


def check_empty_capture_retry_is_content_agnostic_and_bounded() -> None:
    with tempfile.TemporaryDirectory() as temp:
        monitor = SessionMonitor(
            state_path=Path(temp) / "monitor.json",
            empty_capture_retry_seconds=0.0,
        )
        monitor._sessions = {
            "wx:rpa:v1:short": SessionState(
                name="客户A",
                session_key="wx:rpa:v1:short",
                unread_detected=True,
                pending_since="2026-07-19T20:00:00",
                pending_signal_text="在吗",
                pending_signal_kind="high_sensitivity_short",
                pending_observation_id="observation-short",
            )
        }
        assert_true(monitor.should_preserve_pending_after_empty_capture("wx:rpa:v1:short"), "first empty read should retry")
        monitor.reset_unread("wx:rpa:v1:short", preserve_pending=True, retry_after_seconds=0.0)
        assert_true(monitor.should_preserve_pending_after_empty_capture("wx:rpa:v1:short"), "second empty read should retry")
        monitor.reset_unread("wx:rpa:v1:short", preserve_pending=True, retry_after_seconds=0.0)
        assert_true(
            not monitor.should_preserve_pending_after_empty_capture("wx:rpa:v1:short"),
            "short preview must not receive an infinite empty-capture exception",
        )


def check_preview_only_synthetic_input_is_not_reply_authority() -> None:
    pending_signal = {
        "name": "客户A",
        "session_key": "wx:rpa:v1:preview-only",
        "unread_detected": True,
        "unread_badge": "visual_red_dot",
        "pending_signal_text": "客服上一条回复的截断和重复内容",
        "pending_signal_kind": "normal",
        "pending_since": datetime.now().isoformat(timespec="seconds"),
    }
    synthetic = recover_pending_signal_batch_from_monitor(
        [],
        pending_signal,
        target_name="客户A",
        now=datetime.now().isoformat(timespec="seconds"),
    )
    assert_true(bool(synthetic), "legacy compatibility helper should remain callable")
    assert_equal(
        _remove_preview_only_synthetic_reply_inputs(synthetic),
        [],
        "preview-only synthetic messages must not authorize a production reply",
    )
    actual = {"id": "chat-pane:1", "sender": "customer", "type": "text", "content": "真实的新消息"}
    assert_equal(
        _remove_preview_only_synthetic_reply_inputs([actual]),
        [actual],
        "a real chat-pane occurrence must remain reply-eligible",
    )
    capture_source = inspect.getsource(ManagedListenerSchedulerBridge._capture_session)
    assert_true(
        "recover_pending_signal_batch_from_monitor(" not in capture_source,
        "production capture must not synthesize Brain input from a sidebar preview",
    )


def check_runtime_empty_capture_retries_without_brain_task() -> None:
    with tempfile.TemporaryDirectory() as temp:
        store = SchedulerStateStore(tenant_id="local_truth_runtime", path=Path(temp) / "scheduler.json")
        runtime = CustomerServiceSchedulerRuntime(
            store=store,
            config=SchedulerConfig(enabled=True, capture_max_sessions_per_round=1),
            capture_fn=lambda _session: {
                "ok": True,
                "messages": [],
                "batch": [],
                "batch_authoritative": True,
                "pending_signal": {"pending_observation_id": "observation-empty"},
                "pending_signal_consumed": False,
            },
            plan_reply_fn=lambda _capture, _task: (_ for _ in ()).throw(
                AssertionError("Brain must not run for an empty chat-pane capture")
            ),
            freshness_fn=lambda _reply: {"stale": False},
            send_fn=lambda _reply: {"ok": True},
        )
        try:
            result = runtime.tick(
                session_signals=[
                    {
                        "name": "客户A",
                        "session_key": "wx:rpa:v1:empty-runtime",
                        "conversation_type": "private",
                        "content": "侧栏预览不是正文",
                        "time": "20:10",
                        "unread_badge": "visual_red_dot",
                        "unread_detected": True,
                        "pending_observation_id": "observation-empty",
                    }
                ],
                allow_send=False,
            )
            state = store.load()
        finally:
            runtime.shutdown()
        session = state["sessions"]["wx:rpa:v1:empty-runtime"]
        assert_equal((session.get("risk_state") or {}).get("capture_fail_count"), 1, "empty capture should consume one bounded retry")
        assert_true(bool(session.get("pending_capture")), "first empty capture should remain locally retryable")
        assert_equal(state.get("llm_tasks"), {}, "empty capture must not enqueue a Brain task")
        assert_true(any(item.get("event") == "capture_empty" for item in result.get("events") or []), "empty capture should remain auditable")


def check_scheduler_empty_capture_retry_is_terminal_at_limit() -> None:
    state: dict[str, Any] = {}
    for attempt in range(1, 4):
        mark_session_capture_failed(
            state,
            "客户A",
            "empty_capture_no_verified_message",
            session_key="wx:rpa:v1:empty-limit",
            now=f"2026-07-19T20:10:0{attempt}",
        )
        session = state["sessions"]["wx:rpa:v1:empty-limit"]
        assert_equal(
            (session.get("risk_state") or {}).get("capture_fail_count"),
            attempt,
            "the same empty observation should consume one retry per failed read",
        )
        if attempt < 3:
            assert_equal(session.get("status"), "capture_cooldown", "early empty reads should use bounded cooldown")
            assert_true(bool(session.get("pending_capture")), "early empty reads should remain retryable")
        else:
            assert_equal(session.get("status"), "capture_failed", "the retry limit should terminate the observation")
            assert_true(not bool(session.get("pending_capture")), "a terminal empty observation must leave the capture queue")
            assert_true(
                not str((session.get("risk_state") or {}).get("capture_retry_not_before") or "").strip(),
                "a terminal empty observation must not retain a future retry deadline",
            )


class CaptureDoneMonitor:
    def __init__(self) -> None:
        self.preserve_calls: list[bool] = []

    def should_preserve_pending_after_empty_capture(self, _identifier: str) -> bool:
        return True

    def reset_unread(self, _identifier: str, *, preserve_pending: bool = False) -> None:
        self.preserve_calls.append(bool(preserve_pending))


def check_captured_self_occurrence_is_not_treated_as_empty_retry() -> None:
    monitor = CaptureDoneMonitor()
    bridge = object.__new__(ManagedListenerSchedulerBridge)
    bridge.session_monitor = monitor
    bridge._capture_done(
        {"session_key": "wx:rpa:v1:self-context", "target_name": "客户A"},
        {
            "messages": [
                {
                    "id": "chat-pane:self:1",
                    "sender": "self",
                    "type": "text",
                    "content": "我方已发送的上下文",
                }
            ],
            "pending_signal_consumed": False,
            "self_image_context": {},
        },
        {
            "status": "empty",
            "session_key": "wx:rpa:v1:self-context",
            "target_name": "客户A",
        },
    )
    assert_equal(
        monitor.preserve_calls,
        [False],
        "a real self occurrence should be recorded and acknowledged, not retried as an empty pane",
    )


def main() -> int:
    checks = [
        check_exact_observation_reconciliation,
        check_startup_monitor_reauthenticates_persisted_pending,
        check_badge_event_identity_ignores_ocr_preview_jitter,
        check_ambiguous_historical_session_keys_do_not_merge,
        check_scheduler_startup_closes_only_old_unauthenticated_pending,
        check_scheduler_startup_reconciliation_store_failure_stays_fail_closed,
        check_verified_bootstrap_capture_queues_existing_scheduler_contract,
        check_failed_targets_yield_before_dispatch_cap,
        check_empty_capture_retry_is_content_agnostic_and_bounded,
        check_preview_only_synthetic_input_is_not_reply_authority,
        check_runtime_empty_capture_retries_without_brain_task,
        check_scheduler_empty_capture_retry_is_terminal_at_limit,
        check_captured_self_occurrence_is_not_treated_as_empty_retry,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print(f"All {len(checks)} local session truth/fairness checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
