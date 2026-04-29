"""Config-driven guarded WeChat customer-service workflow.

This workflow is the next layer above the single-target minimal loop. It can
poll multiple whitelisted conversations, aggregate recent unprocessed messages,
apply deterministic rules, enforce simple rate limits, optionally send, verify
by reading back, and append audit events.

Default behavior is safe:
- one pass only, unless configured or overridden;
- dry-run unless ``--send`` is passed;
- target conversations must be explicitly enabled in the config;
- fallback replies are blocked unless allowed in the config or CLI.
"""

from __future__ import annotations

from pathlib import Path as _CompatPath
import runpy as _compat_runpy

if __name__ == "__main__":
    _repo_root = _CompatPath(__file__).resolve().parents[4]
    _app_entry = _repo_root / "apps/wechat_ai_customer_service/workflows/listen_and_reply.py"
    _compat_runpy.run_path(str(_app_entry), run_name="__main__")
    raise SystemExit(0)

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from customer_data_capture import append_customer_row, extract_customer_data
from customer_intent_assist import (
    analyze_intent,
    build_llm_prompt_pack,
    call_deepseek_advisory,
    validate_llm_candidate,
)
from customer_service_loop import BOT_PREFIX, ReplyDecision, decide_reply, format_reply, load_rules
from product_knowledge import decide_product_knowledge_reply, load_product_knowledge
from wechat_connector import FILE_TRANSFER_ASSISTANT, ROOT, WeChatConnector


CONFIG_PATH = ROOT / "workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.example.json"
MAX_STORED_IDS = 1000


@dataclass(frozen=True)
class TargetConfig:
    name: str
    enabled: bool
    exact: bool
    allow_self_for_test: bool
    max_batch_messages: int


class StateLock:
    """Small cross-process lock for workflow state writes."""

    def __init__(self, path: Path, timeout_seconds: int, stale_seconds: int) -> None:
        self.path = path
        self.timeout_seconds = max(1, timeout_seconds)
        self.stale_seconds = max(60, stale_seconds)
        self.fd: int | None = None

    def __enter__(self) -> "StateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + self.timeout_seconds
        while True:
            self.remove_stale_lock()
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                payload = f"pid={os.getpid()}\ncreated_at={datetime.now().isoformat(timespec='seconds')}\n"
                os.write(self.fd, payload.encode("utf-8"))
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError(f"Workflow state is locked: {self.path}")
                time.sleep(0.5)

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def remove_stale_lock(self) -> None:
        try:
            age_seconds = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        if age_seconds < self.stale_seconds:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--once", action="store_true", help="Run exactly one iteration.")
    parser.add_argument("--iterations", type=int, help="Override configured iteration count.")
    parser.add_argument("--interval-seconds", type=int, help="Override configured poll interval.")
    parser.add_argument("--send", action="store_true", help="Actually send replies.")
    parser.add_argument(
        "--allow-fallback-send",
        action="store_true",
        help="Allow sending default replies when no rule matched.",
    )
    parser.add_argument(
        "--mark-dry-run",
        action="store_true",
        help="Mark planned dry-run batches as processed.",
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="Mark existing text messages as processed without replying.",
    )
    parser.add_argument(
        "--write-data",
        action="store_true",
        help="Write extracted customer data to Excel.",
    )
    parser.add_argument(
        "--target",
        action="append",
        help=(
            "Temporary runtime target for bootstrap/dry-run checks. "
            "Send mode is blocked for runtime targets unless they are in config."
        ),
    )
    args = parser.parse_args()

    try:
        result = run_workflow(args)
    except Exception as exc:
        result = {"ok": False, "error": repr(exc)}

    print_json(result)
    return 0 if result.get("ok") else 1


def run_workflow(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(args.config)
    state_path = resolve_path(config.get("state_path"))
    audit_path = resolve_path(config.get("audit_log_path"))
    rules = load_rules(resolve_path(config.get("rules_path")))

    iterations = resolve_iterations(args, config)
    interval = int(args.interval_seconds or config.get("poll", {}).get("interval_seconds", 15))
    targets = parse_targets(config)
    if args.target:
        if args.send:
            configured_names = {target.name for target in targets}
            runtime_names = {str(name).strip() for name in args.target if str(name).strip()}
            non_configured = sorted(runtime_names - configured_names)
            if non_configured:
                raise ValueError(
                    "Runtime --target is only allowed for bootstrap/dry-run. "
                    "Add runtime targets to config before --send."
                )
        targets = parse_runtime_targets(args.target, config_targets=targets)
    lock_settings = config.get("state_lock", {}) or {}
    with StateLock(
        state_path.with_suffix(state_path.suffix + ".lock"),
        timeout_seconds=int(lock_settings.get("timeout_seconds", 120)),
        stale_seconds=int(lock_settings.get("stale_seconds", 900)),
    ):
        connector = WeChatConnector()
        state = load_state(state_path)

        status = connector.require_online()
        summary: dict[str, Any] = {
            "ok": True,
            "dry_run": not args.send,
            "iterations": iterations,
            "status": status,
            "targets": [target.name for target in targets],
            "events": [],
        }

        for iteration in range(iterations):
            iteration_events = []
            for target in targets:
                if args.bootstrap:
                    event = bootstrap_target(connector, target, state)
                else:
                    event = process_target(
                        connector=connector,
                        target=target,
                        config=config,
                        rules=rules,
                        state=state,
                        send=bool(args.send),
                        write_data=bool(args.write_data),
                        allow_fallback_send=bool(args.allow_fallback_send),
                        mark_dry_run=bool(args.mark_dry_run),
                    )
                event["iteration"] = iteration + 1
                append_audit(audit_path, event)
                iteration_events.append(event)
            save_state(state_path, state)
            summary["events"].extend(iteration_events)
            if iteration < iterations - 1:
                time.sleep(max(1, interval))

    return summary


def process_target(
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    rules: dict[str, Any],
    state: dict[str, Any],
    send: bool,
    write_data: bool,
    allow_fallback_send: bool,
    mark_dry_run: bool,
) -> dict[str, Any]:
    target_state = state.setdefault("targets", {}).setdefault(
        target.name,
        {
            "processed_message_ids": [],
            "handoff_message_ids": [],
            "sent_replies": [],
            "reply_timestamps": [],
        },
    )
    payload = connector.get_messages(target.name, exact=target.exact)
    if not payload.get("ok"):
        return base_event(target, "error", {"messages": payload})

    batch = select_batch(
        payload.get("messages", []) or [],
        target_state=target_state,
        allow_self_for_test=target.allow_self_for_test,
        max_batch_messages=target.max_batch_messages,
    )
    if not batch:
        return base_event(target, "skipped", {"reason": "no eligible unprocessed text messages"})

    combined = "\n".join(str(item.get("content") or "") for item in batch)
    message_ids = [str(item.get("id") or "") for item in batch]
    if send:
        backoff = get_rate_limit_backoff(target_state, message_ids)
        if backoff:
            return base_event(
                target,
                "skipped",
                {
                    "reason": "rate_limit_backoff_active",
                    "message_ids": message_ids,
                    "message_count": len(batch),
                    "retry_after_at": backoff.get("retry_after_at"),
                    "rate_limit_reason": backoff.get("reason"),
                },
            )

    data_capture = maybe_capture_customer_data(
        config=config,
        target_state=target_state,
        target=target,
        batch=batch,
        combined=combined,
        write_data=False,
    )
    if data_capture.get("enabled"):
        data_capture["write_requested"] = write_data
    product_knowledge = maybe_match_product_knowledge(config, target_state, combined, data_capture)
    update_conversation_context(target_state, product_knowledge)
    decision = decide_reply_with_data_capture(combined, rules, config, data_capture, product_knowledge)
    reply_prefix = str(config.get("reply", {}).get("prefix", BOT_PREFIX + " "))
    reply_text = format_reply(decision.reply_text, reply_prefix)
    fallback_allowed = bool(allow_fallback_send or config.get("reply", {}).get("allow_fallback_send"))

    event = base_event(
        target,
        "planned",
        {
            "message_ids": message_ids,
            "message_count": len(batch),
            "combined_content": combined,
            "decision": {
                **decision.__dict__,
                "raw_reply_text": decision.reply_text,
                "reply_text": reply_text,
            },
            "data_capture": data_capture,
            "product_knowledge": product_knowledge,
            "intent_assist": skipped_intent_assist(config, "not_evaluated_yet"),
            "dry_run": not send,
        },
    )

    rate_check = check_rate_limit(target_state, config)
    if send and not rate_check["allowed"]:
        return handle_rate_limit_block(
            connector=connector,
            target=target,
            config=config,
            target_state=target_state,
            event=event,
            message_ids=message_ids,
            rate_check=rate_check,
        )

    clear_rate_limit_backoff(target_state, message_ids)

    operator_handoff = should_operator_handoff(decision, product_knowledge, fallback_allowed)
    if send and operator_handoff:
        handoff_reply_text = build_operator_handoff_reply_text(config, decision, product_knowledge, reply_text)
        event["decision"]["reply_text"] = handoff_reply_text
        event["intent_assist"] = skipped_intent_assist(config, "operator_handoff")
        verified = connector.send_text_and_verify(target.name, handoff_reply_text, exact=target.exact)
        event["send_result"] = verified
        event["verified"] = bool(verified.get("verified"))
        if not event["verified"]:
            event["action"] = "error"
            event["ok"] = False
            return event
        alert = record_operator_alert(
            config=config,
            target_state=target_state,
            target=target,
            batch=batch,
            combined=combined,
            reason=handoff_reason(decision, product_knowledge),
            reply_text=handoff_reply_text,
            product_knowledge=product_knowledge,
        )
        mark_handoff(
            target_state,
            batch,
            reason=handoff_reason(decision, product_knowledge),
            status="open",
            operator_alert=alert,
        )
        mark_processed(target_state, batch, handoff_reply_text)
        record_reply_timestamp(target_state)
        event["operator_alert"] = alert
        event["action"] = "handoff_sent"
        return event

    if send and not decision.matched and not fallback_allowed:
        mark_handoff(target_state, batch, reason="no_rule_matched", status="open")
        event["action"] = "handoff"
        event["reason"] = "fallback reply blocked"
        event["intent_assist"] = skipped_intent_assist(config, "fallback_reply_blocked")
        return event

    if data_capture.get("is_customer_data") and data_capture.get("complete") and write_data:
        write_customer_data_if_ready(config, target, data_capture)

    if (
        send
        and data_capture.get("is_customer_data")
        and data_capture.get("complete")
        and not data_capture.get("write_result", {}).get("ok")
    ):
        event["data_capture"] = data_capture
        event["action"] = "blocked"
        event["reason"] = "customer data was not written; pass --write-data"
        event["intent_assist"] = skipped_intent_assist(config, "customer_data_write_blocked")
        return event

    event["data_capture"] = data_capture
    event["intent_assist"] = maybe_analyze_intent(
        config=config,
        combined=combined,
        decision=decision,
        reply_text=reply_text,
        data_capture=data_capture,
        product_knowledge=product_knowledge,
    )

    should_mark_after_data_write = bool(data_capture.get("write_result", {}).get("ok") and not send)

    if send:
        verified = connector.send_text_and_verify(target.name, reply_text, exact=target.exact)
        event["send_result"] = verified
        event["verified"] = bool(verified.get("verified"))
        if not event["verified"]:
            event["action"] = "error"
            event["ok"] = False
            return event
        finalize_data_capture_state(target_state, data_capture)
        mark_processed(target_state, batch, reply_text)
        record_reply_timestamp(target_state)
        event["action"] = "sent"
        return event

    if should_mark_after_data_write:
        finalize_data_capture_state(target_state, data_capture)
        mark_processed(target_state, batch, reply_text)
        event["marked_processed"] = True
        event["action"] = "captured"
        return event

    if mark_dry_run:
        finalize_data_capture_state(target_state, data_capture)
        mark_processed(target_state, batch, reply_text)
        event["marked_processed"] = True
    return event


def handle_rate_limit_block(
    connector: WeChatConnector,
    target: TargetConfig,
    config: dict[str, Any],
    target_state: dict[str, Any],
    event: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
) -> dict[str, Any]:
    record_rate_limit_backoff(target_state, message_ids, rate_check)
    event["action"] = "blocked"
    event["reason"] = rate_check["reason"]
    event["rate_limit"] = rate_check
    event["intent_assist"] = skipped_intent_assist(
        config,
        "rate_limited",
        {"rate_limit": rate_check},
    )
    if not should_send_rate_limit_notice(target_state, config, rate_check):
        return event

    reply_prefix = str(config.get("reply", {}).get("prefix", BOT_PREFIX + " "))
    notice_text = format_reply(build_rate_limit_notice_text(config, rate_check), reply_prefix)
    verified = connector.send_text_and_verify(target.name, notice_text, exact=target.exact)
    event["rate_limit_notice"] = {
        "reply_text": notice_text,
        "send_result": verified,
        "verified": bool(verified.get("verified")),
    }
    if event["rate_limit_notice"]["verified"]:
        record_rate_limit_notice(target_state, message_ids, rate_check, notice_text)
        event["action"] = "rate_limit_notice_sent"
    return event


def should_operator_handoff(
    decision: ReplyDecision,
    product_knowledge: dict[str, Any],
    fallback_allowed: bool,
) -> bool:
    if product_knowledge.get("needs_handoff"):
        return True
    if not decision.matched and not fallback_allowed:
        return True
    if decision.reason in {"approval_required", "no_rule_matched"}:
        return True
    return False


def build_operator_handoff_reply_text(
    config: dict[str, Any],
    decision: ReplyDecision,
    product_knowledge: dict[str, Any],
    current_reply_text: str,
) -> str:
    if product_knowledge.get("reply_text"):
        return current_reply_text
    settings = config.get("handoff", {}) or {}
    reply = str(
        settings.get("acknowledgement_reply")
        or "这个问题我当前无法直接确认，我先帮您记录并请示上级，稍后给您准确回复。"
    )
    reply_prefix = str(config.get("reply", {}).get("prefix", BOT_PREFIX + " "))
    return format_reply(reply, reply_prefix)


def handoff_reason(decision: ReplyDecision, product_knowledge: dict[str, Any]) -> str:
    if product_knowledge.get("approval_reason"):
        return str(product_knowledge.get("approval_reason"))
    if product_knowledge.get("needs_handoff"):
        return str(product_knowledge.get("reason") or "product_knowledge_requires_handoff")
    return str(decision.reason or "operator_handoff")


def record_operator_alert(
    config: dict[str, Any],
    target_state: dict[str, Any],
    target: TargetConfig,
    batch: list[dict[str, Any]],
    combined: str,
    reason: str,
    reply_text: str,
    product_knowledge: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("operator_alert", {}) or {}
    alert = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target.name,
        "message_ids": [str(item.get("id") or "") for item in batch],
        "message_contents": [str(item.get("content") or "") for item in batch],
        "combined_content": combined,
        "reason": reason,
        "reply_text": reply_text,
        "product_knowledge": product_knowledge,
        "status": "open",
    }
    if settings.get("enabled", True):
        alert_path = resolve_path(settings.get("alert_log_path") or "runtime/logs/wechat_customer_service/operator_alerts.jsonl")
        append_jsonl(alert_path, alert)
        alert["delivery"] = {"type": "jsonl", "path": str(alert_path), "ok": True}
    else:
        alert["delivery"] = {"type": "disabled", "ok": False}
    target_state.setdefault("operator_alerts", []).append(alert)
    target_state["operator_alerts"] = target_state["operator_alerts"][-MAX_STORED_IDS:]
    return alert


def maybe_capture_customer_data(
    config: dict[str, Any],
    target_state: dict[str, Any],
    target: TargetConfig,
    batch: list[dict[str, Any]],
    combined: str,
    write_data: bool,
) -> dict[str, Any]:
    settings = config.get("data_capture", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}

    pending = get_open_pending_customer_data(target_state)
    pending_raw_text = str(pending.get("raw_text") or "") if pending else ""
    pending_message_ids = [str(item) for item in pending.get("message_ids", [])] if pending else []
    current_message_ids = [str(item.get("id") or "") for item in batch]
    merged_text = "\n".join(item for item in [pending_raw_text, combined] if item.strip())
    merged_message_ids = unique_list([*pending_message_ids, *current_message_ids])

    required_fields = [str(item) for item in settings.get("required_fields", ["name", "phone"])]
    extraction = extract_customer_data(merged_text, required_fields=required_fields)
    result: dict[str, Any] = {
        "enabled": True,
        "is_customer_data": extraction.is_customer_data,
        "complete": extraction.complete,
        "fields": extraction.fields,
        "missing_required_fields": extraction.missing_required_fields,
        "missing_required_labels": missing_field_labels(extraction.missing_required_fields),
        "pending_before": copy.deepcopy(pending),
        "message_ids": merged_message_ids,
        "raw_text": merged_text,
        "write_requested": write_data,
    }
    if not extraction.is_customer_data:
        return result
    if not extraction.complete:
        result["write_skipped_reason"] = "missing_required_fields"
        return result
    if not write_data:
        result["write_skipped_reason"] = "write_data_not_requested"
        return result

    workbook_path = resolve_path(settings.get("workbook_path"))
    sheet_name = str(settings.get("sheet_name") or "客户线索")
    result["write_result"] = append_customer_row(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        source_target=target.name,
        message_ids=merged_message_ids,
        raw_text=merged_text,
        fields=extraction.fields,
    )
    return result


def write_customer_data_if_ready(
    config: dict[str, Any],
    target: TargetConfig,
    data_capture: dict[str, Any],
) -> None:
    if not data_capture.get("enabled") or not data_capture.get("is_customer_data"):
        return
    if not data_capture.get("complete"):
        return
    if data_capture.get("write_result", {}).get("ok"):
        return

    settings = config.get("data_capture", {}) or {}
    workbook_path = resolve_path(settings.get("workbook_path"))
    sheet_name = str(settings.get("sheet_name") or "客户线索")
    data_capture["write_requested"] = True
    data_capture.pop("write_skipped_reason", None)
    data_capture["write_result"] = append_customer_row(
        workbook_path=workbook_path,
        sheet_name=sheet_name,
        source_target=target.name,
        message_ids=[str(item) for item in data_capture.get("message_ids", [])],
        raw_text=str(data_capture.get("raw_text") or ""),
        fields=data_capture.get("fields", {}) or {},
    )


def decide_reply_with_data_capture(
    combined: str,
    rules: dict[str, Any],
    config: dict[str, Any],
    data_capture: dict[str, Any],
    product_knowledge: dict[str, Any] | None = None,
) -> ReplyDecision:
    if data_capture.get("is_customer_data"):
        if data_capture.get("complete"):
            reply = data_capture_reply(config, data_capture, complete=True)
            return ReplyDecision(
                reply_text=reply,
                rule_name="customer_data_capture",
                matched=True,
                need_handoff=False,
                reason="customer_data_complete",
            )
        reply = data_capture_reply(config, data_capture, complete=False)
        return ReplyDecision(
            reply_text=reply,
            rule_name="customer_data_incomplete",
            matched=True,
            need_handoff=True,
            reason="customer_data_missing_required_fields",
            )
    if product_knowledge and product_knowledge.get("matched") and product_knowledge.get("reply_text"):
        return ReplyDecision(
            reply_text=str(product_knowledge.get("reply_text") or ""),
            rule_name="product_knowledge",
            matched=True,
            need_handoff=bool(product_knowledge.get("needs_handoff")),
            reason=str(product_knowledge.get("reason") or "product_knowledge_matched"),
        )
    return decide_reply(combined, rules)


def maybe_match_product_knowledge(
    config: dict[str, Any],
    target_state: dict[str, Any],
    combined: str,
    data_capture: dict[str, Any],
) -> dict[str, Any]:
    settings = config.get("product_knowledge", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}
    if data_capture.get("is_customer_data"):
        return {"enabled": True, "matched": False, "reason": "skipped_for_customer_data"}
    path = resolve_path(settings.get("path"))
    knowledge = load_product_knowledge(path)
    result = decide_product_knowledge_reply(
        combined,
        knowledge,
        context=target_state.get("conversation_context", {}) or {},
    )
    result["path"] = str(path)
    return result


def update_conversation_context(target_state: dict[str, Any], product_knowledge: dict[str, Any]) -> None:
    if not product_knowledge.get("matched"):
        return
    if product_knowledge.get("match_type") != "product":
        return
    context = dict(target_state.get("conversation_context", {}) or {})
    context["last_product_id"] = product_knowledge.get("product_id")
    context["last_product_name"] = product_knowledge.get("product_name")
    context["last_product_unit"] = product_knowledge.get("product_unit")
    if product_knowledge.get("quantity") not in (None, ""):
        context["last_quantity"] = product_knowledge.get("quantity")
    if product_knowledge.get("shipping_city"):
        context["last_shipping_city"] = product_knowledge.get("shipping_city")
    if product_knowledge.get("unit_price") not in (None, ""):
        context["last_unit_price"] = product_knowledge.get("unit_price")
    if product_knowledge.get("total") not in (None, ""):
        context["last_total"] = product_knowledge.get("total")
    context["updated_at"] = datetime.now().isoformat(timespec="seconds")
    target_state["conversation_context"] = context


def maybe_analyze_intent(
    config: dict[str, Any],
    combined: str,
    decision: ReplyDecision,
    reply_text: str,
    data_capture: dict[str, Any],
    product_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.get("intent_assist", {}) or {}
    if not settings.get("enabled", False):
        return {"enabled": False}
    mode = str(settings.get("mode") or "heuristic")
    if mode != "heuristic":
        return {
            "enabled": True,
            "mode": mode,
            "ok": False,
            "reason": "unsupported_intent_assist_mode",
        }

    analysis_context = build_intent_context(config, data_capture, decision, product_knowledge or {})
    result = analyze_intent(combined, context=analysis_context)
    payload = {
        **result.__dict__,
        "ok": True,
        "advisory_only": bool(settings.get("advisory_only", True)),
        "rule_decision": {
            "rule_name": decision.rule_name,
            "matched": decision.matched,
            "reason": decision.reason,
            "reply_text": reply_text,
        },
    }
    suggested_reply = str(payload.get("suggested_reply") or "")
    payload["would_change_reply"] = bool(suggested_reply and suggested_reply not in reply_text)
    payload["llm_advisory"] = build_llm_advisory(
        settings=settings,
        combined=combined,
        context=analysis_context,
        heuristic=result,
    )
    return payload


def build_intent_context(
    config: dict[str, Any],
    data_capture: dict[str, Any],
    decision: ReplyDecision,
    product_knowledge: dict[str, Any],
) -> dict[str, Any]:
    return {
        "service_profile": config.get("service_profile", {}) or {},
        "answer_policy": {
            "use_known_facts_only": True,
            "unknown_or_authority_required_action": "handoff",
            "never_invent_price_stock_shipping_or_policy": True,
        },
        "data_capture": data_capture,
        "product_knowledge": product_knowledge,
        "rule_decision": decision.__dict__,
    }


def skipped_intent_assist(
    config: dict[str, Any],
    reason: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config.get("intent_assist", {}) or {}
    payload: dict[str, Any] = {
        "enabled": bool(settings.get("enabled", False)),
        "skipped": True,
        "reason": reason,
    }
    if settings:
        payload["mode"] = str(settings.get("mode") or "heuristic")
        llm_settings = settings.get("llm_advisory", {}) or {}
        if llm_settings:
            payload["llm_advisory"] = {
                "enabled": bool(llm_settings.get("enabled", False)),
                "skipped": True,
                "reason": reason,
            }
    if extra:
        payload.update(extra)
    return payload


def build_llm_advisory(
    settings: dict[str, Any],
    combined: str,
    context: dict[str, Any],
    heuristic: Any,
) -> dict[str, Any]:
    llm_settings = settings.get("llm_advisory", {}) or {}
    if not llm_settings.get("enabled", False):
        return {"enabled": False}

    provider = str(llm_settings.get("provider") or "manual_json")
    prompt_pack = build_llm_prompt_pack(combined, context=context, heuristic=heuristic)
    advisory: dict[str, Any] = {
        "enabled": True,
        "provider": provider,
        "advisory_only": bool(llm_settings.get("advisory_only", True)),
        "schema_version": prompt_pack.get("schema_version"),
        "status": "prompt_pack_ready",
    }
    if llm_settings.get("include_prompt_in_audit", False):
        advisory["prompt_pack"] = prompt_pack

    if provider == "deepseek":
        advisory["status"] = "provider_called"
        advisory["result"] = call_deepseek_advisory(
            combined,
            context=context,
            heuristic=heuristic,
            model=str(llm_settings.get("model") or ""),
            base_url=str(llm_settings.get("base_url") or ""),
            timeout=int(llm_settings.get("timeout_seconds", 60)),
        )
        return advisory

    candidate_path_value = str(llm_settings.get("candidate_json_path") or "").strip()
    if not candidate_path_value:
        return advisory

    candidate_path = resolve_path(candidate_path_value)
    advisory["candidate_json_path"] = str(candidate_path)
    if not candidate_path.exists():
        advisory["status"] = "candidate_file_missing"
        return advisory

    try:
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    except Exception as exc:
        advisory["status"] = "candidate_file_error"
        advisory["error"] = repr(exc)
        return advisory

    advisory["status"] = "candidate_validated"
    advisory["validation"] = validate_llm_candidate(candidate, heuristic=heuristic)
    return advisory


def data_capture_reply(config: dict[str, Any], data_capture: dict[str, Any], complete: bool) -> str:
    settings = config.get("data_capture", {}) or {}
    if complete:
        return str(settings.get("success_reply") or "客户资料已记录，我会尽快为您继续处理。")
    missing = "、".join(data_capture.get("missing_required_labels", []) or data_capture.get("missing_required_fields", []) or [])
    template = str(settings.get("incomplete_reply") or "客户资料还缺少：{missing_fields}。请补充后我再记录。")
    return template.format(missing_fields=missing)


def finalize_data_capture_state(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    if not data_capture.get("enabled") or not data_capture.get("is_customer_data"):
        return
    if data_capture.get("complete") and data_capture.get("write_result", {}).get("ok"):
        close_pending_customer_data(target_state, data_capture)
    elif not data_capture.get("complete"):
        upsert_pending_customer_data(target_state, data_capture)


def get_open_pending_customer_data(target_state: dict[str, Any]) -> dict[str, Any] | None:
    pending_items = target_state.get("pending_customer_data", []) or []
    for item in reversed(pending_items):
        if item.get("status") == "waiting_for_fields":
            return item
    return None


def upsert_pending_customer_data(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    pending_items = list(target_state.get("pending_customer_data", []) or [])
    pending = get_open_pending_customer_data(target_state)
    entry = {
        "status": "waiting_for_fields",
        "fields": data_capture.get("fields", {}),
        "missing_required_fields": data_capture.get("missing_required_fields", []),
        "missing_required_labels": data_capture.get("missing_required_labels", []),
        "message_ids": data_capture.get("message_ids", []),
        "raw_text": data_capture.get("raw_text", ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    if pending:
        entry["created_at"] = pending.get("created_at") or entry["updated_at"]
        for index, item in enumerate(pending_items):
            if item is pending:
                pending_items[index] = entry
                break
        else:
            pending_items.append(entry)
    else:
        entry["created_at"] = entry["updated_at"]
        pending_items.append(entry)
    target_state["pending_customer_data"] = pending_items[-MAX_STORED_IDS:]


def close_pending_customer_data(target_state: dict[str, Any], data_capture: dict[str, Any]) -> None:
    pending_items = list(target_state.get("pending_customer_data", []) or [])
    now = datetime.now().isoformat(timespec="seconds")
    for item in reversed(pending_items):
        if item.get("status") == "waiting_for_fields":
            item["status"] = "completed"
            item["completed_at"] = now
            item["completed_message_ids"] = data_capture.get("message_ids", [])
            item["write_result"] = data_capture.get("write_result")
            break
    target_state["pending_customer_data"] = pending_items[-MAX_STORED_IDS:]


def missing_field_labels(fields: list[str]) -> list[str]:
    labels = {
        "name": "姓名",
        "phone": "电话",
        "address": "地址",
        "product": "产品",
        "quantity": "数量",
        "spec": "规格",
        "budget": "预算",
        "note": "备注",
    }
    return [labels.get(field, field) for field in fields]


def unique_list(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def bootstrap_target(
    connector: WeChatConnector,
    target: TargetConfig,
    state: dict[str, Any],
) -> dict[str, Any]:
    target_state = state.setdefault("targets", {}).setdefault(
        target.name,
        {
            "processed_message_ids": [],
            "handoff_message_ids": [],
            "sent_replies": [],
            "reply_timestamps": [],
        },
    )
    payload = connector.get_messages(target.name, exact=target.exact)
    if not payload.get("ok"):
        return base_event(target, "error", {"messages": payload})

    processed = list(target_state.get("processed_message_ids", []))
    added = []
    for message in payload.get("messages", []) or []:
        message_id = str(message.get("id") or "")
        content = str(message.get("content") or "").strip()
        if not message_id or not content or message.get("type") != "text":
            continue
        if content.startswith(BOT_PREFIX):
            continue
        if message_id not in processed:
            processed.append(message_id)
            added.append(message_id)
    target_state["processed_message_ids"] = processed[-MAX_STORED_IDS:]
    target_state.setdefault("bootstrap_events", []).append(
        {
            "message_ids": added,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return base_event(
        target,
        "bootstrapped",
        {"marked_message_ids": added, "marked_count": len(added)},
    )


def select_batch(
    messages: list[dict[str, Any]],
    target_state: dict[str, Any],
    allow_self_for_test: bool,
    max_batch_messages: int,
) -> list[dict[str, Any]]:
    processed = set(target_state.get("processed_message_ids", []))
    handoff = set(target_state.get("handoff_message_ids", []))
    selected: list[dict[str, Any]] = []
    for message in reversed(messages):
        message_id = str(message.get("id") or "")
        content = str(message.get("content") or "").strip()
        sender = str(message.get("sender") or "")
        if not message_id or message_id in processed or message_id in handoff:
            if selected:
                break
            continue
        if message.get("type") != "text" or not content:
            if selected:
                break
            continue
        if content.startswith(BOT_PREFIX):
            if selected:
                break
            continue
        if sender == "self" and not allow_self_for_test:
            if selected:
                break
            continue
        selected.append(message)
        if len(selected) >= max(1, max_batch_messages):
            break
    return list(reversed(selected))


def check_rate_limit(target_state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    limits = config.get("rate_limits", {}) or {}
    min_seconds = int(limits.get("min_seconds_between_replies", 0))
    max_per_10_minutes = int(limits.get("max_replies_per_10_minutes", 20))
    max_per_hour = int(limits.get("max_replies_per_hour", 100))
    now = datetime.now()
    timestamps = [
        parsed
        for parsed in (parse_datetime(item) for item in target_state.get("reply_timestamps", []))
        if parsed is not None
    ]
    blocks = []
    if timestamps and min_seconds > 0 and (now - max(timestamps)).total_seconds() < min_seconds:
        retry_after_at = max(timestamps) + timedelta(seconds=min_seconds)
        blocks.append(rate_limit_blocked("min_seconds_between_replies", now, retry_after_at))
    for reason, window_seconds, max_count in [
        ("max_replies_per_10_minutes", 10 * 60, max_per_10_minutes),
        ("max_replies_per_hour", 60 * 60, max_per_hour),
    ]:
        block = check_window_rate_limit(timestamps, now, reason, window_seconds, max_count)
        if block:
            blocks.append(block)
    if blocks:
        return max(blocks, key=lambda item: parse_datetime(str(item.get("retry_after_at") or "")) or now)
    return {"allowed": True, "reason": "ok"}


def check_window_rate_limit(
    timestamps: list[datetime],
    now: datetime,
    reason: str,
    window_seconds: int,
    max_count: int,
) -> dict[str, Any] | None:
    if max_count <= 0:
        return None
    window = timedelta(seconds=window_seconds)
    recent = sorted(item for item in timestamps if now - item <= window)
    if len(recent) < max_count:
        return None
    release_index = max(0, len(recent) - max_count)
    retry_after_at = recent[release_index] + window + timedelta(seconds=1)
    return rate_limit_blocked(reason, now, retry_after_at, window_seconds=window_seconds, max_count=max_count)


def rate_limit_blocked(
    reason: str,
    now: datetime,
    retry_after_at: datetime,
    window_seconds: int | None = None,
    max_count: int | None = None,
) -> dict[str, Any]:
    retry_after_seconds = max(1, int((retry_after_at - now).total_seconds()))
    payload = {
        "allowed": False,
        "reason": reason,
        "retry_after_at": retry_after_at.isoformat(timespec="seconds"),
        "retry_after_seconds": retry_after_seconds,
    }
    if window_seconds is not None:
        payload["window_seconds"] = window_seconds
    if max_count is not None:
        payload["max_count"] = max_count
    return payload


def get_rate_limit_backoff(target_state: dict[str, Any], message_ids: list[str]) -> dict[str, Any] | None:
    backoff = target_state.get("rate_limit_backoff")
    if not isinstance(backoff, dict):
        return None
    retry_after_at = parse_datetime(str(backoff.get("retry_after_at") or ""))
    if retry_after_at is None:
        return None
    if datetime.now() >= retry_after_at:
        target_state.pop("rate_limit_backoff", None)
        return None
    backoff["observed_message_ids"] = unique_list(
        [*[str(item) for item in backoff.get("observed_message_ids", [])], *message_ids]
    )
    return backoff


def record_rate_limit_backoff(
    target_state: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
) -> None:
    existing = target_state.get("rate_limit_backoff")
    attempts = int(existing.get("attempts", 0)) + 1 if isinstance(existing, dict) else 1
    target_state["rate_limit_backoff"] = {
        "message_ids": message_ids,
        "observed_message_ids": message_ids,
        "reason": rate_check.get("reason"),
        "retry_after_at": rate_check.get("retry_after_at"),
        "retry_after_seconds": rate_check.get("retry_after_seconds"),
        "attempts": attempts,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def clear_rate_limit_backoff(target_state: dict[str, Any], message_ids: list[str]) -> None:
    backoff = target_state.get("rate_limit_backoff")
    if not isinstance(backoff, dict):
        return
    target_state.pop("rate_limit_backoff", None)


def should_send_rate_limit_notice(
    target_state: dict[str, Any],
    config: dict[str, Any],
    rate_check: dict[str, Any],
) -> bool:
    settings = config.get("rate_limits", {}) or {}
    if not settings.get("notice_customer", True):
        return False
    retry_after_at = str(rate_check.get("retry_after_at") or "")
    if not retry_after_at:
        return False
    notices = target_state.get("rate_limit_notices", []) or []
    if not notices:
        return True
    latest = notices[-1]
    if latest.get("retry_after_at") == retry_after_at:
        return False
    min_interval = int(settings.get("notice_min_interval_seconds", 300))
    latest_at = parse_datetime(str(latest.get("sent_at") or ""))
    if latest_at and (datetime.now() - latest_at).total_seconds() < min_interval:
        return False
    return True


def build_rate_limit_notice_text(config: dict[str, Any], rate_check: dict[str, Any]) -> str:
    settings = config.get("rate_limits", {}) or {}
    retry_after_seconds = int(rate_check.get("retry_after_seconds") or 60)
    retry_after_minutes = max(1, int((retry_after_seconds + 59) / 60))
    reason_label = {
        "min_seconds_between_replies": "回复过快",
        "max_replies_per_10_minutes": "10分钟回复额度",
        "max_replies_per_hour": "1小时回复额度",
    }.get(str(rate_check.get("reason") or ""), "回复额度")
    template = str(
        settings.get("notice_reply")
        or "当前自动客服用量已超，已达到{reason_label}上限，请稍等约 {retry_after_minutes} 分钟，冷却后我会继续处理您的消息。"
    )
    return template.format(
        reason_label=reason_label,
        retry_after_minutes=retry_after_minutes,
        retry_after_at=rate_check.get("retry_after_at") or "",
    )


def record_rate_limit_notice(
    target_state: dict[str, Any],
    message_ids: list[str],
    rate_check: dict[str, Any],
    notice_text: str,
) -> None:
    notices = list(target_state.get("rate_limit_notices", []) or [])
    notices.append(
        {
            "message_ids": message_ids,
            "reason": rate_check.get("reason"),
            "retry_after_at": rate_check.get("retry_after_at"),
            "notice_text": notice_text,
            "sent_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    target_state["rate_limit_notices"] = notices[-MAX_STORED_IDS:]


def record_reply_timestamp(target_state: dict[str, Any]) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    timestamps = list(target_state.get("reply_timestamps", []))
    timestamps.append(now)
    target_state["reply_timestamps"] = timestamps[-MAX_STORED_IDS:]


def mark_processed(target_state: dict[str, Any], batch: list[dict[str, Any]], reply_text: str) -> None:
    processed = list(target_state.get("processed_message_ids", []))
    for message in batch:
        message_id = str(message.get("id") or "")
        if message_id and message_id not in processed:
            processed.append(message_id)
    target_state["processed_message_ids"] = processed[-MAX_STORED_IDS:]
    target_state.setdefault("sent_replies", []).append(
        {
            "message_ids": [item.get("id") for item in batch],
            "message_contents": [item.get("content") for item in batch],
            "reply_text": reply_text,
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


def mark_handoff(
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    reason: str,
    status: str = "open",
    operator_alert: dict[str, Any] | None = None,
) -> None:
    handoff = list(target_state.get("handoff_message_ids", []))
    for message in batch:
        message_id = str(message.get("id") or "")
        if message_id and message_id not in handoff:
            handoff.append(message_id)
    target_state["handoff_message_ids"] = handoff[-MAX_STORED_IDS:]
    event = {
        "message_ids": [item.get("id") for item in batch],
        "message_contents": [item.get("content") for item in batch],
        "reason": reason,
        "status": status,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if operator_alert:
        event["operator_alert"] = operator_alert
    target_state.setdefault("handoff_events", []).append(event)


def base_event(target: TargetConfig, action: str, extra: dict[str, Any]) -> dict[str, Any]:
    event = {
        "ok": action != "error",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "target": target.name,
        "action": action,
    }
    event.update(extra)
    return event


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "targets": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_audit(path: Path, event: dict[str, Any]) -> None:
    append_jsonl(path, event)


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False))
        handle.write("\n")


def parse_targets(config: dict[str, Any]) -> list[TargetConfig]:
    targets = []
    for item in config.get("targets", []) or []:
        if not item.get("enabled", False):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        allow_self = bool(item.get("allow_self_for_test", False))
        if allow_self and name != FILE_TRANSFER_ASSISTANT:
            raise ValueError("allow_self_for_test is only allowed for File Transfer Assistant")
        targets.append(
            TargetConfig(
                name=name,
                enabled=True,
                exact=bool(item.get("exact", True)),
                allow_self_for_test=allow_self,
                max_batch_messages=int(item.get("max_batch_messages", 3)),
            )
        )
    if not targets:
        raise ValueError("No enabled targets in config")
    return targets


def parse_runtime_targets(values: list[str], config_targets: list[TargetConfig]) -> list[TargetConfig]:
    config_by_name = {target.name: target for target in config_targets}
    targets = []
    for value in values:
        name = str(value or "").strip()
        if not name:
            continue
        if name in config_by_name:
            targets.append(config_by_name[name])
            continue
        targets.append(
            TargetConfig(
                name=name,
                enabled=True,
                exact=True,
                allow_self_for_test=False,
                max_batch_messages=3,
            )
        )
    if not targets:
        raise ValueError("No runtime targets were provided")
    return targets


def resolve_iterations(args: argparse.Namespace, config: dict[str, Any]) -> int:
    if args.once:
        return 1
    if args.iterations is not None:
        return max(1, args.iterations)
    return max(1, int(config.get("poll", {}).get("iterations", 1)))


def resolve_path(value: Any) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    return ROOT / path


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
