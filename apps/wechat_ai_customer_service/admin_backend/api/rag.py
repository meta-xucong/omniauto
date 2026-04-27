"""RAG auxiliary layer admin APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.rag_admin_service import RagAdminService


router = APIRouter(prefix="/api/rag", tags=["rag"])
service = RagAdminService()


@router.get("/status")
def status() -> dict[str, Any]:
    return service.status()


@router.post("/search")
def search(payload: dict[str, Any]) -> dict[str, Any]:
    return service.search(payload)


@router.post("/rebuild")
def rebuild() -> dict[str, Any]:
    return service.rebuild()


@router.get("/analytics")
def analytics() -> dict[str, Any]:
    return service.analytics()


@router.get("/experiences")
def list_experiences(status: str = "active", limit: int = 100) -> dict[str, Any]:
    return service.list_experiences({"status": status, "limit": limit})


@router.post("/experiences/{experience_id}/discard")
def discard_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return service.discard_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc
