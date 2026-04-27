# 微信 AI 客服分类知识库与运行时重构计划

本文档记录下一轮工程化改造方案。目标不是在现有 JSON 后台上继续贴补丁，而是把微信 AI 客服系统的正式知识源、客服运行时、AI 学习、候选审核、检测、备份恢复和 Web 管理台统一到一套分类知识库架构上。

## 1. 改造目标

本次改造遵循以下顺序：

1. 先调整底层知识库结构。
2. 再调整微信客服的工作方式，让客服运行时直接适配分类知识库。
3. 再把当前已有知识迁移到新的分类目录中。
4. 再做后端与客服流程测试，确认结构和运行时都稳定。
5. 最后再按业务人员可用的方式改造前端管理台。

完成后，系统应满足：

- 知识在后端按门类物理隔离存放，不再把不同类型知识混在同一个大文件或同一个目录。
- 微信客服流程直接读取分类知识库，不再依赖旧的大 JSON 作为主数据源。
- 用户可新增自定义知识门类，每个门类有自己的目录、字段模板、校验规则和表单。
- Web 管理台不再默认展示 JSON，而是展示业务人员能理解的表单、表格、卡片和状态结论。
- AI 学习只生成待审核候选，候选经人工确认、校验通过后才能入正式知识库。
- 所有正式入库、回滚、还原操作前自动备份。
- 旧 `structured` 或 `compiled` 文件只作为过渡兼容、导出或缓存，不再作为唯一正式知识源。

## 2. 当前问题

当前管理台和客服流程已经能跑通，但仍存在结构性问题：

- 知识库当前主要围绕旧的 `product_knowledge.example.json`、`style_examples.json` 和 `manifest.json` 工作。
- 前端知识详情和草稿编辑偏开发者视角，展示 JSON，对普通业务用户不友好。
- 知识类型没有在正式存储层彻底分开，后续数据增多后会变得难维护。
- 上传资料已按商品资料、聊天记录、政策规则、ERP 导出分了门类，但正式知识库没有完全承接这个分类。
- 微信客服运行时仍更习惯旧的商品、FAQ、政策、话术结构，后续新增门类会需要不断改主流程。
- 候选审核、一键检测、系统状态仍偏技术报告，需要转成业务语言。

## 3. 目标架构

### 3.1 正式知识源

正式知识源统一放到：

```text
apps/wechat_ai_customer_service/data/knowledge_bases/
  registry.json
  products/
    schema.json
    resolver.json
    items/
      commercial_fridge_bx_200.json
      office_chair_oc_300.json
  chats/
    schema.json
    resolver.json
    items/
      quote_detail_request.json
      discount_handoff.json
  policies/
    schema.json
    resolver.json
    items/
      invoice_policy.json
      logistics_policy.json
  erp_exports/
    schema.json
    resolver.json
    items/
  custom/
    <custom_category_id>/
      schema.json
      resolver.json
      items/
```

每个门类独立目录，每条知识独立文件。

### 3.2 运行时缓存与兼容导出

```text
apps/wechat_ai_customer_service/data/compiled/
  product_knowledge.example.json
  style_examples.json
  manifest.json
  knowledge_index.json
```

`compiled` 只用于：

- 兼容旧测试和旧工具；
- 作为运行缓存；
- 导出给外部系统；
- 快速比对与回滚诊断。

微信客服主流程应优先读取 `knowledge_bases`，不能长期依赖 `compiled`。

### 3.3 运行时组件

新增或重构以下通用组件：

```text
KnowledgeRegistry
KnowledgeBaseStore
KnowledgeSchemaManager
KnowledgeIndex
EvidenceResolver
ReplyPlanner
KnowledgeValidator
KnowledgeBackupStore
KnowledgeCompiler
```

职责如下：

- `KnowledgeRegistry`：读取所有门类，包括默认门类和自定义门类。
- `KnowledgeBaseStore`：按门类读取、写入、搜索、列出知识条目。
- `KnowledgeSchemaManager`：管理每个门类的字段模板、字段类型、必填项和默认值。
- `KnowledgeIndex`：构建关键词、别名、意图、风险规则和关联关系索引。
- `EvidenceResolver`：根据客户消息从分类知识库中检索证据。
- `ReplyPlanner`：根据证据决定自动回复、调用 LLM、转人工、采集数据或拒绝处理。
- `KnowledgeValidator`：检测字段缺失、重复、冲突、越权承诺、高风险词等。
- `KnowledgeBackupStore`：处理手动备份、自动备份、还原前备份和撤销还原。
- `KnowledgeCompiler`：从分类知识库生成兼容旧流程的 `compiled` 文件。

## 4. 默认门类设计

### 4.1 商品资料 `products`

用途：商品匹配、报价、规格、库存、物流、售后和禁用承诺。

核心字段：

- `id`
- `name`
- `category`
- `sku`
- `aliases`
- `specs`
- `price`
- `price_tiers`
- `inventory`
- `shipping_policy`
- `warranty_policy`
- `reply_templates`
- `risk_rules`
- `allow_auto_reply`
- `requires_handoff`
- `updated_at`

### 4.2 聊天记录与话术 `chats`

用途：沉淀真实客服话术、风格样例、问答样例、边界处理样例。

核心字段：

- `id`
- `customer_message`
- `service_reply`
- `intent_tags`
- `tone_tags`
- `linked_categories`
- `linked_item_ids`
- `usable_as_template`
- `allow_auto_reply`
- `requires_handoff`
- `source`
- `updated_at`

### 4.3 政策规则 `policies`

用途：开票、付款、物流、售后、合同、安装、退款、人工接管等规则。

核心字段：

- `id`
- `title`
- `policy_type`
- `keywords`
- `answer`
- `allow_auto_reply`
- `requires_handoff`
- `handoff_reason`
- `operator_alert`
- `risk_level`
- `updated_at`

### 4.4 ERP 导出 `erp_exports`

用途：对接库存、价格、客户资料、订单状态等后续 ERP 数据。

核心字段：

- `id`
- `source_system`
- `record_type`
- `external_id`
- `fields`
- `sync_status`
- `updated_at`

第一版只建立门类、上传、候选和表单，不强制接入真实 ERP。

### 4.5 自定义门类 `custom/<category_id>`

用途：允许不同客户添加自己的知识模块。

自定义门类必须支持：

- 门类名称；
- 门类说明；
- 字段模板；
- 字段类型；
- 是否参与客服回复；
- 是否参与 AI 学习；
- 是否参与一键检测；
- 是否允许自动回复；
- 是否需要人工审核；
- resolver 规则；
- 表单展示顺序。

第一版字段类型建议支持：

- 短文本；
- 长文本；
- 数字；
- 金额；
- 开关；
- 单选；
- 多选；
- 标签；
- 表格；
- 附件路径；
- 关联知识条目。

## 5. 微信客服运行时改造

### 5.1 新证据包结构

旧证据包按商品、FAQ、政策混合输出。新证据包应按门类输出：

```json
{
  "matched_categories": ["products", "policies", "chats"],
  "evidence_items": [
    {
      "category_id": "products",
      "item_id": "commercial_fridge_bx_200",
      "matched_fields": ["aliases", "shipping_policy"],
      "match_reason": "product_alias_and_shipping_intent",
      "confidence": 0.88,
      "allow_auto_reply": true,
      "requires_handoff": false
    }
  ],
  "safety": {
    "allowed_auto_reply": true,
    "must_handoff": false,
    "reasons": []
  }
}
```

### 5.2 回复决策

微信客服主流程不再直接问“商品 JSON 里有没有这个 FAQ”，而是统一问：

- 命中了哪些门类？
- 命中了哪些知识条目？
- 这些条目是否允许自动回复？
- 是否有必须转人工的规则？
- 是否需要调用 LLM 组织语言？
- 是否存在客户资料采集？
- 是否需要写 Excel 或后续 ERP？

### 5.3 LLM 上下文

DeepSeek 上下文只加载命中的证据项，不加载全量知识。

LLM 输入包括：

- 客户消息；
- 最近上下文；
- 命中的门类；
- 命中的知识条目摘要；
- 禁止承诺规则；
- 客服人设；
- 必须转人工规则。

LLM 输出仍必须结构化，并受守护规则约束。

### 5.4 审计日志

每次决策记录：

- `category_id`
- `item_id`
- `field_id`
- `match_reason`
- `reply_source`
- `llm_used`
- `handoff_reason`
- `backup_id`
- `knowledge_version`

这样后续复盘可以知道到底是哪条知识驱动了回复。

## 6. 数据迁移计划

### 6.1 迁移来源

当前来源：

```text
data/structured/product_knowledge.example.json
data/structured/style_examples.json
data/structured/manifest.json
data/review_candidates/
data/raw_inbox/
```

### 6.2 迁移规则

- `products[]` 迁移到 `knowledge_bases/products/items/*.json`。
- `faq[]` 中开票、公司、付款、物流、售后、合同、安装等规则迁移到 `knowledge_bases/policies/items/*.json`。
- `style_examples.examples[]` 迁移到 `knowledge_bases/chats/items/*.json`。
- 原 `manifest` 迁移到 `knowledge_bases/registry.json` 和各门类 schema。
- 已有 pending candidate 保留，但增加目标门类字段。

### 6.3 迁移脚本

新增：

```text
apps/wechat_ai_customer_service/workflows/migrate_structured_to_knowledge_bases.py
```

脚本要求：

- 可 dry-run；
- 可重复运行；
- 不覆盖人工修改，除非显式指定；
- 输出迁移报告；
- 迁移前自动备份旧结构；
- 迁移后运行校验和编译。

## 7. Web 管理台改造方案

前端改造必须在后端结构和客服运行时适配通过后进行。

### 7.1 知识库页面

改成：

- 左侧门类列表；
- 中间知识条目列表；
- 右侧表单详情；
- 顶部搜索和筛选；
- 支持新增、编辑、删除、保存草稿、校验、入库。

默认不显示 JSON。

高级 JSON 视图可以保留，但放到开发者模式。

### 7.2 草稿页面

草稿必须表单化：

- 选择门类；
- 选择新增、修改、删除、合并；
- 按 schema 生成表单；
- 支持自定义变量；
- 校验通过后才能入库；
- 入库前自动备份；
- 入库后更新索引和运行时缓存。

### 7.3 上传页面

上传继续保留默认门类：

- 商品资料；
- 聊天记录；
- 政策规则；
- ERP 导出；
- 自定义门类。

上传时必须选择门类，AI 学习结果也必须归入门类。

### 7.4 AI 学习结果审核

“候选审核”改名为“AI 学习结果审核”。

展示卡片：

- 来源文件；
- AI 识别到的知识类型；
- 建议入库门类；
- 建议新增或修改的字段；
- 原文证据；
- 冲突提示；
- 风险等级；
- 按钮：编辑后入库、直接入库、合并到已有知识、拒绝。

### 7.5 一键检测

快速检测：

- 只检测最近 7 天新增或修改的知识；
- 或只检测本次草稿、候选和上传影响的知识。

全量检测：

- 检测所有门类、所有条目、所有 schema、所有索引。

输出：

- 是否通过；
- 故障数量；
- 警告数量；
- 所属门类；
- 所属知识；
- 问题说明；
- 建议处理；
- 一键修复按钮。

一键修复分三类：

- 安全修复：格式、空格、缺省值、索引重建，可直接修。
- 半自动修复：生成修复草稿，用户确认后入库。
- 高风险修复：只提示，不自动修，例如价格、合同、退款、赔偿、违规开票。

### 7.6 版本备份与还原

“版本回滚”改名为“备份与还原”。

功能：

- 一键备份；
- 自动备份列表；
- 按门类筛选备份；
- 查看备份摘要；
- 二次确认后一键还原；
- 还原前自动备份当前状态；
- 还原后可撤销本次还原。

### 7.7 系统状态

不显示原始结构化 JSON，只显示模块状态：

- Web 管理台；
- 知识库；
- schema；
- 索引；
- 编译缓存；
- 微信客服流程；
- DeepSeek；
- 微信适配器；
- 文件权限；
- 待审核候选；
- 最近备份；
- 最近检测。

每项显示：正常、警告、异常、未配置。

## 8. 实施章节

### 第 0 章：冻结当前基线

目标：

- 记录当前可运行版本；
- 备份当前 `data/structured`、`data/review_candidates`、`configs`；
- 确认当前管理台和客服回归通过。

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
```

### 第 1 章：建立分类知识库底层结构

目标：

- 新增 `data/knowledge_bases`；
- 新增默认门类；
- 新增 `registry.json`；
- 新增每个门类的 `schema.json` 和 `resolver.json`；
- 新增自定义门类创建能力。

新增模块：

```text
admin_backend/services/knowledge_base_store.py
admin_backend/services/knowledge_schema_manager.py
admin_backend/services/knowledge_registry.py
```

验收：

- 能列出默认门类；
- 能新增自定义门类；
- 每个门类目录物理隔离；
- schema 校验通过。

### 第 2 章：迁移当前知识到分类知识库

目标：

- 写迁移脚本；
- 把现有商品、FAQ、政策、话术迁移到不同门类；
- 生成迁移报告；
- 保留旧文件不删除。

验收：

- 迁移前后知识数量一致或有明确映射说明；
- 商品、政策、话术分别进入不同目录；
- 原客服回归仍可通过兼容层运行。

### 第 3 章：建立分类知识运行时

目标：

- 新增统一知识运行时；
- 建立门类索引；
- 建立别名、关键词、意图、风险规则索引；
- 支持 custom 门类参与检索。

新增模块：

```text
workflows/knowledge_runtime.py
workflows/knowledge_index.py
workflows/evidence_resolver.py
```

验收：

- 输入客户问题，能返回分类 evidence pack；
- 能命中商品、政策、话术；
- 自定义门类能被识别为候选证据；
- 无关问题能正确进入转人工或未知边界。

### 第 4 章：重构微信客服决策流程

目标：

- `listen_and_reply.py` 使用新 evidence pack；
- `build_evidence_pack.py` 改成分类知识 resolver；
- 回复、LLM、转人工、客户资料采集全部基于分类证据；
- 审计日志记录 category 和 item。

验收：

- 现有离线回归通过；
- 工作流逻辑检查通过；
- DeepSeek 边界探针通过；
- 文件传输助手测试场景不退化。

### 第 5 章：保留兼容编译器

目标：

- 新增 `KnowledgeCompiler`；
- 从分类知识库生成旧格式 `compiled` 文件；
- 旧测试或旧工具仍可读取；
- 但客服主流程不依赖旧格式。

验收：

- 编译产物可生成；
- 编译产物与分类知识数量可对账；
- 主流程关闭 compiled 读取后仍可运行。

### 第 6 章：重构 AI 学习候选

目标：

- 上传资料必须选择目标门类；
- AI 学习结果生成分类候选；
- 候选包含表单字段，而不是旧 JSON patch；
- 候选入库前走 schema 校验和备份。

验收：

- 商品资料生成商品候选；
- 聊天记录生成话术候选；
- 政策文档生成政策候选；
- 自定义门类能生成通用候选；
- 候选不会自动进入正式库。

### 第 7 章：重构检测与修复

目标：

- 检测按门类执行；
- 快速检测只检测最近新增或修改；
- 全量检测检查所有门类；
- 输出用户可读结果；
- 安全问题提供一键修复；
- 高风险问题只生成建议或草稿。

验收：

- 空字段、重复 ID、重复别名、冲突价格、高风险承诺均能检测；
- 检测结果不展示原始 JSON；
- 可修复项能生成修复结果或修复草稿。

### 第 8 章：重构备份与还原

目标：

- 备份整个 `knowledge_bases`；
- 备份包含门类、schema、items、索引元信息；
- 正式入库前自动备份；
- 还原前自动备份；
- 支持撤销本次还原。

验收：

- 一键备份可用；
- 一键还原可用；
- 还原前备份可用；
- 撤销还原可用；
- 恢复后客服回归通过。

### 第 9 章：前端表单化改造

目标：

- 知识库页面表单化；
- 草稿页面表单化；
- 候选审核业务卡片化；
- 检测结果摘要化；
- 系统状态模块化；
- 备份还原用户友好化；
- 高级 JSON 视图隐藏到开发者模式。

验收：

- 普通用户无需看 JSON 即可完成新增、修改、审核、检测、备份、还原；
- 自定义门类可在前端创建并编辑字段；
- 表单提交后走 schema 校验；
- Playwright 桌面和移动端截图无明显错位。

### 第 10 章：全量测试与交付

目标：

- 全量编译；
- JSON 校验；
- 分类知识迁移校验；
- 分类 evidence pack 校验；
- 客服离线回归；
- 工作流逻辑检查；
- DeepSeek 探针；
- Web 管理台 E2E；
- 运行锁检查；
- 版本备份恢复演练。

验收：

```powershell
uv run python -m py_compile <apps/wechat_ai_customer_service/**/*.py>
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
```

另外需要新增：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_admin_form_e2e_checks.py
```

## 9. 不可破坏的约束

- 不允许把所有知识继续堆在一个正式文件里。
- 不允许只做前端分类，后端仍混放。
- 不允许 AI 学习结果绕过人工审核直接入正式库。
- 不允许回滚或入库前不备份。
- 不允许微信客服主流程长期依赖旧大 JSON 作为唯一知识源。
- 不允许普通用户默认看到大段 JSON。
- 不允许高风险业务规则被一键自动修复。

## 10. 交付标准

本轮改造完成后，应达到以下状态：

- `knowledge_bases` 是唯一正式知识源；
- 默认门类和自定义门类都可用；
- 微信客服流程直接基于分类知识库做证据检索和回复决策；
- 当前已有知识已迁移到正确门类；
- 兼容编译器可生成旧格式，但主流程不依赖旧格式；
- Web 管理台面向业务用户，不再以 JSON 为主要交互形式；
- AI 学习、候选审核、检测、备份还原、系统状态全部围绕分类知识库运行；
- 全量自动化测试通过；
- 没有测试上传、测试候选、测试版本快照残留。

