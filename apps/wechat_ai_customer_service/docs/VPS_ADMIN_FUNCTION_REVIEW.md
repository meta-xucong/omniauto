# VPS Admin 功能复核与优化说明

## 已按本轮需求补齐

- VPS admin 控制台改为与 local 客户端一致的中文玻璃面板风格。
- 当前客户端数据已可打包为 `test01` customer 账号：
  - 账号：`test01`
  - 密码：`1234.abcd`
  - 绑定租户：`default`
  - 服务端可看到对应客户数据包。
- 共享公共知识已提供服务端查看和同步快照入口。
- 备份与还原页已提供：
  - 一键备份所有数据
  - 一键还原所有数据（默认演练，不直接覆盖）

## 当前共享公共知识状态

当前共享公共知识位于：

```text
apps/wechat_ai_customer_service/data/shared_knowledge
```

当前有 1 个共享分类：

- `global_guidelines`

当前有 1 条共享公共知识：

- `customer_service_style_guidelines`

它主要保存通用客服表达、边界原则、自动回复与转人工规则。

## 是否已和专业知识区分

已区分。

- 共享公共知识：`data/shared_knowledge`
- 客户正式知识：`data/tenants/<tenant>/knowledge_bases`
- 商品专属知识：`data/tenants/<tenant>/product_item_knowledge`
- 客户 RAG 资料和经验：`data/tenants/<tenant>/rag_*`

在 PostgreSQL 结构中也通过 `knowledge_categories.layer` 和 `knowledge_items.layer` 区分 shared / tenant / product 层。

## 保留的功能

- 客户/访客账号管理：必要。
- local 节点连接状态：必要，后续真实 VPS 依赖它下发备份、还原、更新命令。
- 共享知识 proposal/patch：必要，后续多人客户贡献共享知识时需要审核流。
- 版本更新：保留，但当前只登记发布信息；真实安装前必须加签名校验和灰度策略。
- 审计日志：必要，所有 admin 高危动作都要可追踪。

## 优化过的功能

- “还原”改成默认演练入口，避免误操作覆盖客户本地数据。
- “备份”拆成服务端可立即打包的本地模拟入口，以及面向真实 local 节点的命令队列入口。
- “test01 初始化”只作为当前交付/测试入口，生产环境不需要给客户展示。

## 暂不开放或后续再做

- 非 dry-run 真实还原：需要先完成恢复前快照、校验、回滚。
- 自动安装更新：需要更新包签名、校验、灰度和失败回滚。
- 多 VPS/多区域部署：当前单 VPS 控制平面足够。
- 大文件备份上传对象存储：当前先打包并记录服务端可见路径，真实部署建议接入对象存储。
