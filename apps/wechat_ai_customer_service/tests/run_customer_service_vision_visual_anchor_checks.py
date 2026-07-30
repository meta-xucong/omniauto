from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.capture.visual_anchor import (  # noqa: E402
    match_visual_occurrence_groups,
    normalize_visual_occurrence,
    select_current_turn_visual_group,
    visual_occurrence_identity_keys,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def _request() -> dict[str, Any]:
    return {
        "session_key": "wx:customer-a",
        "target_identity": "Customer A",
        "conversation_type": "private",
    }


def _candidate(
    occurrence_id: str,
    *,
    top: int,
    side: str = "customer",
    session_key: str = "wx:customer-a",
    target_identity: str = "Customer A",
    conversation_type: str = "private",
    structural_key: str = "",
    stable_key: str = "",
    fingerprint: str = "",
    following: str = "",
    ordinal: str = "",
    time_text: str = "10:01",
    self_after: bool = False,
    processed: bool = False,
    consumed: bool = False,
) -> dict[str, Any]:
    return {
        "message_id": occurrence_id,
        "visual_side": side,
        "session_key": session_key,
        "target_identity": target_identity,
        "conversation_type": conversation_type,
        "visual_structural_key": structural_key,
        "visual_stable_key": stable_key,
        "transaction_fingerprint": fingerprint,
        "following_text_key": following,
        "occurrence_ordinal": ordinal,
        "wechat_message_time": time_text,
        "has_self_message_after": self_after,
        "processed": processed,
        "consumed": consumed,
        "bounds": [420, top, 660, top + 120],
    }


def check_group_selects_current_turn_customer_images_and_orders_after_membership() -> None:
    result = select_current_turn_visual_group(
        [
            _candidate("img-bottom", top=420, structural_key="struct-bottom"),
            _candidate("self-img", top=200, side="self", structural_key="struct-self"),
            _candidate("img-top", top=180, structural_key="struct-top"),
            _candidate("old-img", top=80, structural_key="struct-old", self_after=True),
        ],
        request=_request(),
    )
    assert_true(result.get("ok") is True, f"group should select current customer images: {result}")
    assert_equal(
        [item.get("structural_message_id") for item in result.get("occurrences") or []],
        ["img-top", "img-bottom"],
        "selected images must be ordered by y only after membership is fixed",
    )
    rejected_reasons = {item.get("reason") for item in result.get("rejected") or []}
    assert_true("visual_occurrence_side_mismatch" in rejected_reasons, f"self image must be rejected: {result}")
    assert_true("visual_occurrence_crosses_self_boundary" in rejected_reasons, f"old image after self boundary must be rejected: {result}")


def check_group_hard_rejects_wrong_scope_and_missing_candidate_scope() -> None:
    cases = [
        _candidate("wrong-session", top=100, session_key="wx:other", structural_key="struct-a"),
        _candidate("wrong-target", top=120, target_identity="Other", structural_key="struct-b"),
        _candidate("wrong-conversation", top=140, conversation_type="group", structural_key="struct-c"),
        {
            "message_id": "missing-scope",
            "visual_side": "customer",
            "visual_structural_key": "struct-d",
            "bounds": [420, 160, 660, 280],
        },
    ]
    result = select_current_turn_visual_group(cases, request=_request())
    assert_true(result.get("ok") is False, f"wrong or missing scope must fail: {result}")
    assert_equal(result.get("reason"), "visual_group_no_candidate", "scope rejection should leave no eligible candidates")
    assert_true(
        all(item.get("reason") == "visual_occurrence_scope_mismatch" for item in result.get("rejected") or []),
        f"all rejected candidates should fail scope hard gate: {result}",
    )


def check_group_rejects_missing_request_scope() -> None:
    result = select_current_turn_visual_group(
        [_candidate("img", top=100, structural_key="struct-a")],
        request={"session_key": "wx:customer-a", "target_identity": "", "conversation_type": "private"},
    )
    assert_true(result.get("ok") is False, f"request missing target must fail hard: {result}")
    assert_equal(result.get("reason"), "visual_group_no_candidate", "missing request scope leaves no eligible candidate")
    assert_equal((result.get("rejected") or [{}])[0].get("reason"), "visual_occurrence_scope_mismatch", "missing request scope is a hard scope failure")


def check_group_excludes_processed_or_consumed_candidates() -> None:
    result = select_current_turn_visual_group(
        [
            _candidate("processed", top=100, structural_key="struct-processed", processed=True),
            _candidate("consumed", top=250, structural_key="struct-consumed", consumed=True),
        ],
        request=_request(),
    )
    assert_true(result.get("ok") is False, f"processed/consumed images must be excluded: {result}")
    assert_true(
        all(item.get("reason") == "visual_occurrence_already_processed" for item in result.get("rejected") or []),
        f"processed/consumed rejects should be explicit: {result}",
    )


def check_group_rejects_more_than_three_images_without_truncating() -> None:
    result = select_current_turn_visual_group(
        [
            _candidate(f"img-{index}", top=100 + index * 80, structural_key=f"struct-{index}")
            for index in range(4)
        ],
        request=_request(),
    )
    assert_true(result.get("ok") is False, f">3 group must fail closed: {result}")
    assert_equal(result.get("reason"), "visual_group_too_many_images", ">3 images must not be truncated")
    assert_equal(result.get("candidate_count"), 4, "failure should expose candidate count for private tests")


def check_known_current_matching_allows_same_image_vertical_move() -> None:
    known = [_candidate("known-a", top=420, structural_key="struct-a", fingerprint="fp-a")]
    current = [_candidate("current-a", top=260, structural_key="struct-a", fingerprint="fp-a")]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"same structural identity should match after move: {result}")
    assert_equal(result.get("status"), "no_delta", "moved same image is not a visual delta")
    assert_equal((result.get("matches") or [{}])[0].get("reason"), "identity_key_match", "structural match should be primary")


def check_relation_ordinal_matches_id_time_and_bounds_jitter() -> None:
    known = [_candidate("known-id-y420", top=420, structural_key="", following="现在想换这台", ordinal="0", time_text="10:01")]
    current = [_candidate("current-id-y360", top=360, structural_key="", following="现在想换这台", ordinal="0", time_text="10 01")]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"relation+ordinal should survive OCR id/time/bounds jitter: {result}")
    assert_equal(result.get("status"), "no_delta", "jittered same occurrence is not a visual delta")


def check_integer_zero_ordinal_keeps_relation_identity() -> None:
    base = _candidate("img-zero", top=420, structural_key="", following="现在想换这台")
    int_zero = normalize_visual_occurrence({**base, "occurrence_index": 0}, request=_request())
    str_zero = normalize_visual_occurrence({**base, "occurrence_index": "0"}, request=_request())
    assert_equal(int_zero.get("occurrence_ordinal"), "0", "integer zero ordinal must not be cleaned as empty")
    assert_equal(
        visual_occurrence_identity_keys(int_zero),
        visual_occurrence_identity_keys(str_zero),
        "integer and string zero ordinals must produce the same relation identity",
    )
    assert_true(
        any("ordinal:0" in item for item in visual_occurrence_identity_keys(int_zero)),
        f"zero ordinal relation key must be present: {int_zero}",
    )


def check_shared_following_text_three_image_group_matches_by_ordinal() -> None:
    known = [
        _candidate(f"known-{index}", top=120 + index * 120, structural_key="", following="同一条正文", ordinal=str(index), time_text="10:01")
        for index in range(3)
    ]
    current = [
        _candidate(f"current-{index}", top=150 + index * 130, structural_key="", following="同一条正文", ordinal=str(index), time_text="10 01")
        for index in range(3)
    ]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"shared following text must still match as ordered occurrences: {result}")
    assert_equal(result.get("status"), "no_delta", "same three-image group should not be treated as delta")
    assert_equal(
        [(item.get("known_index"), item.get("current_index")) for item in result.get("matches") or []],
        [(0, 0), (1, 1), (2, 2)],
        "transaction-local ordinal must produce one-to-one same-order mapping",
    )


def check_global_matching_avoids_greedy_trap_and_is_order_independent() -> None:
    known = [
        _candidate("known-a", top=100, structural_key="struct-a"),
        _candidate("known-b", top=260, stable_key="stable-b"),
    ]
    current = [
        _candidate("current-1", top=120, structural_key="struct-a"),
        _candidate("current-2", top=280, structural_key="struct-a", stable_key="stable-b"),
    ]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"global matcher should find unique non-greedy mapping: {result}")
    assert_equal(
        [(item.get("known_index"), item.get("current_index")) for item in result.get("matches") or []],
        [(0, 0), (1, 1)],
        "unique global match should map A->1 and B->2",
    )
    reversed_result = match_visual_occurrence_groups(list(reversed(known)), list(reversed(current)), request=_request())
    assert_true(reversed_result.get("ok") is True, f"global match should not depend on input order: {reversed_result}")
    assert_equal(reversed_result.get("status"), "no_delta", "input order should not change semantic status")


def check_verify_treats_known_offscreen_as_no_delta() -> None:
    result = match_visual_occurrence_groups(
        [_candidate("known-a", top=100, structural_key="struct-a")],
        [],
        request=_request(),
    )
    assert_true(result.get("ok") is True, f"known image offscreen should not be a visual delta: {result}")
    assert_equal(result.get("status"), "no_delta", "current empty means no visible delta, not known-missing failure")
    assert_equal(result.get("added_occurrences"), [], "offscreen known images add no new occurrence")


def check_verify_allows_partial_known_offscreen_and_reports_only_added_current() -> None:
    known = [
        _candidate("known-offscreen", top=100, structural_key="struct-a"),
        _candidate("known-visible", top=260, structural_key="struct-b"),
    ]
    current = [
        _candidate("current-visible", top=260, structural_key="struct-b"),
        _candidate("current-added", top=420, structural_key="struct-c"),
    ]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"partial known offscreen should still allow delta detection: {result}")
    assert_equal(result.get("status"), "added_occurrences", "unmatched current image is the only delta")
    assert_equal(
        [item.get("structural_message_id") for item in result.get("added_occurrences") or []],
        ["current-added"],
        "known offscreen must not be reported as an error or added image",
    )


def check_match_missing_request_scope_fails_closed() -> None:
    result = match_visual_occurrence_groups(
        [_candidate("known", top=100, structural_key="struct-a")],
        [],
        request={"session_key": "wx:customer-a", "target_identity": "Customer A", "conversation_type": ""},
    )
    assert_true(result.get("ok") is False, f"match request missing conversation must fail closed: {result}")
    assert_equal(result.get("status"), "invalid_request", "missing request scope cannot be treated as no_delta")


def check_match_wrong_scope_known_fails_closed() -> None:
    result = match_visual_occurrence_groups(
        [_candidate("known", top=100, session_key="wx:other", structural_key="struct-a")],
        [],
        request=_request(),
    )
    assert_true(result.get("ok") is False, f"wrong-scope known occurrence must fail closed: {result}")
    assert_equal(result.get("status"), "invalid_known_occurrence", "wrong known scope cannot participate in matching")
    assert_equal(result.get("reason"), "visual_occurrence_scope_mismatch", "wrong known scope must be explicit")


def check_match_wrong_scope_current_fails_closed_not_no_delta() -> None:
    result = match_visual_occurrence_groups(
        [_candidate("known", top=100, structural_key="struct-a")],
        [_candidate("current-wrong", top=120, session_key="wx:other", structural_key="struct-b")],
        request=_request(),
    )
    assert_true(result.get("ok") is False, f"wrong-scope current occurrence must fail closed: {result}")
    assert_equal(result.get("status"), "invalid_current_occurrence", "wrong current scope cannot be hidden as no_delta")
    assert_equal(result.get("reason"), "visual_occurrence_scope_mismatch", "wrong current scope must be explicit")


def check_same_content_duplicate_sends_remain_two_occurrences() -> None:
    result = select_current_turn_visual_group(
        [
            _candidate("img-a", top=150, structural_key="struct-a", fingerprint="same-car", ordinal="0"),
            _candidate("img-b", top=330, structural_key="struct-b", fingerprint="same-car", ordinal="1"),
        ],
        request=_request(),
    )
    assert_true(result.get("ok") is True, f"same-content repeated sends should remain valid group: {result}")
    occurrences = result.get("occurrences") or []
    assert_equal(len(occurrences), 2, "same fingerprint with different occurrences must not be collapsed")
    assert_equal(
        [item.get("structural_message_id") for item in occurrences],
        ["img-a", "img-b"],
        "duplicate content keeps chat order",
    )


def check_matching_reports_added_occurrence_without_reidentifying_known() -> None:
    known = [_candidate("known-a", top=140, structural_key="struct-a", fingerprint="fp-a")]
    current = [
        _candidate("current-a", top=120, structural_key="struct-a", fingerprint="fp-a"),
        _candidate("current-b", top=320, structural_key="struct-b", fingerprint="fp-b"),
    ]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"known + new occurrence should match cleanly: {result}")
    assert_equal(result.get("status"), "added_occurrences", "new current occurrence should be reported as delta")
    assert_equal(
        [item.get("structural_message_id") for item in result.get("added_occurrences") or []],
        ["current-b"],
        "only the new image should be returned as added",
    )


def check_relation_ordinal_reports_new_same_content_occurrence() -> None:
    known = [_candidate("known-a", top=140, structural_key="", fingerprint="same-car", following="同一条正文", ordinal="0")]
    current = [
        _candidate("current-a", top=140, structural_key="", fingerprint="same-car", following="同一条正文", ordinal="0"),
        _candidate("current-b", top=320, structural_key="", fingerprint="same-car", following="同一条正文", ordinal="1"),
    ]
    result = match_visual_occurrence_groups(known, current, request=_request())
    assert_true(result.get("ok") is True, f"new same-content occurrence should be reported as added: {result}")
    assert_equal(result.get("status"), "added_occurrences", "same content but new occurrence remains a delta")
    assert_equal(
        [item.get("occurrence_ordinal") for item in result.get("added_occurrences") or []],
        ["1"],
        "added occurrence must preserve the second chat occurrence",
    )


def check_fingerprint_only_match_is_unique_or_ambiguous() -> None:
    unique = match_visual_occurrence_groups(
        [_candidate("known", top=100, structural_key="", fingerprint="fp-unique")],
        [_candidate("current", top=200, structural_key="", fingerprint="fp-unique")],
        request=_request(),
    )
    assert_true(unique.get("ok") is True, f"unique fingerprint can align same occurrence: {unique}")
    assert_equal(unique.get("status"), "no_delta", "unique fingerprint match is a cache hit")

    ambiguous = select_current_turn_visual_group(
        [
            _candidate("", top=100, structural_key="", fingerprint="fp-collision"),
            _candidate("", top=250, structural_key="", fingerprint="fp-collision"),
        ],
        request=_request(),
    )
    assert_true(ambiguous.get("ok") is False, f"fingerprint collision without occurrence evidence must fail: {ambiguous}")
    assert_equal(ambiguous.get("reason"), "visual_group_ambiguous", "weak fingerprint collision cannot be guessed")


def check_identity_keys_do_not_depend_on_current_bounds() -> None:
    first = normalize_visual_occurrence(_candidate("same", top=100, structural_key="struct-same"), request=_request())
    second = normalize_visual_occurrence(_candidate("same", top=500, structural_key="struct-same"), request=_request())
    assert_equal(
        visual_occurrence_identity_keys(first),
        visual_occurrence_identity_keys(second),
        "identity keys must ignore current screenshot y/bounds",
    )


CHECKS = [
    check_group_selects_current_turn_customer_images_and_orders_after_membership,
    check_group_hard_rejects_wrong_scope_and_missing_candidate_scope,
    check_group_rejects_missing_request_scope,
    check_group_excludes_processed_or_consumed_candidates,
    check_group_rejects_more_than_three_images_without_truncating,
    check_known_current_matching_allows_same_image_vertical_move,
    check_relation_ordinal_matches_id_time_and_bounds_jitter,
    check_integer_zero_ordinal_keeps_relation_identity,
    check_shared_following_text_three_image_group_matches_by_ordinal,
    check_global_matching_avoids_greedy_trap_and_is_order_independent,
    check_verify_treats_known_offscreen_as_no_delta,
    check_verify_allows_partial_known_offscreen_and_reports_only_added_current,
    check_match_missing_request_scope_fails_closed,
    check_match_wrong_scope_known_fails_closed,
    check_match_wrong_scope_current_fails_closed_not_no_delta,
    check_same_content_duplicate_sends_remain_two_occurrences,
    check_matching_reports_added_occurrence_without_reidentifying_known,
    check_relation_ordinal_reports_new_same_content_occurrence,
    check_fingerprint_only_match_is_unique_or_ambiguous,
    check_identity_keys_do_not_depend_on_current_bounds,
]


def main() -> int:
    results = []
    failures = []
    for check in CHECKS:
        try:
            check()
        except Exception as exc:  # noqa: BLE001
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
            failures.append(check.__name__)
        else:
            results.append({"name": check.__name__, "ok": True})
    print(json.dumps({"ok": not failures, "count": len(CHECKS), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
