"""Managed loop for the local WeChat customer-service listener."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
for path in (PROJECT_ROOT, APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from apps.wechat_ai_customer_service.admin_backend.services.customer_service_runtime import (  # noqa: E402
    runtime_log_path,
    summarize_listener_result,
    write_runtime_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=3.0)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    tenant_id = str(args.tenant_id).strip()
    config_path = args.config.resolve()
    env = dict(os.environ)
    env["WECHAT_KNOWLEDGE_TENANT"] = tenant_id
    log_path = runtime_log_path(tenant_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    workflow = APP_ROOT / "workflows" / "listen_and_reply.py"

    append_log(log_path, {"event": "managed_listener_start", "tenant_id": tenant_id, "config": str(config_path)})
    write_runtime_status("idle", "自动客服监听已启动，等待微信消息。", tenant_id=tenant_id)
    while True:
        command = [sys.executable, str(workflow), "--config", str(config_path), "--once"]
        if args.send:
            command.append("--send")
        write_runtime_status("thinking", "正在读取微信消息并准备回复。", tenant_id=tenant_id)
        started = time.time()
        result = run_once(command, env=env, cwd=PROJECT_ROOT, log_path=log_path)
        duration = round(time.time() - started, 2)
        summary = summarize_listener_result(result) if isinstance(result, dict) else {}
        message = status_message_from_result(result, duration)
        write_runtime_status(
            "idle",
            message,
            tenant_id=tenant_id,
            last_run_seconds=duration,
            **summary,
        )
        time.sleep(max(0.5, float(args.interval_seconds)))


def run_once(command: list[str], *, env: dict[str, str], cwd: Path, log_path: Path) -> dict:
    process = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    payload = parse_last_json(stdout)
    append_log(
        log_path,
        {
            "event": "listen_once_exit",
            "returncode": process.returncode,
            "stdout_tail": stdout[-3000:],
            "stderr_tail": stderr[-3000:],
        },
    )
    if payload:
        payload.setdefault("ok", process.returncode == 0)
        return payload
    return {"ok": process.returncode == 0, "error": stderr[-1000:] or stdout[-1000:] or f"exit={process.returncode}", "events": []}


def parse_last_json(text: str) -> dict:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload
    for line in reversed([item.strip() for item in text.splitlines() if item.strip()]):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    start = text.rfind("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def status_message_from_result(result: dict, duration: float) -> str:
    if not isinstance(result, dict) or result.get("ok") is False:
        return f"本轮处理没有成功，已等待下一轮自动重试。耗时 {duration} 秒。"
    events = [item for item in result.get("events", []) or [] if isinstance(item, dict)]
    if not events:
        return f"本轮未发现需要回复的新消息。耗时 {duration} 秒。"
    actions = {str(item.get("action") or "") for item in events}
    if "sent" in actions or "handoff_sent" in actions:
        return f"本轮已处理并发送回复。耗时 {duration} 秒。"
    if "skipped" in actions and actions <= {"skipped"}:
        return f"本轮没有可自动回复的新消息。耗时 {duration} 秒。"
    return f"本轮微信消息检查完成。耗时 {duration} 秒。"


def append_log(path: Path, payload: dict) -> None:
    record = {"created_at": datetime.now().isoformat(timespec="seconds"), **payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
