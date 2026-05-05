# VPS-LOCAL 命令与同步协议

## 1. 协议目标

VPS 不直接操控 local 文件系统，而是通过命令队列让 local 主动拉取、执行、回传结果。

这样设计的原因：

- local 常在 NAT、家庭网络或客户电脑后面，VPS 主动连 local 不稳定。
- local 主动出站访问 VPS 更容易部署。
- 命令可审计、可重试、可限流。
- 高危动作可以先进入 queued 状态，等待 local dry-run。

## 2. 节点注册

请求：

```http
POST /v1/local/nodes/register
X-Enrollment-Token: <enrollment-token>
```

请求体：

```json
{
  "node_id": "local-shop-a-01",
  "display_name": "Shop A Local",
  "tenant_ids": ["tenant_a"],
  "version": "0.1.0",
  "capabilities": ["backup_all", "backup_tenant", "pull_shared_patch", "check_update"]
}
```

响应：

```json
{
  "ok": true,
  "node": {
    "node_id": "local-shop-a-01",
    "tenant_ids": ["tenant_a"],
    "node_token": "node_xxx"
  }
}
```

local 需要把 `node_token` 写入本机安全配置：

```text
WECHAT_LOCAL_NODE_ID=local-shop-a-01
WECHAT_LOCAL_NODE_TOKEN=node_xxx
```

## 3. 心跳

请求：

```http
POST /v1/local/nodes/{node_id}/heartbeat
X-Node-Token: <node-token>
```

请求体：

```json
{
  "status": "online",
  "version": "0.1.0",
  "metrics": {
    "pending_jobs": 0,
    "last_backup_at": "2026-04-29T12:00:00+08:00"
  }
}
```

VPS 更新 `last_seen_at`、版本号和指标。

## 4. 命令轮询

请求：

```http
GET /v1/local/commands?tenant_id=tenant_a&node_id=local-shop-a-01
X-Node-Token: <node-token>
```

响应：

```json
{
  "ok": true,
  "commands": [
    {
      "command_id": "cmd_xxx",
      "type": "backup_tenant",
      "tenant_id": "tenant_a",
      "node_id": "local-shop-a-01",
      "payload": {},
      "created_at": "2026-04-29T12:00:00+00:00"
    }
  ]
}
```

VPS 将匹配命令从 `queued` 标记为 `sent`，并增加 attempts。

## 5. 命令结果回传

请求：

```http
POST /v1/local/commands/{command_id}/result
X-Node-Token: <node-token>
```

成功：

```json
{
  "command_id": "cmd_xxx",
  "accepted": true,
  "result": {
    "ok": true,
    "backup_id": "backup_xxx",
    "package_path": "D:/AI/AI_RPA/runtime/..."
  }
}
```

失败：

```json
{
  "command_id": "cmd_xxx",
  "accepted": false,
  "error": "unsupported command type"
}
```

VPS 根据结果更新命令状态：

- `succeeded`
- `failed`

并写入 command_results 和 audit。

## 6. 命令类型

### 6.1 backup_tenant

备份指定 tenant 私有知识。

```json
{
  "type": "backup_tenant",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01"
}
```

local 执行：

- 打包 tenant 私有知识。
- 生成 manifest。
- 回传 backup_id、package_path、bytes、digest。
- 后续版本再上传备份包到 VPS 或对象存储。

### 6.2 backup_all

admin 一键备份指定 local 的所有知识。

```json
{
  "type": "backup_all",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01"
}
```

注意：

- `tenant_id` 用于路由到 local 节点授权范围。
- 实际备份 scope 是 all。
- 必须由 admin 创建。

### 6.3 pull_shared_patch

要求 local 拉取共享知识 patch。

```json
{
  "type": "pull_shared_patch",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01",
  "payload": {
    "patch_id": "patch_xxx"
  }
}
```

local 应先 preview，再 apply。

### 6.4 check_update

要求 local 检查最新版本。

```json
{
  "type": "check_update",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01"
}
```

### 6.5 restore_backup

要求 local 从指定备份恢复。

```json
{
  "type": "restore_backup",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01",
  "payload": {
    "backup_id": "backup_xxx",
    "dry_run": true
  }
}
```

当前落地阶段只建立协议和命令闭环。真实恢复必须等以下能力补齐后开放：

- backup digest 校验
- dry-run 报告
- 恢复前快照
- 回滚
- 恢复后知识完整性检查

### 6.6 push_update

要求 local 拉取并安装更新包。

```json
{
  "type": "push_update",
  "tenant_id": "tenant_a",
  "node_id": "local-shop-a-01",
  "payload": {
    "release_id": "release_xxx",
    "version": "0.2.0",
    "artifact_url": "https://example.com/releases/0.2.0.zip",
    "signature": "..."
  }
}
```

真实执行前必须验签。

## 7. 共享知识 proposal

local 提交：

```http
POST /v1/shared/proposals
```

请求体：

```json
{
  "tenant_id": "tenant_a",
  "title": "售后政策共性总结",
  "summary": "从客户 A 的售后知识中归纳出的通用规则",
  "operations": [
    {
      "op": "upsert_json",
      "path": "global_guidelines/items/after_sale_policy.json",
      "content": {
        "schema_version": 1,
        "id": "after_sale_policy",
        "data": {
          "title": "售后政策"
        }
      }
    }
  ]
}
```

admin 审核接受后，VPS 生成 patch。

## 8. 错误处理

local 轮询失败：

- 保持本地正常运行。
- 记录同步错误。
- 下次继续轮询。

命令执行失败：

- 回传 `accepted=false` 或 `ok=false`。
- 附带错误原因。
- VPS 标记 failed。
- admin 可重试或作废。

VPS 不可达：

- local 使用本地已有知识和会话策略。
- 若 `WECHAT_AUTH_REQUIRED=1` 且 VPS 不可达，则登录失败。
- 若非强制认证，可回落到本地开发账号。
> 2026-05-05 更新：`pull_shared_patch` 的客户端执行语义已调整为“刷新云端正式共享知识快照”。历史 patch payload 继续作为审计和兼容字段保留，但客户端不再把它写入 `data/shared_knowledge`。
