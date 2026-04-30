"""Bridge WeChat task messages into Codex Desktop-visible app-server threads."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
for path in (APP_ROOT, APP_ROOT / "adapters", APP_ROOT / "workflows"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from codex_app_server import list_threads, resolve_path, send_prompt  # noqa: E402
from task_ledger import (  # noqa: E402
    create_run,
    format_status_reply,
    preview,
    update_run,
)
from wechat_connector import FILE_TRANSFER_ASSISTANT, WeChatConnector  # noqa: E402


DEFAULT_CONFIG_PATH = APP_ROOT / "configs" / "default.example.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--prompt", help="Send a direct prompt to Codex without reading WeChat.")
    parser.add_argument("--once", action="store_true", help="Poll the configured WeChat chat once.")
    parser.add_argument("--loop", action="store_true", help="Poll the configured WeChat chat until interrupted.")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Seconds to wait between --loop polls.")
    parser.add_argument("--bootstrap", action="store_true", help="Mark current WeChat messages as processed without calling Codex.")
    parser.add_argument("--send", action="store_true", help="Actually send Codex output back to WeChat.")
    parser.add_argument("--reset-state", action="store_true", help="Delete bridge state before running.")
    parser.add_argument("--thread-id", help="Override the persisted active Codex thread id.")
    parser.add_argument("--title", help="Title for a newly created Codex thread.")
    args = parser.parse_args()

    config = load_config(args.config)
    if args.reset_state:
        reset_state(config)

    if args.prompt:
        result = process_prompt(config, args.prompt, thread_id=args.thread_id, title=args.title)
    elif args.bootstrap:
        result = bootstrap_wechat(config)
    elif args.loop:
        result = run_wechat_loop(config, send=bool(args.send), interval_seconds=args.interval_seconds, thread_id=args.thread_id, title=args.title)
    elif args.once:
        result = run_wechat_once(config, send=bool(args.send), thread_id=args.thread_id, title=args.title)
    else:
        parser.error("Provide --prompt, --bootstrap, or --once")

    print_json(result)
    return 0 if result.get("ok") else 1


def run_wechat_loop(
    config: dict[str, Any],
    *,
    send: bool,
    interval_seconds: float,
    thread_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    interval = max(1.0, float(interval_seconds))
    print_json(
        {
            "ok": True,
            "event": "loop_started",
            "send_enabled": bool(send),
            "interval_seconds": interval,
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    while True:
        try:
            result = run_wechat_once(config, send=send, thread_id=thread_id, title=title)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            result = {
                "ok": False,
                "event": "loop_iteration_error",
                "error": repr(exc),
            }
        result["loop_at"] = datetime.now().isoformat(timespec="seconds")
        record_poll_heartbeat(config, result)
        print_json(result)
        sys.stdout.flush()
        if consume_stop_requested(config):
            stop_result = {
                "ok": True,
                "event": "loop_stopped",
                "stopped_at": datetime.now().isoformat(timespec="seconds"),
            }
            print_json(stop_result)
            return stop_result
        time.sleep(interval)


def load_config(path: Path) -> dict[str, Any]:
    resolved = resolve_path(path)
    config = json.loads(resolved.read_text(encoding="utf-8"))
    config["_config_path"] = str(resolved)
    return config


def state_path(config: dict[str, Any]) -> Path:
    return resolve_path(config.get("state_path", "runtime/apps/codex_wechat_bridge/state/bridge_state.json"))


def load_state(config: dict[str, Any]) -> dict[str, Any]:
    path = state_path(config)
    if not path.exists():
        return {"version": 1, "active_thread_id": None, "processed_message_keys": [], "runs": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def reset_state(config: dict[str, Any]) -> None:
    path = state_path(config)
    if path.exists():
        path.unlink()


def process_prompt(
    config: dict[str, Any],
    prompt: str,
    *,
    thread_id: str | None = None,
    title: str | None = None,
    message_key_value: str | None = None,
    force_new: bool = False,
) -> dict[str, Any]:
    state = load_state(config)
    active_thread_id = None if force_new else (thread_id or state.get("active_thread_id"))
    resolved_title = title or default_thread_title(config)
    codex_result = send_prompt(config, prompt, thread_id=active_thread_id, title=resolved_title)
    ok = codex_result.get("status") == "ok"
    if ok:
        state["active_thread_id"] = codex_result.get("threadId") or active_thread_id
        if message_key_value:
            remember_processed_key(config, state, message_key_value)
        append_run(state, prompt, codex_result)
        save_state(config, state)
    return {
        "ok": bool(ok),
        "prompt": prompt,
        "thread_id": codex_result.get("threadId"),
        "turn_id": codex_result.get("turnId"),
        "assistant_text": codex_result.get("assistantText", ""),
        "codex": compact_codex_result(codex_result),
        "state_path": str(state_path(config)),
    }


def run_wechat_once(
    config: dict[str, Any],
    *,
    send: bool,
    thread_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    wechat_config = dict(config.get("wechat") or {})
    target = str(wechat_config.get("target") or FILE_TRANSFER_ASSISTANT)
    exact = bool(wechat_config.get("exact", True))
    connector = WeChatConnector()
    messages_payload = connector.get_messages(target, exact=exact)
    messages = messages_payload.get("messages", []) or []
    annotate_message_keys(messages)
    state = load_state(config)
    pending = state.get("pending_reply")
    stop_message = find_unprocessed_stop_message(config, state, messages)
    if stop_message is not None:
        key = message_key(stop_message)
        result = process_wechat_command(config, str(stop_message.get("content") or ""), thread_id=thread_id, title=title)
        reply_text = format_wechat_reply(config, str(result.get("reply_text") or result.get("assistant_text") or ""))
        if result.get("ok"):
            state = load_state(config)
            remember_processed_message(config, state, stop_message, key=key)
            save_state(config, state)
        send_result: dict[str, Any] | None = None
        sent = False
        send_state = "not_attempted"
        if send and result.get("ok") and reply_text:
            send_result = connector.send_text_and_verify(
                target,
                reply_text,
                exact=exact,
                verify_attempts=4,
                verify_interval_seconds=0.5,
                initial_delay_seconds=0.5,
            )
            send_state = classify_send_result(send_result)
            sent = send_state in {"verified", "unknown"}
            state = load_state(config)
            state["pending_reply"] = None
            save_state(config, state)
        elif result.get("ok") and reply_text:
            state = load_state(config)
            state["pending_reply"] = None
            save_state(config, state)
        ok = bool(result.get("ok")) and (not send or not reply_text or sent)
        return {
            "ok": ok,
            "target": target,
            "send_enabled": bool(send),
            "message_count": len(messages),
            "new_count": 1,
            "processed_count": 1 if result.get("ok") else 0,
            "control_preempted_pending": isinstance(pending, dict) and bool(pending.get("message_key")),
            "results": [
                {
                    "ok": ok,
                    "message_key": key,
                    "message": compact_message(stop_message),
                    "codex": result,
                    "reply_text": reply_text,
                    "send": send_result,
                    "send_state": send_state,
                    "sent": sent,
                }
            ],
            "messages_payload_ok": bool(messages_payload.get("ok")),
        }

    new_messages = select_new_messages(config, state, messages)
    max_messages = int(wechat_config.get("max_messages_per_poll") or 1)
    selected = new_messages[:max_messages]
    if not selected and isinstance(pending, dict) and pending.get("message_key"):
        return process_pending_reply(config, connector, target, exact, pending, send=send, message_count=len(messages), messages_payload_ok=bool(messages_payload.get("ok")))
    results = []
    for message in selected:
        text = str(message.get("content") or "").strip()
        key = message_key(message)
        task_request = parse_task_request(config, text)
        run: dict[str, Any] | None = None
        receipt_send: dict[str, Any] | None = None
        if task_request:
            active_thread_id = None if task_request.get("force_new") else (thread_id or load_state(config).get("active_thread_id"))
            run = create_run(
                config,
                message_key=key,
                message=message,
                prompt=str(task_request["prompt"]),
                command=str(task_request["command"]),
                active_thread_id=active_thread_id,
            )
            update_run(config, str(run["run_id"]), status="running", note="Codex task is running.")
            if send and send_receipts_enabled(config):
                receipt_text = format_wechat_reply(config, task_received_text(run))
                receipt_send = connector.send_text_and_verify(
                    target,
                    receipt_text,
                    exact=exact,
                    verify_attempts=4,
                    verify_interval_seconds=0.5,
                    initial_delay_seconds=0.5,
                )
                update_run(
                    config,
                    str(run["run_id"]),
                    note="WeChat receipt send attempted.",
                    wechat_receipt_sent=bool(receipt_send.get("verified")),
                    receipt_send=receipt_send,
                )
        result = process_wechat_command(config, text, thread_id=thread_id, title=title)
        if run is not None:
            result["run_id"] = run["run_id"]
            if result.get("ok"):
                update_run(
                    config,
                    str(run["run_id"]),
                    status="codex_completed",
                    note="Codex turn completed.",
                    thread_id=result.get("thread_id"),
                    turn_id=result.get("turn_id"),
                    assistant_preview=preview(str(result.get("assistant_text") or result.get("reply_text") or ""), 500),
                )
            else:
                update_run(
                    config,
                    str(run["run_id"]),
                    status="failed",
                    note=str(result.get("error") or "Codex task failed."),
                    error=result.get("error") or result,
                )
        reply_source = result.get("reply_text")
        if reply_source is None:
            reply_source = result.get("assistant_text", "")
        verify_token: str | None = None
        if run is not None:
            verify_token = task_final_verify_token(str(run["run_id"]))
            reply_text = format_task_final_reply(config, str(run["run_id"]), result, str(reply_source or ""))
        else:
            reply_text = format_wechat_reply(config, str(reply_source or ""))
        send_result: dict[str, Any] | None = None
        sent = False
        send_state = "not_attempted"
        state = load_state(config)
        if result.get("ok"):
            remember_processed_message(config, state, message, key=key)
            save_state(config, state)
        if send and result.get("ok") and reply_text:
            send_result = connector.send_text_and_verify(
                target,
                reply_text,
                exact=exact,
                verify_token=verify_token,
                verify_attempts=18,
                verify_interval_seconds=1.0,
                initial_delay_seconds=1.0,
            )
            send_state = classify_send_result(send_result)
            sent = send_state in {"verified", "unknown"}
            state = load_state(config)
            if sent:
                clear_matching_pending_reply(state, key)
                if run is not None:
                    run_status = "done" if send_state == "verified" else "send_unknown"
                    note = "Final reply sent to WeChat." if send_state == "verified" else "Final reply was accepted by WeChat but could not be read back for verification."
                    update_run(
                        config,
                        str(run["run_id"]),
                        status=run_status,
                        note=note,
                        wechat_final_sent=send_state == "verified",
                        wechat_final_send_state=send_state,
                        final_send=send_result,
                    )
            else:
                set_pending_reply(
                    state,
                    build_pending_reply(
                        target,
                        exact,
                        key,
                        message,
                        result,
                        reply_text,
                        verify_token=verify_token,
                    ),
                )
                if run is not None:
                    update_run(
                        config,
                        str(run["run_id"]),
                        status="send_failed",
                        note="Final reply could not be verified in WeChat.",
                        wechat_final_sent=False,
                        wechat_final_send_state=send_state,
                        final_send=send_result,
                    )
            save_state(config, state)
        elif result.get("ok") and reply_text:
            state = load_state(config)
            set_pending_reply(
                state,
                build_pending_reply(
                    target,
                    exact,
                    key,
                    message,
                    result,
                    reply_text,
                    verify_token=verify_token,
                ),
            )
            save_state(config, state)
        results.append(
            {
                "ok": bool(result.get("ok")) and (not send or not reply_text or sent),
                "message_key": key,
                "message": compact_message(message),
                "codex": result,
                "reply_text": reply_text,
                "run_id": run.get("run_id") if run else None,
                "receipt_send": receipt_send,
                "send": send_result,
                "send_state": classify_send_result(send_result) if send_result else "not_attempted",
                "sent": sent,
            }
        )

    return {
        "ok": all(item.get("ok") for item in results) if selected else True,
        "target": target,
        "send_enabled": bool(send),
        "message_count": len(messages),
        "new_count": len(new_messages),
        "processed_count": sum(1 for item in results if item.get("ok")),
        "results": results,
        "messages_payload_ok": bool(messages_payload.get("ok")),
    }


def process_pending_reply(
    config: dict[str, Any],
    connector: WeChatConnector,
    target: str,
    exact: bool,
    pending: dict[str, Any],
    *,
    send: bool,
    message_count: int,
    messages_payload_ok: bool,
) -> dict[str, Any]:
    if not send:
        return {
            "ok": True,
            "target": target,
            "send_enabled": False,
            "message_count": message_count,
            "new_count": 0,
            "processed_count": 0,
            "pending_reply": pending,
            "results": [],
            "messages_payload_ok": messages_payload_ok,
        }

    state = load_state(config)
    retry_count = int(pending.get("retry_count") or 0)
    max_retries = max_pending_retries(config)
    if retry_count >= max_retries:
        archive_pending_reply(state, pending, reason="retry_exhausted")
        state["pending_reply"] = None
        save_state(config, state)
        if pending.get("run_id"):
            update_run(
                config,
                str(pending.get("run_id")),
                status="send_failed",
                note="Pending final reply retry exhausted; manual resend may be required.",
                wechat_final_send_state="retry_exhausted",
            )
        return {
            "ok": False,
            "target": target,
            "send_enabled": True,
            "message_count": message_count,
            "new_count": 0,
            "processed_count": 0,
            "pending_sent": False,
            "pending_retry_exhausted": True,
            "results": [
                {
                    "ok": False,
                    "message_key": pending.get("message_key"),
                    "message": pending.get("message"),
                    "codex": pending.get("codex"),
                    "reply_text": pending_reply_text(config, pending),
                    "send_state": "retry_exhausted",
                    "sent": False,
                }
            ],
            "messages_payload_ok": messages_payload_ok,
        }

    reply_text = pending_reply_text(config, pending)
    verify_token = pending_verify_token(pending)
    send_result = (
        connector.send_text_and_verify(
            target,
            reply_text,
            exact=exact,
            verify_token=verify_token,
            verify_attempts=18,
            verify_interval_seconds=1.0,
            initial_delay_seconds=1.0,
        )
        if reply_text
        else None
    )
    send_state = classify_send_result(send_result)
    sent = send_state in {"verified", "unknown"}
    if sent:
        remember_processed_message(
            config,
            state,
            dict(pending.get("message") or {}),
            key=str(pending.get("message_key")),
        )
        state["pending_reply"] = None
        save_state(config, state)
        if pending.get("run_id"):
            run_status = "done" if send_state == "verified" else "send_unknown"
            note = "Pending final reply sent to WeChat." if send_state == "verified" else "Pending final reply was accepted by WeChat but could not be read back for verification."
            update_run(
                config,
                str(pending.get("run_id")),
                status=run_status,
                note=note,
                wechat_final_sent=send_state == "verified",
                wechat_final_send_state=send_state,
                final_send=send_result,
            )
    else:
        retry_count += 1
        pending["retry_count"] = retry_count
        pending["last_send_state"] = send_state
        pending["reply_text"] = reply_text
        if verify_token:
            pending["verify_token"] = verify_token
        if retry_count >= max_retries:
            archive_pending_reply(state, pending, reason="retry_exhausted")
            state["pending_reply"] = None
            note = "Pending final reply still could not be sent and retry limit was reached."
            exhausted = True
        else:
            state["pending_reply"] = pending
            note = "Pending final reply still could not be sent."
            exhausted = False
        save_state(config, state)
        if pending.get("run_id"):
            update_run(
                config,
                str(pending.get("run_id")),
                status="send_failed",
                note=note,
                wechat_final_sent=False,
                wechat_final_send_state=send_state,
                final_send=send_result,
            )

    return {
        "ok": sent,
        "target": target,
        "send_enabled": True,
        "message_count": message_count,
        "new_count": 0,
        "processed_count": 1 if sent else 0,
        "pending_sent": sent,
        "pending_retry_count": retry_count,
        "pending_retry_exhausted": (not sent and retry_count >= max_retries),
        "results": [
            {
                "ok": sent,
                "message_key": pending.get("message_key"),
                "message": pending.get("message"),
                "codex": pending.get("codex"),
                "reply_text": reply_text,
                "send": send_result,
                "send_state": send_state,
                "sent": sent,
            }
        ],
        "messages_payload_ok": messages_payload_ok,
    }


def bootstrap_wechat(config: dict[str, Any]) -> dict[str, Any]:
    wechat_config = dict(config.get("wechat") or {})
    target = str(wechat_config.get("target") or FILE_TRANSFER_ASSISTANT)
    exact = bool(wechat_config.get("exact", True))
    connector = WeChatConnector()
    messages_payload = connector.get_messages(target, exact=exact)
    messages = messages_payload.get("messages", []) or []
    state = load_state(config)
    added = bootstrap_messages(config, state, messages)
    save_state(config, state)
    return {
        "ok": bool(messages_payload.get("ok")),
        "target": target,
        "message_count": len(messages),
        "bootstrapped_count": added,
        "state_path": str(state_path(config)),
    }


def process_wechat_command(
    config: dict[str, Any],
    text: str,
    *,
    thread_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    parsed = parse_wechat_command(config, text)
    if parsed is None:
        return {
            "ok": True,
            "kind": "ignored",
            "reply_text": "",
            "reason": "missing_command_prefix",
        }

    body = parsed["body"]
    prefix = parsed["prefix"]
    if not body:
        return command_reply(command_help(prefix), command="help", command_ok=False)

    if not body.startswith("/"):
        result = process_prompt(config, body, thread_id=thread_id, title=title)
        result["kind"] = "task"
        result["command_prefix"] = prefix
        return result

    command, _, rest = body.partition(" ")
    command = command.lower()
    rest = rest.strip()

    if command in {"/help", "/h", "/?"}:
        return command_reply(command_help(prefix), command="help")

    if command == "/status":
        state = load_state(config)
        active = state.get("active_thread_id") or "(none)"
        reply_text = format_status_reply(config, active)
        if rest:
            reply_text = f"{reply_text}\nrequest: {rest}"
        return command_reply(reply_text, command="status")

    if command == "/stop":
        state = load_state(config)
        state["stop_requested"] = True
        state["shutdown_requested_at"] = time.time()
        save_state(config, state)
        reply_text = "Stop requested. Bridge loop will exit after this reply."
        if rest:
            reply_text = f"{reply_text}\nrequest: {rest}"
        return command_reply(reply_text, command="stop")

    if command == "/use":
        if not rest:
            return command_reply(f"Usage: {prefix} /use <thread_id>", command="use", command_ok=False)
        thread_id_value = rest.split()[0]
        state = load_state(config)
        state["active_thread_id"] = thread_id_value
        save_state(config, state)
        return command_reply(f"Switched active Codex thread to:\n{thread_id_value}", command="use")

    if command == "/new":
        if not rest:
            return command_reply(f"Usage: {prefix} /new <task>", command="new", command_ok=False)
        result = process_prompt(config, rest, thread_id=None, title=title, force_new=True)
        result["kind"] = "task"
        result["command"] = "new"
        result["command_prefix"] = prefix
        return result

    if command == "/list":
        limit = parse_limit(rest, default=8, maximum=20)
        state = load_state(config)
        listed = list_threads(config, limit=limit)
        return command_reply(
            format_thread_list(listed, active_thread_id=state.get("active_thread_id")),
            command="list",
            command_ok=listed.get("status") == "ok",
            extra={"threads_result": compact_thread_list_result(listed)},
        )

    return command_reply(
        f"Unknown command: {command}\n\n{command_help(prefix)}",
        command=command.lstrip("/") or "unknown",
        command_ok=False,
    )


def parse_wechat_command(config: dict[str, Any], text: str) -> dict[str, str] | None:
    content = (text or "").strip()
    prefix = command_prefix(config)
    if prefix:
        if not content.startswith(prefix):
            return None
        content = content[len(prefix) :].strip()
    return {"prefix": prefix, "body": content}


def parse_task_request(config: dict[str, Any], text: str) -> dict[str, Any] | None:
    parsed = parse_wechat_command(config, text)
    if parsed is None:
        return None
    body = parsed["body"]
    if not body:
        return None
    if not body.startswith("/"):
        return {"command": "task", "prompt": body, "force_new": False}

    command, _, rest = body.partition(" ")
    if command.lower() != "/new":
        return None
    rest = rest.strip()
    if not rest:
        return None
    return {"command": "new", "prompt": rest, "force_new": True}


def send_receipts_enabled(config: dict[str, Any]) -> bool:
    wechat_config = dict(config.get("wechat") or {})
    return bool(wechat_config.get("send_receipts", True))


def task_received_text(run: dict[str, Any]) -> str:
    prompt_preview = preview(str(run.get("prompt") or ""), 100)
    return "\n".join(
        [
            f"已识别到问题：{prompt_preview}",
            "正在思考中。",
            f"run_id: {run.get('run_id')}",
            f"thread_id: {run.get('thread_id') or '(new thread)'}",
        ]
    )


def find_unprocessed_stop_message(
    config: dict[str, Any],
    state: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for message in reversed(select_new_messages(config, state, messages)):
        if is_stop_command(config, str(message.get("content") or "")):
            return message
    return None


def is_stop_command(config: dict[str, Any], text: str) -> bool:
    parsed = parse_wechat_command(config, text)
    if parsed is None:
        return False
    command = parsed["body"].split(maxsplit=1)[0].lower() if parsed["body"] else ""
    return command == "/stop"


def command_prefix(config: dict[str, Any]) -> str:
    wechat_config = dict(config.get("wechat") or {})
    return str(wechat_config.get("command_prefix") or "[ToCodex]").strip()


def command_reply(
    text: str,
    *,
    command: str,
    command_ok: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "ok": True,
        "kind": "command",
        "command": command,
        "command_ok": bool(command_ok),
        "reply_text": text,
    }
    if extra:
        result.update(extra)
    return result


def command_help(prefix: str) -> str:
    return "\n".join(
        [
            "Codex WeChat commands:",
            f"{prefix} <task>",
            f"{prefix} /new <task>",
            f"{prefix} /list [limit]",
            f"{prefix} /use <thread_id>",
            f"{prefix} /status",
            f"{prefix} /stop",
            f"{prefix} /help",
        ]
    )


def parse_limit(text: str, *, default: int, maximum: int) -> int:
    if not text:
        return default
    first = text.split()[0]
    try:
        return max(1, min(int(first), maximum))
    except ValueError:
        return default


def format_thread_list(result: dict[str, Any], *, active_thread_id: str | None) -> str:
    if result.get("status") != "ok":
        return f"Could not list Codex threads:\n{result.get('error') or 'unknown error'}"

    threads = list(result.get("threads") or [])
    if not threads:
        return "No Codex threads found."

    lines = ["Recent Codex threads:"]
    for index, thread in enumerate(threads, start=1):
        thread_id = str(thread.get("id") or "")
        name = str(thread.get("name") or "(untitled)")
        status = thread.get("status") or {}
        status_text = status.get("type") if isinstance(status, dict) else str(status)
        marker = " active" if active_thread_id and thread_id == active_thread_id else ""
        lines.append(f"{index}. {name}{marker} [{status_text or 'unknown'}]\n{thread_id}")
    return "\n\n".join(lines)


def compact_thread_list_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "error": result.get("error"),
        "thread_count": len(result.get("threads") or []),
        "fake": result.get("fake"),
        "artifacts": result.get("artifacts"),
    }


def record_poll_heartbeat(config: dict[str, Any], result: dict[str, Any]) -> None:
    state = load_state(config)
    state["last_poll"] = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "ok": bool(result.get("ok")),
        "message_count": result.get("message_count"),
        "new_count": result.get("new_count"),
        "processed_count": result.get("processed_count"),
        "send_enabled": result.get("send_enabled"),
        "error": result.get("error"),
    }
    save_state(config, state)


def build_pending_reply(
    target: str,
    exact: bool,
    key: str,
    message: dict[str, Any],
    result: dict[str, Any],
    reply_text: str,
    *,
    verify_token: str | None = None,
) -> dict[str, Any]:
    pending = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_id": result.get("run_id"),
        "target": target,
        "exact": exact,
        "message_key": key,
        "message": compact_message(message),
        "codex": result,
        "reply_text": reply_text,
    }
    if verify_token:
        pending["verify_token"] = verify_token
    return pending


def pending_reply_text(config: dict[str, Any], pending: dict[str, Any]) -> str:
    run_id = str(pending.get("run_id") or "")
    if not run_id:
        return str(pending.get("reply_text") or "")
    result = dict(pending.get("codex") or {})
    reply_source = result.get("reply_text")
    if reply_source is None:
        reply_source = result.get("assistant_text")
    if reply_source is None:
        reply_source = pending.get("reply_text")
    return format_task_final_reply(config, run_id, result, str(reply_source or ""))


def pending_verify_token(pending: dict[str, Any]) -> str | None:
    token = str(pending.get("verify_token") or "").strip()
    if token:
        return token
    run_id = str(pending.get("run_id") or "").strip()
    return task_final_verify_token(run_id) if run_id else None


def classify_send_result(send_result: dict[str, Any] | None) -> str:
    if not send_result:
        return "not_attempted"
    if send_result.get("verified"):
        return "verified"
    send_payload = send_result.get("send")
    if isinstance(send_payload, dict) and send_payload.get("ok"):
        return "unknown"
    return "failed"


def clear_matching_pending_reply(state: dict[str, Any], key: str) -> None:
    pending = state.get("pending_reply")
    if not isinstance(pending, dict):
        return
    if not key or pending.get("message_key") == key:
        state["pending_reply"] = None


def set_pending_reply(state: dict[str, Any], pending: dict[str, Any]) -> None:
    existing = state.get("pending_reply")
    if (
        isinstance(existing, dict)
        and existing.get("message_key")
        and existing.get("message_key") != pending.get("message_key")
    ):
        archive_pending_reply(state, existing, reason="superseded_by_new_pending")
    state["pending_reply"] = pending


def max_pending_retries(config: dict[str, Any]) -> int:
    wechat_config = dict(config.get("wechat") or {})
    return max(0, int(wechat_config.get("max_pending_retries") or 1))


def archive_pending_reply(state: dict[str, Any], pending: dict[str, Any], *, reason: str) -> None:
    failed = list(state.get("failed_replies") or [])
    archived = dict(pending)
    archived["archived_at"] = datetime.now().isoformat(timespec="seconds")
    archived["archive_reason"] = reason
    failed.append(archived)
    state["failed_replies"] = failed[-20:]


def bootstrap_messages(config: dict[str, Any], state: dict[str, Any], messages: list[dict[str, Any]]) -> int:
    annotate_message_keys(messages)
    seen = set(state.get("processed_message_keys", []) or [])
    added = 0
    for message in messages:
        if str(message.get("content") or "").strip():
            key = message_key(message)
            if key not in seen:
                remember_processed_message(config, state, message, key=key)
                seen.add(key)
                added += 1
    return added


def select_new_messages(config: dict[str, Any], state: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotate_message_keys(messages)
    wechat_config = dict(config.get("wechat") or {})
    allow_self = bool(wechat_config.get("allow_self_messages", True))
    ignore_prefixes = [str(item) for item in wechat_config.get("ignore_prefixes", []) or []]
    required_prefix = command_prefix(config)
    processed = set(state.get("processed_message_keys", []) or [])
    processed_fingerprints = set(state.get("processed_message_fingerprints", []) or [])
    selected: list[dict[str, Any]] = []
    for message in messages:
        content = str(message.get("content") or "").strip()
        sender = str(message.get("sender") or "")
        if not content:
            continue
        if sender == "system":
            continue
        if is_system_time_marker(content):
            continue
        if sender == "self" and not allow_self:
            continue
        if any(content.startswith(prefix) for prefix in ignore_prefixes):
            continue
        if required_prefix and not content.startswith(required_prefix):
            continue
        key = message_key(message)
        fingerprint = message_fingerprint(message)
        if key in processed or fingerprint in processed_fingerprints:
            continue
        selected.append(message)
    return selected


def is_system_time_marker(content: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}:\d{2}", content.strip()))


def annotate_message_keys(messages: list[dict[str, Any]]) -> None:
    context_time = ""
    occurrence_counts: dict[str, int] = {}
    for message in messages:
        sender = str(message.get("sender") or "")
        content = str(message.get("content") or "").strip()
        if sender == "system":
            context_time = str(message.get("time") or content or context_time)
            continue
        message["_bridge_context_time"] = context_time
        signature = message_signature(message, context_time=context_time)
        signature_key = json.dumps(signature, ensure_ascii=False, sort_keys=True)
        occurrence_counts[signature_key] = occurrence_counts.get(signature_key, 0) + 1
        occurrence = occurrence_counts[signature_key]
        message["_bridge_occurrence"] = occurrence
        message["_bridge_key"] = stable_hash(
            {
                "signature": signature,
                "occurrence": occurrence,
            }
        )


def message_signature(message: dict[str, Any], *, context_time: str = "") -> dict[str, Any]:
    signature = {
        "sender": message.get("sender"),
        "type": message.get("type"),
        "content": str(message.get("content") or "").strip(),
        "context_time": context_time,
    }
    if not context_time and message.get("id"):
        signature["id"] = message.get("id")
    return signature


def message_key(message: dict[str, Any]) -> str:
    if message.get("_bridge_key"):
        return str(message["_bridge_key"])
    return stable_hash(message_signature(message))


def message_fingerprint(message: dict[str, Any]) -> str:
    context_time = str(message.get("_bridge_context_time") or message.get("time") or "")
    payload = {
        "sender": message.get("sender"),
        "type": message.get("type"),
        "content": str(message.get("content") or "").strip(),
        "context_time": context_time,
        "occurrence": int(message.get("_bridge_occurrence") or 1),
    }
    if not context_time and message.get("id"):
        payload["id"] = message.get("id")
    return stable_hash(payload)


def stable_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def remember_processed_key(config: dict[str, Any], state: dict[str, Any], key: str) -> None:
    limit = int((config.get("dedupe") or {}).get("history_limit") or 200)
    keys = [item for item in state.get("processed_message_keys", []) if item != key]
    keys.append(key)
    state["processed_message_keys"] = keys[-limit:]


def remember_processed_message(config: dict[str, Any], state: dict[str, Any], message: dict[str, Any], *, key: str | None = None) -> None:
    remember_processed_key(config, state, key or message_key(message))
    fingerprint = message_fingerprint(message)
    limit = int((config.get("dedupe") or {}).get("history_limit") or 200)
    fingerprints = [item for item in state.get("processed_message_fingerprints", []) if item != fingerprint]
    fingerprints.append(fingerprint)
    state["processed_message_fingerprints"] = fingerprints[-limit:]


def consume_stop_requested(config: dict[str, Any]) -> bool:
    state = load_state(config)
    if not state.get("stop_requested"):
        return False
    state["stop_requested"] = False
    save_state(config, state)
    return True


def append_run(state: dict[str, Any], prompt: str, codex_result: dict[str, Any]) -> None:
    runs = list(state.get("runs", []) or [])
    runs.append(
        {
            "at": datetime.now().isoformat(timespec="seconds"),
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "thread_id": codex_result.get("threadId"),
            "turn_id": codex_result.get("turnId"),
            "status": codex_result.get("status"),
        }
    )
    state["runs"] = runs[-50:]
    state["last_assistant_text"] = codex_result.get("assistantText", "")


def format_task_final_reply(config: dict[str, Any], run_id: str, result: dict[str, Any], text: str) -> str:
    lines = [
        f"run_id: {run_id}",
        "status: done",
        f"final_token: {task_final_verify_token(run_id)}",
    ]
    thread_id = result.get("thread_id") or result.get("threadId")
    turn_id = result.get("turn_id") or result.get("turnId")
    if thread_id:
        lines.append(f"thread_id: {thread_id}")
    if turn_id:
        lines.append(f"turn_id: {turn_id}")
    lines.append(f"monitor: {monitor_url(config)}")
    clean = (text or "").strip()
    if clean:
        lines.extend(["", clean])
    return format_wechat_reply(config, "\n".join(lines), max_chars=final_reply_max_chars(config))


def task_final_verify_token(run_id: str) -> str:
    return f"final:{run_id}"


def monitor_url(config: dict[str, Any]) -> str:
    monitor = dict(config.get("monitor") or {})
    host = str(monitor.get("host") or "127.0.0.1")
    port = int(monitor.get("port") or 17911)
    return f"http://{host}:{port}"


def final_reply_max_chars(config: dict[str, Any]) -> int:
    wechat_config = dict(config.get("wechat") or {})
    return int(wechat_config.get("max_final_reply_chars") or wechat_config.get("max_reply_chars") or 3500)


def format_wechat_reply(config: dict[str, Any], text: str, *, max_chars: int | None = None) -> str:
    wechat_config = dict(config.get("wechat") or {})
    prefix = str(wechat_config.get("reply_prefix") or "")
    resolved_max_chars = int(max_chars if max_chars is not None else wechat_config.get("max_reply_chars") or 3500)
    clean = (text or "").strip()
    if resolved_max_chars > 0 and len(prefix + clean) > resolved_max_chars:
        available = max(0, resolved_max_chars - len(prefix) - len("\n[truncated]"))
        clean = clean[:available].rstrip() + "\n[truncated]"
    return prefix + clean if clean else ""


def default_thread_title(config: dict[str, Any]) -> str:
    codex = dict(config.get("codex") or {})
    prefix = str(codex.get("thread_title_prefix") or "WECHAT_CODEX_TASK")
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def compact_codex_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "status",
        "threadId",
        "turnId",
        "assistantText",
        "fake",
        "listHit",
        "error",
        "appServer",
        "artifacts",
        "desktopIndexSync",
    ]
    return {key: result.get(key) for key in keys if key in result}


def compact_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender": message.get("sender"),
        "content": message.get("content"),
        "time": message.get("time"),
        "id": message.get("id"),
    }


def print_json(payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write(text.encode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
