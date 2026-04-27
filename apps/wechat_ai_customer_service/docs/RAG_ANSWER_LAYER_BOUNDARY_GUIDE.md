# RAG 应答层边界说明

## 定位

RAG 应答层位于 `intent_assist` 之后、DeepSeek 候选接管之前。它只把已经检索到的非结构化资料片段整理成“可参考”的客服话术，不改变结构化知识的最高优先级。

## 可自动回复的场景

- 客户描述的是软场景、选型思路、规格理解、轻度闲聊等，不涉及明确交易承诺。
- `intent_assist.evidence.rag_hits` 中存在可用片段，且片段没有高风险词。
- 当前没有客户资料录入、商品专属人工确认、证据安全拦截。
- 默认只接管未匹配结构化规则的软问题；已命中商品/政策主档时不覆盖。

## 必须阻断或转人工的场景

- 价格、优惠、库存、发货、开票、付款、售后争议、合同、账期、客户资料录入。
- RAG 命中的片段包含“最低价、账期、月结、赔偿、退款、合同、安装费、先发货、虚开发票”等风险表达。
- 结构化安全层已经标记 `must_handoff=true`。
- RAG 只是命中旧聊天或原始资料，但没有结构化规则授权。

## 配置入口

配置文件新增顶层 `rag_response`：

```json
{
  "rag_response": {
    "enabled": true,
    "apply_to_unmatched": true,
    "apply_to_matched_product": false,
    "apply_to_small_talk": false,
    "skip_llm_after_apply": true,
    "min_hit_score": 0.12,
    "max_reply_chars": 220,
    "max_snippet_chars": 130
  }
}
```

## 测试命令

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_boundary_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_boundary_matrix_checks.py
```

## 设计原则

RAG 可以增加上下文和人情味，但不能替代结构化授权。客服最终回答的优先级为：客户资料/人工拦截 > 商品和政策结构化知识 > 受控 RAG 应答 > DeepSeek 边界候选 > 默认转人工。
