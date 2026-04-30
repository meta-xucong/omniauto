# WeChat AI Customer Service Multi-Tenant VPS-LOCAL Requirements

## 1. Goal

把当前微信自动客服升级为多账户、多租户、本地优先、VPS 协同的交付版本。

Local 端继续承担微信客户端 RPA、知识库检索、RAG 检索、客服回复、管理台和本地数据存储。VPS 端承担登录授权、云端备份、共享知识候选汇总、共享知识补丁分发、远程运维指令和客户端更新通知。

本轮改造的核心不是替换现有客服流程，而是在现有 `shared_knowledge + tenants/default + PostgreSQL/JSON fallback` 基础上补齐身份、权限、租户上下文和 VPS-LOCAL 协议骨架。

## 2. Design Principles

- Local-first: 客服运行、微信窗口控制、正式知识检索和 RAG 检索默认使用本地数据。
- Tenant isolation: customer 私有知识、RAG 资料、RAG 经验、上传资料、候选知识、运行状态必须按 `tenant_id` 隔离。
- Shared knowledge is governed: customer 不能直接修改正式共享知识，只能提交共享候选；正式补丁由 admin 或审核流程发布。
- RAG remains auxiliary: RAG 资料和 RAG 经验不能授权价格、账期、合同、退款、赔偿、发货承诺等高风险业务决策。
- VPS is a coordinator: VPS 不接管微信 RPA，不成为实时客服链路的强依赖。
- Safe fallback: 没配置 VPS 时，本地开发和自动测试可以使用 local auth fallback；生产模式必须启用远端授权。
- Auditable operations: 权限越界、备份、恢复、共享补丁、远程命令和更新检查都要可审计。

## 3. Account Model

### 3.1 Roles

`admin`

- 最高权限。
- 可查看和修改任意 customer 的数据。
- 可查看、修改、发布共享全局知识。
- 可触发全量备份、远程命令、共享补丁下发和更新推送。

`customer`

- 客户主账户。
- 只能查看和修改自己 tenant 下的数据。
- 可管理自己的商品专属知识、正式知识、RAG 资料、RAG 经验、同步备份配置。
- 不能修改正式共享全局知识。
- 可提交共享知识候选。

`guest`

- 只读访客。
- 由 admin 或 customer 授权。
- 只能查看授权范围内的数据。
- 不能执行任何写入、删除、同步、备份、恢复、发布、审批或远程命令操作。

### 3.2 Permission Shape

权限由 role、tenant scope、resource、action 共同决定：

```text
role: admin | customer | guest
tenant_scope: all | <tenant_id>
resource: tenant_knowledge | tenant_rag | rag_experience | shared_knowledge | backups | settings | commands | updates
action: read | write | delete | backup | restore | sync | approve | publish | execute
```

## 4. Data Layout

现有目录保留并扩展：

```text
apps/wechat_ai_customer_service/data/shared_knowledge/
  registry.json
  global_guidelines/
  proposals/
  patches/

apps/wechat_ai_customer_service/data/tenants/<tenant_id>/
  tenant.json
  knowledge_bases/
  product_item_knowledge/
  rag_sources/
  rag_chunks/
  rag_index/
  rag_cache/
  rag_experience/
  sync/
```

运行时状态按 tenant 隔离：

```text
runtime/apps/wechat_ai_customer_service/tenants/<tenant_id>/
  state/
  logs/
  admin/
  backups/
  commands/
```

兼容现有路径：

- 未传 `tenant_id` 时继续使用 `default`。
- 旧 `runtime/apps/wechat_ai_customer_service/admin/*` 在当前阶段保留，后续迁移到 tenant runtime root。
- `active_tenant_id()` 仍保留，但应优先从请求/流程上下文读取，而不是只读环境变量。

## 5. Knowledge Layering

运行时读取顺序：

1. 用户商品专属知识：`tenant/product_item_knowledge`
2. 用户正式知识：`tenant/knowledge_bases`
3. 共享全局知识：`shared_knowledge`
4. 用户 RAG 资料：`tenant/rag_sources + chunks + index`
5. 用户 RAG 经验：`tenant/rag_experience`

优先级规则：

- 用户正式业务事实优先于共享话术。
- 共享知识可以约束安全边界和表达风格，但不能覆盖用户商品价格、库存、售后等私有业务事实。
- RAG 只能提供软参考和来源证据，不能绕过正式知识和安全规则。

## 6. VPS-LOCAL Responsibilities

### 6.1 VPS Responsibilities

- 登录授权和 session 刷新。
- 保存 tenant 备份包和备份索引。
- 接收共享知识候选。
- 生成共享知识候选补丁。
- 发布审核后的共享知识补丁。
- 发布远程命令，例如 `backup_all`。
- 发布客户端更新元数据。

### 6.2 Local Responsibilities

- 启动时向 VPS 请求授权。
- 维护本地 session、tenant context 和权限判断。
- 按 tenant 读写知识、RAG、经验、状态。
- 定期或手动生成备份包。
- 拉取、校验并应用共享知识补丁。
- 轮询远程命令并执行被允许的命令。
- 检查更新但不执行未签名更新。

## 7. Authorization Flow

```text
User -> Local Admin: login
Local Admin -> VPS: account credential/device proof
VPS -> Local Admin: signed session
Local Admin: create AuthContext + TenantContext
Local API: enforce role and tenant scope
Workflow: pass tenant_id into knowledge/RAG/runtime state
```

开发/测试 fallback：

- `WECHAT_AUTH_REQUIRED=0` 时允许本地默认 admin session，避免破坏现有测试。
- `WECHAT_AUTH_REQUIRED=1` 时未登录请求必须返回 401。
- 配置了 `WECHAT_VPS_BASE_URL` 时优先走 VPS 登录。
- 未配置 VPS 但要求远端登录时返回可解释错误，不默默降级。

## 8. Backup And Sync

### 8.1 Shared Knowledge Sync

Local 上传的是共享知识候选，不是正式共享知识：

```text
shared proposal -> VPS candidate pool -> dedupe/summarize -> patch candidate -> admin approve -> signed patch -> Local apply
```

Local 应用补丁前必须检查：

- patch schema version
- patch version monotonicity
- signature when signing key is configured
- file path safety
- conflict preview

### 8.2 Customer Private Backup

customer 可配置是否自动备份自己的 tenant 数据：

- disabled: 不自动上传私有数据。
- daily: 每日备份。
- weekly: 每周备份。
- manual: 仅手动备份。

备份范围：

- `tenant.json`
- `knowledge_bases`
- `product_item_knowledge`
- `rag_sources`
- `rag_experience`
- `review_candidates` 中属于该 tenant 的候选记录
- tenant 运行状态摘要

RAG chunks/index/cache 可重建，默认不纳入完整备份；如客户要求可设 `include_derived=true`。

### 8.3 Admin Full Backup

admin 可通过 VPS 下发 `backup_all`：

```text
VPS command -> Local poll -> verify command -> build shared backup -> build every tenant backup -> upload -> ack result
```

## 9. Update Push

VPS 提供最新版本元数据：

```json
{
  "version": "x.y.z",
  "channel": "stable",
  "artifact_url": "...",
  "sha256": "...",
  "signature": "...",
  "notes": "..."
}
```

Local 只下载并进入待更新状态；自动覆盖代码需要单独审批。本轮只实现检查和下载/校验骨架，不做静默升级。

## 10. Acceptance Criteria

- GitHub backup status is confirmed before implementation.
- admin can access all tenants and shared knowledge APIs.
- customer can read/write only own tenant data and cannot write shared knowledge.
- guest can read authorized data and all write attempts are blocked.
- tenant context can switch existing knowledge/RAG services without environment-only routing.
- tenant backup package can be generated locally with manifest and hashes.
- shared patch preview/apply path exists and refuses unsafe paths.
- remote command polling can handle `backup_all` safely in local/mock mode.
- focused auth/sync tests pass.
- existing regression suite passes in JSON fallback and PostgreSQL mode where available.
- File Transfer Assistant live test passes or records a concrete environmental blocker.
