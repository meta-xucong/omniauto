"""Private reconciliation helpers for monitor/scheduler runtime state.

The WeChat connector is an observation source, not the owner of scheduling
state.  These helpers compare the already-existing observation identities on
both sides so a failed target cannot monopolize a bounded dispatch window.

This module intentionally has no dependency on OCR, RPA, Brain, voice, or
vision implementations and does not define a transport payload.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


ELIGIBLE = "eligible"
DEFER = "defer"
ACKNOWLEDGE = "acknowledge"


def capture_observation_disposition(
    scheduler_state: dict[str, Any],
    *,
    target_name: str,
    session_key: str,
    pending_observation_id: str,
    now: str | datetime | None = None,
) -> tuple[str, float]:
    """Return how Monitor should treat one pending target.

    Reconciliation is deliberately exact.  A missing/ambiguous identity or a
    different observation remains eligible; it must not be suppressed using a
    display-name guess.  Only the same session key and the same non-empty
    observation can inherit Scheduler cooldown or terminal failure state.
    """

    monitor_key = str(session_key or "").strip()
    monitor_observation = str(pending_observation_id or "").strip()
    if not monitor_key or not monitor_observation:
        return ELIGIBLE, 0.0

    sessions = scheduler_state.get("sessions") if isinstance(scheduler_state, dict) else {}
    if not isinstance(sessions, dict):
        return ELIGIBLE, 0.0
    session = sessions.get(monitor_key)
    if not isinstance(session, dict):
        return ELIGIBLE, 0.0
    scheduler_key = str(session.get("session_key") or monitor_key).strip()
    if scheduler_key != monitor_key:
        return ELIGIBLE, 0.0
    scheduler_name = str(session.get("target_name") or session.get("display_name") or "").strip()
    if scheduler_name and str(target_name or "").strip() and scheduler_name != str(target_name or "").strip():
        return ELIGIBLE, 0.0
    scheduler_observation = str(
        session.get("pending_observation_id")
        or session.get("last_session_observation_id")
        or ""
    ).strip()
    if not scheduler_observation or scheduler_observation != monitor_observation:
        return ELIGIBLE, 0.0

    risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
    retry_not_before = str((risk_state or {}).get("capture_retry_not_before") or "").strip()
    retry_seconds = _remaining_seconds(retry_not_before, now=now)
    if retry_seconds > 0:
        return DEFER, retry_seconds

    status = str(session.get("status") or "").strip().lower()
    pending_capture = bool(session.get("pending_capture"))
    if not pending_capture and status in {"capture_failed", "capture_cooldown"}:
        return ACKNOWLEDGE, 0.0
    return ELIGIBLE, 0.0


def reconcile_stale_scheduler_pending_at_startup(
    scheduler_state: dict[str, Any],
    *,
    current_pending_identifiers: set[str],
    runtime_started_at: str | datetime,
    bootstrap_grace_seconds: float = 120.0,
) -> list[str]:
    """Close old capture work that has no evidence in the new process.

    A verified bootstrap can run immediately before the managed listener and
    legitimately leave a fresh pending capture (notably for media).  Preserve
    that short handoff window, current Monitor targets, and any session that
    already owns Brain/polish/send work.  Everything else is an old logical
    level, not proof of a current unread event.
    """

    if not isinstance(scheduler_state, dict):
        return []
    sessions = scheduler_state.get("sessions")
    if not isinstance(sessions, dict):
        return []
    started = _coerce_datetime(runtime_started_at)
    identifiers = {str(item or "").strip() for item in current_pending_identifiers if str(item or "").strip()}
    closed: list[str] = []
    for state_key, session in sessions.items():
        if not isinstance(session, dict) or not bool(session.get("pending_capture")):
            continue
        session_key = str(session.get("session_key") or state_key or "").strip()
        target_name = str(session.get("target_name") or session.get("display_name") or "").strip()
        if (session_key and session_key in identifiers) or (not session_key and target_name in identifiers):
            continue
        if _session_has_active_non_capture_work(
            scheduler_state,
            session_record=session,
            session_key=session_key,
            target_name=target_name,
        ):
            continue
        detected = _coerce_datetime(
            str(session.get("last_detected_at") or session.get("pending_since") or "")
        )
        if started is not None and detected is not None:
            age_before_start = (started - detected).total_seconds()
            if age_before_start <= max(0.0, float(bootstrap_grace_seconds or 0.0)):
                continue
        session["pending_capture"] = False
        session["pending_reason"] = ""
        session["pending_signal_has_unread_evidence"] = False
        if str(session.get("status") or "").strip().lower() in {
            "capture_pending",
            "capture_cooldown",
            "capture_failed",
        }:
            session["status"] = "idle"
        risk_state = session.get("risk_state") if isinstance(session.get("risk_state"), dict) else {}
        if isinstance(risk_state, dict):
            risk_state.pop("capture_retry_not_before", None)
        closed.append(session_key or target_name)
    return closed


def _session_has_active_non_capture_work(
    state: dict[str, Any],
    *,
    session_record: dict[str, Any] | None,
    session_key: str,
    target_name: str,
) -> bool:
    session = session_record if isinstance(session_record, dict) else None
    if isinstance(session, dict) and any(
        str(session.get(field) or "").strip()
        for field in ("llm_inflight_task_id", "polish_inflight_task_id", "media_context_inflight_task_id")
    ):
        return True
    for field, statuses in (
        ("llm_tasks", {"queued", "running"}),
        ("polish_tasks", {"queued", "running"}),
        ("media_context_tasks", {"queued", "running"}),
        ("ready_replies", {"ready", "sending"}),
    ):
        for item in (state.get(field) or {}).values():
            if not isinstance(item, dict) or str(item.get("status") or "").strip().lower() not in statuses:
                continue
            item_key = str(item.get("session_key") or "").strip()
            item_name = str(item.get("target_name") or "").strip()
            if (session_key and item_key == session_key) or (not item_key and target_name and item_name == target_name):
                return True
    return False


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed


def _remaining_seconds(value: str, *, now: str | datetime | None) -> float:
    if not value:
        return 0.0
    try:
        deadline = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return 0.0
    if isinstance(now, datetime):
        current = now
    elif str(now or "").strip():
        try:
            current = datetime.fromisoformat(str(now))
        except ValueError:
            current = datetime.now(tz=deadline.tzinfo)
    else:
        current = datetime.now(tz=deadline.tzinfo)
    if deadline.tzinfo is not None and current.tzinfo is None:
        current = current.replace(tzinfo=deadline.tzinfo)
    elif deadline.tzinfo is None and current.tzinfo is not None:
        current = current.replace(tzinfo=None)
    return max(0.0, (deadline - current).total_seconds())
