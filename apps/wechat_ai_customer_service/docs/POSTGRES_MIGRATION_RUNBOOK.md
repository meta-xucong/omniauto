# PostgreSQL Migration Runbook

## 1. 准备数据库

示例：

```powershell
$env:WECHAT_POSTGRES_DSN="postgresql://omniauto:omniauto@127.0.0.1:5432/omniauto"
$env:WECHAT_POSTGRES_SCHEMA="wechat_ai_customer_service"
```

如需正式启用：

```powershell
$env:WECHAT_STORAGE_BACKEND="postgres"
```

## 2. 初始化 schema

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\postgres_storage_admin.py init
```

## 3. 预检迁移

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\migrate_file_storage_to_postgres.py --dry-run
```

输出应包含：

- categories count
- knowledge items count
- product scoped items count
- RAG sources/chunks/index/experience count
- candidates/uploads/audit/version metadata count

## 4. 执行迁移

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\migrate_file_storage_to_postgres.py
```

迁移采用 upsert，可重复运行。不会删除 JSON 文件。

## 5. 校验 parity

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_postgres_storage_checks.py --dsn $env:WECHAT_POSTGRES_DSN
```

若没有 DSN，测试会只运行静态 schema/配置检查，并提示数据库集成部分跳过。

## 6. 切换运行模式

```powershell
$env:WECHAT_STORAGE_BACKEND="postgres"
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_enterprise_eval.py
```

## 7. 回滚

```powershell
$env:WECHAT_STORAGE_BACKEND="json"
```

JSON 文件仍保留原始数据。若数据库迁移出现问题，先切回 JSON 模式，再修复 DB 读写或重新导入。
