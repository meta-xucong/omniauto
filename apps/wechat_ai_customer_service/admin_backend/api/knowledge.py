"""Read-only knowledge APIs for the admin console."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..services.knowledge_base_store import KnowledgeBaseStore, product_scoped_category_records
from ..services.knowledge_registry import KnowledgeRegistry
from ..services.knowledge_schema_manager import KnowledgeSchemaManager
from ..services.knowledge_store import KnowledgeStore


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
store = KnowledgeStore()
registry = KnowledgeRegistry()
schema_manager = KnowledgeSchemaManager(registry)
base_store = KnowledgeBaseStore(registry, schema_manager)


@router.get("/overview")
def overview() -> dict[str, Any]:
    return store.overview()


@router.get("/categories")
def categories() -> dict[str, Any]:
    items = []
    for category in registry.list_categories(enabled_only=True):
        category_id = str(category.get("id") or "")
        items.append(
            {
                **category,
                "schema": schema_manager.load_schema(category_id),
                "resolver": schema_manager.load_resolver(category_id),
                "item_count": len(base_store.list_items(category_id)),
            }
        )
    for category in product_scoped_category_records():
        category_id = str(category.get("id") or "")
        items.append(
            {
                **category,
                "schema": schema_manager.load_schema(category_id),
                "resolver": schema_manager.load_resolver(category_id),
                "item_count": len(base_store.list_items(category_id)),
            }
        )
    return {"ok": True, "items": items}


@router.post("/categories")
def create_category(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        category = registry.create_custom_category(
            category_id=str(payload.get("id") or payload.get("category_id") or ""),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            participates_in_reply=bool(payload.get("participates_in_reply", False)),
            participates_in_learning=bool(payload.get("participates_in_learning", True)),
            participates_in_diagnostics=bool(payload.get("participates_in_diagnostics", True)),
            fields=payload.get("fields") if isinstance(payload.get("fields"), list) else None,
        )
    except (ValueError, FileExistsError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "item": category}


@router.get("/categories/{category_id}")
def category_detail(category_id: str) -> dict[str, Any]:
    try:
        category = next((item for item in product_scoped_category_records() if item.get("id") == category_id), None)
        if not category:
            category = registry.require_category(category_id)
        return {
            "ok": True,
            "item": {
                **category,
                "schema": schema_manager.load_schema(category_id),
                "resolver": schema_manager.load_resolver(category_id),
                "item_count": len(base_store.list_items(category_id)),
            },
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"category not found: {category_id}") from exc


@router.get("/categories/{category_id}/items")
def category_items(category_id: str, include_archived: bool = False) -> dict[str, Any]:
    try:
        return {"ok": True, "items": base_store.list_items(category_id, include_archived=include_archived)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"category not found: {category_id}") from exc


@router.get("/categories/{category_id}/items/{item_id}")
def category_item_detail(category_id: str, item_id: str) -> dict[str, Any]:
    try:
        item = base_store.get_item(category_id, item_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"item not found: {category_id}/{item_id}") from exc
    if not item:
        raise HTTPException(status_code=404, detail=f"item not found: {category_id}/{item_id}")
    return {"ok": True, "item": item}


@router.post("/categories/{category_id}/items")
def create_category_item(category_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = normalize_item_payload(category_id, payload)
    result = base_store.save_item(category_id, item)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.put("/categories/{category_id}/items/{item_id}")
def update_category_item(category_id: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = base_store.get_item(category_id, item_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"item not found: {category_id}/{item_id}")
    item = normalize_item_payload(category_id, {**existing, **payload, "id": item_id})
    result = base_store.save_item(category_id, item)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.delete("/categories/{category_id}/items/{item_id}")
def archive_category_item(category_id: str, item_id: str) -> dict[str, Any]:
    result = base_store.archive_item(category_id, item_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result)
    return result


@router.get("/products")
def products() -> dict[str, Any]:
    return {"ok": True, "items": store.products()}


@router.get("/products/{product_id}")
def product_detail(product_id: str) -> dict[str, Any]:
    return {"ok": True, "item": store.product(product_id)}


@router.get("/faqs")
def faqs() -> dict[str, Any]:
    return {"ok": True, "items": store.faqs()}


@router.get("/policies")
def policies() -> dict[str, Any]:
    return {"ok": True, "items": store.policies()}


@router.get("/styles")
def styles() -> dict[str, Any]:
    return {"ok": True, "items": store.styles()}


@router.get("/persona")
def persona() -> dict[str, Any]:
    return {"ok": True, "item": store.persona()}


@router.get("/raw-json")
def raw_json(file: str = Query(..., pattern="^(manifest|product_knowledge|style_examples)$")) -> dict[str, Any]:
    return {"ok": True, "file": file, "content": store.raw_json(file)}


def normalize_item_payload(category_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {
        "schema_version": int(payload.get("schema_version") or 1),
        "category_id": category_id,
        "id": str(payload.get("id") or ""),
        "status": str(payload.get("status") or "active"),
        "source": payload.get("source") if isinstance(payload.get("source"), dict) else {"type": "admin_form"},
        "data": data,
        "runtime": payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {"allow_auto_reply": True, "requires_handoff": False, "risk_level": "normal"},
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
