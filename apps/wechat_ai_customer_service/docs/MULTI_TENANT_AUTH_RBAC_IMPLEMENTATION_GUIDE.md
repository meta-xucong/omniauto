# Multi-Tenant Auth And RBAC Implementation Guide

## 1. Modules

```text
apps/wechat_ai_customer_service/auth/
  models.py          account, session, permission dataclasses
  permissions.py     RBAC decisions
  session.py         local session store and fallback accounts
  vps_client.py      VPS authorization client

apps/wechat_ai_customer_service/admin_backend/
  auth_context.py    FastAPI middleware and dependencies
```

## 2. Environment Flags

```text
WECHAT_AUTH_REQUIRED=0|1
WECHAT_VPS_BASE_URL=https://...
WECHAT_VPS_TIMEOUT_SECONDS=8
WECHAT_LOCAL_AUTH_SECRET=<local dev/session signing secret>
WECHAT_KNOWLEDGE_TENANT=default
```

Default behavior remains developer-friendly:

- `WECHAT_AUTH_REQUIRED` defaults to `0`.
- When auth is not required, API requests receive an implicit local admin session.
- Tests can force strict behavior by setting `WECHAT_AUTH_REQUIRED=1`.

## 3. Tenant Context

`active_tenant_id()` must resolve in this order:

1. Explicit function argument.
2. Current request/workflow context variable.
3. `WECHAT_KNOWLEDGE_TENANT`.
4. `default`.

This lets current services keep working while new API middleware can switch tenant without mutating process-wide environment variables.

## 4. API Auth Rules

General rules:

- `/api/health`, `/`, and `/static/*` are public.
- `/api/auth/login` is public.
- other `/api/*` routes require an auth context when `WECHAT_AUTH_REQUIRED=1`.
- guest is read-only.
- customer cannot access another tenant.
- admin can access all tenants.

HTTP method classification:

```text
read: GET, HEAD, OPTIONS
write: POST, PUT, PATCH, DELETE
```

Path-level resources:

```text
/api/knowledge        tenant_knowledge
/api/rag              tenant_rag
/api/uploads          tenant_knowledge
/api/candidates       tenant_knowledge
/api/sync             backups/shared_knowledge/commands depending on subpath
/api/system           settings
/api/tenants          settings
```

## 5. Session Payload

Local session object:

```json
{
  "session_id": "sess_...",
  "user_id": "admin",
  "role": "admin",
  "tenant_ids": ["*"],
  "active_tenant_id": "default",
  "issued_at": "...",
  "expires_at": "...",
  "source": "local|vps"
}
```

Header contract:

```text
Authorization: Bearer <session_id or token>
X-Tenant-ID: <tenant_id>
```

For developer tests, `X-Role` and `X-User-ID` may be accepted only when auth is not required.

## 6. Guest Grants

Guest grants are represented as a constrained session:

```json
{
  "role": "guest",
  "tenant_ids": ["tenant_a"],
  "resource_scopes": ["tenant_knowledge", "tenant_rag"],
  "expires_at": "..."
}
```

All non-read actions are denied regardless of resource scope.

## 7. Migration Strategy

Phase 1:

- Add context variables and middleware.
- Existing services continue to call `active_tenant_id()`.
- New routes instantiate services after middleware sets tenant context.

Phase 2:

- Add explicit `tenant_id` constructor arguments to high-risk services.
- Stop creating module-level service singletons where tenant matters.

Phase 3:

- Enforce strict auth by default in packaged deployments.

## 8. Test Requirements

- local dev mode still passes existing admin checks without login.
- strict mode blocks unauthenticated write calls.
- guest `GET /api/knowledge/overview` succeeds.
- guest `POST /api/rag/rebuild` fails with 403.
- customer tenant mismatch fails with 403.
- admin can access a non-default tenant by `X-Tenant-ID`.
