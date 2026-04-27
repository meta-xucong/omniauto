# 分类知识库 Schema 规范

本文档定义分类知识库的正式数据格式。后续后端、微信客服运行时、迁移脚本、AI 学习、表单前端都必须遵守本规范。

## 1. 根目录

```text
apps/wechat_ai_customer_service/data/knowledge_bases/
  registry.json
  products/
    schema.json
    resolver.json
    items/
  chats/
    schema.json
    resolver.json
    items/
  policies/
    schema.json
    resolver.json
    items/
  erp_exports/
    schema.json
    resolver.json
    items/
  custom/
    <category_id>/
      schema.json
      resolver.json
      items/
```

规则：

- 一个门类一个目录。
- 一个知识条目一个 JSON 文件。
- 文件名默认使用 `item_id.json`。
- 自定义门类必须位于 `custom/<category_id>`。
- 正式读写不得把不同门类 item 混在同一目录。

## 2. registry.json

示例：

```json
{
  "schema_version": 1,
  "updated_at": "2026-04-26T16:00:00+08:00",
  "categories": [
    {
      "id": "products",
      "name": "商品资料",
      "kind": "builtin",
      "path": "products",
      "enabled": true,
      "participates_in_reply": true,
      "participates_in_learning": true,
      "participates_in_diagnostics": true,
      "sort_order": 10
    }
  ]
}
```

字段说明：

- `id`：门类 ID，使用小写字母、数字、下划线、短横线。
- `name`：用户可读名称。
- `kind`：`builtin` 或 `custom`。
- `path`：相对 `knowledge_bases` 的目录。
- `enabled`：是否启用。
- `participates_in_reply`：是否参与微信客服回复证据检索。
- `participates_in_learning`：是否允许 AI 学习写候选。
- `participates_in_diagnostics`：是否参与检测。
- `sort_order`：前端显示顺序。

## 3. schema.json

每个门类必须有 schema。

示例：

```json
{
  "schema_version": 1,
  "category_id": "products",
  "display_name": "商品资料",
  "description": "用于商品匹配、报价、规格、库存、物流和售后。",
  "item_title_field": "name",
  "item_subtitle_field": "sku",
  "fields": [
    {
      "id": "name",
      "label": "商品名称",
      "type": "short_text",
      "required": true,
      "searchable": true,
      "form_order": 10
    },
    {
      "id": "aliases",
      "label": "客户常用叫法",
      "type": "tags",
      "required": false,
      "searchable": true,
      "form_order": 20
    }
  ],
  "validation": {
    "unique_fields": ["id"],
    "unique_tag_fields": ["aliases"],
    "required_for_auto_reply": ["name"]
  }
}
```

支持字段类型：

- `short_text`
- `long_text`
- `number`
- `money`
- `boolean`
- `single_select`
- `multi_select`
- `tags`
- `table`
- `object`
- `attachment`
- `relation`

字段通用属性：

- `id`
- `label`
- `type`
- `required`
- `default`
- `placeholder`
- `help_text`
- `searchable`
- `form_order`
- `options`
- `columns`
- `relation_category`
- `diagnostics`

## 4. resolver.json

每个门类必须有 resolver，用于运行时检索。

示例：

```json
{
  "schema_version": 1,
  "category_id": "products",
  "match_fields": ["name", "aliases", "sku", "category"],
  "intent_fields": ["reply_templates", "risk_rules"],
  "risk_fields": ["risk_rules"],
  "reply_fields": ["reply_templates"],
  "minimum_confidence": 0.45,
  "default_action": "answer_from_evidence"
}
```

规则：

- `match_fields` 决定哪些字段参与关键词、别名、模糊匹配。
- `risk_fields` 决定哪些字段参与安全边界判断。
- `reply_fields` 决定哪些字段可以进入自动回复或 LLM 上下文。
- 自定义门类如果参与客服回复，必须配置 resolver。

## 5. item 文件通用外壳

每条知识建议使用统一外壳：

```json
{
  "schema_version": 1,
  "category_id": "products",
  "id": "commercial_fridge_bx_200",
  "status": "active",
  "source": {
    "type": "migration",
    "path": "data/structured/product_knowledge.example.json"
  },
  "data": {},
  "runtime": {
    "allow_auto_reply": true,
    "requires_handoff": false,
    "risk_level": "normal"
  },
  "metadata": {
    "created_at": "2026-04-26T16:00:00+08:00",
    "updated_at": "2026-04-26T16:00:00+08:00",
    "created_by": "migration",
    "updated_by": "migration"
  }
}
```

规则：

- `data` 中放业务字段。
- `runtime` 中放客服运行时决策字段。
- `metadata` 中放版本、时间、来源。
- 删除优先使用 `status=archived`，不要直接物理删除，除非是测试清理。

## 6. 默认门类字段

### products

必备字段：

- `name`
- `aliases`
- `category`
- `sku`
- `specs`
- `price`
- `price_tiers`
- `inventory`
- `shipping_policy`
- `warranty_policy`
- `reply_templates`
- `risk_rules`

### chats

必备字段：

- `customer_message`
- `service_reply`
- `intent_tags`
- `tone_tags`
- `linked_categories`
- `linked_item_ids`
- `usable_as_template`

### policies

必备字段：

- `title`
- `policy_type`
- `keywords`
- `answer`
- `allow_auto_reply`
- `requires_handoff`
- `handoff_reason`
- `operator_alert`
- `risk_level`

### erp_exports

必备字段：

- `source_system`
- `record_type`
- `external_id`
- `fields`
- `sync_status`

## 7. 自定义门类

创建自定义门类时必须生成：

```text
custom/<category_id>/schema.json
custom/<category_id>/resolver.json
custom/<category_id>/items/.gitkeep
```

限制：

- `category_id` 不得与默认门类重名。
- 默认不参与客服回复，除非用户显式开启。
- 开启客服回复前必须配置至少一个 `match_fields`。
- 开启自动回复前必须配置 `reply_fields`。
- 自定义字段不能使用系统保留名：`schema_version`、`category_id`、`id`、`status`、`source`、`data`、`runtime`、`metadata`。

## 8. 校验要求

基础校验：

- JSON 可解析；
- schema 字段 ID 唯一；
- item ID 唯一；
- 必填字段完整；
- 字段类型正确；
- relation 指向存在；
- resolver 引用字段存在。

业务校验：

- 自动回复条目必须有可用回复字段；
- `requires_handoff=true` 时必须有 `handoff_reason`；
- 高风险政策不得被一键自动修复；
- 商品别名不得跨商品重复；
- 价格阶梯不得自相矛盾。

