from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = PROJECT_ROOT / "apps" / "wechat_ai_customer_service"
TENANT_ID = "chejin"
TARGETS = ["新数据测试", "许聪"]
PROMPT_LABEL = "双会话长测"
ARTIFACT_ROOT = (
    PROJECT_ROOT
    / "runtime"
    / "apps"
    / "wechat_ai_customer_service"
    / "test_artifacts"
    / "two_visible_session_customer_service_live"
)
RPA_INPUT_METHODS = {"auto", "sendinput_unicode", "uia_chunks", "clipboard_chunks", "clipboard_once"}
PROMPT_SCENARIOS = [
    {
        "新数据测试": "你好，我想看看10万左右的电车或混动，给老婆开，别太大，有合适的吗？",
        "许聪": "晚上好，家用代步，预算6万以内，省油耐用的你直接推荐一台。",
    },
    {
        "新数据测试": "刚才那台如果纯电优先，你会更推荐哪一款？大概多少钱？",
        "许聪": "我不太懂车，你别让我选太多，直接帮我挑最稳的。",
    },
    {
        "新数据测试": "你是不是机器人在回我？怎么感觉每句都往车上绕。",
        "许聪": "贷款和置换能一起办吗？我有旧车想抵一部分。",
    },
    {
        "新数据测试": "先不聊车了，今天南京热不热？随便聊两句。",
        "许聪": "如果周末去看车，检测报告和车况能现场看吗？",
    },
    {
        "新数据测试": "自己开车撞墙了保险一般赔吗？这个我也想顺便问下。",
        "许聪": "好的谢谢，我先跟家里商量一下。",
    },
    {
        "新数据测试": "我又回来了，预算如果放到15万，想要空间大一点，有没有更合适的？",
        "许聪": "人呢？刚才那台你再简单说下优缺点。",
    },
]
BOUNDARY_PROMPT_SCENARIOS = [
    {
        "新数据测试": "你好，我想给老婆看一台时尚点、不太贵的二手车，别太大，你先直接帮我推荐方向。",
        "许聪": "晚上好，我家里代步用，预算5到8万，省油耐用就行，别让我选太多。",
    },
    {
        "新数据测试": "我说的是电车或者混动，库里如果有合适的你就直接说一两台，别一直问预算。",
        "许聪": "如果我主要跑市区，你从刚才方向里直接挑一台最稳的，理由简单说。",
    },
    {
        "新数据测试": "有没有奥迪A4或者A4L这种？如果有，大概什么价位？",
        "许聪": "我旧车想置换，再贷款一部分，这两个能不能一起走流程？",
    },
    {
        "新数据测试": "我打错了，塞纳那种MPV有吗？其实我说的是赛那或者类似大空间商务车。",
        "许聪": "征信一般能不能保证包过？如果能包过我今天就定。",
    },
    {
        "新数据测试": "你是不是机器人？怎么每句话都想把我往买车上带，我就随便聊聊。",
        "许聪": "自己开车撞墙了，保险一般赔吗？这个和买车没直接关系，我顺口问下。",
    },
    {
        "新数据测试": "先不聊车了，今天南京热不热？你就正常陪我聊两句。",
        "许聪": "如果周末去看车，检测报告、出险记录和车况能现场看吗？",
    },
    {
        "新数据测试": "你还在吗？刚才我问的问题别漏了。",
        "许聪": "好的，谢谢，我先跟家里商量一下。",
    },
    {
        "新数据测试": "我又想继续看车了，15万以内空间大、省心一点的，你重新帮我筛一下。",
        "许聪": "还有个问题，最低价能不能直接给到底？别让我来回砍。",
    },
]
SHORT_GREETING_PROMPT_SCENARIOS = [
    {
        "新数据测试": "你好",
        "许聪": "在吗",
    },
    {
        "新数据测试": "您好",
        "许聪": "还在吗",
    },
    {
        "新数据测试": "有空吗",
        "许聪": "你好",
    },
]
SHORT_BUSINESS_PROMPT_SCENARIOS = [
    {
        "新数据测试": "秦PLUS多少钱？",
        "许聪": "能贷款吗？",
    },
    {
        "新数据测试": "周末能看车吗？",
        "许聪": "车况怎么样？",
    },
]

SCENARIO_SETS = {
    "default": PROMPT_SCENARIOS,
    "boundary": BOUNDARY_PROMPT_SCENARIOS,
    "short_greeting": SHORT_GREETING_PROMPT_SCENARIOS,
    "short_business": SHORT_BUSINESS_PROMPT_SCENARIOS,
}

for candidate in (PROJECT_ROOT, APP_ROOT, APP_ROOT / "workflows", APP_ROOT / "adapters"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from apps.wechat_ai_customer_service.adapters.wechat_connector import WeChatConnector  # noqa: E402
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import (  # noqa: E402
    CustomerServiceRuntime,
    runtime_operator_guard_state_path,
    runtime_pid_path,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler import (  # noqa: E402
    CustomerServiceSchedulerRuntime,
    ManagedListenerSchedulerBridge,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_scheduler_state import (  # noqa: E402
    SchedulerStateStore,
    enqueue_pending_session,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_settings import (  # noqa: E402
    CustomerServiceSettings,
)
from apps.wechat_ai_customer_service.admin_backend.services.customer_service_session_ledger import (  # noqa: E402
    SessionLedgerStore,
    stable_session_key,
)
from apps.wechat_ai_customer_service.knowledge_paths import tenant_runtime_root  # noqa: E402
from apps.wechat_ai_customer_service.scripts.run_customer_service_listener import (  # noqa: E402
    clear_file,
    empty_operator_control_state,
    launch_operator_guard,
    normalize_operator_guard_settings,
    read_operator_guard_pid,
    runtime_operator_control_path,
    runtime_operator_guard_pid_path,
    sync_operator_mode,
    terminate_pid,
    verify_operator_guard_bootstrap,
    write_operator_control_state,
)


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _seconds_between(start: Any, finish: Any) -> float | None:
    started_at = _parse_time(start)
    finished_at = _parse_time(finish)
    if started_at is None or finished_at is None:
        return None
    if started_at.tzinfo is None and finished_at.tzinfo is not None:
        finished_at = finished_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and finished_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    seconds = (finished_at - started_at).total_seconds()
    if seconds < 0:
        return None
    return round(seconds, 4)


def compact_latency_breakdown(trace: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    pairs = {
        "signal_to_capture_start_seconds": ("session_signal_detected_at", "capture_started_at"),
        "capture_seconds": ("capture_started_at", "capture_finished_at"),
        "capture_to_brain_start_seconds": ("capture_finished_at", "brain_started_at"),
        "brain_seconds": ("brain_started_at", "brain_finished_at"),
        "final_polish_seconds": ("final_polish_started_at", "final_polish_finished_at"),
        "ready_queue_wait_seconds": ("send_queue_entered_at", "send_started_at"),
        "send_seconds": ("send_started_at", "send_finished_at"),
        "send_rpa_seconds": ("send_rpa_started_at", "send_rpa_finished_at"),
        "end_to_end_seconds": ("session_signal_detected_at", "send_finished_at"),
    }
    compact: dict[str, Any] = {}
    for name, (start_key, finish_key) in pairs.items():
        seconds = _seconds_between(trace.get(start_key), trace.get(finish_key))
        if seconds is not None:
            compact[name] = seconds
    return compact


def safe_name(value: str) -> str:
    text = str(value or "").strip() or "target"
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)[:80] or "target"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def scenario_prompts(scenario_set: str) -> list[dict[str, str]]:
    return SCENARIO_SETS.get(str(scenario_set or "default"), PROMPT_SCENARIOS)


def round_prompts(token: str, round_index: int, *, scenario_set: str = "default") -> dict[str, str]:
    scenarios = scenario_prompts(scenario_set)
    scenario = scenarios[(max(1, int(round_index)) - 1) % len(scenarios)]
    return {target: str(scenario[target]) for target in TARGETS}


def backup_files(paths: list[Path]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for path in paths:
        snapshots.append({"path": str(path), "exists": path.exists(), "bytes": path.read_bytes() if path.exists() else None})
    return snapshots


def restore_files(snapshots: list[dict[str, Any]]) -> None:
    for item in reversed(snapshots):
        path = Path(str(item.get("path") or ""))
        if item.get("exists"):
            data = item.get("bytes")
            if isinstance(data, bytes):
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_name(path.name + ".restore_tmp")
                temp.write_bytes(data)
                os.replace(temp, path)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def compact_status(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": payload.get("ok"),
        "online": payload.get("online"),
        "adapter": payload.get("adapter"),
        "scheme": payload.get("scheme"),
        "state": payload.get("state"),
        "reason": payload.get("reason"),
        "blocking_reason": payload.get("blocking_reason"),
        "ocr_count": payload.get("ocr_count"),
        "geometry": payload.get("geometry"),
    }


def hard_status_reason(status: dict[str, Any]) -> str:
    state = str(status.get("state") or "")
    reason = str(status.get("reason") or status.get("blocking_reason") or "")
    if "blank" in state or "blank" in reason:
        return "blank_render_detected"
    if not status.get("online"):
        return reason or state or "wechat_not_online"
    return ""


def compact_send(payload: dict[str, Any]) -> dict[str, Any]:
    send = payload.get("send") if isinstance(payload.get("send"), dict) else {}
    send_result = send.get("send_result") if isinstance(send.get("send_result"), dict) else {}
    click = send_result.get("click") if isinstance(send_result.get("click"), dict) else {}
    guard = send.get("guard") if isinstance(send.get("guard"), dict) else {}
    guard_click = guard.get("click") if isinstance(guard.get("click"), dict) else {}
    paste = click.get("paste") if isinstance(click.get("paste"), dict) else {}
    if not paste and isinstance(guard_click.get("paste"), dict):
        paste = guard_click.get("paste") or {}
    input_result = paste.get("input_result") if isinstance(paste.get("input_result"), dict) else {}
    pre_guard = send_result.get("pre_send_guard") if isinstance(send_result.get("pre_send_guard"), dict) else {}
    if not pre_guard and guard:
        pre_guard = guard
    post_guard = click.get("post_send_guard") if isinstance(click.get("post_send_guard"), dict) else {}
    if not post_guard and isinstance(send_result.get("post_send_guard"), dict):
        post_guard = send_result.get("post_send_guard") or {}
    window_probe = send.get("window_probe") if isinstance(send.get("window_probe"), dict) else {}
    selected_window = window_probe.get("selected_main_window") if isinstance(window_probe.get("selected_main_window"), dict) else {}
    focused_window = window_probe.get("focused_window") if isinstance(window_probe.get("focused_window"), dict) else {}
    wxauto4_reserve = send.get("wxauto4_reserve_status") if isinstance(send.get("wxauto4_reserve_status"), dict) else {}
    reason = (
        send.get("reason")
        or send_result.get("reason")
        or guard_click.get("reason")
        or paste.get("reason")
        or payload.get("reason")
    )
    return {
        "ok": bool(payload.get("ok")),
        "verified": bool(payload.get("verified")),
        "verification_mode": payload.get("verification_mode"),
        "adapter": send.get("adapter"),
        "state": send.get("state"),
        "target": send.get("target"),
        "exact": send.get("exact"),
        "reason": reason,
        "method": send_result.get("method"),
        "humanized_method": send_result.get("humanized_method"),
        "input_mode": paste.get("input_mode"),
        "confirmed_by": paste.get("confirmed_by"),
        "probe_token": paste.get("probe_token"),
        "probe_tokens": paste.get("probe_tokens"),
        "input_region": paste.get("input_region"),
        "input_visual_confirm": paste.get("input_visual_confirm"),
        "input_clear_reason": (paste.get("input_clear") or {}).get("reason") if isinstance(paste.get("input_clear"), dict) else None,
        "chunks": input_result.get("chunks"),
        "typo_count": input_result.get("typo_count"),
        "window_probe": {
            "visible_main_count": window_probe.get("visible_main_count"),
            "main_count": window_probe.get("main_count"),
            "selected_title": selected_window.get("title"),
            "selected_geometry": selected_window.get("geometry_hint"),
            "focused_title": focused_window.get("title"),
            "focused_geometry": focused_window.get("geometry_hint"),
            "screenshot_path": window_probe.get("screenshot_path"),
        },
        "pre_send_guard": {
            "ok": pre_guard.get("ok"),
            "reason": pre_guard.get("reason"),
            "requested_target": pre_guard.get("requested_target"),
            "confirmed_target": pre_guard.get("confirmed_target"),
            "confirmation_confidence": pre_guard.get("confirmation_confidence"),
            "blind_send": pre_guard.get("blind_send"),
        },
        "post_send_guard": {
            "ok": post_guard.get("ok"),
            "reason": post_guard.get("reason"),
            "confirmation_confidence": post_guard.get("confirmation_confidence"),
        },
        "wxauto4_reserve_status": {
            "ok": wxauto4_reserve.get("ok"),
            "state": wxauto4_reserve.get("state"),
            "reason": wxauto4_reserve.get("reason"),
            "error": wxauto4_reserve.get("error"),
        } if wxauto4_reserve else {},
        "rpa_lock": send.get("rpa_lock") if isinstance(send.get("rpa_lock"), dict) else {},
        "timing": payload.get("timing") if isinstance(payload.get("timing"), dict) else {},
        "send_timing": send.get("timing") if isinstance(send.get("timing"), dict) else {},
        "error": payload.get("error") or send.get("error") or send_result.get("error"),
    }


def prompt_failure_summary(target: str, send: dict[str, Any]) -> dict[str, Any]:
    compact = compact_send(send)
    return {
        "category": "prompt_send_rpa",
        "target": target,
        "state": compact.get("state"),
        "reason": compact.get("reason"),
        "error": compact.get("error"),
        "input_mode": compact.get("input_mode"),
        "confirmed_by": compact.get("confirmed_by"),
        "probe_token": compact.get("probe_token"),
        "probe_tokens": compact.get("probe_tokens"),
        "input_region": compact.get("input_region"),
        "input_visual_confirm": compact.get("input_visual_confirm"),
        "input_clear_reason": compact.get("input_clear_reason"),
        "window_probe": compact.get("window_probe"),
        "pre_send_guard": compact.get("pre_send_guard"),
        "post_send_guard": compact.get("post_send_guard"),
    }


def sent_target_coverage(sent: list[dict[str, Any]], expected_targets: list[str]) -> dict[str, Any]:
    successful_targets = [str(item.get("target") or "") for item in sent if (item.get("result") or {}).get("ok")]
    successful_set = {target for target in successful_targets if target}
    expected_set = {str(target) for target in expected_targets}
    missing = sorted(expected_set - successful_set)
    unexpected = sorted(successful_set - expected_set)
    return {
        "ok": not missing and not unexpected,
        "counts": {target: successful_targets.count(target) for target in sorted(successful_set)},
        "missing_targets": missing,
        "unexpected_targets": unexpected,
    }


def sent_session_key_coverage(sent: list[dict[str, Any]], expected_key_by_target: dict[str, str]) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for item in sent:
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if not result.get("ok"):
            continue
        target = str(item.get("target") or "")
        expected_key = str(expected_key_by_target.get(target) or "")
        actual_key = str(item.get("session_key") or "")
        if expected_key:
            checked += 1
            if actual_key != expected_key:
                mismatches.append({"target": target, "expected_session_key": expected_key, "actual_session_key": actual_key})
    return {"ok": not mismatches, "checked": checked, "mismatches": mismatches}


def tick_failure_events(replies: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    no_visible_events: list[dict[str, Any]] = []
    rpa_send_events: list[dict[str, Any]] = []
    hard_send_reasons = {
        "send_input_not_ready",
        "send_not_verified",
        "target_not_confirmed",
        "target_title_not_confirmed",
        "ocr_capture_unavailable",
        "login_window_detected",
        "blank_render_detected",
        "wechat_logout_detected_by_passive_probe",
        "wechat_blank_render_detected_by_passive_probe",
    }
    ticks = replies.get("ticks") if isinstance(replies.get("ticks"), list) else []
    for tick in ticks:
        if not isinstance(tick, dict):
            continue
        for event in tick.get("events") or []:
            if not isinstance(event, dict):
                continue
            fields = [
                event.get("event"),
                event.get("action"),
                event.get("reason"),
                event.get("error"),
            ]
            send_result = event.get("send_result") if isinstance(event.get("send_result"), dict) else {}
            fields.extend(
                [
                    send_result.get("reason"),
                    send_result.get("state"),
                    send_result.get("nested_reason"),
                ]
            )
            joined = " ".join(str(value or "") for value in fields)
            if "customer_service_brain_no_visible_reply" in joined:
                no_visible_events.append(
                    {
                        "event": event.get("event"),
                        "action": event.get("action"),
                        "reason": event.get("reason") or send_result.get("reason") or send_result.get("nested_reason"),
                        "error": event.get("error"),
                        "target": event.get("target"),
                        "session_key": event.get("session_key"),
                    }
                )
            send_reasons = {
                str(event.get("reason") or ""),
                str(send_result.get("reason") or ""),
                str(send_result.get("state") or ""),
                str(send_result.get("nested_reason") or ""),
            }
            hard_reason = next((item for item in send_reasons if item in hard_send_reasons), "")
            if hard_reason:
                rpa_send_events.append(
                    {
                        "event": event.get("event"),
                        "action": event.get("action"),
                        "reason": hard_reason,
                        "target": event.get("target"),
                        "session_key": event.get("session_key"),
                        "send_result": send_result,
                    }
                )
    return no_visible_events, rpa_send_events


def summarize_reply_failure(replies: dict[str, Any], sent: list[dict[str, Any]], expected_targets: list[str]) -> dict[str, Any]:
    coverage = sent_target_coverage(sent, expected_targets)
    no_visible_events, rpa_send_events = tick_failure_events(replies)
    reason = str(replies.get("reason") or "reply_phase_failed")
    sent_count = sum(1 for item in sent if (item.get("result") or {}).get("ok"))
    if no_visible_events and sent_count > 0:
        category = "partial_brain_no_visible"
    elif no_visible_events or reason == "reply_incomplete_idle_no_visible_reply":
        category = "brain_no_visible"
    elif rpa_send_events:
        category = "reply_send_rpa"
    elif reason == "reply_timeout":
        category = "reply_timeout"
    else:
        category = reason
    ticks = replies.get("ticks") if isinstance(replies.get("ticks"), list) else []
    last_tick = ticks[-1] if ticks and isinstance(ticks[-1], dict) else {}
    return {
        "category": category,
        "reason": reason,
        "sent_count": sent_count,
        "sent_target_counts": coverage.get("counts"),
        "missing_reply_targets": coverage.get("missing_targets"),
        "unexpected_reply_targets": coverage.get("unexpected_targets"),
        "brain_no_visible_events": no_visible_events[-6:],
        "rpa_send_events": rpa_send_events[-6:],
        "last_summary": last_tick.get("summary") if isinstance(last_tick.get("summary"), dict) else {},
        "post_status": replies.get("post_status") if isinstance(replies.get("post_status"), dict) else {},
    }


def apply_reply_failure_result(
    result: dict[str, Any],
    round_result: dict[str, Any],
    replies: dict[str, Any],
    sent: list[dict[str, Any]],
) -> None:
    failure = summarize_reply_failure(replies, sent, TARGETS)
    result["error"] = str(failure.get("reason") or "reply_phase_failed")
    result["failure_category"] = failure.get("category")
    result["failure"] = failure
    round_result["failure"] = failure
    round_result["sent_target_counts"] = failure.get("sent_target_counts")
    round_result["missing_reply_targets"] = failure.get("missing_reply_targets")
    round_result["unexpected_reply_targets"] = failure.get("unexpected_reply_targets")


def build_config(run_dir: Path) -> Path:
    base = json.loads((APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json").read_text(encoding="utf-8"))
    base["state_path"] = str(run_dir / "workflow_state.json")
    base["audit_log_path"] = str(run_dir / "audit.jsonl")
    base["targets"] = [{"name": target, "enabled": True, "exact": True, "allow_self_for_test": False, "max_batch_messages": 4} for target in TARGETS]
    base.setdefault("reply", {})["prefix"] = ""
    base.setdefault("raw_messages", {})["enabled"] = False
    base.setdefault("data_capture", {})["enabled"] = False
    base.setdefault("operator_alert", {})["enabled"] = False
    base.setdefault("multi_target", {})["enabled"] = True
    base["multi_target"].update(
        {
            "max_targets_per_iteration": 2,
            "scan_all_whitelist_each_iteration": False,
            "capture_one_target_per_round": False,
            "short_preview_can_raise_unread": True,
            "preview_change_can_raise_unread": False,
            "initial_preview_can_raise_unread": False,
        }
    )
    base.setdefault("concurrency_scheduler", {})["enabled"] = True
    base["concurrency_scheduler"].update(
        {
            "capture_max_sessions_per_round": 2,
            "llm_max_concurrency": 2,
            "send_max_replies_per_round": 1,
            "same_session_single_inflight": True,
            "stale_reply_policy": "discard_and_requeue",
        }
    )
    base.setdefault("live_safety_guard", {})["enabled"] = True
    base["live_safety_guard"].update(
        {
            "allowed_targets": list(TARGETS),
            "targets": list(TARGETS),
            "required_allowed_targets": list(TARGETS),
            "require_exact_targets": True,
            "disable_respond_all_unread_sessions": True,
            "reject_group_targets": False,
            "sync_allowed_targets_from_settings": False,
            "require_recent_bootstrap": False,
        }
    )
    base.setdefault("history_backfill", {})["enabled"] = True
    base["history_backfill"].update(
        {
            "mode": "anchor_until_found",
            "max_scroll_steps": 2,
            "max_duration_seconds": 8,
            "trigger_when_anchor_missing": True,
            "overflow_batch_on_anchor_missing": True,
            "restore_to_latest": True,
        }
    )
    base.setdefault("rpa_humanized_send", {})
    input_method = str(os.getenv("WECHAT_LIVE_TEST_RPA_INPUT_METHOD") or "clipboard_chunks").strip().lower()
    if input_method not in RPA_INPUT_METHODS:
        input_method = "clipboard_chunks"
    base["rpa_humanized_send"].update(
        {
            "enabled": True,
            "input_method": input_method,
            "send_trigger_mode": "enter_only",
            "send_input_confirm_attempts": 1,
            "typing_typo_probability": 0.0,
            "typing_typo_max": 0,
            "send_pre_delay_min_ms": 500,
            "send_pre_delay_max_ms": 1300,
            "send_post_input_delay_min_ms": 450,
            "send_post_input_delay_max_ms": 1200,
            "send_trigger_delay_min_ms": 720,
            "send_trigger_delay_max_ms": 2100,
            "send_after_trigger_delay_min_ms": 420,
            "send_after_trigger_delay_max_ms": 1250,
            "input_fast_visual_confirm_enabled": True,
        }
    )
    base.setdefault("rpa_operator_guard", {})
    base["rpa_operator_guard"].update(
        {
            "enabled": True,
            "block_manual_input": True,
            "floating_indicator_enabled": True,
            "control_hotkey": "f8",
            "pause_poll_interval_ms": 450,
        }
    )
    base.setdefault("customer_service_brain", {})
    base["customer_service_brain"].update(
        {
            "timeout_seconds": 35,
            "max_tokens": 900,
            "history_char_budget": 1200,
            "current_batch_char_budget": 420,
        }
    )
    path = run_dir / "listener_config.json"
    write_json(path, base)
    return path


def prepare_round_state(
    bridge: ManagedListenerSchedulerBridge,
    run_dir: Path,
    round_index: int,
    *,
    continuous_ledger: bool = False,
) -> None:
    state_name = "scheduler_state_continuous.json" if continuous_ledger else f"scheduler_state_round_{round_index}.json"
    bridge.store = SchedulerStateStore(tenant_id=TENANT_ID, path=run_dir / state_name)
    bridge.ledger = SessionLedgerStore(tenant_id=TENANT_ID, root=bridge.store.ledger_root)
    if bridge.runtime is not None:
        bridge.runtime.shutdown()
    bridge.runtime = CustomerServiceSchedulerRuntime(
        store=bridge.store,
        config=bridge.scheduler_config,
        capture_fn=bridge._capture_session,
        plan_reply_fn=bridge._plan_reply,
        polish_reply_fn=bridge._polish_reply,
        freshness_fn=bridge._freshness_check,
        send_fn=bridge._send_reply,
        capture_done_fn=bridge._capture_done,
    )


def target_conversation_type(
    target: str,
    conversation_type_by_target: dict[str, str] | None = None,
) -> str:
    detected = str((conversation_type_by_target or {}).get(target) or "").strip().lower()
    if detected and detected != "unknown":
        return detected
    return "group" if target == "新数据测试" else "private"


def configure_settings(conversation_type_by_target: dict[str, str] | None = None) -> None:
    CustomerServiceSettings(tenant_id=TENANT_ID).save(
        {
            "enabled": True,
            "reply_mode": "full_auto",
            "record_messages": False,
            "auto_learn": False,
            "use_llm": True,
            "rag_enabled": True,
            "data_capture_enabled": False,
            "handoff_enabled": True,
            "operator_alert_enabled": False,
            "identity_guard_enabled": True,
            "style_adapter_enabled": True,
            "final_visible_llm_polish_enabled": True,
            "customer_service_brain_mode": "brain_first",
            "respond_all_unread_sessions": False,
            "session_targets_managed": True,
            "session_targets": [
                {
                    "name": target,
                    "display_name": target,
                    "enabled": True,
                    "exact": True,
                    "archived": False,
                    "conversation_type": target_conversation_type(
                        target,
                        conversation_type_by_target,
                    ),
                    "source": "live_acceptance",
                }
                for target in TARGETS
            ],
        }
    )


def launch_guard(config: dict[str, Any]) -> dict[str, Any]:
    settings = normalize_operator_guard_settings(config.get("rpa_operator_guard") if isinstance(config.get("rpa_operator_guard"), dict) else {})
    settings.update({"enabled": True, "block_manual_input": True, "floating_indicator_enabled": True, "control_hotkey": "f8"})
    control_path = runtime_operator_control_path(TENANT_ID)
    pid_path = runtime_operator_guard_pid_path(TENANT_ID)
    state_path = runtime_operator_guard_state_path(TENANT_ID)
    clear_file(pid_path)
    clear_file(state_path)
    write_operator_control_state(control_path, empty_operator_control_state(TENANT_ID, mode="running"))
    launch = launch_operator_guard(
        tenant_id=TENANT_ID,
        settings=settings,
        control_path=control_path,
        status_path=tenant_runtime_root(TENANT_ID) / "customer_service" / "runtime_status.json",
        state_path=state_path,
        pid_path=pid_path,
        parent_pid=os.getpid(),
    )
    verify = {}
    if launch.get("ok"):
        verify = verify_operator_guard_bootstrap(int(launch.get("pid") or 0), state_path, expected_parent_pid=os.getpid())
    return {"ok": bool(launch.get("ok") and verify.get("ok")), "launch": launch, "verify": verify, "state": read_json(state_path)}


def stop_guard(reason: str) -> None:
    try:
        sync_operator_mode(runtime_operator_control_path(TENANT_ID), tenant_id=TENANT_ID, mode="stopped", message=reason)
    except Exception:
        pass
    pid = read_operator_guard_pid(runtime_operator_guard_pid_path(TENANT_ID))
    if pid > 0:
        terminate_pid(pid)
    clear_file(runtime_operator_guard_pid_path(TENANT_ID))
    clear_file(runtime_operator_guard_state_path(TENANT_ID))


class SyntheticInboundConnector:
    def __init__(
        self,
        real: WeChatConnector,
        synthetic_by_target: dict[str, dict[str, Any]],
        *,
        dry_reply_send: bool = False,
        synthetic_input_only: bool = False,
    ) -> None:
        self.real = real
        self.synthetic_by_target = synthetic_by_target
        self.dry_reply_send = bool(dry_reply_send)
        self.synthetic_input_only = bool(synthetic_input_only)
        self.sent_targets: set[str] = set()
        self.sent: list[dict[str, Any]] = []

    def synthetic_only_message_payload(
        self,
        target: str,
        *,
        exact: bool,
        reason: str,
        real_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        synthetic = None if str(target) in self.sent_targets else self.synthetic_by_target.get(str(target))
        if not synthetic or not self.dry_reply_send:
            return None
        return {
            "ok": True,
            "target": target,
            "exact": exact,
            "messages": [dict(synthetic)],
            "synthetic_inbound_test": {
                "enabled": True,
                "target": target,
                "message_id": synthetic.get("id"),
                "mode": "synthetic_input_only" if self.synthetic_input_only else "synthetic_only_after_real_read_failure",
                "reason": reason,
                "real_payload": {
                    "ok": (real_payload or {}).get("ok"),
                    "state": (real_payload or {}).get("state"),
                    "reason": (real_payload or {}).get("reason"),
                    "error": (real_payload or {}).get("error"),
                },
            },
        }

    def require_online(self) -> dict[str, Any]:
        return self.real.require_online()

    def status(self, *, interactive: bool = False) -> dict[str, Any]:
        return self.real.status(interactive=interactive)

    def capabilities(self, *, interactive: bool = False) -> dict[str, Any]:
        return self.real.capabilities(interactive=interactive)

    def list_sessions(self, *, fresh: bool = False) -> dict[str, Any]:
        return self.real.list_sessions(fresh=fresh)

    def get_messages(self, target: str, exact: bool = True, history_load_times: int = 0, **kwargs: Any) -> dict[str, Any]:
        if self.synthetic_input_only:
            synthetic_payload = self.synthetic_only_message_payload(
                target,
                exact=exact,
                reason="synthetic_input_only",
                real_payload=None,
            )
            if synthetic_payload is not None:
                return synthetic_payload
        payload = self.real.get_messages(target, exact=exact, history_load_times=history_load_times, **kwargs)
        synthetic = None if str(target) in self.sent_targets else self.synthetic_by_target.get(str(target))
        if not payload.get("ok"):
            synthetic_payload = self.synthetic_only_message_payload(
                target,
                exact=exact,
                reason="real_get_messages_failed",
                real_payload=payload,
            )
            if synthetic_payload is not None:
                return synthetic_payload
        if payload.get("ok") and synthetic:
            messages = [item for item in (payload.get("messages") or []) if isinstance(item, dict)]
            if not any(str(item.get("id") or "") == str(synthetic.get("id") or "") for item in messages):
                messages.append(dict(synthetic))
            payload = dict(payload)
            payload["messages"] = messages
            payload["synthetic_inbound_test"] = {"enabled": True, "target": target, "message_id": synthetic.get("id")}
        return payload

    def send_text_and_verify(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        if self.dry_reply_send:
            result = self._dry_send_result(target, text, exact=exact, **kwargs)
        else:
            result = self.real.send_text_and_verify(target, text, exact=exact, **kwargs)
        self.sent.append({"target": target, "session_key": kwargs.get("session_key", ""), "text": text, "result": compact_send(result)})
        if result.get("ok") and result.get("verified"):
            self.sent_targets.add(str(target))
        return result

    def send_text(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        if self.dry_reply_send:
            result = self._dry_send_result(target, text, exact=exact, **kwargs)
        else:
            result = self.real.send_text(target, text, exact=exact, **kwargs)
        compact_result = compact_send(
            {
                "ok": bool(result.get("ok")) if isinstance(result, dict) else False,
                "verified": bool(result.get("ok")) if isinstance(result, dict) else False,
                "send": result if isinstance(result, dict) else {},
                "error": result.get("error") if isinstance(result, dict) else "send_text_invalid_result",
            }
        )
        if compact_result.get("verification_mode") is None:
            compact_result["verification_mode"] = "send_only_intermediate"
        self.sent.append(
            {
                "target": target,
                "session_key": kwargs.get("session_key", ""),
                "text": text,
                "result": compact_result,
            }
        )
        if isinstance(result, dict) and result.get("ok"):
            self.sent_targets.add(str(target))
        return result

    def _dry_send_result(self, target: str, text: str, exact: bool = True, **kwargs: Any) -> dict[str, Any]:
        session_key = str(kwargs.get("session_key") or "")
        started_at = now_text()
        return {
            "ok": True,
            "verified": True,
            "target": target,
            "exact": exact,
            "text": text,
            "verification_mode": "dry_reply_send",
            "send": {
                "ok": True,
                "adapter": "dry_rpa",
                "state": "dry_reply_send",
                "target": target,
                "exact": exact,
                "session_key": session_key,
                "send_result": {
                    "ok": True,
                    "verified": True,
                    "state": "dry_reply_send",
                    "method": "dry_reply_send",
                    "pre_send_guard": {
                        "ok": True,
                        "reason": "dry_reply_send",
                        "requested_target": target,
                        "confirmed_target": target,
                        "session_key": session_key,
                    },
                    "click": {
                        "post_send_guard": {
                            "ok": True,
                            "reason": "dry_reply_send",
                            "confirmation_confidence": 1.0,
                        }
                    },
                },
            },
            "timing": {
                "send_started_at": started_at,
                "send_finished_at": now_text(),
                "send_duration_seconds": 0.0,
                "send_verify_started_at": started_at,
                "send_verify_finished_at": now_text(),
                "send_verify_duration_seconds": 0.0,
                "verification_attempts": 0,
                "adapter_stage": "dry_reply_send",
            },
        }

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


def build_bridge(config_path: Path, connector: Any, run_dir: Path, *, allow_send: bool = True) -> ManagedListenerSchedulerBridge:
    bridge = ManagedListenerSchedulerBridge(tenant_id=TENANT_ID, config_path=config_path, allow_send=allow_send, write_data=False)
    bridge.connector = connector
    bridge.store = SchedulerStateStore(tenant_id=TENANT_ID, path=run_dir / "scheduler_state.json")
    bridge.ledger = SessionLedgerStore(tenant_id=TENANT_ID, root=bridge.store.ledger_root)
    if bridge.runtime is not None:
        bridge.runtime.shutdown()
    bridge.runtime = CustomerServiceSchedulerRuntime(
        store=bridge.store,
        config=bridge.scheduler_config,
        capture_fn=bridge._capture_session,
        plan_reply_fn=bridge._plan_reply,
        polish_reply_fn=bridge._polish_reply,
        freshness_fn=bridge._freshness_check,
        send_fn=bridge._send_reply,
        capture_done_fn=bridge._capture_done,
    )
    return bridge


def seed_synthetic_pending_sessions(
    bridge: ManagedListenerSchedulerBridge,
    progress_path: Path,
    session_key_by_target: dict[str, str] | None = None,
    conversation_type_by_target: dict[str, str] | None = None,
) -> None:
    state = bridge.store.load()
    key_map = session_key_by_target or {}
    type_map = conversation_type_by_target or {}
    for target in TARGETS:
        conversation_type = target_conversation_type(target, type_map)
        enqueue_pending_session(
            state,
            target,
            exact=True,
            conversation_type=conversation_type,
            session_key=str(
                key_map.get(target)
                or stable_session_key(target, conversation_type=conversation_type)
            ),
            reason="two_visible_session_synthetic_inbound",
            now=now_text(),
        )
    bridge.store.save(state)
    append_jsonl(
        progress_path,
        {
            "event": "seed_synthetic_pending_sessions",
            "targets": list(TARGETS),
            "session_key_by_target": dict(key_map),
            "conversation_type_by_target": dict(type_map),
            "summary": {
                "sessions": len((state.get("sessions") or {})),
                "pending_sessions": sum(1 for item in (state.get("sessions") or {}).values() if isinstance(item, dict) and item.get("pending_capture")),
            },
            "created_at": now_text(),
        },
    )


def compact_tick(tick: dict[str, Any]) -> dict[str, Any]:
    def _compact_event_send_result(item: dict[str, Any]) -> dict[str, Any]:
        payload = item.get("send_result") if isinstance(item.get("send_result"), dict) else {}
        nested = payload.get("send_result") if isinstance(payload.get("send_result"), dict) else {}
        return {
            "ok": payload.get("ok"),
            "verified": payload.get("verified"),
            "reason": payload.get("reason") or payload.get("error"),
            "state": payload.get("state") or nested.get("state"),
            "nested_ok": nested.get("ok"),
            "nested_verified": nested.get("verified"),
            "nested_reason": nested.get("reason") or nested.get("error"),
            "verification_mode": payload.get("verification_mode") or nested.get("verification_mode"),
        }

    return {
        "ok": tick.get("ok"),
        "summary": tick.get("summary") if isinstance(tick.get("summary"), dict) else {},
        "duration_seconds": tick.get("duration_seconds"),
        "phase_durations": tick.get("phase_durations") if isinstance(tick.get("phase_durations"), dict) else {},
        "events": [
            {
                "event": item.get("event"),
                "action": item.get("action"),
                "reason": item.get("reason"),
                "error": item.get("error"),
                "target": item.get("target_name") or item.get("target"),
                "reply_id": item.get("reply_id"),
                "session_key": item.get("session_key"),
                "send_result": _compact_event_send_result(item),
                "send_observability": item.get("send_observability") if isinstance(item.get("send_observability"), dict) else {},
                "latency_trace": item.get("latency_trace") if isinstance(item.get("latency_trace"), dict) else {},
                "latency_breakdown": (
                    item.get("latency_breakdown")
                    if isinstance(item.get("latency_breakdown"), dict)
                    else compact_latency_breakdown(item.get("latency_trace") if isinstance(item.get("latency_trace"), dict) else {})
                ),
            }
            for item in (tick.get("events") or [])[-12:]
            if isinstance(item, dict)
        ],
    }


def tick_sent_count(tick: dict[str, Any]) -> int:
    count = 0
    for item in tick.get("events") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("action") or "") == "sent" or str(item.get("event") or "") in {"reply_sent", "send_completed", "scheduler_send_completed"}:
            count += 1
    return count


def reply_ready_count(replies: dict[str, Any]) -> int:
    ticks = replies.get("ticks") if isinstance(replies.get("ticks"), list) else []
    ready = 0
    for tick in ticks:
        if not isinstance(tick, dict):
            continue
        summary = tick.get("summary") if isinstance(tick.get("summary"), dict) else {}
        try:
            ready = max(ready, int(summary.get("reply_ready") or 0))
        except (TypeError, ValueError):
            continue
    return ready


def hard_tick_reason(tick: dict[str, Any]) -> str:
    hard = {
        "send_input_not_ready",
        "send_not_verified",
        "target_not_confirmed",
        "target_title_not_confirmed",
        "ocr_capture_unavailable",
        "login_window_detected",
        "blank_render_detected",
        "wechat_logout_detected_by_passive_probe",
        "wechat_blank_render_detected_by_passive_probe",
    }
    for item in tick.get("events") or []:
        if not isinstance(item, dict):
            continue
        send_result = item.get("send_result") if isinstance(item.get("send_result"), dict) else {}
        nested = send_result.get("send_result") if isinstance(send_result.get("send_result"), dict) else {}
        candidates = {
            str(item.get("reason") or ""),
            str(send_result.get("reason") or ""),
            str(send_result.get("state") or ""),
            str(nested.get("reason") or ""),
            str(nested.get("state") or ""),
        }
        reason = next((value for value in candidates if value in hard), "")
        if reason:
            return reason
    return ""


def wait_for_replies(
    bridge: ManagedListenerSchedulerBridge,
    connector: WeChatConnector,
    progress_path: Path,
    *,
    expected: int,
    allow_send: bool = True,
    timeout_seconds: float = 240.0,
    tick_interval_seconds: float = 4.0,
    probe_status_each_tick: bool = True,
) -> dict[str, Any]:
    deadline = time.time() + max(10.0, float(timeout_seconds or 240.0))
    sent = 0
    ticks: list[dict[str, Any]] = []
    last_status: dict[str, Any] = {}
    deferred_status_probe = False

    def current_status() -> dict[str, Any]:
        if last_status:
            return last_status
        return connector.status(interactive=False)

    while time.time() < deadline:
        tick = bridge.tick(allow_send=allow_send)
        compact = compact_tick(tick)
        ticks.append(compact)
        append_jsonl(progress_path, {"event": "scheduler_tick", **compact, "created_at": now_text()})
        sent += tick_sent_count(tick)
        summary = tick.get("summary") if isinstance(tick.get("summary"), dict) else {}
        sending = int((summary.get("reply_sending") or 0) if isinstance(summary, dict) else 0)
        if probe_status_each_tick and sending <= 0:
            last_status = connector.status(interactive=False)
            deferred_status_probe = False
        elif probe_status_each_tick and sending > 0:
            deferred_status_probe = True
            append_jsonl(
                progress_path,
                {
                    "event": "status_probe_deferred_during_reply_sending",
                    "reply_sending": sending,
                    "created_at": now_text(),
                },
            )
        reason = (hard_status_reason(last_status) if probe_status_each_tick and last_status else "") or hard_tick_reason(tick)
        if reason:
            post_status = current_status() if probe_status_each_tick else connector.status(interactive=False)
            return {"ok": False, "reason": reason, "ticks": ticks, "post_status": compact_status(post_status)}
        ready = int((summary.get("reply_ready") or 0) if isinstance(summary, dict) else 0)
        if (allow_send and sent >= expected) or (not allow_send and ready >= expected):
            post_status = connector.status(interactive=False) if deferred_status_probe else current_status()
            return {"ok": True, "ticks": ticks, "post_status": compact_status(post_status)}
        active_counts = [
            int(summary.get(name) or 0)
            for name in (
                "pending_sessions",
                "planner_queued",
                "planner_running",
                "polish_queued",
                "polish_running",
                "llm_queued",
                "llm_running",
                "reply_ready",
                "reply_sending",
            )
        ]
        if not any(active_counts):
            post_status = connector.status(interactive=False) if deferred_status_probe else current_status()
            return {
                "ok": False,
                "reason": "reply_incomplete_idle_no_visible_reply",
                "ticks": ticks,
                "post_status": compact_status(post_status),
            }
        time.sleep(max(0.2, float(tick_interval_seconds or 4.0)))
    return {"ok": False, "reason": "reply_timeout", "ticks": ticks, "post_status": compact_status(connector.status(interactive=False))}


def runtime_start_probe(run_dir: Path, config_path: Path, progress_path: Path) -> dict[str, Any]:
    runtime_root = tenant_runtime_root(TENANT_ID)
    runtime_config = runtime_root / "customer_service" / "listener_config.json"
    snapshots = backup_files([runtime_config, runtime_pid_path(TENANT_ID), runtime_operator_guard_state_path(TENANT_ID)])
    runtime = CustomerServiceRuntime(tenant_id=TENANT_ID)
    try:
        write_json(runtime_config, read_json(config_path))
        stopped = runtime.stop()
        append_jsonl(progress_path, {"event": "runtime_probe_stop_before_start", "result": stopped, "created_at": now_text()})
        start = runtime.start(token="")
        append_jsonl(progress_path, {"event": "runtime_probe_start", "result": start, "created_at": now_text()})
        if not start.get("ok"):
            return {"ok": False, "stage": "start", "start": start}
        time.sleep(10)
        status = runtime.status()
        guard_state = read_json(runtime_operator_guard_state_path(TENANT_ID))
        append_jsonl(progress_path, {"event": "runtime_probe_status", "status": status, "guard_state": guard_state, "created_at": now_text()})
        result = {
            "ok": bool(status.get("running") and status.get("operator_guard_running")),
            "status": {
                "running": status.get("running"),
                "state": status.get("state"),
                "pid": status.get("pid"),
                "operator_guard_running": status.get("operator_guard_running"),
                "operator_guard_pid": status.get("operator_guard_pid"),
                "message": status.get("message"),
            },
            "guard_state": {
                "mode": guard_state.get("mode"),
                "floating_indicator_enabled": guard_state.get("floating_indicator_enabled"),
                "block_manual_input": guard_state.get("block_manual_input"),
                "hotkey": guard_state.get("control_hotkey") or guard_state.get("hotkey"),
                "last_error": guard_state.get("last_error"),
            },
        }
        return result
    finally:
        stop = runtime.stop()
        append_jsonl(progress_path, {"event": "runtime_probe_stop_after_start", "result": stop, "created_at": now_text()})
        restore_files(snapshots)


def runtime_idle_probe(progress_path: Path) -> dict[str, Any]:
    runtime = CustomerServiceRuntime(tenant_id=TENANT_ID)
    stopped = runtime.stop()
    status = runtime.status()
    result = {
        "ok": not bool(status.get("running") or status.get("operator_guard_running")),
        "stopped": stopped,
        "status": {
            "running": status.get("running"),
            "state": status.get("state"),
            "pid": status.get("pid"),
            "operator_guard_running": status.get("operator_guard_running"),
            "operator_guard_pid": status.get("operator_guard_pid"),
            "message": status.get("message"),
        },
    }
    append_jsonl(progress_path, {"event": "runtime_idle_probe", "result": result, "created_at": now_text()})
    return result


def ledger_snapshot(target: str) -> dict[str, Any]:
    conversation_type = "group" if target == "新数据测试" else "private"
    key = stable_session_key(target, conversation_type=conversation_type)
    store = SessionLedgerStore(tenant_id=TENANT_ID)
    summary = store.load_summary(key)
    recent = summary.get("recent_messages") if isinstance(summary.get("recent_messages"), list) else []
    return {
        "target": target,
        "session_key": key,
        "recent_count": len(recent),
        "recent_tail": [
            {
                "message_id": item.get("message_id"),
                "sender_role": item.get("sender_role"),
                "content": str(item.get("content") or "")[:120],
                "processed": item.get("processed"),
                "reply_id": item.get("reply_id"),
            }
            for item in recent[-6:]
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    token = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ARTIFACT_ROOT / token
    run_dir.mkdir(parents=True, exist_ok=True)
    progress_path = run_dir / "progress.jsonl"
    result: dict[str, Any] = {
        "ok": False,
        "run_id": token,
        "artifact_dir": str(run_dir),
        "targets": TARGETS,
        "started_at": now_text(),
        "rounds_requested": max(1, int(getattr(args, "rounds", 1) or 1)),
        "dry_reply_send": bool(getattr(args, "dry_reply_send", False)),
        "scenario_set": str(getattr(args, "scenario_set", "default") or "default"),
    }
    tenant_root = tenant_runtime_root(TENANT_ID)
    snapshots = backup_files(
        [
            tenant_root / "customer_service" / "settings.json",
            tenant_root / "state" / "customer_service_scheduler_state.json",
            tenant_root / "state" / "customer_service_scheduler_state.json.lock",
        ]
    )
    config_path = build_config(run_dir)
    connector = WeChatConnector()
    bridge: ManagedListenerSchedulerBridge | None = None
    guard_started = False
    try:
        os.environ.update(
            {
                "WECHAT_KNOWLEDGE_TENANT": TENANT_ID,
                "WECHAT_ENABLE_WXAUTO4": "0",
                "WECHAT_DISABLE_WXAUTO4": "1",
                "WECHAT_WIN32_OCR_ALLOW_BLIND_FILE_TRANSFER_SEND": "0",
                "WECHAT_WIN32_OCR_PASSIVE_PROBE": "1",
                "WECHAT_RPA_OPERATOR_GUARD_ENABLED": "1",
                "WECHAT_RPA_OPERATOR_GUARD_BLOCK_MANUAL_INPUT": "1",
                "WECHAT_RPA_OPERATOR_GUARD_FLOATING_INDICATOR_ENABLED": "1",
                "WECHAT_RPA_OPERATOR_GUARD_CONTROL_HOTKEY": "f8",
            }
        )
        preflight = connector.capabilities(interactive=True)
        sessions = connector.list_sessions(fresh=True)
        result["preflight"] = compact_status(preflight)
        result["sessions"] = [
            {
                "name": item.get("name"),
                "session_key": item.get("session_key"),
                "conversation_type": item.get("conversation_type"),
                "unread_signal": item.get("unread_signal"),
                "content": item.get("content"),
            }
            for item in (sessions.get("sessions") or [])
            if isinstance(item, dict)
        ]
        session_key_by_target = {
            str(item.get("name") or ""): str(item.get("session_key") or "")
            for item in result["sessions"]
            if isinstance(item, dict) and str(item.get("name") or "") in TARGETS and str(item.get("session_key") or "")
        }
        conversation_type_by_target = {
            str(item.get("name") or ""): str(item.get("conversation_type") or "unknown")
            for item in result["sessions"]
            if isinstance(item, dict) and str(item.get("name") or "") in TARGETS
        }
        result["session_key_by_target"] = dict(session_key_by_target)
        result["conversation_type_by_target"] = dict(conversation_type_by_target)
        append_jsonl(progress_path, {"event": "preflight", "preflight": result["preflight"], "sessions": result["sessions"], "created_at": now_text()})
        reason = hard_status_reason(preflight)
        if reason:
            result["error"] = reason
            return finish(result, run_dir)
        visible = {str(item.get("name") or "") for item in result["sessions"]}
        missing = [target for target in TARGETS if target not in visible]
        if missing:
            result["error"] = "target_not_visible_in_session_scan"
            result["missing_targets"] = missing
            return finish(result, run_dir)
        missing_session_keys = [target for target in TARGETS if not session_key_by_target.get(target)]
        if missing_session_keys:
            result["error"] = "target_session_key_missing"
            result["missing_session_key_targets"] = missing_session_keys
            return finish(result, run_dir)

        configure_settings(conversation_type_by_target)

        result["runtime_idle_probe"] = runtime_idle_probe(progress_path)
        if not result["runtime_idle_probe"].get("ok"):
            result["error"] = "runtime_not_idle_before_live_simulation"
            return finish(result, run_dir)

        guard = launch_guard(read_json(config_path))
        guard_started = True
        result["operator_guard"] = guard
        append_jsonl(progress_path, {"event": "operator_guard_launch", "guard": guard, "created_at": now_text()})
        if not guard.get("ok"):
            result["error"] = "operator_guard_failed"
            return finish(result, run_dir)

        allow_reply_send = not args.no_reply_send
        result["reply_send_enabled"] = allow_reply_send
        bridge = build_bridge(config_path, connector, run_dir, allow_send=allow_reply_send)
        all_sent: list[dict[str, Any]] = []
        all_rounds: list[dict[str, Any]] = []
        total_ready = 0
        rounds = max(1, int(getattr(args, "rounds", 1) or 1))
        for round_index in range(1, rounds + 1):
            prompts = round_prompts(token, round_index, scenario_set=result["scenario_set"])
            round_dir = run_dir / f"round_{round_index:02d}"
            round_result: dict[str, Any] = {
                "round": round_index,
                "prompts": prompts,
                "started_at": now_text(),
                "prompt_results": [],
            }
            prepare_round_state(
                bridge,
                run_dir,
                round_index,
                continuous_ledger=bool(getattr(args, "continuous_ledger", False)),
            )
            prompt_results: list[dict[str, Any]] = []
            if args.skip_prompt_send:
                for target in TARGETS:
                    skipped = {"ok": True, "verified": True, "skipped": True, "reason": "skip_prompt_send"}
                    prompt_results.append({"target": target, "text": prompts[target], "send": skipped})
                    append_jsonl(progress_path, {"event": "prompt_send_skipped", "round": round_index, "target": target, "send": skipped, "created_at": now_text()})
            else:
                for target in TARGETS:
                    target_artifact_dir = round_dir / "prompt_send" / safe_name(target)
                    send = connector.send_text_and_verify(
                        target,
                        f"【{PROMPT_LABEL}{token}-R{round_index}-{target}】{prompts[target]}",
                        exact=True,
                        artifact_dir=str(target_artifact_dir),
                        session_key=session_key_by_target[target],
                    )
                    prompt_results.append({"target": target, "text": prompts[target], "send": compact_send(send)})
                    append_jsonl(progress_path, {"event": "prompt_send", "round": round_index, "target": target, "send": compact_send(send), "created_at": now_text()})
                    if not send.get("ok") or not send.get("verified"):
                        result["error"] = "prompt_send_failed"
                        failure = prompt_failure_summary(target, send)
                        result["failure_category"] = failure["category"]
                        result["failure"] = failure
                        round_result["failure"] = failure
                        round_result["prompt_results"] = prompt_results
                        all_rounds.append(round_result)
                        result["rounds"] = all_rounds
                        return finish(result, run_dir)
                    status = connector.status(interactive=False)
                    reason = hard_status_reason(status)
                    if reason:
                        result["error"] = reason
                        round_result["prompt_results"] = prompt_results
                        all_rounds.append(round_result)
                        result["rounds"] = all_rounds
                        return finish(result, run_dir)
                    time.sleep(max(0.0, float(getattr(args, "prompt_gap_seconds", 8.0) or 0.0)))
            round_result["prompt_results"] = prompt_results

            synthetic_by_target = {
                target: {
                    "id": f"two_visible_session_live:{token}:r{round_index}:{target}",
                    "type": "text",
                    "sender": "customer",
                    "sender_role": "customer",
                    "content": prompts[target],
                    "time": now_text(),
                    "source_adapter": "codex_two_visible_session_live",
                }
                for target in TARGETS
            }
            wrapper = SyntheticInboundConnector(
                connector,
                synthetic_by_target,
                dry_reply_send=bool(getattr(args, "dry_reply_send", False)),
                synthetic_input_only=bool(getattr(args, "synthetic_input_only", False)),
            )
            bridge.connector = wrapper
            if bridge.runtime is not None:
                bridge.runtime.capture_fn = bridge._capture_session
                bridge.runtime.send_fn = bridge._send_reply
            seed_synthetic_pending_sessions(
                bridge,
                progress_path,
                session_key_by_target=session_key_by_target,
                conversation_type_by_target=conversation_type_by_target,
            )
            round_result["ledger_before"] = [ledger_snapshot(target) for target in TARGETS]
            replies = wait_for_replies(
                bridge,
                connector,
                progress_path,
                expected=len(TARGETS),
                allow_send=allow_reply_send,
                timeout_seconds=float(getattr(args, "reply_timeout_seconds", 240.0) or 240.0),
                tick_interval_seconds=float(getattr(args, "tick_interval_seconds", 4.0) or 4.0),
                probe_status_each_tick=not bool(getattr(args, "dry_reply_send", False)),
            )
            round_result["reply_phase"] = replies
            round_result["sent_replies"] = wrapper.sent
            round_result["ledger_after"] = [ledger_snapshot(target) for target in TARGETS]
            all_sent.extend(wrapper.sent)
            if not replies.get("ok"):
                apply_reply_failure_result(result, round_result, replies, wrapper.sent)
                all_rounds.append(round_result)
                result["rounds"] = all_rounds
                return finish(result, run_dir)
            if not allow_reply_send:
                ready_count = reply_ready_count(replies)
                round_result["ready_reply_count"] = ready_count
                round_result["target_match_ok"] = ready_count >= len(TARGETS)
                total_ready += ready_count
                if not round_result["target_match_ok"]:
                    result["error"] = "ready_reply_count_mismatch"
                    all_rounds.append(round_result)
                    result["rounds"] = all_rounds
                    return finish(result, run_dir)
            else:
                coverage = sent_target_coverage(wrapper.sent, TARGETS)
                key_coverage = sent_session_key_coverage(wrapper.sent, session_key_by_target)
                round_result["sent_target_counts"] = coverage["counts"]
                round_result["missing_reply_targets"] = coverage["missing_targets"]
                round_result["unexpected_reply_targets"] = coverage["unexpected_targets"]
                round_result["target_match_ok"] = bool(coverage.get("ok"))
                round_result["session_key_match_ok"] = bool(key_coverage.get("ok"))
                round_result["session_key_mismatches"] = key_coverage.get("mismatches")
                if not round_result["target_match_ok"]:
                    result["error"] = "sent_target_mismatch"
                    all_rounds.append(round_result)
                    result["rounds"] = all_rounds
                    return finish(result, run_dir)
                if not round_result["session_key_match_ok"]:
                    result["error"] = "sent_session_key_mismatch"
                    all_rounds.append(round_result)
                    result["rounds"] = all_rounds
                    return finish(result, run_dir)
            status = connector.status(interactive=False)
            reason = hard_status_reason(status)
            if reason:
                result["error"] = reason
                all_rounds.append(round_result)
                result["rounds"] = all_rounds
                return finish(result, run_dir)
            round_result["post_status"] = compact_status(status)
            round_result["ok"] = True
            round_result["finished_at"] = now_text()
            all_rounds.append(round_result)
            result["rounds"] = all_rounds
            write_json(run_dir / "partial_result.json", result)
            if round_index < rounds:
                time.sleep(max(0.0, float(getattr(args, "round_gap_seconds", 2.0) or 0.0)))
        result["sent_replies"] = all_sent
        if not allow_reply_send:
            result["ready_reply_count"] = total_ready
            result["target_match_ok"] = total_ready >= len(TARGETS) * rounds
        else:
            coverage = sent_target_coverage(all_sent, TARGETS)
            key_coverage = sent_session_key_coverage(all_sent, session_key_by_target)
            result["sent_target_counts"] = coverage["counts"]
            result["missing_reply_targets"] = coverage["missing_targets"]
            result["unexpected_reply_targets"] = coverage["unexpected_targets"]
            result["target_match_ok"] = bool(coverage.get("ok")) and all(
                int(coverage.get("counts", {}).get(target, 0) or 0) >= rounds
                for target in TARGETS
            )
            result["session_key_match_ok"] = bool(key_coverage.get("ok"))
            result["session_key_mismatches"] = key_coverage.get("mismatches")
            if not result["target_match_ok"]:
                result["error"] = "sent_target_mismatch"
                return finish(result, run_dir)
            if not result["session_key_match_ok"]:
                result["error"] = "sent_session_key_mismatch"
                return finish(result, run_dir)
        postflight = connector.capabilities(interactive=False)
        result["postflight"] = compact_status(postflight)
        reason = hard_status_reason(postflight)
        if reason:
            result["error"] = reason
            return finish(result, run_dir)
        result["ok"] = True
        return finish(result, run_dir)
    except Exception as exc:  # noqa: BLE001
        result["error"] = repr(exc)
        result["exception_type"] = type(exc).__name__
        result["traceback"] = traceback.format_exc()
        return finish(result, run_dir)
    finally:
        if bridge is not None:
            bridge.shutdown()
        if guard_started:
            stop_guard("two_visible_session_live_complete")
        restore_files(snapshots)


def finish(result: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    result["finished_at"] = now_text()
    path = run_dir / "result.json"
    write_json(path, result)
    result["result_path"] = str(path)
    return result


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    reply = result.get("reply_phase") if isinstance(result.get("reply_phase"), dict) else {}
    return {
        "ok": result.get("ok"),
        "error": result.get("error", ""),
        "failure_category": result.get("failure_category", ""),
        "failure": result.get("failure") if isinstance(result.get("failure"), dict) else {},
        "targets": result.get("targets"),
        "rounds_requested": result.get("rounds_requested"),
        "rounds_completed": sum(1 for item in result.get("rounds", []) if isinstance(item, dict) and item.get("ok")),
        "dry_reply_send": result.get("dry_reply_send"),
        "runtime_start_probe": result.get("runtime_start_probe"),
        "prompt_results": [
            {
                "target": item.get("target"),
                "ok": (item.get("send") or {}).get("ok"),
                "verified": (item.get("send") or {}).get("verified"),
                "confirmed_target": ((item.get("send") or {}).get("pre_send_guard") or {}).get("confirmed_target"),
            }
            for item in result.get("prompt_results", [])
        ],
        "rounds": [
            {
                "round": item.get("round"),
                "ok": item.get("ok"),
                "ready_reply_count": item.get("ready_reply_count"),
                "target_match_ok": item.get("target_match_ok"),
                "session_key_match_ok": item.get("session_key_match_ok"),
                "sent_count": len(item.get("sent_replies") or []),
                "missing_reply_targets": item.get("missing_reply_targets"),
                "unexpected_reply_targets": item.get("unexpected_reply_targets"),
                "failure": item.get("failure") if isinstance(item.get("failure"), dict) else {},
                "post_status": item.get("post_status"),
            }
            for item in result.get("rounds", [])
            if isinstance(item, dict)
        ],
        "sent_replies": [
            {
                "target": item.get("target"),
                "ok": (item.get("result") or {}).get("ok"),
                "verified": (item.get("result") or {}).get("verified"),
                "confirmed_target": ((item.get("result") or {}).get("pre_send_guard") or {}).get("confirmed_target"),
                "preview": str(item.get("text") or "")[:80],
            }
            for item in result.get("sent_replies", [])
        ],
        "reply_ok": reply.get("ok"),
        "reply_reason": reply.get("reason", ""),
        "ready_reply_count": result.get("ready_reply_count"),
        "target_match_ok": result.get("target_match_ok"),
        "postflight": result.get("postflight"),
        "artifact_dir": result.get("artifact_dir"),
        "result_path": result.get("result_path"),
    }


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


class _SelfCheckBridge:
    def __init__(self, ticks: list[dict[str, Any]]) -> None:
        self._ticks = list(ticks)

    def tick(self, *, allow_send: bool = True) -> dict[str, Any]:
        if self._ticks:
            return self._ticks.pop(0)
        return {
            "ok": True,
            "duration_seconds": 0.0,
            "summary": {
                "pending_sessions": 0,
                "planner_queued": 0,
                "planner_running": 0,
                "polish_queued": 0,
                "polish_running": 0,
                "llm_queued": 0,
                "llm_running": 0,
                "reply_ready": 0,
            },
            "events": [],
        }


class _SelfCheckConnector:
    def __init__(self) -> None:
        self.status_calls = 0

    def status(self, *, interactive: bool = False) -> dict[str, Any]:
        self.status_calls += 1
        return {
            "ok": True,
            "online": True,
            "state": "main_window_compat",
            "ocr_count": 1,
            "interactive": bool(interactive),
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--self-check", action="store_true", help="Run offline harness assertions without touching WeChat.")
    parser.add_argument("--skip-prompt-send", action="store_true", help="Reuse synthetic inbound without sending new prompt messages to WeChat.")
    parser.add_argument("--no-reply-send", action="store_true", help="Run capture/Brain scheduling until replies are ready, but do not send replies to WeChat.")
    parser.add_argument("--dry-reply-send", action="store_true", help="Run capture/Brain/scheduler and simulate the final RPA reply send as successful.")
    parser.add_argument(
        "--synthetic-input-only",
        action="store_true",
        help="Test-only mode: feed synthetic inbound directly instead of mixing current live OCR bubbles into the capture batch.",
    )
    parser.add_argument("--rounds", type=int, default=1, help="Number of two-session synthetic customer rounds to run.")
    parser.add_argument("--continuous-ledger", action="store_true", help="Keep scheduler state and session ledger across rounds to simulate one continuous conversation.")
    parser.add_argument("--reply-timeout-seconds", type=float, default=240.0)
    parser.add_argument("--tick-interval-seconds", type=float, default=4.0)
    parser.add_argument("--prompt-gap-seconds", type=float, default=8.0)
    parser.add_argument("--round-gap-seconds", type=float, default=2.0)
    parser.add_argument(
        "--scenario-set",
        choices=sorted(SCENARIO_SETS),
        default="default",
        help="Synthetic two-session prompt set to replay.",
    )
    args = parser.parse_args()
    if args.self_check:
        ok = run_self_check()
        print_json({"ok": ok})
        return 0 if ok else 1
    result = run(args)
    print_json(compact_result(result))
    return 0 if result.get("ok") else 1


def run_self_check() -> bool:
    if target_conversation_type("新数据测试", {"新数据测试": "private"}) != "private":
        return False
    if target_conversation_type("新数据测试", {}) != "group":
        return False
    split_sent = [
        {"target": "新数据测试", "result": {"ok": True}},
        {"target": "新数据测试", "result": {"ok": True}},
        {"target": "许聪", "result": {"ok": True}},
        {"target": "许聪", "result": {"ok": True}},
    ]
    split = sent_target_coverage(split_sent, TARGETS)
    if not split.get("ok"):
        return False
    if split.get("counts") != {"新数据测试": 2, "许聪": 2}:
        return False
    missing = sent_target_coverage([{"target": "新数据测试", "result": {"ok": True}}], TARGETS)
    if missing.get("ok") or missing.get("missing_targets") != ["许聪"]:
        return False
    unexpected = sent_target_coverage(
        [{"target": "新数据测试", "result": {"ok": True}}, {"target": "陌生会话", "result": {"ok": True}}],
        TARGETS,
    )
    if unexpected.get("ok") or unexpected.get("unexpected_targets") != ["陌生会话"]:
        return False
    key_ok = sent_session_key_coverage(
        [
            {"target": "新数据测试", "session_key": "key-a", "result": {"ok": True}},
            {"target": "许聪", "session_key": "key-b", "result": {"ok": True}},
        ],
        {"新数据测试": "key-a", "许聪": "key-b"},
    )
    if not key_ok.get("ok") or key_ok.get("checked") != 2:
        return False
    key_bad = sent_session_key_coverage(
        [{"target": "新数据测试", "session_key": "wrong", "result": {"ok": True}}],
        {"新数据测试": "key-a"},
    )
    if key_bad.get("ok") or not key_bad.get("mismatches"):
        return False
    if not round_prompts("unit", 1).get("新数据测试"):
        return False
    if round_prompts("unit", len(PROMPT_SCENARIOS) + 1) != round_prompts("unit", 1):
        return False
    if round_prompts("unit", len(BOUNDARY_PROMPT_SCENARIOS) + 1, scenario_set="boundary") != round_prompts("unit", 1, scenario_set="boundary"):
        return False
    if len(scenario_prompts("boundary")) < 8:
        return False
    if round_prompts("unit", len(SHORT_GREETING_PROMPT_SCENARIOS) + 1, scenario_set="short_greeting") != round_prompts("unit", 1, scenario_set="short_greeting"):
        return False
    if scenario_prompts("short_greeting")[0].get("新数据测试") != "你好":
        return False
    if round_prompts("unit", len(SHORT_BUSINESS_PROMPT_SCENARIOS) + 1, scenario_set="short_business") != round_prompts("unit", 1, scenario_set="short_business"):
        return False
    if scenario_prompts("short_business")[0].get("新数据测试") != "秦PLUS多少钱？":
        return False
    with tempfile.TemporaryDirectory() as temp:
        progress_path = Path(temp) / "progress.jsonl"
        ticks = [
            {
                "ok": True,
                "duration_seconds": 0.0,
                "summary": {"llm_running": 1},
                "events": [],
            },
            {
                "ok": True,
                "duration_seconds": 0.0,
                "summary": {"reply_sent": 1},
                "events": [{"event": "send_completed", "target_name": "新数据测试"}],
            },
        ]
        dry_connector = _SelfCheckConnector()
        dry_result = wait_for_replies(
            _SelfCheckBridge(ticks),
            dry_connector,
            progress_path,
            expected=1,
            allow_send=True,
            timeout_seconds=5,
            tick_interval_seconds=0.2,
            probe_status_each_tick=False,
        )
        if not dry_result.get("ok") or dry_connector.status_calls != 1:
            return False
        live_connector = _SelfCheckConnector()
        live_result = wait_for_replies(
            _SelfCheckBridge(ticks),
            live_connector,
            progress_path,
            expected=1,
            allow_send=True,
            timeout_seconds=5,
            tick_interval_seconds=0.2,
            probe_status_each_tick=True,
        )
        if not live_result.get("ok") or live_connector.status_calls != 2:
            return False
        sending_connector = _SelfCheckConnector()
        sending_result = wait_for_replies(
            _SelfCheckBridge(
                [
                    {
                        "ok": True,
                        "duration_seconds": 0.0,
                        "summary": {"reply_sending": 1},
                        "events": [{"event": "send_dispatched", "target_name": "新数据测试"}],
                    },
                    {
                        "ok": True,
                        "duration_seconds": 0.0,
                        "summary": {"reply_sent": 1},
                        "events": [{"event": "send_completed", "target_name": "新数据测试"}],
                    },
                ]
            ),
            sending_connector,
            progress_path,
            expected=1,
            allow_send=True,
            timeout_seconds=5,
            tick_interval_seconds=0.2,
            probe_status_each_tick=True,
        )
        if not sending_result.get("ok") or sending_connector.status_calls != 1:
            return False
    config_check_dir = ARTIFACT_ROOT / "_self_check_config"
    previous_input_method = os.environ.get("WECHAT_LIVE_TEST_RPA_INPUT_METHOD")
    try:
        os.environ.pop("WECHAT_LIVE_TEST_RPA_INPUT_METHOD", None)
        default_config_path = build_config(config_check_dir)
        default_config = json.loads(default_config_path.read_text(encoding="utf-8"))
        default_rpa = default_config.get("rpa_humanized_send") or {}
        if default_rpa.get("input_method") != "clipboard_chunks":
            return False
        if default_rpa.get("typing_typo_probability") != 0.0 or default_rpa.get("typing_typo_max") != 0:
            return False
        os.environ["WECHAT_LIVE_TEST_RPA_INPUT_METHOD"] = "sendinput_unicode"
        override_config_path = build_config(config_check_dir)
        override_config = json.loads(override_config_path.read_text(encoding="utf-8"))
        if (override_config.get("rpa_humanized_send") or {}).get("input_method") != "sendinput_unicode":
            return False
        os.environ["WECHAT_LIVE_TEST_RPA_INPUT_METHOD"] = "invalid"
        fallback_config_path = build_config(config_check_dir)
        fallback_config = json.loads(fallback_config_path.read_text(encoding="utf-8"))
        if (fallback_config.get("rpa_humanized_send") or {}).get("input_method") != "clipboard_chunks":
            return False
    finally:
        if previous_input_method is None:
            os.environ.pop("WECHAT_LIVE_TEST_RPA_INPUT_METHOD", None)
        else:
            os.environ["WECHAT_LIVE_TEST_RPA_INPUT_METHOD"] = previous_input_method

    prompt_failure = prompt_failure_summary(
        "新数据测试",
        {
            "ok": False,
            "verified": False,
            "send": {
                "state": "send_input_not_ready",
                "target": "新数据测试",
                "guard": {
                    "reason": "target_confirmed",
                    "click": {
                        "reason": "paste_not_confirmed",
                        "paste": {
                            "reason": "input_token_not_detected_after_paste",
                            "probe_token": "双会话",
                            "probe_tokens": ["双会话", "长测"],
                            "input_mode": "clipboard_chunks",
                            "input_region": {"has_visible_text": False, "reason": "input_region_blank"},
                            "input_result": {"chunks": 2, "typo_count": 0},
                        },
                    },
                },
                "error": "Could not confirm pasted text in WeChat input box before send.",
            },
        },
    )
    if prompt_failure.get("category") != "prompt_send_rpa":
        return False
    if prompt_failure.get("state") != "send_input_not_ready":
        return False
    if prompt_failure.get("reason") != "paste_not_confirmed":
        return False
    if (prompt_failure.get("input_region") or {}).get("reason") != "input_region_blank":
        return False

    partial_failure = summarize_reply_failure(
        {
            "ok": False,
            "reason": "reply_timeout",
            "ticks": [
                {
                    "summary": {"pending_sessions": 0, "planner_queued": 0, "reply_ready": 0},
                    "events": [
                        {
                            "event": "llm_task_failed_requeued_planner",
                            "reason": "customer_service_brain_no_visible_reply",
                            "target": "新数据测试",
                            "session_key": "key-a",
                        }
                    ],
                }
            ],
            "post_status": {"online": True, "state": "main_window_compat"},
        },
        [{"target": "许聪", "session_key": "key-b", "result": {"ok": True, "verified": True}}],
        TARGETS,
    )
    if partial_failure.get("category") != "partial_brain_no_visible":
        return False
    if partial_failure.get("missing_reply_targets") != ["新数据测试"]:
        return False
    if not partial_failure.get("brain_no_visible_events"):
        return False

    brain_failure = summarize_reply_failure(
        {
            "ok": False,
            "reason": "reply_incomplete_idle_no_visible_reply",
            "ticks": [
                {
                    "summary": {"pending_sessions": 0, "planner_queued": 0, "reply_ready": 0},
                    "events": [],
                }
            ],
        },
        [],
        TARGETS,
    )
    if brain_failure.get("category") != "brain_no_visible":
        return False

    rpa_failure = summarize_reply_failure(
        {
            "ok": False,
            "reason": "send_input_not_ready",
            "ticks": [
                {
                    "summary": {"reply_ready": 1},
                    "events": [
                        {
                            "event": "scheduler_send_failed",
                            "target": "许聪",
                            "send_result": {
                                "ok": False,
                                "state": "send_input_not_ready",
                                "reason": "paste_not_confirmed",
                            },
                        }
                    ],
                }
            ],
        },
        [],
        TARGETS,
    )
    if rpa_failure.get("category") != "reply_send_rpa":
        return False
    if not rpa_failure.get("rpa_send_events"):
        return False

    round_result: dict[str, Any] = {}
    result: dict[str, Any] = {}
    apply_reply_failure_result(
        result,
        round_result,
        {
            "ok": False,
            "reason": "reply_timeout",
            "ticks": [
                {
                    "summary": {"pending_sessions": 0},
                    "events": [
                        {
                            "event": "llm_task_failed_requeued_planner",
                            "reason": "customer_service_brain_no_visible_reply",
                            "target": "新数据测试",
                        }
                    ],
                }
            ],
        },
        [{"target": "许聪", "session_key": "key-b", "result": {"ok": True, "verified": True}}],
    )
    if result.get("failure_category") != "partial_brain_no_visible":
        return False
    if round_result.get("missing_reply_targets") != ["新数据测试"]:
        return False

    class FakeRealConnector:
        def get_messages(self, target: str, exact: bool = True, history_load_times: int = 0, **kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "messages": [
                    {
                        "id": "real-history",
                        "type": "text",
                        "sender": "customer",
                        "content": "这是现场历史残留，不应进入synthetic-only测试批次",
                    }
                ],
            }

    wrapper = SyntheticInboundConnector(
        FakeRealConnector(),  # type: ignore[arg-type]
        {"新数据测试": {"id": "synthetic-current", "type": "text", "sender": "customer", "content": "本轮合成输入"}},
        dry_reply_send=True,
        synthetic_input_only=True,
    )
    payload = wrapper.get_messages("新数据测试")
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if len(messages) != 1 or str(messages[0].get("id") or "") != "synthetic-current":
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
