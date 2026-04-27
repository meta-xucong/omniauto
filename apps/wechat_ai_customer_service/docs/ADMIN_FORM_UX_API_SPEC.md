# Web 管理台表单化 UX 与 API 规范

本文档定义分类知识库重构后的 Web 管理台交互形态和 API 合约。目标用户是业务人员，不是开发者。

## 1. 总体原则

- 默认不展示 JSON。
- 用门类、表格、表单、卡片、摘要表达知识。
- JSON 视图只放在开发者模式。
- 所有正式入库前必须校验。
- 所有正式写入前必须备份。
- 高风险修改必须二次确认。
- 用户能创建自定义门类和自定义字段。

## 2. 导航结构

建议导航：

- 总览
- 知识库
- 新增/编辑草稿
- 资料上传
- AI 学习结果审核
- 一键检测
- 备份与还原
- 系统状态
- 门类设置

## 3. 知识库页面

布局：

- 左侧：门类列表。
- 中间：当前门类条目列表。
- 右侧：表单详情。

功能：

- 搜索；
- 筛选启用/停用；
- 新增条目；
- 编辑条目；
- 存为草稿；
- 校验；
- 入库；
- 归档；
- 查看关联候选；
- 开发者模式查看 JSON。

API：

```text
GET  /api/knowledge/categories
POST /api/knowledge/categories
GET  /api/knowledge/categories/{category_id}
GET  /api/knowledge/categories/{category_id}/schema
GET  /api/knowledge/categories/{category_id}/items
GET  /api/knowledge/categories/{category_id}/items/{item_id}
POST /api/knowledge/categories/{category_id}/items
PATCH /api/knowledge/categories/{category_id}/items/{item_id}
POST /api/knowledge/categories/{category_id}/items/{item_id}/archive
```

## 4. 门类设置页面

功能：

- 查看默认门类；
- 创建自定义门类；
- 编辑自定义门类名称、说明、字段；
- 设置是否参与客服回复；
- 设置是否参与 AI 学习；
- 设置是否参与检测；
- 配置表单字段顺序；
- 配置检索字段。

创建自定义门类表单：

- 门类名称；
- 门类 ID；
- 说明；
- 字段列表；
- 是否启用；
- 是否参与客服回复；
- 是否参与 AI 学习；
- 是否参与检测。

API：

```text
POST /api/knowledge/categories
PATCH /api/knowledge/categories/{category_id}
POST /api/knowledge/categories/{category_id}/fields
PATCH /api/knowledge/categories/{category_id}/fields/{field_id}
DELETE /api/knowledge/categories/{category_id}/fields/{field_id}
```

限制：

- 默认门类 schema 第一版不允许在前端删除系统字段。
- 自定义门类字段可以增删改。
- 已有数据的字段删除必须提示影响范围。

## 5. 草稿页面

草稿不再是 JSON 编辑器。

流程：

1. 选择门类。
2. 选择操作：新增、修改、合并、归档。
3. 根据 schema 渲染表单。
4. 填写字段。
5. 点击校验。
6. 校验通过后允许入库。
7. 入库前自动备份。
8. 入库后刷新索引。

API：

```text
POST /api/drafts
GET  /api/drafts/{draft_id}
PATCH /api/drafts/{draft_id}
POST /api/drafts/{draft_id}/validate
POST /api/drafts/{draft_id}/apply
DELETE /api/drafts/{draft_id}
```

草稿显示：

- 门类；
- 操作类型；
- 影响字段；
- 校验状态；
- 风险提示；
- 修改摘要。

## 6. 资料上传页面

上传时必须选择门类：

- 商品资料；
- 聊天记录；
- 政策规则；
- ERP 导出；
- 自定义门类。

功能：

- 文件上传；
- 选择门类；
- 选择是否立即 AI 学习；
- 查看上传历史；
- 查看是否已学习；
- 查看生成候选数量。

API：

```text
POST /api/uploads
GET  /api/uploads
GET  /api/uploads/{upload_id}
POST /api/learning/jobs
GET  /api/learning/jobs
GET  /api/learning/jobs/{job_id}
```

## 7. AI 学习结果审核

“候选审核”改名为“AI 学习结果审核”。

卡片展示：

- 来源文件；
- 目标门类；
- AI 识别结果；
- 建议新增/修改字段；
- 原文证据；
- 冲突提示；
- 风险等级；
- 置信度；
- 操作按钮。

按钮：

- 编辑后入库；
- 直接入库；
- 合并到已有知识；
- 拒绝；
- 标记稍后处理。

API：

```text
GET  /api/candidates?status=pending
GET  /api/candidates/{candidate_id}
PATCH /api/candidates/{candidate_id}
POST /api/candidates/{candidate_id}/apply
POST /api/candidates/{candidate_id}/reject
POST /api/candidates/{candidate_id}/merge
```

要求：

- 候选详情默认不展示 JSON。
- 应展示“AI 准备改什么”。
- 应展示“为什么建议这么改”。
- 入库必须走 schema 校验和自动备份。

## 8. 一键检测

页面只展示用户可读结果。

快速检测：

- 最近 7 天新增或修改；
- 当前草稿；
- 当前候选；
- 最近上传影响范围。

全量检测：

- 所有门类；
- 所有 item；
- 所有 schema；
- 所有 resolver；
- 索引；
- 运行时证据包；
- 兼容编译产物。

结果展示：

- 总体状态；
- 通过项；
- 警告项；
- 故障项；
- 可一键修复项；
- 需人工处理项。

API：

```text
POST /api/diagnostics/run
GET  /api/diagnostics/runs
GET  /api/diagnostics/runs/{run_id}
POST /api/diagnostics/runs/{run_id}/apply-suggestion
```

一键修复规则：

- 安全修复可直接执行；
- 半自动修复生成草稿；
- 高风险修复只给建议。

## 9. 备份与还原

“版本回滚”改名为“备份与还原”。

功能：

- 一键备份；
- 自动备份列表；
- 按门类筛选；
- 查看备份摘要；
- 二次确认还原；
- 还原前自动备份；
- 撤销本次还原。

API：

```text
POST /api/backups
GET  /api/backups
GET  /api/backups/{backup_id}
POST /api/backups/{backup_id}/restore
POST /api/backups/{backup_id}/undo-restore
```

展示字段：

- 备份时间；
- 备份原因；
- 影响门类；
- 条目数量；
- 操作人；
- 是否可还原；
- 是否为还原前自动备份。

## 10. 系统状态

不显示原始 JSON。

显示模块：

- Web 管理台；
- 分类知识库；
- schema；
- resolver；
- 知识索引；
- 微信客服运行时；
- DeepSeek；
- 微信适配器；
- 上传目录；
- 备份目录；
- 待审核候选；
- 最近检测；
- 最近备份。

状态值：

- 正常；
- 警告；
- 异常；
- 未配置；
- 未检测。

API：

```text
GET /api/system/status
GET /api/system/runtime-locks
```

## 11. 页面测试要求

Playwright E2E 至少覆盖：

- 创建自定义门类；
- 新增商品知识；
- 新增政策知识；
- 保存草稿；
- 校验失败；
- 校验通过；
- 入库；
- 上传资料；
- 生成候选；
- 候选编辑后入库；
- 快速检测；
- 全量检测；
- 一键备份；
- 还原并撤销；
- 桌面和移动端截图。

