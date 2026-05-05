# 服务端/客户端分离交付边界

> 更新日期：2026-05-05

## 结论

可以沿着当前仓库继续开发，但必须按“单仓库、双交付包”的方式治理边界。代码不需要立刻拆成两个独立 Git 仓库；现在已经把影响客户端单独交付的运行时耦合点拆掉，并增加了边界测试，防止客户端代码再次直接 import 服务端私有模块。

交付给客户时不要打包整个 `apps/wechat_ai_customer_service/` 目录，因为其中包含 `vps_admin/` 服务端控制面。应该按客户端清单打包。

## 交付分区

客户端可交付源码：

- `admin_backend/`：客户本机控制台和本地 API。
- `auth/`：本地登录、VPS 登录客户端、会话模型。
- `sync/`：本地到 VPS 的 JSON 客户端、备份、云端共享知识租约缓存。
- `workflows/`：微信客服运行、知识检索、RAG、回复生成。
- `adapters/`、`storage/`、`exports/`：客户端运行依赖的适配、存储、导出工具。
- `configs/`、必要的 `data/` 模板、`knowledge_paths.py`、`llm_config.py`。注意客户端源码包应排除旧的 `data/shared_knowledge/`、版本快照、原始上传和待审核候选状态；共享公共知识只通过云端快照进入本地缓存。

服务端私有源码：

- `vps_admin/`：VPS admin 控制台、服务端状态、共享公共知识审核、客户账号治理、远程命令。
- `scripts/seed_vps_test_customer.py` 等只操作 VPS 控制面的脚本。
- VPS 部署脚本、真实服务端状态、admin 凭据和云端运行数据。

共享但可交付的公共工具：

- `exports/readable_export.py`：从原来的 VPS 目录挪出，客户端和服务端都可复用。
- `sync/shared_candidate_scanner.py`：客户端从正式知识中筛选共享候选的逻辑；它只负责生成 proposal，不具备云端审核/发布能力。

## 已修复的耦合点

此前存在两个会阻碍客户端单独交付的问题：

1. `sync/vps_sync.py` 上传共享候选时直接 import `vps_admin.services`。
2. 本地导出服务直接 import `vps_admin.readable_export`。

现在已改为：

- 客户端候选扫描迁移到 `sync/shared_candidate_scanner.py`。
- 可复用导出迁移到 `exports/readable_export.py`。
- `vps_admin/readable_export.py` 仅保留兼容 wrapper，服务端可继续工作，但客户端不依赖它。

## 边界测试

新增：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_delivery_boundary_checks.py
```

它会检查：

- 客户端可交付源码路径中不能 import `apps.wechat_ai_customer_service.vps_admin`。
- 导入客户端入口 `admin_backend.app`、`sync.vps_sync`、`workflows.listen_and_reply` 时，不能加载任何 `vps_admin` 模块。

以后只要这条测试过，客户端源码包就不会因为缺少服务端源码而在运行时崩掉。

## 推荐开发方式

短期继续保留单仓库，原因：

- 本地双端口联调方便：一个端口跑 VPS，一个端口跑客户客户端。
- API、租约、同步协议仍在快速迭代，单仓库更容易同步修改和测试。
- 现在有边界测试兜底，不会再无意识把服务端 import 回客户端。

中期可以升级为更明确的目录层：

```text
apps/wechat_ai_customer_service/
  client/
  server/
  shared/
```

但这会牵动大量 import 路径和测试脚本。当前阶段更稳妥的做法是先用“边界测试 + 交付清单”管理，等产品形态稳定后再做物理目录重排。

## 客户端打包原则

客户端包必须排除：

- `vps_admin/`
- VPS 部署脚本
- VPS 运行态数据
- 服务端 admin 凭据或环境文件
- 云端共享公共知识正式库状态
- `data/shared_knowledge/` 旧本地共享公共知识目录
- `data/versions/`、`data/raw_inbox/`、`data/review_candidates/` 等运行态/审核态数据

客户端包可以包含：

- 本地运行源码
- 客户自己的正式知识库和本地缓存结构
- `WECHAT_VPS_BASE_URL` 配置入口
- 空的或示例化的运行目录

正式部署时，客户端通过 `WECHAT_VPS_BASE_URL=https://<你的VPS域名或公网IP>` 连接服务端；服务端源码和 `shared_library` 只保留在你自己的 VPS 上。
