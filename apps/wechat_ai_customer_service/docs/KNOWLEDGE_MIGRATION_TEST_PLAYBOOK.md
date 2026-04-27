# 分类知识库迁移、测试与回滚手册

本文档用于指导从旧结构迁移到分类知识库，并保证每一步可回退、可验证。

## 1. 迁移输入

旧结构来源：

```text
apps/wechat_ai_customer_service/data/structured/manifest.json
apps/wechat_ai_customer_service/data/structured/product_knowledge.example.json
apps/wechat_ai_customer_service/data/structured/style_examples.json
apps/wechat_ai_customer_service/data/review_candidates/
apps/wechat_ai_customer_service/data/raw_inbox/
```

新结构目标：

```text
apps/wechat_ai_customer_service/data/knowledge_bases/
```

## 2. 迁移前备份

迁移脚本执行 `--apply` 前必须自动备份：

```text
apps/wechat_ai_customer_service/data/backups/
  migration_<timestamp>/
    structured/
    review_candidates/
    knowledge_bases_before/
    metadata.json
```

`metadata.json` 至少包含：

- 备份原因；
- 时间；
- 迁移脚本版本；
- 源文件摘要；
- 目标目录摘要。

## 3. 迁移映射

| 旧位置 | 新门类 | 说明 |
| --- | --- | --- |
| `product_knowledge.products[]` | `products/items/*.json` | 每个商品一份文件 |
| `product_knowledge.faq[]` 中开票/付款/公司/物流/售后/合同/安装 | `policies/items/*.json` | 政策和业务规则 |
| `style_examples.examples[]` | `chats/items/*.json` | 话术、风格样例、边界回复 |
| `manifest.json` | `registry.json` + `schema.json` | 门类注册和 schema 元信息 |
| `review_candidates/pending/*.json` | 保留并补充门类字段 | 不直接入正式库 |
| `raw_inbox/*` | 保留 | 上传原始资料不迁移为正式知识 |

## 4. 迁移脚本模式

### dry-run

只输出计划，不写入：

```powershell
uv run python apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py --dry-run
```

输出：

- 将创建哪些门类；
- 将生成哪些 item；
- 哪些 FAQ 会归为 policies；
- 哪些字段无法自动归类；
- 是否存在重复 ID 或重复别名。

### apply

执行迁移：

```powershell
uv run python apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py --apply
```

要求：

- 迁移前自动备份；
- 只写 `knowledge_bases`；
- 不删除旧 `structured`；
- 可重复运行；
- 已存在人工修改时不得静默覆盖。

### force

只允许开发调试时使用：

```powershell
uv run python apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py --apply --force
```

`--force` 必须在日志中显式记录。

## 5. 迁移后校验

新增测试：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
```

检查：

- `registry.json` 可解析；
- 默认门类存在；
- 每个门类 schema/resolver/items 存在；
- 商品数量与旧 products 数量一致；
- 话术数量与旧 style examples 数量一致；
- 政策规则数量可对账；
- item ID 唯一；
- 商品别名不跨商品重复；
- resolver 引用字段存在；
- 自定义门类目录安全。

## 6. 运行时校验

新增测试：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
```

场景：

- 商品报价；
- 商品物流；
- 开票政策；
- 公司信息；
- 售后边界；
- 合同账期转人工；
- 闲聊转业务；
- 无关业务转人工；
- 自定义门类命中。

## 7. 编译器校验

新增测试：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py
```

检查：

- compiled 文件可生成；
- compiled 数量与分类知识可对账；
- 旧格式兼容测试通过；
- 主流程不依赖 compiled 也能通过。

## 8. 客服回归

迁移和运行时改造后必须跑：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
```

通过标准：

- 原有确定性回答不退化；
- 转人工边界不放松；
- 客户资料采集不误判；
- LLM 只能在安全证据边界内发挥；
- 审计日志包含 category/item。

## 9. 回滚方案

如果迁移失败：

1. 停止后续章节。
2. 保留失败现场。
3. 根据 `data/backups/migration_<timestamp>` 恢复。
4. 重新运行旧客服回归。
5. 修复迁移脚本后重新 dry-run。

回滚命令建议由脚本提供：

```powershell
uv run python apps/wechat_ai_customer_service/workflows/restore_knowledge_backup.py --backup-id migration_<timestamp>
```

回滚要求：

- 还原前也要备份当前状态；
- 还原后运行结构校验；
- 还原后运行客服回归。

## 10. 测试残留清理

测试不得留下：

- `admin_*sample*` 上传；
- 测试候选；
- 测试草稿；
- 测试版本快照；
- 测试备份；
- `.lock` 文件。

测试脚本必须内置 cleanup。

