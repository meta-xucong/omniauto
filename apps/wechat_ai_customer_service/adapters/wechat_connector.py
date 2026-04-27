"""Connector wrapper for the wxauto4 WeChat sidecar.

The connector is the stable boundary the workflow layer should use. It keeps
WeChat-specific Python 3.12/wxauto4 details outside the OmniAuto Python 3.13
process and returns plain dictionaries that are easy to validate and persist.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
SIDECAR_PYTHON = ROOT / "runtime/tool_envs/wxauto4-py312/Scripts/python.exe"
SIDECAR_SCRIPT = ROOT / "apps/wechat_ai_customer_service/adapters/wxauto4_sidecar.py"
WECHAT_EXE = Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe")
FILE_TRANSFER_ASSISTANT = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93, 0x52A9, 0x624B])


class WeChatConnectorError(RuntimeError):
    """Raised when the connector cannot complete a guarded operation."""


@dataclass(frozen=True)
class WeChatConnector:
    sidecar_python: Path = SIDECAR_PYTHON
    sidecar_script: Path = SIDECAR_SCRIPT
    root: Path = ROOT
    timeout_seconds: int = 120

    def status(self) -> dict[str, Any]:
        return self.call_sidecar(["status"], allow_failure=True)

    def wait_online(self, seconds: int = 60) -> dict[str, Any]:
        deadline = time.time() + max(1, seconds)
        latest: dict[str, Any] = {}
        while time.time() <= deadline:
            latest = self.status()
            if latest.get("ok") and latest.get("online"):
                return latest
            time.sleep(3)
        return latest

    def list_sessions(self) -> dict[str, Any]:
        self.require_online()
        return self.call_sidecar(["sessions"])

    def get_messages(self, target: str, exact: bool = True) -> dict[str, Any]:
        self.require_online()
        args = ["messages", "--target", target]
        if exact:
            args.append("--exact")
        return self.call_sidecar(args)

    def send_text(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        if not target:
            raise WeChatConnectorError("target is required")
        if not text:
            raise WeChatConnectorError("text is required")
        self.require_online()
        args = ["send", "--target", target, "--text", text]
        if exact:
            args.append("--exact")
        return self.call_sidecar(args)

    def send_text_and_verify(self, target: str, text: str, exact: bool = True) -> dict[str, Any]:
        send_result = self.send_text(target, text, exact=exact)
        if not send_result.get("ok"):
            return {"ok": False, "send": send_result, "verified": False}
        messages: dict[str, Any] = {}
        verified = False
        for attempt in range(6):
            if attempt:
                time.sleep(1)
            messages = self.get_messages(target, exact=exact)
            verified = any(
                item.get("sender") == "self" and item.get("content") == text
                for item in messages.get("messages", []) or []
            )
            if verified:
                break
        return {
            "ok": bool(verified),
            "send": send_result,
            "messages": messages,
            "verified": bool(verified),
        }

    def require_online(self) -> dict[str, Any]:
        status = self.status()
        if not status.get("ok") or not status.get("online"):
            raise WeChatConnectorError(
                "WeChat is not online; open and log in to the main window first. "
                f"status={status!r}"
            )
        return status

    def ensure_wechat_started(self) -> None:
        """Explicit startup helper. Normal workflows should not call this by default."""
        if any_weixin_process():
            return
        if not WECHAT_EXE.exists():
            raise FileNotFoundError(str(WECHAT_EXE))
        subprocess.Popen([str(WECHAT_EXE)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(8)

    def call_sidecar(self, args: list[str], allow_failure: bool = False) -> dict[str, Any]:
        if not self.sidecar_python.exists():
            raise FileNotFoundError(str(self.sidecar_python))
        if not self.sidecar_script.exists():
            raise FileNotFoundError(str(self.sidecar_script))

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        completed = subprocess.run(
            [str(self.sidecar_python), str(self.sidecar_script), *args],
            cwd=str(self.root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout_seconds,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            payload = {
                "ok": False,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        if completed.returncode and not allow_failure and payload.get("ok") is not True:
            payload.setdefault("returncode", completed.returncode)
        return payload


def any_weixin_process() -> bool:
    for proc in psutil.process_iter(["name"]):
        try:
            if str(proc.info.get("name") or "").lower() == "weixin.exe":
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False
