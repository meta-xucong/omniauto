"""Bridge verified startup captures into the existing Scheduler state.

The startup bootstrap and the managed listener run in separate processes.  A
visible-only bootstrap can clear WeChat's unread badge while it verifies the
chat pane, so its verified customer occurrences must be committed through the
same durable capture/task contract that the live Scheduler already consumes.

This module defines no transport payload and owns no reply wording.  It only
uses existing Scheduler fields and state transitions.
"""

from __future__ import annotations

from typing import Any

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (
    SchedulerStateStore,
    active_input_identity_sets,
    enqueue_llm_task,
    has_active_session_work,
    message_identity,
    record_capture_result,
    record_session_signal,
    stable_id,
)


def resolve_unique_bootstrap_session_row(
    sessions_payload: dict[str, Any] | None,
    *,
    target_name: str,
) -> dict[str, Any]:
    """Return one exact, keyed session row or fail closed with an empty dict."""

    payload = sessions_payload if isinstance(sessions_payload, dict) else {}
    if payload.get("ok") is not True:
        return {}
    clean_name = str(target_name or "").strip()
    if not clean_name:
        return {}
    matches = [
        dict(item)
        for item in (payload.get("sessions") or [])
        if isinstance(item, dict) and str(item.get("name") or item.get("title") or "").strip() == clean_name
    ]
    if len(matches) != 1:
        return {}
    row = matches[0]
    if bool(row.get("ambiguous_display_name")):
        return {}
    if not str(row.get("session_key") or "").strip():
        return {}
    return row


def bootstrap_row_has_current_unread_evidence(row: dict[str, Any] | None) -> bool:
    data = row if isinstance(row, dict) else {}
    unread_badge = str(data.get("unread_badge") or data.get("unread") or "").strip()
    return bool(unread_badge or data.get("unread_signal") or data.get("unread_detected"))


def queue_verified_bootstrap_capture(
    store: SchedulerStateStore,
    *,
    target_name: str,
    session_row: dict[str, Any],
    messages: list[dict[str, Any]],
    batch: list[dict[str, Any]],
    overflow_messages: list[dict[str, Any]] | None = None,
    llm_timeout_seconds: int = 30,
) -> dict[str, Any]:
    """Persist a verified bootstrap batch, or a media recapture signal.

    Sidebar unread evidence may authorize a later live recapture, but it is
    not required once ``batch`` already contains verified chat-pane customer
    occurrences.  Opening the chat can legitimately clear the badge before
    this durable handoff runs.
    """

    row = dict(session_row or {})
    clean_name = str(target_name or "").strip()
    session_key = str(row.get("session_key") or "").strip()
    if not clean_name or not session_key:
        return {"ok": False, "queued": False, "reason": "bootstrap_session_identity_unconfirmed"}
    if str(row.get("name") or row.get("title") or "").strip() != clean_name:
        return {"ok": False, "queued": False, "reason": "bootstrap_session_name_mismatch"}

    clean_messages = [dict(item) for item in messages or [] if isinstance(item, dict)]
    clean_batch = [dict(item) for item in batch or [] if isinstance(item, dict) and message_identity(item)]
    clean_overflow = [dict(item) for item in overflow_messages or [] if isinstance(item, dict)]
    conversation_type = str(row.get("conversation_type") or row.get("type") or "unknown").strip() or "unknown"
    if not clean_batch and not bootstrap_row_has_current_unread_evidence(row):
        return {"ok": True, "queued": False, "reason": "bootstrap_row_has_no_current_unread_evidence"}

    def mutate(state: dict[str, Any]) -> dict[str, Any]:
        if clean_batch:
            active_ids, _active_keys = active_input_identity_sets(
                state,
                clean_name,
                session_key=session_key,
            )
            batch_ids = {message_identity(item) for item in clean_batch if message_identity(item)}
            if batch_ids and batch_ids.issubset(active_ids):
                return {
                    "ok": True,
                    "queued": True,
                    "reason": "bootstrap_batch_already_active",
                    "session_key": session_key,
                }
            if has_active_session_work(state, clean_name, session_key=session_key):
                signal = _record_recent_bootstrap_signal(state, clean_name=clean_name, session_key=session_key, row=row)
                return {
                    "ok": bool(signal),
                    # The signal preserves a retry opportunity, but it does not
                    # durably retain this already-captured customer batch.  The
                    # bootstrap caller must therefore fail closed instead of
                    # reporting the handoff as complete.
                    "queued": False,
                    "reason": "bootstrap_new_batch_deferred_behind_active_work",
                    "session_key": session_key,
                }
            capture = record_capture_result(
                state,
                clean_name,
                messages=clean_messages,
                batch=clean_batch,
                overflow_messages=clean_overflow,
                history_backfill={
                    "enabled": True,
                    "applied": False,
                    "reason": "verified_visible_only_bootstrap_handoff",
                    "history_continuity": "startup_verified_visible",
                    "gap_risk": False,
                },
                batch_selection={
                    "eligible_count": len(clean_batch),
                    "overflow_count": len(clean_overflow),
                    "max_batch_messages": len(clean_batch),
                    "truncated": bool(clean_overflow),
                },
                exact=True,
                conversation_type=conversation_type,
                session_key=session_key,
            )
            if str(capture.get("status") or "") != "captured":
                return {
                    "ok": True,
                    "queued": False,
                    "reason": "bootstrap_batch_already_closed",
                    "session_key": session_key,
                    "capture_id": str(capture.get("capture_id") or ""),
                }
            task = enqueue_llm_task(
                state,
                str(capture.get("capture_id") or ""),
                timeout_seconds=max(1, int(llm_timeout_seconds or 30)),
            )
            return {
                "ok": True,
                "queued": True,
                "reason": "bootstrap_verified_capture_queued",
                "session_key": session_key,
                "capture_id": str(capture.get("capture_id") or ""),
                "task_id": str(task.get("task_id") or ""),
            }

        signal = _record_recent_bootstrap_signal(state, clean_name=clean_name, session_key=session_key, row=row)
        return {
            "ok": bool(signal),
            "queued": bool(signal),
            "reason": "bootstrap_current_unread_requires_live_capture" if signal else "bootstrap_signal_not_recorded",
            "session_key": session_key,
        }

    return store.update(mutate)


def _record_recent_bootstrap_signal(
    state: dict[str, Any],
    *,
    clean_name: str,
    session_key: str,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    observation_id = str(row.get("session_observation_id") or "").strip()
    if not observation_id:
        observation_id = stable_id(
            "bootstrap_observation",
            session_key,
            row.get("time"),
            row.get("unread_badge") or row.get("unread"),
        )
    return record_session_signal(
        state,
        {
            **row,
            "name": clean_name,
            "session_key": session_key,
            "unread_detected": True,
            "session_observation_id": observation_id,
            "session_observation_is_new": True,
            "exact": True,
        },
    )
