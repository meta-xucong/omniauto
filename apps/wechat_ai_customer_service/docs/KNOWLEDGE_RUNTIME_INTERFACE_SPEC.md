# 分类知识库运行时接口契约

本文档定义微信客服流程如何直接使用分类知识库。目标是让客服运行时从根源上适配新结构，而不是通过旧大 JSON 打补丁。

## 1. 运行时原则

- 正式知识源是 `data/knowledge_bases`。
- `compiled` 只是缓存、兼容导出或测试辅助。
- 客服主流程通过 `KnowledgeRuntime` 获取证据。
- 所有回复、LLM、转人工、数据采集都基于分类 evidence pack。
- 审计日志必须记录命中的门类和知识条目。

## 2. 核心组件

### KnowledgeRegistry

职责：

- 读取 `registry.json`。
- 列出启用门类。
- 判断门类是否参与回复、学习、检测。
- 创建自定义门类时更新注册表。

建议接口：

```python
class KnowledgeRegistry:
    def list_categories(self, enabled_only: bool = True) -> list[Category]
    def get_category(self, category_id: str) -> Category
    def create_custom_category(self, spec: CategoryCreate) -> Category
```

### KnowledgeBaseStore

职责：

- 按门类读取 item。
- 按门类写入 item。
- 提供搜索和列表。
- 保证 item 不跨目录混放。

建议接口：

```python
class KnowledgeBaseStore:
    def list_items(self, category_id: str) -> list[KnowledgeItem]
    def get_item(self, category_id: str, item_id: str) -> KnowledgeItem | None
    def save_item(self, category_id: str, item: KnowledgeItem) -> SaveResult
    def archive_item(self, category_id: str, item_id: str) -> SaveResult
```

### KnowledgeIndex

职责：

- 读取所有启用门类。
- 根据 resolver 构建关键词、别名、意图、风险索引。
- 支持增量重建和全量重建。

建议接口：

```python
class KnowledgeIndex:
    def rebuild(self, category_ids: list[str] | None = None) -> IndexReport
    def search(self, text: str, context: ConversationContext) -> list[KnowledgeHit]
```

### EvidenceResolver

职责：

- 根据客户消息和上下文查找证据。
- 输出分类 evidence pack。
- 标记安全边界和转人工原因。

建议接口：

```python
class EvidenceResolver:
    def resolve(self, text: str, context: ConversationContext) -> EvidencePack
```

### ReplyPlanner

职责：

- 根据 evidence pack 决定下一步动作。
- 生成确定性回复或 LLM 输入。
- 遵守安全边界。

建议接口：

```python
class ReplyPlanner:
    def plan(self, message_batch: list[Message], evidence: EvidencePack, context: ConversationContext) -> ReplyPlan
```

## 3. EvidencePack 格式

```json
{
  "schema_version": 1,
  "text": "客户原始消息",
  "matched_categories": ["products", "policies"],
  "evidence_items": [
    {
      "category_id": "products",
      "item_id": "commercial_fridge_bx_200",
      "title": "商用冰箱 BX-200",
      "matched_fields": ["aliases", "shipping_policy"],
      "match_reason": "product_alias_and_shipping_intent",
      "confidence": 0.88,
      "reply_excerpt": "48 小时内发货，江浙沪包邮。",
      "allow_auto_reply": true,
      "requires_handoff": false,
      "risk_level": "normal"
    }
  ],
  "safety": {
    "allowed_auto_reply": true,
    "must_handoff": false,
    "reasons": []
  },
  "context": {
    "last_product_id": "commercial_fridge_bx_200"
  }
}
```

要求：

- `category_id` 和 `item_id` 必须可追溯到实际文件。
- `reply_excerpt` 只放必要片段，避免 LLM 上下文过大。
- 高风险证据必须把 `must_handoff` 置为 true。
- 无业务证据的问题必须标记 `no_relevant_business_evidence`。

## 4. ReplyPlan 格式

```json
{
  "schema_version": 1,
  "action": "send_reply",
  "reply_text": "可发送给客户的话",
  "reply_source": "deterministic",
  "llm_used": false,
  "handoff": {
    "required": false,
    "reason": ""
  },
  "data_capture": {
    "detected": false,
    "complete": false,
    "fields": {}
  },
  "audit": {
    "category_ids": ["products"],
    "item_ids": ["commercial_fridge_bx_200"],
    "safety_reasons": []
  }
}
```

允许的 `action`：

- `send_reply`
- `handoff_sent`
- `skip`
- `write_data`
- `rate_limited`
- `error`

## 5. LLM 调用契约

LLM 只能看到：

- 客户消息；
- 最近上下文；
- evidence pack 摘要；
- 客服人设；
- 禁止承诺规则；
- 输出 schema。

LLM 不允许：

- 直接读取全量知识库；
- 修改正式知识；
- 绕过 `requires_handoff`；
- 自行承诺价格、账期、退款、赔偿、违规开票、合同盖章。

LLM 输出必须包含：

- `recommended_action`
- `reply_text`
- `safe_to_auto_send`
- `needs_handoff`
- `confidence`
- `evidence_item_ids`
- `risk_notes`

## 6. 审计日志要求

每次处理消息必须记录：

- 目标联系人；
- 消息 ID；
- action；
- reply_source；
- LLM 是否使用；
- 命中的 `category_id`；
- 命中的 `item_id`；
- 命中的字段；
- safety reasons；
- handoff reason；
- 是否写入客户资料；
- 是否触发速率限制。

## 7. 兼容策略

迁移期允许：

- 从 `knowledge_bases` 编译出旧格式；
- 旧测试读取 compiled；
- 管理台提供开发者模式查看 compiled。

不允许：

- 客服主流程只读取旧 `product_knowledge.example.json`；
- 新功能直接写旧 structured 文件；
- 自定义门类只存在前端，不进入运行时。

