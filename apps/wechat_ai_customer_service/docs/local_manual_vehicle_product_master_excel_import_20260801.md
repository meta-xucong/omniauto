# 本地手动 V2 车辆库与 Excel 导入方案

本方案引用并遵守：

- `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`
- `apps/wechat_ai_customer_service/docs/customer_service_external_contract_and_optional_plugin_baseline.md`

## 结论

商品库正式主线收束为“本地手动 V2 车辆库”。大风车开放平台字段只作为本地车辆资料的字段结构参考；本方案不再同步任何大风车 API，不配置签名客户端，不拉取远程车辆，不做官方写回，也不把同步状态扩成新主路径。

正式录入路径只有两种：

1. 管理台现有手动 V2 编辑。
2. 本地 Excel 模板预览、校验、人工确认后批量导入。

管理台手动 V2 编辑页与查看页使用同一份大风车 `vehicle_detail` 原始字段矩阵：基础信息、车辆身份、车型参数、价格/手续、车主信息等原始字段均按中文业务标题展示；系统字段、受限字段、对象父节点和未知兼容字段在同一位置只读展示，只有可手填的原始叶子字段进入保存 patch。编辑控件不展示 `baseCarInfo`、`carPriceInfo`、`annotations`、`manual` 等内部路径。普通编辑区只展示原始车辆字段和车辆图片上传；所有不是原始大风车车辆字段的本地扩展内容，包括客户可见补充、回复话术、本地管理字段、内部备注和商品专属知识/话术，统一放在“高级选项（一般不用）”中，默认折叠。

查看页的普通车辆资料区只展示标准业务字段，不再突出“其他大风车字段”或内部字段路径。source payload 中无法归入标准分组的额外兼容字段继续保留在后台结构中；如需给运营查看，只放入默认折叠的“高级选项”并显示为“其他保留信息（系统）”，只展示业务标题和值。

车辆图片属于管理台手动 V2 编辑路径：在车辆详情编辑页使用图片上传入口维护，可一次选择多张图片；第一张作为主图展示，并可在编辑页内上移、下移、设为主图或删除。当前新版 Excel 下载模板不再提供图片网址填写入口。

已有 Dafengche mirror/sync 相关代码若仍被历史测试或兼容调用引用，可以继续作为历史兼容实现存在；本方案不扩张、不恢复、不接入新的定时同步、凭据、远程 API 或 reconciliation 流程。

## 数据合同

Excel 导入生成的记录必须与手动编辑一致，仍写入 `ProductMasterStore` 的 V2 vehicle envelope：

- `schema_version=2`
- `category_id=products`
- `source.type=manual`
- `source.provider=manual`
- `source.marker.ingest_channel=manual_input`
- `source.marker.original_source_type=manual`
- `source.binding.state=unbound`
- `source_payloads.vehicle_detail` 保持 Dafengche-shaped snapshot
- `source_payloads.vehicle_pictures` 保持 Dafengche-shaped snapshot

没有真实上游绑定时，Excel 不能伪造 `shopCode` 或 `carId`。本地身份统一使用 `local_id`，并映射为 record `id`。

车辆名称使用成熟的 Dafengche 嵌套结构：

```json
{
  "baseCarInfo": {
    "name": {
      "displayValue": "丰田 凯美瑞 2.0G",
      "brandName": "丰田",
      "seriesName": "凯美瑞",
      "modelName": "2.0G"
    }
  }
}
```

不得把 `baseCarInfo.name` 新写成与现有 V2 admin/customer evidence 不一致的另一套字符串结构。

Excel 模板现在按“原始车辆字段 + 必要本地身份”的边界生成中文竖向填写表，避免横向几十列和技术字段路径给运营造成负担。`车辆信息` sheet 第 1 行固定为 `车辆编号 * / 填写项 / 填写内容 / 填写说明`；第 2 行起每行一个原始车辆字段。下载模板会把“车辆编号”和“填写内容”留空，一个车辆由同一“车辆编号”下的一组字段行组成；运营按车辆编号填写整组字段行，新车可复制整组字段行后填写新的车辆编号。已下载旧模板中的 `车辆编号` 表头继续可读。

用户可见工作表不展示 `baseCarInfo`、`carPriceInfo`、`annotations`、`manual`、target path 或变量名；也不要求运营填写 `brandCode`、`seriesCode`、`modelCode`、`cityCode`、`provinceCode`、`shopCode/carId` 等上游内部编码。能用中文业务字段表达的内容，只展示“品牌 / 车系 / 车型 / 车辆所在地城市名 / 车辆所在地省份名 / 车辆所在地展示值 / 车辆归属地城市名 / 车辆归属地省份名 / 车辆归属地展示值”等可读字段。程序内部使用稳定的“中文填写项 -> target path”映射，再合并到可由 `apply_admin_vehicle_update()` 处理的 Dafengche-shaped 车辆原始字段位置；旧模板或历史 API 中已经携带的 code 字段仍可兼容读取/保存，但新版下载模板和普通编辑界面不再把这些 code 作为用户填写项。当前下载模板版本为 `local_manual_vehicle_v2_excel_20260802_simple_raw_fields`，只生成原始车辆字段；旧 simple 版本 `local_manual_vehicle_v2_excel_20260801_simple_vertical` 若已包含本地客服扩展行，仍可读取和确认，避免已下载模板突然失效。旧字段路径竖向版本 `local_manual_vehicle_v2_excel_20260801_vertical`、旧横向版本 `local_manual_vehicle_v2_excel_20260801_admin_fields` 和更早版本 `local_manual_vehicle_v2_excel_20260801` 也仍可读取和确认。

新模板的字段来源以 `packages/dafengche_product_master/admin_projection.py` / `contract.py` 中的 vehicle_detail 原始字段矩阵为准，查看页、编辑页和 Excel 下载模板共享这一套字段口径。新模板的关键字段包括：

- `baseCarInfo.name.displayValue/brandName/seriesName/modelName`（品牌/车系/车型 code 不作为新版模板填写项）
- `baseCarInfo.carName`
- `baseCarInfo.vinNumber / area.cityName / area.provinceName / area.displayValue / registerArea.cityName / registerArea.provinceName / registerArea.displayValue / stockStatus / contractSignDate / vehicleCondition / carDetailForDisplay / color / innerColor / productionDate / annualExpiresDate / outStockDate / inStock / reserveTime / payTime / mileage / outStockReason / salesperson / useType / plateNumber / vehicleNumber / purchaseType / video / weidianIsUpshelf / detectReportPdf.*`
- `carOwnerInfo.*`
- `carModelParam.highlightsConfiguration / engineNumber / carBody / gearBoxType / seatNumber / engineVolumeLiter / emissionStandard / fuelType`
- `carLicenseInfo.xiancheshangyexianjine / xiancheshangyexiandaoqiri / jiaoqiangdaoqiri / keysCount / transferTotal`
- `carPriceInfo.salePrice / purchasePrice / newPrice / dealPrice / exhibitionPrice / salesPrice / managerPrice / wholesalePrice / retrofitPrice`
- `operationPhase`

其中 `purchasePrice`、`dealPrice`、`salesPrice`、`managerPrice`、`wholesalePrice` 等属于原始车辆价格字段，可以进入源记录，但仍属于 customer evidence restricted 字段，默认不得进入 Brain/customer-visible evidence。Excel 只维护原始车辆字段；客户可见补充、回复话术、本地管理字段、内部备注和商品专属知识/话术不通过新版 Excel 维护；这些低频本地客服扩展在管理台车辆编辑页“高级选项（一般不用）”中维护。

### 必填规则

只读核对当前本地大风车适配开发文档后，未发现官方接口文档在本仓库中明确声明“品牌、车系、车型”等业务字段必须由本地手动录入强制填写。现阶段采用最小核心必填规则：

- Excel：`车辆编号` 必填，用于本地唯一身份；`车辆展示名称` 必填，用于管理台和客服证据中的车源可识别名称。下载模板在车辆信息表 A1 标为 `车辆编号 *`，字段说明表也单独列出 `车辆编号 / 是`。
- 管理台手动 V2 编辑：现有车辆编号是系统记录身份，编辑页不提供随意修改入口；真正可编辑且必填的是 `车辆展示名称`。品牌、车系、车型、价格、颜色、手续等原始字段均保持可空，留空不覆盖既有手工字段。

字段说明表中的“是否必填”使用“是/否”展示；解析器和前端保存都会执行同一最小规则，不能只依赖视觉星号。

## Excel 流程

当前实现停点：Excel 预览可在所有本地管理台环境中使用；确认写入支持文件存储原子批量写入，也支持 PostgreSQL product-master 存储模式下的私有批量事务写入。PostgreSQL 模式中 DB 是 canonical source，文件镜像只是提交后的可选副本；DB 事务成功后，如果文件镜像中途失败，确认结果必须返回 `mirror_files_failed` warning 和失败镜像 ids，提示需要重建镜像，但不得回滚已提交 DB，也不得把整批确认误报为失败。

现有 `list_items()` 在 PostgreSQL 不可用或未配置时会回退文件存储，这是既有存储合同，本轮不改写。运营判断 PostgreSQL product-master 导入结果时必须以可用 DB 读为准，不能把过期或部分失败的文件镜像当成 DB 成功证据。

当前下载模板包含两个 sheet：

1. `车辆信息`
2. `字段说明`

历史已下载模板若包含 `车辆图片` sheet，仍按兼容路径读取其中的远程图片 URL；新版模板不再生成该 sheet。

`字段说明` 保留一行隐藏的系统模板版本，供预览时精确识别版本；用户可见区域只展示填写说明和字段说明，其中 `车辆编号` 与 `车辆展示名称` 均标记为必填。预览时必须存在该 sheet，且版本精确匹配；缺失或不匹配直接拒绝，不生成可确认的导入预览。

模板排版要求不改变解析合同：`车辆信息` 的第 1 行始终是短表头，不插入标题行、不合并第 1 行。当前下载模板会：

- 冻结首行，关闭网格线。
- 使用深色、白字、加粗、换行表头。
- `车辆信息` 按基础信息、车型参数、价格、手续/状态等原始字段分组使用克制浅色；填写内容与填写说明列保持较宽，中文填写项不截断。
- 对价格、座位数等 `填写内容` 设置可读数字格式。
- 在 `字段说明` 中突出按车辆编号填写整组字段行的方式和字段说明表头；字段说明表只保留 `填写项 / 是否必填 / 填写说明`，不展示内部 target path；再次提示车辆图片请在管理台车辆编辑页上传，可一次选择多张。

预览阶段：

- 只读取本地 `.xlsx`。
- 不调用 LLM。
- 不调用网络。
- 不调用大风车 API。
- 不写商品库 items。
- 输出行级错误，包括缺失必填列、未知列、未知填写项、必填字段缺失、非法车辆编号、图片行引用未知车辆编号、同一 `车辆编号 + 填写项` 重复等。

确认阶段：

- 只接受同租户下的 preview id。
- 必须在写库前完成整批 record 校验。
- 任何预览错误都不能确认写入。
- PostgreSQL 模式必须通过 `ProductMasterStore` 私有批量事务入口一次写入；事务失败时 DB 零新增、零半批污染。
- PostgreSQL DB 事务成功后，文件镜像失败只返回 `mirror_files_failed` warning 和失败镜像 ids；DB 仍为权威结果，镜像需要后续重建。
- 已有车辆编号且为本地手动车辆时按 V2 admin patch 合并，Excel 空白字段不会清空既有手工字段。
- 已有车辆编号但不是本地手动车辆时拒绝，避免 Excel 覆盖历史 Dafengche mirror 或其他来源。
- 写入失败必须回滚已写目标，避免半批污染商品库。

## 客户安全证据链

Excel 导入只维护 ProductMasterStore 的源记录。客户可见回复仍必须走现有 customer-safe evidence projection：

- Brain 只能收到 `customer_evidence` / legacy compatibility projection 中允许的字段。
- 手动 V2 / Excel 导入的 Dafengche-shaped `vehicle_detail` 和 `vehicle_pictures` 不得直接进入 Brain；只能由 `ProductMasterStore.list_customer_evidence_items()` / `get_customer_evidence_item()` 经过既有 allowlist projection 后进入外层证据包。
- `source_payloads`、车主信息、VIN、车牌、内部车辆编号、销售员/负责人、发动机号、采购价、销售底价、经理价、批发价等 restricted/raw 字段默认不得进入 Brain evidence。
- 手动未绑定车辆是租户内本地记录；显式绑定 `shopCode` 的手动/历史镜像车辆必须按 shop scope 过滤，错误店铺或缺少匹配 shop scope 时不得投给 customer evidence。
- 数据层只提供事实和证据，不生成客户可见回复；客户可见回复仍由 `customer_service_brain` 拥有。

## 管理台语义

商品库 UI 使用“本地车辆库 / 本地手动车辆 / Excel 导入”语义。历史“大风车同步”可以作为已有记录的来源筛选或兼容状态存在，但不作为新主线路径扩张。

AI 商品助手不是本轮主路径。若删除会破坏已有公开合同，则保留兼容入口，但 Excel 导入不接入 AI 商品助手。

## 测试矩阵

必须覆盖：

- 模板生成可被读取，当前下载模板包含 `车辆信息` / `字段说明` 两个 sheet 和精确模板版本，不包含图片 URL 填写列。
- 当前下载模板是中文竖向 `车辆信息`：第 1 行为 `车辆编号 * / 填写项 / 填写内容 / 填写说明`，同时兼容旧版 `车辆编号` 表头；用户可见工作表不得出现 target path、`baseCarInfo`、`carPriceInfo`、`annotations`、`manual` 等技术内容；复制整组字段行并修改车辆编号可录入多车。
- 有效 Excel 预览不写库，确认后写入 manual V2 记录。
- 车辆名称落成 `baseCarInfo.name.displayValue/brandName/seriesName/modelName` 嵌套结构。
- 新模板字段与 V2 管理台原始字段矩阵对齐：查看页、编辑页与 Excel 共同覆盖 `vehicle_detail` 标准字段矩阵；系统/受限/对象父节点在页面只读展示，Excel 只生成可手填的原始叶子字段。
- 旧字段路径竖向模板和旧横向模板版本仍可读取并按旧列集合确认导入。
- 当前新版 workbook 不含 `车辆图片` sheet、`图片地址` 或 `大图地址`；旧 URL 图片模板仍可读取并导入远程 URL。
- 前端车辆编辑页必须提供真实多图上传入口：`file` input 支持 multiple，一次选择多张后逐张预览/上传，支持主图、上移/下移排序和删除。
- 前端车辆编辑页必须覆盖新版 Excel 的全部中文填写项；编辑控件只显示业务标题，不展示内部 target path；高级选项默认折叠并可手动展开。
- 普通车辆查看页不得出现“其他大风车字段”、内部字段路径或原始载荷 JSON；兼容保留字段如需查看，只能在默认折叠的高级区以“其他保留信息（系统）”展示业务标题和值。
- 缺失字段、未知列、损坏文件、过大文件、模板版本错误均返回可解释错误。
- 同一 `车辆编号 + 填写项` 重复报错；同一车辆编号下多行字段是竖向模板的正常车辆分组。
- 重复导入同一有效 Excel 幂等更新；空白字段不覆盖既有手工字段。
- 旧 URL 图片模板的图片行按 `local_id` 归属并落入 `vehicle_pictures`；新版模板不再用 Excel 维护图片。
- 确认前预览不污染商品库；确认中失败不产生半批写入。
- 租户隔离：A 租户 preview id 不能由 B 租户确认。
- 租户/店铺隔离：A 租户商品证据不得被 B 租户读取；显式 shop-bound 手动 V2 记录只对匹配 shop scope 出现在 customer evidence。
- PostgreSQL 模式确认导入使用批量 DB 事务；事务失败时零新增，事务成功但文件镜像失败时返回 warning、DB 全批仍可读。
- 同一批次内重复 item id 在写入前拒绝，不能以后写覆盖。
- 静态禁止网络/LLM/大风车 API 调用。
- Brain/customer evidence 不泄漏 raw `source_payloads`，也不泄漏 VIN、车牌、内部身份、进价/底价/批发价等受限字段。
