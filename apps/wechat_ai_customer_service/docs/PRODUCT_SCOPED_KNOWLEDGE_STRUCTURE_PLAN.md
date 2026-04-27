# 商品专属知识结构优化方案

## 背景

当前知识库已经按大门类物理隔离：

- `products/items/*.json`：商品主档。
- `policies/items/*.json`：通用政策规则。
- `chats/items/*.json`：客服话术风格。
- `erp_exports/items/*.json`：后台导出数据。

这能解决“商品、政策、话术不要混在一起”的问题，但还没有解决“某条规则只适用于某个商品”的问题。

例如：

- 某个商品的安装注意事项。
- 某个商品的特殊物流限制。
- 某个商品的禁用承诺。
- 某个商品的专属问答。
- 某个商品的材质、场景、售后解释补充。

这些内容如果都放进通用 `policies`，会污染全局规则；如果都塞进商品主档 `additional_details`，商品文件会越来越大，也不方便审核、回滚和按来源追踪。

## 结论

有必要做结构优化。推荐采用“商品主档 + 商品专属知识文件夹 + 通用知识库”的三层结构。

## 推荐目录

```text
data/knowledge_bases/products/
  items/
    commercial_fridge_bx_200.json
    water_filter_core.json
  item_knowledge/
    commercial_fridge_bx_200/
      faq/
        shipping_to_upper_floor.json
        compressor_warranty.json
      rules/
        discount_boundary.json
        installation_handoff.json
      explanations/
        use_scene_convenience_store.json
        material_and_power.json
    water_filter_core/
      faq/
      rules/
      explanations/
```

## 数据分工

商品主档只存稳定核心信息：

- 商品名称、SKU、别名。
- 类目、规格、基础价格、阶梯价。
- 库存、基础发货、基础售后。
- 商品级默认回复模板。

商品专属知识文件夹存针对该商品的细节：

- `faq`：只对该商品生效的问答。
- `rules`：只对该商品生效的风险规则、转人工规则、优惠边界。
- `explanations`：只对该商品生效的解释资料、使用场景、参数补充。

通用政策库继续存跨商品规则：

- 开票。
- 公司信息。
- 通用付款规则。
- 通用物流规则。
- 通用售后规则。
- 通用合同、账期、人工边界。

## 运行时加载规则

客服处理一条消息时，应按范围加载知识：

1. 先判断是否命中某个商品。
2. 命中商品后加载商品主档。
3. 再按意图加载该商品文件夹下相关 `faq/rules/explanations`。
4. 同时只加载必要的通用政策，不全量加载所有知识。

这能减少上下文浪费，也能避免某商品的特殊规则影响其他商品。

## 管理台交互建议

商品详情页应新增二级区域：

- 商品主档。
- 专属问答。
- 专属规则。
- 专属解释资料。

专属知识可以单独新增、编辑、删除、审核和回滚。

候选审核入库时，如果 AI 判断内容是“某商品专用”，应提示：

- 归属商品。
- 专属知识类型。
- 是否缺少商品指向。
- 是否应转为通用政策。

如果资料里提到商品名但匹配不确定，应暂存候选并提示用户选择归属商品。

## 改造章节

### Chapter 1：底层结构

- 新增 `products/item_knowledge/<product_id>/` 目录规范。
- 定义商品专属 `faq/rules/explanations` 三类 schema。
- 保持现有 `products/items/*.json` 不迁移，降低风险。

### Chapter 2：运行时加载

- 商品命中后加载对应 `item_knowledge/<product_id>/`。
- 证据包里区分 `product_core` 和 `product_scoped_knowledge`。
- LLM 提示中明确商品专属知识优先级高于通用政策。

### Chapter 3：候选生成与审核

- 上传资料和知识生成器识别“商品专属知识”。
- 候选审核中显示归属商品。
- 商品不明确时标记 `needs_more_info`，要求用户选择商品后再入库。

### Chapter 4：管理台

- 商品详情页展示专属知识列表。
- 支持新增、编辑、删除商品专属知识。
- 支持把专属知识转为通用政策，或把通用政策转挂到某商品。

### Chapter 5：迁移与验证

- 将现有商品主档里明显属于单商品的长说明迁移到专属文件夹。
- 回测报价、物流、售后、议价、转人工边界。
- 确保通用政策不被商品专属规则污染。

## 本次先不直接迁移的原因

这不是单纯新增字段，而是会影响：

- 知识生成器分类。
- 上传候选应用位置。
- 管理台编辑页面。
- 运行时证据加载。
- DeepSeek 上下文组织。
- 备份、回滚、检测和修复逻辑。

因此应作为一个独立小阶段改造，而不是夹在候选按钮 bug 修复里一次性改完。
