# RAG 层运行与验收指南

## 运行定位

RAG 层用于辅助理解和检索原始资料，不是正式业务规则源。

正式回复决策仍由：

- `shared_knowledge`
- `tenants/<tenant_id>/knowledge_bases`
- `tenants/<tenant_id>/product_item_knowledge`

共同决定。

## 常用操作

### 查看 RAG 状态

```http
GET /api/rag/status
```

返回：

- source 数量
- chunk 数量
- index 是否存在
- 最近更新时间
- tenant id

### 检索 RAG

```http
POST /api/rag/search
{
  "query": "门锁适合酒店公寓吗",
  "product_id": "fl-920",
  "limit": 5
}
```

### 重建索引

```http
POST /api/rag/rebuild
```

## 安全验收

RAG 检索结果不得直接授权：

- 更低价格。
- 账期、月结、先货后款。
- 退款赔偿。
- 合同盖章。
- 安装费用和上门时效。
- 发货时效承诺。
- 产品效果保证。

命中这些场景时，系统必须回到结构化规则或转人工。

## 故障判断

### 有文件但搜不到

检查：

- 上传文件是否已经执行 AI 学习任务。
- `rag_chunks` 中是否生成 chunk。
- `rag_index/index.json` 是否存在。
- 搜索是否带了错误的 `product_id` 过滤。

### 候选审核没有证据片段

检查：

- 学习任务是否启用了 RAG ingest。
- 上传文件是否可读。
- chunk 是否为空。
- 候选是否来自手动生成器而不是上传文件。

### RAG 命中但客服没自动回答

这是预期行为的一部分。RAG 只能补证据，不能绕过结构化安全规则。

## 验收清单

- RAG 源文件可登记。
- 文本可切块。
- 索引可重建。
- 检索结果有分数和来源。
- 候选审核能看到 RAG evidence。
- 运行时 evidence pack 能包含 RAG evidence。
- RAG-only 高风险内容不自动拍板。
- 旧结构化客服回归不退化。
- 文件传输助手实盘回归通过。

