> [!WARNING]
> **文档状态：仅保留为历史技术参考（2026-07-18）。** Provider、模型配置和多模态调用经验仍可参考，但本文不再授权任何模块落点或生产数据流；实现必须服从 [完全独立图像识别模块改造方案](../customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)。

> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# AlchemyOS 豆包识图参考审计

本审计基于以下参考位置：

- `D:\AI\AlchemyOS\custom_media_agent_2_0\docs\claude_code_source_fallback.md`
- `D:\AI\AlchemyOS\custom_media_agent_2_0\app\services\claude_orchestrator.py`
- `D:\AI\AlchemyOS\custom_media_agent_2_0\app\services\uploaded_asset_vision.py`
- `D:\AI\AlchemyOS\custom_media_agent_docs\custom_media_agent_2_0\app\providers\images\doubao_image.py`
- `D:\AI\AlchemyOS\custom_media_agent_docs\tests\test_provider_contract.py`

## 1. 已确认的可复用经验

### 1.1 文本模型和多模态模型分路

`AlchemyOS` 的关键经验不是“所有事情都交给一个大模型”，而是显式区分：

- 文本主脑模型
- 多模态理解模型
- fallback 模型

这个思路对微信客服非常适合，因为：

- Brain 仍负责理解、策略和客户可见回复。
- 识图模块只负责视觉证据。
- 两条链路可以分别优化延迟和成本。

### 1.2 独立配置、独立 key、独立 timeout

`AlchemyOS` 对豆包相关能力采用独立模型和独立 key 管理，这一点非常值得复用。

适用于微信客服的直接结论：

- 识图模块不要复用 `customer_service_brain` 的模型配置。
- 识图模块必须有单独的 `api_key/base_url/model/request_style/timeout`。

### 1.3 明确记录 `source_reason`

`AlchemyOS` 在多模态分路时记录了为什么走多模态，例如：

- `provider_input_images_required`
- `hard_reference_input_image`
- `prompt_requests_uploaded_image_understanding`

这对微信客服也很有价值。建议识图模块记录：

- `image_only_turn`
- `image_plus_text_turn`
- `vehicle_catalog_question`
- `visual_followup_resolution`

### 1.4 本地轻量视觉预分析值得复用

`uploaded_asset_vision.py` 展示了一个很稳的低成本预分析模式：

- 先读本地图像
- 做尺寸、方向、主色、亮度、对比度摘要
- 把这些摘要作为辅助视觉信号

这部分不能替代语义识图，但很适合做：

- 文件有效性检查
- 下采样和压缩前校验
- 轻量审计摘要
- 识图失败时的资产诊断

### 1.5 provider 契约测试非常值得照搬

`test_provider_contract.py` 证明了一个重要工程原则：

- 豆包相关 provider 要验证“专用 key、专用 base_url、专用 model”是否真的生效。

微信客服落地时也应补同类测试，防止：

- 误复用 Brain key
- 误走错模型
- 误发到旧网关

## 2. 不应直接照搬的部分

### 2.1 生图 provider 代码本身

`doubao_image.py` 是图片生成/编辑 provider，不是客服识图 adapter。

能借鉴的是：

- 独立 provider 封装方式
- 独立 key/base_url/model 管理
- HTTP 错误处理
- 响应规范化测试

不能直接拿来做客服识图的原因：

- 请求目标不同
- 输出结构不同
- 客服识图需要结构化车辆识别和意图判断，不是返回图像 bytes

### 2.2 AlchemyOS 的创意编排上下文

`claude_orchestrator.py` 服务的是生图编排，不是会话型客服。

它的“多模态分路、source reason、compact JSON only”值得参考，但：

- 不适合直接套用到微信客服 Prompt
- 不适合直接复用其资产 role/fusion 语义

### 2.3 Logo、海报、菜单等内容策略

AlchemyOS 的很多多模态判断围绕：

- logo
- 海报
- 文案
- 二维码
- 素材融合

微信客服这边的主目标是：

- 识别是否是车
- 识别可能车型
- 结合用户文字做商品库匹配或相似推荐

所以只能借“结构化视觉结果”的思路，不能直接搬业务标签。

## 3. 对微信客服最有价值的复用点

### 3.1 复用“分路原则”

建议在微信客服中固定：

- 文本回复主脑：`customer_service_brain`
- 视觉理解专线：`customer_image_understanding`

### 3.2 复用“独立 provider 配置”

建议新增：

- `CUSTOMER_IMAGE_UNDERSTANDING_API_KEY`
- `CUSTOMER_IMAGE_UNDERSTANDING_BASE_URL`
- `CUSTOMER_IMAGE_UNDERSTANDING_MODEL`
- `CUSTOMER_IMAGE_UNDERSTANDING_REQUEST_STYLE`

默认值可以参考 `AlchemyOS` 的当前多模态路由意图：

- `base_url=https://aiself.vip/v1`
- `model=doubao-seed-2-0-lite-260428`

但真正落代码时必须以当前可用网关能力为准，不要仅凭旧文档硬编码。

### 3.3 复用“紧凑 JSON 输出”

识图模块应要求 provider 输出紧凑 JSON，而不是长篇描述。

这样有两个好处：

- 更快
- 更便于桥接到商品库和 Brain

### 3.4 复用“本地预分析 + 模型识图”双层结构

推荐顺序：

1. 本地图片资产校验和轻量分析
2. 多模态模型做语义识别
3. 结构化桥接到商品检索和 Brain

## 4. 本次审计的诚实结论

我没有在 `AlchemyOS` 中找到一个“现成可直接复制粘贴到微信客服的 standalone 客服识图模块”。

我确认找到的，是这些可直接借鉴的成熟经验：

- 多模态和文本模型分路
- 独立 key/base_url/model 管理
- source reason 审计
- 本地轻量视觉画像
- provider contract 测试方法

因此，最合理的落地方式不是“直接拷贝 AlchemyOS 某个完整识图文件”，而是：

- 复用它的工程边界和配置纪律
- 参考它的豆包接法和测试方法
- 沿用微信客服里已有的 `customer_image_understanding` 适配层，并只补微信图片保存入口与 `saved_image_path` 输入优先级

## 5. 对实现阶段的建议

优先级最高的复用项：

- 配置隔离
- timeout 隔离
- 审计字段 `source_reason`
- provider 契约测试

优先级较低的复用项：

- 本地颜色/亮度/方向摘要
- 附件资产的轻量视觉 profile

不建议直接复用：

- 生图 provider 输出结构
- 创意编排 prompt
- logo/海报/文案融合规则
