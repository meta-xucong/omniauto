# 受控 LLM 客服综合回复开发文档

## 1. 背景

真实微信客户不会按知识库字段提问。客户可能说“我老婆接娃开，别太费油，有没有靠谱的”“刚才那台还能不能再聊点”“外地看车是不是很麻烦”。这些问题需要大模型理解上下文、联系 RAG 经验和正式知识，再组织成自然客服回复。

现有系统已经具备结构化知识、RAG 经验、边界判断、人工兜底和知识晋升链路。本次改造不推翻这些成果，只新增一个受控的 LLM 客服综合回复层。

## 2. 设计原则

- 新模块只增强，不替代现有链路。
- 现有结构化知识、RAG、规则回复、人工兜底继续先执行。
- RAG 必须作为 LLM 综合回复的重要证据输入，但未确认 RAG 不能越权承诺价格、库存、金融、车况、合同、售后。
- LLM 可以理解、归纳、改写和组织语言，不能凭空新增业务事实。
- 客户专属正式知识优先于共享公共知识。
- 商品专属规则优先于泛用话术。
- 任何失败、超时、低置信度、越界或证据不足，都回退到现有回复或转人工。

## 3. 新增模块

### 3.1 `reply_evidence_builder.py`

负责构建给 LLM 的证据包：

- 当前客户问题。
- 当前批次消息。
- 最近聊天上下文。
- 现有规则回复。
- 旧 LLM advisory 结果。
- 商品库命中。
- 正式知识命中。
- 商品专属问答、规则、解释。
- RAG 经验命中。
- 安全边界判断。

重点：RAG 命中必须保留 `chunk_id`、`source_id`、`score`、`source_type`、`product_id`、`text`，方便审计“LLM 是否真的参考了 RAG”。

### 3.2 `llm_reply_synthesis.py`

负责调用大模型，让它输出结构化结果：

```json
{
  "can_answer": true,
  "reply": "自然客服回复",
  "confidence": 0.86,
  "recommended_action": "send_reply",
  "needs_handoff": false,
  "used_evidence": ["product:chejin_camry_2021_20g", "rag:rag_chunk_xxx"],
  "rag_used": true,
  "structured_used": true,
  "uncertain_points": ["最终成交价需人工确认"],
  "risk_tags": ["price_sensitive"],
  "reason": "用户询问同一台车的适用场景和看车安排，商品库和RAG均有证据"
}
```

### 3.3 `llm_reply_guard.py`

负责最终安全裁决：

- 权威类问题必须有正式结构化证据，RAG 只能辅助解释。
- 无正式证据时，LLM 不能承诺价格、库存、金融审批、车况结论、合同、售后。
- 原链路已判定必须转人工时，LLM 不能覆盖。
- 置信度不足、回复为空、模型输出格式错误时，回退旧逻辑。
- LLM 建议转人工时，使用现有人工兜底回复，不直接发送模型自写承诺。

## 4. 新回复链路

```text
微信消息
  -> 原始消息记录
  -> 商品/正式知识/RAG 检索
  -> 现有规则回复
  -> 现有 RAG 短回复层
  -> 现有 LLM advisory
  -> 新增 LLM 综合回复证据包
  -> 新增 LLM 综合回复
  -> 新增安全 guard
  -> 通过则发送综合回复
  -> 不通过则回退旧回复或转人工
```

## 5. 配置

新增配置段：

```json
{
  "llm_reply_synthesis": {
    "enabled": true,
    "provider": "deepseek",
    "mode": "guarded_auto",
    "shadow_mode": false,
    "require_evidence": true,
    "require_structured_for_authority": true,
    "max_history_messages": 40,
    "history_char_budget": 12000,
    "max_rag_hits": 5,
    "min_confidence": 0.62,
    "fallback_to_existing_reply": true,
    "include_prompt_in_audit": false
  }
}
```

上线建议：

- 测试期可以使用 `shadow_mode=true`，只记录大模型建议，不发送。
- 正式期使用 `guarded_auto`，通过安全 guard 后才发送。
- 客服控制台的“使用 LLM”开关应同时控制 raw learning、intent advisory 和 reply synthesis。

## 6. 测试要求

离线测试必须覆盖：

- 拟人化二手车自然问题。
- 多轮上下文指代，例如“刚才那台”“这个再便宜点呢”。
- RAG 命中参与综合回复。
- RAG 不能独立授权价格、金融、车况、售后。
- 商品正式知识优先于共享公共知识。
- 模型输出非法 JSON 时安全回退。
- 模型建议转人工时走现有人工兜底。
- LLM 关闭时旧逻辑完全不变。

实盘测试必须在离线测试全部通过后进行。

