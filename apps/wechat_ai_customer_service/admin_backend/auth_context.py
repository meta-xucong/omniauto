"""FastAPI auth and tenant-context integration."""

from __future__ import annotations

from typing import Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from apps.wechat_ai_customer_service.auth import AuthContext, AuthService, assert_allowed
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, reset_active_tenant_id, set_active_tenant_id


PUBLIC_PREFIXES = ("/static/",)
PUBLIC_PATHS = {
    "/",
    "/api/health",
    "/api/auth/login",
    "/api/auth/login/start",
    "/api/auth/login/bind-email/start",
    "/api/auth/login/verify",
    "/api/auth/initialize/start",
    "/api/auth/initialize/verify",
    "/api/auth/logout",
    "/v1/auth/login",
    "/v1/auth/login/start",
    "/v1/auth/login/bind-email/start",
    "/v1/auth/login/verify",
    "/v1/auth/initialize/start",
    "/v1/auth/initialize/verify",
}
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthTenantMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, auth_service: AuthService | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.auth_service = auth_service or AuthService()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:  # type: ignore[override]
        path = request.url.path
        if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return await call_next(request)

        tenant_header = request.headers.get("X-Tenant-ID") or request.query_params.get("tenant_id") or ""
        context = self.auth_service.resolve_context(
            authorization=request.headers.get("Authorization", ""),
            tenant_id=tenant_header or None,
            dev_role=request.headers.get("X-Role", ""),
            dev_user_id=request.headers.get("X-User-ID", ""),
        )
        if context is None:
            return JSONResponse({"ok": False, "detail": "authentication required"}, status_code=401)

        resource = resource_for_path(path)
        action = action_for_request(path, request.method)
        try:
            assert_allowed(context, resource=resource, action=action, tenant_id=context.tenant_id)
        except HTTPException as exc:
            return JSONResponse({"ok": False, "detail": exc.detail}, status_code=exc.status_code)

        token = set_active_tenant_id(context.tenant_id)
        request.state.auth_context = context
        try:
            response = await call_next(request)
        finally:
            reset_active_tenant_id(token)
        response.headers.setdefault("X-Tenant-ID", context.tenant_id)
        response.headers.setdefault("X-Auth-Role", context.role.value)
        return response


def current_auth_context(request: Request) -> AuthContext:
    context = getattr(request.state, "auth_context", None)
    if isinstance(context, AuthContext):
        return context
    service = AuthService()
    return service.implicit_admin_context(tenant_id=active_tenant_id())


def resource_for_path(path: str) -> str:
    if path.startswith("/api/sync/shared"):
        return "shared_knowledge"
    if path.startswith("/api/sync/commands"):
        return "commands"
    if path.startswith("/api/sync/update"):
        return "updates"
    if path.startswith("/api/auth/change-password") or path.startswith("/api/auth/email") or path.startswith("/api/auth/security"):
        return "account_security"
    if path.startswith("/api/sync"):
        return "backups"
    if path.startswith("/api/rag"):
        return "tenant_rag"
    if path.startswith("/api/knowledge") or path.startswith("/api/uploads") or path.startswith("/api/candidates"):
        return "tenant_knowledge"
    if path.startswith("/api/tenants") or path.startswith("/api/system"):
        return "settings"
    return "tenant_knowledge"


def action_for_request(path: str, method: str) -> str:
    method = method.upper()
    if path.startswith("/api/sync/commands"):
        return "execute"
    if path.startswith("/api/sync/update"):
        return "sync"
    if path.startswith("/api/sync/shared"):
        return "sync"
    if method in READ_METHODS:
        return "read"
    if path.startswith("/api/sync"):
        return "backup"
    if method == "DELETE":
        return "delete"
    return "write"
