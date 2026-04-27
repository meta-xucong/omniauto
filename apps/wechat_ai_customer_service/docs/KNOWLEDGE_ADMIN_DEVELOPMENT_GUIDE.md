# 微信 AI 客服知识管理台开发文档

## 1. 技术路线

推荐采用两阶段客户端路线：

1. 第一阶段：本地 Web 管理台。
   - 后端：FastAPI，复用仓库已有依赖。
   - 前端：先用轻量静态页面或简单 Vite/React 页面。
   - 运行方式：`localhost`，只服务本机。

2. 第二阶段：桌面应用客户端。
   - 可用 Tauri / Electron / WebView 包一层本地 Web 管理台。
   - 后端仍保持同一套 FastAPI API。

这样可以最快落地，又不把前端客户端和知识管理逻辑绑死。

## 2. 目录规划

建议新增：

```text
apps/wechat_ai_customer_service/
  admin_backend/
    __init__.py
    app.py
    models.py
    api/
      knowledge.py
      uploads.py
      candidates.py
      diagnostics.py
      versions.py
      system.py
    services/
      knowledge_store.py
      draft_store.py
      candidate_store.py
      upload_store.py
      learning_service.py
      diagnostics_service.py
      version_store.py
      audit_log.py
      locks.py
    static/
      index.html
      app.js
      styles.css
  data/
    versions/
      .gitkeep
  tests/
    run_admin_backend_checks.py
```

运行时新增：

```text
runtime/apps/wechat_ai_customer_service/
  admin/
    audit.jsonl
    jobs/
    diagnostics/
    uploads_index.json
    drafts/
```

说明：

- 正式知识继续放在 `data/structured/`。
- 原始资料继续放在 `data/raw_inbox/`。
- AI 候选继续放在 `data/review_candidates/`。
- 版本快照放在 app 内 `data/versions/`。
- 管理台运行日志、任务状态、草稿放在 runtime。

## 3. 后端模块职责

### 3.1 `app.py`

创建 FastAPI 应用：

- 注册 API router；
- 挂载静态前端；
- 提供健康检查；
- 设置本地访问限制。

第一版只监听 `127.0.0.1`。

### 3.2 `models.py`

定义 Pydantic 模型：

- `ProductItem`
- `FaqItem`
- `PolicyBundle`
- `StyleExample`
- `KnowledgeOverview`
- `DraftChange`
- `Candidate`
- `UploadRecord`
- `DiagnosticRun`
- `VersionSnapshot`
- `ApplyResult`

模型要贴近现有 JSON，但不强行一次重构全部业务结构。

### 3.3 `knowledge_store.py`

负责正式知识读写：

- 读取 `data/structured/product_knowledge.example.json`；
- 读取 `data/structured/style_examples.json`；
- 读取 `data/structured/manifest.json`；
- 提供商品、FAQ、政策、风格话术的列表、详情、保存；
- 保存时保持 JSON 美观、稳定排序和 UTF-8；
- 写入前调用校验服务。

### 3.4 `draft_store.py`

负责草稿：

- 创建草稿；
- 更新草稿；
- 获取差异；
- 丢弃草稿；
- 应用草稿。

草稿存放在 runtime，避免未完成修改污染正式知识。

### 3.5 `version_store.py`

负责版本：

- 应用正式变更前创建快照；
- 快照结构化数据目录；
- 写入 `metadata.json`；
- 列出历史版本；
- 比较版本；
- 回滚版本。

### 3.6 `candidate_store.py`

负责 AI 候选：

- 列出 pending / approved / rejected；
- 读取候选；
- 编辑候选；
- 批准候选；
- 拒绝候选；
- 将候选应用到正式知识。

应用候选前必须创建版本快照并运行校验。

### 3.7 `upload_store.py`

负责上传：

- 校验后缀；
- 保存到对应 raw_inbox 子目录；
- 计算 hash；
- 记录上传索引；
- 标记是否已学习。

第一版支持 `.txt / .md / .json / .csv`，后续增加 `.xlsx / .docx / pdf`。

### 3.8 `learning_service.py`

负责 AI 学习任务：

- 接收上传文件或 raw_inbox 文件列表；
- 调用已有 `generate_review_candidates.py` 的能力；
- 后续扩展 DeepSeek 抽取；
- 生成 pending 候选；
- 记录任务状态和错误。

第一版可以先复用当前规则抽取逻辑，再加 LLM 抽取。

### 3.9 `diagnostics_service.py`

负责检测：

- JSON 校验；
- schema 校验；
- 重复 ID / 别名 / 关键词冲突；
- 必填字段；
- 价格、折扣、账期、发票等高风险字段提示；
- token 预算估算；
- 调用离线回归；
- 调用工作流守护测试；
- 可选调用 DeepSeek probe；
- 可选调用 File Transfer Assistant live regression。

检测结果写入 `runtime/apps/wechat_ai_customer_service/admin/diagnostics/`。

### 3.10 `audit_log.py`

统一写审计日志：

- `upload_created`
- `learning_started`
- `candidate_created`
- `candidate_approved`
- `candidate_rejected`
- `draft_created`
- `knowledge_applied`
- `version_created`
- `rollback_applied`
- `diagnostics_run`

## 4. API 设计

### 4.1 系统状态

- `GET /api/health`
- `GET /api/system/status`
- `GET /api/system/runtime-locks`

返回：

- 管理台状态；
- 当前配置；
- 是否存在锁；
- 最近测试结果；
- 待审核数量。

### 4.2 知识读取

- `GET /api/knowledge/overview`
- `GET /api/knowledge/products`
- `GET /api/knowledge/products/{id}`
- `GET /api/knowledge/faqs`
- `GET /api/knowledge/policies`
- `GET /api/knowledge/styles`
- `GET /api/knowledge/persona`
- `GET /api/knowledge/raw-json?file=...`

### 4.3 草稿与编辑

- `POST /api/drafts`
- `GET /api/drafts/{draft_id}`
- `PATCH /api/drafts/{draft_id}`
- `GET /api/drafts/{draft_id}/diff`
- `POST /api/drafts/{draft_id}/validate`
- `POST /api/drafts/{draft_id}/apply`
- `DELETE /api/drafts/{draft_id}`

### 4.4 上传

- `POST /api/uploads`
- `GET /api/uploads`
- `GET /api/uploads/{upload_id}`
- `DELETE /api/uploads/{upload_id}`

### 4.5 AI 学习

- `POST /api/learning/jobs`
- `GET /api/learning/jobs`
- `GET /api/learning/jobs/{job_id}`
- `POST /api/learning/jobs/{job_id}/cancel`

第一版任务可以同步执行，但 API 结构按异步任务设计，方便后续长文件和 LLM 批处理。

### 4.6 候选审核

- `GET /api/candidates?status=pending`
- `GET /api/candidates/{candidate_id}`
- `PATCH /api/candidates/{candidate_id}`
- `POST /api/candidates/{candidate_id}/approve`
- `POST /api/candidates/{candidate_id}/reject`
- `POST /api/candidates/{candidate_id}/apply`

### 4.7 一键检测

- `POST /api/diagnostics/run`
- `GET /api/diagnostics/runs`
- `GET /api/diagnostics/runs/{run_id}`
- `POST /api/diagnostics/runs/{run_id}/apply-suggestion`

检测参数：

- `mode`: `quick` 或 `full`;
- `include_llm_probe`: 是否调用 DeepSeek；
- `include_wechat_live`: 是否跑文件传输助手 live regression；
- `target_scope`: 全部知识或指定模块。

### 4.8 版本与回滚

- `GET /api/versions`
- `GET /api/versions/{version_id}`
- `GET /api/versions/{version_id}/diff`
- `POST /api/versions/{version_id}/rollback`

## 5. 前端页面设计

### 5.1 总览页

组件：

- 健康状态卡片；
- 知识统计；
- 待审核候选；
- 最近检测；
- 最近修改；
- 运行风险提示。

### 5.2 商品页

功能：

- 商品表格；
- 搜索别名；
- 编辑抽屉；
- 阶梯价编辑；
- 删除确认；
- 查看关联 FAQ / 测试。

### 5.3 FAQ 与政策页

功能：

- FAQ 列表；
- 优先级排序；
- 关键词编辑；
- 转人工开关；
- 政策分组编辑。

### 5.4 风格与人设页

功能：

- 人设编辑；
- 回复边界编辑；
- 风格示例编辑；
- 小样本预览。

### 5.5 上传与学习页

功能：

- 拖拽上传；
- 文件类型选择；
- 上传历史；
- 选择文件发起 AI 学习；
- 学习任务进度；
- 生成候选跳转。

### 5.6 候选审核页

功能：

- pending / approved / rejected 标签页；
- 候选详情；
- 原始证据摘录；
- 建议变更；
- 风险等级；
- 编辑候选；
- 批准、拒绝、应用。

### 5.7 检测页

功能：

- 快速检测；
- 全量检测；
- 检测历史；
- 问题列表；
- 一键生成修复候选；
- 应用建议。

### 5.8 版本页

功能：

- 版本列表；
- 查看差异；
- 回滚；
- 回滚后检测结果。

## 6. 开发阶段

### 阶段 1：只读管理台

目标：

- FastAPI 启动；
- 静态前端可打开；
- 首页展示正式知识摘要；
- 能查看商品、FAQ、政策、风格话术；
- 不提供写入。

验收：

- `GET /api/health` 通过；
- `GET /api/knowledge/overview` 返回统计；
- 浏览器能看到当前知识；
- 不改变任何正式文件。

### 阶段 2：草稿编辑与校验

目标：

- 支持商品、FAQ、风格话术的草稿编辑；
- 支持 diff；
- 支持快速校验；
- 支持应用草稿到正式库；
- 应用前创建版本快照。

验收：

- 新增商品后能在正式库看到；
- 删除或编辑能生成差异；
- 重复 ID 被阻止；
- 应用失败不会破坏正式库；
- 能回滚。

### 阶段 3：上传与候选生成

目标：

- 支持上传文件；
- 保存到 raw_inbox；
- 记录上传索引；
- 调用候选生成；
- 候选进入 pending；
- 前端能审核候选。

验收：

- 上传 `.txt / .md / .json / .csv` 成功；
- 空文件和非法后缀被拒绝；
- 生成候选保留来源证据；
- 拒绝候选不影响正式库。

### 阶段 4：候选应用

目标：

- 支持编辑候选；
- 支持批准并应用；
- 支持移动到 approved / rejected；
- 应用前运行校验和快照；
- 更新 manifest 的必要元数据。

验收：

- 产品候选可变成正式商品或商品更新；
- FAQ 候选可变成正式 FAQ；
- 风格候选可进入 style examples；
- 应用后离线回归通过；
- 应用失败可回滚。

### 阶段 5：一键检测

目标：

- 快速检测；
- 全量检测；
- 检测报告；
- 生成修复候选；
- 可选 DeepSeek probe。

验收：

- `quick` 检测能在 5 秒左右完成；
- `full` 检测能调用现有测试；
- 报告展示问题、影响和建议；
- 修复建议进入候选流程。

### 阶段 6：客户端封装

目标：

- 选择桌面外壳；
- 本地启动后端；
- 打开客户端窗口；
- 处理端口占用；
- 提供关闭进程能力。

验收：

- 双击或命令可启动；
- 客户端关闭后后端可正常退出；
- 日志路径清晰；
- 不影响微信监听进程。

## 7. 检测与测试命令

开发过程中应复用已有命令：

```powershell
uv run python -m py_compile apps/wechat_ai_customer_service/**/*.py
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
```

管理台新增测试建议：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py
```

测试覆盖：

- API 读写；
- 草稿 diff；
- 版本快照；
- 回滚；
- 上传；
- 候选生成；
- 候选应用；
- 检测报告；
- 正式库不被失败操作破坏。

## 8. 关键实现细节

### 8.1 写入必须原子化

正式知识写入时：

1. 写临时文件；
2. 校验临时文件；
3. 备份旧文件；
4. 原子替换；
5. 写审计日志。

### 8.2 应用前锁

应用草稿、应用候选、回滚版本时，应加管理台写锁：

```text
runtime/apps/wechat_ai_customer_service/admin/write.lock
```

如果微信监听正在运行，第一版先提示用户暂停监听。

### 8.3 LLM 学习上下文

AI 学习时不能把所有知识都塞给模型。应按资料类型加载：

- 商品资料：加载商品 schema、现有商品 ID/别名、价格字段说明；
- 聊天记录：加载风格话术 schema、转人工规则、少量现有风格样本；
- 政策文件：加载 FAQ/policy schema、相关政策字段；
- ERP 导出：加载商品字段映射和去重规则。

### 8.4 安全字段

以下字段变更要高风险提示：

- 商品价格；
- 阶梯价；
- 折扣授权；
- 账期/月结；
- 退款、赔偿；
- 发票特殊处理；
- 安装和上门承诺；
- 合同条款。

高风险字段应用前至少要求二次确认，后续可要求管理员角色。

### 8.5 用户可读报告

检测报告不要只显示 `AssertionError`。需要转成：

- 问题：例如“商品 A 的别名和商品 B 重复”；
- 影响：例如“客户问这个别名时可能匹配错误商品”；
- 建议：例如“保留更常用商品，或把别名改成更具体的词”；
- 操作：生成修复候选 / 忽略 / 手动编辑。

## 9. 交付顺序建议

建议先做：

1. 只读后台和总览；
2. 商品/FAQ/风格话术读写；
3. 草稿、快照、回滚；
4. 上传和候选生成；
5. 候选应用；
6. 一键检测；
7. 桌面客户端封装。

不要一开始就做完整桌面客户端。先把数据流和安全写入跑通，客户端外壳后置。

## 10. 第一轮开发完成定义

第一轮可以交付的最小可用版本：

- 启动本地管理台；
- 查看正式知识；
- 编辑商品/FAQ/风格话术；
- 生成 diff；
- 应用前校验和快照；
- 上传文件；
- 生成 pending 候选；
- 审核并应用候选；
- 快速检测；
- 回滚最近版本。

达到这个程度后，再考虑更漂亮的客户端、更强的 AI 抽取、更细的权限和更复杂的 ERP 对接。
