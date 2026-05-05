# VPS 服务端开发文档 V2

> 2026-05-05 更新：共享公共知识不再通过补丁写入客户端本地正式库。新的实现以云端 `shared_library` 为唯一正式来源，`pull_shared_patch` 的客户端语义为刷新 `/v1/shared/knowledge` 快照到 runtime 只读缓存。

## 1. 涉及模块

- `apps/wechat_ai_customer_service/vps_admin/app.py`
- `apps/wechat_ai_customer_service/vps_admin/services.py`
- `apps/wechat_ai_customer_service/vps_admin/static/index.html`
- `apps/wechat_ai_customer_service/vps_admin/static/app.js`
- `apps/wechat_ai_customer_service/vps_admin/static/styles.css`
- `apps/wechat_ai_customer_service/sync/vps_sync.py`
- `apps/wechat_ai_customer_service/tests/run_vps_admin_control_plane_checks.py`
- `apps/wechat_ai_customer_service/tests/run_multi_tenant_auth_sync_checks.py`

## 2. 后端接口

### 2.1 推送共享知识补丁

```http
POST /v1/admin/shared/patches/{patch_id}/push
```

请求体：

```json
{
  "tenant_id": "",
  "node_id": "",
  "all_nodes": true
}
```

返回：

```json
{
  "ok": true,
  "patch": {},
  "commands": []
}
```

规则：

- admin only。
- `node_id` 存在时只推送给这个节点。
- `tenant_id` 存在时只推送给含该 tenant 的节点。
- 都不传时推送给所有已注册节点。
- 没有匹配节点时返回 404，避免 admin 误以为已经下发。

### 2.2 推送版本检查

```http
POST /v1/admin/releases/{release_id}/push
```

请求体：

```json
{
  "tenant_id": "",
  "node_id": "",
  "mode": "check_update"
}
```

规则：

- 默认只创建 `check_update` 命令。
- `mode=push_update` 时只下发 payload，不在 local 自动安装。

## 3. 服务端服务层

### 3.1 SharedKnowledgeService

新增能力：

- `validate_operations_as_patch`
- `sign_patch_if_configured`
- `push_patch`

采纳候选时：

1. 组装 patch。
2. 安全校验 patch。
3. 写正式共享库。
4. 可选签名。
5. 写 `shared_patches`。

### 3.2 ReleaseService

新增能力：

- 保存 `sha256`、`signature`、`notes`。
- `push_release` 创建更新命令。

### 3.3 CommandService

增加辅助方法：

- `create_system_command`
- 或继续复用 `create_command`，但由 push 服务负责组装 payload。

## 4. 前端页面

### 4.1 共享公共知识

分为四块：

- 共享知识流程说明
- 候选待审核
- 正式共享库
- 已发布补丁

候选详情用抽屉展示，不再只依赖卡片摘要。

### 4.2 版本更新

新增字段：

- 校验码 `sha256`
- 签名 `signature`
- 更新说明 `notes`

版本记录增加“通知客户电脑检查更新”按钮。

## 5. 测试

至少覆盖：

- proposal 采纳前安全校验。
- unsafe proposal 被拒绝。
- 采纳后 patch 带签名。
- patch push 创建 `pull_shared_patch` 命令。
- local `pull_shared_patch` 命令能 preview/apply。
- release push 创建 `check_update` 命令。
- VPS 页面包含补丁区、候选详情区、推送按钮。
- 桌面和移动端主要页面无横向溢出。

## 6. 手工验收路径

1. 启动 VPS 控制台：`python -m apps.wechat_ai_customer_service.vps_admin.app`
2. 打开 `http://127.0.0.1:8766/`
3. 登录 admin。
4. 进入“共享公共知识”。
5. 查看候选，采纳一条。
6. 在“已发布补丁”中点击推送。
7. 到“客户电脑连接/命令队列”确认生成 `pull_shared_patch`。
8. 到 Local 客户端轮询命令，确认共享知识可应用。
