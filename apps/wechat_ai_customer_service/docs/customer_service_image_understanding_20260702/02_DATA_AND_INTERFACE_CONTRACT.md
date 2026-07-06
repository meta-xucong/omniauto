> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# 微信智能客服识图数据与接口契约

## 1. 契约总原则

- 现有 `message.content`、`history_text`、`current_batch_text` 语义不变。
- 不把图片识别结果回填成普通聊天正文。
- 新能力全部通过“新增可选字段”和既有 `customer_image_*` 模块返回值接入。
- 新字段即使缺失，旧逻辑也必须继续可运行。

## 2. 配置原则

V1 推荐优先使用独立环境变量或独立 sidecar 配置读取识图能力，不强制改现有共享配置结构。

可选配置块名仍建议保留：

- `customer_image_understanding`

建议字段：

- `enabled`
- `provider`
- `request_style`
- `model`
- `base_url`
- `api_key_env`
- `timeout_seconds`
- `fallback_enabled`
- `fallback_provider`
- `fallback_request_style`
- `fallback_model`
- `fallback_base_url`
- `fallback_api_key_env`
- `max_images_per_turn`
- `max_image_edge_px`
- `jpeg_quality`
- `same_turn_text_window_seconds`
- `vehicle_confidence_threshold`
- `catalog_match_min_confidence`
- `local_preanalysis_enabled`
- `artifact_retention_days`
- `include_raw_vision_result_in_audit`

说明：

- 这里是识图模块自己的可选配置，不要求先改造现有主配置契约才能开工。
- 如果实现阶段需要零侵入接入，可先只走环境变量。

参考样例见：

- [examples/customer_image_understanding_config.example.json](examples/customer_image_understanding_config.example.json)

## 3. 原始消息层契约

V1 不要求改原始消息 schema。

要求：

- 不改现有 `type/content/sender/message_id` 语义。
- 图片资产和识图结果优先保存在既有 `customer_image_*` 模块的 sidecar payload 与 event audit 中。
- 如果后续需要增强原始消息层，也只能新增可选字段，不能改旧字段含义。

## 4. 图片资产契约

建议结构：

```json
{
  "asset_id": "visual_asset_wx_20260702_001",
  "message_id": "wx_msg_123",
  "conversation_id": "wx_conv_abc",
  "target_name": "客户A",
  "message_type": "image",
  "thumbnail_path": "runtime/apps/wechat_ai_customer_service/visual_assets/.../thumb.jpg",
  "bubble_crop_path": "runtime/apps/wechat_ai_customer_service/visual_assets/.../bubble_crop.jpg",
  "turn_capture_path": "runtime/apps/wechat_ai_customer_service/visual_assets/.../turn_capture.jpg",
  "sha256": "abc123",
  "width": 1080,
  "height": 1440,
  "captured_at": "2026-07-02T14:11:00+08:00"
}
```

要求：

- 至少保留一个可供模型识别的稳定本地文件。
- 路径必须能追溯到 `message_id` 和 `conversation_id`。
- 资产缺失时要返回明确失败原因，而不是静默继续。

## 5. 识图请求契约

建议内部接口：

```python
def maybe_run_customer_image_understanding(
    *,
    config: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    raw_capture: dict[str, Any],
) -> dict[str, Any]:
    ...
```

职责：

- 读取当前 batch 中的图片资产和同轮文字。
- 进行本地轻量预分析。
- 调用多模态 provider。
- 返回结构化识图结果和审计字段。

请求样例见：

- [examples/customer_image_understanding_request.example.json](examples/customer_image_understanding_request.example.json)

## 6. 识图结果契约

建议返回结构：

```json
{
  "schema_version": 1,
  "enabled": true,
  "applied": true,
  "adoptable": true,
  "reason": "vision_ready",
  "provider": "openai_compatible",
  "request_style": "anthropic_messages_vision",
  "model": "doubao-seed-2-0-lite-260428",
  "source_messages": [
    {
      "message_id": "wx_msg_123",
      "asset_id": "visual_asset_wx_20260702_001",
      "message_type": "image"
    }
  ],
  "local_visual_profile": {
    "width": 1080,
    "height": 1440,
    "orientation": "portrait",
    "dominant_colors": ["#f0f0f0", "#222222"]
  },
  "vision_summary": "图片主体是一辆白色三厢轿车，前脸接近比亚迪秦PLUS风格。",
  "image_ocr_text": ["秦PLUS", "DM-i"],
  "classification": {
    "is_vehicle": true,
    "vehicle_confidence": 0.93,
    "non_vehicle_reason": ""
  },
  "entities": {
    "brand_candidates": ["比亚迪"],
    "series_candidates": ["秦PLUS"],
    "model_clues": ["DM-i", "白色", "轿车"],
    "body_type": "sedan",
    "color": "white",
    "year_clues": ["2021+"]
  },
  "intent_hints": {
    "wants_catalog_match": true,
    "wants_similar_recommendation": true,
    "wants_general_chat": false,
    "needs_clarification": false
  },
  "bridge": {
    "normalized_vehicle_query": "比亚迪 秦PLUS DM-i 白色 轿车",
    "brain_mode": "vehicle_catalog_assist",
    "catalog_lookup_mode": "vehicle_exact_then_similar"
  },
  "audit": {
    "latency_ms": 1840,
    "used_fallback": false
  }
}
```

强约束：

- `vision_summary` 是可审计摘要，不是客户可见回复。
- `classification.is_vehicle` 只表示视觉判断，不表示商品库已命中。
- `bridge.normalized_vehicle_query` 是检索线索，不是授权事实。

参考样例见：

- [examples/customer_image_understanding_result.example.json](examples/customer_image_understanding_result.example.json)

## 7. 商品检索桥接契约

建议内部接口：

```python
def compose_visual_query_for_catalog(
    *,
    combined_text: str,
    image_understanding: dict[str, Any],
    target_state: dict[str, Any],
) -> dict[str, Any]:
    ...
```

建议输出：

- `catalog_query_text`
- `catalog_lookup_mode`
- `visual_match_confidence`
- `preferred_candidate_ids`
- `similar_recommendation_allowed`
- `clarification_needed`

行为约束：

- 不直接输出客户回复。
- 不直接输出价格或库存。
- 只为现有 `reply_evidence_builder` 提供更好的查询文本和候选偏好。

## 8. Brain 最小桥接契约

V1 不建议重写 `BrainInput` 主合同。

建议只给 Brain 增加一个最小可选内部参数：

```python
def maybe_run_customer_service_brain(
    *,
    ...,
    visual_bridge_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
```

### 8.1 `visual_bridge_input`

建议字段：

- `present`
- `is_vehicle`
- `vehicle_confidence`
- `vision_summary`
- `normalized_vehicle_query`
- `needs_clarification`
- `source_message_ids`
- `catalog_assist`
- `policy`

建议政策文案：

- `visual bridge input is advisory only; product facts must still be grounded in product_master and formal_knowledge`

使用规则：

- 不改写原有 `clean_text`。
- 不改写原有 `history_text/current_batch_text`。
- 不要求所有旧调用方都传这个参数。
- 参数缺失时，Brain 行为应与当前版本一致。

桥接输入样例见：

- [examples/brain_visual_bridge_input.example.json](examples/brain_visual_bridge_input.example.json)

## 9. Brain Preflight 轻量外挂契约

当 `visual_bridge_input` 存在，或图片后的短追问需要复用视觉上下文时，允许在 `customer_service_brain` 内部调用 `Brain Preflight`。

内部接口建议：

```python
def maybe_run_customer_service_brain_preflight(
    *,
    config: dict[str, Any],
    settings: dict[str, Any],
    target_name: str,
    target_state: dict[str, Any],
    batch: list[dict[str, Any]],
    combined: str,
    visual_bridge_input: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
```

返回结构建议：

```json
{
  "enabled": true,
  "applied": true,
  "reason": "brain_preflight_ready",
  "provider": "kimi",
  "model": "kimi-latest",
  "plan": {
    "requires_product_master": true,
    "low_authority_fast_allowed": false,
    "normalized_product_queries": ["比亚迪秦PLUS DM-i"],
    "brain_guidance": "先查商品库，再由 Brain 回复"
  }
}
```

使用规则：

- Preflight 是 `customer_service_brain` 的内部轻量外挂，不是新增外部层级。
- Preflight 只能影响 evidence 查询词、证据需求和低权威快路径开关。
- Preflight 不得生成客户可见回复。
- Preflight 不得把视觉摘要写入 `history_text/current_batch_text`。
- Preflight 失败时不能本地兜底回复；如果视觉桥接已有明确车型线索，只允许强制补查商品库。
- 普通文字扩展只允许在 `product_master` evidence 缺口或短句快路径风险下触发，用 LLM 归一查询词；不能改成所有消息全量前置判断。

详细设计见：

- [07_BRAIN_PREFLIGHT_LIGHTWEIGHT_PLUGIN_DESIGN.md](07_BRAIN_PREFLIGHT_LIGHTWEIGHT_PLUGIN_DESIGN.md)

## 9. 会话级视觉上下文契约

建议在既有 `customer_image_*` 模块自有 sidecar state 中维护，必要时再映射为 `target_state` 的可选内部字段：

- `visual_context_state`

建议字段：

- `last_visual_reference`
- `last_vehicle_query`
- `last_vehicle_confidence`
- `source_message_ids`
- `updated_at`
- `expires_at`

使用规则：

- 只在同一会话内有效。
- 只用于“这款 / 这台 / 上面这个”类指代解析。
- 过期后自动失效。

## 10. 审计事件字段

建议在 `event` 中新增：

- `customer_image_assets`
- `customer_image_understanding`
- `customer_image_understanding_adopted`
- `visual_catalog_bridge`
- `brain_visual_context_used`

建议 reason 值：

- `vision_ready`
- `vision_no_image_assets`
- `vision_provider_unavailable`
- `vision_timeout`
- `vision_parse_failed`
- `vision_low_confidence`
- `vision_text_path_used`

## 11. provider 适配器契约

沿用既有独立 provider 适配器，不直接污染 `llm_config.py` 公共文本路径。

建议内部接口：

```python
def run_customer_image_understanding_provider(
    *,
    provider: str,
    request_style: str,
    api_key: str,
    base_url: str,
    model: str,
    prompt: str,
    image_paths: list[str],
    response_json_schema_hint: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    ...
```

建议支持的 `request_style`：

- `openai_chat_vision`
- `anthropic_messages_vision`

## 12. 失败契约

识图模块失败时返回结构必须可审计：

```json
{
  "enabled": true,
  "applied": false,
  "adoptable": false,
  "reason": "vision_timeout",
  "error": "customer_image_understanding_timeout"
}
```

处理原则：

- 如果文字足够，主流程可继续。
- 如果文字不足，最终如何向客户追问，必须由 Brain 决定。
