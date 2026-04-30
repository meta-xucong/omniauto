"""Persistent task ledger for the Codex WeChat bridge."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from codex_app_server import resolve_path


DEFAULT_LEDGER_PATH = "runtime/apps/codex_wechat_bridge/state/task_ledger.json"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ledger_path(config: dict[str, Any]) -> Path:
    return resolve_path(config.get("ledger_path", DEFAULT_LEDGER_PATH))


def load_ledger(config: dict[str, Any]) -> dict[str, Any]:
    path = ledger_path(config)
    if not path.exists():
        return {"version": 1, "runs": []}
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "runs": [], "load_error": f"invalid json: {path}"}
    ledger.setdefault("version", 1)
    ledger.setdefault("runs", [])
    return ledger


def save_ledger(config: dict[str, Any], ledger: dict[str, Any]) -> None:
    path = ledger_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = now_iso()
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def make_run_id(message_key: str | None = None) -> str:
    suffix = (message_key or "manual")[:8]
    return f"cw_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"


def create_run(
    config: dict[str, Any],
    *,
    message_key: str,
    message: dict[str, Any],
    prompt: str,
    command: str,
    active_thread_id: str | None,
) -> dict[str, Any]:
    ledger = load_ledger(config)
    run_id = unique_run_id(ledger, make_run_id(message_key))
    created_at = now_iso()
    run = {
        "run_id": run_id,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "source": "wechat",
        "command": command,
        "message_key": message_key,
        "message": compact_message(message),
        "prompt": prompt,
        "prompt_preview": preview(prompt, 240),
        "requested_thread_id": active_thread_id,
        "thread_id": active_thread_id,
        "turn_id": None,
        "wechat_receipt_sent": False,
        "wechat_final_sent": False,
        "events": [
            {
                "at": created_at,
                "status": "queued",
                "note": "Task accepted from WeChat.",
            }
        ],
    }
    runs = list(ledger.get("runs") or [])
    runs.append(run)
    ledger["runs"] = trim_runs(config, runs)
    save_ledger(config, ledger)
    return run


def update_run(
    config: dict[str, Any],
    run_id: str,
    *,
    status: str | None = None,
    note: str | None = None,
    **fields: Any,
) -> dict[str, Any] | None:
    ledger = load_ledger(config)
    updated = None
    for run in ledger.get("runs") or []:
        if run.get("run_id") != run_id:
            continue
        if status:
            run["status"] = status
        for key, value in fields.items():
            if value is not None:
                run[key] = value
        run["updated_at"] = now_iso()
        if status or note:
            events = list(run.get("events") or [])
            events.append(
                {
                    "at": run["updated_at"],
                    "status": status or run.get("status"),
                    "note": note,
                }
            )
            run["events"] = events[-30:]
        updated = run
        break
    if updated is not None:
        save_ledger(config, ledger)
    return updated


def latest_run(config: dict[str, Any]) -> dict[str, Any] | None:
    runs = list(load_ledger(config).get("runs") or [])
    return runs[-1] if runs else None


def build_monitor_snapshot(config: dict[str, Any], bridge_state: dict[str, Any] | None = None) -> dict[str, Any]:
    ledger = load_ledger(config)
    runs = list(ledger.get("runs") or [])
    active_thread_id = (bridge_state or {}).get("active_thread_id")
    compact_runs = [compact_monitor_run(run) for run in runs[-50:]]
    return {
        "ok": True,
        "generated_at": now_iso(),
        "paths": {
            "ledger": str(ledger_path(config)),
            "state": str(resolve_path(config.get("state_path", "runtime/apps/codex_wechat_bridge/state/bridge_state.json"))),
        },
        "active_thread_id": active_thread_id,
        "pending_reply": (bridge_state or {}).get("pending_reply"),
        "last_poll": (bridge_state or {}).get("last_poll"),
        "latest_run": compact_monitor_run(runs[-1]) if runs else None,
        "runs": list(reversed(compact_runs)),
        "status_counts": status_counts(runs),
        "desktop_index": desktop_index_snapshot(active_thread_id),
    }


def format_status_reply(config: dict[str, Any], active_thread_id: str | None) -> str:
    run = latest_run(config)
    monitor = dict(config.get("monitor") or {})
    host = str(monitor.get("host") or "127.0.0.1")
    port = int(monitor.get("port") or 17911)
    lines = [f"active_thread_id: {active_thread_id or '(none)'}"]
    if run:
        lines.extend(
            [
                f"latest_run: {run.get('run_id')}",
                f"status: {run.get('status')}",
                f"thread_id: {run.get('thread_id') or '(none)'}",
                f"turn_id: {run.get('turn_id') or '(none)'}",
            ]
        )
    else:
        lines.append("latest_run: (none)")
    lines.append(f"monitor: http://{host}:{port}")
    return "\n".join(lines)


def desktop_index_snapshot(thread_id: str | None) -> dict[str, Any]:
    if not thread_id:
        return {"ok": True, "thread_id": None}
    codex_home = Path.home() / ".codex"
    snapshot: dict[str, Any] = {"ok": True, "thread_id": thread_id}
    index_path = codex_home / "session_index.jsonl"
    if index_path.exists():
        try:
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if thread_id in line:
                    snapshot["session_index"] = json.loads(line)
                    break
        except Exception as exc:  # pragma: no cover - depends on local Codex files.
            snapshot["ok"] = False
            snapshot["session_index_error"] = repr(exc)
    return snapshot


def status_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for run in runs:
        status = str(run.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def compact_monitor_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "source": run.get("source"),
        "command": run.get("command"),
        "prompt_preview": run.get("prompt_preview"),
        "thread_id": run.get("thread_id"),
        "turn_id": run.get("turn_id"),
        "requested_thread_id": run.get("requested_thread_id"),
        "wechat_receipt_sent": run.get("wechat_receipt_sent"),
        "wechat_final_sent": run.get("wechat_final_sent"),
        "wechat_final_send_state": run.get("wechat_final_send_state"),
        "assistant_preview": preview(str(run.get("assistant_preview") or ""), 500),
        "events": list(run.get("events") or [])[-8:],
    }


def trim_runs(config: dict[str, Any], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = int((config.get("ledger") or {}).get("history_limit") or 200)
    return runs[-max(1, limit) :]


def unique_run_id(ledger: dict[str, Any], run_id: str) -> str:
    existing = {str(run.get("run_id")) for run in ledger.get("runs") or []}
    if run_id not in existing:
        return run_id
    index = 2
    while f"{run_id}_{index}" in existing:
        index += 1
    return f"{run_id}_{index}"


def compact_message(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender": message.get("sender"),
        "content": message.get("content"),
        "time": message.get("time"),
        "id": message.get("id"),
    }


def preview(text: str, max_chars: int) -> str:
    clean = (text or "").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max(0, max_chars - 12)].rstrip() + " [truncated]"
