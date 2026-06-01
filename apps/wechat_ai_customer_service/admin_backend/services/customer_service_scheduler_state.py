"""Persistent state primitives for customer-service multi-session scheduling.

The scheduler state is deliberately transport-agnostic. It tracks which WeChat
sessions need capture, which captured batches need reply generation, and which
planned replies are ready for the single RPA sender.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


STATE_VERSION = 1
DEFAULT_PENDING_SESSION_TTL_SECONDS = 1800
DEFAULT_READY_REPLY_TTL_SECONDS = 900
MAX_STORED_EVENTS = 500


def utcnow_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _iso_to_ts(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(text).timestamp()
    except (TypeError, ValueError, OSError):
        return 0.0


def stable_id(prefix: str, *parts: Any) -> str:
    seed = json.dumps([str(item) for item in parts], ensure_ascii=False, sort_keys=True)
    return f"{prefix}_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def normalize_target_name(name: Any) -> str:
    return str(name or "").strip()


def message_content_key(message: dict[str, Any]) -> str:
    sender = str(message.get("sender") or "")
    content = " ".join(str(message.get("content") or "").split())
    msg_type = str(message.get("type") or "")
    if not content:
        return ""
    return hashlib.sha256(f"{sender}|{msg_type}|{content}".encode("utf-8")).hexdigest()[:24]


def message_identity(message: dict[str, Any]) -> str:
    message_id = str(message.get("id") or "").strip()
    if message_id:
        return message_id
    return message_content_key(message)


@dataclass(frozen=True)
class SchedulerConfig:
    enabled: bool = False
    capture_max_sessions_per_round: int = 3
    llm_max_concurrency: int = 2
    send_max_replies_per_round: int = 1
    same_session_single_inflight: bool = True
    stale_reply_policy: str = "discard_and_requeue"
    pending_session_ttl_seconds: int = DEFAULT_PENDING_SESSION_TTL_SECONDS
    reply_ready_ttl_seconds: int = DEFAULT_READY_REPLY_TTL_SECONDS
    max_pending_sessions: int = 30
    max_pending_messages_per_session: int = 80

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "SchedulerConfig":
        raw = (config or {}).get("concurrency_scheduler", {})
        if not isinstance(raw, dict):
            raw = {}

        def bounded_int(name: str, default: int, minimum: int = 1, maximum: int = 1000) -> int:
            try:
                value = int(raw.get(name, default) or default)
            except (TypeError, ValueError):
                value = default
            return max(minimum, min(maximum, value))

        return cls(
            enabled=raw.get("enabled", False) is True,
            capture_max_sessions_per_round=bounded_int("capture_max_sessions_per_round", 3, 1, 20),
            llm_max_concurrency=bounded_int("llm_max_concurrency", 2, 1, 10),
            send_max_replies_per_round=bounded_int("send_max_replies_per_round", 1, 1, 10),
            same_session_single_inflight=raw.get("same_session_single_inflight", True) is not False,
            stale_reply_policy=str(raw.get("stale_reply_policy") or "discard_and_requeue"),
            pending_session_ttl_seconds=bounded_int("pending_session_ttl_seconds", DEFAULT_PENDING_SESSION_TTL_SECONDS, 60, 86400),
            reply_ready_ttl_seconds=bounded_int("reply_ready_ttl_seconds", DEFAULT_READY_REPLY_TTL_SECONDS, 30, 86400),
            max_pending_sessions=bounded_int("max_pending_sessions", 30, 1, 1000),
            max_pending_messages_per_session=bounded_int("max_pending_messages_per_session", 80, 1, 1000),
        )


class SchedulerStateLock:
    """Small cross-process lock for scheduler state files."""

    def __init__(self, path: Path, timeout_seconds: float = 10.0, stale_seconds: float = 120.0) -> None:
        self.path = path
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.stale_seconds = max(1.0, float(stale_seconds))
        self.fd: int | None = None

    def __enter__(self) -> "SchedulerStateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            self._remove_stale()
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = f"pid={os.getpid()}\ncreated_at={utcnow_iso()}\n"
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Scheduler state is locked: {self.path}")
                time.sleep(0.05)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _remove_stale(self) -> None:
        try:
            age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age >= self.stale_seconds:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class SchedulerStateStore:
    """Read/update helper for multi-session scheduler state."""

    def __init__(self, *, tenant_id: str | None = None, path: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.path = path or (
            tenant_runtime_root(self.tenant_id) / "state" / "customer_service_scheduler_state.json"
        )
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def empty_state(self) -> dict[str, Any]:
        now = utcnow_iso()
        return {
            "version": STATE_VERSION,
            "tenant_id": self.tenant_id,
            "created_at": now,
            "updated_at": now,
            "sessions": {},
            "captures": {},
            "llm_tasks": {},
            "ready_replies": {},
            "send_sequence": 0,
            "events": [],
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.empty_state()
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = self.empty_state()
            state["recovered_from_corrupt_state"] = True
            return state
        if not isinstance(state, dict):
            return self.empty_state()
        state.setdefault("version", STATE_VERSION)
        state.setdefault("tenant_id", self.tenant_id)
        state.setdefault("sessions", {})
        state.setdefault("captures", {})
        state.setdefault("llm_tasks", {})
        state.setdefault("ready_replies", {})
        state.setdefault("send_sequence", 0)
        state.setdefault("events", [])
        return state

    def save(self, state: dict[str, Any]) -> None:
        payload = copy.deepcopy(state)
        payload["updated_at"] = utcnow_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def update(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with SchedulerStateLock(self.lock_path):
            state = self.load()
            result = mutator(state)
            self.save(state)
            return result


def ensure_session(
    state: dict[str, Any],
    target_name: str,
    *,
    exact: bool = True,
    conversation_type: str = "unknown",
    now: str | None = None,
) -> dict[str, Any]:
    name = normalize_target_name(target_name)
    if not name:
        raise ValueError("target_name is required")
    sessions = state.setdefault("sessions", {})
    session = sessions.get(name)
    now = now or utcnow_iso()
    if not isinstance(session, dict):
        session = {
            "session_id": stable_id("session", name),
            "target_name": name,
            "exact": bool(exact),
            "conversation_type": conversation_type or "unknown",
            "status": "idle",
            "context_version": 0,
            "pending_message_count": 0,
            "pending_capture": False,
            "pending_since": "",
            "last_detected_at": "",
            "last_dispatched_at": "",
            "last_capture_at": "",
            "oldest_unreplied_at": "",
            "llm_inflight_task_id": "",
            "ready_reply_ids": [],
            "processed_message_ids": [],
            "processed_content_keys": [],
            "risk_state": {},
            "created_at": now,
            "updated_at": now,
        }
        sessions[name] = session
    session["target_name"] = name
    session["exact"] = bool(exact)
    if conversation_type:
        session["conversation_type"] = conversation_type
    session["updated_at"] = now
    return session


def append_event(state: dict[str, Any], event: str, **payload: Any) -> dict[str, Any]:
    item = {"event": event, "created_at": utcnow_iso(), **payload}
    events = state.setdefault("events", [])
    events.append(item)
    state["events"] = events[-MAX_STORED_EVENTS:]
    return item


def has_active_session_work(state: dict[str, Any], target_name: str) -> bool:
    """Return True when a target already has unsent/in-flight scheduler work."""

    name = normalize_target_name(target_name)
    if not name:
        return False
    session = (state.get("sessions", {}) or {}).get(name)
    if isinstance(session, dict):
        inflight = str(session.get("llm_inflight_task_id") or "")
        if inflight:
            task = (state.get("llm_tasks", {}) or {}).get(inflight)
            if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
                return True
        if str(session.get("status") or "") in {"capturing", "sending"}:
            return True
    for task in (state.get("llm_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            return True
    for reply in (state.get("ready_replies", {}) or {}).values():
        if (
            isinstance(reply, dict)
            and str(reply.get("target_name") or "") == name
            and reply.get("status") in {"ready", "sending"}
        ):
            return True
    return False


def active_input_identity_sets(state: dict[str, Any], target_name: str) -> tuple[set[str], set[str]]:
    """Message ids/content keys already owned by in-flight tasks or ready replies."""

    name = normalize_target_name(target_name)
    ids: set[str] = set()
    keys: set[str] = set()
    if not name:
        return ids, keys
    for task in (state.get("llm_tasks", {}) or {}).values():
        if (
            isinstance(task, dict)
            and str(task.get("target_name") or "") == name
            and task.get("status") in {"queued", "running"}
        ):
            ids.update(str(item) for item in task.get("input_message_ids", []) if str(item))
            keys.update(str(item) for item in task.get("input_content_keys", []) if str(item))
    for reply in (state.get("ready_replies", {}) or {}).values():
        if (
            isinstance(reply, dict)
            and str(reply.get("target_name") or "") == name
            and reply.get("status") in {"ready", "sending"}
        ):
            ids.update(str(item) for item in reply.get("input_message_ids", []) if str(item))
            keys.update(str(item) for item in reply.get("input_content_keys", []) if str(item))
    return ids, keys


def enqueue_pending_session(
    state: dict[str, Any],
    target_name: str,
    *,
    exact: bool = True,
    conversation_type: str = "unknown",
    reason: str = "manual",
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, exact=exact, conversation_type=conversation_type, now=now)
    if not session.get("pending_capture"):
        session["pending_since"] = now
    session["pending_capture"] = True
    session["last_detected_at"] = now
    session["status"] = "capture_pending"
    session["priority_score"] = int(session.get("priority_score") or 50)
    append_event(state, "scheduler_capture_enqueued", target_name=session["target_name"], reason=reason)
    return session


def record_session_signal(
    state: dict[str, Any],
    session_payload: dict[str, Any],
    *,
    whitelist: set[str] | None = None,
    blacklist: set[str] | None = None,
    now: str | None = None,
) -> dict[str, Any] | None:
    name = normalize_target_name(session_payload.get("name") or session_payload.get("title"))
    if not name:
        return None
    if whitelist and name not in whitelist:
        return None
    if blacklist and name in blacklist:
        return None
    now = now or utcnow_iso()
    content = str(session_payload.get("content") or "").strip()
    msg_time = str(session_payload.get("time") or "").strip()
    unread_badge = str(session_payload.get("unread_badge") or session_payload.get("unread") or "").strip()
    conversation_type = str(session_payload.get("conversation_type") or session_payload.get("type") or "unknown")
    session = ensure_session(state, name, conversation_type=conversation_type, now=now)
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    retry_not_before = str((risk_state or {}).get("capture_retry_not_before") or "")
    if retry_not_before:
        now_ts = _iso_to_ts(now)
        retry_ts = _iso_to_ts(retry_not_before)
        if retry_ts > 0 and now_ts > 0 and now_ts < retry_ts:
            session["last_detected_at"] = now
            session["status"] = "capture_cooldown"
            return session
    previous_digest = str(session.get("last_content_digest") or "")
    previous_time = str(session.get("last_message_time") or "")
    previous_badge = str(session.get("last_unread_badge") or "")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:32] if content else ""
    unread_detected = bool(session_payload.get("unread_detected") or session_payload.get("pending"))
    has_signal = bool(digest or msg_time or unread_badge or unread_detected)
    unread_only_signal = bool(unread_detected and not digest and not msg_time and not unread_badge)
    if unread_only_signal and has_active_session_work(state, name):
        session["last_detected_at"] = now
        return session
    changed = bool(
        (digest and digest != previous_digest)
        or (msg_time and msg_time != previous_time)
        or (unread_badge and unread_badge != previous_badge)
        or unread_detected
    )
    if changed or (has_signal and not previous_digest and not previous_time and not previous_badge):
        session["last_content_digest"] = digest
        session["last_message_time"] = msg_time
        session["last_unread_badge"] = unread_badge
        enqueue_pending_session(
            state,
            name,
            exact=bool(session_payload.get("exact", True)),
            conversation_type=conversation_type,
            reason="session_signal_changed",
            now=now,
        )
    elif session.get("pending_capture"):
        # No change does not imply handled. Pending survives until capture/send.
        session["status"] = "capture_pending"
        session["last_detected_at"] = now
    else:
        session["status"] = session.get("status") or "idle"
    return session


def select_capture_sessions(
    state: dict[str, Any],
    *,
    limit: int,
    blocked_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    blocked_names = blocked_names or set()
    candidates = [
        session
        for session in (state.get("sessions", {}) or {}).values()
        if isinstance(session, dict)
        and session.get("pending_capture")
        and str(session.get("target_name") or "") not in blocked_names
        and str(session.get("status") or "") not in {"paused", "capturing", "sending"}
        and not has_active_session_work(state, str(session.get("target_name") or ""))
    ]

    def sort_key(session: dict[str, Any]) -> tuple[str, int, str]:
        oldest = str(session.get("oldest_unreplied_at") or session.get("pending_since") or session.get("last_detected_at") or "")
        pending_count = int(session.get("pending_message_count") or 0)
        last_capture = str(session.get("last_capture_at") or "")
        return (oldest, -pending_count, last_capture)

    ordered = sorted(candidates, key=sort_key)
    return [copy.deepcopy(item) for item in ordered[: max(1, int(limit or 1))]]


def mark_capture_started(state: dict[str, Any], target_name: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, now=now)
    session["status"] = "capturing"
    session["last_dispatched_at"] = now
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    if risk_state:
        risk_state.pop("capture_retry_not_before", None)
    append_event(state, "scheduler_capture_started", target_name=session["target_name"])
    return session


def record_capture_result(
    state: dict[str, Any],
    target_name: str,
    *,
    messages: list[dict[str, Any]],
    batch: list[dict[str, Any]] | None = None,
    overflow_messages: list[dict[str, Any]] | None = None,
    history_backfill: dict[str, Any] | None = None,
    exact: bool = True,
    conversation_type: str = "unknown",
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    session = ensure_session(state, target_name, exact=exact, conversation_type=conversation_type, now=now)
    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    batch = list(batch if batch is not None else messages)
    overflow_messages = list(overflow_messages or [])
    existing_ids = set(session.get("processed_message_ids", []) or [])
    existing_keys = set(session.get("processed_content_keys", []) or [])
    active_ids, active_keys = active_input_identity_sets(state, session["target_name"])
    existing_ids.update(active_ids)
    existing_keys.update(active_keys)
    new_messages = [
        item
        for item in batch
        if message_identity(item)
        and message_identity(item) not in existing_ids
        and (not message_content_key(item) or message_content_key(item) not in existing_keys)
    ]
    if new_messages:
        session["context_version"] = int(session.get("context_version") or 0) + 1
        session["pending_message_count"] = len(new_messages) + len(overflow_messages)
        session["oldest_unreplied_at"] = str(new_messages[0].get("time") or now)
        session["status"] = "captured"
        session["pending_capture"] = False
        if risk_state:
            risk_state.pop("capture_fail_count", None)
            risk_state.pop("capture_retry_not_before", None)
            risk_state.pop("last_capture_failed_at", None)
    else:
        session["pending_message_count"] = 0
        session["pending_capture"] = False
        session["status"] = "idle"
    session["last_capture_at"] = now
    capture_id = stable_id("capture", target_name, session.get("context_version"), [message_identity(item) for item in batch], now)
    capture = {
        "capture_id": capture_id,
        "target_name": session["target_name"],
        "exact": bool(exact),
        "conversation_type": conversation_type,
        "context_version": int(session.get("context_version") or 0),
        "captured_at": now,
        "message_ids": [message_identity(item) for item in batch if message_identity(item)],
        "content_keys": [message_content_key(item) for item in batch if message_content_key(item)],
        "messages": copy.deepcopy(messages),
        "batch": copy.deepcopy(batch),
        "overflow_messages": copy.deepcopy(overflow_messages),
        "history_backfill": history_backfill or {},
        "status": "captured" if new_messages else "empty",
    }
    state.setdefault("captures", {})[capture_id] = capture
    append_event(
        state,
        "scheduler_capture_completed",
        target_name=session["target_name"],
        capture_id=capture_id,
        context_version=capture["context_version"],
        message_count=len(batch),
    )
    return capture


def enqueue_llm_task(
    state: dict[str, Any],
    capture_id: str,
    *,
    timeout_seconds: int = 30,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    capture = state.setdefault("captures", {}).get(capture_id)
    if not isinstance(capture, dict):
        raise KeyError(f"capture not found: {capture_id}")
    target_name = str(capture.get("target_name") or "")
    session = ensure_session(state, target_name, exact=bool(capture.get("exact", True)), conversation_type=str(capture.get("conversation_type") or "unknown"), now=now)
    inflight = str(session.get("llm_inflight_task_id") or "")
    if inflight:
        task = state.setdefault("llm_tasks", {}).get(inflight)
        if isinstance(task, dict) and task.get("status") in {"queued", "running"}:
            return task
    task_id = stable_id("llm_task", target_name, capture_id, capture.get("context_version"), now)
    task = {
        "task_id": task_id,
        "target_name": target_name,
        "input_context_version": int(capture.get("context_version") or 0),
        "capture_ids": [capture_id],
        "input_message_ids": list(capture.get("message_ids") or []),
        "input_content_keys": list(capture.get("content_keys") or []),
        "status": "queued",
        "created_at": now,
        "started_at": "",
        "finished_at": "",
        "timeout_seconds": max(1, int(timeout_seconds or 30)),
        "attempt": 1,
        "result": None,
        "error": None,
    }
    state.setdefault("llm_tasks", {})[task_id] = task
    session["llm_inflight_task_id"] = task_id
    session["status"] = "llm_queued"
    append_event(state, "scheduler_llm_task_enqueued", target_name=target_name, task_id=task_id, context_version=task["input_context_version"])
    return task


def mark_llm_started(state: dict[str, Any], task_id: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    task["status"] = "running"
    task["started_at"] = now
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    session["status"] = "llm_running"
    session["llm_inflight_task_id"] = task_id
    append_event(state, "scheduler_llm_task_started", target_name=session["target_name"], task_id=task_id)
    return task


def recover_orphaned_running_llm_tasks(
    state: dict[str, Any],
    *,
    active_task_ids: set[str],
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Requeue running LLM tasks whose in-memory future was lost.

    The scheduler state is durable, but Python futures live only inside the
    current listener process. If the listener restarts while an LLM task is
    marked running, the persisted task would otherwise block that session
    forever. Requeueing is safe because RPA send still goes through freshness
    and context-version checks.
    """
    now = now or utcnow_iso()
    recovered: list[dict[str, Any]] = []
    for task_id, task in list((state.get("llm_tasks", {}) or {}).items()):
        if not isinstance(task, dict):
            continue
        normalized_task_id = str(task.get("task_id") or task_id)
        if task.get("status") != "running" or normalized_task_id in active_task_ids:
            continue
        task["status"] = "queued"
        task["requeued_at"] = now
        task["orphan_recovery_count"] = int(task.get("orphan_recovery_count") or 0) + 1
        target_name = str(task.get("target_name") or "")
        session = ensure_session(state, target_name, now=now)
        session["status"] = "llm_queued"
        session["llm_inflight_task_id"] = normalized_task_id
        append_event(
            state,
            "scheduler_llm_task_orphan_requeued",
            target_name=session["target_name"],
            task_id=normalized_task_id,
            orphan_recovery_count=task["orphan_recovery_count"],
        )
        recovered.append(copy.deepcopy(task))
    return recovered


def complete_llm_task(
    state: dict[str, Any],
    task_id: str,
    *,
    reply_text: str,
    decision: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    target_name = str(task.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    input_version = int(task.get("input_context_version") or 0)
    current_version = int(session.get("context_version") or 0)
    task["finished_at"] = now
    task["result"] = {"reply_text": reply_text, "decision": decision or {}}
    if input_version < current_version:
        task["status"] = "stale"
        if session.get("llm_inflight_task_id") == task_id:
            session["llm_inflight_task_id"] = ""
        append_event(state, "scheduler_llm_task_stale", target_name=target_name, task_id=task_id, input_context_version=input_version, current_context_version=current_version)
        return {"status": "stale", "task": task}

    task["status"] = "completed"
    if session.get("llm_inflight_task_id") == task_id:
        session["llm_inflight_task_id"] = ""
    reply = enqueue_ready_reply(state, task_id, reply_text=reply_text, decision=decision or {}, now=now)
    append_event(state, "scheduler_llm_task_completed", target_name=target_name, task_id=task_id, reply_id=reply["reply_id"])
    return {"status": "completed", "task": task, "reply": reply}


def fail_llm_task(state: dict[str, Any], task_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    task["status"] = "failed"
    task["finished_at"] = now
    task["error"] = reason
    session = ensure_session(state, str(task.get("target_name") or ""), now=now)
    if session.get("llm_inflight_task_id") == task_id:
        session["llm_inflight_task_id"] = ""
    session["status"] = "failed"
    append_event(state, "scheduler_llm_task_failed", target_name=session["target_name"], task_id=task_id, reason=reason)
    return task


def enqueue_ready_reply(
    state: dict[str, Any],
    task_id: str,
    *,
    reply_text: str,
    decision: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    now = now or utcnow_iso()
    task = state.setdefault("llm_tasks", {}).get(task_id)
    if not isinstance(task, dict):
        raise KeyError(f"llm task not found: {task_id}")
    sequence = int(state.get("send_sequence") or 0) + 1
    state["send_sequence"] = sequence
    target_name = str(task.get("target_name") or "")
    reply_id = stable_id("reply", target_name, task_id, sequence)
    reply = {
        "reply_id": reply_id,
        "task_id": task_id,
        "target_name": target_name,
        "input_context_version": int(task.get("input_context_version") or 0),
        "capture_ids": list(task.get("capture_ids") or []),
        "input_message_ids": list(task.get("input_message_ids") or []),
        "input_content_keys": list(task.get("input_content_keys") or []),
        "reply_text": reply_text,
        "decision": decision or {},
        "status": "ready",
        "ready_at": now,
        "send_attempts": 0,
        "last_send_error": "",
        "freshness_check": None,
        "priority": {"ready_sequence": sequence},
    }
    state.setdefault("ready_replies", {})[reply_id] = reply
    session = ensure_session(state, target_name, now=now)
    ids = list(session.get("ready_reply_ids") or [])
    if reply_id not in ids:
        ids.append(reply_id)
    session["ready_reply_ids"] = ids[-20:]
    session["status"] = "reply_ready"
    append_event(state, "scheduler_reply_ready", target_name=target_name, task_id=task_id, reply_id=reply_id, context_version=reply["input_context_version"])
    return reply


def select_ready_replies(state: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    replies = [
        reply
        for reply in (state.get("ready_replies", {}) or {}).values()
        if isinstance(reply, dict) and reply.get("status") == "ready"
    ]
    replies.sort(key=lambda item: (str(item.get("ready_at") or ""), int((item.get("priority") or {}).get("ready_sequence") or 0)))
    selected: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for reply in replies:
        target = str(reply.get("target_name") or "")
        session = (state.get("sessions", {}) or {}).get(target, {})
        if int(reply.get("input_context_version") or 0) < int((session or {}).get("context_version") or 0):
            mark_reply_stale(state, str(reply.get("reply_id") or ""), reason="context_version_advanced_before_send")
            continue
        if target in seen_targets:
            continue
        selected.append(copy.deepcopy(reply))
        seen_targets.add(target)
        if len(selected) >= max(1, int(limit or 1)):
            break
    return selected


def mark_reply_sending(state: dict[str, Any], reply_id: str, *, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "sending"
    reply["send_started_at"] = now
    reply["send_attempts"] = int(reply.get("send_attempts") or 0) + 1
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "sending"
    append_event(state, "scheduler_send_started", target_name=session["target_name"], reply_id=reply_id)
    return reply


def mark_reply_sent(state: dict[str, Any], reply_id: str, *, send_result: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "sent"
    reply["sent_at"] = now
    reply["send_result"] = send_result or {}
    target_name = str(reply.get("target_name") or "")
    session = ensure_session(state, target_name, now=now)
    pending_after_send = bool(session.get("pending_capture"))
    if pending_after_send:
        # Preserve queued follow-up signals that arrived while this reply was in flight.
        session["status"] = "capture_pending"
        session["pending_capture"] = True
        session["pending_message_count"] = max(1, int(session.get("pending_message_count") or 0))
        if not str(session.get("pending_since") or ""):
            session["pending_since"] = now
        if not str(session.get("last_detected_at") or ""):
            session["last_detected_at"] = now
        if not str(session.get("oldest_unreplied_at") or ""):
            session["oldest_unreplied_at"] = now
    else:
        session["status"] = "sent"
        session["pending_capture"] = False
        session["pending_message_count"] = 0
        session["oldest_unreplied_at"] = ""
    processed = list(session.get("processed_message_ids") or [])
    for message_id in reply.get("input_message_ids") or []:
        if message_id and message_id not in processed:
            processed.append(message_id)
    session["processed_message_ids"] = processed[-500:]
    processed_keys = list(session.get("processed_content_keys") or [])
    for content_key in reply.get("input_content_keys") or []:
        if content_key and content_key not in processed_keys:
            processed_keys.append(content_key)
    session["processed_content_keys"] = processed_keys[-500:]
    append_event(
        state,
        "scheduler_send_completed",
        target_name=target_name,
        reply_id=reply_id,
        pending_capture_after_send=pending_after_send,
    )
    return reply


def mark_reply_stale(state: dict[str, Any], reply_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "stale"
    reply["stale_at"] = now
    reply["stale_reason"] = reason
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "captured" if session.get("pending_message_count") else "idle"
    append_event(state, "scheduler_send_freshness_stale", target_name=session["target_name"], reply_id=reply_id, reason=reason)
    return reply


def mark_reply_failed(state: dict[str, Any], reply_id: str, *, reason: str, send_result: dict[str, Any] | None = None, now: str | None = None) -> dict[str, Any]:
    now = now or utcnow_iso()
    reply = state.setdefault("ready_replies", {}).get(reply_id)
    if not isinstance(reply, dict):
        raise KeyError(f"reply not found: {reply_id}")
    reply["status"] = "send_failed"
    reply["last_send_error"] = reason
    reply["send_result"] = send_result or {}
    session = ensure_session(state, str(reply.get("target_name") or ""), now=now)
    session["status"] = "failed"
    append_event(state, "scheduler_send_failed", target_name=session["target_name"], reply_id=reply_id, reason=reason)
    return reply


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    sessions = [item for item in (state.get("sessions", {}) or {}).values() if isinstance(item, dict)]
    tasks = [item for item in (state.get("llm_tasks", {}) or {}).values() if isinstance(item, dict)]
    replies = [item for item in (state.get("ready_replies", {}) or {}).values() if isinstance(item, dict)]
    return {
        "sessions": len(sessions),
        "pending_sessions": sum(1 for item in sessions if item.get("pending_capture")),
        "llm_queued": sum(1 for item in tasks if item.get("status") == "queued"),
        "llm_running": sum(1 for item in tasks if item.get("status") == "running"),
        "reply_ready": sum(1 for item in replies if item.get("status") == "ready"),
        "reply_stale": sum(1 for item in replies if item.get("status") == "stale"),
        "reply_sent": sum(1 for item in replies if item.get("status") == "sent"),
        "reply_failed": sum(1 for item in replies if item.get("status") == "send_failed"),
    }
