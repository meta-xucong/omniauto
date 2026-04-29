# Post-Migration Self Evaluation

This note records the optimization pass after the PostgreSQL storage migration.
It focuses on reliability gaps that affect production-like operation, without
starting a new architecture rewrite.

## Reviewed Areas

- PostgreSQL/file fallback parity.
- Durable work queue recovery behavior.
- Human handoff case identity and duplicate prevention.
- Runtime readiness signals shown to the admin console.
- RAG retrieval safety and live File Transfer Assistant regression coverage.

## Findings And Fixes

### 1. Expired Running Jobs Needed Recovery Semantics

Before this pass, a worker could claim a job and leave it in `running` if the
worker stopped before completion. The database stored `locked_until`, but the
claim path only selected `pending` jobs.

Fix:

- JSON and PostgreSQL queue backends now treat expired `running` jobs as
claimable when attempts remain.
- JSON fallback now stores a future `locked_until` value instead of the current
timestamp.
- Queue summaries now include `stale_running` so readiness can surface stuck
work clearly.

### 2. Handoff Cases Needed Message-Level Deduplication

Before this pass, runtime handoff case IDs included the current timestamp. If
the same customer message was processed again, the system could create multiple
open cases for one real issue.

Fix:

- Handoff case IDs are stable when message IDs are available.
- Duplicate handoff creation returns the existing case and marks the response
with `deduped=true`.
- Handoff status updates now reject invalid statuses.

### 3. Readiness Needed User-Facing Attention Items

Before this pass, readiness returned a short summary plus raw subsystem blocks.
That was enough for tests, but not ideal for an operator deciding what to fix.

Fix:

- Readiness now includes `attention_items`, each with `area`, `severity`,
  `message`, and `detail`.
- Failed queue jobs, expired running jobs, open handoff cases, warning/error
  heartbeats, and unavailable PostgreSQL storage are reported in a consistent
  format.

## Verification Added

- JSON queue stale-lock recovery.
- PostgreSQL queue stale-lock recovery.
- JSON and PostgreSQL handoff deduplication.
- JSON and PostgreSQL readiness attention items.

## Deferred Optimizations

- Replacing the lightweight vector-ready RAG scoring with a dedicated vector
  database remains deferred until knowledge size or latency makes it necessary.
- Moving raw upload binaries into PostgreSQL remains a non-goal; files stay on
  disk and metadata stays queryable.
- Multi-account scheduling and worker pools are still future work. The durable
  queue now provides the foundation for that next step.

