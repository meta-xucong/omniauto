# Enterprise Hardening Code Roadmap

This document breaks the enterprise hardening plan into small implementation chapters. Each chapter must be tested before moving to the next.

## Chapter 1. Local PostgreSQL Development Environment

### Files

- `apps/wechat_ai_customer_service/docs/LOCAL_POSTGRES_DEV_ENV.md`
- Optional local ignored files under `.local/`
- Optional ignored env file: `apps/wechat_ai_customer_service/configs/postgres.local.env`

### Tasks

- Use a portable PostgreSQL binary in `.local/` when system install is not available.
- Start PostgreSQL on a non-default local development port.
- Create `omniauto_wechat_dev`.
- Initialize app schema.
- Migrate existing file data.
- Run PostgreSQL roundtrip checks.

### Verification

- `postgres_storage_admin.py status`
- `postgres_storage_admin.py init`
- `migrate_file_storage_to_postgres.py`
- `run_postgres_storage_checks.py --dsn <dsn>`

## Chapter 2. Storage Parity And Migration Reporting

### Files

- `storage/postgres_store.py`
- `workflows/postgres_storage_admin.py`
- `workflows/migrate_file_storage_to_postgres.py`
- `tests/run_postgres_storage_checks.py`

### Tasks

- Add a parity command that compares file-side migration counts with PostgreSQL counts.
- Report duplicate/merged candidates explicitly.
- Make migration output clear enough for operator review.

### Verification

- Static storage checks.
- Migration dry-run.
- Migration import against local PostgreSQL.
- Parity command returns `ok=true` or a precise difference list.

## Chapter 3. Durable Work Queue

### Files

- `storage/postgres_schema.sql`
- `storage/postgres_store.py`
- `admin_backend/services/work_queue.py`
- `admin_backend/api/jobs.py`
- `admin_backend/app.py`
- `tests/run_enterprise_hardening_checks.py`

### Tasks

- Add PostgreSQL tables for work queue jobs.
- Add JSON fallback queue store.
- Implement enqueue, claim, complete, fail, cancel, list, and summary operations.
- Expose `/api/jobs` endpoints.
- Include queue summary in system status.

### Verification

- Unit-style queue checks in JSON fallback mode.
- PostgreSQL queue roundtrip with local DSN.
- Admin backend checks still pass.

## Chapter 4. Human Handoff Case Store

### Files

- `storage/postgres_schema.sql`
- `storage/postgres_store.py`
- `admin_backend/services/handoff_store.py`
- `admin_backend/api/handoffs.py`
- `workflows/listen_and_reply.py`
- `tests/run_enterprise_hardening_checks.py`

### Tasks

- Add durable handoff case storage.
- Record runtime handoff events into the case store.
- Preserve current operator alert JSONL behavior as a fallback/export path.
- Expose list/get/resolve/ignore APIs.
- Add open case counts to system status.

### Verification

- Handoff case create/list/resolve checks in JSON fallback and PostgreSQL mode.
- Existing workflow logic handoff tests still pass.

## Chapter 5. Monitoring And Readiness

### Files

- `storage/postgres_schema.sql`
- `storage/postgres_store.py`
- `admin_backend/services/runtime_monitor.py`
- `admin_backend/api/system.py`
- `workflows/preflight.py`
- `tests/run_enterprise_hardening_checks.py`

### Tasks

- Add runtime heartbeat storage.
- Add readiness summary: storage, queue, handoff, RAG, knowledge, diagnostics, recent failures.
- Keep user-facing summaries concise.

### Verification

- Heartbeat upsert/list checks.
- `/api/system/status` contains enterprise health fields.
- Preflight still passes.

## Chapter 6. RAG Vector-Ready Retrieval

### Files

- `workflows/rag_layer.py`
- `storage/postgres_store.py`
- `tests/run_rag_enterprise_eval.py`
- `tests/run_rag_boundary_checks.py`

### Tasks

- Generate deterministic lightweight vectors for chunks and queries.
- Store vectors in the RAG index payload.
- Add cosine similarity to retrieval scoring.
- Preserve lexical/semantic/product/risk guardrails.
- Expose vector score details for audit and debugging.

### Verification

- RAG enterprise eval passes.
- RAG boundary checks pass.
- Existing live scenarios retain correct behavior.

## Chapter 7. Full Regression And Live Self-Test

### Tasks

- Run all static checks.
- Run all existing offline regression suites.
- Run PostgreSQL-mode full regression.
- Run focused File Transfer Assistant live regression with PostgreSQL enabled.
- Clean temporary RAG test sources and experiences.

### Verification

- All checks pass.
- No runtime artifacts are staged.
- Long-running state is updated to `done` or a precise blocker.

