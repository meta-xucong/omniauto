"""System status APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from apps.wechat_ai_customer_service.auth.models import Role
from apps.wechat_ai_customer_service.platform_safety_rules import load_platform_safety_rules, save_platform_safety_rules
from apps.wechat_ai_customer_service.platform_understanding_rules import load_platform_understanding_rules, save_platform_understanding_rules
from ..auth_context import current_auth_context
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


@router.get("/platform-safety-rules")
def platform_safety_rules(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    payload = load_platform_safety_rules()
    item = payload.get("item", {})
    return {
        "ok": bool(payload.get("ok")),
        "path": payload.get("path"),
        "error": payload.get("error", ""),
        "editable": context.role == Role.ADMIN,
        "item": item,
    }


@router.put("/platform-safety-rules")
def update_platform_safety_rules(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can update platform safety rules"}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
    result = save_platform_safety_rules(item)
    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "item": result.get("item"),
    }


@router.get("/platform-understanding-rules")
def platform_understanding_rules(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    payload = load_platform_understanding_rules()
    item = payload.get("item", {})
    return {
        "ok": bool(payload.get("ok")),
        "path": payload.get("path"),
        "error": payload.get("error", ""),
        "editable": context.role == Role.ADMIN,
        "item": item,
    }


@router.put("/platform-understanding-rules")
def update_platform_understanding_rules(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        return {"ok": False, "detail": "only admin can update platform understanding rules"}
    item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
    result = save_platform_understanding_rules(item)
    return {
        "ok": bool(result.get("ok")),
        "path": result.get("path"),
        "item": result.get("item"),
    }


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
