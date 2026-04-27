"""System status APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..services.diagnostics_service import DiagnosticsService
from ..services.handoff_store import HandoffStore
from ..services.knowledge_store import KnowledgeStore
from ..services.locks import list_runtime_locks
from ..services.runtime_monitor import RuntimeMonitor
from ..services.version_store import VersionStore
from ..services.work_queue import WorkQueueService


router = APIRouter(prefix="/api/system", tags=["system"])
knowledge = KnowledgeStore()
diagnostics = DiagnosticsService()
versions = VersionStore()
work_queue = WorkQueueService()
handoffs = HandoffStore()
monitor = RuntimeMonitor()


@router.get("/status")
def status() -> dict[str, Any]:
    overview = knowledge.overview()
    runs = diagnostics.list_runs()
    return {
        "ok": True,
        "knowledge": overview,
        "recent_diagnostic": runs[0] if runs else None,
        "versions": {"count": len(versions.list_versions())},
        "work_queue": work_queue.summary(),
        "handoffs": handoffs.summary(),
        "readiness": monitor.readiness(),
        "locks": list_runtime_locks(),
    }


@router.get("/runtime-locks")
def runtime_locks() -> dict[str, Any]:
    return {"ok": True, "items": list_runtime_locks()}


@router.get("/readiness")
def readiness() -> dict[str, Any]:
    report = monitor.readiness()
    return {"ok": report["ok"], "report": report}


@router.post("/heartbeat/{component_id}")
def heartbeat(component_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return {
        "ok": True,
        "item": monitor.heartbeat(
            component_id,
            status=str(payload.get("status") or "ok"),
            message=str(payload.get("message") or ""),
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
        ),
    }
