# 共享公共知识云端唯一正式库改造设计

> 2026-05-05 追加收敛：customer 客户端不再展示共享公共知识库或云端缓存页，也不再注册 `/api/shared-knowledge/*` 本地管理路由。客户端仅在后台静默刷新云端快照、提交正式知识衍生的共享候选；可见审核和治理全部留在 VPS admin。详见 `SHARED_PUBLIC_KNOWLEDGE_CLIENT_SURFACE_CLEANUP.md`。

## 1. 背景

上一版共享公共知识链路已经把“从 customer 正式知识提炼候选”放到了云端 proposal 审核流程里，但客户端仍然保留了 `data/shared_knowledge` 作为本地正式共享库，并且 `pull_shared_patch` 命令会把云端补丁写入这个目录。

这会造成三类混淆：

- 正式来源不唯一：云端 `shared_library` 和本地 `data/shared_knowledge` 都像“正式库”。
- 消费链路绕远：云端审核通过后先变成补丁，再写本地正式库，runtime 再从本地正式库读取。
- 新共享知识入口容易误解：本地 admin 可以直接编辑本地共享库，看起来像绕过云端审核。

本次改造把云端 `shared_library` 定义为唯一正式共享公共知识库。客户端只保留只读运行缓存，用于离线运行和 runtime 读取，不再把本地 `data/shared_knowledge` 当作正式库。

## 2. 目标

1. customer 正式知识新增或更新后，直接从 customer 正式知识中筛选可共享候选，并提交到云端 `/v1/shared/proposals`。
2. admin 在云端审核 proposal。只有 admin 接受后，内容才进入云端正式 `shared_library`。
3. 客户端从云端 `/v1/shared/knowledge` 拉取正式共享知识快照，写入只读运行缓存。
4. runtime 只读取 tenant 正式知识、本地商品专属知识、云端共享知识缓存，不再读取本地 `data/shared_knowledge`。
5. 旧 `pull_shared_patch` 命令不再写本地正式共享库，而是触发客户端刷新云端正式共享知识快照。

## 3. 非目标

- 不在客户端自动接受共享公共知识候选。
- 不让 LLM 在客户端消费共享知识时再做二次提炼。
- 不删除历史 `data/shared_knowledge` 文件。它只作为 legacy 数据或迁移参考保留，不再是 runtime 官方来源。
- 不改变 customer 私有正式知识和商品专属知识的所有权边界。

## 4. 新架构

```mermaid
flowchart LR
  A["Customer formal knowledge"] --> B["Local candidate scanner"]
  B --> C["Cloud /v1/shared/proposals"]
  C --> D["Cloud admin review"]
  D --> E["Cloud official shared_library"]
  E --> F["Cloud /v1/shared/knowledge snapshot"]
  F --> G["Client read-only runtime cache"]
  G --> H["Reply runtime / EvidenceResolver"]
```

权威边界：

- customer formal knowledge：客户自己的正式知识，仍由客户侧维护。
- cloud proposal：共享候选区，允许 AI 辅助判断，但不具备正式效力。
- cloud `shared_library`：唯一正式共享公共知识库。
- client runtime cache：云端正式库的只读快照，不允许本地编辑升级为正式共享知识。

## 5. 工作流

### 5.1 从正式知识提炼候选

触发点：

- 本地 admin 手动新增或更新正式知识。
- 待确认知识被应用进正式知识库。
- 客户端启动或周期同步时补扫未检查过的正式知识。

执行：

- `queue_shared_public_scan` 判断分类是否属于可扫描范围。
- `VpsLocalSyncService.upload_formal_knowledge_candidates` 读取 customer formal knowledge。
- 系统先做规则过滤，排除商品、门店、城市、价格、库存、合同、手机号、客户承诺、行业强绑定信息。
- LLM 可用于建议是否具备跨客户通用性。LLM 只生成候选建议，不写正式共享库。
- 候选通过 `/v1/shared/proposals` 提交云端。
- 本地只记录 scan cache，避免同一正式知识重复提交。

### 5.2 云端审核与发布

admin 在 VPS 控制台处理 proposal：

- `SharedKnowledgeService.submit_proposal` 保存候选。
- `review_assist` 用规则或 LLM 提供通用性、重复性、风险建议。
- admin 接受后，`review_proposal` 写入云端 `shared_library`。
- 云端仍可生成 patch 作为审计和推送记录，但 patch 不再是客户端正式共享库的写入载体。
- admin 点击推送时，云端创建 `pull_shared_patch` 命令。客户端收到后刷新云端正式共享知识快照。

### 5.3 客户端拉取共享知识

触发点：

- 客户端启动后。
- 周期同步。
- 收到 `pull_shared_patch` 命令。
- 本地 admin 点击刷新共享知识。

执行：

- 客户端调用 `/api/sync/shared/cloud-snapshot`。
- 本地服务调用云端 `/v1/shared/knowledge`。
- 云端返回当前 `shared_library` 快照、版本号、分类和条目。
- 客户端写入 `runtime/apps/wechat_ai_customer_service/cache/shared_knowledge`。
- runtime 读取该缓存参与证据检索。

### 5.4 离线行为

- VPS 未配置时，不执行候选扫描上传。
- VPS 不可用但已有共享知识缓存时，runtime 继续使用最近一次成功拉取的缓存。
- VPS 不可用且无缓存时，runtime 只使用 tenant 正式知识和商品专属知识。

## 6. API 设计

### 6.1 云端正式共享知识快照

`GET /v1/shared/knowledge`

查询参数：

- `tenant_id`：请求方当前 tenant，用于授权和审计，不用于过滤共享公共知识。
- `node_id`：本地节点身份，可选。
- `since_version`：客户端已有版本，可选。

响应：

```json
{
  "ok": true,
  "snapshot": {
    "schema_version": 1,
    "source": "cloud_official_shared_library",
    "version": "shared_...",
    "tenant_id": "default",
    "generated_at": "2026-05-05T00:00:00+00:00",
    "categories": [],
    "items": [],
    "deleted_item_ids": [],
    "ttl_seconds": 600
  }
}
```

授权：

- bearer session 可访问。
- 已注册 local node 可用 `node_id + X-Node-Token` 访问。

### 6.2 客户端刷新共享知识缓存

`POST /api/sync/shared/cloud-snapshot`

请求体：

```json
{
  "force": false,
  "since_version": "shared_..."
}
```

响应包含：

- `snapshot_version`
- `item_count`
- `category_count`
- `cache_root`
- `snapshot_path`
- `mode`
- `not_modified`

## 7. 本地缓存格式

缓存根目录：

```text
runtime/apps/wechat_ai_customer_service/cache/shared_knowledge/
```

文件：

- `snapshot.json`：云端原始快照。
- `registry.json`：runtime 可读取的分类注册表。
- `<category>/schema.json`
- `<category>/resolver.json`
- `<category>/items/<item_id>.json`

缓存写入策略：

- 每次成功拉取云端快照后重建缓存目录。
- 写入前校验目标目录在 runtime cache 下。
- 不写入 `apps/wechat_ai_customer_service/data/shared_knowledge`。

## 8. 兼容策略

- `data/shared_knowledge` 保留为 legacy 目录，不作为 runtime 默认来源。
- 如需临时回退，可用环境变量 `WECHAT_ENABLE_LEGACY_LOCAL_SHARED_KB=1` 让 runtime 追加读取 legacy 本地共享库。
- 本地 `/api/shared-knowledge/items` 改为读取云端缓存快照。
- 本地新增、编辑、删除共享公共知识 API 返回 410，提示应在云端 admin 审核或编辑。
- `pull_shared_patch` 命令保留名称，执行语义改为“刷新云端正式共享知识快照”。

## 9. 验收标准

- 客户端正式知识候选上传仍走 `/v1/shared/proposals`。
- 云端 admin 接受 proposal 后，`shared_library` 有正式条目。
- `/v1/shared/knowledge` 能返回云端正式共享知识快照。
- 客户端刷新后只写 runtime cache，不写 `data/shared_knowledge`。
- runtime 默认 roots 包含 tenant formal knowledge 和 cloud shared cache，不包含 legacy `data/shared_knowledge`。
- 启动同步文案从“应用补丁”改为“刷新云端共享知识”。
- 静态检查、重点回归和全量测试完成。
