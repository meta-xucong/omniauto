# PostgreSQL 迁移与运行手册

## 1. 准备数据库

示例环境变量：

```powershell
$env:WECHAT_POSTGRES_DSN="postgresql://omniauto:omniauto@127.0.0.1:5432/omniauto"
$env:WECHAT_POSTGRES_SCHEMA="wechat_ai_customer_service"
$env:WECHAT_POSTGRES_MIRROR_FILES="1"
```

正式启用 PostgreSQL 后端：

```powershell
$env:WECHAT_STORAGE_BACKEND="postgres"
```

`WECHAT_POSTGRES_MIRROR_FILES` 在 PostgreSQL 模式下默认等同于 `1`。显式写出来只是为了让运维人员更容易确认：数据库是主存储，JSON 文件仍会同步保留为备份、回退和重新导入来源。

## 2. 初始化 Schema

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

迁移采用 upsert，可重复运行；不会删除原始 JSON 文件。

## 5. 校验 Parity

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_postgres_storage_checks.py --dsn $env:WECHAT_POSTGRES_DSN
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\workflows\postgres_storage_admin.py parity
```

如果没有 DSN，测试只运行静态 schema 和配置检查，并提示数据库集成部分跳过。

## 6. 切换运行模式

```powershell
$env:WECHAT_STORAGE_BACKEND="postgres"
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_enterprise_eval.py
```

## 7. JSON 镜像策略

PostgreSQL 模式下，普通知识新增、编辑、归档等管理台写入流程会先写 PostgreSQL，再同步写入对应 JSON 文件。这样后续新增知识时，数据库和 JSON 备份会自动保持一致，不需要每次再手动执行迁移。

只有以下情况需要再次运行迁移：

- 首次搭建 PostgreSQL 环境。
- 需要从 JSON 备份重建数据库。
- 人工绕过管理台，直接批量修改了 JSON 文件。

只有在部署环境已经有可靠的外部数据库备份，并且明确不希望本地 JSON 跟随写入时，才设置：

```powershell
$env:WECHAT_POSTGRES_MIRROR_FILES="0"
```

## 8. 回滚

```powershell
$env:WECHAT_STORAGE_BACKEND="json"
```

JSON 文件仍保留同步数据。若数据库读写出现问题，先切回 JSON 模式恢复运行，再修复数据库或重新导入。
