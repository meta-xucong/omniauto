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
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


@dataclass
class SessionState:
    name: str
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


@dataclass
class ActiveTarget:
    name: str
    exact: bool = True
    priority_score: int = 0
    unread_detected: bool = False
    session_age_seconds: int = 0
    conversation_type: str = "unknown"


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
        self._last_switch_at: float = 0.0
        self._last_dispatched_target: str = ""
        self._sticky_target: str = ""
        self._sticky_until_ts: float = 0.0
        self._sticky_dispatch_rounds: int = 0
        self._sessions: dict[str, SessionState] = {}
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
        self._sessions = {
            str(name): SessionState(
                name=str(name),
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
            )
            for name, data in raw.items()
            if isinstance(data, dict)
        }

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tenant_id": self.tenant_id,
            "last_poll_at": datetime.now().isoformat(timespec="seconds"),
            "sessions": {
                name: {
                    "last_content_digest": s.last_content_digest,
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
        active: list[ActiveTarget] = []

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
            has_signal = bool(digest or msg_time or unread_badge)

            existing = self._sessions.get(name)
            if existing is None:
                # New session seen for the first time
                initial_unread = bool(unread_badge or has_signal)
                self._sessions[name] = SessionState(
                    name=name,
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
                )
                if initial_unread:
                    active.append(ActiveTarget(
                        name=name,
                        exact=True,
                        priority_score=60,
                        unread_detected=True,
                        session_age_seconds=0,
                        conversation_type=conversation_type,
                    ))
            else:
                changed_by_digest = bool(digest and digest != existing.last_content_digest)
                changed_by_time = bool(msg_time and msg_time != existing.last_message_time)
                changed_by_badge = bool(unread_badge and unread_badge != existing.last_unread_badge)
                changed = bool(changed_by_digest or changed_by_time or changed_by_badge)

                if changed:
                    # Bump priority based on how long since last contact
                    age_seconds = 0
                    try:
                        last = datetime.fromisoformat(existing.last_seen_at.replace("Z", "+00:00"))
                        age_seconds = int((datetime.now() - last).total_seconds())
                    except Exception:
                        pass
                    priority = min(100, 50 + age_seconds // 60)
                    existing.last_content_digest = digest
                    existing.last_message_time = msg_time
                    existing.last_unread_badge = unread_badge
                    existing.conversation_type = conversation_type
                    existing.last_seen_at = now_iso
                    should_raise_unread = False
                    if changed_by_badge and unread_badge:
                        should_raise_unread = True
                        existing.preview_change_hits = 0
                    elif changed_by_digest or changed_by_time:
                        existing.preview_change_hits = int(existing.preview_change_hits or 0) + 1
                        if existing.preview_change_hits >= self.preview_change_confirmations:
                            should_raise_unread = True
                    if should_raise_unread:
                        existing.unread_detected = True
                        if not existing.pending_since:
                            existing.pending_since = now_iso
                        existing.last_detected_at = now_iso
                        existing.priority_score = priority
                        active.append(ActiveTarget(
                            name=name,
                            exact=True,
                            priority_score=priority,
                            unread_detected=True,
                            session_age_seconds=age_seconds,
                            conversation_type=conversation_type,
                        ))
                else:
                    existing.last_seen_at = now_iso
                    existing.conversation_type = conversation_type
                    if existing.last_unread_badge and not unread_badge:
                        existing.last_unread_badge = ""
                    if existing.unread_detected:
                        # No change in the session-list preview does not mean this
                        # pending session was handled. Keep it active until the
                        # workflow explicitly calls reset_unread after processing.
                        active.append(ActiveTarget(
                            name=name,
                            exact=True,
                            priority_score=max(1, existing.priority_score),
                            unread_detected=True,
                            session_age_seconds=_age_seconds(existing.pending_since or existing.last_detected_at or existing.last_seen_at),
                            conversation_type=conversation_type,
                        ))
                    else:
                        existing.preview_change_hits = 0
                        existing.priority_score = max(0, existing.priority_score - 5)

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
        by_name = {item.name: item for item in pending}
        selected: list[ActiveTarget] = []

        sticky = self._sticky_target
        if sticky and sticky in by_name and now_ts <= self._sticky_until_ts:
            should_rotate = False
            if self.sticky_max_dispatch_rounds > 0 and self._sticky_dispatch_rounds >= self.sticky_max_dispatch_rounds:
                # Avoid starving other active sessions under continuous sticky traffic.
                should_rotate = any(item.name != sticky for item in pending)
            if should_rotate:
                fallback = next((item for item in pending if item.name != sticky), None)
                if fallback is not None:
                    self._last_switch_at = now_ts
                    selected.append(fallback)
                    self._last_dispatched_target = fallback.name
                    self._sticky_target = fallback.name
                    self._sticky_until_ts = now_ts + float(self.sticky_target_hold_seconds)
                    self._sticky_dispatch_rounds = 1
                else:
                    selected.append(by_name[sticky])
            else:
                selected.append(by_name[sticky])
                self._sticky_dispatch_rounds = max(1, self._sticky_dispatch_rounds + 1)
        else:
            candidate = pending[0]
            last_target = str(self._last_dispatched_target or "")
            if last_target and candidate.name != last_target:
                elapsed = now_ts - self._last_switch_at
                if elapsed < self.min_switch_interval_seconds:
                    if last_target in by_name:
                        selected.append(by_name[last_target])
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
                current = selected[0].name
                self._last_dispatched_target = current
                self._sticky_target = current
                self._sticky_until_ts = now_ts + float(self.sticky_target_hold_seconds)
                self._sticky_dispatch_rounds = 1

        if not selected:
            return []
        # In low-disturbance mode we intentionally dispatch one foreground target per turn.
        return selected[:1]

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

    def all_sessions(self) -> list[dict[str, Any]]:
        """Return all known sessions for admin UI."""
        return [
            {
                "name": s.name,
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
            }
            for s in self._sessions.values()
        ]

    def pending_targets(self, *, limit: int | None = None) -> list[ActiveTarget]:
        """Return all sessions still waiting for workflow processing."""
        active = [
            ActiveTarget(
                name=s.name,
                exact=True,
                priority_score=max(1, s.priority_score),
                unread_detected=True,
                session_age_seconds=_age_seconds(s.pending_since or s.last_detected_at or s.last_seen_at),
                conversation_type=s.conversation_type or "unknown",
            )
            for s in self._sessions.values()
            if s.unread_detected
            and (not self.whitelist or s.name in self.whitelist)
            and (not self.blacklist or s.name not in self.blacklist)
        ]
        active.sort(key=lambda t: (-t.priority_score, -t.session_age_seconds))
        if limit is None:
            return active
        return active[: max(0, int(limit))]

    def reset_unread(self, name: str) -> None:
        """Mark a session as read after processing."""
        if name in self._sessions:
            self._sessions[name].unread_detected = False
            self._sessions[name].priority_score = 0
            self._sessions[name].pending_since = ""
            self._sessions[name].last_unread_badge = ""
            self._sessions[name].preview_change_hits = 0
            self._sessions[name].last_dispatched_at = datetime.now().isoformat(timespec="seconds")
            self._save_state()


def _digest(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:32]


def _age_seconds(value: str) -> int:
    if not value:
        return 0
    try:
        base = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0, int((datetime.now() - base).total_seconds()))
    except Exception:
        return 0


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
