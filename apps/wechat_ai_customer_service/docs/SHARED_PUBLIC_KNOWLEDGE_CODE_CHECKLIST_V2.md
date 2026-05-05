# 共享公共知识库 V2 代码落地清单

## 服务端

- `vps_admin/store.py`
  - 增加 `shared_scan_state` 持久区。

- `vps_admin/services.py`
  - `SharedKnowledgeService.generate_universal_proposals`
    - 默认只扫描未检查 formal knowledge。
    - 生成候选前比对已有候选和正式共享库。
    - 写入 scan state。
    - 为候选生成 admin 审核建议。
  - `SharedKnowledgeService.submit_proposal`
    - 保存 `source_meta`。
    - 对客户端上传候选做重复过滤。
    - 生成保守审核建议。
  - `SharedKnowledgeService.refresh_proposal_review_assist`
    - 支持 admin 手动 LLM 复核。
  - `SharedKnowledgeService.review_proposal`
    - 采纳后写正式共享库、生成补丁并更新 scan state。
    - 拒绝/作废同样更新 scan state。

- `vps_admin/app.py`
  - 新增 `/v1/admin/shared/proposals/{proposal_id}/review-assist`。

- `vps_admin/static/app.js`
  - 候选列表展示 AI 审核建议摘要。
  - 候选详情展示通用性评分、重复比对、风险和 admin 确认清单。
  - 新增“AI复核建议”操作。

## 客户端

- `auth/permissions.py`
  - customer 允许执行自身 tenant 的 `commands:execute` 与 `updates:sync`。
  - guest 仍禁止写入与同步。

- `sync/vps_sync.py`
  - 新增 `upload_formal_knowledge_candidates`。
  - 新增本地 formal scan cache。
  - 未配置 VPS 时跳过候选扫描，避免浪费 token。

- `admin_backend/api/sync.py`
  - 新增 `/api/sync/shared/formal-candidates`。

- `admin_backend/services/shared_public_sync.py`
  - 新增正式知识入库后的后台触发器。

- `admin_backend/api/knowledge.py`
  - 手动新增/编辑 formal knowledge 后触发共享候选扫描。

- `admin_backend/api/candidates.py`
  - 待确认知识应用入库后触发共享候选扫描。

- `admin_backend/static/app.js`
  - 登录启动后执行注册节点、轮询命令、检查更新、提交未检查 formal 候选。
  - admin 切换客户数据空间后重新执行同步计划。
  - 本地共享页面“上传候选”改为“检查正式知识并提交候选”。

## 回归重点

- 重复执行 formal scan 不应重复产生候选。
- LLM 关闭时应有规则回退，并标记 `llm_used=false`。
- customer 可轮询自身命令并检查更新，不能操作其他 tenant。
- guest 不能提交共享候选、不能轮询命令。
- admin 采纳候选后必须生成正式共享知识和补丁。
- 客户端启动同步不能阻塞首页加载。
> 2026-05-05 更新：共享公共知识已经进入云端唯一正式库改造。本清单保留 V2 历史落地项；新清单见 `SHARED_PUBLIC_KNOWLEDGE_CLOUD_CANONICAL_CODE_CHECKLIST.md`。
