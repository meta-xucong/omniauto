# AI 智能自动记录员开发文档

## 1. 开发原则

本次开发先落共享能力，再落记录员模块。共享能力必须能被现有微信 AI 客服直接使用，记录员只作为新的采集入口接入同一条知识流转链路。

核心原则：

- 不复制客服知识库。
- 不复制候选审核逻辑。
- 不允许 AI 直接跳过候选写正式库。
- 正式知识写入统一走快照、审计和新加入标识。
- Excel 导出复用服务端可读知识表语义。

## 2. 推荐代码结构

共享后端：

- `storage/postgres_schema.sql`
- `storage/postgres_store.py`
- `admin_backend/services/raw_message_store.py`
- `admin_backend/services/candidate_badges.py`
- `admin_backend/services/formal_review_state.py`
- `admin_backend/services/readable_export_service.py`
- `admin_backend/api/raw_messages.py`
- `admin_backend/api/export.py`

记录员后端：

- `admin_backend/services/recorder_store.py`
- `admin_backend/services/recorder_service.py`
- `admin_backend/api/recorder.py`
- `workflows/recorder_loop.py`

前端：

- `admin_backend/static/index.html`
- `admin_backend/static/app.js`
- `admin_backend/static/styles.css`

测试：

- `tests/run_recorder_checks.py`
- 扩展 `tests/run_admin_backend_checks.py`
- 必要时扩展 `tests/run_postgres_storage_checks.py`

## 3. 共享原始消息库

### 3.1 Postgres 表

新增表：

- `raw_conversations`
- `raw_messages`
- `raw_message_batches`
- `message_intake_jobs`

最小实现可以先把 conversation 和 message 写入 Postgres，同时 JSON fallback 写入 runtime。

`raw_messages` 推荐唯一键：

```sql
UNIQUE (tenant_id, dedupe_key)
```

`dedupe_key` 由 store 层生成，优先使用 message_id。

### 3.2 Store 接口

`RawMessageStore`：

- `upsert_conversation(record)`
- `list_conversations(filters)`
- `upsert_messages(conversation, messages, source_module)`
- `list_messages(filters)`
- `create_batch(conversation_id, message_ids, reason)`
- `mark_learning_excluded(message_ids, reason)`

返回值必须包含：

- inserted_count
- duplicate_count
- message_ids
- batch_id

### 3.3 客服接入点

`listen_and_reply.py` 在读取 target messages 后调用共享 store：

- 保存该 target 的新消息。
- 不改变现有回复判断。
- 不因 raw store 失败阻断客服回复，但要写 audit/error。

## 4. 候选状态标识

新增 `candidate_badges.py`，集中生成候选展示标签。

输入：

- candidate
- intake
- review
- source
- proposal

输出：

```json
{
  "badges": [
    {"key": "complete", "label": "已完善", "tone": "ok"},
    {"key": "rag_generated", "label": "RAG生成", "tone": "info"}
  ],
  "primary_status": "ready",
  "can_promote": true
}
```

服务端 `CandidateStore.list_candidates` 应给候选补充 `display_badges`，前端只负责展示。

## 5. 正式知识新加入标识

新增 `formal_review_state.py`：

- `mark_item_new(item, source)`
- `acknowledge_item(category_id, item_id, actor)`
- `review_badges_for_item(item)`

接入点：

- `CandidateStore.apply_native_candidate`
- `KnowledgeBaseStore.save_item`
- 手动新增知识 API

为了避免误伤运行时，`review_state` 仅作为后台元数据，不参与客服决策。

API：

- `POST /api/knowledge/categories/{category_id}/items/{item_id}/acknowledge`

## 6. 统一可读 Excel 导出

新增 `readable_export_service.py` 复用：

- `BackupService.build_backup(scope="tenant")`
- `build_customer_readable_workbook(package, package_path)`

API：

- `POST /api/export/customer-readable`
- `GET /api/export/customer-readable/{export_id}/download`

第一版可每次点击生成新包，不必缓存太复杂。生成记录写入 runtime admin export index。

## 7. 记录员服务

### 7.1 会话扫描

`RecorderService.scan_sessions()`：

- 调用 `WeChatConnector.list_sessions()`。
- 标准化 session。
- 用启发式标记 `suggested_type=group|private|unknown`。
- 保存最近扫描结果。

群聊识别只作为建议，用户选择才算启用。

### 7.2 会话配置

`RecorderStore` 保存：

- target_name
- conversation_type
- enabled
- exact
- record_self
- learning_enabled
- notify_enabled
- selected_by_user

### 7.3 记录循环

`workflows/recorder_loop.py`：

- 读取启用会话。
- 调用 `get_messages`。
- 写 raw store。
- 为新增消息创建 batch。
- 如果 intake 开启，创建 job 或同步调用轻量 intake。
- 发送提示前检查 notify 开关和限流。

第一版可以先实现后端服务和离线测试，真实微信轮询沿用连接器。

## 8. 记录员 API

建议：

- `GET /api/recorder/overview`
- `POST /api/recorder/sessions/scan`
- `GET /api/recorder/sessions`
- `POST /api/recorder/conversations`
- `PATCH /api/recorder/conversations/{conversation_id}`
- `GET /api/recorder/messages`
- `GET /api/recorder/jobs`
- `POST /api/recorder/jobs/{job_id}/retry`
- `POST /api/recorder/jobs/{job_id}/skip`
- `GET /api/recorder/settings`
- `PATCH /api/recorder/settings`

## 9. 前端落地

新增导航：

- “智能记录员”

页面分区：

- 总览
- 会话选择
- 原始消息
- 摄入任务
- 设置

候选页改造：

- 展示 `display_badges`。
- 增加按标识过滤可以后续做，第一版至少展示。

知识页改造：

- 展示正式知识 `review_state`。
- 详情页提供“已阅”按钮。

导出入口：

- 知识库或备份还原页增加“导出可读知识表”按钮。

## 10. 测试策略

新增 `run_recorder_checks.py` 覆盖：

- raw message 去重。
- conversation upsert。
- batch 生成。
- candidate badge 生成。
- formal review state 标记与已阅。
- readable export API 生成 xlsx。
- recorder session scan 使用 fake connector。

扩展既有测试：

- admin backend 检查新增路由可用。
- Node syntax 检查前端。
- py_compile 覆盖新增文件。

## 11. 分阶段交付

1. 文档与清单。
2. 共享 raw message store。
3. 候选和正式知识标识。
4. 可读知识表导出。
5. 记录员 API 和页面。
6. 记录员 loop。
7. 回归测试与清理。

