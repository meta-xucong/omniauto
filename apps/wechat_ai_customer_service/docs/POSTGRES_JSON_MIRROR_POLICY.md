# PostgreSQL And JSON Mirror Policy

## Purpose

PostgreSQL is the preferred runtime storage backend. JSON files are still kept
as a backup, fallback, and re-import source. Normal knowledge changes should not
require a manual migration after the database is enabled.

## Default Behavior

When `WECHAT_STORAGE_BACKEND=postgres`, JSON mirroring is enabled by default.
The app behaves as if this were set:

```powershell
$env:WECHAT_POSTGRES_MIRROR_FILES = "1"
```

This means supported write paths update PostgreSQL first and also write the
matching JSON file. If PostgreSQL is unavailable or the backend is set to
`json`, file mode continues to work as before.

## Supported Double-Write Paths

- Admin knowledge item create/edit/archive.
- Candidate generation and candidate review status files.
- Candidate apply into formal knowledge through the admin service.
- Version snapshot metadata.
- RAG sources, chunks, index entries, and RAG experience records when mirror
  mode is enabled.

## When To Run Migration

Manual migration should be rare. Use it only for:

- First-time PostgreSQL setup.
- Rebuilding PostgreSQL from the JSON backup tree.
- Bulk manual edits made directly to JSON files outside the admin console.

## When To Disable Mirroring

Set this only for deployments that use external database backup and intentionally
do not want local JSON backup files to track database writes:

```powershell
$env:WECHAT_POSTGRES_MIRROR_FILES = "0"
```

Disabling mirror mode makes PostgreSQL the sole write target for supported DB
paths, so it should not be used during local development or business-user
knowledge editing unless there is a separate backup plan.

## Verification

Run:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_postgres_storage_checks.py --dsn $env:WECHAT_POSTGRES_DSN
```

The test suite includes a mirror check that saves a knowledge item in
PostgreSQL mode and verifies both the database row and the JSON file are
created.

