"""VPS-LOCAL sync, backup, shared-patch, and update APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..auth_context import current_auth_context
from apps.wechat_ai_customer_service.auth import assert_allowed
from apps.wechat_ai_customer_service.sync import BackupService, SharedPatchService, VpsLocalSyncService


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    return VpsLocalSyncService().status(tenant_id=context.tenant_id)


@router.post("/register-node")
def register_node(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    context = current_auth_context(request)
    assert_allowed(context, resource="backups", action="backup", tenant_id=context.tenant_id)
    payload = payload or {}
    return VpsLocalSyncService().register_node(
        token=str(request.headers.get("Authorization") or "").replace("Bearer ", "").strip(),
        tenant_id=context.tenant_id,
        display_name=str(payload.get("display_name") or ""),
    )


@router.post("/backup")
def backup(request: Request, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    context = current_auth_context(request)
    payload = payload or {}
    tenant_id = str(payload.get("tenant_id") or context.tenant_id)
    scope = str(payload.get("scope") or "tenant")
    assert_allowed(context, resource="backups", action="backup", tenant_id=tenant_id)
    if scope == "all":
        assert_allowed(context, resource="commands", action="execute", tenant_id=tenant_id)
    try:
        return BackupService().build_backup(
            scope=scope,
            tenant_id=tenant_id,
            include_derived=bool(payload.get("include_derived", False)),
            include_runtime=bool(payload.get("include_runtime", False)),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/shared/preview-patch")
def preview_shared_patch(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return SharedPatchService().preview(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/shared/apply-patch")
def apply_shared_patch(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return SharedPatchService().apply(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/shared/upload-candidates")
def upload_shared_candidates(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    assert_allowed(context, resource="shared_knowledge", action="sync", tenant_id=context.tenant_id)
    return VpsLocalSyncService().upload_shared_candidates(
        token=str(request.headers.get("Authorization") or "").replace("Bearer ", "").strip(),
        tenant_id=context.tenant_id,
    )


@router.post("/commands/poll")
def poll_commands(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    assert_allowed(context, resource="commands", action="execute", tenant_id=context.tenant_id)
    return VpsLocalSyncService().poll_commands(
        token=str(request.headers.get("Authorization") or "").replace("Bearer ", "").strip(),
        tenant_id=context.tenant_id,
    )


@router.get("/update/check")
def check_update(request: Request) -> dict[str, Any]:
    context = current_auth_context(request)
    assert_allowed(context, resource="updates", action="sync", tenant_id=context.tenant_id)
    return VpsLocalSyncService().check_update(token=str(request.headers.get("Authorization") or "").replace("Bearer ", "").strip())
