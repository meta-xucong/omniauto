"""Diagnostics APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..services.diagnostics_service import DiagnosticsService


router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])
service = DiagnosticsService()


@router.post("/run")
def run_diagnostics(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return service.run(
        mode=str(payload.get("mode") or "quick"),
        include_llm_probe=bool(payload.get("include_llm_probe", False)),
        include_wechat_live=bool(payload.get("include_wechat_live", False)),
        include_ignored=bool(payload.get("include_ignored", False)),
    )


@router.get("/runs")
def list_runs() -> dict[str, Any]:
    return {"ok": True, "items": service.list_runs()}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return {"ok": True, "item": service.get_run(run_id)}


@router.post("/runs/{run_id}/apply-suggestion")
def apply_suggestion(run_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return service.apply_suggestion(run_id, payload or {})


@router.get("/ignores")
def list_ignores() -> dict[str, Any]:
    return {"ok": True, "items": service.list_ignored()}


@router.post("/ignore")
def ignore_issue(payload: dict[str, Any]) -> dict[str, Any]:
    return service.ignore_issue(
        fingerprint=str(payload.get("fingerprint") or ""),
        reason=str(payload.get("reason") or ""),
    )


@router.post("/clear-notices")
def clear_acknowledged_notices(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return service.clear_acknowledged_notices(code=str(payload.get("code") or "knowledge_token_budget_large"))
