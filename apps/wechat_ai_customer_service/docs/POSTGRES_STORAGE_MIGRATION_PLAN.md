# PostgreSQL 存储层升级改造计划

## 目标

将微信 AI 客服系统当前的 JSON/文件存储，逐步升级为 PostgreSQL 主存储。迁移必须保留现有 JSON 文件模式作为兼容回退，避免一次性切换导致管理台、客服运行时、RAG 检索、候选审核和版本回滚同时失效。

本轮范围包括：

- 正式知识库：全局通用知识、租户通用知识、商品专属知识。
- 管理台数据：候选审核、上传索引、审计日志、诊断忽略、版本元数据。
- RAG 数据：source、chunk、index entry、experience。
- 迁移工具：从现有文件结构导入 PostgreSQL，并输出 parity 校验报告。
- 配置切换：默认继续使用 JSON；设置 `WECHAT_STORAGE_BACKEND=postgres` 后启用 PostgreSQL。

本轮不做：

- 将微信聊天监听状态、Excel 填表产物、浏览器/微信运行日志迁入数据库。
- 多机部署、读写分离、连接池高可用。
- pgvector 向量检索。当前 RAG 仍使用本地混合检索算法，先把 chunk/index 元数据迁入 PostgreSQL。

## 迁移原则

1. JSON 模式永远可跑：没有数据库或 DSN 时，现有测试和本地使用不受影响。
2. PostgreSQL 模式优先读库：如果启用数据库，则正式知识和 RAG 数据从数据库读取。
3. 文件兼容只做回退：PostgreSQL 为空时允许从文件回退，便于冷启动和迁移前预览。
4. 写入双保险：数据库模式下写入数据库；必要时保留可选文件镜像，便于人工排查。
5. schema 先稳定：数据库字段以业务维度拆出索引列，同时保留 `payload JSONB` 存放完整结构，避免信息损失。
6. 阶段验收：每完成一章先跑静态检查和局部测试，再进入下一章。

## 阶段拆分

### Phase 0：发布当前稳定系统

- 当前 verified 系统已提交并推送到 `origin/master`。
- `.gitignore` 已排除运行期目录和本地状态。
- 后续 PostgreSQL 改造在 `codex/postgres-storage-migration` 分支开发。

### Phase 1：文档与 schema

- 新增 PostgreSQL schema 文档。
- 新增迁移运行手册。
- 新增数据库 DDL：租户、知识分类、知识条目、候选、上传、审计、版本、RAG 数据。
- 增加环境变量说明。

验收：

- 文档存在且相互引用清楚。
- DDL 可以被静态解析。
- 无真实密钥、无本地路径依赖。

### Phase 2：通用数据库基础设施

- 新增 `storage` 包：
  - 配置读取。
  - PostgreSQL 可用性检测。
  - DDL 初始化。
  - JSONB 文档读写。
  - parity 统计。
- 所有数据库依赖延迟导入；未安装/未配置 PostgreSQL 时不影响 JSON 模式。

验收：

- Python 编译通过。
- storage 单元检查通过。
- 无 DSN 时返回明确的不可用原因，而不是异常崩溃。

### Phase 3：正式知识库迁移

- `KnowledgeRegistry` 支持从 PostgreSQL 读取/保存 category registry。
- `KnowledgeBaseStore` 支持 PostgreSQL 读写普通知识条目和商品专属知识。
- 文件模式保持现状。
- 新增迁移命令导入现有全局/租户/商品专属知识。

验收：

- JSON 模式现有知识测试全部通过。
- PostgreSQL 模式可用时，导入后 list/get/save/archive 结果与文件模式一致。
- 商品专属知识仍按 `product_id + kind + item_id` 唯一。

### Phase 4：RAG 存储迁移

- `RagService` 支持 PostgreSQL source/chunk/index entry。
- `RagExperienceStore` 支持 PostgreSQL experience。
- 保持现有混合检索打分逻辑不变，只替换数据来源。
- 迁移命令导入现有 RAG 文件数据。

验收：

- RAG layer checks、enterprise eval、boundary checks 通过。
- PostgreSQL 模式下 search/evidence/status 字段与 JSON 模式一致。

### Phase 5：管理台运行数据迁移

- 候选审核、上传索引、审计日志、版本元数据支持 PostgreSQL。
- 版本快照保留“元数据入库 + 文件树快照”的混合方式；正式知识已经入库时，版本元数据记录数据库快照范围。
- 诊断忽略项进入数据库。

验收：

- admin backend checks 通过。
- 上传、AI 学习、候选补充、应用入库、拒绝、诊断忽略、备份/回滚无回归。

### Phase 6：全量测试与实盘自测

- 全量静态检查。
- JSON 模式全量回归。
- 如本机有 PostgreSQL DSN：运行 PostgreSQL 模式迁移、parity、全量回归。
- 文件传输助手实盘自测重点覆盖：
  - 标准结构化回复。
  - RAG 软参考回复。
  - 风险话题转人工。
  - RAG experience 记录与不进入正式知识库。
  - 管理台新增/编辑/候选应用后 runtime 立即可用。

验收：

- 所有相关测试通过。
- 若无 PostgreSQL 服务，则代码和迁移测试通过，并在状态文件明确标注外部环境阻塞项。

## 环境变量

- `WECHAT_STORAGE_BACKEND=json`：默认文件模式。
- `WECHAT_STORAGE_BACKEND=postgres`：启用 PostgreSQL。
- `WECHAT_POSTGRES_DSN`：PostgreSQL 连接串，例如 `postgresql://omniauto:omniauto@127.0.0.1:5432/omniauto`.
- `WECHAT_POSTGRES_SCHEMA=wechat_ai_customer_service`：业务 schema，默认该值。
- `WECHAT_POSTGRES_MIRROR_FILES=0|1`：PostgreSQL 模式下是否同时写回 JSON 文件，默认 `0`。

## 回滚策略

- 代码回滚：切回 `WECHAT_STORAGE_BACKEND=json` 即可恢复文件模式。
- 数据回滚：迁移前不删除原 JSON 文件；数据库导入是 upsert，不破坏文件基线。
- 发布回滚：若 PostgreSQL 模式发现逻辑错误，保留数据库数据，先降级到 JSON 模式，再修复迁移层。
