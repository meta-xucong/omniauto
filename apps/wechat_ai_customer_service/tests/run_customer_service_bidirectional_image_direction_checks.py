from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.optional_plugins.vision.occurrence import (  # noqa: E402
    confirmed_customer_image_placeholder,
    resolve_pending_visual_occurrence,
)
from apps.wechat_ai_customer_service.optional_plugins.vision.capture.surface import (  # noqa: E402
    visual_image_envelopes_from_bubbles,
)


def main() -> int:
    checks = [
        check_structural_bubbles_become_exclusive_direction_envelopes,
        check_occurrence_identity_ignores_observation_anchor_movement,
        check_malformed_observation_bounds_do_not_break_direction_projection,
        check_sidebar_signal_without_structural_occurrence_has_no_owner,
        check_self_occurrence_cannot_create_customer_placeholder,
        check_customer_occurrence_can_create_customer_placeholder,
        check_normal_text_cannot_reactivate_visible_self_image,
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


def _bubble(*, side: str, y: int, message_time: str = "05:38") -> dict[str, Any]:
    return {
        "side": side,
        "bounds": [320 if side == "customer" else 760, y, 560 if side == "customer" else 960, y + 150],
        "anchor": {"x": 440 if side == "customer" else 860, "y": y + 75},
        "wechat_message_time": message_time,
        "detection_method": "structural_media_lane_v1",
    }


def _envelopes(bubbles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return visual_image_envelopes_from_bubbles(bubbles, [], target="Customer A")


def check_structural_bubbles_become_exclusive_direction_envelopes() -> None:
    messages = _envelopes([_bubble(side="customer", y=260), _bubble(side="self", y=500)])
    assert_equal([item.get("sender") for item in messages], ["customer", "self"], "left/right structure must set the two directions")
    assert_equal([item.get("visual_side") for item in messages], ["customer", "self"], "visual_side must agree with sender")
    assert_true(all(item.get("sender") == item.get("sender_role") for item in messages), "one occurrence must have one owner")
    encoded = json.dumps(messages, ensure_ascii=False)
    for forbidden in ("bounds", "anchor", "saved_image_path", "sha256", "base64"):
        assert_true(forbidden not in encoded, f"structural geometry/image data leaked through {forbidden}")


def check_occurrence_identity_ignores_observation_anchor_movement() -> None:
    first = _envelopes([_bubble(side="self", y=500), _bubble(side="self", y=680)])
    second = _envelopes([_bubble(side="self", y=487), _bubble(side="self", y=667)])
    assert_equal(
        [item.get("message_id") for item in first],
        [item.get("message_id") for item in second],
        "observation coordinates/capture time must not manufacture new business occurrences",
    )
    assert_equal(len(set(item.get("message_id") for item in first)), 2, "two same-minute occurrences must remain distinct")


def check_malformed_observation_bounds_do_not_break_direction_projection() -> None:
    bubble = _bubble(side="customer", y=260)
    bubble["bounds"] = ["invalid"]
    messages = _envelopes([bubble])
    assert_equal(len(messages), 1, "malformed private geometry must not break ordinary message capture")
    assert_equal(messages[0].get("sender"), "customer", "structural side must remain the direction authority")


def _resolve(messages: list[dict[str, Any]], *, explicit_image_pending: bool = True) -> dict[str, Any]:
    return resolve_pending_visual_occurrence(
        messages,
        target_state={},
        explicit_image_pending=explicit_image_pending,
        pending_signal_id="image-signal-1",
    )


def check_sidebar_signal_without_structural_occurrence_has_no_owner() -> None:
    resolution = _resolve([])
    assert_equal(resolution.get("state"), "no_candidate", "sidebar media activity alone must not authorize customer")
    assert_equal(resolution.get("direction"), "", "no structural occurrence means no direction")
    assert_equal(resolution.get("occurrence"), {}, "no synthetic customer occurrence may be created")


def check_self_occurrence_cannot_create_customer_placeholder() -> None:
    resolution = _resolve(_envelopes([_bubble(side="self", y=500)]))
    assert_equal(resolution.get("state"), "self_confirmed", "right-side image must resolve to self")
    assert_equal(resolution.get("direction"), "self", "right-side owner must remain self")
    placeholder = confirmed_customer_image_placeholder(
        resolution,
        target_name="Customer A",
        session_key="wx:customer-a",
        pending_signal_id="image-signal-1",
    )
    assert_equal(placeholder, {}, "self occurrence must make the customer placeholder path unreachable")


def check_customer_occurrence_can_create_customer_placeholder() -> None:
    resolution = _resolve(_envelopes([_bubble(side="customer", y=500)]))
    assert_equal(resolution.get("state"), "customer_confirmed", "left-side image must resolve to customer")
    placeholder = confirmed_customer_image_placeholder(
        resolution,
        target_name="Customer A",
        session_key="wx:customer-a",
        pending_signal_id="image-signal-1",
    )
    assert_equal(placeholder.get("sender"), "customer", "confirmed customer occurrence may create the existing proxy")
    assert_true(placeholder.get("is_customer_image_proxy") is True, "confirmed proxy must use the existing customer-image contract")
    assert_equal(placeholder.get("pending_signal_id"), "image-signal-1", "proxy must stay bound to the current event")


def check_normal_text_cannot_reactivate_visible_self_image() -> None:
    resolution = _resolve(_envelopes([_bubble(side="self", y=500)]), explicit_image_pending=False)
    assert_equal(resolution.get("state"), "sidebar_signal_only", "ordinary text must not activate old visible media")
    assert_equal(resolution.get("occurrence"), {}, "ordinary text must not schedule a self clipboard transaction")


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
