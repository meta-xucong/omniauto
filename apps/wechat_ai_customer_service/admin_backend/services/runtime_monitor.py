"""Runtime heartbeat and readiness summary."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config

from .handoff_store import HandoffStore
from .work_queue import WorkQueueService


PROJECT_ROOT = Path(__file__).resolve().parents[4]
HEARTBEAT_PATH = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "runtime_heartbeats.json"


class RuntimeMonitor:
    def __init__(self, tenant_id: str | None = None, path: Path | None = None) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.path = path or HEARTBEAT_PATH

    def heartbeat(self, component_id: str, *, status: str = "ok", message: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        db = self.db()
        if db:
            return db.upsert_heartbeat(self.tenant_id, component_id=component_id, status=status, message=message, payload=payload or {})
        items = [item for item in self.read_items() if item.get("component_id") != component_id or item.get("tenant_id") != self.tenant_id]
        item = {
            "tenant_id": self.tenant_id,
            "component_id": component_id,
            "status": status or "ok",
            "message": message or "",
            "payload": payload or {},
            "last_seen_at": now(),
        }
        items.append(item)
        self.write_items(items)
        return item

    def list_heartbeats(self) -> list[dict[str, Any]]:
        db = self.db()
        if db:
            return db.list_heartbeats(self.tenant_id)
        return [item for item in self.read_items() if item.get("tenant_id") == self.tenant_id]

    def readiness(self) -> dict[str, Any]:
        storage = self.storage_status()
        queue = WorkQueueService(tenant_id=self.tenant_id).summary()
        handoffs = HandoffStore(tenant_id=self.tenant_id).summary()
        heartbeats = self.list_heartbeats()
        problems = []
        if storage["backend"] == "postgres" and not storage["postgres_ok"]:
            problems.append("PostgreSQL is configured but unavailable")
        if queue.get("failed", 0):
            problems.append(f"{queue.get('failed')} queue job(s) failed")
        if handoffs.get("open", 0):
            problems.append(f"{handoffs.get('open')} handoff case(s) need attention")
        for item in heartbeats:
            if item.get("status") not in {"ok", "idle"}:
                problems.append(f"{item.get('component_id')} heartbeat is {item.get('status')}")
        return {
            "ok": not problems,
            "tenant_id": self.tenant_id,
            "storage": storage,
            "work_queue": queue,
            "handoffs": handoffs,
            "heartbeats": heartbeats,
            "problems": problems,
            "summary": "系统运行正常" if not problems else "需要关注：" + "；".join(problems),
        }

    def storage_status(self) -> dict[str, Any]:
        config = load_storage_config()
        store = get_postgres_store(tenant_id=self.tenant_id, config=config)
        availability = store.availability()
        return {
            "backend": config.backend,
            "postgres_configured": config.postgres_configured,
            "postgres_ok": availability.ok,
            "postgres_reason": availability.reason,
            "schema": config.postgres_schema,
            "mirror_files": config.mirror_files,
        }

    def read_items(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if isinstance(payload, dict):
            return list(payload.get("heartbeats", []) or [])
        if isinstance(payload, list):
            return payload
        return []

    def write_items(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"heartbeats": items}, ensure_ascii=False, indent=2), encoding="utf-8")

    def db(self):
        config = load_storage_config()
        store = get_postgres_store(tenant_id=self.tenant_id, config=config)
        if not store.availability().ok:
            return None
        store.initialize_schema()
        return store


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")
