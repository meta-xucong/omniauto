> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# Brain Preflight 轻量外挂增强设计

## 1. 背景

2026-07-06 实盘复盘发现，微信图片保存和识图链路已经可以把车型识别结果传到 `visual_bridge_input`，但客户问“这个有吗 / 型号发我”这类短句时，`customer_service_brain` 可能命中 `low_authority_fast`，从而构造空商品证据包。

结果是：

- 识图模块已经识别到车型。
- `customer_image_catalog_assist` 也能给出候选商品。
- Brain 输入里只有视觉辅助线索，没有 `product_master` 权威证据。
- Brain 遵守事实边界，只能说“让同事确认”，不能正面回复库存、价格、型号。

这不是识图 provider 失败，也不是 Brain 不会说话，而是“Brain 正式思考前缺少一轮轻量意图/证据需求判断”。

## 2. 层级定位

`Brain Preflight` 不新增架构层级，归类为 `customer_service_brain` 的可插拔轻量外挂增强。

它的职责是：

- 在 Brain 正式构造 evidence pack 前，用轻量 LLM 判断当前 turn 是否需要权威证据。
- 把视觉结果、客户文字和近期视觉上下文归一成内部检索意图。
- 当普通文字疑似商品问题但 `product_master` 证据为空时，作为轻量 evidence-gap 修复器归一查询词。
- 给证据构造层提供查询词和低权威快速路径控制信号。
- 把判断结果作为审计字段和 Brain advisory 输入。

它明确不是：

- 不是第二个客服 Brain。
- 不是客户可见回复生成器。
- 不是商品事实授权源。
- 不是第二套识图模块。
- 不是本地关键词模板兜底。

客户可见回复仍只能来自 `customer_service_brain` 的 `BrainPlan.reply_segments`。

## 3. 总体链路

```text
微信文字/图片 turn
  -> customer_image_* 识图与视觉桥接
  -> Brain Preflight 轻量 LLM 判断
  -> evidence_builder 按 preflight 查询词补齐 product_master/formal evidence
  -> customer_service_brain 生成 BrainPlan
  -> guard / reviewer / final visible polish
  -> 发送前会话复核
```

Preflight 位于 `visual_bridge_input` 之后、`build_reply_evidence_pack` 之前。

## 4. LLM 输出契约

Preflight 使用 LLM，但输出必须是结构化 JSON，结构化只是“接口格式”，不是枚举规则替代智能判断。

建议字段：

```json
{
  "schema_version": 1,
  "customer_goal": "客户想确认图片里的车是否有现车",
  "business_intent": "product_availability",
  "requires_product_master": true,
  "requires_formal_knowledge": false,
  "requires_current_context": true,
  "low_authority_fast_allowed": false,
  "normalized_product_queries": ["比亚迪秦PLUS DM-i"],
  "evidence_lookup_mode": "product_master_exact_then_similar",
  "context_resolution": {
    "uses_visual_bridge": true,
    "uses_recent_visual_context": false,
    "ambiguous_reference": false
  },
  "brain_guidance": "先按商品库核对同款；无同款再让 Brain 基于商品库候选做相似推荐。",
  "confidence": 0.86,
  "reason": "图片识别为车型且客户问是否有这款"
}
```

字段边界：

- `normalized_product_queries` 只是检索词，不是商品事实。
- `requires_product_master=true` 只表示必须查商品库，不表示商品库已经命中。
- `brain_guidance` 是内部建议，不可直接发给客户。
- `low_authority_fast_allowed=false` 只能阻止空证据快路径，不能生成回复。

参考样例见：

- [examples/brain_preflight_output.example.json](examples/brain_preflight_output.example.json)

## 5. 触发策略

默认采用 `adaptive`，避免给所有文字 turn 增加一次 LLM 延迟。

触发条件：

- 当前 turn 有 `visual_bridge_input`。
- 当前 turn 是图片后的短追问，并且 `target_state.visual_context_state.last_visual_bridge_input` 存在。
- 当前 turn 是短文字，可能被 `low_authority_fast` 当成低权威短句，但 LLM 判断它其实是在问商品事实。
- 标准 evidence pack 已构造完成，但 `product_master.items` 为空，同时文字表面有车型代号、价格、配置、库存、车况等通用商品证据缺口信号。
- 配置显式设置 `preflight_mode=always`。

不触发条件：

- 纯文字普通闲聊且没有视觉上下文。
- 纯文字问题已经正常命中 `product_master`。
- Brain 未启用或 `mode=off`。
- 配置关闭 `preflight_enabled=false`。

这层触发只是省时策略；代码只做极少量通用门控，不枚举车名、不维护车型正则表。车型别名、错字、英文数字混写、口语表达的归一判断交给 LLM。

## 6. 配置契约

推荐配置位于 `customer_service_brain.preflight`，也兼容顶层 `customer_service_brain_preflight`。

```json
{
  "customer_service_brain": {
    "preflight": {
      "enabled": true,
      "mode": "adaptive",
      "provider": "kimi",
      "model_tier": "flash",
      "timeout_seconds": 3,
      "fallback_timeout_seconds": 2,
      "max_tokens": 360,
      "temperature": 0,
      "text_evidence_gap_enabled": true,
      "text_evidence_gap_max_chars": 80,
      "text_evidence_gap_probe_short_low_authority": true
    }
  }
}
```

配置原则：

- 默认可继承 Brain provider，也可单独指定更快的 provider。
- 超时必须短，失败不能阻断 Brain。
- 失败时只能回到原 Brain 流程；如果视觉桥接已经有明确车型线索，则只允许强制补查商品库，仍不生成客户话术。
- 普通文字扩展只在 evidence 缺口或短句快路径风险下触发，不能升级为所有消息全量 preflight。

## 7. 代码接入点

### 新增文件

| 文件 | 作用 |
|---|---|
| `apps/wechat_ai_customer_service/workflows/customer_service_brain_preflight.py` | 轻量 LLM preflight、契约归一、证据查询增强、审计压缩 |
| `apps/wechat_ai_customer_service/tests/run_customer_service_brain_preflight_checks.py` | 离线契约与 Brain evidence 接入测试 |

### 修改文件

| 文件 | 修改点 |
|---|---|
| `apps/wechat_ai_customer_service/workflows/customer_service_brain.py` | 在 evidence pack 前调用 preflight；用 preflight 阻止空证据快路径；把 preflight advisory 放入 BrainInput |
| `apps/wechat_ai_customer_service/docs/customer_service_image_understanding_20260702/00_INDEX.md` | 增加本设计文档入口 |
| `apps/wechat_ai_customer_service/docs/customer_service_image_understanding_20260702/examples/brain_preflight_output.example.json` | 输出契约样例 |

### 不修改

- 不改 `customer_image_understanding` provider。
- 不改 `customer_image_catalog_assist` 的商品匹配职责。
- 不改微信图片保存闭环。
- 不改历史消息 schema。
- 不改客户可见回复所有权。
- 不改非图片普通文字捕获和发送主流程。

## 8. 安全刹车

如果 Preflight LLM 不可用，但 `visual_bridge_input.catalog_assist.normalized_vehicle_query` 或上一轮视觉上下文里已有明确车型线索，代码机制层允许生成一个内部 `visual_bridge_evidence_guard`：

- 只做一件事：禁止 `low_authority_fast` 生成空商品证据包。
- 同时把视觉查询词追加到 evidence 查询文本。
- 不生成回复、不授权价格库存、不替 Brain 判断有无现车。

这个 guard 是证据链完整性保护，不是兜底话术。

## 9. 验收标准

- 图片识别出 `比亚迪秦PLUS DM-i` 后，客户问“有这款吗”，Brain evidence pack 必须包含 `chejin_qinplus_2022_dmi55`。
- 图片后的短追问“型号发我”必须复用视觉上下文查商品库，不得走空证据快路径。
- 文字短句如“奥迪a四l有吗”在商品库初次未命中时，Preflight 应输出“奥迪A4L”等通用查询词并重建 evidence pack。
- 文字问题如“秦PLUS多少钱”已经命中商品库时，不应额外调用文字 evidence-gap Preflight。
- 如果商品库无同款，Brain 只能基于 `product_master` 候选做相似推荐或说明需要核实，不能编造。
- 非车图或无视觉上下文的普通闲聊不应触发商品库强查。
- Preflight 失败不能导致客户可见本地兜底回复。
- 现有 Brain contract、视觉桥接、图片 turn router 测试不回归。

## 10. 审计结论

本方案修复的是 Brain evidence 前置判断缺口，不改变现有识图模块和 Brain First 主结构。它把“是否需要查商品库”交给轻量 LLM 做通用判断，同时用机制层确保视觉车型线索不会被低权威快路径吞掉。

只要实现阶段严格遵守 `customer_visible_reply_ownership_baseline.md`，Preflight 可以作为 Brain 的轻量外挂增强长期保留，不会变成新的回复层级。
