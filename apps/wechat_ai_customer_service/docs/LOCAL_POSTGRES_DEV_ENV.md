# Local PostgreSQL Development Environment

This app supports PostgreSQL as the preferred durable storage backend. For local testing on Windows, a portable PostgreSQL instance is preferred because it does not require a Windows service or admin configuration.

## 1. Directory Layout

Local-only files should live under ignored paths:

- `.local/postgresql-17.9-3/`
- `.local/postgres-data-17/`
- `.local/downloads/`
- `apps/wechat_ai_customer_service/configs/postgres.local.env`

These paths must not be committed.

## 2. Portable PostgreSQL Setup

The local development setup used for this project:

- PostgreSQL: 17.9 portable Windows x64 binaries
- Host: `127.0.0.1`
- Port: `55432`
- Database: `omniauto_wechat_dev`
- User: `postgres`

The local DSN shape is:

```powershell
$env:WECHAT_STORAGE_BACKEND = "postgres"
$env:WECHAT_POSTGRES_DSN = "postgresql://postgres:<local-password>@127.0.0.1:55432/omniauto_wechat_dev"
$env:WECHAT_POSTGRES_MIRROR_FILES = "1"
```

Do not commit the real local password.

## 3. Start And Stop

Start:

```powershell
$bin = ".local\postgresql-17.9-3\pgsql\bin"
$data = ".local\postgres-data-17"
& "$bin\pg_ctl.exe" -D $data -l "$data\postgres.log" -o "-p 55432" start
```

Stop:

```powershell
$bin = ".local\postgresql-17.9-3\pgsql\bin"
$data = ".local\postgres-data-17"
& "$bin\pg_ctl.exe" -D $data stop
```

Status:

```powershell
$bin = ".local\postgresql-17.9-3\pgsql\bin"
$data = ".local\postgres-data-17"
& "$bin\pg_ctl.exe" -D $data status
```

## 4. App Schema And Migration

Initialize schema:

```powershell
$env:WECHAT_STORAGE_BACKEND = "postgres"
$env:WECHAT_POSTGRES_DSN = "postgresql://postgres:<local-password>@127.0.0.1:55432/omniauto_wechat_dev"
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\postgres_storage_admin.py init
```

Migrate file storage into PostgreSQL:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\migrate_file_storage_to_postgres.py
```

Check counts:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\postgres_storage_admin.py counts
```

Run PostgreSQL integration checks:

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_postgres_storage_checks.py --dsn $env:WECHAT_POSTGRES_DSN
```

## 5. Operational Notes

- Use port `55432` locally to avoid collisions with any system PostgreSQL on `5432`.
- Keep JSON/file fallback enabled as the default in committed config.
- In PostgreSQL mode, JSON mirroring is enabled by default. This means normal admin-console knowledge writes update PostgreSQL and the matching JSON file, so the JSON tree remains a backup/fallback source without manual migration.
- Set `WECHAT_POSTGRES_MIRROR_FILES=0` only when a deployment intentionally disables JSON backups and relies on external database backup tooling.
- Only set `WECHAT_STORAGE_BACKEND=postgres` in the current shell or ignored local env files.
- DB-backed live tests should clean temporary RAG sources and experiences after each run.
