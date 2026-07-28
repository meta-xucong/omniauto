from __future__ import annotations

import json
import sys
import time
import tempfile
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.capture.visual_anchor import (  # noqa: E402
    select_pending_visual_candidate,
    visual_candidate_from_parts,
    visual_exclusion_keys,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.wechat import (  # noqa: E402
    image_preview_text as capture_image_preview_text,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.occurrence_store import (  # noqa: E402
    VisualOccurrenceStore,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.projection.message import (  # noqa: E402
    image_preview_text as projection_image_preview_text,
    payload_image_pending_signal,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.runtime import (  # noqa: E402
    _customer_image_selection_source_preview,
    _public_clipboard_transaction,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.trigger import (  # noqa: E402
    customer_image_capture_trigger,
    image_preview_text as trigger_image_preview_text,
)


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


def _request(**extra: Any) -> dict[str, Any]:
    return {
        "session_key": "wx:customer-a",
        "target_identity": "Customer A",
        "target_name": "Customer A",
        "conversation_type": "private",
        "pending_signal_id": "signal-1",
        "pending_observation_id": "observation-1",
        "side_filter": "customer",
        "source_preview": "这是什么车？",
        **extra,
    }


def _candidate(
    name: str,
    *,
    side: str = "customer",
    signal_id: str = "signal-1",
    observation_id: str = "observation-1",
    following_text: str = "这是什么车？",
    structural_id: str = "",
    time_marker: str = "18:10",
    ordinal_from_bottom: int = 1,
) -> dict[str, Any]:
    return visual_candidate_from_parts(
        {
            "label": name,
            "session_key": "wx:customer-a",
            "target_identity": "Customer A",
            "conversation_type": "private",
            "pending_signal_id": signal_id,
            "pending_observation_id": observation_id,
            "side": side,
            "structural_message_id": structural_id or f"visual-{name}",
            "following_text": following_text,
            "wechat_message_time": time_marker,
            "ordinal_from_bottom": ordinal_from_bottom,
            "bounds": [410, 220 + ordinal_from_bottom * 30, 650, 430 + ordinal_from_bottom * 30],
        }
    )


def check_runtime_selection_preview_prefers_bound_customer_text_over_dirty_sidebar_preview() -> None:
    signal = {
        "pending_signal_id": "signal-1",
        "pending_observation_id": "observation-1",
        "pending_signal_text": "现在想换这台 现在想换这台",
        "preview_content": "现在想换这台 现在想换这台",
    }
    payload = {
        "messages": [
            {
                "id": "win32_ocr:body-once",
                "message_id": "win32_ocr:body-once",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "现在想换这台",
                "pending_signal_id": "signal-1",
            },
            {
                "id": "clipboard_image_pending:any",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "客户发送了一张图片，图片内容暂未取得。",
                "pending_signal_id": "signal-1",
                "is_customer_image_proxy": True,
                "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
            },
        ]
    }
    preview = _customer_image_selection_source_preview(
        payload=payload,
        batch=[],
        pending_signal=signal,
        pending_signal_id="signal-1",
        pending_observation_id="observation-1",
    )
    assert_equal(preview, "现在想换这台", "vision selection must prefer the current bound chat bubble over dirty sidebar preview")


def check_runtime_selection_preview_ignores_unbound_or_synthetic_customer_text() -> None:
    signal = {
        "pending_signal_id": "signal-1",
        "pending_observation_id": "observation-1",
        "pending_signal_text": "现在想换这台 现在想换这台",
    }
    payload = {
        "messages": [
            {
                "id": "win32_ocr:other-turn",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "现在想换这台",
                "pending_signal_id": "signal-other",
            },
            {
                "id": "clipboard_image_pending:any",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "客户发送了一张图片，图片内容暂未取得。",
                "pending_signal_id": "signal-1",
                "is_customer_image_proxy": True,
                "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
            },
        ]
    }
    preview = _customer_image_selection_source_preview(
        payload=payload,
        batch=[],
        pending_signal=signal,
        pending_signal_id="signal-1",
        pending_observation_id="observation-1",
    )
    assert_equal(
        preview,
        "现在想换这台 现在想换这台",
        "vision fallback must not borrow text from another signal or synthetic placeholder",
    )


def check_runtime_selection_preview_keeps_real_customer_text_that_mentions_image() -> None:
    signal = {
        "pending_signal_id": "signal-1",
        "pending_observation_id": "observation-1",
        "pending_signal_text": "[图片]",
    }
    preview = _customer_image_selection_source_preview(
        payload={
            "messages": [
                {
                    "id": "win32_ocr:body-image-word",
                    "type": "text",
                    "sender": "customer",
                    "sender_role": "customer",
                    "content": "图片里的这台车多少钱",
                    "pending_signal_id": "signal-1",
                }
            ]
        },
        batch=[],
        pending_signal=signal,
        pending_signal_id="signal-1",
        pending_observation_id="observation-1",
    )
    assert_equal(preview, "图片里的这台车多少钱", "real customer text mentioning image should remain usable as a visual anchor")


def check_plain_text_image_words_do_not_trigger_image_preview() -> None:
    plain_texts = [
        "置换需要发照片吗",
        "你能看图片吗",
        "图片里的这台车多少钱",
        "现场照片怎么拍",
    ]
    for text in plain_texts:
        assert_true(not trigger_image_preview_text(text), f"trigger must not treat plain image-word text as media preview: {text}")
        assert_true(not capture_image_preview_text(text), f"capture must not treat plain image-word text as media preview: {text}")
        assert_true(not projection_image_preview_text(text), f"projection must not treat plain image-word text as media preview: {text}")
        trigger = customer_image_capture_trigger(
            payload={},
            pending_signal={
                "pending_signal_id": "plain-signal",
                "pending_signal_kind": "normal",
                "pending_signal_text": text,
            },
            pending_signal_kind="normal",
            target_state={},
        )
        assert_true(trigger.get("should_run") is False, f"plain image-word text must stay text-only: {trigger}")
        pending = payload_image_pending_signal({"pending_signal": {"pending_signal_text": text, "pending_signal_kind": "normal"}}, {})
        assert_equal(pending, {}, f"projection must not synthesize image pending signal from plain text: {text}")

    for marker in ("[图片]", "[照片]", "许聪:[图片]", "许聪：[照片]", "发送了一张图片"):
        assert_true(trigger_image_preview_text(marker), f"trigger must keep real media marker: {marker}")
        assert_true(capture_image_preview_text(marker), f"capture must keep real media marker: {marker}")
        assert_true(projection_image_preview_text(marker), f"projection must keep real media marker: {marker}")


def check_dirty_sidebar_preview_store_claim_is_recovered_by_runtime_anchor() -> None:
    signal = {
        "pending_signal_id": "signal-1",
        "pending_observation_id": "observation-1",
        "pending_signal_text": "现在想换这台 现在想换这台",
    }
    payload = {
        "messages": [
            {
                "id": "win32_ocr:body-once",
                "message_id": "win32_ocr:body-once",
                "type": "text",
                "sender": "customer",
                "sender_role": "customer",
                "content": "现在想换这台",
                "pending_signal_id": "signal-1",
            }
        ]
    }
    clean_preview = _customer_image_selection_source_preview(
        payload=payload,
        batch=[],
        pending_signal=signal,
        pending_signal_id="signal-1",
        pending_observation_id="observation-1",
    )
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        raw = visual_candidate_from_parts(
            {
                "label": "observed-with-dirty-sidebar-preview",
                "session_key": "wx:customer-a",
                "target_identity": "Customer A",
                "conversation_type": "private",
                "side": "customer",
                "structural_message_id": "visual-observed-dirty-preview",
                "following_text": "现在想换这台",
                "following_text_id": "win32_ocr:body-once",
                "bounds": [410, 220, 650, 430],
            }
        )
        dirty_request = _request(
            source_preview="现在想换这台 现在想换这台",
            pending_signal_id="signal-1",
            pending_observation_id="observation-1",
        )
        store.record_occurrences([raw], dirty_request)
        dirty_claim = store.claim_best_match(dirty_request)
        assert_true(dirty_claim.get("ok") is False, f"dirty duplicated sidebar preview should remain unsafe by itself: {dirty_claim}")
        clean_claim = store.claim_best_match(
            _request(
                source_preview=clean_preview,
                pending_signal_id="signal-1",
                pending_observation_id="observation-1",
            )
        )
        assert_true(clean_claim.get("ok") is True, f"runtime body anchor should recover the claim: {clean_claim}")


def check_selector_rejects_observation_mismatch() -> None:
    good = _candidate("good", observation_id="observation-1")
    stale = _candidate("stale", observation_id="observation-old")
    result = select_pending_visual_candidate([stale, good], _request())
    assert_true(result.get("ok") is True, f"expected matching observation to win: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "good", "stale observation must not be selected")
    rejected = result.get("rejected") or []
    assert_true(
        any(item.get("label") == "stale" and item.get("reason") == "pending_observation_mismatch" for item in rejected),
        f"mismatched observation rejection should be auditable internally: {rejected}",
    )


def check_selector_rejects_missing_observation_when_request_is_bound() -> None:
    missing = _candidate("missing-observation", observation_id="")
    result = select_pending_visual_candidate([missing], _request())
    assert_true(result.get("ok") is False, f"bound request must reject candidate missing observation id: {result}")
    assert_equal(result.get("reason"), "visual_candidate_not_found", "missing observation should be hard-rejected")
    rejected = result.get("rejected") or []
    assert_true(
        any(
            item.get("label") == "missing-observation"
            and item.get("reason") == "pending_observation_missing_for_bound_request"
            for item in rejected
        ),
        f"missing observation rejection should be auditable internally: {rejected}",
    )


def check_selector_keeps_missing_observation_compatible() -> None:
    candidate = _candidate("legacy-missing-observation", observation_id="")
    result = select_pending_visual_candidate([candidate], _request(pending_observation_id=""))
    assert_true(result.get("ok") is True, f"missing observation id must keep compatible path: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "legacy-missing-observation", "single compatible candidate should be selected")


def check_selector_fails_closed_on_tied_candidates() -> None:
    first = _candidate("first", structural_id="", ordinal_from_bottom=1)
    second = _candidate("second", structural_id="", ordinal_from_bottom=2)
    # Remove labels from identity-bearing fields so both candidates have equal
    # hard gates and soft evidence.  Current/latest y must not break the tie.
    for item in (first, second):
        item["structural_message_id"] = ""
        item["visual_structural_key"] = ""
        item["visual_stable_key"] = "visual-stable:same"
        item["visual_anchor_key"] = f"visual-anchor:{item['label']}"
    result = select_pending_visual_candidate([first, second], _request())
    assert_true(result.get("ok") is False, f"tied image candidates must fail closed: {result}")
    assert_equal(result.get("reason"), "visual_candidate_margin_insufficient", "tie must be a margin failure")


def check_selector_requires_best_margin() -> None:
    best = _candidate("best", structural_id="visual-structural-current", following_text="这是什么车？")
    runner_up = _candidate("runner-up", structural_id="", following_text="")
    result = select_pending_visual_candidate([runner_up, best], _request(), minimum_score=70.0, minimum_margin=20.0)
    assert_true(result.get("ok") is True, f"clear best candidate should pass: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "best", "best-margin candidate should be selected")


def check_selector_respects_exclusion_keys() -> None:
    blocked = _candidate("blocked")
    fallback = _candidate("fallback", following_text="", structural_id="fallback-structural", ordinal_from_bottom=2)
    excluded = visual_exclusion_keys(blocked)
    result = select_pending_visual_candidate([blocked, fallback], _request(), excluded_keys=excluded)
    assert_true(result.get("ok") is True, f"fallback should be selectable after exclusion: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "fallback", "excluded candidate must be skipped")


def check_selector_rejects_unbound_current_candidate_without_relationship_evidence() -> None:
    unbound = _candidate(
        "unbound-weak",
        signal_id="",
        observation_id="",
        following_text="",
        structural_id="auto-visible-structural-id",
        time_marker="18:10",
    )
    result = select_pending_visual_candidate(
        [unbound],
        _request(source_preview="[图片]"),
        allow_unbound_current_candidate=True,
    )
    assert_true(result.get("ok") is False, f"unbound current candidate without relationship evidence must fail closed: {result}")
    assert_equal(result.get("reason"), "visual_candidate_pending_relation_missing", "weak unbound candidate must not pass")


def check_selector_allows_unbound_current_candidate_with_reference_relation() -> None:
    reference = _candidate("observed-reference", structural_id="visual-observed")
    current = {
        **_candidate("current-unbound", signal_id="", observation_id="", structural_id="visual-observed"),
        "visual_anchor_key": "",
    }
    result = select_pending_visual_candidate(
        [current],
        _request(),
        reference_records=[reference],
        allow_unbound_current_candidate=True,
    )
    assert_true(result.get("ok") is True, f"unbound candidate with reference relation should be selectable: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "current-unbound", "reference-bound unbound candidate should win")
    assert_true(
        "reference_visual_key_match" in ((result.get("candidate") or {}).get("visual_selection_evidence") or []),
        f"selection should expose internal reference evidence for audit: {result}",
    )


def check_selector_allows_unbound_current_candidate_with_neighbor_relation() -> None:
    current = _candidate(
        "current-neighbor",
        signal_id="",
        observation_id="",
        following_text="这是什么车？",
        structural_id="auto-visible-structural-id",
    )
    result = select_pending_visual_candidate(
        [current],
        _request(source_preview="这是什么车？"),
        allow_unbound_current_candidate=True,
    )
    assert_true(result.get("ok") is True, f"unbound candidate with exact neighbor relation should be selectable: {result}")
    assert_equal((result.get("candidate") or {}).get("label"), "current-neighbor", "neighbor-bound unbound candidate should win")


def check_selector_rejects_two_unbound_old_images_without_relationship_evidence() -> None:
    older = _candidate("older", signal_id="", observation_id="", following_text="", ordinal_from_bottom=2)
    newer = _candidate("newer", signal_id="", observation_id="", following_text="", ordinal_from_bottom=1)
    result = select_pending_visual_candidate(
        [older, newer],
        _request(source_preview="[图片]"),
        allow_unbound_current_candidate=True,
    )
    assert_true(result.get("ok") is False, f"two weak unbound images must not be selected by time/latest/auto id: {result}")
    assert_true(
        result.get("reason") in {"visual_candidate_pending_relation_missing", "visual_candidate_margin_insufficient"},
        f"weak unbound candidates must fail closed for relation or margin, got: {result}",
    )


def check_occurrence_store_isolates_signal_and_observation() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        first = _candidate("first", observation_id="observation-1")
        second = _candidate("second", observation_id="observation-2")
        store.record_occurrences([first, second], _request())

        claimed_first = store.claim_best_match(_request(pending_observation_id="observation-1"))
        assert_true(claimed_first.get("ok") is True, f"first observation should claim: {claimed_first}")
        assert_equal((claimed_first.get("record") or {}).get("pending_observation_id"), "observation-1", "first claim must bind observation")

        claimed_second = store.claim_best_match(_request(pending_observation_id="observation-2"))
        assert_true(claimed_second.get("ok") is True, f"second observation should claim independently: {claimed_second}")
        assert_equal((claimed_second.get("record") or {}).get("pending_observation_id"), "observation-2", "second claim must not reuse first")


def check_occurrence_store_does_not_reuse_observed_record_when_request_lacks_observation() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        store.record_occurrences([_candidate("observed", observation_id="observation-1")], _request())
        missing = store.claim_best_match(_request(pending_observation_id=""))
        assert_true(missing.get("ok") is False, f"missing observation request must not consume observed cache: {missing}")
        assert_equal(missing.get("reason"), "visual_occurrence_store_no_match", "missing observation should fall back to transaction selector")


def check_occurrence_store_empty_candidate_identity_inherits_bound_request() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
        raw = visual_candidate_from_parts(
            {
                "label": "raw-current",
                "session_key": "wx:customer-a",
                "target_identity": "Customer A",
                "conversation_type": "private",
                "side": "customer",
                "structural_message_id": "raw-current-structural",
                "following_text": "这是什么车？",
                "bounds": [410, 220, 650, 430],
            }
        )
        assert_equal(raw.get("pending_signal_id"), "", "raw normalized candidate starts unbound by design")
        store.record_occurrences([raw], _request())
        records = _store_records(root)
        assert_true(records, "record should be written")
        assert_equal(records[0].get("pending_signal_id"), "signal-1", "empty candidate signal should inherit request identity")
        assert_equal(records[0].get("pending_observation_id"), "observation-1", "empty candidate observation should inherit request identity")
        claim = store.claim_best_match(_request())
        assert_true(claim.get("ok") is True, f"inherited pending identity should be claimable: {claim}")


def check_occurrence_store_inherited_pending_identity_still_needs_relationship_evidence() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        raw = visual_candidate_from_parts(
            {
                "label": "weak-inherited",
                "session_key": "wx:customer-a",
                "target_identity": "Customer A",
                "conversation_type": "private",
                "side": "customer",
                "structural_message_id": "weak-inherited-structural",
                "wechat_message_time": "18:10",
                "bounds": [410, 220, 650, 430],
            }
        )
        store.record_occurrences([raw], _request(source_preview="普通文字"))
        claim = store.claim_best_match(_request(source_preview="普通文字"))
        assert_true(claim.get("ok") is False, f"inherited pending identity alone must not claim: {claim}")
        assert_equal(
            claim.get("selector_reason"),
            "visual_candidate_pending_relation_missing",
            "weak inherited pending identity should require relationship evidence",
        )


def check_occurrence_store_explicit_image_preview_claims_inherited_observation_record() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        raw = visual_candidate_from_parts(
            {
                "label": "live-explicit-image",
                "session_key": "wx:customer-a",
                "target_identity": "Customer A",
                "conversation_type": "private",
                "side": "customer",
                "structural_message_id": "visual-live-explicit-image",
                "wechat_message_time": "18:10",
                "bounds": [410, 220, 650, 430],
            }
        )
        request = _request(source_preview="[图片]")
        store.record_occurrences([raw], request)
        claim = store.claim_best_match(request)
        assert_true(claim.get("ok") is True, f"explicit image event should claim its own observed occurrence: {claim}")
        record = claim.get("record") or {}
        assert_equal(record.get("pending_signal_id"), "signal-1", "claim must keep inherited signal identity")
        assert_equal(record.get("pending_observation_id"), "observation-1", "claim must keep inherited observation identity")


def check_occurrence_store_nonempty_candidate_identity_overrides_request_and_isolates_mismatch() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
        raw = visual_candidate_from_parts(
            {
                "label": "raw-other-event",
                "session_key": "wx:customer-a",
                "target_identity": "Customer A",
                "conversation_type": "private",
                "pending_signal_id": "signal-other",
                "pending_observation_id": "observation-other",
                "side": "customer",
                "structural_message_id": "raw-other-structural",
                "following_text": "这是什么车？",
                "bounds": [410, 220, 650, 430],
            }
        )
        store.record_occurrences([raw], _request())
        records = _store_records(root)
        assert_true(records, "record should be written")
        assert_equal(records[0].get("pending_signal_id"), "signal-other", "nonempty candidate signal should remain isolated")
        assert_equal(records[0].get("pending_observation_id"), "observation-other", "nonempty candidate observation should remain isolated")
        mismatch = store.claim_best_match(_request())
        assert_true(mismatch.get("ok") is False, f"mismatched candidate-specific identity must not cross-claim: {mismatch}")
        exact = store.claim_best_match(_request(pending_signal_id="signal-other", pending_observation_id="observation-other"))
        assert_true(exact.get("ok") is True, f"candidate-specific event should claim with exact identity: {exact}")


def check_occurrence_store_legacy_unbound_request_still_claims_unbound_record() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        store.record_occurrences(
            [_candidate("legacy", signal_id="", observation_id="")],
            _request(pending_signal_id="", pending_observation_id=""),
        )
        result = store.claim_best_match(_request(pending_signal_id="", pending_observation_id=""))
        assert_true(result.get("ok") is True, f"legacy no-pending store path should remain compatible: {result}")


def check_occurrence_store_ttl_expires_records() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=0.001)
        store.record_occurrences([_candidate("expired")], _request())
        time.sleep(0.01)
        expired = store.claim_best_match(_request())
        assert_true(expired.get("ok") is False, f"expired record must not claim: {expired}")


def check_occurrence_store_isolates_session_target_conversation_and_side() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0)
        session_a = _candidate("session-a")
        session_b = {
            **_candidate("session-b"),
            "session_key": "wx:customer-b",
            "target_identity": "Customer B",
            "target_name": "Customer B",
        }
        group = {
            **_candidate("group"),
            "conversation_type": "group",
        }
        self_side = _candidate("self-side", side="self")
        store.record_occurrences([session_a, session_b, group, self_side], _request())

        claimed_b = store.claim_best_match(_request(session_key="wx:customer-b", target_identity="Customer B", target_name="Customer B"))
        assert_true(claimed_b.get("ok") is True, f"session B should claim only its own record: {claimed_b}")
        assert_equal((claimed_b.get("record") or {}).get("label"), "session-b", "session isolation failed")

        private = store.claim_best_match(_request(conversation_type="private"))
        assert_true(private.get("ok") is True, f"private conversation should claim private record: {private}")
        assert_equal((private.get("record") or {}).get("conversation_type"), "private", "conversation type isolation failed")

        group_claim = store.claim_best_match(_request(conversation_type="group"))
        assert_true(group_claim.get("ok") is True, f"group conversation should claim group record: {group_claim}")
        assert_equal((group_claim.get("record") or {}).get("label"), "group", "group record should not cross into private")

        self_claim = store.claim_best_match(_request(side_filter="self"))
        assert_true(self_claim.get("ok") is True, f"self-side record should claim only for self route: {self_claim}")
        assert_equal((self_claim.get("record") or {}).get("side"), "self", "side isolation failed")


def check_occurrence_store_claim_is_single_consumer_until_timeout() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0, claim_ttl_seconds=60.0)
        store.record_occurrences([_candidate("single-consumer")], _request())
        first = store.claim_best_match(_request())
        second = store.claim_best_match(_request())
        assert_true(first.get("ok") is True, f"first claim should succeed: {first}")
        assert_true(second.get("ok") is False, f"second concurrent claim must not reuse record: {second}")

    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0, claim_ttl_seconds=0.001)
        store.record_occurrences([_candidate("claim-timeout")], _request())
        first = store.claim_best_match(_request())
        time.sleep(0.01)
        second = store.claim_best_match(_request())
        assert_true(first.get("ok") is True, f"first timeout test claim should succeed: {first}")
        assert_true(second.get("ok") is True, f"expired claim should release safely: {second}")


def check_occurrence_store_corruption_fails_closed_without_crashing() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        (root / "broken.json").write_text("{not-json", encoding="utf-8")
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
        result = store.claim_best_match(_request())
        assert_true(result.get("ok") is False, f"corrupt store should not produce a match: {result}")
        assert_equal(result.get("reason"), "visual_occurrence_store_no_match", "corrupt store must fail closed as no match")


def _store_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def check_occurrence_store_moved_occurrence_reuses_record_identity() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
        first = _candidate("moved", structural_id="same-structural", ordinal_from_bottom=1)
        moved = {
            **_candidate("moved", structural_id="same-structural", ordinal_from_bottom=1),
            "bounds": [410, 110, 650, 320],
        }
        store.record_occurrences([first], _request())
        store.record_occurrences([moved], _request())
        records = _store_records(root)
        assert_equal(len(records), 1, f"moved occurrence must keep one stable record: {records}")
        assert_equal(records[0].get("bounds"), [410, 110, 650, 320], "unclaimed live observation may update transient bounds")


def check_occurrence_store_repeated_observation_does_not_resurrect_consumed_record() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0)
        store.record_occurrences([_candidate("consumed", structural_id="same-consumed")], _request())
        first = store.claim_best_match(_request())
        assert_true(first.get("ok") is True, f"first claim should succeed: {first}")
        store.consume_claim(
            str((first.get("record") or {}).get("record_id") or ""),
            str(first.get("claim_id") or ""),
            success=True,
        )
        store.record_occurrences([_candidate("consumed-again", structural_id="same-consumed")], _request())
        second = store.claim_best_match(_request())
        records = _store_records(root)
        assert_true(second.get("ok") is False, f"consumed occurrence must not be resurrected: {second}")
        assert_true(records and bool(records[0].get("consumed")), f"record must remain consumed: {records}")


def check_occurrence_store_active_claim_is_not_overwritten_by_observation() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0, claim_ttl_seconds=60.0)
        store.record_occurrences([_candidate("claimed", structural_id="active-claim")], _request())
        first = store.claim_best_match(_request())
        assert_true(first.get("ok") is True, f"first claim should succeed: {first}")
        updated = {
            **_candidate("claimed-updated", structural_id="active-claim"),
            "bounds": [410, 110, 650, 320],
        }
        store.record_occurrences([updated], _request())
        second = store.claim_best_match(_request())
        records = _store_records(root)
        assert_true(second.get("ok") is False, f"active claim must stay single-consumer after observation refresh: {second}")
        assert_true(records and records[0].get("label") == "claimed", f"active claim should not be overwritten by refresh: {records}")


def check_occurrence_store_expired_claim_cannot_consume() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        store = VisualOccurrenceStore(root=Path(tmp), ttl_seconds=60.0, claim_ttl_seconds=0.001)
        store.record_occurrences([_candidate("expired-consume")], _request())
        first = store.claim_best_match(_request())
        assert_true(first.get("ok") is True, f"claim should succeed before expiry: {first}")
        time.sleep(0.01)
        consumed = store.consume_claim(
            str((first.get("record") or {}).get("record_id") or ""),
            str(first.get("claim_id") or ""),
            success=True,
        )
        assert_true(consumed.get("ok") is False, f"expired claim must not consume: {consumed}")
        assert_equal(consumed.get("reason"), "visual_occurrence_store_claim_expired", "expired claim consume should fail closed")


def check_occurrence_store_enforces_per_session_record_bound_without_cross_session_leak() -> None:
    with tempfile.TemporaryDirectory(prefix="vision-occurrence-store-") as tmp:
        root = Path(tmp)
        store = VisualOccurrenceStore(root=root, ttl_seconds=60.0, max_records=10, max_records_per_session=2)
        for index in range(3):
            store.record_occurrences(
                [_candidate(f"a-{index}", observation_id=f"observation-a-{index}", structural_id=f"struct-a-{index}")],
                _request(pending_observation_id=f"observation-a-{index}"),
            )
            time.sleep(0.002)
        store.record_occurrences(
            [
                {
                    **_candidate("b-0", observation_id="observation-b-0", structural_id="struct-b-0"),
                    "session_key": "wx:customer-b",
                    "target_identity": "Customer B",
                    "target_name": "Customer B",
                }
            ],
            _request(
                session_key="wx:customer-b",
                target_identity="Customer B",
                target_name="Customer B",
                pending_observation_id="observation-b-0",
            ),
        )
        records = _store_records(root)
        session_a = [item for item in records if item.get("session_key") == "wx:customer-a"]
        session_b = [item for item in records if item.get("session_key") == "wx:customer-b"]
        assert_true(len(session_a) <= 2, f"session A should be bounded independently: {records}")
        assert_equal(len(session_b), 1, "session B should not be removed by session A bound")


def check_public_clipboard_transaction_strips_private_visual_fields() -> None:
    public = _public_clipboard_transaction(
        {
            "status": "clipboard_read",
            "captured_at": "2026-07-28T21:40:00",
            "right_click_ok": True,
            "menu_copy_confirmed": True,
            "clipboard_sequence_changed": True,
            "clipboard_content_read": True,
            "clipboard_image_valid": True,
            "visual_anchor_key": "private-anchor",
            "visual_stable_key": "private-stable",
            "visual_structural_key": "private-structural",
            "bounds": [1, 2, 3, 4],
            "cache_path": "runtime/private-cache.json",
            "claim_id": "private-claim",
        }
    )
    serialized = json.dumps(public, ensure_ascii=False).lower()
    for token in ("visual_anchor", "visual_stable", "visual_structural", "bounds", "cache", "claim_id"):
        assert_true(token not in serialized, f"public transaction leaked private visual field {token}: {public}")


def check_vision_optional_plugin_does_not_import_voice_implementation() -> None:
    root = APP_ROOT / "optional_plugins" / "vision"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "optional_plugins.voice" in text or "optional_plugins\\voice" in text:
            offenders.append(str(path.relative_to(APP_ROOT)))
    assert_true(not offenders, f"vision module must not import voice implementation: {offenders}")


def main() -> int:
    checks = [
        check_runtime_selection_preview_prefers_bound_customer_text_over_dirty_sidebar_preview,
        check_runtime_selection_preview_ignores_unbound_or_synthetic_customer_text,
        check_runtime_selection_preview_keeps_real_customer_text_that_mentions_image,
        check_plain_text_image_words_do_not_trigger_image_preview,
        check_dirty_sidebar_preview_store_claim_is_recovered_by_runtime_anchor,
        check_selector_rejects_observation_mismatch,
        check_selector_rejects_missing_observation_when_request_is_bound,
        check_selector_keeps_missing_observation_compatible,
        check_selector_fails_closed_on_tied_candidates,
        check_selector_requires_best_margin,
        check_selector_respects_exclusion_keys,
        check_selector_rejects_unbound_current_candidate_without_relationship_evidence,
        check_selector_allows_unbound_current_candidate_with_reference_relation,
        check_selector_allows_unbound_current_candidate_with_neighbor_relation,
        check_selector_rejects_two_unbound_old_images_without_relationship_evidence,
        check_occurrence_store_isolates_signal_and_observation,
        check_occurrence_store_does_not_reuse_observed_record_when_request_lacks_observation,
        check_occurrence_store_empty_candidate_identity_inherits_bound_request,
        check_occurrence_store_inherited_pending_identity_still_needs_relationship_evidence,
        check_occurrence_store_explicit_image_preview_claims_inherited_observation_record,
        check_occurrence_store_nonempty_candidate_identity_overrides_request_and_isolates_mismatch,
        check_occurrence_store_legacy_unbound_request_still_claims_unbound_record,
        check_occurrence_store_ttl_expires_records,
        check_occurrence_store_isolates_session_target_conversation_and_side,
        check_occurrence_store_claim_is_single_consumer_until_timeout,
        check_occurrence_store_corruption_fails_closed_without_crashing,
        check_occurrence_store_moved_occurrence_reuses_record_identity,
        check_occurrence_store_repeated_observation_does_not_resurrect_consumed_record,
        check_occurrence_store_active_claim_is_not_overwritten_by_observation,
        check_occurrence_store_expired_claim_cannot_consume,
        check_occurrence_store_enforces_per_session_record_bound_without_cross_session_leak,
        check_public_clipboard_transaction_strips_private_visual_fields,
        check_vision_optional_plugin_does_not_import_voice_implementation,
    ]
    results: list[dict[str, Any]] = []
    for check in checks:
        try:
            check()
            results.append({"name": check.__name__, "ok": True})
        except Exception as exc:  # pragma: no cover - standalone harness
            results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
