# RAG 企业化优化开发计划

## 范围

本轮优化不做存储层数据库迁移。正式知识、RAG 原始资料、RAG 索引、RAG 经验、审计文件仍沿用当前文件结构。

本轮要补齐的是：

1. 混合检索：在现有词法检索上加入查询扩展、轻量语义项、重排评分和可审计 scoring。
2. 固定评估集：把 RAG 的召回、边界、安全、经验层行为变成可重复跑的测试。
3. 运营分析：汇总 RAG 使用、未命中、废弃经验、可转正式知识的候选经验。
4. 真人感应答控制：让安全软场景回复更自然，但不能越权承诺。
5. 实盘验证：只针对新增 RAG 能力跑文件传输助手场景，已覆盖过的普通客服回归不重复。

## 非目标

- 不接入数据库。
- 不接入生产向量数据库。
- 不让 RAG 直接决定价格、优惠、账期、合同、赔偿、售后承诺、开票主体。
- 不让 RAG 经验自动进入正式知识库。

## 分阶段落地

### 第一章：混合检索

修改：

- `workflows/rag_layer.py`

能力：

- 保留原有本地离线词法检索。
- 增加查询扩展，例如“公寓/民宿/酒店”“预留电源/供电方式”“怎么看型号/型号命名”。
- 为索引条目生成轻量语义项。
- 返回每条命中的 `scoring`，包含 lexical、semantic、phrase、product、boost、risk_penalty 和 final。
- 返回 `retrieval_mode=hybrid_lexical_semantic`。
- 低置信度仍不授权业务承诺。

验收：

- 旧 RAG 测试通过。
- 新增同义表达检索测试通过。

### 第二章：RAG 评估集

新增：

- `tests/fixtures/rag_eval_sources/`
- `tests/run_rag_enterprise_eval.py`

覆盖：

- 同义词/改写召回。
- 商品过滤。
- 风险词检索可见但应答阻断。
- RAG 经验 active 可检索、discarded 不检索。
- 低置信度不误答。

验收：

- 输出 JSON 报告。
- 关键指标全部达到预设阈值。

### 第三章：运营分析

新增：

- `workflows/rag_operations.py`
- 管理台 RAG API 增加 `/api/rag/analytics`

能力：

- 汇总索引规模、来源类型、知识分类。
- 汇总 RAG 经验 active/discarded。
- 从审计日志中统计 RAG 命中、RAG 应答、未命中、被阻断原因。
- 给出“建议转正式知识”的经验候选。

验收：

- 管理台测试覆盖 analytics API。

### 第四章：真人感应答控制

修改：

- `workflows/rag_answer_layer.py`

能力：

- 对闲聊/轻咨询/场景咨询使用更自然的语气。
- 明确表达“资料中有相关说明，先给您参考”。
- 涉及价格、库存、发货、售后、合同、账期等仍阻断或交给正式知识。
- 回复长度受控。

验收：

- RAG 边界测试通过。
- 风险场景不能被人情味回复绕过。

### 第五章：实盘测试

新增或更新：

- `configs/file_transfer_rag_enterprise.example.json`
- `tests/scenarios/file_transfer_rag_enterprise.json`

只测新增能力：

- 同义表达能触发 RAG 回复。
- 风险问题不会用 RAG 越权回复。
- RAG 经验层写入后可在经验层检索。

验收：

- 文件传输助手实盘场景通过。
- 临时 RAG source 和测试经验清理干净。
