# 微信客服与 AI 智能记录员统一知识流转方案 V3.0

## 1. 结论

建议采用统一路径：

```text
原始内容
  -> AI 大模型思考与归纳
  -> RAG 经验
  -> 待确认知识
  -> 人工晋升正式知识
  -> 可选推送为共享公共知识候选
  -> admin 审核共享公共知识
  -> admin 手动推送版本更新到客户端
```

这条路径比当前“上传资料、记录员、RAG 经验、AI 生成器都可能直接生成候选”的混合模式更清晰，也更安全。正式知识仍然只允许人工确认后生效；AI 只能做整理、归纳、候选生成和风险提示。

补充强制规则：所有自动学习入口都必须先执行“LLM 辅助判断”步骤。LLM 负责业务理解、分类、字段抽取、适用范围、风险、与正式知识库重合度判断；LLM 不可用、输出不合格或被明确关闭时，才允许进入规则兜底。规则兜底结果必须在候选 `review.llm_assist` 中标明，不得伪装成大模型判断。

## 2. 当前现状与问题

当前系统已经具备以下能力：

- 上传资料会进入 raw inbox，并摄入 RAG source/chunk。
- 自动客服和记录员会写入统一原始消息库。
- 原始消息批次会摄入 RAG source/chunk。
- 上传资料和原始消息可以直接生成待确认知识。
- RAG 经验列表存在，但当前二手车测试租户中 `experience_counts.total=0`。

问题在于：

- RAG source/chunk 是“可检索资料层”，不是“LLM 思考后的经验层”。
- 待确认知识既可能来自上传资料，也可能来自记录员，也可能来自后续 RAG 经验，入口过多。
- “AI参考资料 / 对话中学到的经验”没有承接聊天记录，因此用户会看到记录员有聊天、候选库有候选，但经验层为空。
- 候选可以绕过“RAG 经验”直接出现，导致知识成长链路不直观。

## 3. 目标分层

### 3.1 原始内容层

只负责保存事实，不做业务判断。

来源包括：

- 文件上传。
- 自动客服私聊。
- AI 智能记录员私聊。
- AI 智能记录员群聊。
- 文件传输助手。
- 手动粘贴或导入聊天记录。

输出：

- `raw_messages`
- `raw_message_batches`
- `raw_uploads`
- `rag_sources`
- `rag_chunks`

### 3.2 AI 思考层 / RAG 经验层

这是 V3 的统一中间层。所有原始内容都应先经过该层。

职责：

- 优先用 LLM 从原始内容中总结“可复用经验”；受控规则只能作为 LLM 不可用或输出无效时的兜底。
- 保留证据片段、来源入口、可信度、适用范围和风险。
- 明确哪些只是资料片段，哪些可形成经验，哪些可尝试结构化。
- 对照正式知识库，标明高度重合、部分相近、疑似冲突或全新内容。

输出：

- `rag_experience`
- 经验状态：`active | discarded | promoted`
- 经验关系：`raw_source_id`、`raw_batch_id`、`candidate_ids`

### 3.3 待确认知识层

只能从 RAG 经验生成。

规则：

- 候选生成前必须先经过 LLM 辅助判断，候选详情必须展示 `llm_assist` 状态。
- 字段完整：标记“已完善”，但仍需人工点击应用。
- 字段缺失：标记“待完善”，用户补全后才允许应用。
- 来自 RAG 经验：标记“RAG生成”。
- 保留原始来源：文件上传、记录员群聊、文件传输助手、客服私聊等。
- 如果 LLM 或正式库比对判断“已高度覆盖”，禁止重复生成待确认知识。

### 3.4 正式知识层

只接受人工晋升。

规则：

- 写入前创建版本快照。
- 写入后记录审计日志。
- 新增或更新知识显示“新加入/未阅”。
- 用户点击“已阅”后才取消醒目标识。

### 3.5 共享公共知识层

这是跨账号共享的二级审核链路。

流程：

1. 每个客户账号内部产生 RAG 经验。
2. LLM 从多个账号经验中识别普适知识。
3. 普适知识只推送到服务端“共享公共知识候选”。
4. admin 审核后才进入共享公共知识库。
5. admin 手动发起版本推送。
6. 客户端拉取新版本后合并到本地共享知识层。

## 4. UI 调整原则

待确认知识必须同时展示：

- 完善状态：已完善、待完善。
- 来源入口：知识录入与学习、AI 智能记录员、AI参考资料。
- 来源通道：导入资料、微信群聊、微信私聊、文件传输助手、RAG经验、AI生成器。
- 风险状态：需人工确认、疑似重复、可晋升。

“待确认知识”入口显示红色数量角标，数量等于当前租户 pending candidates。

AI参考资料页面应改名或分区得更清楚：

- “已导入资料”：RAG source/chunk，可检索证据。
- “AI归纳经验”：LLM 从原始内容中总结出的经验。
- “可升级知识”：从经验中提取出的候选关系。

## 5. 需要收敛的代码路径

### 5.1 上传资料

当前：

```text
upload -> rag source/chunk -> build_candidates -> pending candidates
```

目标：

```text
upload -> rag source/chunk -> build_rag_experience -> promote_experience_candidates -> pending candidates
```

### 5.2 记录员与客服聊天

当前：

```text
raw messages -> transcript -> rag source/chunk -> build_candidates -> pending candidates
```

目标：

```text
raw messages -> transcript -> rag source/chunk -> build_rag_experience -> promote_experience_candidates -> pending candidates
```

### 5.3 AI 生成器

当前可以直接形成结构化草稿。

目标：

- 仍可作为人工录入辅助工具。
- 但若作为“学习入口”，应先生成 RAG 经验，再从经验生成候选。
- 明确区分“用户手动新增正式知识”和“AI 从资料学习生成候选”。

## 6. 迁移计划

### Phase A - 先补观测与提示

已完成：

- 待确认知识显示红色数量角标。
- 候选知识显示来源摘要。
- 文件上传、微信群聊、文件传输助手等来源打标。
- 长标题和长 ID 防溢出。

### Phase B - 经验层补齐

新增统一服务：

- `RagExperienceBuilder`
- `RawContentExperienceJob`
- `ExperiencePromotionService`

让上传资料和 raw message 学习都先产出 `rag_experience`。

### Phase C - 禁止直达候选

将 `learning_service` 和 `raw_message_learning_service` 中的直接 `build_candidates(...)` 改为：

- 创建 RAG 经验。
- 从经验创建候选。
- 候选 `source.type=rag_experience`。
- 候选 `source.original_channel` 保留原始入口。

### Phase D - 共享公共知识候选

新增服务端候选池：

- `shared_public_candidates`
- `shared_public_candidate_reviews`
- `shared_public_release_batches`

admin 审核后才进入共享公共知识，并手动推送版本。

## 7. 验收标准

- 上传资料后，AI参考资料的“AI归纳经验”不再为空。
- 记录员捕获聊天后，先生成 RAG 经验，再由经验生成候选。
- 待确认知识中的每条候选都有 RAG 经验 ID 和原始来源摘要。
- 没有任何 AI 自动写入正式知识。
- admin 未确认前，没有任何客户知识进入共享公共知识。
- admin 未手动推送前，客户端不会自动获得共享公共知识更新。
