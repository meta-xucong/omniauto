# RAG 层代码落地指导

## 章节 1：路径和存储骨架

目标：

- 在 `knowledge_paths.py` 中加入 tenant-aware RAG 路径。
- 创建 RAG source/chunk/index/cache 的读写服务。
- 不改变正式结构化知识目录。

验收：

- 能为 `default` tenant 返回：
  - `rag_sources`
  - `rag_chunks`
  - `rag_index`
  - `rag_cache`
- 目录创建不会影响旧知识库。

## 章节 2：本地 RAG 检索核心

目标：

- 支持从 `.txt`、`.md`、`.csv`、`.json` 等已经可读文本中提取文本。
- 支持切块、去重、chunk 元数据。
- 支持构建本地索引。
- 支持按 query、category、product_id、source_type 检索。

第一版检索策略：

- 中文和英文关键词切分。
- 字符片段匹配。
- query-term 覆盖率。
- category/product metadata 加权。
- 高风险词仅作为标记，不允许授权。

验收：

- 上传商品说明后，可检索到商品片段。
- 指定 `product_id` 时，只优先返回该商品相关片段。
- 检索结果包含 `chunk_id`、`source_id`、`score`、`text`、`metadata`。

## 章节 3：上传学习与候选审核集成

目标：

- `LearningService.create_job()` 在生成候选前/后为上传文件建立 RAG chunks。
- `generate_review_candidates.build_candidates()` 可接收 RAG evidence，并写入 candidate 的 `source.rag_hits` 或 `review.rag_evidence`。
- 重复文件上传时，RAG source 可 upsert，不重复污染索引。
- 候选仍然必须人工审核后才能入库。

验收：

- 对同一个上传文件重复学习，不产生重复正式候选。
- 候选详情能看到 RAG 来源片段摘要。
- 缺字段候选仍然不能应用入库。

## 章节 4：运行时 Evidence 集成

目标：

- `knowledge_loader.build_evidence_pack()` 增加可选 RAG evidence。
- 默认配置可关闭 RAG。
- 开启后仅在结构化证据不足或上下文需要增强时检索。
- RAG evidence 不能覆盖 safety decision。

验收：

- 结构化知识已命中时，不需要 RAG 也能正常回复。
- 模糊问题可拿到 RAG evidence。
- RAG-only 高风险问题必须转人工。

## 章节 5：管理台接口

目标：

- 增加 `/api/rag/status`。
- 增加 `/api/rag/search`。
- 增加 `/api/rag/rebuild`。
- 返回业务友好的 source/chunk 统计，不暴露 embedding 细节。

验收：

- API 可以查看 source/chunk/index 数量。
- API 可以用文本检索 RAG chunks。
- 重建索引后检索结果不丢失。

## 章节 6：全量回归

目标：

- 新增 `tests/run_rag_layer_checks.py`。
- 更新必要的 admin/runtime/workflow 测试。
- 保持现有 File Transfer Assistant 实盘回归通过。

验收命令：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_rag_layer_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_knowledge_runtime_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_offline_regression.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_workflow_logic_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_file_transfer_live_regression.py --send --reset-state --delay-seconds 1
```

