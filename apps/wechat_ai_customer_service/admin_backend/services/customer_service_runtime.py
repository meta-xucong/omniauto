"""Runtime process control for the local WeChat customer-service listener."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_runtime_root


PROJECT_ROOT = Path(__file__).resolve().parents[4]
APP_ROOT = PROJECT_ROOT / "apps" / "wechat_ai_customer_service"
DEFAULT_CHEJIN_TENANT_ID = "jiangsu_chejin_usedcar_customer_20260501"
DEFAULT_CHEJIN_CONFIG = APP_ROOT / "configs" / "jiangsu_chejin_xucong_live.example.json"

RUNTIME_STATES = {"idle", "thinking", "stopped"}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def runtime_dir(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "customer_service"


def runtime_status_path(tenant_id: str | None = None) -> Path:
    return runtime_dir(tenant_id) / "runtime_status.json"


def runtime_pid_path(tenant_id: str | None = None) -> Path:
    return runtime_dir(tenant_id) / "listener.pid.json"


def runtime_log_path(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "logs" / "customer_service_managed_listener.log"


def write_runtime_status(
    state: str,
    message: str = "",
    *,
    tenant_id: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Write the compact status consumed by the floating console widget."""
    normalized = state if state in RUNTIME_STATES else "idle"
    payload: dict[str, Any] = {
        "ok": True,
        "state": normalized,
        "message": message or status_default_message(normalized),
        "updated_at": now_iso(),
        "tenant_id": active_tenant_id(tenant_id),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    path = runtime_status_path(tenant_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)
    return payload


def read_runtime_status(tenant_id: str | None = None) -> dict[str, Any]:
    path = runtime_status_path(tenant_id)
    if not path.exists():
        return {
            "ok": True,
            "state": "stopped",
            "message": status_default_message("stopped"),
            "updated_at": "",
            "tenant_id": active_tenant_id(tenant_id),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "ok": False,
            "state": "stopped",
            "message": "状态文件读取失败，请重新启动客服监听。",
            "updated_at": "",
            "tenant_id": active_tenant_id(tenant_id),
        }
    if not isinstance(payload, dict):
        payload = {}
    state = str(payload.get("state") or "stopped")
    if state not in RUNTIME_STATES:
        state = "stopped"
    return {
        **payload,
        "ok": payload.get("ok", True) is not False,
        "state": state,
        "message": str(payload.get("message") or status_default_message(state)),
        "tenant_id": str(payload.get("tenant_id") or active_tenant_id(tenant_id)),
    }


def status_default_message(state: str) -> str:
    return {
        "idle": "自动客服正在运行，当前没有正在处理的消息。",
        "thinking": "自动客服正在读取微信消息或调用大模型。",
        "stopped": "自动客服监听已停止。",
    }.get(state, "自动客服状态未知。")


def summarize_listener_result(result: dict[str, Any]) -> dict[str, Any]:
    events = [item for item in result.get("events", []) or [] if isinstance(item, dict)]
    last_event = events[-1] if events else {}
    synthesis = last_event.get("llm_reply_synthesis") if isinstance(last_event.get("llm_reply_synthesis"), dict) else {}
    rag = last_event.get("rag_reply") if isinstance(last_event.get("rag_reply"), dict) else {}
    evidence_summary = synthesis.get("evidence_summary") if isinstance(synthesis.get("evidence_summary"), dict) else {}
    return {
        "last_action": last_event.get("action"),
        "last_target": last_event.get("target"),
        "last_reason": last_event.get("reason") or synthesis.get("reason") or rag.get("reason"),
        "last_reply_preview": str(((last_event.get("decision") or {}).get("reply_text") if isinstance(last_event.get("decision"), dict) else "") or "")[:180],
        "model_tier": synthesis.get("model_tier"),
        "model": synthesis.get("model"),
        "rag_hit_count": evidence_summary.get("rag_hit_count"),
        "structured_evidence_count": evidence_summary.get("structured_evidence_count"),
    }


class CustomerServiceRuntime:
    """Start/stop/status wrapper for one tenant's managed WeChat listener."""

    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)

    def status(self) -> dict[str, Any]:
        pid_record = self._read_pid_record()
        running = self._pid_alive(int(pid_record.get("pid") or 0))
        status = read_runtime_status(self.tenant_id)
        status.update(
            {
                "running": running,
                "pid": int(pid_record.get("pid") or 0) if running else None,
                "started_at": pid_record.get("started_at") if running else "",
                "config_path": str(pid_record.get("config_path") or self._config_path_or_empty()),
                "log_path": str(runtime_log_path(self.tenant_id)),
            }
        )
        if not running:
            status["state"] = "stopped"
            status["message"] = status_default_message("stopped")
        return status

    def start(self) -> dict[str, Any]:
        current = self.status()
        if current.get("running"):
            return {"ok": True, "message": "自动客服已经在运行。", "item": current}
        try:
            config_path = self._resolve_config_path()
        except FileNotFoundError as exc:
            write_runtime_status("stopped", str(exc), tenant_id=self.tenant_id)
            return {"ok": False, "message": str(exc), "item": self.status()}
        script_path = APP_ROOT / "scripts" / "run_customer_service_listener.py"
        if not script_path.exists():
            return {"ok": False, "message": f"缺少监听脚本：{script_path}", "item": current}
        log_path = runtime_log_path(self.tenant_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["WECHAT_KNOWLEDGE_TENANT"] = self.tenant_id
        write_runtime_status("thinking", "正在启动微信自动客服监听。", tenant_id=self.tenant_id)
        creationflags = 0
        if os.name == "nt":
            creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            [
                str(self._python_executable()),
                str(script_path),
                "--tenant-id",
                self.tenant_id,
                "--config",
                str(config_path),
                "--interval-seconds",
                "3",
                "--send",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._write_pid_record(
            {
                "pid": proc.pid,
                "tenant_id": self.tenant_id,
                "config_path": str(config_path),
                "started_at": now_iso(),
                "log_path": str(log_path),
            }
        )
        time.sleep(0.8)
        return {"ok": True, "message": "自动客服监听已启动。", "item": self.status()}

    def stop(self) -> dict[str, Any]:
        pid_record = self._read_pid_record()
        pid = int(pid_record.get("pid") or 0)
        if pid and self._pid_alive(pid):
            self._terminate_tree(pid)
        write_runtime_status("stopped", "自动客服监听已手动停止。", tenant_id=self.tenant_id)
        self._clear_pid_record()
        return {"ok": True, "message": "自动客服监听已停止。", "item": self.status()}

    def _config_path_or_empty(self) -> str:
        try:
            return str(self._resolve_config_path())
        except FileNotFoundError:
            return ""

    def _resolve_config_path(self) -> Path:
        candidates = [
            runtime_dir(self.tenant_id) / "listener_config.json",
            APP_ROOT / "configs" / f"{self.tenant_id}.json",
            APP_ROOT / "configs" / f"{self.tenant_id}.example.json",
        ]
        if self.tenant_id == DEFAULT_CHEJIN_TENANT_ID:
            candidates.append(DEFAULT_CHEJIN_CONFIG)
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(
            "当前客户账号还没有配置微信监听目标。请先为该账号创建 listener_config.json，或在后台为该账号完成微信自动客服配置。"
        )

    def _python_executable(self) -> Path:
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists():
            return venv_python
        return Path(sys.executable)

    def _read_pid_record(self) -> dict[str, Any]:
        path = runtime_pid_path(self.tenant_id)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_pid_record(self, payload: dict[str, Any]) -> None:
        path = runtime_pid_path(self.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _clear_pid_record(self) -> None:
        try:
            runtime_pid_path(self.tenant_id).unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @staticmethod
    def _terminate_tree(pid: int) -> None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        try:
            os.kill(pid, 15)
        except OSError:
            pass
