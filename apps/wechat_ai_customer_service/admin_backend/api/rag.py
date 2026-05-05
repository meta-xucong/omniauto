"""RAG auxiliary layer admin APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..services.rag_admin_service import RagAdminService


router = APIRouter(prefix="/api/rag", tags=["rag"])


def rag_service() -> RagAdminService:
    return RagAdminService()


@router.get("/status")
def status() -> dict[str, Any]:
    return rag_service().status()


@router.post("/search")
def search(payload: dict[str, Any]) -> dict[str, Any]:
    return rag_service().search(payload)


@router.post("/rebuild")
def rebuild() -> dict[str, Any]:
    return rag_service().rebuild()


@router.get("/sources")
def sources(limit: int = 80) -> dict[str, Any]:
    return rag_service().sources({"limit": limit})


@router.get("/analytics")
def analytics() -> dict[str, Any]:
    return rag_service().analytics()


@router.get("/experiences")
def list_experiences(status: str = "active", limit: int = 100, fast: bool = False) -> dict[str, Any]:
    return rag_service().list_experiences({"status": status, "limit": limit, "fast": fast})


@router.get("/experiences/unreviewed-count")
def unreviewed_experience_count() -> dict[str, Any]:
    return rag_service().unreviewed_experience_count()


@router.post("/experiences/interpret")
def interpret_experiences(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return rag_service().interpret_experiences(payload or {})


@router.post("/experiences/{experience_id}/interpret")
def interpret_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return rag_service().interpret_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc


@router.post("/experiences/{experience_id}/discard")
def discard_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return rag_service().discard_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc


@router.post("/experiences/{experience_id}/keep")
def keep_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return rag_service().keep_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc


@router.post("/experiences/{experience_id}/reopen")
def reopen_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = rag_service().reopen_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.patch("/experiences/{experience_id}")
def update_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = rag_service().update_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/experiences/{experience_id}/promote")
def promote_experience(experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        result = rag_service().promote_experience(experience_id, payload or {})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"RAG experience not found: {experience_id}") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result
