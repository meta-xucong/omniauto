# VPS 服务端代码实现清单 V2

> 2026-05-05 更新：共享公共知识发布链路已改为云端正式库唯一来源。旧 patch 写客户端 `data/shared_knowledge` 的条目只作为历史检查项保留；新开发以 `SHARED_PUBLIC_KNOWLEDGE_CLOUD_CANONICAL_CODE_CHECKLIST.md` 为准。

## 后端

- [x] proposal review 前增加 shared patch 安全校验。
- [x] patch 生成时自动补齐 `schema_version`、`patch_id`、`version`、`status`。
- [x] 配置 `WECHAT_SHARED_PATCH_SECRET` 时自动签名。
- [x] 新增 `POST /v1/admin/shared/patches/{patch_id}/push`。
- [x] patch push 根据 node/tenant 过滤目标节点。
- [x] release 保存 `sha256`、`signature`、`notes`。
- [x] 新增 `POST /v1/admin/releases/{release_id}/push`。

## Local 同步

- [x] `pull_shared_patch` 命令支持含 patch payload 时 preview/apply。
- [x] `check_update` 仍保持只检查更新。
- [x] `push_update` 保持 deferred，不自动安装。

## WEB

- [x] 共享公共知识页增加流程说明。
- [x] 候选库增加“查看详情”。
- [x] 正式共享库保留手动新增入口。
- [x] 增加已发布补丁列表和推送按钮。
- [x] 版本登记增加校验码、签名、更新说明。
- [x] 版本记录增加通知检查更新按钮。
- [x] 检查桌面/移动端无横向溢出。

## 测试

- [x] `node --check vps_admin/static/app.js`
- [x] `python -m py_compile vps_admin/app.py vps_admin/services.py sync/vps_sync.py`
- [x] `run_vps_admin_control_plane_checks.py`
- [x] `run_multi_tenant_auth_sync_checks.py`
- [x] Playwright VPS 页面烟测
