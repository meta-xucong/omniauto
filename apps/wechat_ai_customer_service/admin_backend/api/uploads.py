"""Raw material upload APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ..services.upload_store import UploadStore


router = APIRouter(prefix="/api/uploads", tags=["uploads"])
store = UploadStore()


@router.post("")
async def upload_file(kind: str = Form("products"), file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    result = store.save_upload(filename=file.filename or "upload.txt", content=content, kind=kind)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("message") or result)
    return result


@router.post("/batch")
async def upload_files(kind: str = Form("products"), files: list[UploadFile] = File(...)) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="no files uploaded")
    results = []
    for file in files:
        content = await file.read()
        result = store.save_upload(filename=file.filename or "upload.txt", content=content, kind=kind)
        result.setdefault("filename", file.filename or "upload.txt")
        results.append(result)
    return {
        "ok": all(item.get("ok") for item in results),
        "count": len(results),
        "items": [item.get("item") for item in results if item.get("ok")],
        "results": results,
    }


@router.get("")
def list_uploads() -> dict[str, Any]:
    return {"ok": True, "items": store.list_uploads()}


@router.get("/{upload_id}")
def get_upload(upload_id: str) -> dict[str, Any]:
    return {"ok": True, "item": store.get_upload(upload_id)}


@router.delete("/{upload_id}")
def delete_upload(upload_id: str) -> dict[str, Any]:
    result = store.delete_upload(upload_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message") or result)
    return result
