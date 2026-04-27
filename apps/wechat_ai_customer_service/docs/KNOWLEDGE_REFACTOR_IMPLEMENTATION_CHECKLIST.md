# 分类知识库重构代码实施清单

本清单用于真正开工后的逐章落地。每章必须独立可测试，测试通过后再进入下一章。

## 第 0 章：冻结当前基线

目标：

- 确认当前管理台、客服离线回归、工作流逻辑都通过。
- 记录当前 `data/structured`、`data/review_candidates`、`configs` 的状态。
- 建立本轮重构状态记录。

文件范围：

- `.codex-longrun/state.json`
- `.codex-longrun/progress.md`
- `.codex-longrun/test-log.md`

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
```

## 第 1 章：建立分类知识库目录和注册表

目标：

- 新建 `data/knowledge_bases`。
- 新建默认门类：`products`、`chats`、`policies`、`erp_exports`。
- 支持 `custom/<category_id>`。
- 每个门类必须有 `schema.json`、`resolver.json`、`items/`。

新增文件：

```text
apps/wechat_ai_customer_service/data/knowledge_bases/registry.json
apps/wechat_ai_customer_service/data/knowledge_bases/products/schema.json
apps/wechat_ai_customer_service/data/knowledge_bases/products/resolver.json
apps/wechat_ai_customer_service/data/knowledge_bases/products/items/.gitkeep
apps/wechat_ai_customer_service/data/knowledge_bases/chats/schema.json
apps/wechat_ai_customer_service/data/knowledge_bases/chats/resolver.json
apps/wechat_ai_customer_service/data/knowledge_bases/chats/items/.gitkeep
apps/wechat_ai_customer_service/data/knowledge_bases/policies/schema.json
apps/wechat_ai_customer_service/data/knowledge_bases/policies/resolver.json
apps/wechat_ai_customer_service/data/knowledge_bases/policies/items/.gitkeep
apps/wechat_ai_customer_service/data/knowledge_bases/erp_exports/schema.json
apps/wechat_ai_customer_service/data/knowledge_bases/erp_exports/resolver.json
apps/wechat_ai_customer_service/data/knowledge_bases/erp_exports/items/.gitkeep
apps/wechat_ai_customer_service/data/knowledge_bases/custom/.gitkeep
```

新增模块：

```text
apps/wechat_ai_customer_service/admin_backend/services/knowledge_registry.py
apps/wechat_ai_customer_service/admin_backend/services/knowledge_schema_manager.py
apps/wechat_ai_customer_service/admin_backend/services/knowledge_base_store.py
```

验收：

- 能列出所有默认门类。
- 能创建自定义门类目录。
- 门类 ID 只能使用安全字符。
- 每个门类都能读取 schema 和 resolver。
- 不同门类的 item 物理隔离。

## 第 2 章：迁移旧知识

目标：

- 新增迁移脚本。
- 把旧商品、FAQ、政策、话术迁移到分类目录。
- 迁移前自动备份。
- 支持 dry-run 和 report。

新增文件：

```text
apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py
apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
```

迁移规则：

- `products[]` -> `products/items/*.json`
- `faq[]` 中业务规则 -> `policies/items/*.json`
- `style_examples.examples[]` -> `chats/items/*.json`
- `manifest.json` -> `registry.json` 和默认 schema 元信息

验收：

```powershell
uv run python apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py --dry-run
uv run python apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py --apply
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
```

## 第 3 章：分类知识运行时

目标：

- 微信客服运行时可以直接读取分类知识库。
- 构建统一知识索引。
- 生成分类 evidence pack。

新增或重构：

```text
apps/wechat_ai_customer_service/workflows/knowledge_runtime.py
apps/wechat_ai_customer_service/workflows/knowledge_index.py
apps/wechat_ai_customer_service/workflows/evidence_resolver.py
apps/wechat_ai_customer_service/workflows/build_evidence_pack.py
apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
```

验收：

- 商品别名能命中 `products`。
- 开票、物流、合同、售后能命中 `policies`。
- 风格话术能命中 `chats`。
- 自定义门类能作为 evidence item 返回。
- 无关问题能进入未知或转人工边界。

## 第 4 章：重构微信客服决策流程

目标：

- `listen_and_reply.py` 使用新 evidence pack。
- `ReplyPlanner` 基于分类证据决定自动回复、LLM、转人工、数据采集。
- 审计日志记录 category/item/field。

修改文件：

```text
apps/wechat_ai_customer_service/workflows/listen_and_reply.py
apps/wechat_ai_customer_service/workflows/knowledge_loader.py
apps/wechat_ai_customer_service/workflows/deepseek_advisory.py
apps/wechat_ai_customer_service/tests/run_offline_regression.py
apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
```

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
```

## 第 5 章：兼容编译器

目标：

- 从 `knowledge_bases` 生成 `data/compiled`。
- 旧格式只作为兼容、缓存和导出。
- 主流程优先读取分类知识库。

新增文件：

```text
apps/wechat_ai_customer_service/workflows/compile_knowledge_bases.py
apps/wechat_ai_customer_service/admin_backend/services/knowledge_compiler.py
apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py
```

验收：

- compiled 文件能生成。
- compiled 与分类知识数量可对账。
- 主流程关闭 compiled 读取仍通过。

## 第 6 章：候选与 AI 学习重构

目标：

- 上传资料必须指定门类。
- AI 学习结果生成分类候选。
- 候选展示表单字段，不展示 JSON patch。
- 候选入库前校验、备份、写入对应门类。

修改文件：

```text
apps/wechat_ai_customer_service/workflows/generate_review_candidates.py
apps/wechat_ai_customer_service/admin_backend/services/learning_service.py
apps/wechat_ai_customer_service/admin_backend/services/candidate_store.py
apps/wechat_ai_customer_service/admin_backend/api/learning.py
apps/wechat_ai_customer_service/admin_backend/api/candidates.py
```

验收：

- 商品资料生成商品候选。
- 聊天记录生成话术候选。
- 政策规则生成政策候选。
- 自定义门类能生成通用候选。
- 候选不能绕过审核直接入库。

## 第 7 章：检测、修复、备份还原

目标：

- 检测按门类运行。
- 快速检测只看最近新增或修改。
- 全量检测覆盖所有门类。
- 安全问题可以一键修复。
- 高风险问题只生成草稿或人工建议。
- 备份还原覆盖整个 `knowledge_bases`。

新增或修改：

```text
apps/wechat_ai_customer_service/admin_backend/services/knowledge_validator.py
apps/wechat_ai_customer_service/admin_backend/services/knowledge_backup_store.py
apps/wechat_ai_customer_service/admin_backend/services/diagnostics_service.py
apps/wechat_ai_customer_service/admin_backend/api/diagnostics.py
apps/wechat_ai_customer_service/admin_backend/api/versions.py
```

验收：

- 重复 ID、重复别名、空字段、冲突规则可检测。
- 一键修复只处理安全问题。
- 入库前、还原前自动备份。
- 可撤销本次还原。

## 第 8 章：前端表单化

目标：

- 知识库页面按门类展示。
- 知识详情表单化。
- 草稿表单化。
- 候选审核卡片化。
- 检测和系统状态摘要化。
- 备份还原业务化。
- 支持创建自定义门类和自定义字段。

修改文件：

```text
apps/wechat_ai_customer_service/admin_backend/static/index.html
apps/wechat_ai_customer_service/admin_backend/static/app.js
apps/wechat_ai_customer_service/admin_backend/static/styles.css
apps/wechat_ai_customer_service/admin_backend/api/knowledge.py
apps/wechat_ai_customer_service/admin_backend/api/drafts.py
```

验收：

- 用户不看 JSON 即可新增、编辑、校验、入库。
- 自定义门类可创建。
- 自定义字段可渲染表单。
- Playwright 桌面和移动端截图通过。

## 第 9 章：全量交付测试

验收命令：

```powershell
uv run python -m py_compile <apps/wechat_ai_customer_service/**/*.py>
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
```

还需验证：

- 本地管理台启动成功；
- 桌面和移动端页面可用；
- 运行锁无残留；
- 测试上传、候选、版本快照无残留。

