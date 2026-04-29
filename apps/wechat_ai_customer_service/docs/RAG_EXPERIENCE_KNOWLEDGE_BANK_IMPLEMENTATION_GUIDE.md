# RAG 经验知识库代码改造指南

## 第一章：资料源可视化 API

### 目标

让管理台能看到 RAG 已导入资料和切片预览，而不是只显示统计数字。

### 改造点

- `admin_backend/services/rag_admin_service.py`
  - 新增 `sources()`。
  - 调用 `RagService.list_sources()` 和 `RagService.iter_chunks()`。
  - 返回资料源、切片预览、每个资料源的切片数量。

- `admin_backend/api/rag.py`
  - 新增 `GET /api/rag/sources`。

### 验证

- `GET /api/rag/sources` 返回 `ok: true`。
- 返回结果包含 `sources`、`chunks`、`chunk_counts`。

## 第二章：RAG 经验和正式知识关系标注

### 目标

在经验列表中告诉用户：这条经验是新的、已被正式知识覆盖、疑似冲突，还是建议升级。

### 改造点

- `admin_backend/services/rag_admin_service.py`
  - 引入正式知识读取能力。
  - 为每条经验计算 `formal_relation`。
  - 返回 `formal_match` 和 `recommended_action`。

### 判断规则

第一版采用 deterministic scoring：

- 文本相似度高且没有明显冲突：`covered_by_formal`。
- 文本相似度中等且方向一致：`supports_formal`。
- 同一商品或同一关键词下存在价格、账期、人工接管等敏感差异：`conflicts_formal`。
- 使用次数达到阈值、无风险词、没有正式覆盖：`promotion_candidate`。
- 其他：`novel`。

### 验证

- `GET /api/rag/experiences?status=all` 每条记录包含 `formal_relation`。
- active、discarded、promoted 均能返回。

## 第三章：RAG 经验状态更新能力

### 目标

支持除废弃外的经验状态变更，为“升级为正式知识候选”做准备。

### 改造点

- `workflows/rag_experience_store.py`
  - 新增通用 `update_status()`。
  - 复用 JSON 与 PostgreSQL 双后端。
  - 状态变化后重建 RAG 索引。

### 验证

- `update_status(..., status="promoted")` 后经验不再参与 RAG 检索。
- JSON fallback 和 PostgreSQL 模式均可保存状态。

## 第四章：升级为正式知识候选

### 目标

用户可以把 RAG 经验转入“待确认知识”，但不能绕过审核直接入库。

### 改造点

- `admin_backend/services/rag_admin_service.py`
  - 新增 `promote_experience()`。
  - 生成 review candidate。
  - 写入 `data/review_candidates/pending/`。
  - 同步写入 PostgreSQL candidate mirror。
  - 标记经验为 `promoted`。

- `admin_backend/api/rag.py`
  - 新增 `POST /api/rag/experiences/{experience_id}/promote`。

### 候选分类

- 命中商品专属 FAQ/规则/解释：优先进入对应商品专属门类。
- 命中政策：进入 `policies`。
- 默认：进入 `chats`，作为对话话术候选。

### 验证

- promote 返回 `candidate_id`。
- `GET /api/candidates?status=pending` 能看到该候选。
- RAG 经验状态变为 `promoted`。

## 第五章：管理台前端改造

### 目标

让用户能无脑管理 RAG 资料和经验。

### 改造点

- `static/index.html`
  - 在“已导入资料”中新增资料源列表和切片预览容器。

- `static/app.js`
  - 状态加载时同时加载 `/api/rag/sources`。
  - 经验列表改为 `status=all`。
  - 渲染经验关系、建议操作、升级按钮。
  - 升级或废弃后刷新 RAG 状态、经验列表和候选列表。

- `static/styles.css`
  - 增加 RAG source/experience relation 的轻量样式。

### 验证

- 前端静态检查通过。
- JS 中包含新接口和新按钮。
- 管理台能看到资料源、切片、经验关系。

## 第六章：回归测试

### 目标

确保 RAG 经验知识库改造不影响现有系统。

### 测试命令

```powershell
node --check apps\wechat_ai_customer_service\admin_backend\static\app.js
.\.venv\Scripts\python.exe -m py_compile apps\wechat_ai_customer_service\admin_backend\api\rag.py apps\wechat_ai_customer_service\admin_backend\services\rag_admin_service.py apps\wechat_ai_customer_service\workflows\rag_experience_store.py apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter foundation
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_admin_backend_checks.py --chapter all
.\.venv\Scripts\python.exe -m compileall -q apps\wechat_ai_customer_service
```

### 验收

- PostgreSQL 模式 admin checks 通过。
- JSON fallback 模式 admin checks 通过。
- RAG enterprise/boundary/offline 相关测试没有退化。
- 本地管理台重启后可用。
