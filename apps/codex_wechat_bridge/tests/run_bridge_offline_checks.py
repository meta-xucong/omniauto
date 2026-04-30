"""Offline checks for the Codex WeChat bridge."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
for path in (APP_ROOT, APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import bridge_loop as bridge_loop_module  # noqa: E402
from bridge_loop import (  # noqa: E402
    bootstrap_messages,
    format_wechat_reply,
    load_state,
    message_key,
    process_prompt,
    process_wechat_command,
    run_wechat_once,
    save_state,
    select_new_messages,
)
from codex_app_server import parse_ws_endpoint  # noqa: E402
from task_ledger import load_ledger  # noqa: E402


ARTIFACT_ROOT = ROOT / "runtime/apps/codex_wechat_bridge/test_artifacts/offline_checks"


def main() -> int:
    if ARTIFACT_ROOT.exists():
        shutil.rmtree(ARTIFACT_ROOT)
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    config = {
        "version": 1,
        "state_path": str(ARTIFACT_ROOT / "state.json"),
        "ledger_path": str(ARTIFACT_ROOT / "task_ledger.json"),
        "artifact_root": str(ARTIFACT_ROOT),
        "codex": {
            "mode": "fake",
            "fake_thread_id": "fake-visible-thread",
            "fake_response_template": "FAKE_CODEX_REPLY: {prompt}",
        },
        "wechat": {
            "allow_self_messages": True,
            "command_prefix": "[ToCodex]",
            "ignore_prefixes": ["[Codex] "],
            "reply_prefix": "[Codex] ",
            "send_receipts": True,
            "max_reply_chars": 32,
        },
        "dedupe": {
            "history_limit": 3,
        },
    }

    checks = [
        check_endpoint_parse(),
        check_direct_prompt(config),
        check_message_filtering(config),
        check_unstable_id_dedupe(config),
        check_repeated_command_after_new_time(config),
        check_repeated_command_same_time(config),
        check_no_context_same_id_dedupe(config),
        check_no_context_same_command_new_id(config),
        check_system_message_filtering(config),
        check_reply_formatting(config),
        check_dedupe_limit(config),
        check_bootstrap(config),
        check_use_command(config),
        check_list_command(config),
        check_new_command(config),
        check_stop_command(config),
        check_task_receipt_and_ledger(config),
        check_verified_send_failure(config),
        check_pending_send_failure(config),
        check_pending_does_not_block_new_task(config),
        check_stop_preempts_pending(config),
    ]
    failures = [item for item in checks if not item["ok"]]
    payload = {"ok": not failures, "failures": failures, "checks": checks}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def check_endpoint_parse() -> dict[str, object]:
    host, port = parse_ws_endpoint("ws://127.0.0.1:17910")
    return {"name": "endpoint_parse", "ok": host == "127.0.0.1" and port == 17910}


def check_direct_prompt(config: dict[str, object]) -> dict[str, object]:
    result = process_prompt(config, "bridge offline task", title="offline-title")
    state = load_state(config)
    ok = (
        result.get("ok") is True
        and result.get("thread_id") == "fake-visible-thread"
        and "bridge offline task" in str(result.get("assistant_text"))
        and state.get("active_thread_id") == "fake-visible-thread"
        and len(state.get("runs", [])) == 1
    )
    return {"name": "direct_prompt_fake_codex", "ok": ok, "result": result}


def check_message_filtering(config: dict[str, object]) -> dict[str, object]:
    messages = [
        {"id": "1", "sender": "self", "content": "[Codex] already answered", "time": "t1"},
        {"id": "2", "sender": "self", "content": "[ToCodex] new task", "time": "t2"},
        {"id": "3", "sender": "self", "content": "accidental text without prefix", "time": "t3"},
        {"id": "4", "sender": "other", "content": "", "time": "t4"},
    ]
    state = load_state(config)
    selected = select_new_messages(config, state, messages)
    ok = len(selected) == 1 and selected[0]["content"] == "[ToCodex] new task"
    return {"name": "message_filtering", "ok": ok, "selected": selected}


def check_unstable_id_dedupe(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "unstable_id_state.json")
    first_batch = [
        {"id": "t1", "sender": "system", "type": "time", "content": "10:00", "time": "2026-04-30 10:00:00"},
        {"id": "volatile-a", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    second_batch = [
        {"id": "t1", "sender": "system", "type": "time", "content": "10:00", "time": "2026-04-30 10:00:00"},
        {"id": "volatile-b", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    state = load_state(local_config)
    selected_first = select_new_messages(local_config, state, first_batch)
    key = message_key(selected_first[0])
    state["processed_message_keys"] = [key]
    state["processed_message_fingerprints"] = [bridge_loop_module.message_fingerprint(selected_first[0])]
    save_state(local_config, state)
    selected_second = select_new_messages(local_config, load_state(local_config), second_batch)
    ok = len(selected_first) == 1 and selected_second == []
    return {
        "name": "unstable_wxauto_id_dedupe",
        "ok": ok,
        "first_key": key,
        "second_selected": selected_second,
    }


def check_repeated_command_after_new_time(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "repeated_command_after_new_time_state.json")
    first_batch = [
        {"id": "t1", "sender": "system", "type": "time", "content": "10:00", "time": "2026-04-30 10:00:00"},
        {"id": "status-a", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    second_batch = [
        {"id": "t2", "sender": "system", "type": "time", "content": "10:01", "time": "2026-04-30 10:01:00"},
        {"id": "status-b", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    state = load_state(local_config)
    selected_first = select_new_messages(local_config, state, first_batch)
    first = selected_first[0]
    state["processed_message_keys"] = [message_key(first)]
    state["processed_message_fingerprints"] = [bridge_loop_module.message_fingerprint(first)]
    save_state(local_config, state)
    selected_second = select_new_messages(local_config, load_state(local_config), second_batch)
    ok = (
        len(selected_first) == 1
        and len(selected_second) == 1
        and selected_second[0]["content"] == "[ToCodex] /status"
    )
    return {
        "name": "repeated_command_after_new_time_is_not_suppressed",
        "ok": ok,
        "first_selected": selected_first,
        "second_selected": selected_second,
    }


def check_repeated_command_same_time(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "repeated_command_same_time_state.json")
    first_batch = [
        {"id": "t1", "sender": "system", "type": "time", "content": "10:00", "time": "2026-04-30 10:00:00"},
        {"id": "status-a", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    second_batch = [
        {"id": "t1", "sender": "system", "type": "time", "content": "10:00", "time": "2026-04-30 10:00:00"},
        {"id": "status-a2", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
        {"id": "status-b", "sender": "self", "type": "text", "content": "[ToCodex] /status", "time": None},
    ]
    state = load_state(local_config)
    selected_first = select_new_messages(local_config, state, first_batch)
    first = selected_first[0]
    state["processed_message_keys"] = [message_key(first)]
    state["processed_message_fingerprints"] = [bridge_loop_module.message_fingerprint(first)]
    save_state(local_config, state)
    selected_second = select_new_messages(local_config, load_state(local_config), second_batch)
    ok = (
        len(selected_first) == 1
        and len(selected_second) == 1
        and selected_second[0]["content"] == "[ToCodex] /status"
        and selected_second[0].get("_bridge_occurrence") == 2
    )
    return {
        "name": "repeated_command_same_time_is_not_suppressed",
        "ok": ok,
        "first_selected": selected_first,
        "second_selected": selected_second,
    }


def check_no_context_same_id_dedupe(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "no_context_same_id_state.json")
    first = {"id": "stable-stop", "sender": "self", "type": "text", "content": "[ToCodex] /stop", "time": None}
    second = {"id": "stable-stop", "sender": "self", "type": "text", "content": "[ToCodex] /stop", "time": None}
    state = load_state(local_config)
    selected_first = select_new_messages(local_config, state, [first])
    first = selected_first[0]
    state["processed_message_keys"] = [message_key(first)]
    state["processed_message_fingerprints"] = [bridge_loop_module.message_fingerprint(first)]
    save_state(local_config, state)
    selected_second = select_new_messages(local_config, load_state(local_config), [second])
    ok = len(selected_first) == 1 and selected_second == []
    return {
        "name": "no_context_same_id_is_deduped",
        "ok": ok,
        "first_selected": selected_first,
        "second_selected": selected_second,
    }


def check_no_context_same_command_new_id(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "no_context_same_command_new_id_state.json")
    first = {"id": "old-stop", "sender": "self", "type": "text", "content": "[ToCodex] /stop", "time": None}
    second = {"id": "new-stop", "sender": "self", "type": "text", "content": "[ToCodex] /stop", "time": None}
    state = load_state(local_config)
    selected_first = select_new_messages(local_config, state, [first])
    first = selected_first[0]
    state["processed_message_keys"] = [message_key(first)]
    state["processed_message_fingerprints"] = [bridge_loop_module.message_fingerprint(first)]
    save_state(local_config, state)
    selected_second = select_new_messages(local_config, load_state(local_config), [second])
    ok = (
        len(selected_first) == 1
        and len(selected_second) == 1
        and selected_second[0]["content"] == "[ToCodex] /stop"
    )
    return {
        "name": "no_context_same_command_new_id_is_not_suppressed",
        "ok": ok,
        "first_selected": selected_first,
        "second_selected": selected_second,
    }


def check_system_message_filtering(config: dict[str, object]) -> dict[str, object]:
    messages = [
        {"id": "s1", "sender": "system", "content": "01:20", "time": "t1"},
        {"id": "s2", "sender": "system", "content": "2026年4月30日", "time": "t2"},
        {"id": "u1", "sender": "self", "content": "[ToCodex] real task", "time": "t3"},
    ]
    state = {"processed_message_keys": []}
    selected = select_new_messages(config, state, messages)
    ok = len(selected) == 1 and selected[0]["content"] == "[ToCodex] real task"
    return {"name": "system_message_filtering", "ok": ok, "selected": selected}


def check_reply_formatting(config: dict[str, object]) -> dict[str, object]:
    reply = format_wechat_reply(config, "x" * 100)
    ok = reply.startswith("[Codex] ") and len(reply) <= 32 and reply.endswith("[truncated]")
    return {"name": "reply_formatting", "ok": ok, "reply": reply}


def check_dedupe_limit(config: dict[str, object]) -> dict[str, object]:
    state = load_state(config)
    messages = [
        {"id": str(index), "sender": "self", "content": f"task {index}", "time": f"t{index}"}
        for index in range(5)
    ]
    state["processed_message_keys"] = [message_key(item) for item in messages]
    save_state(config, state)
    selected = select_new_messages(config, load_state(config), messages)
    # save_state does not trim by itself; process_prompt/remember_processed_key own
    # the rolling dedupe behavior. This check ensures stored keys are honored.
    ok = selected == []
    return {"name": "dedupe_processed_keys", "ok": ok}


def check_bootstrap(config: dict[str, object]) -> dict[str, object]:
    state = {"processed_message_keys": []}
    messages = [
        {"id": "a", "sender": "self", "content": "old task", "time": "ta"},
        {"id": "b", "sender": "self", "content": "", "time": "tb"},
    ]
    added = bootstrap_messages(config, state, messages)
    selected = select_new_messages(config, state, messages)
    ok = added == 1 and selected == []
    return {"name": "bootstrap_existing_messages", "ok": ok, "added": added}


def check_use_command(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "use_command_state.json")
    result = process_wechat_command(local_config, "[ToCodex] /use thread-123")
    state = load_state(local_config)
    ok = (
        result.get("ok") is True
        and result.get("command") == "use"
        and state.get("active_thread_id") == "thread-123"
        and "thread-123" in str(result.get("reply_text"))
    )
    return {"name": "use_command_updates_active_thread", "ok": ok, "result": result, "state": state}


def check_list_command(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "list_command_state.json")
    result = process_wechat_command(local_config, "[ToCodex] /list 3")
    ok = (
        result.get("ok") is True
        and result.get("command") == "list"
        and "fake-visible-thread" in str(result.get("reply_text"))
        and (result.get("threads_result") or {}).get("thread_count") == 1
    )
    return {"name": "list_command_formats_threads", "ok": ok, "result": result}


def check_new_command(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "new_command_state.json")
    save_state(
        local_config,
        {"version": 1, "active_thread_id": "old-thread", "processed_message_keys": [], "runs": []},
    )
    result = process_wechat_command(local_config, "[ToCodex] /new fresh task")
    state = load_state(local_config)
    ok = (
        result.get("ok") is True
        and result.get("command") == "new"
        and result.get("prompt") == "fresh task"
        and state.get("active_thread_id") == "fake-visible-thread"
    )
    return {"name": "new_command_starts_fresh_thread", "ok": ok, "result": result, "state": state}


def check_stop_command(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "stop_command_state.json")
    result = process_wechat_command(local_config, "[ToCodex] /stop")
    state = load_state(local_config)
    ok = (
        result.get("ok") is True
        and result.get("command") == "stop"
        and state.get("stop_requested") is True
        and "Stop requested" in str(result.get("reply_text"))
    )
    return {"name": "stop_command_sets_stop_requested", "ok": ok, "result": result, "state": state}


def check_verified_send_failure(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "verified_send_failure_state.json")
    local_config["wechat"]["max_reply_chars"] = 200
    local_config["wechat"]["max_final_reply_chars"] = 500
    message = {"id": "send-fail", "sender": "self", "content": "[ToCodex] task needing verified send", "time": "t-send"}
    fake = FakeWeChatConnector(
        [message],
        [
            {"ok": True, "verified": True, "send": {"ok": True}},
            {"ok": False, "verified": False, "send": {"ok": True}},
        ],
    )
    result = run_once_with_fake_connector(local_config, fake, send=True)
    state = load_state(local_config)
    ledger = load_ledger(local_config)
    run = ledger.get("runs", [{}])[-1]
    key = message_key(message)
    final_call = fake.verify_calls[1] if len(fake.verify_calls) > 1 else ("", False, None)
    ok = (
        result.get("ok") is True
        and len(fake.verify_calls) == 2
        and fake.verify_calls[0][0].startswith("[Codex] 已识别到问题：")
        and "正在思考中。" in fake.verify_calls[0][0]
        and str(final_call[0]).startswith("[Codex] run_id:")
        and "status: done" in str(final_call[0])
        and "FAKE_CODEX_REPLY: task needing verified send" in str(final_call[0])
        and final_call[1] is True
        and final_call[2] == f"final:{run.get('run_id')}"
        and key in state.get("processed_message_keys", [])
        and state.get("pending_reply") is None
        and run.get("status") == "send_unknown"
        and run.get("wechat_final_send_state") == "unknown"
        and run.get("wechat_receipt_sent") is True
        and result.get("results", [{}])[0].get("sent") is True
        and result.get("results", [{}])[0].get("send_state") == "unknown"
    )
    return {"name": "verified_send_unknown_does_not_retry", "ok": ok, "result": result, "state": state, "run": run}


def check_task_receipt_and_ledger(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "task_receipt_state.json")
    local_config["wechat"]["max_reply_chars"] = 200
    local_config["wechat"]["max_final_reply_chars"] = 500
    message = {"id": "task-ok", "sender": "self", "content": "[ToCodex] task with receipt", "time": "t-task"}
    fake = FakeWeChatConnector(
        [message],
        [
            {"ok": True, "verified": True, "send": {"ok": True}},
            {"ok": True, "verified": True, "send": {"ok": True}},
        ],
    )
    result = run_once_with_fake_connector(local_config, fake, send=True)
    ledger = load_ledger(local_config)
    run = ledger.get("runs", [{}])[-1]
    final_call = fake.verify_calls[1] if len(fake.verify_calls) > 1 else ("", False, None)
    ok = (
        result.get("ok") is True
        and len(fake.verify_calls) == 2
        and fake.verify_calls[0][0].startswith("[Codex] 已识别到问题：")
        and "正在思考中。" in fake.verify_calls[0][0]
        and str(final_call[0]).startswith("[Codex] run_id:")
        and "status: done" in str(final_call[0])
        and "FAKE_CODEX_REPLY: task with receipt" in str(final_call[0])
        and final_call[1] is True
        and final_call[2] == f"final:{run.get('run_id')}"
        and run.get("run_id") == result.get("results", [{}])[0].get("run_id")
        and run.get("status") == "done"
        and run.get("thread_id") == "fake-visible-thread"
        and run.get("turn_id")
        and run.get("wechat_receipt_sent") is True
        and run.get("wechat_final_sent") is True
    )
    return {"name": "task_receipt_and_ledger", "ok": ok, "result": result, "run": run}


def check_pending_send_failure(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "pending_send_failure_state.json")
    message = {"id": "pending", "sender": "self", "content": "pending task", "time": "t-pending"}
    key = message_key(message)
    state = {
        "version": 1,
        "active_thread_id": "fake-visible-thread",
        "processed_message_keys": [],
        "runs": [],
        "pending_reply": {
            "created_at": "2026-04-30T01:00:00",
            "target": "文件传输助手",
            "exact": True,
            "message_key": key,
            "message": message,
            "codex": {"ok": True},
            "reply_text": "[Codex] pending reply",
        },
    }
    save_state(local_config, state)
    fake = FakeWeChatConnector([], {"ok": False, "verified": False, "send": {"ok": False}})
    result = run_once_with_fake_connector(local_config, fake, send=True)
    updated = load_state(local_config)
    ok = (
        result.get("ok") is False
        and result.get("pending_sent") is False
        and result.get("pending_retry_exhausted") is True
        and updated.get("pending_reply") is None
        and (updated.get("failed_replies") or [{}])[-1].get("message_key") == key
        and key not in updated.get("processed_message_keys", [])
        and fake.verify_calls == [("[Codex] pending reply", True, None)]
    )
    return {"name": "pending_send_failure_is_archived", "ok": ok, "result": result, "state": updated}


def check_pending_does_not_block_new_task(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "pending_does_not_block_state.json")
    local_config["wechat"]["max_reply_chars"] = 200
    local_config["wechat"]["max_final_reply_chars"] = 500
    pending_message = {"id": "old-pending", "sender": "self", "content": "[ToCodex] old task", "time": "t-old"}
    pending_key = message_key(pending_message)
    new_message = {"id": "new-task", "sender": "self", "content": "[ToCodex] new task wins", "time": "t-new"}
    save_state(
        local_config,
        {
            "version": 1,
            "active_thread_id": "fake-visible-thread",
            "processed_message_keys": [],
            "runs": [],
            "pending_reply": {
                "created_at": "2026-04-30T01:00:00",
                "target": "文件传输助手",
                "exact": True,
                "message_key": pending_key,
                "message": pending_message,
                "codex": {"ok": True},
                "reply_text": "[Codex] old pending reply",
            },
        },
    )
    fake = FakeWeChatConnector(
        [new_message],
        [
            {"ok": True, "verified": True, "send": {"ok": True}},
            {"ok": True, "verified": True, "send": {"ok": True}},
        ],
    )
    result = run_once_with_fake_connector(local_config, fake, send=True)
    updated = load_state(local_config)
    ledger = load_ledger(local_config)
    run = ledger.get("runs", [{}])[-1]
    result_key = result.get("results", [{}])[0].get("message_key")
    ok = (
        result.get("ok") is True
        and len(fake.verify_calls) == 2
        and fake.verify_calls[0][0].startswith("[Codex] 已识别到问题：new task wins")
        and "old pending reply" not in fake.verify_calls[0][0]
        and "old pending reply" not in fake.verify_calls[1][0]
        and result_key in updated.get("processed_message_keys", [])
        and (updated.get("pending_reply") or {}).get("message_key") == pending_key
        and run.get("prompt") == "new task wins"
        and run.get("status") == "done"
    )
    return {"name": "pending_does_not_block_new_task", "ok": ok, "result": result, "state": updated, "run": run}


def check_stop_preempts_pending(config: dict[str, object]) -> dict[str, object]:
    local_config = isolated_config(config, "stop_preempts_pending_state.json")
    local_config["wechat"]["max_reply_chars"] = 200
    pending_message = {"id": "pending", "sender": "self", "content": "[ToCodex] old task", "time": "t-pending"}
    pending_key = message_key(pending_message)
    stop_message = {"id": "stop", "sender": "self", "content": "[ToCodex] /stop", "time": "t-stop"}
    stop_key = message_key(stop_message)
    state = {
        "version": 1,
        "active_thread_id": "fake-visible-thread",
        "processed_message_keys": [],
        "runs": [],
        "pending_reply": {
            "created_at": "2026-04-30T01:00:00",
            "target": "文件传输助手",
            "exact": True,
            "message_key": pending_key,
            "message": pending_message,
            "codex": {"ok": True},
            "reply_text": "[Codex] pending reply",
        },
    }
    save_state(local_config, state)
    fake = FakeWeChatConnector([stop_message], {"ok": True, "verified": True, "send": {"ok": True}})
    result = run_once_with_fake_connector(local_config, fake, send=True)
    updated = load_state(local_config)
    result_key = result.get("results", [{}])[0].get("message_key")
    ok = (
        result.get("ok") is True
        and result.get("control_preempted_pending") is True
        and updated.get("stop_requested") is True
        and updated.get("pending_reply") is None
        and result_key in updated.get("processed_message_keys", [])
        and pending_key not in updated.get("processed_message_keys", [])
        and fake.verify_calls == [("[Codex] Stop requested. Bridge loop will exit after this reply.", True, None)]
    )
    return {"name": "stop_preempts_pending_reply", "ok": ok, "result": result, "state": updated}


def isolated_config(config: dict[str, object], state_file: str) -> dict[str, object]:
    local_config = json.loads(json.dumps(config, ensure_ascii=False))
    local_config["state_path"] = str(ARTIFACT_ROOT / state_file)
    local_config["ledger_path"] = str(ARTIFACT_ROOT / state_file.replace(".json", "_ledger.json"))
    state_path = Path(str(local_config["state_path"]))
    if state_path.exists():
        state_path.unlink()
    ledger_path = Path(str(local_config["ledger_path"]))
    if ledger_path.exists():
        ledger_path.unlink()
    return local_config


def run_once_with_fake_connector(config: dict[str, object], fake: "FakeWeChatConnector", send: bool) -> dict[str, object]:
    original = bridge_loop_module.WeChatConnector
    bridge_loop_module.WeChatConnector = lambda: fake
    try:
        return run_wechat_once(config, send=send)
    finally:
        bridge_loop_module.WeChatConnector = original


class FakeWeChatConnector:
    def __init__(self, messages: list[dict[str, object]], verify_result: dict[str, object] | list[dict[str, object]]) -> None:
        self.messages = messages
        self.verify_results = list(verify_result) if isinstance(verify_result, list) else [verify_result]
        self.verify_calls: list[tuple[str, bool, str | None]] = []

    def get_messages(self, target: str, exact: bool = True) -> dict[str, object]:
        return {"ok": True, "target": target, "exact": exact, "messages": self.messages}

    def send_text(self, target: str, text: str, exact: bool = True) -> dict[str, object]:
        raise AssertionError("run_wechat_once must use send_text_and_verify")

    def send_text_and_verify(
        self,
        target: str,
        text: str,
        exact: bool = True,
        verify_token: str | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        self.verify_calls.append((text, exact, verify_token))
        if len(self.verify_results) > 1:
            return dict(self.verify_results.pop(0))
        return dict(self.verify_results[0])


if __name__ == "__main__":
    raise SystemExit(main())
