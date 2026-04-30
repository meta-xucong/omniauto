"""Admin-only APIs for the local shared public knowledge layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..auth_context import current_auth_context
from apps.wechat_ai_customer_service.auth import Role
from apps.wechat_ai_customer_service.knowledge_paths import SHARED_KNOWLEDGE_ROOT
from apps.wechat_ai_customer_service.vps_admin.local_data import build_shared_knowledge_snapshot


router = APIRouter(prefix="/api/shared-knowledge", tags=["shared-knowledge"])


@router.get("/items")
def list_items(request: Request) -> dict[str, Any]:
    require_admin(request)
    return {"ok": True, **build_shared_knowledge_snapshot()}


@router.get("/items/{item_id}")
def get_item(item_id: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    item_path = find_item_path(item_id)
    if item_path is None:
        raise HTTPException(status_code=404, detail=f"shared knowledge item not found: {item_id}")
    return {"ok": True, "item": read_json(item_path), "path": str(item_path)}


@router.post("/items")
def create_item(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    context = require_admin(request)
    category_id = clean_id(payload.get("category_id") or "global_guidelines")
    item_id = clean_id(payload.get("item_id") or payload.get("id") or "")
    if not item_id:
        item_id = "shared_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    item_path = item_file_path(category_id, item_id)
    if item_path.exists():
        raise HTTPException(status_code=409, detail=f"shared knowledge item already exists: {item_id}")
    ensure_category(category_id)
    record = item_record(payload, category_id=category_id, item_id=item_id, actor_id=context.user.user_id)
    write_json(item_path, record)
    return {"ok": True, "item": record, "path": str(item_path)}


@router.put("/items/{item_id}")
def update_item(item_id: str, payload: dict[str, Any], request: Request) -> dict[str, Any]:
    context = require_admin(request)
    item_path = find_item_path(item_id)
    if item_path is None:
        raise HTTPException(status_code=404, detail=f"shared knowledge item not found: {item_id}")
    existing = read_json(item_path)
    category_id = clean_id(payload.get("category_id") or existing.get("category_id") or "global_guidelines")
    next_id = clean_id(payload.get("item_id") or payload.get("id") or item_id)
    record = item_record(payload, category_id=category_id, item_id=next_id, actor_id=context.user.user_id, existing=existing)
    next_path = item_file_path(category_id, next_id)
    ensure_category(category_id)
    if next_path != item_path:
        delete_item_file(item_path)
    write_json(next_path, record)
    return {"ok": True, "item": record, "path": str(next_path)}


@router.delete("/items/{item_id}")
def delete_item(item_id: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    item_path = find_item_path(item_id)
    if item_path is None:
        raise HTTPException(status_code=404, detail=f"shared knowledge item not found: {item_id}")
    record = read_json(item_path)
    deleted = delete_item_file(item_path)
    return {"ok": True, "item": record, "deleted": deleted, "path": str(item_path)}


def require_admin(request: Request):  # type: ignore[no-untyped-def]
    context = current_auth_context(request)
    if context.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="admin account required")
    return context


def item_record(
    payload: dict[str, Any],
    *,
    category_id: str,
    item_id: str,
    actor_id: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = existing.get("data") if isinstance(existing, dict) and isinstance(existing.get("data"), dict) else {}
    data = dict(data)
    if "title" in payload:
        data["title"] = str(payload.get("title") or "")
    if "content" in payload:
        data["guideline_text"] = str(payload.get("content") or "")
    if isinstance(payload.get("data"), dict):
        data.update(payload["data"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "schema_version": int(payload.get("schema_version") or ((existing or {}).get("schema_version") if isinstance(existing, dict) else 1) or 1),
        "category_id": category_id,
        "id": item_id,
        "status": str(payload.get("status") or (existing or {}).get("status") or "active"),
        "source": payload.get("source") if isinstance(payload.get("source"), dict) else {"type": str(payload.get("source") or "local_admin_console")},
        "data": data,
        "runtime": payload.get("runtime") if isinstance(payload.get("runtime"), dict) else (existing or {}).get("runtime", {}),
        "metadata": {
            **(((existing or {}).get("metadata") if isinstance((existing or {}).get("metadata"), dict) else {})),
            "updated_at": now,
            "updated_by": actor_id,
        },
    }


def ensure_category(category_id: str) -> None:
    registry_path = SHARED_KNOWLEDGE_ROOT / "registry.json"
    registry = read_json(registry_path) if registry_path.exists() else {"schema_version": 1, "scope": "wechat_ai_customer_service_shared", "categories": []}
    categories = registry.get("categories") if isinstance(registry.get("categories"), list) else []
    changed = False
    if not any(str(item.get("id") or item.get("category_id") or "") == category_id for item in categories if isinstance(item, dict)):
        categories.append(
            {
                "id": category_id,
                "name": category_id,
                "kind": "global",
                "path": category_id,
                "enabled": True,
                "participates_in_reply": True,
                "participates_in_learning": False,
                "participates_in_diagnostics": True,
                "sort_order": 100,
            }
        )
        changed = True
    registry["categories"] = categories
    if changed or not registry_path.exists():
        registry["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        write_json(registry_path, registry)
    (SHARED_KNOWLEDGE_ROOT / category_id / "items").mkdir(parents=True, exist_ok=True)


def item_file_path(category_id: str, item_id: str) -> Path:
    return SHARED_KNOWLEDGE_ROOT / category_id / "items" / f"{item_id}.json"


def find_item_path(item_id: str) -> Path | None:
    cleaned = clean_id(item_id)
    for path in sorted(SHARED_KNOWLEDGE_ROOT.glob("*/items/*.json")):
        if path.stem == cleaned:
            return path
    return None


def clean_id(value: Any) -> str:
    text = str(value or "").strip()
    allowed = []
    for char in text:
        if char.isalnum() or char in {"_", "-"}:
            allowed.append(char)
        elif char.isspace():
            allowed.append("_")
    return "".join(allowed).strip("_")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail=f"JSON object required: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def delete_item_file(path: Path) -> bool:
    root = SHARED_KNOWLEDGE_ROOT.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="item path is outside shared knowledge root") from None
    if not resolved.exists():
        return False
    resolved.unlink()
    return True
