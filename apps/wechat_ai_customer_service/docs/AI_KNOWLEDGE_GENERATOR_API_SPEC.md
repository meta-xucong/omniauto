# AI 知识生成器接口与状态机

## 概念

AI 知识生成器负责把自然语言描述转成分类知识库条目。它是一个会话式生成器，不是 JSON 草稿编辑器。

会话状态：

- `collecting`: 已识别部分信息，但缺关键字段，需要继续追问。
- `ready`: 信息足够，等待用户确认保存。
- `saved`: 已写入正式知识库。
- `error`: 解析或校验失败，需要用户修改输入。

## API

### 创建会话

`POST /api/generator/sessions`

请求：

```json
{
  "message": "新增商品：200L 商用冷柜，单价1999元，10台以上1880元",
  "preferred_category_id": "",
  "use_llm": true
}
```

响应：

```json
{
  "ok": true,
  "session": {
    "session_id": "gen_20260426_xxxxxx",
    "status": "ready",
    "category_id": "products",
    "category_name": "商品资料",
    "question": "",
    "missing_fields": [],
    "draft_item": {},
    "summary_rows": [],
    "warnings": [],
    "provider": "deepseek"
  }
}
```

### 继续补充

`POST /api/generator/sessions/{session_id}/messages`

请求：

```json
{
  "message": "型号 BX-200，库存 18 台，默认 24 小时内发货"
}
```

响应同创建会话。后端会把新回答合并到旧草稿。

### 确认保存

`POST /api/generator/sessions/{session_id}/confirm`

响应：

```json
{
  "ok": true,
  "session": {"status": "saved"},
  "item": {},
  "compile": {}
}
```

只有 `ready` 状态允许保存。保存后写入对应分类 `items/` 目录。

## DeepSeek 提示词原则

系统提示词必须说明：

1. 你是微信客服知识库整理员，不是直接对客户回复。
2. 只能输出 JSON，不能输出解释性段落。
3. 必须根据分类 schema 抽取字段。
4. 不确定的信息不要编造，放入 `missing_fields`。
5. 高风险承诺、账期、赔偿、免单、虚开发票等必须输出 warning。
6. 如果用户描述不属于已知分类，选择最接近分类或建议 `custom`。

模型输出结构：

```json
{
  "category_id": "products",
  "confidence": 0.86,
  "item_id_hint": "commercial_fridge_bx_200",
  "data": {},
  "missing_fields": [],
  "followup_question": "",
  "warnings": [],
  "summary_rows": []
}
```

## 确定性兜底

当 DeepSeek 未配置、超时或返回非 JSON 时，后端使用规则解析：

- 出现“商品、价格、型号、库存、发货、规格”等，归入 `products`。
- 出现“开票、付款、合同、售后、退换、物流规则、人工”等，归入 `policies`。
- 出现“客户说、客服说、话术、聊天、怎么回复”等，归入 `chats`。
- 出现“ERP、订单、字段、导出、客户资料”等，归入 `erp_exports`。

兜底解析只填有把握的字段，并返回 provider=`heuristic`。

## 后端硬校验

生成器保存前必须调用分类知识库校验，并额外执行：

- 产品阶梯价格：每一档数量必须高于上一档，价格必须低于上一档。
- 金额字段必须是非负数字。
- 必填字段不能为空。
- 高风险内容必须设置 `requires_handoff=true` 或 risk warning。
- item ID 自动生成时必须稳定、安全、可读。

## 前端交互

生成器页面包含：

- 自然语言输入框。
- 会话消息区。
- AI 追问区。
- 识别出的门类、置信度、风险提醒。
- 总览表。
- 确认保存按钮。

用户无需理解 JSON。只有当状态为 `ready` 时，保存按钮可用。

