"""Merchant-friendly product workbench APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..services.product_console_service import ProductConsoleService


router = APIRouter(prefix="/api/product-console", tags=["product-console"])


def service() -> ProductConsoleService:
    return ProductConsoleService()


@router.get("/catalog")
def catalog(include_archived: bool = Query(False)) -> dict[str, Any]:
    return service().catalog(include_archived=include_archived)


@router.get("/products/{product_id}")
def product_detail(product_id: str) -> dict[str, Any]:
    try:
        return service().detail(product_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"product not found: {product_id}") from exc


@router.post("/products/{product_id}/inventory")
def adjust_inventory(product_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return service().adjust_inventory(
            product_id,
            operation=str((payload or {}).get("operation") or ""),
            quantity=(payload or {}).get("quantity"),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"product not found: {product_id}") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/command")
def product_command(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return service().command(str((payload or {}).get("message") or ""), use_llm=bool((payload or {}).get("use_llm", True)))
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upload-draft")
async def upload_product_draft(use_llm: bool = Form(True), file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        content = await file.read()
        return service().upload_product_draft(
            filename=file.filename or "product_upload.txt",
            content=content,
            use_llm=use_llm,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
