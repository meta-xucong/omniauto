# 共享公共知识客户端无感化收敛

## 结论

共享公共知识的可见治理面只保留在 VPS admin。customer 客户端不再展示“共享公共知识库”、云端共享知识缓存、手动刷新、手动提交候选等入口。

客户端仍然会在后台做两件事：

1. 从 VPS 拉取 `/v1/shared/knowledge`，写入 runtime 只读缓存，供客服 runtime 检索使用。
2. 在客户正式知识变更或启动同步时，将适合共享的正式知识提交为云端 proposal，等待 VPS admin 审核。

## 本地端行为

- 不注册 `/api/shared-knowledge/*` 本地管理路由。
- 不展示 `shared_public` 导航、模块卡片或页面面板。
- 不展示手动“检查正式知识并提交候选”按钮。
- 不展示共享知识同步阻塞弹窗。云端快照刷新失败只记录到前端日志，不阻塞客户继续使用已有缓存。
- 保留 `/api/sync/shared/cloud-snapshot` 作为后台快照刷新入口。
- 保留 `/api/sync/shared/formal-candidates` 作为后台候选提交入口。

## 云端端行为

- VPS admin 继续作为唯一共享公共知识治理入口。
- admin 在云端查看候选、AI 辅助审核、采纳/拒绝、编辑正式共享库。
- admin 下发历史 `pull_shared_patch` 命令时，客户端执行语义仍是刷新云端快照。

## 验收点

- customer/admin 登录本地客户端时，HTML 中不出现“共享公共知识库”入口。
- 本地 `/api/shared-knowledge/items` 返回 404。
- 本地静态 JS 不调用 `/api/shared-knowledge`。
- 本地静态 JS 仍调用 `/api/sync/shared/cloud-snapshot` 和 `/api/sync/shared/formal-candidates`。
- VPS admin 页面仍保留共享公共知识治理。
