# RAG 与正式知识库持续优化实现指南

## Chapter 1: 文档与状态

目标：建立本轮优化的工程边界。

改动：

- 新增持续优化方案文档。
- 新增本实现指南。
- 更新 long-running task 状态与路线图。

验证：

- 文档路径存在。
- long-running state 合法。

## Chapter 2: RAG 经验质量评分

目标：每条 RAG 对话经验都能被自动评估。

实现点：

- 在 `workflows/rag_experience_store.py` 增加 `score_experience_quality`。
- 记录新经验时写入 `quality`。
- 重复命中、状态变更、元数据变更时重新计算质量。
- 为历史经验提供兼容计算函数，避免旧数据没有 `quality` 时出错。

质量规则：

- 高命中分、完整问题与回复、无风险、无人工接管：高质量。
- 中等命中分、无风险、内容完整：中质量。
- 命中分低、内容太短、证据不足：低质量。
- 有风险词、人工接管、拒答/审批建议：阻断。

验证：

- 高质量经验 `retrieval_allowed=true`。
- 低分经验 `retrieval_allowed=false`。
- 风险经验 `retrieval_allowed=false`。

## Chapter 3: 检索准入门

目标：RAG 索引只吸收允许检索的经验。

实现点：

- 在 `RagExperienceStore` 增加 `list_retrievable`。
- 在 `workflows/rag_layer.py` 的 `iter_experience_chunks` 中改用 `list_retrievable`。
- 经验 chunk 带上质量摘要，便于搜索结果审计。

验证：

- active 高质量经验可检索。
- active 低质量经验不可检索。
- promoted/discarded 不可检索。

## Chapter 4: 正式知识关系缓存

目标：管理台展示经验和正式知识的关系，同时把稳定关系缓存到经验记录里。

实现点：

- 在 `RagExperienceStore` 增加 `update_metadata`。
- 在 `rag_admin_service.list_experiences` 中注入质量字段和关系缓存。
- 只有关系、匹配项或建议动作变化时写缓存，避免每次刷新都改数据。

验证：

- `/api/rag/experiences` 返回 `formal_relation_cache`。
- 缓存里有 relation、formal_match、recommended_action。
- 已废弃/已升级经验关系仍明确。

## Chapter 5: 管理台可解释展示

目标：让用户看到“经验是否可靠、是否进入检索、为什么”。

实现点：

- RAG 经验统计卡片增加质量相关统计。
- 经验行增加质量 chip、检索准入 chip、原因说明。
- CSS 增加高/中/低/阻断质量样式。

验证：

- 前端静态检查包含 `quality-chip` 和 `retrieval_allowed`。
- `node --check` 通过。

## Chapter 6: 自动化回归

目标：把质量门控与关系缓存纳入常规测试。

实现点：

- 扩展 `run_admin_backend_checks.py`。
- 扩展 `run_rag_enterprise_eval.py`。
- 覆盖 PostgreSQL 与 JSON fallback。

验证：

- Admin foundation/all 通过。
- RAG enterprise eval 通过。
- RAG boundary、workflow、offline、runtime、storage、compile 全通过。

## Chapter 7: 实盘测试与迭代

目标：通过文件传输助手验证实盘流程。

测试重点：

- RAG 软参考正常回复。
- 风险问题不会被经验层绕过。
- 正式知识优先级不被破坏。
- 新经验能在管理台看到质量解释。

处理：

- 如实盘发现质量误判，回到 Chapter 2 调整评分。
- 如发现经验污染检索，回到 Chapter 3 调整准入。
- 如发现用户看不懂，回到 Chapter 5 调整展示。

## Chapter 8: 清理与交付

目标：确保可交付状态干净。

操作：

- 清理测试 RAG 源、经验、候选、临时上传。
- 必要时刷新 PostgreSQL 默认租户，使其与 JSON 镜像一致。
- 重启管理台。
- 更新 long-running state、progress、test-log。
- 发送完成通知。
