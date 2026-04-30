# VPS-LOCAL 协作测试策略

## 1. 结论

这个服务端-客户端协作架构可以先在本地完整模拟，再上真实 VPS 做网络、部署和安全验证。

推荐顺序：

1. 本地协议模拟。
2. 本地双进程联调。
3. 局域网或 localhost 端到端。
4. 真实 VPS 预生产。
5. 小范围真实客户灰度。

不建议一开始直接拿真实 VPS 测所有功能，因为备份、恢复、推送更新属于高影响动作。先把协议、权限和状态机在本地跑稳，再把真实 VPS 当成部署环境差异来验证。

## 2. L0 静态检查

目标：

- Python 语法正确。
- FastAPI app 可导入。
- 文档与代码入口存在。

命令：

```powershell
python -m compileall apps/wechat_ai_customer_service/vps_admin apps/wechat_ai_customer_service/auth apps/wechat_ai_customer_service/sync
```

通过标准：

- 无语法错误。
- 无 import error。

## 3. L1 单进程 TestClient 协议测试

目标：

- 不启动真实网络。
- 用 FastAPI TestClient 模拟 VPS。
- 验证 admin、tenant、user、node、command、proposal、release 全流程。

覆盖：

- admin 登录成功。
- admin 不出现在用户列表。
- 禁止创建 role=admin 的用户。
- 创建 tenant。
- 创建 customer。
- 创建 guest。
- customer 可登录。
- local node 注册。
- local node 心跳。
- admin 创建备份命令。
- local 轮询命令。
- local 回传结果。
- VPS 命令状态变为 succeeded。
- local 提交共享知识 proposal。
- admin 接受 proposal。
- VPS 生成 shared patch。
- admin 创建 release。
- `/v1/updates/latest` 返回 release。

命令：

```powershell
python apps/wechat_ai_customer_service/tests/run_vps_admin_control_plane_checks.py
```

通过标准：

- 脚本返回 exit code 0。
- JSON 输出 `ok: true`。

## 4. L2 本地双进程联调

目标：

- VPS admin 作为独立服务跑在本地端口。
- local admin 作为独立服务跑在另一个端口。
- local 通过 `WECHAT_VPS_BASE_URL` 请求 VPS。

启动 VPS：

```powershell
python -m apps.wechat_ai_customer_service.vps_admin.app
```

默认：

```text
http://127.0.0.1:8766/
```

启动 local：

```powershell
python -m apps.wechat_ai_customer_service.admin_backend.app
```

默认：

```text
http://127.0.0.1:8765/
```

local 环境变量：

```powershell
$env:WECHAT_VPS_BASE_URL="http://127.0.0.1:8766"
$env:WECHAT_AUTH_REQUIRED="1"
```

验证：

- VPS admin 登录。
- VPS 创建 tenant/customer。
- local 使用 customer 登录。
- VPS 使用 admin 登录 local。
- VPS 下发 backup_tenant。
- local 轮询并执行。
- VPS 看到 command result。

## 5. L3 真实 VPS 预生产测试

目标：

- 验证公网网络、HTTPS、环境变量、systemd、反向代理、证书、文件权限。

建议部署：

- VPS: Ubuntu LTS。
- 反向代理: Nginx/Caddy。
- HTTPS: Let's Encrypt。
- 进程管理: systemd。
- 状态仓: 预生产可 JSON，生产建议 Postgres。
- 备份包: 预生产可本地磁盘，生产建议对象存储。

必须配置：

```text
WECHAT_VPS_ADMIN_USERNAME
WECHAT_VPS_ADMIN_PASSWORD
WECHAT_VPS_ADMIN_USER_ID
WECHAT_VPS_NODE_ENROLLMENT_TOKEN
WECHAT_VPS_ADMIN_STATE_PATH
```

真实 VPS 测试顺序：

1. `/v1/health`。
2. admin 登录。
3. 创建测试 tenant。
4. 创建测试 customer。
5. local 设置 `WECHAT_VPS_BASE_URL=https://<vps-domain>`。
6. local node 注册。
7. node heartbeat。
8. admin 下发 backup_tenant。
9. local 轮询并执行。
10. VPS 检查 command succeeded。
11. 提交共享知识 proposal。
12. admin 接受 proposal。
13. local 拉取 shared patch 预览。
14. 创建 release。
15. local 检查 latest update。

暂不执行：

- 非 dry-run restore。
- 自动安装更新。
- 大规模 backup_all。

## 6. L4 灰度实盘测试

目标：

- 选一个低风险客户 tenant。
- 使用真实知识库副本。
- 验证备份、防丢、共享知识候选和版本检查。

灰度步骤：

1. 创建 tenant。
2. 导入客户知识副本。
3. 开启自动备份。
4. 连续运行 24 小时。
5. 检查同步错误率。
6. 手动触发 tenant 备份。
7. 只做 restore dry-run。
8. 提交一个共享知识 proposal。
9. admin 审核接受。
10. local preview patch。

通过标准：

- local 客服主流程不受 VPS 波动影响。
- VPS 不可达时 local 仍可使用本地知识。
- 强制登录模式下 VPS 不可达会拒绝登录，符合预期。
- 自动备份不会覆盖本地数据。
- 共享 patch 不会写出共享知识根目录。
- 审计可追踪每个高危动作。

## 7. 故障注入

必须测试：

- VPS 断网。
- node token 错误。
- enrollment token 错误。
- tenant 未授权。
- 命令重复轮询。
- 命令执行失败。
- proposal path escape。
- release artifact url 缺失。
- backup 包损坏。
- restore dry-run 失败。

## 8. 是否需要真实 VPS

当前阶段不强制需要真实 VPS。

原因：

- 核心协议可以本地 TestClient 覆盖。
- 命令状态机可以本地确定性验证。
- 真实 restore 和 push_update 尚未开放执行。
- 真实 VPS 主要验证部署、HTTPS、网络和权限配置。

等以下条件满足后，再接真实 VPS 更合适：

- 本地 L0-L2 全部通过。
- admin 默认密码已替换。
- enrollment token 已启用。
- backup 上传存储方案确定。
- restore 仍保持 dry-run。
- 有一个测试 tenant 和一份可丢弃数据。

如果提供真实 VPS，我建议只做 L3 预生产测试，不直接做破坏性恢复或自动更新。
