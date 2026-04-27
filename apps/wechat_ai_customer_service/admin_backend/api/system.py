"""System status APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..services.diagnostics_service import DiagnosticsService
from ..services.knowledge_store import KnowledgeStore
from ..services.locks import list_runtime_locks
from ..services.version_store import VersionStore


router = APIRouter(prefix="/api/system", tags=["system"])
knowledge = KnowledgeStore()
diagnostics = DiagnosticsService()
versions = VersionStore()


@router.get("/status")
def status() -> dict[str, Any]:
    overview = knowledge.overview()
    runs = diagnostics.list_runs()
    return {
        "ok": True,
        "knowledge": overview,
        "recent_diagnostic": runs[0] if runs else None,
        "versions": {"count": len(versions.list_versions())},
        "locks": list_runtime_locks(),
    }


@router.get("/runtime-locks")
def runtime_locks() -> dict[str, Any]:
    return {"ok": True, "items": list_runtime_locks()}

