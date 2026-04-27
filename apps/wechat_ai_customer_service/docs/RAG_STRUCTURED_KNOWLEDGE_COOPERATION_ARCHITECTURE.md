# RAG 与结构化知识协作架构

## 目标

微信 AI 客服的正式答案来源仍然是三层结构化知识：

1. `data/shared_knowledge`：所有客户可共享的通用客服知识。
2. `data/tenants/<tenant_id>/knowledge_bases`：某个客户自己的通用政策、商品主档、话术和 ERP 知识。
3. `data/tenants/<tenant_id>/product_item_knowledge/<product_id>`：某个商品自己的 FAQ、规则和解释资料。

RAG 层不是替代这些正式知识，而是提供“资料检索增强”：

- 帮知识生成器理解原始文件、聊天记录、说明书和 ERP 导出。
- 帮候选审核展示来源证据。
- 在客服运行时补充模糊问题的背景证据。
- 发现应该沉淀为正式结构化知识的候选内容。

## 核心原则

### 结构化知识是决策源

以下内容必须以结构化知识为准：

- 商品价格、阶梯价、起订量、单位。
- 发货时效、包邮规则、物流费用。
- 开票主体、对公账户、付款规则。
- 售后、退换、赔偿、安装、合同、账期。
- 是否允许自动回复、是否必须转人工。

RAG 命中的原始资料不能直接授权这些决策。若 RAG 与结构化知识冲突，结构化知识优先。

### RAG 是证据和候选来源

RAG 可用于：

- 检索产品说明书里的使用场景、安装注意事项、常见问答。
- 检索聊天记录里的真实客服表达风格。
- 检索政策文档里的长段落说明。
- 给 AI 知识生成器提供证据片段。
- 给候选审核提供“来源证据”。

### RAG-only 不直接拍板

如果某个问题只有 RAG 证据，没有结构化知识确认：

- 普通解释性问题可以谨慎回答，并说明“按资料显示”。
- 涉及价格、优惠、赔偿、合同、账期、安装费用、发货承诺等高风险内容时，必须转人工。
- 可以生成候选知识，等待人工审核后进入正式知识库。

## 新增目录

每个租户下新增 RAG 辅助层目录：

```text
data/tenants/<tenant_id>/
├─ knowledge_bases/
├─ product_item_knowledge/
├─ rag_sources/
│  ├─ uploads/
│  ├─ chat_logs/
│  ├─ product_docs/
│  ├─ policy_docs/
│  └─ erp_exports/
├─ rag_chunks/
├─ rag_index/
└─ rag_cache/
```

目录用途：

- `rag_sources`：保存原始资料的索引记录，不复制正式上传文件，记录来源路径、资料类型、关联商品和状态。
- `rag_chunks`：保存从资料中切分出来的文本块。
- `rag_index`：保存本地可搜索索引。第一阶段使用离线确定性的关键词/混合检索，后续可替换或叠加向量索引。
- `rag_cache`：保存热门问题的检索结果缓存，后续用于降低重复检索成本。

## Chunk 元数据

每个 chunk 必须包含：

```json
{
  "chunk_id": "chunk_xxx",
  "source_id": "source_xxx",
  "tenant_id": "default",
  "layer": "tenant",
  "source_type": "upload|chat_log|product_doc|policy_doc|erp_export",
  "category": "products|policies|chats|erp_exports|product_faq|product_rules|product_explanations",
  "product_id": "fl-920",
  "text": "原始片段文本",
  "source_path": "D:/...",
  "created_at": "2026-04-27T19:00:00+08:00",
  "status": "active"
}
```

## 运行时协作流程

客户发来消息后：

1. 识别意图、商品、上下文。
2. 优先检索结构化知识。
3. 如果结构化知识已足够，直接回复，不调用 RAG。
4. 如果问题模糊、需要解释、或结构化证据不足，按需检索 RAG。
5. 合并为 evidence pack。
6. 执行安全决策：
   - 商品专属结构化知识优先。
   - 客户专属结构化知识次之。
   - 平台共享结构化知识再次之。
   - RAG 只补充证据和解释。
   - 冲突或高风险时转人工。

## Evidence Pack 扩展

RAG evidence 应作为独立字段进入证据包：

```json
{
  "structured_evidence": {},
  "rag_evidence": {
    "enabled": true,
    "query": "客户原文",
    "hits": [],
    "confidence": 0.72,
    "structured_priority": true,
    "rag_can_authorize": false
  },
  "safety": {}
}
```

`rag_can_authorize` 第一阶段固定为 `false`，表示 RAG 不具备最终业务授权能力。

## 管理台协作

资料上传后：

```text
上传文件
-> 保存 raw_inbox
-> 建立 RAG source/chunk/index
-> AI 生成候选知识
-> 候选审核显示 RAG 来源片段
-> 人工补充或改分类
-> 应用入正式结构化库
-> 重新编译运行时缓存
```

## 后续可演进

第一阶段先实现离线关键词/混合检索，保证无需额外服务也能测试。

第二阶段可增加：

- embedding provider 配置。
- Qdrant / pgvector。
- tenant namespace。
- 向量索引重建任务。
- 真实聊天记录风格检索。
- 高频 RAG 命中自动生成候选知识。

