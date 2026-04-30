"""Codex app-server process and RPC helpers for the WeChat bridge."""

from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
NODE_RPC_SCRIPT = APP_ROOT / "workflows" / "codex_app_server_rpc.mjs"


class CodexAppServerError(RuntimeError):
    """Raised when the bridge cannot reach or use Codex app-server."""


@dataclass(frozen=True)
class AppServerInfo:
    endpoint: str
    started: bool
    pid: int | None
    stdout_path: Path | None
    stderr_path: Path | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "started": self.started,
            "pid": self.pid,
            "stdout_path": str(self.stdout_path) if self.stdout_path else None,
            "stderr_path": str(self.stderr_path) if self.stderr_path else None,
        }


def resolve_path(raw: str | Path, *, root: Path = ROOT) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def parse_ws_endpoint(endpoint: str) -> tuple[str, int]:
    parsed = urlparse(endpoint)
    if parsed.scheme != "ws" or not parsed.hostname or not parsed.port:
        raise CodexAppServerError(f"Only ws://HOST:PORT endpoints are supported: {endpoint!r}")
    return parsed.hostname, int(parsed.port)


def is_endpoint_listening(endpoint: str, timeout: float = 0.4) -> bool:
    host, port = parse_ws_endpoint(endpoint)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_endpoint(endpoint: str, timeout_seconds: int = 20) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_endpoint_listening(endpoint):
            return True
        time.sleep(0.25)
    return False


def ensure_app_server(config: dict[str, Any]) -> AppServerInfo:
    codex = dict(config.get("codex") or {})
    endpoint = str(codex.get("endpoint") or "ws://127.0.0.1:17910")
    if is_endpoint_listening(endpoint):
        return AppServerInfo(endpoint=endpoint, started=False, pid=None, stdout_path=None, stderr_path=None)

    if not bool(codex.get("manage_app_server", True)):
        raise CodexAppServerError(f"Codex app-server is not listening at {endpoint}")

    artifact_root = resolve_path(config.get("artifact_root", "runtime/apps/codex_wechat_bridge/test_artifacts"))
    log_dir = artifact_root / f"app_server_{timestamp()}"
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = log_dir / "app-server.out.txt"
    stderr_path = log_dir / "app-server.err.txt"

    model = str(codex.get("model") or "gpt-5.4")
    command = normalize_app_server_command(codex.get("app_server_command"))
    args = [*command, "--listen", endpoint]
    overrides = list(codex.get("config_overrides") or [])
    if not any(str(item).startswith("model=") for item in overrides):
        overrides.append(f'model="{model}"')
    for override in overrides:
        args.extend(["-c", str(override)])

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as stdout:
        with stderr_path.open("w", encoding="utf-8", errors="replace") as stderr:
            proc = subprocess.Popen(
                args,
                cwd=str(ROOT),
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
            )

    if not wait_for_endpoint(endpoint, timeout_seconds=int(codex.get("startup_timeout_seconds") or 30)):
        raise CodexAppServerError(
            f"Started app-server pid={proc.pid}, but {endpoint} did not become ready. "
            f"stderr={stderr_path}"
        )

    return AppServerInfo(
        endpoint=endpoint,
        started=True,
        pid=proc.pid,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def normalize_app_server_command(raw_command: Any) -> list[str]:
    if raw_command:
        command = [str(item) for item in raw_command]
    else:
        command = ["codex", "app-server"]
    if not command:
        raise CodexAppServerError("app_server_command cannot be empty")
    if command[0].lower() == "codex":
        command[0] = find_codex_executable()
    return command


def find_codex_executable() -> str:
    candidates = ["codex.cmd", "codex.exe", "codex"]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "codex"


def send_prompt(config: dict[str, Any], prompt: str, *, thread_id: str | None = None, title: str | None = None) -> dict[str, Any]:
    codex = dict(config.get("codex") or {})
    if codex.get("mode") == "fake":
        fake_thread = thread_id or str(codex.get("fake_thread_id") or "fake-codex-thread")
        template = str(codex.get("fake_response_template") or "FAKE_CODEX_RESPONSE: {prompt}")
        return {
            "status": "ok",
            "threadId": fake_thread,
            "turnId": f"fake-turn-{int(time.time() * 1000)}",
            "assistantText": template.format(prompt=prompt, thread_id=fake_thread, title=title or ""),
            "fake": True,
            "listHit": True,
        }

    server = ensure_app_server(config)
    artifact_root = resolve_path(config.get("artifact_root", "runtime/apps/codex_wechat_bridge/test_artifacts"))
    run_dir = artifact_root / f"codex_rpc_{timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "request.json"
    summary_path = run_dir / "summary.json"
    events_path = run_dir / "events.jsonl"

    request = {
        "endpoint": server.endpoint,
        "thread_id": thread_id,
        "title": title,
        "prompt": prompt,
        "model": codex.get("model") or "gpt-5.4",
        "cwd": str(resolve_path(codex.get("cwd") or ROOT)),
        "approval_policy": codex.get("approval_policy") or "never",
        "sandbox": codex.get("sandbox") or "read-only",
        "service_name": codex.get("service_name") or "codex-wechat-bridge",
        "timeout_ms": int(codex.get("timeout_ms") or 180000),
    }
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    node_command = str(codex.get("node_command") or "node")
    completed = subprocess.run(
        [node_command, str(NODE_RPC_SCRIPT), str(request_path), str(summary_path), str(events_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(codex.get("timeout_ms") or 180000) + 45,
    )

    summary: dict[str, Any]
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "status": "error",
            "error": "RPC helper did not write summary.json",
        }
    summary["appServer"] = server.to_dict()
    summary["artifacts"] = {
        "run_dir": str(run_dir),
        "request_path": str(request_path),
        "summary_path": str(summary_path),
        "events_path": str(events_path),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0 and summary.get("status") == "ok":
        summary["status"] = "error"
        summary["error"] = f"RPC helper exited {completed.returncode}"
    if summary.get("status") == "ok":
        summary["desktopIndexSync"] = sync_desktop_thread_index(config, summary, requested_title=title)
    return summary


def list_threads(config: dict[str, Any], *, limit: int = 8, archived: bool = False) -> dict[str, Any]:
    codex = dict(config.get("codex") or {})
    if codex.get("mode") == "fake":
        fake_thread = str(codex.get("fake_thread_id") or "fake-codex-thread")
        return {
            "status": "ok",
            "threads": [
                {
                    "id": fake_thread,
                    "name": "Fake Codex Thread",
                    "preview": "Fake thread for offline checks",
                    "updatedAt": int(time.time()),
                    "status": {"type": "idle"},
                    "source": "fake",
                }
            ],
            "fake": True,
        }

    server = ensure_app_server(config)
    artifact_root = resolve_path(config.get("artifact_root", "runtime/apps/codex_wechat_bridge/test_artifacts"))
    run_dir = artifact_root / f"codex_rpc_list_{timestamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "request.json"
    summary_path = run_dir / "summary.json"
    events_path = run_dir / "events.jsonl"

    request = {
        "action": "list_threads",
        "endpoint": server.endpoint,
        "limit": max(1, int(limit)),
        "archived": bool(archived),
        "timeout_ms": min(int(codex.get("timeout_ms") or 180000), 60000),
    }
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")

    node_command = str(codex.get("node_command") or "node")
    completed = subprocess.run(
        [node_command, str(NODE_RPC_SCRIPT), str(request_path), str(summary_path), str(events_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=int(request["timeout_ms"]) + 30,
    )

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "status": "error",
            "error": "RPC helper did not write summary.json",
        }
    summary["appServer"] = server.to_dict()
    summary["artifacts"] = {
        "run_dir": str(run_dir),
        "request_path": str(request_path),
        "summary_path": str(summary_path),
        "events_path": str(events_path),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "returncode": completed.returncode,
    }
    if completed.returncode != 0 and summary.get("status") == "ok":
        summary["status"] = "error"
        summary["error"] = f"RPC helper exited {completed.returncode}"
    return summary


def sync_desktop_thread_index(
    config: dict[str, Any],
    summary: dict[str, Any],
    *,
    requested_title: str | None,
) -> dict[str, Any]:
    codex = dict(config.get("codex") or {})
    if codex.get("sync_desktop_index") is False:
        return {"ok": True, "skipped": True, "reason": "disabled"}

    thread_id = str(summary.get("threadId") or "").strip()
    if not thread_id:
        return {"ok": False, "error": "missing threadId"}

    read_thread = ((summary.get("readResult") or {}).get("thread") or {})
    thread_title = str(read_thread.get("name") or requested_title or "").strip()
    if not thread_title:
        thread_title = str(read_thread.get("preview") or "").strip()

    finished_at = str(summary.get("finishedAt") or datetime.now(timezone.utc).isoformat())
    updated_at_ms = iso_to_epoch_ms(finished_at)
    updated_at_seconds = updated_at_ms // 1000

    codex_home = Path.home() / ".codex"
    result: dict[str, Any] = {
        "ok": True,
        "thread_id": thread_id,
        "thread_title": thread_title,
        "updated_at": finished_at,
    }

    db_path = codex_home / "state_5.sqlite"
    if db_path.exists():
        try:
            with sqlite3.connect(str(db_path), timeout=5) as connection:
                if thread_title:
                    cursor = connection.execute(
                        """
                        UPDATE threads
                        SET title = ?,
                            updated_at = max(updated_at, ?),
                            updated_at_ms = max(updated_at_ms, ?)
                        WHERE id = ?
                        """,
                        (thread_title, updated_at_seconds, updated_at_ms, thread_id),
                    )
                else:
                    cursor = connection.execute(
                        """
                        UPDATE threads
                        SET updated_at = max(updated_at, ?),
                            updated_at_ms = max(updated_at_ms, ?)
                        WHERE id = ?
                        """,
                        (updated_at_seconds, updated_at_ms, thread_id),
                    )
                result["sqlite_rows"] = cursor.rowcount
        except Exception as exc:  # pragma: no cover - depends on Codex Desktop state.
            result["ok"] = False
            result["sqlite_error"] = repr(exc)

    index_path = codex_home / "session_index.jsonl"
    if index_path.exists() and thread_title:
        try:
            rows = []
            replaced = False
            for line in index_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    rows.append(line)
                    continue
                if row.get("id") == thread_id:
                    row["thread_name"] = thread_title
                    row["updated_at"] = finished_at
                    replaced = True
                rows.append(json.dumps(row, ensure_ascii=False) if isinstance(row, dict) else line)
            if not replaced:
                rows.append(
                    json.dumps(
                        {"id": thread_id, "thread_name": thread_title, "updated_at": finished_at},
                        ensure_ascii=False,
                    )
                )
            index_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
            result["session_index_replaced"] = replaced
        except Exception as exc:  # pragma: no cover - depends on Codex Desktop state.
            result["ok"] = False
            result["session_index_error"] = repr(exc)

    return result


def iso_to_epoch_ms(value: str) -> int:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return int(parsed.timestamp() * 1000)
