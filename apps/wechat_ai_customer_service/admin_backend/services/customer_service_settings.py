"""Tenant-local settings for the WeChat customer-service workbench."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import tenant_runtime_root


DEFAULT_SETTINGS = {
    "enabled": False,
    "reply_mode": "manual_assist",
    "record_messages": True,
    "auto_learn": True,
    "use_llm": True,
    "rag_enabled": True,
    "data_capture_enabled": True,
    "handoff_enabled": True,
    "operator_alert_enabled": True,
}

REPLY_MODES = {
    "record_only": "只记录不回复",
    "manual_assist": "只给建议，人工发送",
    "guarded_auto": "谨慎自动回复",
    "full_auto": "全自动回复",
}


class CustomerServiceSettings:
    def __init__(self, *, tenant_id: str | None = None) -> None:
        self.tenant_id = tenant_id

    @property
    def settings_path(self) -> Path:
        return tenant_runtime_root(self.tenant_id) / "customer_service" / "settings.json"

    def get(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.settings_path.exists():
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    payload = raw
            except json.JSONDecodeError:
                payload = {}
        settings = {**DEFAULT_SETTINGS, **{key: value for key, value in payload.items() if key in DEFAULT_SETTINGS}}
        if settings["reply_mode"] not in REPLY_MODES:
            settings["reply_mode"] = DEFAULT_SETTINGS["reply_mode"]
        return settings

    def save(self, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {key: value for key, value in (patch or {}).items() if key in DEFAULT_SETTINGS}
        settings = {**self.get(), **allowed}
        if settings["reply_mode"] not in REPLY_MODES:
            settings["reply_mode"] = DEFAULT_SETTINGS["reply_mode"]
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.settings_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.settings_path)
        return settings

    def summary(self) -> dict[str, Any]:
        settings = self.get()
        return {
            "settings": settings,
            "reply_modes": [{"id": key, "label": label} for key, label in REPLY_MODES.items()],
            "status": self.status_text(settings),
        }

    @staticmethod
    def status_text(settings: dict[str, Any]) -> str:
        if not settings.get("enabled"):
            return "已关闭，不会自动回复客户。"
        mode = str(settings.get("reply_mode") or "")
        if mode == "record_only":
            return "只记录消息，不自动回复。"
        if mode == "manual_assist":
            return "会生成回复建议，等待人工发送。"
        if mode == "guarded_auto":
            return "只在命中可靠知识时谨慎自动回复。"
        if mode == "full_auto":
            return "会按知识库自动回复，风险问题仍转人工。"
        return "已启用。"
