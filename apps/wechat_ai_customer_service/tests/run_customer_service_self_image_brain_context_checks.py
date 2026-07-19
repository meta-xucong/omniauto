from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.workflows.customer_service_brain import (  # noqa: E402
    build_brain_input,
    low_authority_fast_profile_decision,
)
from apps.wechat_ai_customer_service.workflows.reply_evidence_builder import (  # noqa: E402
    build_reply_evidence_pack,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_session_ledger import (  # noqa: E402
    SessionLedgerStore,
)


VISION_SUMMARY = "一名穿浅蓝色艾莎公主纱裙的小女孩在粉色花簇旁触摸花朵"


def main() -> int:
    checks = [
        check_ledger_self_image_enters_existing_history_fields_without_raw_store,
        check_fast_profile_cannot_drop_recent_multimodal_context,
        check_latest_turn_recovery_preserves_recent_multimodal_text,
        check_unenriched_synthetic_placeholder_is_not_brain_history,
        check_empty_recent_history_clears_legacy_synthetic_summary,
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


def _self_image_message() -> dict[str, Any]:
    return {
        "id": "visual_self_context_stable_one",
        "identity": "visual_self_context_stable_one",
        "sender": "self",
        "sender_role": "self",
        "type": "image",
        "modality": "image",
        "content": "[图片]",
        "time": "05:38",
        "image_understanding": {"applied": True, "vision_summary": VISION_SUMMARY},
        "vision_summary": VISION_SUMMARY,
    }


def _target_state(*messages: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_context": {
            "ledger_recent_messages": list(messages or [_self_image_message()]),
            "ledger_context_summary": f"客服: [图片] 识图: {VISION_SUMMARY}",
        }
    }


def _batch() -> list[dict[str, Any]]:
    return [{"id": "customer-followup-1", "message_id": "customer-followup-1", "sender": "customer", "type": "text", "content": "你刚发给我的是啥"}]


def _evidence(target_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = target_state or _target_state(_self_image_message())
    return build_reply_evidence_pack(
        config={"llm_reply_synthesis": {"max_history_messages": 20, "history_char_budget": 3000}},
        target_name="许聪",
        target_state=state,
        batch=_batch(),
        combined="你刚发给我的是啥",
        decision=SimpleNamespace(rule_name="test", reason="test", reply_text=""),
        reply_text="",
        intent_assist={},
        rag_reply={},
        llm_reply={},
        product_knowledge={},
        data_capture={},
        raw_capture={},
    )


def check_ledger_self_image_enters_existing_history_fields_without_raw_store() -> None:
    evidence = _evidence()
    conversation = evidence.get("conversation") or {}
    assert_true(VISION_SUMMARY in str(conversation.get("history_text") or ""), "ledger vision text must enter existing history_text when RawMessageStore is absent")
    history = conversation.get("history") or []
    assert_true(any(item.get("sender") == "self" and VISION_SUMMARY in str(item.get("content") or "") for item in history), "existing history list must carry the self direction and vision text")
    encoded = json.dumps(conversation, ensure_ascii=False)
    for forbidden in ("saved_image_path", "base64", "sha256", "bubble_bounds", "image_bytes"):
        assert_true(forbidden not in encoded, f"Brain conversation leaked forbidden image data: {forbidden}")


def check_fast_profile_cannot_drop_recent_multimodal_context() -> None:
    decision = low_authority_fast_profile_decision(
        settings={"low_authority_fast_profile_enabled": True},
        combined="你刚发给我的是啥",
        batch=_batch(),
        target_state=_target_state(_self_image_message()),
    )
    assert_equal(decision.get("enabled"), False, "recent trusted multimodal text must keep the full context path")


def check_latest_turn_recovery_preserves_recent_multimodal_text() -> None:
    state = _target_state(_self_image_message())
    evidence = _evidence(state)
    brain_input = build_brain_input(
        settings={"mode": "brain_first"},
        target_name="许聪",
        target_state=state,
        batch=_batch(),
        combined="你刚发给我的是啥",
        raw_capture={
            "context_recovery": {
                "schema_version": 1,
                "applied": True,
                "mode": "latest_turn_only_candidate",
                "reason": "history_recovery",
                "latest_message_ids": ["customer-followup-1"],
                "latest_customer_text": "你刚发给我的是啥",
            }
        },
        evidence_pack=evidence,
    )
    history_text = str(((brain_input.get("conversation") or {}).get("history_text") or ""))
    assert_true(VISION_SUMMARY in history_text, "context recovery may prune old history but must keep the recent trusted image text")


def check_unenriched_synthetic_placeholder_is_not_brain_history() -> None:
    placeholder = {
        "id": "clipboard_image_pending:fake",
        "sender": "customer",
        "type": "text",
        "modality": "image",
        "content": "客户发来了一张图片",
        "image_capture_pending": True,
        "quality_flags": ["synthetic_visual_turn", "clipboard_current_transaction_required"],
    }
    evidence = _evidence(_target_state(_self_image_message(), placeholder))
    history_text = str(((evidence.get("conversation") or {}).get("history_text") or ""))
    assert_true(VISION_SUMMARY in history_text, "valid self vision context must survive fake-placeholder filtering")
    assert_true("客户发来了一张图片" not in history_text, "unenriched synthetic customer placeholder must not become Brain history")


def check_empty_recent_history_clears_legacy_synthetic_summary() -> None:
    with tempfile.TemporaryDirectory(prefix="wechat-ledger-empty-summary-") as temp_dir:
        ledger = SessionLedgerStore(root=Path(temp_dir))
        path = ledger.summary_path("wx:empty-summary")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "recent_messages": [],
                    "context_summary": "客户: 客户发来了一张图片",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        summary = ledger.load_summary("wx:empty-summary")
        assert_equal(summary.get("context_summary"), "", "legacy fake image summary must be cleared even with no recent messages")


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected={expected!r}, actual={actual!r}")


if __name__ == "__main__":
    raise SystemExit(main())
