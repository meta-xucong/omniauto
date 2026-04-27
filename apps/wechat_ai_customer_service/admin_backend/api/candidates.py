"""Review-candidate APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services.candidate_store import CandidateStore


router = APIRouter(prefix="/api/candidates", tags=["candidates"])
store = CandidateStore()


@router.get("")
def list_candidates(status: str = Query("pending", pattern="^(pending|approved|rejected)$")) -> dict[str, Any]:
    return {"ok": True, "items": store.list_candidates(status)}


@router.get("/{candidate_id}")
def get_candidate(candidate_id: str) -> dict[str, Any]:
    return {"ok": True, "item": store.get_candidate(candidate_id)}


@router.patch("/{candidate_id}")
def update_candidate(candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return store.update_candidate(candidate_id, payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc


@router.post("/{candidate_id}/supplement")
def supplement_candidate(candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return store.supplement_candidate(candidate_id, data=(payload or {}).get("data") or {})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc


@router.post("/{candidate_id}/category")
def change_candidate_category(candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = store.change_candidate_category(
            candidate_id,
            target_category=str((payload or {}).get("target_category") or ""),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/{candidate_id}/reject")
def reject_candidate(candidate_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return store.reject(candidate_id, reason=str((payload or {}).get("reason") or "rejected in admin"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc


@router.post("/{candidate_id}/approve")
def approve_candidate(candidate_id: str) -> dict[str, Any]:
    try:
        return store.approve(candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc


@router.post("/{candidate_id}/apply")
def apply_candidate(candidate_id: str) -> dict[str, Any]:
    try:
        return store.apply(candidate_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"candidate not found: {candidate_id}") from exc
