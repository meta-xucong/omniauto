> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# 微信智能客服识图测试、验收与审计计划

## 1. 验收目标

验证新增识图能力后：

- 车图可以正确进入“商品库匹配或相似推荐”路径。
- 非车图不会误进入商品事实链。
- Brain First 不被破坏。
- 现有主结构和纯文字路径不被重构。
- 多会话隔离、视觉证据隔离和 RPA 发送安全不被破坏。

## 2. 必须新增的测试类型

### 2.1 识图契约测试

建议脚本：

- `apps/wechat_ai_customer_service/tests/run_customer_service_image_understanding_contract_checks.py`

覆盖：

- 成功返回结构 normalize
- provider 超时
- provider 返回非 JSON
- 低置信度结果
- 图片缺失
- 多图输入截断到上限

### 2.2 商品桥接测试

建议脚本：

- `apps/wechat_ai_customer_service/tests/run_customer_service_visual_catalog_bridge_checks.py`

覆盖：

- 车图高置信度命中商品 alias
- 车图未命中完全同款但给出相似推荐
- 非车图不进入商品检索
- 低置信度时要求 Brain 澄清

### 2.3 Brain 桥接测试

建议脚本：

- `apps/wechat_ai_customer_service/tests/run_customer_service_visual_brain_bridge_checks.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_brain_preflight_checks.py`

覆盖：

- `visual_bridge_input` 缺失时，Brain 与旧行为一致
- `visual_bridge_input` 存在时，Brain 能读取视觉辅助包
- 视觉结果不会改写 `clean_text/history_text/current_batch_text`
- 识图失败但文字足够时，Brain 仍可正常走文字路径
- 视觉车型线索存在时，Preflight 会禁止空证据 `low_authority_fast`
- 图片后的短追问能通过 Preflight 复用上一轮视觉上下文查商品库
- 普通文字已命中商品库时，不额外触发 text evidence-gap Preflight
- 普通文字车型错别字/英文数字混写导致商品库初次为空时，Preflight 能归一查询词并重建 evidence pack
- Preflight 失败不会生成客户可见本地兜底回复

### 2.4 主流程集成测试

建议扩充：

- `apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- `apps/wechat_ai_customer_service/tests/run_knowledge_contamination_guard_checks.py`
- `apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py`
- `apps/wechat_ai_customer_service/tests/run_customer_image_live_capture_replay_checks.py`

新增断言：

- 图片 turn 可以通过独立视觉路径成为 Brain 任务。
- `visual_ocr_non_text` 仍然不会进入普通文字 history。
- 视觉上下文不会跨会话串用。
- `[图片]` pending 不会被旧 `monitor_pending` 文本合成吞掉。
- 微信保存图 `saved_image_path` 能成为识图主输入。

## 3. 场景矩阵

| 场景 | 预期 |
|---|---|
| 客户只发车图 | 识图 + 商品匹配或相似推荐 |
| 客户发车图并说“有这款吗” | 优先匹配商品库 |
| 客户发车图并问价格 | 识别车型后走商品库报价路径 |
| 客户发车图但库里无同款 | Brain 说明不是完全同款并给相似推荐 |
| 客户发食物/宠物/风景图 | 进入普通聊天模式 |
| 客户发非车图并问“这车多少钱” | Brain 应识别图文矛盾，优先澄清 |
| 客户只发模糊图 | Brain 要求补图或补车型名 |
| 客户连续发两张不同车图 | 以最新图为主，冲突时澄清 |
| A 会话发车图，B 会话发文字 | 不串会话、不串视觉上下文 |

## 4. 关键边界测试

### 4.1 Brain First 所有权

- 识图模块不能生成最终回复文本。
- provider 失败时不能本地模板替代 Brain。
- guard/final polish 仍然不能接管客户可见回复。
- `visual_bridge_input` 只能是 advisory side input，不能变成第二套回复 owner。

### 4.2 数据污染

- 图片 OCR 文本不得进入 AI 经验池学习源。
- 视觉摘要不得进入普通 history 组装。
- 图中看起来像价格的数字不能直接当商品价格。

### 4.3 商品事实授权

- 识图说“像秦PLUS”不等于商品库已命中。
- 只有 `product_master` 证据支持后，Brain 才能说具体价格、库存、车况。

### 4.4 多会话隔离

- `asset_id` 必须绑定到对应 `conversation_id`。
- `visual_context_state` 不得跨 session 使用。
- 发送前仍要保持现有目标会话复核链路。

### 4.5 结构冻结审计

- 只允许 `listen_and_reply.py`、`customer_service_brain.py`、`wechat_win32_ocr_sidecar.py` 三个旧文件出现窄接入改动。
- `wechat_win32_ocr_sidecar.py` 只能新增 `image-save` action 并委托专用模块，不得改变 `messages/send/sessions` 旧语义。
- `wechat_image_save_capture.py` 只能做微信图片保存采集，不能调用 LLM、不能做商品匹配、不能生成 `visual_bridge_input`。
- 识图理解、商品辅助和 Brain 桥接必须继续复用既有 `customer_image_understanding -> customer_image_catalog_assist -> customer_image_brain_bridge`，不能出现第二套并行链路。
- 纯文字路径的输入输出行为与旧版本一致。
- 没有把现有共享模块重构成多模态中心。

## 5. 性能目标

建议 V1 目标：

- 识图模块 P50 小于 2.5s
- 识图模块 P90 小于 5s
- 文字 Brain 路径不因识图模块默认增加不可控长尾

性能观测字段建议：

- `customer_image_understanding.audit.latency_ms`
- `customer_image_understanding.audit.used_fallback`
- `customer_image_assets.asset_prepare_ms`
- `visual_catalog_bridge.lookup_ms`
- `brain_visual_context_used`
- `customer_service_brain.brain_preflight.duration_seconds`
- `customer_service_brain.brain_preflight.plan.requires_product_master`
- `customer_service_brain.brain_preflight.plan.normalized_product_queries`

## 6. live 验收建议

### 6.1 真实图片用例

- 一张明确车型图
- 一张角度偏斜但仍能识别的车型图
- 一张库里没有的车型图
- 一张完全无关图片
- 一张模糊图

### 6.2 真实对话话术

- “这款有吗”
- “这车多少钱”
- “有类似的吗”
- “这是什么车”
- “你看这张图”

### 6.3 必看审计字段

- `customer_image_assets`
- `customer_image_understanding`
- `visual_catalog_bridge`
- `customer_service_brain`
- `brain_first_reply_audit`
- `customer_image_assets.assets[0].saved_image_path`
- `customer_image_assets.assets[0].save_method`
- `customer_image_assets.assets[0].session_key`
- `customer_image_turn.source_reason`

### 6.4 微信保存闭环验收

- 发送图片后，会话列表 `[图片]` pending 必须触发 `image-save`，不能只产生空 capture。
- 本地必须出现 tenant/session 隔离的图片文件和 `.meta.json`。
- 保存图必须能被 `customer_image_understanding` 读取并调用 provider。
- 保存图必须通过 `customer_image_asset_store.py` 统一进入既有 image asset 结构，不能绕过 asset store 直接调用 provider。
- 保存失败时必须保留 pending/retry 证据，并产生明确 reason，不能静默跳过。
- 旧文字回复如果被新图片打断，必须被 freshness stale 拦截，并重新处理图片 turn。

### 6.5 非识图回归验收

- 纯文字消息不触发 `image-save`。
- 纯文字消息不触发 `customer_image_understanding` provider。
- 纯文字 Brain 输入不包含 `visual_bridge_input` 时，回复链路与旧版本一致。
- `messages/send/sessions/voice-transcribe` sidecar contract tests 不回归。
- 商品库、RAG 学习、cloud gate、recorder、add_friend 相关测试不因识图改动变化。

## 7. go / no-go

### 可以上线灰度

- 所有新增 contract tests 通过
- 现有 Brain contract tests 不回归
- 图片不污染文字 history 和 learning
- 商品库匹配路径可稳定工作
- 非车图不会误触发商品报价
- 真实微信图片可以保存为 `saved_image_path` 并进入识图模块

### 不可上线

- 识图模块直接写客户话术
- 识图失败时本地模板顶替 Brain
- 图片识别结果跨会话串用
- 视觉 OCR 文本重新进入 history 或 learning
- `[图片]` 预览仍然只触发 `message_count=0` 空捕获
- 图片保存失败后没有 retry、诊断截图或内部告警

## 8. 文档阶段审计结论

本设计包要求后续实现时必须额外做一轮“落代码审计”：

- 审核新增字段是否都是可选字段
- 审核旧接口是否未被改名或换义
- 审核所有失败路径是否仍由 Brain 决定客户可见澄清/阻断
- 审核 `customer_visible_reply_ownership_baseline.md` 没有被违反
