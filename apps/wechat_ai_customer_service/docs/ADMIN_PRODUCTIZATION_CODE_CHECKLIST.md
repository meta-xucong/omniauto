# 管理台产品化代码实施清单

## 第 1 章：文档与状态初始化

目标：把本轮产品化目标和 AI 知识生成器设计固化到文档和长任务状态。

验收：

- 新增产品化总方案文档。
- 新增 AI 知识生成器接口规范。
- 新增代码实施清单。
- `.codex-longrun/state.json` 指向本轮目标。

## 第 2 章：后端 AI 知识生成器

目标：新增会话式生成器服务和 API。

涉及文件：

- `admin_backend/services/knowledge_generator.py`
- `admin_backend/api/generator.py`
- `admin_backend/app.py`
- `tests/run_admin_backend_checks.py`

实现要求：

- 支持创建会话、继续补充、确认保存。
- 可调用 DeepSeek，也可离线兜底。
- 生成结果必须通过 schema 校验。
- 保存写入分类知识库根目录。
- 保存后触发兼容编译。

回测：

- Python 编译。
- admin backend generator 检查。

## 第 3 章：知识库业务表单

目标：彻底去掉用户侧 JSON 编辑痕迹。

涉及文件：

- `admin_backend/static/app.js`
- `admin_backend/static/index.html`
- `admin_backend/static/styles.css`

实现要求：

- 默认只读详情。
- 编辑、新增、取消、保存状态明确。
- 阶梯价格用表格行编辑。
- 回复模板用业务文本框编辑。
- 对象字段用键值对行编辑。
- 保存前客户端校验阶梯价格。

回测：

- `node --check app.js`
- 浏览器 smoke 检查知识库页面无控制台错误。

## 第 4 章：前端 AI 知识生成器

目标：用生成器替代旧“编辑草稿”。

涉及文件：

- `admin_backend/static/index.html`
- `admin_backend/static/app.js`
- `admin_backend/static/styles.css`

实现要求：

- 导航改为“知识生成器”。
- 提供自然语言输入框。
- 展示对话追问、识别门类、总览表、风险提醒。
- 状态 ready 时允许确认保存。
- 保存后刷新知识库和总览。

回测：

- 静态资产检查。
- admin backend generator flow。
- 浏览器 smoke。

## 第 5 章：候选审核业务化

目标：让用户理解候选审核用途和处理动作。

实现要求：

- 页面显示“候选审核怎么用”说明。
- 候选详情展示来源、建议、证据、目标门类、风险。
- 不展示原始 JSON。

回测：

- 候选审核 API 原有测试通过。
- 前端静态检查包含候选说明和操作按钮。

## 第 6 章：一键检测细节与忽略

目标：检测结果可定位、可忽略、可修复。

涉及文件：

- `admin_backend/services/diagnostics_service.py`
- `admin_backend/api/diagnostics.py`
- `admin_backend/static/app.js`
- `admin_backend/static/styles.css`

实现要求：

- 每条 issue 附带 fingerprint。
- 支持 `POST /api/diagnostics/ignore`。
- 忽略记录存运行时目录。
- 默认检测结果过滤已忽略 issue。
- 前端提供“查看细节”“标记忽略”“一键修复”。

回测：

- diagnostics 检查。
- 忽略接口测试。

## 第 7 章：备份还原与系统状态合并

目标：修正备份体验，删掉重复系统状态主页面。

实现要求：

- 备份按钮走 `POST /api/versions`。
- 前端对 405 给出“请重启本地服务”的提示。
- 还原前保持二次确认。
- 移除系统状态主导航，把摘要并入总览。
- 保留 `/api/system/status` 供底层和测试使用。

回测：

- versions 测试。
- system endpoint 测试。
- 浏览器 smoke。

## 第 8 章：全量验收

命令：

```powershell
uv run python -m compileall -q apps/wechat_ai_customer_service
node --check apps/wechat_ai_customer_service/admin_backend/static/app.js
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_base_migration_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_runtime_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_knowledge_compiler_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_admin_backend_checks.py --chapter all
uv run python apps/wechat_ai_customer_service/tests/run_offline_regression.py
uv run python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
uv run python apps/wechat_ai_customer_service/tests/run_deepseek_boundary_probe.py
uv run python apps/wechat_ai_customer_service/workflows/preflight.py --skip-wechat --json
```

交付前清理：

- 删除测试生成的候选、上传、会话、版本快照。
- 确认 runtime lock 为空。
- 确认知识库没有残留测试条目。

