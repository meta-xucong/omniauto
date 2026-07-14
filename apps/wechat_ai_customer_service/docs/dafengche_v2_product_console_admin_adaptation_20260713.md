# 大风车 V2 商品库管理端适配设计与验收

**状态：** 已实施；本文件是商品库 V1→V2 后管理端展示与编辑收口的开发依据。

**关联基线：**

- [客户可见回复归属基线](customer_visible_reply_ownership_baseline.md)
- [外部合同与可选插件基线](customer_service_external_contract_and_optional_plugin_baseline.md)
- [大风车优先商品主数据镜像改造设计](dafengche_product_master_mirror_migration_design_20260713.md)
- 根目录 `AGENTS.md` 的 `Dafengche Product Master Mirror Baseline (Required)`。

## 1. 问题与结论

V1 商品目录按 `item.data.name`、`item.data.price`、`item.data.inventory` 渲染和保存。V2 车辆的权威字段已经迁到：

- `source_payloads.vehicle_detail.payload`：大风车字段原样保存；
- `source_payloads.vehicle_pictures.payload`：图片原样保存；
- `extensions.wechat_customer_service`：本地客服注释、经营补充和人工覆盖；
- `source.marker`、`source.binding`、`metadata`：来源、同步和审计信息。

因此，继续把 V1 `data` 当作管理端的读写来源，会造成页面空白、统计失真，以及“后台显示已改、Brain 仍读取旧权威字段”的事实冲突。V1 `data` 只能作为短期、内存态的兼容投影，绝不再落盘或作为 V2 回退源。

## 2. 范围与边界

本次改动只覆盖商品库管理模块：

```text
packages/dafengche_product_master/admin_projection.py
        ↓
ProductConsoleService / product-console API
        ↓
admin_backend/static/index.html + app.js + styles.css
```

不修改以下运行方式：

- `reply_evidence_builder` 仍只通过客户证据门面获取已授权字段；
- `customer_service_brain` 不读取 V2 原始载荷，也不理解大风车字段路径；
- 调度器、守卫、ReplyEnvelope、WeChat RPA 不导入商品库核心，也不改变发送流程；
- 已有 `/api/product-console/catalog`、详情、库存命令与通用兼容输出保持可用；本次仅新增可选 `admin_view`、`vehicle_counts` 和 V2 专用写入路由。

## 3. 管理端读模型

`build_admin_vehicle_view(record, include_raw=False)` 是唯一的 V2 展示投影。它返回：

- `summary`：名称、公开售价、类目、上架状态、业务阶段、图片数量；
- `vehicle`：原字段名不变的 `operationPhase`、`baseCarInfo`、`carModelParam`、`carPriceInfo` 与图片 URL；
- `source`：来源类型、录入标记、绑定状态、店铺/车辆标识、同步观察时间与来源标签；
- `annotations` / `manual_annotations`：本地客服与经营补充；
- `capabilities`：当前来源是否允许编辑车辆事实；
- `raw_source_payloads`：仅详情路由按管理员用途返回，默认折叠显示，绝不进入 Brain 证据。

列表只使用摘要和授权的常用字段；详情展示车辆信息、来源/绑定/观察时间、客服注释、图片和专属知识。原始载荷保留完整性，但不会被复制成第二套业务字段。

## 4. 写入语义

新增 `PUT /api/product-console/products/{product_id}/admin-view`，输入为：

```json
{
  "vehicle_detail_patch": {
    "operationPhase": "<大风车原字段>",
    "baseCarInfo": {"name": "<大风车原字段>"},
    "carModelParam": {},
    "carPriceInfo": {"salePrice": 0}
  },
  "annotations": {},
  "manual_annotations": {}
}
```

规则如下：

| 车源 | `vehicle_detail_patch` | 本地注释 | 结果 |
| --- | --- | --- | --- |
| `source.type=manual` | 允许按原大风车字段路径深度合并 | 允许 | 更新 V2 原始形状，重算快照哈希并写字段来源审计 |
| `source.type=dafengche` | 拒绝 | 允许 | 官方事实保持只读，等待只读同步任务更新 |
| 非 V2 记录 | 拒绝该专用接口 | 不在本接口处理 | 继续由既有兼容路径处理 |

每次手动车辆字段修改会保留未知原字段，更新 `content_hash`、`metadata.manual_last_edited_at`，并在 `extensions.manual.field_provenance` 记录 `manual_admin_edit`。不会写入或重新启用 `data`。

旧的自然语言商品命令和库存接口仍保留。对 V2 车辆，它们由服务层转换为同一 V2 字段/注释写入，避免外部旧入口把 `data` 重新落盘。大风车同步车源尝试通过旧命令修改官方名称或售价会被明确拒绝，而不是伪造本地“已同步”。

新增手动车源（包括 AI 对话录入、旧表单/API 兼容输入）在 `ProductMasterStore` 写入边界自动转换为 `source.type=manual` 的 V2 车辆；它们不会成为 V1 商品记录。为审计和冻结调用方保留的旧输入快照只存在于 `extensions.compatibility.legacy_v1_record`，不会被商品库运行时读取、不会作为回退源，也不会让顶层 `data` 重新出现。

## 5. 页面行为

商品库页面提供：

1. 车源级统计：在售、大风车同步、手动/迁入、归档；不再把二手车简单等同于普通商品库存。
2. 搜索及来源筛选：车名、品牌、车型、注释；大风车同步、手动录入、历史迁入。
3. 列表卡：严格使用大风车的 `baseCarInfo.name`、`carPriceInfo.salePrice` 和固定标准字段集。每个字段始终展示中文标签与原字段路径；未拉取到的值保持空白，不做回退、猜测、单位换算或“待补充”占位。图片位始终保留，空载荷即为空白图片位。
4. 详情：按固定顺序完整展示大风车 `vehicle_detail.payload` 的标准字段组（车源识别、基础车辆信息、车型参数、价格信息、手续信息），并动态列出未预设的其他大风车字段。图片区域始终展示；本地客服注释、来源/绑定/观察、话术、专属知识、RAG/运营信息和原始 JSON 均收进默认折叠的“高级”栏目。
5. 编辑：手动车源可以编辑大风车形状字段；同步车源的官方字段只读，只能补充本地信息。
6. 管理员审计：详情中折叠显示原始载荷。该区域不是客服证据，也不面向客户。

## 6. 安全与合同审计

- `source_payloads` 的 VIN、车牌、内部价格等字段即使对管理员审计可见，也不得进入 `project_customer_evidence`、Brain、日志中的客户消息或 RPA。
- `display`、`data`、`counts` 等历史输出不删除。V2 情况下 `data` 是输出时生成的安全兼容视图，不是数据库中的商品事实。
- `admin_view`、`vehicle_counts` 和 V2 写入路由均为新增、可选合同；忽略它们的旧调用方继续工作。
- 同步按钮不在本次伪造。当前未配置生产同步调度时，页面只展示来源/观察状态，不会声称已经访问大风车。

## 7. 验收矩阵

1. 历史迁入的 chejin V2 车源显示真实车名和售价，不显示内部 ID/空价格。
2. 大风车 V2 车源显示绑定、同步标签、业务阶段、图片和原始载荷审计。
3. 手动车辆编辑后，名称和公开售价更新到 `source_payloads.vehicle_detail.payload`，而非 `data`。
4. 同步车源的官方字段编辑被 API 拒绝；本地注释仍能保存。
5. 旧商品命令仍能按 V2 派生名称匹配手动车辆，且不把 V1 `data` 写回记录。
6. V2 详情没有库存加减控件；归档/恢复仍保持既有接口合同。
7. 新增的 AI/表单手动车源写入后是 `schema_version=2`、`source.type=manual`，顶层不存在 `data`。
8. 商品主库、管理端、Brain/RPA 边界、静态依赖审计和前端语法检查全部通过。

## 8. 历史车源的二次字段整理

历史迁入不是把 V1 `data` 重新启用，而是一次受审计的、缺失字段补齐操作。脚本 `scripts/enrich_chejin_v2_from_legacy_snapshot.py` 只读取每台车保存在 `extensions.compatibility.legacy_v1_record.data` 中的原始快照，默认只输出计划；显式传入 `--apply` 才写入 V2。

允许写入的字段及证据标准如下：

| V2 大风车路径 | 旧字段证据 | 写入规则 |
| --- | --- | --- |
| `baseCarInfo.firstLicensePlateDate` | `data.specs` 中的“YYYY年M月上牌”或“YYYY年上牌” | 分别保存为 `YYYY-MM` 或 `YYYY`，不补造月份 |
| `baseCarInfo.mileage` | `data.specs` 中的“表显X万公里” | 保存为数值 `X`，与大风车示例的万公里数值口径一致 |
| `carModelParam.displacement` | `data.specs`，仅在缺失时回退 `data.name` 中的 `X.XT/L` | 保留明确排量字符串 |
| `carModelParam.gearbox` | 优先 `data.name` 的 `CVT` / `DSG` / `双离合`，再取 `data.specs` 的“自动挡” | 只使用明示变速箱，不从驱动形式推断 |
| `baseCarInfo.exteriorColor` | `data.specs` 中的“XX车漆” | 保留原文颜色名，例如“白色”“魂动红” |

品牌、车系、车型、车况、内饰颜色、车架号、车牌、店铺/车源绑定、业务阶段和图片均不从旧标题或营销描述猜测。每个成功写入字段都在 `extensions.manual.field_provenance` 中记录 `legacy_v1_snapshot_enrichment`、原字段路径、原文证据和时间；已有 V2 值绝不覆盖。脚本完成后再次执行应显示零项计划更新，作为幂等性验收。

历史迁入曾留下的空顶层 `data: {}` 也由同一脚本清除。`ProductMasterStore` 的 V2 写入边界会永久剔除该退役字段；需要旧形状的调用方仍只能获得输出时生成的兼容投影，不能把它再次保存为商品事实。

## 9. V2 编辑与客服识别测试

“编辑车辆资料”按 V2 原字段分组展示并写入 `source_payloads.vehicle_detail.payload`：基础车辆信息、车型参数、价格/手续，以及原始图片载荷。手动车源可上传 JPEG、PNG、WebP；图片保存在当前租户商品库的资产目录，并以受管理员鉴权的 URL 写入 `source_payloads.vehicle_pictures.payload`。同步车源的官方字段和图片仍由大风车同步任务独占写入。

为验证微信客服的 V2 证据读取，可使用 `scripts/fill_chejin_v2_vehicle_test_fields.py --apply`。它只补空字段，写入值带明显“测试”前缀（或以字段来源记录标识为测试），每个字段都在 `extensions.manual.field_provenance` 中标记 `test_fixture_fill`。测试结束后运行同一脚本的 `--remove --apply`，只会删除该脚本写入的值，不会触碰迁入或大风车字段。
