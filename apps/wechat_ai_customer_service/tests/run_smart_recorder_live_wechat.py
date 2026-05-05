"""Live WeChat end-to-end checks for the AI smart recorder.

This script sends synthetic test messages to a real WeChat desktop session,
captures them through the recorder flow, and verifies raw-message persistence,
RAG ingestion, and pending review-candidate generation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.adapters.wechat_connector import FILE_TRANSFER_ASSISTANT, WeChatConnector  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.recorder_service import RecorderService  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.raw_message_store import RawMessageStore  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import tenant_context, tenant_review_candidates_root  # noqa: E402
from apps.wechat_ai_customer_service.workflows.rag_layer import RagService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="default")
    parser.add_argument("--group-name", default="偷数据测试")
    parser.add_argument("--file-target", default=FILE_TRANSFER_ASSISTANT)
    parser.add_argument("--skip-send", action="store_true", help="Only capture and verify existing live test messages.")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM-assisted extraction for this live run.")
    parser.add_argument("--settle-seconds", type=float, default=1.8)
    args = parser.parse_args()

    with tenant_context(args.tenant):
        result = run_live_check(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


def run_live_check(args: argparse.Namespace) -> dict[str, Any]:
    batch_token = "LIVE_RECORDER_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    connector = WeChatConnector()
    status = connector.status()
    if not status.get("ok") or not status.get("online"):
        return {"ok": False, "phase": "wechat_status", "status": status}

    service = RecorderService()
    raw_store = RawMessageStore()
    service.save_settings(
        {
            "group_recording_enabled": True,
            "private_recording_enabled": True,
            "file_transfer_recording_enabled": True,
            "auto_learn": True,
            "use_llm": not args.no_llm,
            "notify_on_collect": False,
        }
    )
    group = service.ensure_conversation(
        {
            "target_name": args.group_name,
            "display_name": args.group_name,
            "conversation_type": "group",
            "selected_by_user": True,
            "status": "active",
            "exact": True,
            "learning_enabled": True,
            "notify_enabled": False,
            "source": {"type": "live_recorder_test", "batch_token": batch_token},
        }
    )
    file_target = service.ensure_conversation(
        {
            "target_name": args.file_target,
            "display_name": args.file_target,
            "conversation_type": "file_transfer",
            "selected_by_user": True,
            "status": "active",
            "exact": True,
            "learning_enabled": True,
            "notify_enabled": False,
            "source": {"type": "live_recorder_test", "batch_token": batch_token},
        }
    )

    baseline_results = [baseline_conversation(connector, raw_store, group), baseline_conversation(connector, raw_store, file_target)]
    if any(not item.get("ok") for item in baseline_results):
        return {"ok": False, "phase": "baseline", "batch_token": batch_token, "baseline": baseline_results}

    sent: list[dict[str, Any]] = []
    capture_history: list[dict[str, Any]] = []
    if not args.skip_send:
        for target, text in live_messages(args.group_name, args.file_target, batch_token):
            token = token_from_text(text)
            send_result = connector.send_text(target, text, exact=True)
            sent.append({"target": target, "ok": bool(send_result.get("ok")), "result": send_result, "token": token})
            time.sleep(max(0.5, args.settle_seconds))
            if not send_result.get("ok"):
                return {"ok": False, "phase": "send", "batch_token": batch_token, "sent": sent}
            capture_history.append(
                {
                    "target": target,
                    "token": token,
                    "capture": retry_capture_until_tokens(service, raw_store, [token], attempts=5, settle_seconds=args.settle_seconds),
                }
            )

    capture = retry_capture_until_tokens(service, raw_store, expected_tokens(batch_token), attempts=3, settle_seconds=args.settle_seconds)
    raw_checks = verify_raw_tokens(raw_store, expected_tokens(batch_token))
    rag_checks = verify_rag_tokens(expected_tokens(batch_token))
    candidate_checks = verify_candidate_expectations(batch_token)
    idempotency = verify_token_idempotency(service, raw_store, expected_tokens(batch_token))

    failures = []
    if not all(item.get("found") for item in raw_checks):
        failures.append("raw_missing_tokens")
    if not all(item.get("found") for item in rag_checks if item.get("required", True)):
        failures.append("rag_missing_tokens")
    if not candidate_checks.get("normal_candidate_found"):
        failures.append("normal_candidate_missing")
    if not candidate_checks.get("file_transfer_candidate_found"):
        failures.append("file_transfer_candidate_missing")
    if candidate_checks.get("noise_candidate_found"):
        failures.append("noise_created_candidate")
    if not idempotency.get("ok"):
        failures.append("idempotency_inserted_again")

    return {
        "ok": not failures,
        "batch_token": batch_token,
        "targets": {"group": group, "file_transfer": file_target},
        "sent": sent,
        "baseline": baseline_results,
        "capture_history": capture_history,
        "capture": capture,
        "raw_checks": raw_checks,
        "rag_checks": rag_checks,
        "candidate_checks": candidate_checks,
        "idempotency": idempotency,
        "failures": failures,
    }


def live_messages(group_name: str, file_target: str, batch_token: str) -> list[tuple[str, str]]:
    return [
        (
            group_name,
            "\n".join(
                [
                    f"商品资料：记录员正常产品 {batch_token}",
                    f"测试批次：{batch_token}",
                    "商品名称：2020款别克GL8 ES陆尊653T豪华型",
                    "型号：CHEJIN-LIVE-GL8-2020ES",
                    "商品类目：二手车/MPV",
                    "价格：17.66万",
                    "单位：台",
                    "库存：1",
                    "发货：南京门店可看车，商务客户试乘需人工确认",
                    "售后：车况以检测报告为准，事故、水泡、火烧承诺必须人工确认",
                ]
            ),
        ),
        (
            group_name,
            "\n".join(
                [
                    f"政策规则：记录员缺字段边界 {batch_token}",
                    f"测试批次：{batch_token}",
                    "规则名称：新能源电池检测转人工",
                    "规则类型：contract",
                    f"触发关键词：电池检测,首付,月供,贷款包过,{batch_token}",
                ]
            ),
        ),
        (
            group_name,
            f"边界噪音：{batch_token}_NOISE 今天天气和测试心跳记录，不是产品资料，也不是客服知识。",
        ),
        (
            file_target,
            "\n".join(
                [
                    f"聊天记录：记录员文件传输助手话术 {batch_token}",
                    f"客户：我想买新能源通勤，能看秦PLUS吗？批次 {batch_token}",
                    "客服：可以先看秦PLUS DM-i，低油耗适合通勤；电池检测、当地迁入和金融方案都需要人工确认。",
                    "意图标签：新能源通勤,车源推荐,金融边界",
                ]
            ),
        ),
    ]


def expected_tokens(batch_token: str) -> list[str]:
    return [
        f"商品资料：记录员正常产品 {batch_token}",
        f"政策规则：记录员缺字段边界 {batch_token}",
        f"{batch_token}_NOISE",
        f"记录员文件传输助手话术 {batch_token}",
    ]


def token_from_text(text: str) -> str:
    for line in text.splitlines():
        if "LIVE_RECORDER_" in line:
            return line.strip()
    return text[:80]


def baseline_conversation(connector: WeChatConnector, raw_store: RawMessageStore, conversation: dict[str, Any]) -> dict[str, Any]:
    target = str(conversation.get("target_name") or "")
    payload = connector.get_messages(target, exact=conversation.get("exact", True) is not False)
    if not payload.get("ok"):
        return {"ok": False, "target": target, "messages": payload}
    result = raw_store.upsert_messages(
        conversation,
        [item for item in payload.get("messages", []) or [] if isinstance(item, dict)],
        source_module="smart_recorder_live_baseline",
        learning_enabled=False,
        create_batch=False,
        batch_reason="live_test_baseline",
    )
    return {"ok": True, "target": target, "baseline_message_count": len(payload.get("messages", []) or []), "result": result}


def retry_capture_until_tokens(
    service: RecorderService,
    raw_store: RawMessageStore,
    tokens: list[str],
    *,
    attempts: int,
    settle_seconds: float,
) -> dict[str, Any]:
    captures = []
    for _ in range(max(1, attempts)):
        capture = service.capture_selected_once(send_notifications=False)
        captures.append(capture)
        raw_checks = verify_raw_tokens(raw_store, tokens)
        if all(item.get("found") for item in raw_checks):
            return {"ok": True, "captures": captures, "raw_checks": raw_checks}
        time.sleep(max(0.5, settle_seconds))
    return {"ok": False, "captures": captures, "raw_checks": verify_raw_tokens(raw_store, tokens)}


def verify_raw_tokens(raw_store: RawMessageStore, tokens: list[str]) -> list[dict[str, Any]]:
    messages = raw_store.list_messages(limit=500)
    return [
        {
            "token": token,
            "found": any(token in str(item.get("content") or "") for item in messages),
            "message_ids": [item.get("raw_message_id") for item in messages if token in str(item.get("content") or "")],
        }
        for token in tokens
    ]


def verify_token_idempotency(service: RecorderService, raw_store: RawMessageStore, tokens: list[str]) -> dict[str, Any]:
    before = raw_token_message_ids(raw_store, tokens)
    capture = service.capture_selected_once(send_notifications=False)
    after = raw_token_message_ids(raw_store, tokens)
    checks = [
        {
            "token": token,
            "before_ids": before.get(token, []),
            "after_ids": after.get(token, []),
            "unchanged": before.get(token, []) == after.get(token, []),
        }
        for token in tokens
    ]
    return {
        "ok": all(item["unchanged"] for item in checks),
        "capture": capture,
        "token_checks": checks,
    }


def raw_token_message_ids(raw_store: RawMessageStore, tokens: list[str]) -> dict[str, list[str]]:
    messages = raw_store.list_messages(limit=500)
    return {
        token: sorted(
            str(item.get("raw_message_id") or "")
            for item in messages
            if token in str(item.get("content") or "")
        )
        for token in tokens
    }


def verify_rag_tokens(tokens: list[str]) -> list[dict[str, Any]]:
    rag = RagService()
    results = []
    for token in tokens:
        search = rag.search(token, limit=30)
        found = any(token in str(hit.get("text") or "") for hit in search.get("hits", []) or [])
        results.append({"token": token, "found": found, "required": "_NOISE" not in token, "search": compact_search(search)})
    return results


def compact_search(search: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": search.get("ok"),
        "hit_count": len(search.get("hits", []) or []),
        "hits": [
            {"source_id": hit.get("source_id"), "score": hit.get("score"), "text": str(hit.get("text") or "")[:180]}
            for hit in (search.get("hits", []) or [])[:3]
        ],
    }


def verify_candidate_expectations(batch_token: str) -> dict[str, Any]:
    candidates = list_candidate_payloads()

    def contains(token: str, candidate: dict[str, Any]) -> bool:
        return token in candidate_structured_text(candidate)

    normal = [item for item in candidates if contains(f"商品资料：记录员正常产品 {batch_token}", item) or contains("2020款别克GL8 ES陆尊653T豪华型", item)]
    file_transfer = [item for item in candidates if contains(f"批次 {batch_token}", item) or contains("秦PLUS", item)]
    incomplete = [item for item in candidates if contains(f"政策规则：记录员缺字段边界 {batch_token}", item) or contains("新能源电池检测转人工", item)]
    noise = [item for item in candidates if contains(f"{batch_token}_NOISE", item)]
    return {
        "normal_candidate_found": bool(normal),
        "normal_candidate_ids": [item.get("candidate_id") for item in normal],
        "file_transfer_candidate_found": bool(file_transfer),
        "file_transfer_candidate_ids": [item.get("candidate_id") for item in file_transfer],
        "incomplete_candidate_found": bool(incomplete),
        "incomplete_candidate_ids": [item.get("candidate_id") for item in incomplete],
        "incomplete_statuses": [candidate_status(item) for item in incomplete],
        "noise_candidate_found": bool(noise),
        "noise_candidate_ids": [item.get("candidate_id") for item in noise],
    }


def candidate_structured_text(candidate: dict[str, Any]) -> str:
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    patch = proposal.get("formal_patch") if isinstance(proposal.get("formal_patch"), dict) else {}
    item = patch.get("item") if isinstance(patch.get("item"), dict) else {}
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    payload = {
        "candidate_id": candidate.get("candidate_id"),
        "target_category": patch.get("target_category"),
        "summary": proposal.get("summary"),
        "suggested_fields": proposal.get("suggested_fields"),
        "item_data": item.get("data") if isinstance(item.get("data"), dict) else {},
        "evidence_excerpt": source.get("evidence_excerpt"),
    }
    return json.dumps(payload, ensure_ascii=False)


def list_candidate_payloads() -> list[dict[str, Any]]:
    items = []
    for status in ("pending", "approved", "rejected"):
        root = tenant_review_candidates_root() / status
        if not root.exists():
            continue
        for path in root.glob("*.json"):
            try:
                items.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
    return items


def candidate_status(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": candidate.get("candidate_id"),
        "review_status": (candidate.get("review") or {}).get("status"),
        "completeness_status": (candidate.get("review") or {}).get("completeness_status") or (candidate.get("intake") or {}).get("status"),
        "missing_fields": (candidate.get("intake") or {}).get("missing_fields") or (candidate.get("review") or {}).get("missing_fields") or [],
    }


if __name__ == "__main__":
    raise SystemExit(main())
