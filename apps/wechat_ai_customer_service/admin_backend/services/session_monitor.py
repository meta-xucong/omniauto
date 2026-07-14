"""WeChat session monitor: detect unread messages via content-digest comparison.

wxauto4 does not expose unread counts, so we compare the SHA256 digest of each
session's latest content preview across polls. A changed digest (or newer time)
indicates potential new messages.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_session_ledger import (
    SessionLedgerStore,
    row_fingerprint_from_payload,
    session_key_from_payload,
)
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


@dataclass
class SessionState:
    name: str
    session_key: str = ""
    last_content_digest: str = ""
    last_message_time: str = ""
    last_unread_badge: str = ""
    unread_detected: bool = False
    priority_score: int = 0
    first_seen_at: str = ""
    last_seen_at: str = ""
    pending_since: str = ""
    last_detected_at: str = ""
    last_dispatched_at: str = ""
    conversation_type: str = "unknown"
    preview_change_hits: int = 0
    pending_signal_text: str = ""
    pending_signal_kind: str = ""
    signal_ready_after: str = ""
    retry_not_before: str = ""
    empty_capture_retries: int = 0
    startup_visual_baseline_at: str = ""
    # A session-list row is an observation, not a new-message event.  Keep the
    # two identities separately so a persistent red dot cannot repeatedly
    # recreate the already handled event after a capture/reset.
    last_observation_id: str = ""
    pending_observation_id: str = ""
    acknowledged_observation_id: str = ""
    acknowledged_unread_badge_epoch: int = 0
    last_observed_unread_badge: bool = False
    unread_badge_epoch: int = 0
    candidate_observation_id: str = ""
    candidate_preview_hits: int = 0


@dataclass
class ActiveTarget:
    name: str
    session_key: str = ""
    exact: bool = True
    priority_score: int = 0
    unread_detected: bool = False
    session_age_seconds: int = 0
    conversation_type: str = "unknown"
    pending_signal_kind: str = ""
    pending_signal_text: str = ""
    last_message_time: str = ""
    unread_badge: str = ""
    # Additive event metadata for the scheduler.  ``session_observation_id``
    # is the stable raw sidebar observation; ``pending_observation_id`` is the
    # monitor's event identity (including an unread-badge rising-edge epoch).
    session_observation_id: str = ""
    pending_observation_id: str = ""


MEDIA_CAPTURE_SIGNAL_KINDS = {"voice_capture", "image_capture", "media_capture"}


class SessionMonitor:
    """Polls WeChat session list and detects changes."""

    def __init__(
        self,
        *,
        tenant_id: str | None = None,
        state_path: Path | None = None,
        whitelist: set[str] | None = None,
        blacklist: set[str] | None = None,
        max_targets_per_iteration: int = 5,
        min_switch_interval_seconds: int = 2,
        dispatch_strategy: str = "event_driven",
        sticky_target_hold_seconds: int = 35,
        sticky_max_dispatch_rounds: int = 3,
        preview_change_confirmations: int = 2,
        initial_preview_can_raise_unread: bool = True,
        preview_change_can_raise_unread: bool = True,
        short_preview_can_raise_unread: bool = True,
        require_unread_badge_for_dispatch: bool = False,
        require_preview_signal_with_unread_badge: bool = False,
        high_sensitivity_short_max_chars: int = 7,
        high_sensitivity_short_merge_window_seconds: float = 0.0,
        empty_capture_retry_seconds: float = 3.0,
        empty_capture_retry_backoff_multiplier: float = 1.8,
        empty_capture_retry_max_seconds: float = 15.0,
    ) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.state_path = state_path or (
            tenant_runtime_root(self.tenant_id) / "customer_profiles" / "session_monitor_state.json"
        )
        self.whitelist = whitelist or set()
        self.blacklist = blacklist or set()
        self.max_targets_per_iteration = max(1, max_targets_per_iteration)
        self.min_switch_interval_seconds = max(1, min_switch_interval_seconds)
        self.dispatch_strategy = str(dispatch_strategy or "event_driven").strip().lower()
        if self.dispatch_strategy not in {"event_driven", "legacy_pending_scan"}:
            self.dispatch_strategy = "event_driven"
        self.sticky_target_hold_seconds = max(5, int(sticky_target_hold_seconds or 35))
        self.sticky_max_dispatch_rounds = max(1, int(sticky_max_dispatch_rounds or 3))
        self.preview_change_confirmations = max(1, int(preview_change_confirmations or 2))
        self.initial_preview_can_raise_unread = bool(initial_preview_can_raise_unread)
        self.preview_change_can_raise_unread = bool(preview_change_can_raise_unread)
        self.short_preview_can_raise_unread = bool(short_preview_can_raise_unread)
        self.require_unread_badge_for_dispatch = bool(require_unread_badge_for_dispatch)
        self.require_preview_signal_with_unread_badge = bool(require_preview_signal_with_unread_badge)
        self.high_sensitivity_short_max_chars = max(1, int(high_sensitivity_short_max_chars or 7))
        self.high_sensitivity_short_merge_window_seconds = max(0.0, float(high_sensitivity_short_merge_window_seconds or 0.0))
        self.empty_capture_retry_seconds = max(0.0, float(empty_capture_retry_seconds or 0.0))
        self.empty_capture_retry_backoff_multiplier = max(1.0, float(empty_capture_retry_backoff_multiplier or 1.0))
        self.empty_capture_retry_max_seconds = max(
            self.empty_capture_retry_seconds,
            float(empty_capture_retry_max_seconds or self.empty_capture_retry_seconds or 0.0),
        )
        self._last_switch_at: float = 0.0
        self._last_dispatched_target: str = ""
        self._sticky_target: str = ""
        self._sticky_until_ts: float = 0.0
        self._sticky_dispatch_rounds: int = 0
        self._sessions: dict[str, SessionState] = {}
        self._startup_visual_baseline_active = True
        self._ledger = SessionLedgerStore(tenant_id=self.tenant_id)
        self._load_state()

    def _load_state(self) -> None:
        if not self.state_path.exists():
            self._sessions = {}
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._sessions = {}
            return
        if not isinstance(payload, dict):
            self._sessions = {}
            return
        raw = payload.get("sessions", {})
        restored: dict[str, SessionState] = {}
        for state_key, data in raw.items():
            if not isinstance(data, dict):
                continue
            session_key = str(data.get("session_key") or state_key or "").strip()
            display_name = str(
                data.get("name")
                or data.get("display_name")
                or data.get("target_name")
                or state_key
            ).strip()
            if not display_name:
                display_name = str(state_key)
            restored[str(session_key or state_key)] = SessionState(
                name=display_name,
                session_key=session_key,
                last_content_digest=str(data.get("last_content_digest") or ""),
                last_message_time=str(data.get("last_message_time") or ""),
                last_unread_badge=str(data.get("last_unread_badge") or ""),
                unread_detected=bool(data.get("unread_detected", False)),
                priority_score=int(data.get("priority_score", 0) or 0),
                first_seen_at=str(data.get("first_seen_at") or ""),
                last_seen_at=str(data.get("last_seen_at") or ""),
                pending_since=str(data.get("pending_since") or ""),
                last_detected_at=str(data.get("last_detected_at") or ""),
                last_dispatched_at=str(data.get("last_dispatched_at") or ""),
                conversation_type=str(data.get("conversation_type") or "unknown"),
                preview_change_hits=int(data.get("preview_change_hits", 0) or 0),
                pending_signal_text=str(data.get("pending_signal_text") or ""),
                pending_signal_kind=str(data.get("pending_signal_kind") or ""),
                signal_ready_after=str(data.get("signal_ready_after") or ""),
                retry_not_before=str(data.get("retry_not_before") or ""),
                empty_capture_retries=int(data.get("empty_capture_retries", 0) or 0),
                startup_visual_baseline_at=str(data.get("startup_visual_baseline_at") or ""),
                last_observation_id=str(data.get("last_observation_id") or ""),
                pending_observation_id=str(data.get("pending_observation_id") or ""),
                acknowledged_observation_id=str(data.get("acknowledged_observation_id") or ""),
                acknowledged_unread_badge_epoch=int(data.get("acknowledged_unread_badge_epoch", 0) or 0),
                last_observed_unread_badge=bool(data.get("last_observed_unread_badge", False)),
                unread_badge_epoch=int(data.get("unread_badge_epoch", 0) or 0),
                candidate_observation_id=str(data.get("candidate_observation_id") or ""),
                candidate_preview_hits=int(data.get("candidate_preview_hits", 0) or 0),
            )
        self._sessions = restored

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tenant_id": self.tenant_id,
            "last_poll_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": {
                name: {
                    "name": s.name,
                    "display_name": s.name,
                    "last_content_digest": s.last_content_digest,
                    "session_key": s.session_key,
                    "last_message_time": s.last_message_time,
                    "last_unread_badge": s.last_unread_badge,
                    "unread_detected": s.unread_detected,
                    "priority_score": s.priority_score,
                    "first_seen_at": s.first_seen_at,
                    "last_seen_at": s.last_seen_at,
                    "pending_since": s.pending_since,
                    "last_detected_at": s.last_detected_at,
                    "last_dispatched_at": s.last_dispatched_at,
                    "conversation_type": s.conversation_type,
                    "preview_change_hits": int(s.preview_change_hits or 0),
                    "pending_signal_text": s.pending_signal_text,
                    "pending_signal_kind": s.pending_signal_kind,
                    "signal_ready_after": s.signal_ready_after,
                    "retry_not_before": s.retry_not_before,
                    "empty_capture_retries": int(s.empty_capture_retries or 0),
                    "startup_visual_baseline_at": s.startup_visual_baseline_at,
                    "last_observation_id": s.last_observation_id,
                    "pending_observation_id": s.pending_observation_id,
                    "acknowledged_observation_id": s.acknowledged_observation_id,
                    "acknowledged_unread_badge_epoch": int(s.acknowledged_unread_badge_epoch or 0),
                    "last_observed_unread_badge": bool(s.last_observed_unread_badge),
                    "unread_badge_epoch": int(s.unread_badge_epoch or 0),
                    "candidate_observation_id": s.candidate_observation_id,
                    "candidate_preview_hits": int(s.candidate_preview_hits or 0),
                }
                for name, s in self._sessions.items()
            },
        }
        temp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.state_path)

    def poll(self, connector: Any) -> list[ActiveTarget]:
        """Poll WeChat sessions and return prioritized list of changed targets."""
        result = connector.list_sessions()
        if not result.get("ok"):
            return []

        sessions_data = result.get("sessions", []) or []
        now_iso = datetime.now().isoformat(timespec="seconds")
        startup_visual_baseline_active = bool(self._startup_visual_baseline_active)
        active: list[ActiveTarget] = []
        unsafe_duplicate_display_names = self._unsafe_duplicate_display_names(sessions_data)

        for raw in sessions_data:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue

            # Skip sessions not in whitelist if whitelist is set
            if self.whitelist and name not in self.whitelist:
                continue
            if self.blacklist and name in self.blacklist:
                continue
            content = str(raw.get("content") or "").strip()
            msg_time = str(raw.get("time") or "").strip()
            unread_badge = str(raw.get("unread_badge") or raw.get("unread") or "").strip()
            digest = _digest(content) if content else ""
            conversation_type = _infer_conversation_type(name, raw)
            explicit_session_key = str(raw.get("session_key") or "").strip()
            session_key = session_key_from_payload(
                {
                    **raw,
                    "name": name,
                    "conversation_type": conversation_type,
                    "row_fingerprint": row_fingerprint_from_payload(raw),
                },
                fallback_name=name,
            )
            if name in unsafe_duplicate_display_names:
                self._block_ambiguous_display_name(name, now_iso=now_iso, session_key=session_key)
                continue
            if not explicit_session_key:
                session_key = self._reuse_unique_display_name_session_key(
                    name,
                    candidate_session_key=session_key,
                )
            # All runtime session state is keyed by session_key.  The display
            # name is retained only for UI/whitelist/legacy migration.
            state_key = session_key
            has_preview_signal = bool(digest or msg_time)
            has_signal = bool(has_preview_signal or unread_badge)
            has_dispatch_badge = bool(unread_badge)
            observation_id = _session_observation_id(
                raw,
                session_key=session_key,
                content=content,
                message_time=msg_time,
                unread_badge=unread_badge,
            )

            existing = self._sessions.get(state_key)
            if existing is None and state_key != name:
                legacy = self._sessions.get(name)
                if isinstance(legacy, SessionState) and (not legacy.session_key or legacy.session_key == session_key):
                    existing = legacy
                    existing.session_key = session_key
                    existing.name = name
                    self._sessions[state_key] = existing
                    self._sessions.pop(name, None)
            if existing is None:
                # New session seen for the first time
                signal_kind = self._signal_kind(content)
                short_preview_signal = self.short_preview_can_raise_unread and signal_kind == "high_sensitivity_short"
                startup_media_baseline = bool(
                    startup_visual_baseline_active
                    and signal_kind in MEDIA_CAPTURE_SIGNAL_KINDS
                    and not has_dispatch_badge
                    and not self.require_unread_badge_for_dispatch
                )
                if self.require_unread_badge_for_dispatch:
                    initial_unread = bool(
                        has_dispatch_badge
                        and (
                            not self.require_preview_signal_with_unread_badge
                            or has_preview_signal
                        )
                    )
                else:
                    initial_unread = bool(
                        unread_badge
                        or (self.initial_preview_can_raise_unread and has_signal)
                        or short_preview_signal
                    )
                if startup_media_baseline:
                    initial_unread = False
                unread_badge_epoch = 1 if has_dispatch_badge else 0
                pending_observation_id = _pending_observation_id(
                    observation_id,
                    unread_badge_epoch=unread_badge_epoch,
                )
                self._sessions[state_key] = SessionState(
                    name=name,
                    session_key=session_key,
                    last_content_digest=digest,
                    last_message_time=msg_time,
                    last_unread_badge=unread_badge,
                    unread_detected=initial_unread,
                    priority_score=60 if initial_unread else 0,
                    first_seen_at=now_iso,
                    last_seen_at=now_iso,
                    pending_since=now_iso if initial_unread else "",
                    last_detected_at=now_iso if initial_unread else "",
                    conversation_type=conversation_type,
                    preview_change_hits=0,
                    pending_signal_text=content if initial_unread else "",
                    pending_signal_kind=signal_kind if initial_unread else "",
                    signal_ready_after=self._signal_ready_after(now_iso, content) if initial_unread else "",
                    startup_visual_baseline_at=now_iso if startup_media_baseline else "",
                    last_observation_id=observation_id,
                    pending_observation_id=pending_observation_id if initial_unread else "",
                    last_observed_unread_badge=has_dispatch_badge,
                    unread_badge_epoch=unread_badge_epoch,
                )
                if initial_unread:
                    active.append(ActiveTarget(
                        name=name,
                        session_key=session_key,
                        exact=True,
                        priority_score=60,
                        unread_detected=True,
                        session_age_seconds=0,
                        conversation_type=conversation_type,
                        pending_signal_kind=signal_kind,
                        pending_signal_text=content,
                        last_message_time=msg_time,
                        unread_badge=unread_badge,
                        session_observation_id=observation_id,
                        pending_observation_id=pending_observation_id,
                    ))
            else:
                existing.name = name
                existing.session_key = session_key or existing.session_key
                previous_observation_id = str(existing.last_observation_id or "")
                previous_badge_present = bool(existing.last_observed_unread_badge)
                if has_dispatch_badge and not previous_badge_present:
                    existing.unread_badge_epoch = max(0, int(existing.unread_badge_epoch or 0)) + 1
                elif has_dispatch_badge and int(existing.unread_badge_epoch or 0) <= 0:
                    # Migration from state written before observation identities.
                    existing.unread_badge_epoch = 1
                pending_observation_id = _pending_observation_id(
                    observation_id,
                    unread_badge_epoch=int(existing.unread_badge_epoch or 0),
                )
                if existing.unread_detected and not str(existing.pending_observation_id or ""):
                    # State written before observation identities can already
                    # contain a real pending capture. Bind it to the first
                    # post-upgrade observation so reset_unread can acknowledge
                    # that legacy event instead of letting a painted badge
                    # recreate it one poll later.
                    existing.pending_observation_id = pending_observation_id
                observation_changed = bool(observation_id and observation_id != previous_observation_id)
                observation_already_acknowledged = bool(
                    pending_observation_id
                    and pending_observation_id == str(existing.acknowledged_observation_id or "")
                )
                badge_epoch_already_acknowledged = bool(
                    has_dispatch_badge
                    and int(existing.unread_badge_epoch or 0) > 0
                    and int(existing.unread_badge_epoch or 0) == int(existing.acknowledged_unread_badge_epoch or 0)
                )
                changed_by_digest = bool(digest and digest != existing.last_content_digest)
                changed_by_time = bool(msg_time and msg_time != existing.last_message_time)
                # ``reset_unread`` intentionally clears the logical pending
                # badge.  Comparing against that logical field would turn the
                # same painted dot into a fresh edge on the next poll.  The
                # physical-observation latch is the only valid badge-edge
                # source.
                changed_by_badge = bool(has_dispatch_badge and not previous_badge_present)
                changed_preview_signal = bool(changed_by_digest or changed_by_time)
                changed = bool(changed_by_digest or changed_by_time or changed_by_badge or observation_changed)

                if changed:
                    # Bump priority based on how long since last contact
                    age_seconds = 0
                    try:
                        last = datetime.fromisoformat(existing.last_seen_at.replace("Z", "+00:00"))
                        age_seconds = int((datetime.now() - last).total_seconds())
                    except Exception:
                        pass
                    priority = min(100, 50 + age_seconds // 60)
                    # A red dot that is already acknowledged can stay painted
                    # while OCR makes small preview corrections.  Require two
                    # identical post-acknowledgement preview observations
                    # before treating a text-only change as a new event.  A
                    # badge edge or a visible time change remains immediate.
                    defer_preview_confirmation = bool(
                        badge_epoch_already_acknowledged
                        and changed_preview_signal
                        and not changed_by_time
                        and not changed_by_badge
                    )
                    preview_confirmation_ready = False
                    if defer_preview_confirmation:
                        if observation_id and observation_id == str(existing.candidate_observation_id or ""):
                            existing.candidate_preview_hits = int(existing.candidate_preview_hits or 0) + 1
                        else:
                            existing.candidate_observation_id = observation_id
                            existing.candidate_preview_hits = 1
                        preview_confirmation_ready = int(existing.candidate_preview_hits or 0) >= self.preview_change_confirmations
                    else:
                        existing.candidate_observation_id = ""
                        existing.candidate_preview_hits = 0
                    if not defer_preview_confirmation or preview_confirmation_ready:
                        existing.last_content_digest = digest
                        existing.last_message_time = msg_time
                        existing.candidate_observation_id = ""
                        existing.candidate_preview_hits = 0
                    existing.session_key = existing.session_key or session_key
                    existing.last_unread_badge = unread_badge
                    existing.last_observation_id = observation_id
                    existing.last_observed_unread_badge = has_dispatch_badge
                    existing.conversation_type = conversation_type
                    existing.last_seen_at = now_iso
                    signal_kind = self._signal_kind(content)
                    media_preview_signal = signal_kind in MEDIA_CAPTURE_SIGNAL_KINDS
                    startup_media_baseline = bool(
                        startup_visual_baseline_active
                        and media_preview_signal
                        and not has_dispatch_badge
                        and not self.require_unread_badge_for_dispatch
                    )
                    should_raise_unread = False
                    if startup_media_baseline:
                        existing.startup_visual_baseline_at = now_iso
                    elif self.require_unread_badge_for_dispatch:
                        if has_dispatch_badge and (
                            not self.require_preview_signal_with_unread_badge
                            or changed_preview_signal
                            or (not existing.unread_detected and has_preview_signal)
                        ):
                            should_raise_unread = True
                            existing.preview_change_hits = 0
                        elif changed_preview_signal and not has_dispatch_badge:
                            # Voice/image previews can lose their badge when the
                            # operator opens the chat. They still need a real
                            # capture pass so the sidecar can transcribe/archive
                            # from the chat pane instead of synthesizing text.
                            if media_preview_signal:
                                should_raise_unread = True
                            existing.preview_change_hits = 0
                        elif not has_dispatch_badge:
                            existing.preview_change_hits = 0
                    elif changed_by_badge and unread_badge:
                        should_raise_unread = True
                        existing.preview_change_hits = 0
                    elif changed_by_digest or changed_by_time:
                        short_preview_signal = self.short_preview_can_raise_unread and signal_kind == "high_sensitivity_short"
                        if media_preview_signal or short_preview_signal:
                            should_raise_unread = True
                            existing.preview_change_hits = 0
                        elif self.preview_change_can_raise_unread:
                            existing.preview_change_hits = int(existing.preview_change_hits or 0) + 1
                            if existing.preview_change_hits >= self.preview_change_confirmations:
                                should_raise_unread = True
                        else:
                            # Treat ordinary preview drift as a baseline update
                            # only. This avoids foreground hopping when WeChat
                            # refreshes list previews or timestamps without a
                            # visible unread signal.
                            existing.preview_change_hits = 0
                    if defer_preview_confirmation and not preview_confirmation_ready:
                        should_raise_unread = False
                    if should_raise_unread and not observation_already_acknowledged:
                        self._mark_pending_signal(
                            existing,
                            content=content,
                            now_iso=now_iso,
                            priority=priority,
                            observation_id=pending_observation_id,
                        )
                        active.append(ActiveTarget(
                            name=name,
                            session_key=existing.session_key or session_key,
                            exact=True,
                            priority_score=priority,
                            unread_detected=True,
                            session_age_seconds=age_seconds,
                            conversation_type=conversation_type,
                            pending_signal_kind=existing.pending_signal_kind,
                            pending_signal_text=existing.pending_signal_text,
                            last_message_time=existing.last_message_time,
                            unread_badge=existing.last_unread_badge,
                            session_observation_id=observation_id,
                            pending_observation_id=existing.pending_observation_id,
                        ))
                    elif existing.unread_detected:
                        # A changed/empty sidebar preview is not evidence that
                        # the already-pending capture finished. Preserve the
                        # event until reset_unread explicitly acknowledges it.
                        active.append(ActiveTarget(
                            name=name,
                            session_key=existing.session_key or session_key,
                            exact=True,
                            priority_score=max(1, existing.priority_score),
                            unread_detected=True,
                            session_age_seconds=_age_seconds(existing.pending_since or existing.last_detected_at or existing.last_seen_at),
                            conversation_type=conversation_type,
                            pending_signal_kind=existing.pending_signal_kind,
                            pending_signal_text=existing.pending_signal_text,
                            last_message_time=existing.last_message_time,
                            unread_badge=existing.last_unread_badge,
                            session_observation_id=existing.last_observation_id,
                            pending_observation_id=existing.pending_observation_id,
                        ))
                else:
                    existing.last_seen_at = now_iso
                    existing.conversation_type = conversation_type
                    existing.last_observation_id = observation_id
                    existing.last_observed_unread_badge = has_dispatch_badge
                    if (
                        startup_visual_baseline_active
                        and self._signal_kind(content) in MEDIA_CAPTURE_SIGNAL_KINDS
                        and not has_dispatch_badge
                        and not self.require_unread_badge_for_dispatch
                    ):
                        existing.startup_visual_baseline_at = now_iso
                    if existing.last_unread_badge and not unread_badge:
                        existing.last_unread_badge = ""
                    if existing.unread_detected:
                        # No change in the session-list preview does not mean this
                        # pending session was handled. Keep it active until the
                        # workflow explicitly calls reset_unread after processing.
                        active.append(ActiveTarget(
                            name=name,
                            session_key=existing.session_key or session_key,
                            exact=True,
                            priority_score=max(1, existing.priority_score),
                            unread_detected=True,
                            session_age_seconds=_age_seconds(existing.pending_since or existing.last_detected_at or existing.last_seen_at),
                            conversation_type=conversation_type,
                            pending_signal_kind=existing.pending_signal_kind,
                            pending_signal_text=existing.pending_signal_text,
                            last_message_time=existing.last_message_time,
                            unread_badge=existing.last_unread_badge,
                            session_observation_id=existing.last_observation_id,
                            pending_observation_id=existing.pending_observation_id,
                        ))
                    else:
                        existing.preview_change_hits = 0
                        existing.priority_score = max(0, existing.priority_score - 5)

        self._startup_visual_baseline_active = False
        self._save_state()

        # Sort by priority descending, then by session_age (older = higher priority)
        active.sort(key=lambda t: (-t.priority_score, -t.session_age_seconds))
        return active[: self.max_targets_per_iteration]

    def select_dispatch_targets(self, *, limit: int | None = None) -> list[ActiveTarget]:
        """Select the next sessions to dispatch to scheduler capture.

        event_driven:
        - keep one sticky target for a short window
        - enforce min switch interval when crossing targets
        - intentionally return a small batch to reduce mechanical window hopping
        """
        pending = self.pending_targets(limit=None)
        if not pending:
            self._sticky_target = ""
            self._sticky_until_ts = 0.0
            self._sticky_dispatch_rounds = 0
            return []
        if self.dispatch_strategy == "legacy_pending_scan":
            if limit is None:
                return pending[: self.max_targets_per_iteration]
            return pending[: max(0, int(limit))]
        now_ts = time.time()
        by_key = {self._active_target_key(item): item for item in pending}
        selected: list[ActiveTarget] = []

        sticky = self._sticky_target
        if sticky and sticky in by_key and now_ts <= self._sticky_until_ts:
            should_rotate = False
            if self.sticky_max_dispatch_rounds > 0 and self._sticky_dispatch_rounds >= self.sticky_max_dispatch_rounds:
                # Avoid starving other active sessions under continuous sticky traffic.
                should_rotate = any(self._active_target_key(item) != sticky for item in pending)
            if should_rotate:
                fallback = next((item for item in pending if self._active_target_key(item) != sticky), None)
                if fallback is not None:
                    self._last_switch_at = now_ts
                    selected.append(fallback)
                    fallback_key = self._active_target_key(fallback)
                    self._last_dispatched_target = fallback_key
                    self._sticky_target = fallback_key
                    self._sticky_until_ts = now_ts + float(self.sticky_target_hold_seconds)
                    self._sticky_dispatch_rounds = 1
                else:
                    selected.append(by_key[sticky])
            else:
                selected.append(by_key[sticky])
                self._sticky_dispatch_rounds = max(1, self._sticky_dispatch_rounds + 1)
        else:
            candidate = pending[0]
            candidate_key = self._active_target_key(candidate)
            last_target = str(self._last_dispatched_target or "")
            if last_target and candidate_key != last_target:
                elapsed = now_ts - self._last_switch_at
                if elapsed < self.min_switch_interval_seconds:
                    if last_target in by_key:
                        selected.append(by_key[last_target])
                    else:
                        # Previous target already drained/cleared: switch immediately.
                        self._last_switch_at = now_ts
                        selected.append(candidate)
                else:
                    self._last_switch_at = now_ts
                    selected.append(candidate)
            else:
                if not last_target:
                    self._last_switch_at = now_ts
                selected.append(candidate)
            if selected:
                current = self._active_target_key(selected[0])
                self._last_dispatched_target = current
                self._sticky_target = current
                self._sticky_until_ts = now_ts + float(self.sticky_target_hold_seconds)
                self._sticky_dispatch_rounds = 1

        if not selected:
            return []
        try:
            cap = int(limit) if limit is not None else int(self.max_targets_per_iteration)
        except (TypeError, ValueError):
            cap = int(self.max_targets_per_iteration)
        cap = max(1, min(cap, int(self.max_targets_per_iteration)))
        if cap <= 1:
            return selected[:1]

        # Still avoid whitelist sweeps: only append sessions that already have
        # unread/pending signals. The caller serializes foreground captures and
        # applies humanized delays between real cross-chat switches.
        seen = {self._active_target_key(item) for item in selected}
        for item in pending:
            item_key = self._active_target_key(item)
            if item_key in seen:
                continue
            selected.append(item)
            seen.add(item_key)
            if len(selected) >= cap:
                break
        return selected[:cap]

    def pick_next_target(self, active: list[ActiveTarget]) -> ActiveTarget | None:
        """Respect min_switch_interval and return the highest-priority target."""
        if not active:
            return None
        now_ts = time.time()
        elapsed = now_ts - self._last_switch_at
        if elapsed < self.min_switch_interval_seconds:
            return None
        self._last_switch_at = now_ts
        return active[0]

    def _active_target_key(self, target: ActiveTarget) -> str:
        return str(getattr(target, "session_key", "") or getattr(target, "name", "") or "").strip()

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all known sessions for admin UI."""
        return [
            {
                "name": s.name,
                "session_key": s.session_key,
                "last_content_digest": s.last_content_digest,
                "last_message_time": s.last_message_time,
                "unread_detected": s.unread_detected,
                "priority_score": s.priority_score,
                "first_seen_at": s.first_seen_at,
                "last_seen_at": s.last_seen_at,
                "pending_since": s.pending_since,
                "last_detected_at": s.last_detected_at,
                "last_dispatched_at": s.last_dispatched_at,
                "conversation_type": s.conversation_type,
                "pending_signal_text": s.pending_signal_text,
                "preview_content": s.pending_signal_text,
                "pending_signal_kind": s.pending_signal_kind,
                "signal_ready_after": s.signal_ready_after,
                "retry_not_before": s.retry_not_before,
                "empty_capture_retries": int(s.empty_capture_retries or 0),
                "startup_visual_baseline_at": s.startup_visual_baseline_at,
                "last_observation_id": s.last_observation_id,
                "pending_observation_id": s.pending_observation_id,
                "acknowledged_observation_id": s.acknowledged_observation_id,
                "acknowledged_unread_badge_epoch": int(s.acknowledged_unread_badge_epoch or 0),
                "last_observed_unread_badge": bool(s.last_observed_unread_badge),
                "unread_badge_epoch": int(s.unread_badge_epoch or 0),
                "candidate_observation_id": s.candidate_observation_id,
                "candidate_preview_hits": int(s.candidate_preview_hits or 0),
            }
            for s in self._sessions.values()
        ]

    def pending_targets(self, *, limit: int | None = None) -> list[ActiveTarget]:
        """Return all sessions still waiting for workflow processing."""
        active = [
            ActiveTarget(
                name=s.name,
                session_key=s.session_key,
                exact=True,
                priority_score=max(1, s.priority_score),
                unread_detected=True,
                session_age_seconds=_age_seconds(s.pending_since or s.last_detected_at or s.last_seen_at),
                conversation_type=s.conversation_type or "unknown",
                pending_signal_kind=s.pending_signal_kind or "",
                pending_signal_text=s.pending_signal_text or "",
                last_message_time=s.last_message_time or "",
                unread_badge=s.last_unread_badge or "",
                session_observation_id=s.last_observation_id or "",
                pending_observation_id=s.pending_observation_id or "",
            )
            for s in self._sessions.values()
            if s.unread_detected
            and (not self.whitelist or s.name in self.whitelist)
            and (not self.blacklist or s.name not in self.blacklist)
            and self._signal_ready_for_dispatch(s)
        ]
        active.sort(key=lambda t: (-t.priority_score, -t.session_age_seconds))
        if limit is None:
            return active
        return active[: max(0, int(limit))]

    def reset_unread(
        self,
        name: str,
        *,
        preserve_pending: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Mark a session handled, or preserve its pending signal for retry."""
        session = self._session_by_identifier(name)
        if session is not None:
            now = datetime.now()
            now_iso = now.isoformat(timespec="seconds")
            if preserve_pending:
                session.unread_detected = True
                session.priority_score = max(60, int(session.priority_score or 0))
                if not session.pending_since:
                    session.pending_since = now_iso
                session.last_detected_at = now_iso
                session.last_dispatched_at = now_iso
                session.empty_capture_retries = int(session.empty_capture_retries or 0) + 1
                delay = self._empty_capture_retry_delay(session, retry_after_seconds=retry_after_seconds)
                if delay > 0:
                    session.retry_not_before = (now + timedelta(seconds=delay)).isoformat(timespec="milliseconds")
                session.signal_ready_after = ""
            else:
                # A reset is the explicit acknowledgement of the current
                # sidebar event.  Do not clear the raw-observation/badge-edge
                # latch: a red dot that remains painted after the capture is
                # still the same event and must not be re-enqueued next poll.
                if session.pending_observation_id:
                    session.acknowledged_observation_id = session.pending_observation_id
                if session.last_observed_unread_badge:
                    session.acknowledged_unread_badge_epoch = int(session.unread_badge_epoch or 0)
                session.unread_detected = False
                session.priority_score = 0
                session.pending_since = ""
                session.last_unread_badge = ""
                session.preview_change_hits = 0
                session.pending_signal_text = ""
                session.pending_signal_kind = ""
                session.pending_observation_id = ""
                session.candidate_observation_id = ""
                session.candidate_preview_hits = 0
                session.signal_ready_after = ""
                session.retry_not_before = ""
                session.empty_capture_retries = 0
                session.last_dispatched_at = now_iso
            self._save_state()

    def should_preserve_pending_after_empty_capture(self, name: str) -> bool:
        session = self._session_by_identifier(name)
        if not isinstance(session, SessionState):
            return False
        if not session.unread_detected:
            return False
        if session.pending_signal_kind == "high_sensitivity_short":
            return True
        if session.pending_signal_kind in MEDIA_CAPTURE_SIGNAL_KINDS:
            return int(session.empty_capture_retries or 0) < 3
        if int(session.empty_capture_retries or 0) >= 2:
            return False
        return bool(
            str(session.pending_signal_text or "").strip()
            or str(session.last_unread_badge or "").strip()
            or str(session.pending_since or "").strip()
        )

    def _session_by_identifier(self, value: str) -> SessionState | None:
        key = str(value or "").strip()
        if not key:
            return None
        session = self._sessions.get(key)
        if isinstance(session, SessionState):
            return session
        matches = [item for item in self._sessions.values() if item.name == key or item.session_key == key]
        if len(matches) == 1:
            return matches[0]
        return None

    def _reuse_unique_display_name_session_key(self, name: str, *, candidate_session_key: str) -> str:
        """Repair inferred type drift without weakening duplicate-name isolation."""

        generated_matches = [
            (key, state)
            for key, state in self._sessions.items()
            if isinstance(state, SessionState)
            and state.name == name
            and str(key).startswith("wx:rpa:v1:")
        ]
        if not generated_matches:
            return candidate_session_key
        if len(generated_matches) == 1:
            return str(generated_matches[0][0])

        scored: list[tuple[tuple[int, int, int], str, SessionState]] = []
        for key, state in generated_matches:
            ledger_summary = self._ledger.load_summary(str(key))
            recent_count = len(ledger_summary.get("recent_messages") or []) if isinstance(ledger_summary, dict) else 0
            try:
                context_version = int((ledger_summary or {}).get("context_version") or 0)
            except (TypeError, ValueError):
                context_version = 0
            candidate_bonus = 1 if str(key) == str(candidate_session_key) else 0
            scored.append(((recent_count, context_version, candidate_bonus), str(key), state))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        canonical_key = scored[0][1]
        canonical_state = scored[0][2]
        alias_keys = [key for _score, key, _state in scored[1:]]
        try:
            self._ledger.merge_session_alias_context(
                canonical_session_key=canonical_key,
                alias_session_keys=alias_keys,
                target_name=name,
            )
        except Exception:
            # Monitor identity repair must not block capture; the alias ledger
            # remains available for a later retry/audit if persistence fails.
            pass
        for _score, key, state in scored[1:]:
            canonical_state.unread_detected = bool(canonical_state.unread_detected or state.unread_detected)
            canonical_state.priority_score = max(int(canonical_state.priority_score or 0), int(state.priority_score or 0))
            canonical_state.preview_change_hits = max(
                int(canonical_state.preview_change_hits or 0),
                int(state.preview_change_hits or 0),
            )
            canonical_state.empty_capture_retries = max(
                int(canonical_state.empty_capture_retries or 0),
                int(state.empty_capture_retries or 0),
            )
            for field_name in (
                "first_seen_at",
                "pending_since",
                "last_detected_at",
                "last_dispatched_at",
                "pending_signal_text",
                "pending_signal_kind",
                "signal_ready_after",
                "retry_not_before",
            ):
                if not getattr(canonical_state, field_name) and getattr(state, field_name):
                    setattr(canonical_state, field_name, getattr(state, field_name))
            self._sessions.pop(key, None)
        canonical_state.session_key = canonical_key
        canonical_state.name = name
        self._sessions[canonical_key] = canonical_state
        return canonical_key

    def _mark_pending_signal(
        self,
        session: SessionState,
        *,
        content: str,
        now_iso: str,
        priority: int,
        observation_id: str = "",
    ) -> None:
        session.unread_detected = True
        if not session.pending_since:
            session.pending_since = now_iso
        session.last_detected_at = now_iso
        session.priority_score = priority
        session.pending_signal_text = str(content or "").strip()
        session.pending_signal_kind = self._signal_kind(content)
        session.pending_observation_id = str(observation_id or session.pending_observation_id or "")
        session.signal_ready_after = self._signal_ready_after(now_iso, content)
        session.retry_not_before = ""
        session.empty_capture_retries = 0

    def _signal_kind(self, content: str) -> str:
        media_kind = _media_capture_signal_kind(content)
        if media_kind:
            return media_kind
        if _is_high_sensitivity_short_signal(content, max_chars=self.high_sensitivity_short_max_chars):
            return "high_sensitivity_short"
        return "normal"

    def _signal_ready_after(self, now_iso: str, content: str) -> str:
        if self._signal_kind(content) != "high_sensitivity_short":
            return ""
        if self.high_sensitivity_short_merge_window_seconds <= 0:
            return ""
        base = datetime.now()
        try:
            parsed = datetime.fromisoformat(now_iso)
            if getattr(parsed, "tzinfo", None) is not None:
                parsed = parsed.replace(tzinfo=None)
            if parsed > base:
                base = parsed
        except ValueError:
            pass
        return (base + timedelta(seconds=self.high_sensitivity_short_merge_window_seconds)).isoformat(timespec="milliseconds")

    def _signal_ready_for_dispatch(self, session: SessionState) -> bool:
        now = datetime.now()
        if session.retry_not_before:
            retry_ts = _parse_iso_datetime(session.retry_not_before)
            if retry_ts is not None and retry_ts > now:
                return False
        if session.signal_ready_after:
            ready_ts = _parse_iso_datetime(session.signal_ready_after)
            if ready_ts is not None and ready_ts > now:
                return False
        return True

    def _read_preview_change_should_dispatch(self, session: SessionState, *, content: str, msg_time: str) -> bool:
        """Return whether a badge-less preview change still deserves capture.

        In RPA mode the program may click a conversation to read it before the
        scheduler tick runs.  That clears the unread badge, but the preview text
        or time can still be the only durable signal that this monitored session
        has new customer content.  This method belongs to the code mechanism
        layer: it only preserves a pending capture and never authors replies.
        """

        name = str(session.name or "").strip()
        if self.whitelist and name not in self.whitelist:
            return False
        if self.blacklist and name in self.blacklist:
            return False
        if session.unread_detected:
            return True
        if str(session.pending_since or "").strip():
            return True
        if not (str(content or "").strip() or str(msg_time or "").strip()):
            return False
        if self._signal_kind(content) in MEDIA_CAPTURE_SIGNAL_KINDS:
            return True
        if self._signal_kind(content) == "high_sensitivity_short":
            return True
        if not str(session.last_dispatched_at or "").strip():
            return True
        if msg_time and msg_time != session.last_message_time:
            return True
        return bool(content)

    def _unsafe_duplicate_display_names(self, sessions_data: list[Any]) -> set[str]:
        """Return duplicate display names whose row identities are not unique.

        Duplicate names are safe only when every visible row has a distinct
        session key.  If the keys collide, dispatch would fall back to a
        name-like identity and can cross-send under same-name chats.
        """

        counts_by_name: dict[str, int] = {}
        keys_by_name: dict[str, set[str]] = {}
        for raw in sessions_data:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            if self.whitelist and name not in self.whitelist:
                continue
            if self.blacklist and name in self.blacklist:
                continue
            conversation_type = _infer_conversation_type(name, raw)
            session_key = session_key_from_payload(
                {
                    **raw,
                    "name": name,
                    "conversation_type": conversation_type,
                    "row_fingerprint": row_fingerprint_from_payload(raw),
                },
                fallback_name=name,
            )
            counts_by_name[name] = int(counts_by_name.get(name, 0)) + 1
            keys_by_name.setdefault(name, set()).add(session_key)
        return {
            name
            for name, count in counts_by_name.items()
            if count > 1 and len({item for item in keys_by_name.get(name, set()) if item}) < count
        }

    def _block_ambiguous_display_name(self, name: str, *, now_iso: str, session_key: str = "") -> None:
        key = str(session_key or name or "").strip()
        session = self._sessions.get(key)
        if session is None:
            session = SessionState(
                name=name,
                session_key=session_key,
                first_seen_at=now_iso,
                last_seen_at=now_iso,
                conversation_type="unknown",
            )
            self._sessions[key] = session
        session.last_seen_at = now_iso
        session.unread_detected = False
        session.priority_score = 0
        session.pending_since = ""
        session.last_detected_at = ""
        session.preview_change_hits = 0
        session.pending_signal_text = ""
        session.pending_signal_kind = "ambiguous_duplicate_name"
        session.signal_ready_after = ""
        session.retry_not_before = ""
        session.empty_capture_retries = 0

    def _empty_capture_retry_delay(self, session: SessionState, *, retry_after_seconds: float | None = None) -> float:
        base = self.empty_capture_retry_seconds if retry_after_seconds is None else max(0.0, float(retry_after_seconds))
        if base <= 0:
            return 0.0
        retries = max(0, int(session.empty_capture_retries or 0) - 1)
        delay = base * (self.empty_capture_retry_backoff_multiplier ** retries)
        return min(self.empty_capture_retry_max_seconds, delay)


def _session_observation_id(
    raw: dict[str, Any],
    *,
    session_key: str,
    content: str,
    message_time: str,
    unread_badge: str,
) -> str:
    """Return a stable identity for one sidebar observation.

    The sidecar may supply a richer deterministic identity.  Other connectors
    retain compatibility through a local canonical digest.  Poll time, OCR run
    time, and screenshot paths are intentionally excluded: they describe a
    new *measurement*, not a new customer event.
    """

    supplied = str(raw.get("session_observation_id") or "").strip()
    if supplied:
        return supplied
    evidence = raw.get("unread_badge_evidence") if isinstance(raw.get("unread_badge_evidence"), dict) else {}
    raw_box = evidence.get("bbox") or evidence.get("red_box") or []
    box = [int(value) // 4 for value in raw_box[:4] if isinstance(value, (int, float))]
    row = raw.get("row_fingerprint") if isinstance(raw.get("row_fingerprint"), dict) else {}
    seed = {
        "session_key": str(session_key or ""),
        "content": " ".join(str(content or "").split()),
        "time": str(message_time or "").strip(),
        "unread_badge": str(unread_badge or "").strip(),
        "badge_box": box,
        "row_y_bucket": row.get("row_y_bucket"),
        "duplicate_discriminator": row.get("duplicate_discriminator"),
    }
    encoded = json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "session-observation:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def _pending_observation_id(observation_id: str, *, unread_badge_epoch: int) -> str:
    """Turn a stable sidebar observation into a stable event identity.

    A badge disappearing and later reappearing is a real new trigger even when
    WeChat clips the visible preview to the same text and minute.  The epoch
    records that rising edge without treating every later poll as new.
    """

    seed = f"{str(observation_id or '').strip()}|badge_epoch:{max(0, int(unread_badge_epoch or 0))}"
    return "pending-observation:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _age_seconds(value: str) -> int:
    if not value:
        return 0
    try:
        base = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if getattr(base, "tzinfo", None) is not None:
            base = base.replace(tzinfo=None)
        return max(0, int((datetime.now() - base).total_seconds()))
    except Exception:
        return 0


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if getattr(parsed, "tzinfo", None) is not None:
            return parsed.replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def _normalize_short_signal_text(text: str) -> str:
    compact = "".join(str(text or "").split())
    compact = "".join(ch for ch in compact if ch not in "，。,.！？!、~～：:；;“”\"'（）()[]【】")
    return compact.strip().lower()


def _media_capture_signal_kind(text: str) -> str:
    raw = str(text or "").strip().lower()
    compact = _normalize_short_signal_text(raw)
    if not compact:
        return ""
    voice_tokens = {"语音", "语音消息", "voice", "voicemessage", "audio", "audiomessage"}
    image_tokens = {"图片", "图片消息", "照片", "图像", "image", "photo", "picture", "pic"}
    media_tokens = {"视频", "视频消息", "video", "文件", "文件消息", "file", "表情", "sticker", "emoji"}
    if any(token in raw for token in ("[语音]", "【语音】", "[voice]", "[audio]")) or compact in voice_tokens:
        return "voice_capture"
    if any(token in raw for token in ("[图片]", "【图片】", "[image]", "[photo]", "[picture]")) or compact in image_tokens:
        return "image_capture"
    if (
        any(token in raw for token in ("[视频]", "【视频】", "[video]", "[文件]", "【文件】", "[file]", "[表情]", "【表情】"))
        or compact in media_tokens
    ):
        return "media_capture"
    return ""


def _is_high_sensitivity_short_signal(text: str, *, max_chars: int) -> bool:
    compact = _normalize_short_signal_text(text)
    return bool(compact) and len(compact) <= max(1, int(max_chars or 7))


def _infer_conversation_type(name: str, session: dict[str, Any]) -> str:
    explicit = str(session.get("conversation_type") or session.get("type") or "").strip().lower()
    if explicit in {"private", "group", "file_transfer", "system"}:
        return explicit
    if name in {"文件传输助手", "File Transfer"}:
        return "file_transfer"
    if "群" in name or "chatroom" in name.lower() or "room" in name.lower():
        return "group"
    if any(keyword in name for keyword in ("微信团队", "系统消息", "服务通知", "订阅号")):
        return "system"
    return "private"
