# VPS Admin 控制平面开发需求文档

> 2026-05-05 更新：共享公共知识治理的正式落点是云端 `shared_library`。admin 审核通过后进入云端正式库，客户端通过 `/v1/shared/knowledge` 拉取只读快照；不再把云端补丁写入客户端本地 `data/shared_knowledge`。

## 1. 目标

在现有微信自动客服 local 程序之外，新增一个部署在 VPS 的 admin 专属控制台。它不面向客户展示，主要服务平台管理员完成账号管理、共享知识治理、local 节点运维、备份还原、版本发布和审计。

核心原则：

- local 端继续作为客户日常使用入口，承载客户自己的知识库、RAG 资料、RAG 经验和本地执行流程。
- VPS 端作为控制平面，不直接替代 local 端业务运行，只负责授权、调度、同步、备份、发布和治理。
- 唯一通用 admin 由平台管理员本人持有，可以登录 VPS 控制台，也可以登录任意 local 端；该账号不出现在客户可见账号列表中，也不能被 customer 创建、查看或删除。
- customer 只能管理自己的租户数据，不能修改共享全局知识库。
- guest 只能读授权范围内内容，不能写入。

## 2. 角色与权限

### 2.1 admin

- 唯一、通用、隐藏。
- 凭据由 VPS 环境变量或安全配置注入，不入库，不通过 API 创建。
- 可登录 VPS 服务端。
- 可登录任意 local 端，用于应急排障、迁移、备份和恢复。
- 可管理所有 tenant、customer、guest、local 节点、共享知识提案、共享补丁、备份、恢复、版本发布。
- 所有操作必须写审计日志。

### 2.2 customer

- 每个客户对应一个或多个 customer 账号，通常绑定一个 tenant。
- 可查看、修改自己 tenant 下的：
  - 用户商品专属知识
  - 用户正式知识
  - 用户 RAG 资料
  - 用户 RAG 经验
  - tenant 级同步设置
- 可提交共享知识候选，但不能直接写入共享全局知识库。
- 可开启或关闭自己 tenant 的云端备份。

### 2.3 guest

- 由 admin 或 customer 授权。
- 只可查看被授权 tenant 的可读内容。
- 不可修改知识、备份、同步、发布和账号权限。

## 3. 数据分层

### 3.1 local 默认存放

每个 customer tenant 在 local 保留独立数据目录：

- `product_item_knowledge`: 用户商品专属知识
- `knowledge_bases`: 用户正式知识
- `rag_sources`: 用户 RAG 原始资料
- `rag_chunks` / `rag_index` / `rag_cache`: 派生检索数据
- `sync`: 同步状态
- `runtime/backups`: 本地备份包

### 3.2 全局共享知识

共享全局知识仍在 local 保留本地副本，但写入模式不同：

- local 端客户不能直接修改共享全局知识库。
- local 端可上传共享知识候选到 VPS。
- VPS admin 审核候选，接受后生成共享知识 patch。
- local 端定期拉取已发布 patch，预览后应用到本地共享知识库。
- patch 必须是增量、可审计、可回滚的结构化 JSON 操作。

### 3.3 VPS 控制平面数据

VPS 保存控制面状态：

- tenants
- customer/guest users
- local nodes
- sessions
- command queue
- command results
- shared proposals
- shared patches
- backup requests
- restore requests
- releases
- audit events

当前落地版本先使用 JSON 状态仓，便于快速本地模拟和小规模部署；生产环境建议迁移到 Postgres，并把备份包和发布包放对象存储。

## 4. VPS Admin 控制台功能

### 4.1 用户与租户管理

必须支持：

- 新增 tenant
- 禁用 tenant
- 查看 tenant 同步状态
- 新增 customer
- 新增 guest
- 修改 customer/guest 授权 tenant
- 禁用或删除 customer/guest
- 查询账号审计记录

限制：

- admin 账号不允许通过控制台创建、修改、删除。
- admin 不允许出现在 customer/guest 用户列表。
- customer/guest 不能看到 admin 账号存在。

### 4.2 local 节点管理

VPS 需要管理多个 local 节点：

- local 节点注册
- local 节点心跳
- local 节点所属 tenant
- local 节点版本号
- local 节点能力声明
- 最近在线时间
- 待执行命令
- 命令执行结果

每台 local 节点注册后获得 `node_token`。生产环境必须通过一次性 enrollment token 或 admin 授权完成注册。

### 4.3 共享知识治理

流程：

1. local 提交共享知识候选 proposal。
2. VPS 保存为 `pending_review`。
3. admin 在 VPS 控制台查看差异、来源、风险。
4. admin 选择接受、拒绝或作废。
5. 接受后生成 `shared_patch`。
6. local 拉取 patch，先预览，再应用。
7. 应用结果写回 VPS。

共享知识不建议直接做“自动合并即发布”。可以用 AI 先整理归纳为候选 patch，但最终发布必须有人审。

### 4.4 备份与恢复

备份分三类：

- tenant 备份：备份指定客户的私有知识与 RAG 数据。
- shared 备份：备份共享全局知识。
- all 备份：admin 一键备份指定 local 的所有知识。

恢复流程：

1. admin 在 VPS 选择备份包。
2. VPS 向指定 local 下发 `restore_backup` 命令。
3. local 先执行 dry-run 校验。
4. 校验通过后才允许执行真实恢复。
5. 恢复前 local 必须再生成一次保护性快照。

当前代码落地先完成命令队列和结果回传；真实恢复写盘逻辑必须单独实现 dry-run、校验、快照、回滚后再开放。

### 4.5 推送更新

VPS 管理发布记录：

- release id
- channel
- version
- notes
- artifact url
- status

local 可通过 `/v1/updates/latest` 检查最新版本。正式推送更新时建议采用灰度：

- dev
- canary
- stable

更新包必须签名，local 应先验签再执行。

### 4.6 审计

必须记录：

- 登录
- 创建/修改/删除 tenant
- 创建/修改/删除 customer/guest
- 注册 local 节点
- 创建命令
- 命令回传
- 共享知识审核
- 备份请求
- 恢复请求
- 发布版本

审计日志至少包含：

- event id
- actor id
- action
- target type
- target id
- detail
- created at

## 5. 接口边界

### 5.1 VPS 管理接口

- `/v1/admin/tenants`
- `/v1/admin/users`
- `/v1/admin/nodes`
- `/v1/admin/commands`
- `/v1/admin/shared/proposals`
- `/v1/admin/shared/patches`
- `/v1/admin/backups`
- `/v1/admin/restores`
- `/v1/admin/releases`
- `/v1/admin/audit`

这些接口只允许 admin 访问。

### 5.2 local 节点接口

- `/v1/local/nodes/register`
- `/v1/local/nodes/{node_id}/heartbeat`
- `/v1/local/commands`
- `/v1/local/commands/{command_id}/result`

这些接口供 local 节点注册、心跳、拉取命令、回传结果。

### 5.3 共享知识接口

- `/v1/shared/proposals`
- `/v1/shared/patches`

proposal 可以由 local 提交。patch 只由 admin 审核发布。

### 5.4 认证接口

- `/v1/auth/login`
- `/v1/auth/me`

local 端可使用同一套 VPS 登录接口确认身份。admin 登录成功后可作为隐藏的平台管理员进入任意 local 端。

## 6. 当前代码落地点

新增：

- `apps/wechat_ai_customer_service/vps_admin/app.py`
- `apps/wechat_ai_customer_service/vps_admin/auth.py`
- `apps/wechat_ai_customer_service/vps_admin/services.py`
- `apps/wechat_ai_customer_service/vps_admin/store.py`
- `apps/wechat_ai_customer_service/vps_admin/static/`

增强：

- `apps/wechat_ai_customer_service/auth/vps_client.py`
- `apps/wechat_ai_customer_service/sync/vps_sync.py`

VPS 本地启动：

```powershell
python -m apps.wechat_ai_customer_service.vps_admin.app
```

默认地址：

```text
http://127.0.0.1:8766/
```

开发默认 admin：

```text
username: admin
password: 1234.abcd
```

生产环境必须通过环境变量改掉默认密码：

```powershell
$env:WECHAT_VPS_ADMIN_USERNAME="admin"
$env:WECHAT_VPS_ADMIN_PASSWORD="<strong-password>"
$env:WECHAT_VPS_ADMIN_USER_ID="platform-admin"
$env:WECHAT_VPS_NODE_ENROLLMENT_TOKEN="<one-time-or-rotated-token>"
```
