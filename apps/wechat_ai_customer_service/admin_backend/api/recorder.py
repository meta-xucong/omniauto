"""AI smart recorder admin APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services.recorder_service import RecorderService


router = APIRouter(prefix="/api/recorder", tags=["recorder"])


@router.get("/summary")
def summary() -> dict[str, Any]:
    return {"ok": True, "item": RecorderService().summary()}


@router.get("/settings")
def settings() -> dict[str, Any]:
    return {"ok": True, "item": RecorderService().settings()}


@router.put("/settings")
def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "item": RecorderService().save_settings(payload or {})}


@router.post("/discover")
def discover_sessions() -> dict[str, Any]:
    return RecorderService().discover_sessions()


@router.get("/conversations")
def conversations(
    conversation_type: str = Query("", pattern="^(|private|group|file_transfer|system|unknown)$"),
    status: str = Query("all", pattern="^(all|active|paused|ignored)$"),
) -> dict[str, Any]:
    return {"ok": True, "items": RecorderService().list_conversations(conversation_type=conversation_type, status=status)}


@router.post("/conversations")
def ensure_conversation(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "item": RecorderService().ensure_conversation(payload or {})}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/conversations/{conversation_id}")
def update_conversation(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"ok": True, "item": RecorderService().update_conversation(conversation_id, payload or {})}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"conversation not found: {conversation_id}") from exc


@router.post("/capture")
def capture_selected(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return RecorderService().capture_selected_once(send_notifications=bool(payload.get("send_notifications", False)))
