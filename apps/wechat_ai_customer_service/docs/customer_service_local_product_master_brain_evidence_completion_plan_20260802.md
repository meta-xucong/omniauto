# 本地商品库到 Brain 证据闭环开发方案（2026-08-02）

## 1. 文档目的

本方案针对当前本地手工商品库，补齐“商品资料可被 customer_service_brain 稳定调用”的最后一段证据链。

本方案必须同时遵守：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)
- [dafengche_product_master_mirror_migration_design_20260713.md](dafengche_product_master_mirror_migration_design_20260713.md)

本阶段只处理商品主数据投影、客户安全证据和对应测试。不要改 Vision、Voice、RPA、session monitor、scheduler、Workflow、Brain 回复逻辑或商品管理台/Excel 入口。

## 2. 当前基线

当前数据源是本地手工 V2 商品记录，内部仍使用 Dafengche 形状的 `source_payloads`，不调用大风车 API。

已有链路：

```text
本地 V2 商品记录
  -> ProductMasterStore
  -> packages/dafengche_product_master/projection.py
  -> KnowledgeRuntime.list_customer_evidence_items()
  -> reply_evidence_builder
  -> knowledge.product_master.items
  -> customer_service_brain 的既有 Brain input
```

当前已经具备：

- 商品名称、别名、品牌/车系/车型；
- 公开售价、首次上牌时间、里程；
- 结构化城市回退，例如 `provinceName + cityName`；
- 可读库存状态和业务阶段；
- 多会话/租户隔离；
- VIN、车牌、采购价、销售底价、经理底价、批发价、店铺编码、车源编码、原始 payload 等不进入客户证据；
- Brain 仍是唯一客户可见回复作者。

当前不能宣称“所有客户可用商品资料已完整进入 Brain”，原因是部分已授权字段仍只在 raw payload 中，或没有进入 Brain 现有 prompt compact 路径。

迁移审计中标记为 `filled_test_value` 的字段只是回归填充值，不是客户事实。它们不能授权 Brain 断言“在售”“有库存”或其他当前业务状态；真实验收必须使用人工确认的本地值，或让投影输出“待核实”。

## 3. 目标与完成定义

### 3.1 目标

在不改变 Brain 外部合同的前提下，确保所有被字段策略标记为 `customer_visible_by_default` 的车辆事实，均能通过同一个 customer-safe projection 进入 Brain：

- 有专用结构化字段的，保留现有字段名和类型；
- 没有专用字段但适合自然语言理解的，进入现有 `specs` 摘要；
- 空值不伪造、不补猜；
- 机器编码转成可读语义，未知编码只能转为“待核实”，不得把内部编码原样交给 Brain；
- 受限字段即使存在于 raw payload，也不得进入 evidence、Brain input 或 prompt。

### 3.2 完成定义

以下条件全部满足，才算本阶段完成：

1. `chejin` 手工商品经 `ProductMasterStore -> KnowledgeRuntime -> reply_evidence_builder -> build_brain_input` 能读到全部已授权客户字段。
2. Brain 不需要解析 Dafengche raw 字段，不需要读取本地文件路径，也不需要依赖管理台或 RPA。
3. 普通商品问价、库存、城市、配置、车况描述等问题都能从 `content_basis.product_master` 获得对应证据；无证据时 Brain 必须遵守现有不能确认规则。
4. `default` 或其他租户不能读到 `chejin` 商品。
5. 现有外部 payload、函数签名、Brain input 外层形状、回复所有权不变。
6. 受限字段、raw payload、内部来源标记和内部编码均不泄漏。
7. `filled_test_value` 等未被后续人工确认的迁移/测试字段不会被伪装成实时商品事实；记录整体带有 `legacy_v1_migration` 标记本身，不等于每个字段永久失效，必须按字段级 provenance 判断。

## 4. 字段投影规则

### 4.1 已有结构化字段继续使用

以下字段直接沿用现有 customer evidence/Brain item 字段：

| 事实 | Brain 可用字段 |
| --- | --- |
| 车辆展示名称 | `name` |
| 品牌/车型 | `brand`、`model`、`aliases` |
| 首次上牌 | `year` |
| 表显里程 | `mileage` |
| 车身颜色 | `color` |
| 变速箱 | `transmission` |
| 车辆所在地 | `location` |
| 网络标价 | `price` |
| 库存语义 | `stock` |
| 业务阶段语义 | `availability` |
| 权威来源 | `authority_level=product_master` |

### 4.2 进入现有 `specs` 的客户字段

为避免新增 Brain 公共字段，以下已授权字段统一以稳定的“标签:值”形式追加到 `specs`，由现有 Brain compact 路径原样保留：

- 对外车辆描述；
- 内饰颜色；
- 出厂日期；
- 使用性质；
- 亮点配置；
- 车身结构；
- 变速箱类型、排量、座位数、排放标准、燃料形式；
- 钥匙数量、过户次数；
- 明确被字段策略允许的微店上架状态和上架时间。

`specs` 只允许来自 customer-safe projection 的值，不得拼接整个 `source_payloads`，不得把 raw JSON 转成字符串塞进去。

如果某字段没有值，则完全省略该标签。不要用“未知”“暂无”覆盖真实空值，除非现有业务合同已明确要求该显示语义。

### 4.3 状态和编码

状态映射只存在于 `packages/dafengche_product_master` 中：

- 已知 `stockStatus` 映射为 `在库`、`无库存`、`已预订`、`已售`、`已归档`等可读语义；
- 已知 `operationPhase` 映射为 `在售`、`整备中`、`待上架`、`已预订`、`已下架`等可读语义；
- 未知机器值统一为 `待核实`，不得把 `TEST_SALE`、数字码等内部值交给 Brain；
- 明确标记为测试/迁移填充值且没有后续人工确认的状态，即使文本看起来像 `SALE`，也只能进入内部审计；客户证据中输出 `待核实` 或不输出；后续可审计的 `manual_admin_edit` 才能替代该测试值。
- raw code 仍可留在内部源记录和审计中，但不能出现在 customer evidence、Brain input、prompt 或客户回复。

### 4.4 不进入 Brain 的字段

默认禁止：

- VIN、车牌、发动机号；
- 采购价、销售底价、经理底价、批发价、成交价；
- shopCode、carId、orgId、owner、creator、销售员等内部身份/绑定字段；
- 车主姓名、电话、身份证、银行账户等个人信息；
- 原始 `source_payloads`、同步批次、内部 marker、文件名、assetFile、本地绝对路径；
- 未被策略明确授权的保险、检测内部资料、采购照片和内部备注。

## 5. 图片边界

本阶段“商品资料可被 Brain 调用”首先指结构化车辆事实可调用，不等于 Brain 自动读取本地图片文件。

当前本地上传图片使用应用内部路径或相对管理台路由。不得把以下内容交给 Brain：

- `D:\...` 等本地绝对路径；
- `assetFile`、内部磁盘布局；
- 未授权的原始图片对象。

若后续要求 Brain 基于商品照片进行判断，另开一个独立的商品媒体证据切片：只允许受控、可访问、带租户权限的媒体引用或图片摘要；必须补充媒体访问、过期、租户隔离和不可达处理测试。不得把该需求混入本阶段的文本字段投影，也不得调用客户聊天 Vision 模块代替商品媒体证据。

## 6. 允许修改的边界

### 6.1 允许修改

- `packages/dafengche_product_master/projection.py`：字段读取、可读状态映射、`specs` 汇总；
- 同包中必要的纯字段策略/投影辅助函数；
- `apps/wechat_ai_customer_service/tests/run_dafengche_product_master_checks.py` 及必要的商品证据测试；
- 商品主数据相关文档。

### 6.2 禁止修改

- `customer_service_brain.py` 的回复策略、提示词、BrainPlan 或客户话术；如果现有 prompt compact 硬截断已授权商品字段，可只做保持外层合同不变的字段保真修复，不得改变回复策略；
- `reply_evidence_builder.py` 的外部合同，除非发现当前 projection 无法通过既有入口传递，且只能做兼容性修复；
- `listen_and_reply.py`、scheduler、session monitor、RPA、Vision、Voice；
- public CLI/HTTP/message/Brain 字段；
- 商品管理台和 Excel 导入逻辑；
- 大风车 API 同步、写回或实时网络调用。

## 7. 测试要求

### 7.1 纯投影测试

使用一条包含全部 customer-visible fixture 字段的 V2 手工记录，逐项断言：

- 每个允许字段出现在专用 evidence 字段或 `specs`；
- 空字段不产生伪值；
- location 优先 `displayValue`，缺失时回退省/市名称；
- 状态已转成可读语义，未知码为“待核实”；
- 同一字段不会重复拼接多次。

### 7.2 Brain 输入测试

经真实现有链路构建 Brain input，断言：

- `content_basis.product_master.items` 包含目标商品；
- `authority_level` 仍为 `product_master`；
- `name/price/year/mileage/location/stock/availability/specs` 均可见；
- `specs` 中包含已授权的配置、描述、使用性质、日期等字段；
- 最终 prompt compact 后仍保留全部必需字段标签；正常长度的结构化值完整保留，超长单值或自由描述可按既有预算摘要，但不能因截断丢掉结构化字段标签；
- 不包含 raw payload、路径、受限字段和原始机器编码。

### 7.3 租户与上下文

- `tenant_context("chejin")` 能命中 chejin 商品；
- `default` 和其他租户不能命中；
- `last_product_id` follow-up 仍能命中同一商品；
- 不涉及商品的问题不会强行注入商品 evidence；
- 空商品库、过期商品和未授权字段保持既有阻断/不能确认语义。
- 未被人工确认的测试填充值和迁移快照不能被当作当前库存或在售证据；字段级人工确认后按其最新值和时间进入既有新鲜度策略。

### 7.4 回归门禁

至少通过：

- `run_dafengche_product_master_checks.py`；
- `run_product_console_v2_checks.py`；
- `run_product_master_excel_import_checks.py`；
- `run_customer_service_brain_preflight_checks.py`；
- 相关 Python `py_compile`；
- scoped `git diff --check`；
- 核心包禁止依赖 `apps.wechat_ai_customer_service` 的边界检查。

## 8. 验收顺序

1. 先完成文档要求的 projection 与纯测试。
2. 运行完整本地门禁，确认仅有商品主数据相关改动。
3. 在 `tenant=chejin` 的受控运行环境做一次只读证据回放，确认实际 `KnowledgeRuntime.tenant_id` 为 `chejin`。
4. 再进行最小真实客服问答验收：名称、价格、城市、库存、配置和上下文追问各一条；只观察 Brain evidence 和审计，不允许用本地话术替代 Brain。
5. 通过后只提交 product projection、商品测试和本文档；排除 Vision、Voice、scheduler、generated data、learning packs 和临时文件，再由负责人决定 push/merge。

## 9. 审计结论

本方案是对当前实现的收口，不恢复此前大风车 API 同步，也不扩大到 Brain 或 RPA 架构改造。

只有在“字段完整可投影、Brain 输入可见、受限字段不泄漏、租户隔离通过、现有合同测试通过”之后，才能宣称本地商品库已经可以被 Brain 正常调用并进入提交/推送/合并流程。
