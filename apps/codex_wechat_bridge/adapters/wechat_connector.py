"""WeChat connector for the Codex bridge.

This adapter is intentionally local to `codex_wechat_bridge` so the bridge can
evolve independently from the WeChat AI customer-service app.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil


ROOT = Path(__file__).resolve().parents[3]
SIDECAR_PYTHON = ROOT / "runtime/tool_envs/wxauto4-py312/Scripts/python.exe"
SIDECAR_SCRIPT = ROOT / "apps/codex_wechat_bridge/adapters/wxauto4_sidecar.py"
SIDECAR_LOCK = ROOT / "runtime/apps/codex_wechat_bridge/state/wxauto4_sidecar.lock"
WECHAT_EXE = Path(r"C:\Program Files (x86)\Tencent\Weixin\Weixin.exe")
FILE_TRANSFER_ASSISTANT = "".join(chr(c) for c in [0x6587, 0x4EF6, 0x4F20, 0x8F93, 0x52A9, 0x624B])


class WeChatConnectorError(RuntimeError):
    """Raised when WeChat cannot complete a guarded operation."""


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

    def send_text_and_verify(
        self,
        target: str,
        text: str,
        exact: bool = True,
        verify_token: str | None = None,
        verify_attempts: int = 12,
        verify_interval_seconds: float = 1.0,
        initial_delay_seconds: float = 0.5,
    ) -> dict[str, Any]:
        send_result = self.send_text(target, text, exact=exact)
        if not send_result.get("ok"):
            return {"ok": False, "send": send_result, "verified": False}

        messages: dict[str, Any] = {}
        verified = False
        matched_by = None
        attempts = max(1, int(verify_attempts))
        if initial_delay_seconds > 0:
            time.sleep(initial_delay_seconds)
        for attempt in range(attempts):
            if attempt:
                time.sleep(max(0.1, float(verify_interval_seconds)))
            messages = self.get_messages(target, exact=exact)
            for item in messages.get("messages", []) or []:
                if item.get("sender") != "self":
                    continue
                content = str(item.get("content") or "")
                if content == text:
                    verified = True
                    matched_by = "exact"
                    break
                if verify_token and verify_token in content:
                    verified = True
                    matched_by = "verify_token"
                    break
            if verified:
                break
        return {
            "ok": bool(verified),
            "send": send_result,
            "messages": messages,
            "verified": bool(verified),
            "verify_token": verify_token,
            "matched_by": matched_by,
            "attempts": attempt + 1,
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
        status = self.status()
        if status.get("ok") and status.get("online"):
            return
        raise WeChatConnectorError(
            "Automatic WeChat startup is disabled. Open WeChat, finish login manually, "
            "and keep the main window visible before running the bridge."
        )

    def call_sidecar(self, args: list[str], allow_failure: bool = False) -> dict[str, Any]:
        if not self.sidecar_python.exists():
            raise FileNotFoundError(str(self.sidecar_python))
        if not self.sidecar_script.exists():
            raise FileNotFoundError(str(self.sidecar_script))

        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        with wxauto4_sidecar_lock(timeout_seconds=self.timeout_seconds + 30):
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


@contextmanager
def wxauto4_sidecar_lock(timeout_seconds: int = 150):
    """Serialize wxauto4 access; concurrent attaches can corrupt UI discovery."""
    SIDECAR_LOCK.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        yield
        return

    import msvcrt

    deadline = time.monotonic() + max(1, timeout_seconds)
    SIDECAR_LOCK.touch(exist_ok=True)
    with SIDECAR_LOCK.open("r+b") as handle:
        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for wxauto4 sidecar lock: {SIDECAR_LOCK}")
                time.sleep(0.25)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
