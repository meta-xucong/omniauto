# 云端唯一共享公共知识库测试计划

## 1. 静态检查

```powershell
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\knowledge_paths.py apps\wechat_ai_customer_service\sync\vps_sync.py apps\wechat_ai_customer_service\sync\shared_patch_service.py apps\wechat_ai_customer_service\vps_admin\app.py apps\wechat_ai_customer_service\vps_admin\services.py apps\wechat_ai_customer_service\admin_backend\api\sync.py apps\wechat_ai_customer_service\workflows\knowledge_runtime.py
node --check apps\wechat_ai_customer_service\admin_backend\static\app.js
node --check apps\wechat_ai_customer_service\vps_admin\static\app.js
```

## 2. 重点回归

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_multi_tenant_auth_sync_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_admin_control_plane_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_local_auth_shared_console_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_knowledge_runtime_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_vps_local_two_port_shared_sync_checks.py
```

## 3. 场景断言

- 正式知识新增后，只生成云端候选 proposal，不写本地正式共享库。
- admin 接受 proposal 后，云端 `shared_library` 出现正式条目。
- `/v1/shared/knowledge` 返回 accepted shared library 条目。
- 客户端刷新云端快照后，runtime cache 存在 `registry.json` 和 item JSON。
- `data/shared_knowledge` 不因为云端刷新或 `pull_shared_patch` 命令而新增条目。
- runtime 检索能命中云端共享缓存的 `global_guidelines` 或 `risk_control`。
- tenant 正式知识仍优先于 shared layer。
- customer/admin 登录本地客户端时，页面不出现“共享公共知识库”入口。
- 本地 `/api/shared-knowledge/items` 返回 404。
- 前端 JS 不调用 `/api/shared-knowledge`。
- 前端 JS 仍调用 `/api/sync/shared/cloud-snapshot` 和 `/api/sync/shared/formal-candidates`。
- 本地不再展示共享知识同步阻塞弹窗。

## 4. 全量测试

优先使用仓库标准全量测试入口。如果没有更专门的入口，则执行：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

如全量测试因为外部依赖、浏览器、网络或历史 fixture 阻塞，需要记录失败命令、失败原因和本次改造相关性。
