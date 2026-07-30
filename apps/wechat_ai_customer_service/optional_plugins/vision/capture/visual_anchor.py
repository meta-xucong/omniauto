"""Pure visual occurrence/group matching helpers.

This module is intentionally small and side-effect free.  It does not capture
screenshots, scroll WeChat, read the clipboard, call a provider, or persist any
state.  Runtime code may pass transaction-local evidence such as a crop
fingerprint, but the matcher treats it only as private in-memory evidence.
"""

from __future__ import annotations

from itertools import combinations, permutations
import re
from typing import Any


MAX_VISUAL_GROUP_IMAGES = 3
_CUSTOMER_SIDE = "customer"
_SELF_SIDES = {"self", "assistant", "service", "bot", "outbound"}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_ordinal(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _key(value: Any) -> str:
    return re.sub(r"\s+", "", _clean(value)).lower()


def _ordinal_key(value: Any) -> str:
    return re.sub(r"\s+", "", _clean_ordinal(value)).lower()


def _conversation(value: Any) -> str:
    return _key(value)


def _first_value(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean(source.get(key))
        if value:
            return value
    return ""


def _first_ordinal_value(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _clean_ordinal(source.get(key))
        if value:
            return value
    return ""


def _side(value: dict[str, Any]) -> str:
    raw = _key(_first_value(value, "visual_side", "side", "sender_role", "sender"))
    if raw in _SELF_SIDES:
        return "self"
    return raw


def _bounds(value: dict[str, Any]) -> dict[str, int]:
    raw = value.get("bounds")
    if isinstance(raw, dict):
        raw = [raw.get("left"), raw.get("top"), raw.get("right"), raw.get("bottom")]
    if not isinstance(raw, (list, tuple)) or len(raw) < 4:
        rect = value.get("bubble_rect") if isinstance(value.get("bubble_rect"), dict) else {}
        raw = [rect.get("left"), rect.get("top"), rect.get("right"), rect.get("bottom")]
    try:
        left, top, right, bottom = (int(float(raw[index] or 0)) for index in range(4))
    except (TypeError, ValueError):
        left, top, right, bottom = 0, 0, 0, 0
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _size_bucket(bounds: dict[str, int]) -> str:
    width = max(0, int(bounds.get("right") or 0) - int(bounds.get("left") or 0))
    height = max(0, int(bounds.get("bottom") or 0) - int(bounds.get("top") or 0))
    if width <= 0 or height <= 0:
        return ""
    return f"{round(width / 20) * 20}x{round(height / 20) * 20}"


def _scope_value(value: dict[str, Any], request: dict[str, Any], *keys: str) -> str:
    own = _first_value(value, *keys)
    if own:
        return own
    return _first_value(request, *keys)


def normalize_visual_occurrence(
    candidate: dict[str, Any] | None,
    *,
    request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a Vision-private, normalized occurrence dict.

    Missing scope values are inherited from ``request`` only for normalization;
    hard membership checks still compare the normalized value with request.
    """

    data = candidate if isinstance(candidate, dict) else {}
    req = request if isinstance(request, dict) else {}
    bounds = _bounds(data)
    own_session = _first_value(data, "session_key")
    own_target = _first_value(data, "target_identity", "target_name", "target")
    own_conversation = _conversation(_first_value(data, "conversation_type"))
    occurrence = {
        "session_key": own_session or _scope_value(data, req, "session_key"),
        "target_identity": own_target or _scope_value(data, req, "target_identity", "target_name", "target"),
        "conversation_type": own_conversation or _conversation(_scope_value(data, req, "conversation_type")),
        "_candidate_session_key": own_session,
        "_candidate_target_identity": own_target,
        "_candidate_conversation_type": own_conversation,
        "side": _side(data),
        "structural_message_id": _first_value(data, "structural_message_id", "message_id", "id"),
        "source_message_id": _first_value(data, "source_message_id", "canonical_input_id", "legacy_message_id"),
        "visual_structural_key": _first_value(data, "visual_structural_key", "_vision_visual_structural_key"),
        "visual_stable_key": _first_value(data, "visual_stable_key", "_vision_visual_stable_key"),
        "wechat_message_time": _first_value(data, "wechat_message_time", "screen_time_text", "time_marker"),
        "following_text_key": _key(
            _first_value(data, "following_text_key", "_vision_following_text_key", "_vision_following_text_id")
        ),
        "preceding_text_key": _key(
            _first_value(data, "preceding_text_key", "_vision_preceding_text_key", "_vision_preceding_text_id")
        ),
        "occurrence_ordinal": _first_ordinal_value(
            data,
            "occurrence_ordinal",
            "_vision_occurrence_ordinal",
            "_vision_transaction_ordinal",
            "ordinal",
            "occurrence_index",
        ),
        "transaction_fingerprint": _first_value(
            data,
            "transaction_fingerprint",
            "_vision_private_fingerprint",
            "crop_fingerprint",
            "perceptual_fingerprint",
        ),
        "has_self_message_after": bool(data.get("has_self_message_after")),
        "processed": bool(data.get("processed") or data.get("is_processed")),
        "consumed": bool(data.get("consumed") or data.get("is_consumed")),
        "bounds": bounds,
        "top": int(bounds.get("top") or 0),
        "bottom": int(bounds.get("bottom") or 0),
        "size_bucket": _size_bucket(bounds),
    }
    occurrence["identity_keys"] = sorted(visual_occurrence_identity_keys(occurrence))
    occurrence["match_keys"] = sorted(_match_keys(occurrence))
    return occurrence


def _scope_matches(occurrence: dict[str, Any], request: dict[str, Any]) -> bool:
    expected = {
        "session_key": _first_value(request, "session_key"),
        "target_identity": _first_value(request, "target_identity", "target_name", "target"),
        "conversation_type": _conversation(_first_value(request, "conversation_type")),
    }
    for key, expected_value in expected.items():
        if not expected_value:
            return False
        candidate_value = _clean(occurrence.get(f"_candidate_{key}"))
        if not candidate_value or candidate_value != expected_value:
            return False
    return True


def _request_scope_complete(request: dict[str, Any]) -> bool:
    return bool(
        _first_value(request, "session_key")
        and _first_value(request, "target_identity", "target_name", "target")
        and _conversation(_first_value(request, "conversation_type"))
    )


def _hard_reject_reason(occurrence: dict[str, Any], request: dict[str, Any]) -> str:
    if not _scope_matches(occurrence, request):
        return "visual_occurrence_scope_mismatch"
    if _clean(occurrence.get("side")) != _CUSTOMER_SIDE:
        return "visual_occurrence_side_mismatch"
    if bool(occurrence.get("has_self_message_after")):
        return "visual_occurrence_crosses_self_boundary"
    if bool(occurrence.get("processed")) or bool(occurrence.get("consumed")):
        return "visual_occurrence_already_processed"
    if not _match_keys(occurrence) and not _clean(occurrence.get("transaction_fingerprint")):
        return "visual_occurrence_identity_missing"
    return ""


def _relation_identity_fragment(occurrence: dict[str, Any] | None) -> str:
    item = occurrence if isinstance(occurrence, dict) else {}
    ordinal_key = _ordinal_key(item.get("occurrence_ordinal"))
    if not ordinal_key:
        return ""
    following_key = _key(item.get("following_text_key"))
    if following_key:
        return f"following:{following_key}:ordinal:{ordinal_key}"
    preceding_key = _key(item.get("preceding_text_key"))
    if preceding_key:
        return f"preceding:{preceding_key}:ordinal:{ordinal_key}"
    return ""


def visual_occurrence_identity_keys(occurrence: dict[str, Any] | None) -> set[str]:
    """Return stable keys that must not depend on current screenshot position."""

    item = occurrence if isinstance(occurrence, dict) else {}
    keys: set[str] = set()
    for prefix, field in (
        ("stable", "visual_stable_key"),
        ("structural", "visual_structural_key"),
        ("message", "structural_message_id"),
        ("source", "source_message_id"),
    ):
        value = _key(item.get(field))
        if value:
            keys.add(f"{prefix}:{value}")
    relation = _relation_identity_fragment(item)
    if relation:
        keys.add(f"relation:{relation}")
    return keys


def _match_keys(occurrence: dict[str, Any] | None) -> set[str]:
    item = occurrence if isinstance(occurrence, dict) else {}
    keys = set(visual_occurrence_identity_keys(item))
    fingerprint = _key(item.get("transaction_fingerprint"))
    relation = _relation_identity_fragment(item)
    if fingerprint and relation:
        keys.add(f"fingerprint-relation:{fingerprint}:{relation}")
    return keys


def _dedupe_signature(occurrence: dict[str, Any]) -> str:
    for field in ("visual_stable_key", "visual_structural_key", "structural_message_id", "source_message_id"):
        value = _key(occurrence.get(field))
        if value:
            return f"{field}:{value}"
    relation = [key for key in visual_occurrence_identity_keys(occurrence) if key.startswith("relation:")]
    if relation:
        return relation[0]
    fingerprint = _key(occurrence.get("transaction_fingerprint"))
    ordinal = _ordinal_key(occurrence.get("occurrence_ordinal"))
    if fingerprint and ordinal:
        return f"fingerprint-ordinal:{fingerprint}:{ordinal}"
    return ""


def select_current_turn_visual_group(
    candidates: list[dict[str, Any]] | None,
    *,
    request: dict[str, Any] | None = None,
    max_images: int = MAX_VISUAL_GROUP_IMAGES,
) -> dict[str, Any]:
    """Select an ordered customer-image group from already detected candidates."""

    req = request if isinstance(request, dict) else {}
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    signatures: set[str] = set()
    ambiguous_weak_fingerprints: set[str] = set()
    weak_fingerprints: set[str] = set()
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        occurrence = normalize_visual_occurrence(raw, request=req)
        reason = _hard_reject_reason(occurrence, req)
        if reason:
            rejected.append({"reason": reason, "structural_message_id": _clean(occurrence.get("structural_message_id"))})
            continue
        signature = _dedupe_signature(occurrence)
        fingerprint = _key(occurrence.get("transaction_fingerprint"))
        if signature:
            if signature in signatures:
                continue
            signatures.add(signature)
        elif fingerprint:
            if fingerprint in weak_fingerprints:
                ambiguous_weak_fingerprints.add(fingerprint)
            weak_fingerprints.add(fingerprint)
        selected.append(occurrence)

    if ambiguous_weak_fingerprints:
        return {
            "ok": False,
            "reason": "visual_group_ambiguous",
            "occurrences": [],
            "rejected": rejected,
        }
    if not selected:
        return {"ok": False, "reason": "visual_group_no_candidate", "occurrences": [], "rejected": rejected}
    limit = max(1, int(max_images or MAX_VISUAL_GROUP_IMAGES))
    if len(selected) > limit:
        return {
            "ok": False,
            "reason": "visual_group_too_many_images",
            "occurrences": [],
            "candidate_count": len(selected),
            "max_images": limit,
            "rejected": rejected,
        }
    selected.sort(key=lambda item: (int(item.get("top") or 0), int(item.get("bottom") or 0), _clean(item.get("structural_message_id"))))
    return {
        "ok": True,
        "reason": "visual_group_selected",
        "occurrences": selected,
        "count": len(selected),
        "rejected": rejected,
    }


def _fingerprint_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = _key(item.get("transaction_fingerprint"))
        if value:
            counts[value] = counts.get(value, 0) + 1
    return counts


def _match_reason(
    known: dict[str, Any],
    current: dict[str, Any],
    *,
    known_fingerprints: dict[str, int],
    current_fingerprints: dict[str, int],
) -> str:
    if set(known.get("match_keys") or []).intersection(set(current.get("match_keys") or [])):
        return "identity_key_match"
    fingerprint = _key(known.get("transaction_fingerprint"))
    if (
        fingerprint
        and fingerprint == _key(current.get("transaction_fingerprint"))
        and known_fingerprints.get(fingerprint) == 1
        and current_fingerprints.get(fingerprint) == 1
    ):
        return "unique_fingerprint_match"
    return ""


def _all_global_matches(
    known: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    known_fingerprints = _fingerprint_counts(known)
    current_fingerprints = _fingerprint_counts(current)
    edges: list[tuple[int, int, str]] = []
    for known_index, known_item in enumerate(known):
        for current_index, current_item in enumerate(current):
            reason = _match_reason(
                known_item,
                current_item,
                known_fingerprints=known_fingerprints,
                current_fingerprints=current_fingerprints,
            )
            if reason:
                edges.append((known_index, current_index, reason))
    if not edges:
        return [[]]

    best_size = 0
    best: list[list[dict[str, Any]]] = [[]]
    max_size = min(len(known), len(current))
    for size in range(1, max_size + 1):
        for known_indexes in combinations(range(len(known)), size):
            for current_indexes in permutations(range(len(current)), size):
                candidate: list[dict[str, Any]] = []
                valid = True
                for known_index, current_index in zip(known_indexes, current_indexes):
                    reason = next(
                        (
                            edge_reason
                            for edge_known, edge_current, edge_reason in edges
                            if edge_known == known_index and edge_current == current_index
                        ),
                        "",
                    )
                    if not reason:
                        valid = False
                        break
                    candidate.append({"known_index": known_index, "current_index": current_index, "reason": reason})
                if not valid:
                    continue
                if size > best_size:
                    best_size = size
                    best = [candidate]
                elif size == best_size:
                    best.append(candidate)
    return best


def match_visual_occurrence_groups(
    known_occurrences: list[dict[str, Any]] | None,
    current_candidates: list[dict[str, Any]] | None,
    *,
    request: dict[str, Any] | None = None,
    max_images: int = MAX_VISUAL_GROUP_IMAGES,
) -> dict[str, Any]:
    """Compare known occurrences with the current customer-image group."""

    req = request if isinstance(request, dict) else {}
    if not _request_scope_complete(req):
        return {
            "ok": False,
            "reason": "visual_group_request_scope_missing",
            "status": "invalid_request",
            "known": [],
            "current": [],
            "matches": [],
        }
    known = [normalize_visual_occurrence(item, request=req) for item in (known_occurrences or []) if isinstance(item, dict)]
    for known_item in known:
        known_reject_reason = _hard_reject_reason(known_item, req)
        if known_reject_reason:
            return {
                "ok": False,
                "reason": known_reject_reason,
                "status": "invalid_known_occurrence",
                "known": known,
                "current": [],
                "matches": [],
            }
    current_result = select_current_turn_visual_group(current_candidates, request=req, max_images=max_images)
    if not current_result.get("ok"):
        if current_result.get("reason") == "visual_group_no_candidate":
            rejected_reasons = {
                str(item.get("reason") or "")
                for item in (current_result.get("rejected") or [])
                if isinstance(item, dict)
            }
            if "visual_occurrence_scope_mismatch" in rejected_reasons:
                return {
                    "ok": False,
                    "reason": "visual_occurrence_scope_mismatch",
                    "status": "invalid_current_occurrence",
                    "known": known,
                    "current": [],
                    "matches": [],
                    "rejected": current_result.get("rejected") or [],
                }
            return {
                "ok": True,
                "reason": "visual_group_no_delta",
                "status": "no_delta",
                "known": known,
                "current": [],
                "matches": [],
                "added_occurrences": [],
            }
        return {
            "ok": False,
            "reason": str(current_result.get("reason") or "visual_group_no_candidate"),
            "status": "ambiguous" if current_result.get("reason") == "visual_group_ambiguous" else "unmatched",
            "known": known,
            "current": [],
        }
    current = [dict(item) for item in current_result.get("occurrences") or [] if isinstance(item, dict)]
    best_matches = _all_global_matches(known, current)
    if len(best_matches) != 1:
        return {
            "ok": False,
            "reason": "visual_group_match_ambiguous",
            "status": "ambiguous",
            "known": known,
            "current": current,
            "matches": [],
        }
    matches = best_matches[0]
    used_current = {int(item.get("current_index") or 0) for item in matches}

    added = [item for index, item in enumerate(current) if index not in used_current]
    return {
        "ok": True,
        "reason": "visual_group_delta" if added else "visual_group_no_delta",
        "status": "added_occurrences" if added else "no_delta",
        "known": known,
        "current": current,
        "matches": matches,
        "added_occurrences": added,
    }
