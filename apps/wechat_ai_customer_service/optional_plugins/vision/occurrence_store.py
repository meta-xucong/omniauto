"""Vision-owned cross-process visual occurrence store.

The store is deliberately private to the optional Vision plugin.  It keeps a
short-lived, bounded observation cache that can be shared by separate vision
workers without adding cache tokens, coordinates, hashes, or anchors to public
messages, Brain payloads, or scheduler state.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .capture.visual_anchor import (
    select_pending_visual_candidate,
    visual_candidate_from_parts,
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _now() -> float:
    return float(time.time())


def _safe_digest(payload: Any, *, length: int = 32) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:length]


def default_occurrence_store_root() -> Path:
    env_value = os.environ.get("WECHAT_VISION_OCCURRENCE_STORE_DIR", "").strip()
    if env_value:
        return Path(env_value)
    project_root = Path(__file__).resolve().parents[4]
    return project_root / "runtime" / "apps" / "wechat_ai_customer_service" / "vision_occurrence_store"


class VisualOccurrenceStore:
    """Small file-backed TTL store for pending-aware visual occurrences."""

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        ttl_seconds: float = 120.0,
        claim_ttl_seconds: float = 30.0,
        max_records: int = 200,
        max_records_per_session: int | None = None,
    ) -> None:
        self.root = Path(root) if root is not None else default_occurrence_store_root()
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self.claim_ttl_seconds = max(0.0, float(claim_ttl_seconds))
        self.max_records = max(1, int(max_records))
        self.max_records_per_session = max(
            1,
            int(max_records if max_records_per_session is None else max_records_per_session),
        )

    def record_occurrences(
        self,
        candidates: list[dict[str, Any]],
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist current surface candidates as private pending records.

        Candidate-specific identity fields override the request so that a
        mixed test surface cannot accidentally be collapsed into one session or
        target.  Missing candidate fields are filled from the request, which is
        how a fresh surface observation can be bound to the scheduler's pending
        signal/observation identity inside Vision only.
        """

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._cleanup_expired()
        except OSError as exc:
            return {"ok": False, "reason": "visual_occurrence_store_unavailable", "error": repr(exc)}

        written = 0
        skipped = 0
        errors: list[str] = []
        base = dict(request or {})
        now = _now()
        for raw in candidates or []:
            if not isinstance(raw, dict):
                continue
            candidate = visual_candidate_from_parts(_merge_nonempty_candidate_overrides(base, raw))
            record_id = _record_id(candidate)
            path = self._record_path(record_id)
            try:
                existing = self._read_existing_record(path)
                if bool(existing.get("consumed")):
                    skipped += 1
                    continue
                if self._active_claim_exists(record_id):
                    skipped += 1
                    continue
                record = {
                    **existing,
                    **candidate,
                    "record_id": record_id,
                    "recorded_at": float(existing.get("recorded_at") or now),
                    "last_observed_at": now,
                    "expires_at": now + self.ttl_seconds,
                    "consumed": False,
                }
                self._atomic_write_json(path, record)
                written += 1
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append(repr(exc))
        try:
            self._enforce_bound()
        except OSError as exc:
            errors.append(repr(exc))
        return {
            "ok": not errors,
            "reason": "visual_occurrence_store_recorded" if not errors else "visual_occurrence_store_record_partial",
            "recorded_count": written,
            "skipped_count": skipped,
            "error_count": len(errors),
        }

    def claim_best_match(self, request: dict[str, Any] | None = None) -> dict[str, Any]:
        """Claim one matching record, or fail closed without raising."""

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._cleanup_expired()
            records = self._load_records()
        except OSError as exc:
            return {"ok": False, "reason": "visual_occurrence_store_unavailable", "error": repr(exc)}
        data = dict(request or {})
        selection = select_pending_visual_candidate(
            records,
            data,
            minimum_score=70.0,
            minimum_margin=16.0,
        )
        if not selection.get("ok"):
            return {
                "ok": False,
                "reason": "visual_occurrence_store_no_match",
                "selector_reason": selection.get("reason"),
            }
        record = dict(selection.get("candidate") or {})
        record_id = _clean(record.get("record_id"))
        if not record_id:
            return {"ok": False, "reason": "visual_occurrence_store_no_match", "selector_reason": "record_id_missing"}
        claim = self._try_claim(record_id)
        if not claim.get("ok"):
            return {
                "ok": False,
                "reason": "visual_occurrence_store_no_match",
                "claim_reason": claim.get("reason"),
            }
        record["claim_id"] = claim.get("claim_id")
        return {
            "ok": True,
            "reason": "visual_occurrence_store_claimed",
            "record": record,
            "claim_id": claim.get("claim_id"),
            "selector": {
                "reason": selection.get("reason"),
                "score": selection.get("score"),
                "margin": selection.get("margin"),
            },
        }

    def consume_claim(self, record_id: str, claim_id: str, *, success: bool = True) -> dict[str, Any]:
        """Mark a claimed record consumed when the copy transaction succeeds."""

        clean_record_id = _clean(record_id)
        clean_claim_id = _clean(claim_id)
        if not clean_record_id or not clean_claim_id:
            return {"ok": False, "reason": "visual_occurrence_store_claim_identity_missing"}
        try:
            claim = self._read_json(self._claim_path(clean_record_id))
            if _clean(claim.get("claim_id")) != clean_claim_id:
                return {"ok": False, "reason": "visual_occurrence_store_claim_mismatch"}
            if float(claim.get("expires_at") or 0.0) <= _now():
                self._unlink_quietly(self._claim_path(clean_record_id))
                return {"ok": False, "reason": "visual_occurrence_store_claim_expired"}
            record = self._read_json(self._record_path(clean_record_id))
            record["consumed"] = bool(success)
            if success:
                record["consumed_at"] = _now()
                reason = "visual_occurrence_store_consumed"
            else:
                record["last_claim_failed_at"] = _now()
                reason = "visual_occurrence_store_claim_released"
            self._atomic_write_json(self._record_path(clean_record_id), record)
            self._unlink_quietly(self._claim_path(clean_record_id))
            return {"ok": True, "reason": reason}
        except (OSError, ValueError) as exc:
            return {"ok": False, "reason": "visual_occurrence_store_consume_failed", "error": repr(exc)}

    def _record_path(self, record_id: str) -> Path:
        return self.root / f"{_safe_name(record_id)}.json"

    def _claim_path(self, record_id: str) -> Path:
        return self.root / f"{_safe_name(record_id)}.claim"

    def _atomic_write_json(self, path: Path, data: dict[str, Any]) -> None:
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp_path), str(path))

    def _read_json(self, path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}

    def _read_existing_record(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        value = self._read_json(path)
        return value if isinstance(value, dict) else {}

    def _load_records(self) -> list[dict[str, Any]]:
        now = _now()
        records: list[dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                record = self._read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if not record:
                continue
            if float(record.get("expires_at") or 0.0) <= now:
                continue
            if bool(record.get("consumed")):
                continue
            records.append(record)
        return records

    def _active_claim_exists(self, record_id: str) -> bool:
        claim_path = self._claim_path(record_id)
        if not claim_path.exists():
            return False
        if self._claim_expired(claim_path):
            self._unlink_quietly(claim_path)
            return False
        return True

    def _try_claim(self, record_id: str) -> dict[str, Any]:
        claim_path = self._claim_path(record_id)
        claim_id = uuid.uuid4().hex
        payload = {
            "record_id": record_id,
            "claim_id": claim_id,
            "claimed_at": _now(),
            "expires_at": _now() + self.claim_ttl_seconds,
        }
        for _attempt in range(2):
            try:
                fd = os.open(str(claim_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                if self._claim_expired(claim_path):
                    try:
                        claim_path.unlink()
                    except OSError:
                        return {"ok": False, "reason": "visual_occurrence_store_claim_locked"}
                    continue
                return {"ok": False, "reason": "visual_occurrence_store_claim_locked"}
            except OSError as exc:
                return {"ok": False, "reason": "visual_occurrence_store_claim_failed", "error": repr(exc)}
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                return {"ok": True, "reason": "visual_occurrence_store_claimed", "claim_id": claim_id}
            except OSError as exc:
                return {"ok": False, "reason": "visual_occurrence_store_claim_failed", "error": repr(exc)}
        return {"ok": False, "reason": "visual_occurrence_store_claim_locked"}

    def _claim_expired(self, path: Path) -> bool:
        try:
            payload = self._read_json(path)
            return float(payload.get("expires_at") or 0.0) <= _now()
        except (OSError, ValueError, json.JSONDecodeError):
            return True

    def _cleanup_expired(self) -> None:
        now = _now()
        for path in list(self.root.glob("*.claim")):
            if self._claim_expired(path):
                try:
                    path.unlink()
                except OSError:
                    pass
        for path in list(self.root.glob("*.json")):
            try:
                record = self._read_json(path)
                expired = float(record.get("expires_at") or 0.0) <= now
            except (OSError, ValueError, json.JSONDecodeError):
                expired = False
            if expired:
                self._unlink_quietly(path)

    def _enforce_bound(self) -> None:
        entries: list[tuple[Path, dict[str, Any], float]] = []
        for path in self.root.glob("*.json"):
            try:
                record = self._read_json(path)
                modified = float(path.stat().st_mtime)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            entries.append((path, record, modified))
        deleted: set[Path] = set()
        by_session: dict[tuple[str, str, str], list[tuple[Path, dict[str, Any], float]]] = {}
        for entry in entries:
            record = entry[1]
            scope = (
                _clean(record.get("session_key")),
                _clean(record.get("target_identity")),
                _clean(record.get("conversation_type")),
            )
            by_session.setdefault(scope, []).append(entry)
        for scoped_entries in by_session.values():
            scoped_entries.sort(key=lambda item: item[2], reverse=True)
            for path, record, _modified in scoped_entries[self.max_records_per_session :]:
                if path in deleted or self._active_claim_exists(_clean(record.get("record_id"))):
                    continue
                self._unlink_quietly(path)
                deleted.add(path)
        remaining = [entry for entry in entries if entry[0] not in deleted and entry[0].exists()]
        remaining.sort(key=lambda item: item[2], reverse=True)
        for path, record, _modified in remaining[self.max_records :]:
            if self._active_claim_exists(_clean(record.get("record_id"))):
                continue
            self._unlink_quietly(path)

    def _unlink_quietly(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _safe_name(value: str) -> str:
    clean = _clean(value)
    if clean and all(ch.isalnum() or ch in {"-", "_"} for ch in clean):
        return clean[:80]
    return _safe_digest(clean or uuid.uuid4().hex)


def _meaningful(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _merge_nonempty_candidate_overrides(base: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (raw or {}).items():
        if _meaningful(value):
            merged[key] = value
        elif key not in merged:
            merged[key] = value
    for key, marker in (
        ("pending_signal_id", "_vision_pending_signal_id_inherited_from_request"),
        ("pending_observation_id", "_vision_pending_observation_id_inherited_from_request"),
    ):
        if _meaningful((base or {}).get(key)) and not _meaningful((raw or {}).get(key)):
            merged[marker] = True
    return merged


def _record_id(candidate: dict[str, Any]) -> str:
    visual_identity = (
        _clean(candidate.get("structural_message_id"))
        or _clean(candidate.get("source_message_id"))
        or _clean(candidate.get("message_id"))
        or _clean(candidate.get("visual_structural_key"))
        or _clean(candidate.get("visual_stable_key"))
    )
    seed = {
        "session_key": _clean(candidate.get("session_key")),
        "target_identity": _clean(candidate.get("target_identity")),
        "conversation_type": _clean(candidate.get("conversation_type")),
        "side": _clean(candidate.get("side")),
        "pending_signal_id": _clean(candidate.get("pending_signal_id")),
        "pending_observation_id": _clean(candidate.get("pending_observation_id")),
        "visual_identity": visual_identity,
    }
    return "visual-record-" + _safe_digest(seed, length=24)


def default_occurrence_store() -> VisualOccurrenceStore:
    return VisualOccurrenceStore()
