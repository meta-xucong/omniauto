# 微信 AI 客服知识管理台代码落地清单

本清单把知识管理台拆成可独立实现、独立回测的小章节。每章完成后先跑该章验收命令，通过后再进入下一章。

## 第 0 章：项目状态与实现边界

目标：

- 确认采用本地 Web 管理台路线；
- 管理台只服务 `apps/wechat_ai_customer_service`；
- 第一版不封装桌面客户端；
- 第一版不直接操作真实微信；
- AI 学习只生成候选，不能直接写正式库。

产物：

- 本文件；
- `.codex-longrun/state.json` 切换为管理台目标。

验收：

```powershell
python C:\Users\兰落落的本本\.codex\skills\long-running-task\scripts\validate_state.py --project D:\AI\AI_RPA
```

## 第 1 章：后台骨架与前端壳

目标：

- 新增 `admin_backend` 包；
- 建立 FastAPI 应用；
- 提供 `/api/health`；
- 挂载静态前端；
- 前端使用苹果磨砂玻璃风格，形成总览、知识、编辑、上传、候选、检测、版本、系统状态等导航框架。

文件范围：

- `admin_backend/app.py`
- `admin_backend/models.py`
- `admin_backend/static/index.html`
- `admin_backend/static/app.js`
- `admin_backend/static/styles.css`
- `tests/run_admin_backend_checks.py`

验收：

```powershell
uv run python -m py_compile apps/wechat_ai_customer_service/admin_backend/app.py
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter foundation
```

## 第 2 章：正式知识只读 API

目标：

- 读取正式结构化知识；
- 提供总览、商品、FAQ、政策、风格、人设、原始 JSON API；
- 前端可查看这些数据并搜索。

文件范围：

- `admin_backend/api/knowledge.py`
- `admin_backend/services/knowledge_store.py`
- `admin_backend/static/app.js`

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter readonly
```

## 第 3 章：草稿、校验、版本快照与回滚

目标：

- 创建草稿；
- 获取 diff；
- 快速校验；
- 应用草稿到正式库；
- 应用前创建版本快照；
- 支持版本列表和回滚；
- 前端可编辑商品、FAQ、风格话术的 JSON 草稿。

文件范围：

- `admin_backend/api/drafts.py`
- `admin_backend/api/versions.py`
- `admin_backend/services/draft_store.py`
- `admin_backend/services/version_store.py`
- `admin_backend/services/diagnostics_service.py`
- `admin_backend/services/audit_log.py`

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter drafts
```

## 第 4 章：上传、AI 学习与候选管理

目标：

- 支持 `.txt/.md/.json/.csv` 上传；
- 上传文件进入 `data/raw_inbox/*`；
- 保存上传索引；
- 调用现有候选生成能力；
- 展示 pending / approved / rejected 候选；
- 支持候选编辑、拒绝、应用；
- 候选应用前快照和校验。

文件范围：

- `admin_backend/api/uploads.py`
- `admin_backend/api/candidates.py`
- `admin_backend/services/upload_store.py`
- `admin_backend/services/learning_service.py`
- `admin_backend/services/candidate_store.py`
- `workflows/generate_review_candidates.py`

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter candidates
```

## 第 5 章：一键检测与系统状态

目标：

- 快速检测：JSON、重复 ID、重复别名、空答案、高风险字段、token 预算估算；
- 全量检测：可调用离线回归与工作流守护测试；
- 检测报告保存到 runtime；
- 系统状态展示锁文件、待审核候选、最近检测、版本数量；
- 前端可触发检测并展示用户可读报告。

文件范围：

- `admin_backend/api/diagnostics.py`
- `admin_backend/api/system.py`
- `admin_backend/services/diagnostics_service.py`
- `admin_backend/services/locks.py`

验收：

```powershell
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter diagnostics
```

## 第 6 章：全量回归与启动验收

目标：

- 编译管理台和微信客服 app；
- 运行管理台全部检查；
- 运行已有离线回归；
- 运行已有工作流守护测试；
- 启动本地 Web 服务；
- 验证健康检查和首页可访问。

验收：

```powershell
uv run python -m py_compile <apps/wechat_ai_customer_service/**/*.py>
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
```

交付：

- 本地管理台 URL；
- 本轮测试摘要；
- 剩余建议，例如后续桌面客户端封装、LLM 深度抽取、权限管理。
