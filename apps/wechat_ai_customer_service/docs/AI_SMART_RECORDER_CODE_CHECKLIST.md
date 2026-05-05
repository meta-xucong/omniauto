# AI 智能自动记录员代码落地清单

## Phase 1 - 文档

- [x] 更新 V2.0 需求文档。
- [x] 新增开发文档。
- [x] 新增代码落地清单。

## Phase 2 - 共享原始消息库

- [x] 更新 `storage/postgres_schema.sql`。
- [x] 扩展 `storage/postgres_store.py`。
- [x] 新增 `admin_backend/services/raw_message_store.py`。
- [x] 新增 `admin_backend/api/raw_messages.py`。
- [x] 在 `admin_backend/app.py` 注册 raw messages API。
- [x] 在 `listen_and_reply.py` 接入 raw message 记录。
- [x] 增加 raw message JSON fallback。
- [x] 增加去重测试。

## Phase 3 - 候选与正式知识标识

- [x] 新增 `admin_backend/services/candidate_badges.py`。
- [x] `CandidateStore.list_candidates` 输出 `display_badges`。
- [x] 新增 `admin_backend/services/formal_review_state.py`。
- [x] 候选 apply 后标记正式知识 `review_state.is_new=true`。
- [x] 手动新增知识后标记新加入。
- [x] 新增知识已阅 API。
- [x] 前端候选列表展示标识。
- [x] 前端知识列表和详情展示新加入标识。
- [x] 前端详情支持点击“已阅”。

## Phase 4 - 统一 Excel 导出

- [x] 新增 `admin_backend/services/knowledge_export_service.py`。
- [x] 新增 `admin_backend/api/exports.py`。
- [x] 复用 `BackupService` 和 `build_customer_readable_workbook`。
- [x] 支持下载 xlsx。
- [x] 前端新增导出按钮。
- [x] 测试 xlsx 生成与服务端可读知识表导出入口。

## Phase 5 - 记录员后端

- [x] 复用 `raw_message_store.py` 作为记录员持久化。
- [x] 新增 `admin_backend/services/recorder_service.py`。
- [x] 新增 `admin_backend/api/recorder.py`。
- [x] 支持会话扫描。
- [x] 支持群聊选择。
- [x] 支持记录员设置。
- [x] 支持原始消息查询。
- [x] 支持批次整理与重试入口。
- [x] 在 `admin_backend/app.py` 注册 recorder API。

## Phase 6 - 记录员流程

- [x] 新增 `workflows/recorder_loop.py`。
- [x] 读取启用会话。
- [x] 拉取微信消息。
- [x] 写入 raw message store。
- [x] 生成 message batch。
- [x] 调用 RAG 摄入。
- [x] 生成候选知识。
- [x] 按开关发送收录提示。

## Phase 7 - 记录员前端

- [x] 新增“智能记录员”导航。
- [x] 新增总览区域。
- [x] 新增会话扫描与群聊选择。
- [x] 新增原始消息列表。
- [x] 新增批次整理入口。
- [x] 新增设置区域。
- [x] 接入导出按钮。

## Phase 8 - 验证

- [x] `python -m py_compile` 覆盖新增 Python 文件。
- [x] `node --check apps/wechat_ai_customer_service/admin_backend/static/app.js`。
- [x] `python apps/wechat_ai_customer_service/tests/run_smart_recorder_checks.py`。
- [x] `python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all`。
- [x] 如涉及 Postgres：`python apps/wechat_ai_customer_service/tests/run_postgres_storage_checks.py`。
- [x] 更新 `.codex-longrun/progress.md`。
- [x] 更新 `.codex-longrun/test-log.md`。
