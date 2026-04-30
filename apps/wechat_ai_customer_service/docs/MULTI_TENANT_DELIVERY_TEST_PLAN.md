# Multi-Tenant VPS-LOCAL Delivery Test Plan

## 1. Focused New Checks

Add a focused script:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_multi_tenant_auth_sync_checks.py
```

It must verify:

- tenant context variables override default tenant safely.
- role permission decisions are deterministic.
- auth-disabled dev mode preserves existing API compatibility.
- strict auth blocks unauthenticated API requests.
- guest read succeeds and guest write fails.
- customer cannot switch to another tenant.
- admin can switch tenants.
- tenant backup package includes a manifest and expected files.
- unsafe shared patch paths are rejected.
- safe shared patch preview/apply works in a temp root.
- offline VPS status is explicit when no VPS URL is configured.
- mock remote `backup_all` command produces a backup result.

## 2. Existing Regression Checks

Run after focused checks:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_postgres_storage_checks.py --dsn "<local dsn>"
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_knowledge_runtime_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_enterprise_eval.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_boundary_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_boundary_matrix_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_offline_regression.py
.\.venv\Scripts\python.exe -m compileall -q apps\wechat_ai_customer_service
node --check apps\wechat_ai_customer_service\admin_backend\static\app.js
```

If PostgreSQL is not running, record the unavailable DSN as a blocker for DB-mode only and still run JSON fallback checks.

## 3. Live Verification

Run File Transfer Assistant live test when WeChat is logged in:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_file_transfer_live_regression.py --config apps\wechat_ai_customer_service\configs\file_transfer_rag_enterprise.example.json --scenarios apps\wechat_ai_customer_service\tests\scenarios\file_transfer_rag_enterprise.json --result-path runtime\apps\wechat_ai_customer_service\test_artifacts\file_transfer_rag_enterprise_results.json --send --reset-state --delay-seconds 1
```

Pass criteria:

- safe RAG query replies from `rag_context_reply`.
- risk query routes to handoff.
- self-reply loop does not repeat.
- temporary RAG/live records are cleaned after test.

If WeChat is offline or target session is unavailable, record the exact preflight error in `.codex-longrun/blockers.md`.

## 4. Delivery Gate

The work can stop only when:

- docs exist and match implemented APIs.
- focused new checks pass.
- existing JSON-mode regressions pass.
- PostgreSQL-mode checks pass when local DSN is available.
- live test passes or a real environmental blocker is recorded.
- `.codex-longrun/state.json`, `progress.md`, and `test-log.md` are updated.
