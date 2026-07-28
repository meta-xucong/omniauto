"""Vision-private visual occurrence identity and selector helpers.

This module intentionally does not import voice, Brain, scheduler, provider,
clipboard, or Win32 implementations.  It is an internal helper for the Vision
plugin's pending-aware image capture path.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _lower(value: Any) -> str:
    return _clean(value).lower()


def _digest(prefix: str, payload: Any, *, length: int = 20) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return f"{prefix}:" + hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:length]


def visual_text_key(value: Any) -> str:
    text = re.sub(r"\s+", "", _clean(value)).lower()
    return text


def _bounds(value: Any) -> list[int]:
    try:
        values = [int(round(float(item))) for item in list(value or [])[:4]]
    except (TypeError, ValueError):
        return []
    if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
        return []
    return values


def _bounds_bucket(bounds: list[int], *, bucket: int = 24) -> list[int]:
    if not bounds:
        return []
    return [int(round(value / float(bucket))) for value in bounds[:4]]


def _size_bucket(bounds: list[int], *, bucket: int = 24) -> list[int]:
    if not bounds:
        return []
    return [
        int(round((bounds[2] - bounds[0]) / float(bucket))),
        int(round((bounds[3] - bounds[1]) / float(bucket))),
    ]


def _explicit_image_preview(value: Any) -> bool:
    compact = visual_text_key(value)
    for separator in (":", "："):
        if separator in compact:
            _speaker, body = compact.rsplit(separator, 1)
            if body:
                compact = body
            break
    if compact in {"[图片]", "[照片]", "【图片】", "【照片】", "[image]", "[photo]", "[picture]"}:
        return True
    return compact in {
        "发送了一张图片",
        "发来了一张图片",
        "发了一张图片",
        "发送了一张照片",
        "发来了一张照片",
        "发了一张照片",
    }


def visual_candidate_from_parts(value: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize one Vision-private candidate and attach layered visual keys."""

    source = dict(value or {})
    side = _lower(source.get("side") or source.get("visual_side") or source.get("sender") or source.get("sender_role"))
    if side not in {"customer", "self"}:
        side = ""
    bounds = _bounds(source.get("bounds") or source.get("bubble_bounds") or source.get("bubble_rect"))
    time_marker = _clean(source.get("wechat_message_time") or source.get("time") or source.get("message_time"))
    structural_message_id = _clean(
        source.get("structural_message_id")
        or source.get("source_message_id")
        or source.get("message_id")
        or source.get("id")
    )
    following_text = _clean(source.get("following_text") or source.get("_vision_following_text") or "")
    preceding_text = _clean(source.get("preceding_text") or source.get("_vision_preceding_text") or "")
    following_text_id = _clean(source.get("following_text_id") or source.get("_vision_following_text_id") or "")
    preceding_text_id = _clean(source.get("preceding_text_id") or source.get("_vision_preceding_text_id") or "")
    ordinal = int(float(source.get("ordinal_from_bottom") or source.get("occurrence_index") or 0) or 0)
    stable_seed = {
        "target": _clean(source.get("target_identity") or source.get("target_name") or source.get("target")),
        "conversation_type": _lower(source.get("conversation_type")),
        "side": side,
        "time": time_marker,
        "following_text_id": following_text_id,
        "following_text_key": visual_text_key(following_text),
        "preceding_text_id": preceding_text_id,
        "preceding_text_key": visual_text_key(preceding_text),
        "size_bucket": _size_bucket(bounds),
        "ordinal": ordinal,
    }
    structural_seed = {
        "target": stable_seed["target"],
        "conversation_type": stable_seed["conversation_type"],
        "side": side,
        "time": time_marker,
        "structural_message_id": structural_message_id,
        "following_text_id": following_text_id,
        "following_text_key": stable_seed["following_text_key"],
        "ordinal": ordinal,
    }
    anchor_seed = {
        **structural_seed,
        "bounds_bucket": _bounds_bucket(bounds),
        "pending_signal_id": _clean(source.get("pending_signal_id")),
        "pending_observation_id": _clean(source.get("pending_observation_id")),
    }
    candidate = {
        **source,
        "label": _clean(source.get("label")),
        "session_key": _clean(source.get("session_key")),
        "target_identity": _clean(source.get("target_identity") or source.get("target_name") or source.get("target")),
        "target_name": _clean(source.get("target_name") or source.get("target")),
        "conversation_type": _lower(source.get("conversation_type")),
        "pending_signal_id": _clean(source.get("pending_signal_id")),
        "pending_observation_id": _clean(source.get("pending_observation_id")),
        "side": side,
        "visual_side": side,
        "bounds": bounds,
        "bounds_key": ",".join(str(item) for item in bounds),
        "wechat_message_time": time_marker,
        "structural_message_id": structural_message_id,
        "following_text": following_text,
        "preceding_text": preceding_text,
        "following_text_id": following_text_id,
        "preceding_text_id": preceding_text_id,
        "following_text_key": visual_text_key(following_text),
        "preceding_text_key": visual_text_key(preceding_text),
        "ordinal_from_bottom": ordinal,
    }
    candidate["visual_anchor_key"] = _clean(source.get("visual_anchor_key")) or _digest("visual-anchor", anchor_seed)
    candidate["visual_stable_key"] = _clean(source.get("visual_stable_key")) or _digest("visual-stable", stable_seed)
    candidate["visual_structural_key"] = _clean(source.get("visual_structural_key")) or (
        _digest("visual-structural", structural_seed)
        if any(structural_seed.get(key) for key in ("structural_message_id", "following_text_id", "following_text_key", "time"))
        else ""
    )
    return candidate


def visual_candidates_from_bubbles(
    bubbles: list[dict[str, Any]] | None,
    existing_messages: list[dict[str, Any]] | None,
    *,
    target: str,
    session_key: str = "",
    conversation_type: str = "",
) -> list[dict[str, Any]]:
    """Build Vision-private selector candidates from structural image bubbles."""

    def message_identity(item: dict[str, Any]) -> str:
        for key in (
            "message_id",
            "id",
            "legacy_message_id",
            "original_message_id",
            "canonical_input_id",
        ):
            value = _clean(item.get(key))
            if value:
                return value
        return ""

    def message_vertical_bounds(item: dict[str, Any]) -> tuple[int, int] | None:
        rect = item.get("bubble_rect") if isinstance(item.get("bubble_rect"), dict) else {}
        if not rect:
            return None
        try:
            top = int(float(rect.get("top") or 0))
            bottom = int(float(rect.get("bottom") or 0))
        except (TypeError, ValueError):
            return None
        if bottom <= top:
            return None
        return top, bottom

    text_rows: list[dict[str, Any]] = []
    for message in existing_messages or []:
        if not isinstance(message, dict):
            continue
        message_type = _lower(message.get("type") or "text") or "text"
        if message_type != "text":
            continue
        identity = message_identity(message)
        vertical = message_vertical_bounds(message)
        if not identity or vertical is None:
            continue
        text_rows.append(
            {
                "top": vertical[0],
                "bottom": vertical[1],
                "id": identity,
                "content": _clean(message.get("content") or message.get("text") or ""),
            }
        )
    text_rows.sort(key=lambda item: (int(item["top"]), int(item["bottom"]), str(item["id"])))

    def bubble_top(item: dict[str, Any]) -> int:
        bounds = item.get("bounds")
        if not isinstance(bounds, (list, tuple)) or len(bounds) < 2:
            return 0
        try:
            return int(bounds[1] or 0)
        except (TypeError, ValueError):
            return 0

    ordered = sorted(
        [item for item in (bubbles or []) if isinstance(item, dict)],
        key=lambda item: (
            bubble_top(item),
            0 if _lower(item.get("side")) == "customer" else 1,
        ),
    )
    occurrence_counts: dict[tuple[str, str], int] = {}
    raw_candidates: list[dict[str, Any]] = []
    for bubble in ordered:
        side = _lower(bubble.get("side"))
        if side not in {"customer", "self"}:
            continue
        bounds = _bounds(bubble.get("bounds"))
        if not bounds:
            continue
        observed_time = _clean(bubble.get("wechat_message_time"))
        preceding_rows = [item for item in text_rows if int(item["bottom"]) <= bounds[1] + 6]
        following_rows = [item for item in text_rows if int(item["top"]) >= bounds[3] - 6]
        preceding = preceding_rows[-1] if preceding_rows else {}
        following = following_rows[0] if following_rows else {}
        occurrence_key = (side, observed_time)
        occurrence_index = occurrence_counts.get(occurrence_key, 0)
        occurrence_counts[occurrence_key] = occurrence_index + 1
        identity_seed = json.dumps(
            {
                "target": _clean(target),
                "side": side,
                "time": observed_time,
                "occurrence_index": occurrence_index,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(identity_seed.encode("utf-8")).hexdigest()[:20]
        raw_candidates.append(
            {
                "session_key": _clean(session_key),
                "target_identity": _clean(target),
                "target_name": _clean(target),
                "conversation_type": _lower(conversation_type),
                "side": side,
                "bounds": bounds,
                "anchor": bubble.get("anchor") if isinstance(bubble.get("anchor"), dict) else {},
                "wechat_message_time": observed_time,
                "structural_message_id": f"visual_{side}_context_{digest}",
                "preceding_text_id": _clean(preceding.get("id")),
                "preceding_text": _clean(preceding.get("content")),
                "following_text_id": _clean(following.get("id")),
                "following_text": _clean(following.get("content")),
                "occurrence_index": occurrence_index,
            }
        )
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for candidate in raw_candidates:
        grouped.setdefault(
            (_clean(candidate.get("side")), _clean(candidate.get("wechat_message_time"))),
            [],
        ).append(candidate)
    for items in grouped.values():
        items.sort(key=lambda item: int((item.get("bounds") or [0, 0, 0, 0])[3]), reverse=True)
        for ordinal, item in enumerate(items, start=1):
            item["ordinal_from_bottom"] = ordinal
    return [visual_candidate_from_parts(item) for item in raw_candidates]


def visual_exclusion_keys(candidate: dict[str, Any] | None) -> set[str]:
    item = visual_candidate_from_parts(candidate if isinstance(candidate, dict) else {})
    keys = {
        _clean(item.get("visual_anchor_key")),
        _clean(item.get("visual_stable_key")),
        _clean(item.get("visual_structural_key")),
        _clean(item.get("structural_message_id")),
        _clean(item.get("bounds_key")),
    }
    return {key for key in keys if key}


def _request_value(request: dict[str, Any], key: str) -> str:
    return _clean(request.get(key))


def _value_mismatch(candidate: dict[str, Any], request: dict[str, Any], key: str) -> bool:
    expected = _request_value(request, key)
    actual = _clean(candidate.get(key))
    return bool(expected and actual and expected != actual)


def _hard_reject_reason(
    candidate: dict[str, Any],
    request: dict[str, Any],
    excluded_keys: set[str],
    *,
    allow_unbound_current_candidate: bool = False,
) -> str:
    side_filter = _lower(request.get("side_filter") or "customer")
    side = _lower(candidate.get("side") or candidate.get("visual_side"))
    if side_filter in {"customer", "self"} and side != side_filter:
        return "visual_side_mismatch"
    for key, reason in (
        ("session_key", "session_key_mismatch"),
        ("target_identity", "target_identity_mismatch"),
        ("conversation_type", "conversation_type_mismatch"),
    ):
        if _value_mismatch(candidate, request, key):
            return reason
        if _request_value(request, key) and not _clean(candidate.get(key)):
            return f"{key}_missing_for_bound_request"
    request_signal = _request_value(request, "pending_signal_id")
    candidate_signal = _clean(candidate.get("pending_signal_id"))
    if request_signal:
        if candidate_signal and request_signal != candidate_signal:
            return "pending_signal_mismatch"
        if not candidate_signal and not allow_unbound_current_candidate:
            return "pending_signal_missing_for_bound_request"
    request_observation = _request_value(request, "pending_observation_id")
    candidate_observation = _clean(candidate.get("pending_observation_id"))
    if request_observation:
        if candidate_observation and request_observation != candidate_observation:
            return "pending_observation_mismatch"
        if not candidate_observation and not allow_unbound_current_candidate:
            return "pending_observation_missing_for_bound_request"
    elif candidate_observation:
        return "pending_observation_unbound"
    if bool(candidate.get("processed") or candidate.get("consumed")):
        return "visual_candidate_already_processed"
    if visual_exclusion_keys(candidate) & set(excluded_keys or set()):
        return "visual_candidate_excluded"
    return ""


def _reference_score(candidate: dict[str, Any], reference_records: list[dict[str, Any]]) -> tuple[float, list[str]]:
    if not reference_records:
        return 0.0, []
    candidate_keys = visual_exclusion_keys(candidate)
    best = 0.0
    evidence: list[str] = []
    for record in reference_records:
        record_keys = visual_exclusion_keys(record if isinstance(record, dict) else {})
        if candidate_keys & record_keys:
            best = max(best, 110.0)
            evidence.append("reference_visual_key_match")
            continue
        if (
            _clean(candidate.get("wechat_message_time"))
            and _clean(candidate.get("wechat_message_time")) == _clean(record.get("wechat_message_time"))
            and _clean(candidate.get("side")) == _clean(record.get("side"))
            and (
                _clean(candidate.get("following_text_id")) == _clean(record.get("following_text_id"))
                or _clean(candidate.get("following_text_key")) == _clean(record.get("following_text_key"))
            )
        ):
            best = max(best, 70.0)
            evidence.append("reference_time_neighbor_match")
    return best, sorted(set(evidence))


def _soft_score(
    candidate: dict[str, Any],
    request: dict[str, Any],
    *,
    reference_records: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    score = 0.0
    evidence: list[str] = []
    pending_signal = _request_value(request, "pending_signal_id")
    pending_observation = _request_value(request, "pending_observation_id")
    if pending_signal and _clean(candidate.get("pending_signal_id")) == pending_signal:
        score += 55.0
        evidence.append("pending_signal_match")
    if pending_observation and _clean(candidate.get("pending_observation_id")) == pending_observation:
        score += 45.0
        evidence.append("pending_observation_match")
    if _clean(candidate.get("visual_structural_key")) or _clean(candidate.get("structural_message_id")):
        score += 35.0
        evidence.append("structural_identity_present")
    source_key = visual_text_key(request.get("source_preview") or request.get("customer_text") or request.get("combined"))
    neighbor_keys = {
        _clean(candidate.get("following_text_id")),
        _clean(candidate.get("preceding_text_id")),
        _clean(candidate.get("following_text_key")),
        _clean(candidate.get("preceding_text_key")),
    }
    if source_key and source_key in neighbor_keys:
        score += 60.0
        evidence.append("neighbor_text_matches_source_preview")
    elif source_key and any(key and (source_key in key or key in source_key) for key in neighbor_keys):
        score += 38.0
        evidence.append("neighbor_text_partially_matches_source_preview")
    elif any(key for key in neighbor_keys):
        score += 10.0
        evidence.append("neighbor_text_present")
    if _clean(candidate.get("wechat_message_time")):
        score += 12.0
        evidence.append("time_marker_present")
    if _explicit_image_preview(request.get("source_preview")):
        score += 30.0
        evidence.append("explicit_image_preview")
        if (
            _clean(candidate.get("record_id"))
            and (
                bool(candidate.get("_vision_pending_signal_id_inherited_from_request"))
                or bool(candidate.get("_vision_pending_observation_id_inherited_from_request"))
            )
            and (
                not pending_signal
                or _clean(candidate.get("pending_signal_id")) == pending_signal
            )
            and (
                not pending_observation
                or _clean(candidate.get("pending_observation_id")) == pending_observation
            )
        ):
            evidence.append("store_event_identity_from_explicit_preview")
    reference_points, reference_evidence = _reference_score(candidate, reference_records)
    score += reference_points
    evidence.extend(reference_evidence)
    return score, sorted(set(evidence))


def _candidate_missing_bound_pending_identity(candidate: dict[str, Any], request: dict[str, Any]) -> bool:
    return bool(
        (
            _request_value(request, "pending_signal_id")
            and (
                not _clean(candidate.get("pending_signal_id"))
                or bool(candidate.get("_vision_pending_signal_id_inherited_from_request"))
            )
        )
        or (
            _request_value(request, "pending_observation_id")
            and (
                not _clean(candidate.get("pending_observation_id"))
                or bool(candidate.get("_vision_pending_observation_id_inherited_from_request"))
            )
        )
    )


def _has_reliable_unbound_relation(evidence: list[str]) -> bool:
    relation_evidence = {
        "reference_visual_key_match",
        "reference_time_neighbor_match",
        "neighbor_text_matches_source_preview",
        "store_event_identity_from_explicit_preview",
    }
    return bool(relation_evidence & set(evidence or []))


def select_pending_visual_candidate(
    candidates: list[dict[str, Any]],
    request: dict[str, Any] | None,
    *,
    excluded_keys: set[str] | None = None,
    reference_records: list[dict[str, Any]] | None = None,
    minimum_score: float = 70.0,
    minimum_margin: float = 16.0,
    allow_unbound_current_candidate: bool = False,
) -> dict[str, Any]:
    """Select exactly one pending visual candidate or fail closed.

    The selector deliberately does not use current/latest y-position to break
    ties in pending-aware mode.  Ambiguous candidates must remain non-actionable.
    """

    data = dict(request or {})
    excluded = set(excluded_keys or set())
    references = [
        visual_candidate_from_parts(item)
        for item in (reference_records or [])
        if isinstance(item, dict)
    ]
    scored: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        candidate = visual_candidate_from_parts(raw)
        reason = _hard_reject_reason(
            candidate,
            data,
            excluded,
            allow_unbound_current_candidate=allow_unbound_current_candidate,
        )
        if reason:
            rejected.append(
                {
                    "label": _clean(candidate.get("label")),
                    "reason": reason,
                    "visual_anchor_key": _clean(candidate.get("visual_anchor_key")),
                    "visual_stable_key": _clean(candidate.get("visual_stable_key")),
                    "visual_structural_key": _clean(candidate.get("visual_structural_key")),
                }
            )
            continue
        score, evidence = _soft_score(candidate, data, reference_records=references)
        missing_pending_identity = _candidate_missing_bound_pending_identity(candidate, data)
        scored.append(
            {
                "candidate": candidate,
                "score": float(score),
                "evidence": evidence,
                "missing_pending_identity": missing_pending_identity,
            }
        )
    if not scored:
        return {
            "ok": False,
            "reason": "visual_candidate_not_found",
            "candidate": {},
            "score": 0.0,
            "margin": 0.0,
            "rejected": rejected,
        }
    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    best = scored[0]
    second_score = float(scored[1].get("score") or 0.0) if len(scored) > 1 else None
    best_score = float(best.get("score") or 0.0)
    margin = best_score - float(second_score if second_score is not None else 0.0)
    if best_score < float(minimum_score):
        return {
            "ok": False,
            "reason": "visual_candidate_confidence_too_low",
            "candidate": {},
            "score": best_score,
            "margin": margin,
            "scored": scored[:8],
            "rejected": rejected,
        }
    if second_score is not None and margin < float(minimum_margin):
        return {
            "ok": False,
            "reason": "visual_candidate_margin_insufficient",
            "candidate": {},
            "score": best_score,
            "margin": margin,
            "scored": scored[:8],
            "rejected": rejected,
        }
    if bool(best.get("missing_pending_identity")) and not _has_reliable_unbound_relation(list(best.get("evidence") or [])):
        return {
            "ok": False,
            "reason": "visual_candidate_pending_relation_missing",
            "candidate": {},
            "score": best_score,
            "margin": margin,
            "scored": scored[:8],
            "rejected": rejected,
        }
    candidate = dict(best.get("candidate") or {})
    candidate["visual_selection_score"] = best_score
    candidate["visual_selection_evidence"] = list(best.get("evidence") or [])
    return {
        "ok": True,
        "reason": "visual_candidate_selected",
        "candidate": candidate,
        "score": best_score,
        "margin": margin,
        "scored": scored[:8],
        "rejected": rejected,
    }
