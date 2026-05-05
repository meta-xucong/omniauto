"""Knowledge export APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ..services.knowledge_export_service import KnowledgeExportService


router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/knowledge")
def build_knowledge_export(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    return KnowledgeExportService().build_export(sort_by=str(payload.get("sort_by") or "type"))


@router.get("/knowledge/download")
def download_knowledge_export(sort_by: str = Query("type", pattern="^(type|time)$")) -> FileResponse:
    result = KnowledgeExportService().build_export(sort_by=sort_by)
    path = Path(str(result.get("path") or ""))
    if not path.exists():
        raise HTTPException(status_code=404, detail="export file not found")
    return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
