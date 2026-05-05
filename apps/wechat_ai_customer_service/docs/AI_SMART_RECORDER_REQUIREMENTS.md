# AI 智能自动记录员需求分析 V2.0

> 2026-05-01 补充：知识流转主流程已进一步收敛为 V3.0 目标方案，详见 `UNIFIED_KNOWLEDGE_FLOW_V3_PROPOSAL.md`。V2.0 中的共享原始消息库、候选标识、Excel 导出、群聊选择仍然有效；但“上传资料/原始消息可直接生成候选”的实现应在下一阶段改为“先生成 RAG 经验，再从 RAG 经验生成候选”。

## 1. V2.0 调整摘要

本版在 V1 的基础上做五个关键修正：

1. 原始消息专用库不再只服务记录员，而是作为微信 AI 客服和记录员共用的底层能力。
2. Excel 导出不再另起一套格式，而是复用服务端客户数据包的“可读知识表”语义，导出一致内容。
3. 群聊记录不默认记录全部群，后台应列出识别到的群聊，由用户勾选需要记录的群。
4. AI 抽取出的知识即使已经完全符合结构化要求，也只能进入候选库，等待用户手动晋升；系统用“已完善”“待完善”“RAG生成”等标识帮助用户筛选。
5. 自动客服和记录员统一采用“受控入库”方案：正式库写入必须经过候选晋升、版本快照、审计记录和醒目的“新加入/未阅”标识，用户点击“已阅”后才取消该标识。

为避免术语混乱，V2 中的“受控入库”不是 AI 自动跳过候选库直接写正式知识，而是指两个模块共用同一条受控晋升链路：原始消息或资料 -> RAG/结构化抽取 -> 候选库 -> 用户确认晋升 -> 正式知识库 -> 新加入标识 -> 用户已阅。

## 2. 总体目标

“AI 智能自动记录员”是微信 AI 客服体系中的旁路记录与知识沉淀模块。它复用现有客服框架，将私聊、群聊和客服运行过程中产生的信息统一沉淀为：

1. 原始消息库：完整、可追溯、可去重的微信消息事实层。
2. RAG 资料与经验：聊天记录、资料片段、可复用表达和命中经验。
3. 候选知识：AI 结构化后的待确认条目，按完善度、来源和风险打标。
4. 正式知识：用户手动晋升后的权威结构化知识。

最终目标是让自动客服和记录员共用“消息记录、知识候选、状态标识、导出、审计、版本快照”这些基础能力，而记录员只新增自己的会话选择、静默采集、记录员页面和摄入任务视图。

## 3. 共有改造内容

本节是两个功能模块都要使用的能力，开发时应放在共享服务、共享 API 或共享前端组件中。

### 3.1 统一原始消息库

微信 AI 客服和记录员都需要原始消息库。客服模块需要它保存真实上下文、复盘自动回复、追溯知识来源；记录员模块需要它持续收集私聊和群聊信息。

建议新增共享数据模型：

- `raw_conversations`
- `raw_messages`
- `raw_message_batches`
- `message_intake_jobs`

核心字段：

- tenant_id
- conversation_id
- conversation_type: `private | group | file_transfer | system | unknown`
- target_name
- group_name
- group_member_name
- message_id
- sender
- sender_role: `self | contact | group_member | bot | system | unknown`
- content_type
- content
- message_time
- observed_at
- source_module: `customer_service | recorder | manual_import`
- source_adapter
- raw_payload
- dedupe_key
- learning_enabled
- excluded_reason

幂等规则：

- 以 `tenant_id + conversation_id + message_id` 优先去重。
- 如果 message_id 不稳定，使用 `tenant_id + target_name + sender + content + message_time` 的 hash 兜底。
- 同一消息可以被客服和记录员同时观察，但只能保存一份 raw message；`source_modules` 可记录多来源。

降级存储：

- Postgres 可用时以 Postgres 为主。
- JSON mirror 或无数据库模式写入 `runtime/apps/wechat_ai_customer_service/tenants/<tenant_id>/raw_messages/`。

### 3.2 统一候选状态标识

候选库需要给所有来源的候选统一打标，供自动客服和记录员共用。

候选状态标识建议分三类：

- 完善度：`已完善`、`待完善`、`缺少关键字段`。
- 来源：`微信私聊`、`微信群聊`、`RAG生成`、`文件上传`、`AI生成器`、`人工新增`。
- 风险与处理：`需人工确认`、`疑似冲突`、`重复候选`、`可晋升`、`已拒绝`。

候选判断规则：

- `intake.status=ready` 显示“已完善”。
- `intake.status=needs_more_info` 显示“待完善”。
- 从 RAG 经验升级来的候选显示“RAG生成”。
- 从原始微信消息生成的候选显示私聊或群聊来源。
- 存在 risk warnings、handoff、价格/合同/赔付/发票/账期等风险字段时显示“需人工确认”。

候选应用规则：

- 即使“已完善”，也不能自动进入正式知识库。
- “已完善”只代表字段完整、schema 可用，用户仍需点击晋升。
- “待完善”候选必须先补全，补全后重新诊断，状态变为“已完善”才允许晋升。

### 3.3 统一正式知识新加入标识

两个模块写入正式知识后，都必须给新增或更新的正式知识加醒目标识。

建议字段：

```json
{
  "review_state": {
    "is_new": true,
    "new_reason": "candidate_promoted",
    "source_module": "recorder",
    "candidate_id": "raw_xxx",
    "created_by_flow": "candidate_apply",
    "marked_at": "2026-05-01T12:00:00",
    "read_at": "",
    "read_by": ""
  }
}
```

展示规则：

- 正式知识列表和详情页显示“新加入”或“有更新”醒目标识。
- 用户点击“已阅”后，`is_new=false`，保留 `read_at/read_by`。
- 标识只影响后台展示，不影响运行时自动客服检索。

适用范围：

- 候选晋升为正式知识。
- 手动新增正式知识。
- 候选合并更新已有正式知识。
- RAG 经验经候选晋升后写入正式知识。

### 3.4 统一 Excel 导出

微信 AI 客服和记录员都需要导出已收纳知识。导出内容应和服务端客户数据包的“可读知识表”保持一致。

复用目标：

- 复用 `vps_admin/readable_export.py` 的 workbook 结构和人类可读字段。
- 本地后台导出和 VPS 服务端下载可读知识表保持相同 sheet 语义。
- 导出范围包括正式知识、商品专属知识、RAG 资料、RAG 经验和技术清单。

本地后台需要新增导出入口：

- 导出当前租户可读知识表。
- 可选按类型排序或按时间排序。
- 可选包含或不包含 RAG/技术清单。

导出内容：

- 正式-商品资料
- 正式-政策规则
- 正式-聊天记录与话术
- 正式-ERP导出
- 商品专属-规则
- 商品专属-FAQ
- 商品专属-说明
- RAG资料
- RAG经验
- 技术文件清单或来源追溯

### 3.5 统一审计、版本和权限

正式知识变更必须统一经过：

- 候选 apply 或后台显式保存。
- 写入前版本快照。
- 写入后审计事件。
- 新加入/未阅标识。
- 可回滚路径。

权限建议：

- 查看 raw message 需要 tenant knowledge read。
- 修改监听配置、触发摄入、晋升候选、导出数据需要 tenant knowledge write 或 backup 权限。
- 原始消息含隐私数据，访客默认不可查看。

## 4. 记录员模块新增内容

本节只属于“AI 智能自动记录员”，不应污染客服回复主流程。

### 4.1 记录员运行模式

新增记录员配置：

```json
{
  "recorder": {
    "enabled": true,
    "reply_mode": "silent",
    "record_private_chats": true,
    "record_group_chats": true,
    "auto_discovery": false,
    "notify": {
      "enabled": false,
      "on_candidate_created": true,
      "on_formal_promoted": true,
      "min_interval_seconds": 300
    },
    "intake": {
      "rag_enabled": true,
      "candidate_enabled": true,
      "use_llm": false
    }
  }
}
```

`reply_mode`：

- `silent`：只记录，不发提示。
- `notify_only`：只在候选或正式知识变化时按限流提示。
- `customer_service_compatible`：和自动客服共存，但记录员不改变原有客服回复策略。

### 4.2 群聊识别与选择

记录员不应默认记录所有群。

后台应提供：

1. “扫描当前会话”按钮，调用微信连接器 `list_sessions`。
2. 根据会话名称、wxauto4 chat_info 或用户手动标注识别可能的群聊。
3. 展示候选群列表。
4. 用户勾选要记录的群。
5. 用户可设置 exact match、是否记录 self 消息、是否提示、是否参与学习。

第一版可接受的群识别策略：

- 自动识别只做辅助，不保证 100% 正确。
- 用户最终选择是准入条件。
- 对无法可靠识别的会话，允许用户手动标记为群聊。

### 4.3 私聊记录

私聊可通过显式 target 或会话扫描加入。

默认策略：

- 只记录用户选中的私聊。
- 文件传输助手默认排除，除非用户手动加入测试。
- 公众号、服务通知等系统会话默认排除。
- 可选择是否记录自己发送的消息。

### 4.4 静默摄入任务

记录员采集新消息后，不在同步轮询里做重处理，而是生成任务：

1. `raw_saved`
2. `rag_ingest_pending`
3. `candidate_generation_pending`
4. `succeeded | failed | skipped`

任务可重试、可跳过、可查看错误。

### 4.5 收录提示

提示功能可手动开启。

默认建议：

- 私聊默认关闭，可由用户开启。
- 群聊默认关闭。
- raw message 保存不逐条提示。
- 候选生成可以按批提示。
- 正式知识晋升后可以提示。

提示消息必须限流，避免群聊刷屏。

## 5. 知识流转规则

统一流转如下：

```text
微信消息 / 上传资料 / AI生成器
-> 原始消息库或 raw_inbox
-> RAG source/chunk/index
-> RAG 经验
-> 结构化候选
-> 状态标识：已完善 / 待完善 / RAG生成 / 微信群聊 / 微信私聊
-> 用户补全或确认
-> 手动晋升正式知识
-> 版本快照 + 审计
-> 正式知识新加入标识
-> 用户点击已阅
```

LLM 辅助判断规则：

- 上传资料、微信原始消息、记录员消息、RAG 经验升级和 AI 生成器整理，都应优先调用 LLM 做业务理解、分类、字段抽取、适用范围、风险和正式知识重合判断。
- LLM 只能生成审核建议、RAG 经验或待确认候选，不能直接写正式知识。
- LLM 不可用或返回不合格结构时，允许规则兜底，但候选必须记录 `review.llm_assist.status=rule_fallback_after_llm`。
- 用户或测试显式关闭 LLM 时，候选必须记录 `review.llm_assist.status=rule_only_disabled_by_request`。
- 如果 LLM/正式知识比对认为已经高度覆盖，不能重复升级为待确认知识。

禁止：

- AI 抽取直接跳过候选库写正式知识。
- RAG-only 内容直接授权高风险业务规则。
- 群聊中未经确认的价格、合同、赔付、账期、发票等内容自动变成正式知识。

允许：

- 完整候选标记为“已完善”。
- RAG 经验一键生成“RAG生成”候选。
- 用户补全“待完善”候选后晋升。
- 用户手动晋升后，正式知识带新加入标识。

## 6. 后台页面需求

### 6.1 共享页面改造

知识库页面：

- 正式知识列表显示“新加入/有更新”。
- 详情页显示来源、候选 ID、RAG 经验 ID、原始消息 ID。
- 提供“已阅”按钮。

候选页面：

- 显示“已完善/待完善/RAG生成/微信私聊/微信群聊”等标识。
- 支持按标识过滤。
- 待完善候选保留补全表单。
- 已完善候选突出“可晋升”，但仍需用户点击。

导出入口：

- 在备份还原或知识库页面提供“导出可读知识表”。
- 生成与服务端客户数据包一致的 xlsx。

### 6.2 记录员专属页面

新增页面：智能记录员。

包含：

- 总览：今日消息、会话数、群聊数、候选数、待完善数、RAG 经验数、失败任务数。
- 会话选择：扫描会话、群聊列表、私聊列表、启用/停用。
- 原始消息：按会话、成员、时间、关键词过滤。
- 摄入任务：查看、重试、跳过。
- 设置：总开关、提示、学习开关、保留周期。
- 导出：跳转或调用统一可读知识表导出。

## 7. Excel 导出需求

导出必须和服务端可读知识表一致。

本地后台导出 API 建议：

- `POST /api/export/customer-readable/package`
- `GET /api/export/customer-readable/{package_id}/download`

实现思路：

1. 调用现有 `BackupService.build_backup(scope="tenant")` 生成当前租户数据包。
2. 调用 `build_customer_readable_workbook(package, package_path)` 生成 xlsx。
3. 返回下载地址或直接 FileResponse。

排序参数：

- `sort_by=type`：保持现有按 sheet 分类。
- `sort_by=time`：新增“按时间汇总” sheet，按 created_at/updated_at 倒序。

## 8. 验收标准

### 8.1 共享能力

1. 自动客服和记录员均可写入统一 raw message store。
2. 同一微信消息重复轮询不重复入库。
3. 候选列表能显示已完善、待完善、RAG生成、微信私聊、微信群聊标识。
4. 已完善候选不会自动写正式库，必须手动晋升。
5. 晋升后的正式知识显示新加入标识。
6. 点击已阅后，新加入标识消失，但审计信息保留。
7. 本地后台可导出与服务端可读知识表一致的 xlsx。

### 8.2 记录员模块

1. 后台能扫描当前微信会话。
2. 后台列出可能的群聊，用户可选择记录哪些群。
3. 被选中的群聊消息会写入原始消息库。
4. 被选中的私聊消息会写入原始消息库。
5. 未选择的群聊不会被记录。
6. 记录消息可生成 RAG chat_log source。
7. 记录消息可生成候选知识，候选带来源和 message_ids。
8. 收录提示关闭时不发消息。
9. 收录提示开启时按限流发送。

## 9. 后续开发文档依赖

开发文档应以本 V2.0 为准，按以下边界拆分：

- 共享基础：raw message store、candidate badge、formal unread marker、export。
- 记录员新增：session scan、conversation selection、recorder polling、recorder page。
- 回归测试：共享服务测试、记录员离线测试、admin backend 检查、前端语法检查。
