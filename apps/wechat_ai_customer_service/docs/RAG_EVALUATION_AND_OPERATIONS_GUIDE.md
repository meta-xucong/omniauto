# RAG 评估与运营指南

## 固定评估集

RAG 每次升级后必须跑固定评估集，避免“感觉变聪明了，但边界变松了”。

评估维度：

1. 召回能力：客户换说法后仍能命中正确资料。
2. 商品过滤：指定商品时不能把其他商品资料排到前面。
3. 风险阻断：风险资料可以检索到，但不能直接生成承诺回复。
4. 低置信度：没有足够证据时不应强行回答。
5. 经验层：active 经验可检索，discarded 经验不可检索。

命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_enterprise_eval.py
```

报告输出：

```text
runtime/apps/wechat_ai_customer_service/test_artifacts/rag_enterprise_eval_report.json
```

## 运营分析

RAG 运营分析用于判断系统是否越用越好。

统计内容：

- RAG source/chunk/index 数量。
- 按来源类型和知识分类统计。
- RAG 经验 active/discarded 数量。
- 审计日志中的 RAG 应答数量。
- RAG 未命中或被阻断原因。
- 值得转正式知识的经验候选。

API：

```http
GET /api/rag/analytics
```

## 判断经验是否值得转正式知识

建议优先正式化：

- 被重复使用多次。
- 命中问题相似。
- 回复内容稳定。
- 不含价格、赔偿、账期、合同等风险承诺。
- 用户没有在管理台废弃。

正式化路径：

1. 管理台查看 RAG 经验。
2. 复制核心内容或用知识生成器整理。
3. 进入候选审核。
4. 通过后写入正式知识库。

## 运维指标建议

后续可以逐步增加：

- RAG 命中率。
- RAG 应答率。
- RAG 阻断率。
- 转人工率。
- 废弃经验率。
- 正式化转化率。
- RAG 回复平均耗时。
- 每轮 LLM token 成本。
