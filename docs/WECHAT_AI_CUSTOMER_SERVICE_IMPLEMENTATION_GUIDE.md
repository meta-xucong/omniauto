# 微信 AI 客服代码实现指导文档

## 1. 总体实施方式

本改造按章节推进。每章只实现一组相关能力，完成后运行对应测试。只有当前章节测试通过，才进入下一章。

全量完成标准：

1. 微信客服应用包已从临时目录迁移到 `apps/wechat_ai_customer_service/`。
2. 原有主要命令仍可运行，或提供清晰兼容入口。
3. 业务知识通过 manifest 和按需加载器读取。
4. DeepSeek advisory 使用 evidence pack，而不是读取无关知识。
5. 运行状态、日志、测试产物进入 `runtime/apps/wechat_ai_customer_service/`。
6. 通用/任务专用知识有明确导引文件。
7. 每章测试和最终全量测试记录到 `.codex-longrun/test-log.md`。

## 2. 章节 0：文档与任务状态

### 目标

建立本次长任务的文档、路线和验收标准。

### 需要完成

- 新增优化改造指导文档。
- 新增代码实现指导文档。
- 更新 `.codex-longrun/roadmap.md`。
- 明确每章测试命令。

### 验收

- 两份文档存在。
- `.codex-longrun/state.json` 可通过校验。

## 3. 章节 1：建立独立应用包骨架

### 目标

创建微信 AI 客服专用目录，不移动现有代码，先让新结构可见。

### 需要完成

- 创建 `apps/wechat_ai_customer_service/`。
- 创建 `configs/`、`workflows/`、`adapters/`、`prompts/`、`data/structured/`、`data/raw_inbox/`、`data/review_candidates/`、`tests/scenarios/`、`docs/`。
- 创建 `runtime/apps/wechat_ai_customer_service/` 下的 `state/`、`logs/`、`test_artifacts/`。
- 创建 `knowledge/tasks/desktop/wechat_ai_customer_service/INDEX.md`。
- 新增应用 README，说明旧目录仍为当前兼容来源。

### 验收

```powershell
Test-Path apps/wechat_ai_customer_service/README.md
Test-Path knowledge/tasks/desktop/wechat_ai_customer_service/INDEX.md
```

## 4. 章节 2：迁移配置与业务数据

### 目标

先迁移配置和数据，不迁移执行代码，降低风险。

### 需要完成

- 将测试配置复制到 `apps/wechat_ai_customer_service/configs/test_contact.example.json`。
- 将默认配置复制到 `apps/wechat_ai_customer_service/configs/default.example.json`。
- 将商品知识复制到 `apps/wechat_ai_customer_service/data/structured/product_knowledge.example.json`。
- 调整新配置中的路径，指向新应用目录和新 runtime 目录。
- 保留旧配置不动，避免破坏当前可运行链路。

### 验收

```powershell
uv run python -m json.tool apps/wechat_ai_customer_service/configs/test_contact.example.json
uv run python -m json.tool apps/wechat_ai_customer_service/data/structured/product_knowledge.example.json
```

## 5. 章节 3：实现 manifest 与知识加载器

### 目标

让微信客服业务知识具备按需加载入口。

### 需要完成

- 创建 `apps/wechat_ai_customer_service/data/structured/manifest.json`。
- 新增 `knowledge_loader.py`，支持：
  - 读取 manifest。
  - 根据 intent tags 选择知识条目。
  - 读取被选中的 JSON/Markdown 文件。
  - 构造 evidence pack。
- 新增本地无副作用 CLI，用于测试 evidence pack。

### 验收

```powershell
uv run python apps/wechat_ai_customer_service/workflows/build_evidence_pack.py --text "商用冰箱多少钱"
uv run python apps/wechat_ai_customer_service/workflows/build_evidence_pack.py --text "可以开专票吗"
```

输出应只包含相关 evidence，不应读取全局 `knowledge/` 全量内容。

## 6. 章节 4：迁移可执行 workflow 入口

### 目标

将主要微信客服 workflow 迁移到应用包，并保持旧入口兼容。

### 需要完成

- 将 `guarded_customer_service_workflow.py` 迁移为 `apps/wechat_ai_customer_service/workflows/listen_and_reply.py`。
- 将 `approved_outbound_send.py` 迁移为 `apps/wechat_ai_customer_service/workflows/approved_outbound_send.py`。
- 将 `wechat_customer_service_preflight.py` 迁移为 `apps/wechat_ai_customer_service/workflows/preflight.py`。
- 将微信适配器迁移到 `apps/wechat_ai_customer_service/adapters/`。
- 为旧临时目录保留薄 wrapper，提示新入口并转发执行。

### 验收

```powershell
uv run python apps/wechat_ai_customer_service/workflows/listen_and_reply.py --config apps/wechat_ai_customer_service/configs/test_contact.example.json --once
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --config apps/wechat_ai_customer_service/configs/test_contact.example.json --once
```

测试默认只做 dry-run，不发送消息。

## 7. 章节 5：接入 evidence pack 与 LLM advisory

### 目标

DeepSeek advisory 不再只拿粗糙上下文，而是读取当前消息相关的 evidence pack。

### 需要完成

- 在 `customer_intent_assist` 或新模块中加入 evidence pack 输入。
- prompt 明确：
  - 只能基于 evidence 回答。
  - 证据不足时必须转人工。
  - 不能凭空承诺价格、优惠、库存、物流、售后。
- audit 中记录 evidence item id，不记录敏感内容或 API key。
- 默认仍保持 advisory-only，不直接扩大自动发送权限。

### 验收

```powershell
uv run python apps/wechat_ai_customer_service/workflows/build_evidence_pack.py --text "买7台冰箱能按920吗"
uv run python apps/wechat_ai_customer_service/workflows/listen_and_reply.py --config apps/wechat_ai_customer_service/configs/test_contact.example.json --once
```

议价、破例、账期、投诉类问题应触发人工接管建议。

## 8. 章节 6：原始资料导入与候选知识

### 目标

支持把原始聊天记录、产品资料、政策文件放入 raw inbox，由程序生成待审核候选。

### 需要完成

- 创建 `workflows/generate_review_candidates.py`。
- 从 `data/raw_inbox/` 读取原始文件。
- 生成结构化候选到 `data/review_candidates/pending/`。
- 候选必须包含 evidence、目标文件、建议变更、测试场景建议。
- 不自动改正式 structured 数据。

### 验收

```powershell
uv run python apps/wechat_ai_customer_service/workflows/generate_review_candidates.py --dry-run
```

dry-run 不写正式知识，只打印候选摘要。

## 9. 章节 7：测试场景与回归测试

### 目标

把前面真实测试中暴露的问题固化为回归场景。

### 需要完成

- 新增商品目录、报价、议价、物流、开票、公司信息、客户资料采集、转人工场景。
- 新增离线测试脚本，直接调用产品知识、evidence pack、意图判断，不连接微信。
- 保留真实微信测试为人工触发，不进入默认自动测试。

### 验收

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
```

## 10. 章节 8：全量测试与交付

### 目标

确认文档、目录、配置、知识加载、workflow dry-run、离线回归均可用。

### 需要完成

- 运行 JSON 校验。
- 运行 evidence pack CLI。
- 运行离线回归。
- 运行 workflow dry-run。
- 更新 `.codex-longrun/progress.md` 和 `.codex-longrun/test-log.md`。
- 将 `.codex-longrun/state.json` 标记为 done。

### 验收

所有相关测试通过，且没有正在运行的监听进程或残留锁。

