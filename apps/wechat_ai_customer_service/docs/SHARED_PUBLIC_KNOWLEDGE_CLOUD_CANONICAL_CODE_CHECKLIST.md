# 云端唯一共享公共知识库代码落地清单

## 路径与 runtime

- [x] `knowledge_paths.py` 新增云端共享知识运行缓存路径。
- [x] `runtime_knowledge_roots` 默认读取云端共享知识缓存，不再读取 `data/shared_knowledge`。
- [x] `layer_for_root` 能把云端共享知识缓存标记为 `shared` layer。
- [x] legacy 本地共享库仅在显式环境变量开启时参与 runtime。

## 云端服务

- [x] `SharedKnowledgeService` 提供正式共享知识快照方法。
- [x] 快照只来自云端 `shared_library`，不依赖客户端本地共享库。
- [x] 快照包含版本号、分类、条目、生成时间和 TTL。
- [x] `vps_admin/app.py` 暴露 `GET /v1/shared/knowledge`。
- [x] 端点支持 bearer session 和 local node token 授权。

## 客户端同步

- [x] `VpsLocalSyncService` 新增拉取云端共享知识快照的方法。
- [x] 成功拉取后写入 runtime read-only cache。
- [x] VPS 未配置时返回离线模式，并保留已有缓存。
- [x] `pull_shared_patch` 命令改为刷新云端快照。
- [x] 本地 apply patch 默认不再写 `data/shared_knowledge`。

## 本地 admin

- [x] `/api/sync/shared/cloud-snapshot` 支持后台刷新云端共享知识缓存。
- [x] `/api/shared-knowledge/items` 已从本地客户端取消注册。
- [x] 本地共享知识 create/update/delete 本地 API 已取消注册。
- [x] 本地页面移除共享公共知识导航、模块卡片、缓存页和手动候选提交按钮。
- [x] 启动同步改为后台静默刷新云端共享知识快照。

## VPS admin

- [x] 共享知识页面文案说明“云端正式库是唯一正式来源”。
- [x] 旧“保存本机共享库快照”动作改为保存云端正式库快照。
- [x] 推送 patch 的用户理解改为通知客户端刷新云端快照。

## 测试

- [x] sync 回归覆盖离线、mock VPS、命令刷新云端缓存。
- [x] VPS admin 回归覆盖 `/v1/shared/knowledge`。
- [x] runtime 回归覆盖云端缓存参与检索、legacy 本地共享库默认不参与。
- [x] local admin 回归覆盖共享知识本地 UI/API 已移除，后台同步仍保留。
- [x] Python 编译检查通过。
- [x] 前端 JS `node --check` 通过。
- [x] 仓库全量测试完成。
# 2026-05-05 租约缓存补充

- [x] VPS `/v1/shared/knowledge` 下发 `cloud_authoritative_lease` 租约字段。
- [x] 本地 `snapshot.json` 过期后不再进入 `runtime_knowledge_roots()`。
- [x] `not_modified` 响应会续租并持久化本地缓存。
- [x] 本地启动/周期同步按服务端 `refresh_after_seconds` 安排下一次刷新。
- [x] 增加真实 HTTP 双端口联调脚本，覆盖本地客户端连接 VPS 服务端。
- [x] 增加公网/VPS 连接配置说明。
