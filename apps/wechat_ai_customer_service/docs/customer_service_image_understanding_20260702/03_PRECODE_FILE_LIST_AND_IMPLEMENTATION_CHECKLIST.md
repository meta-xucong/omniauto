> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# 微信智能客服识图预编码文件清单与实施检查表

## 1. 本次已准备好的落代码前文件

- [00_INDEX.md](00_INDEX.md)
- [01_REQUIREMENTS_AND_ARCHITECTURE.md](01_REQUIREMENTS_AND_ARCHITECTURE.md)
- [02_DATA_AND_INTERFACE_CONTRACT.md](02_DATA_AND_INTERFACE_CONTRACT.md)
- [04_TEST_ACCEPTANCE_AND_AUDIT_PLAN.md](04_TEST_ACCEPTANCE_AND_AUDIT_PLAN.md)
- [05_ALCHEMYOS_DOUBAO_REFERENCE_AUDIT.md](05_ALCHEMYOS_DOUBAO_REFERENCE_AUDIT.md)
- [06_WECHAT_IMAGE_SAVE_CLOSED_LOOP_DESIGN.md](06_WECHAT_IMAGE_SAVE_CLOSED_LOOP_DESIGN.md)
- [examples/customer_image_understanding_request.example.json](examples/customer_image_understanding_request.example.json)
- [examples/customer_image_understanding_result.example.json](examples/customer_image_understanding_result.example.json)
- [examples/brain_visual_bridge_input.example.json](examples/brain_visual_bridge_input.example.json)
- [examples/customer_image_understanding_config.example.json](examples/customer_image_understanding_config.example.json)

## 2. 现有识图流水线与新增采集适配

| 类型 | 路径 | 作用 |
|---|---|---|
| `existing/extend` | `apps/wechat_ai_customer_service/workflows/customer_image_asset_store.py` | 唯一图片资产入口；扩展为优先接收微信保存图 `saved_image_path` |
| `new` | `apps/wechat_ai_customer_service/adapters/wechat_image_save_capture.py` | 微信真实图片气泡定位、右键保存、文件稳定性校验、保存图元数据；只做采集适配 |
| `existing` | `apps/wechat_ai_customer_service/workflows/customer_image_understanding_contract.py` | 识图请求/结果 normalize 与校验 |
| `existing` | `apps/wechat_ai_customer_service/workflows/customer_image_understanding_provider.py` | 多模态 provider 独立适配器 |
| `existing/extend` | `apps/wechat_ai_customer_service/workflows/customer_image_understanding.py` | 识图编排、预处理、provider 调用、审计输出；扩展为优先读取 `saved_image_path` |
| `existing` | `apps/wechat_ai_customer_service/workflows/customer_image_catalog_assist.py` | 识图结果到商品辅助查询的桥接 |
| `existing` | `apps/wechat_ai_customer_service/workflows/customer_image_brain_bridge.py` | 组装最小 `visual_bridge_input` |
| `existing/extend` | `apps/wechat_ai_customer_service/workflows/customer_image_turn_router.py` | 图片 turn 路由总入口；扩展识别 `[图片]` pending 和空捕获图片 pending |
| `existing` | `apps/wechat_ai_customer_service/tests/run_customer_service_image_understanding_contract_checks.py` | 识图结果契约测试 |
| `planned` | `apps/wechat_ai_customer_service/tests/run_customer_service_visual_catalog_bridge_checks.py` | 图片到商品检索桥接测试 |
| `existing` | `apps/wechat_ai_customer_service/tests/run_customer_service_visual_brain_bridge_checks.py` | Brain 最小桥接测试 |
| `new` | `apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py` | 微信图片保存 action 与资产契约测试 |
| `new` | `apps/wechat_ai_customer_service/tests/run_customer_image_live_capture_replay_checks.py` | 用截图和菜单 fixture 回放真实微信图片保存链路 |

融合规则：

- 不新增第二套识图 provider、第二套商品桥接、第二套 Brain bridge 或第二套图片 turn router。
- `wechat_image_save_capture.py` 只返回 `assets/messages/diagnostics`，并把保存图路径交给 `customer_image_asset_store.py` 统一归档。
- 后续仍固定走既有 `customer_image_understanding -> customer_image_catalog_assist -> customer_image_brain_bridge -> customer_service_brain` 链路。
- 现有基于截图裁剪的 `bubble_crop_path/thumbnail_path` 保留为诊断或兼容 fallback，不再作为真实微信图片的主输入。

## 3. 允许修改的现有代码文件

| 类型 | 路径 | 作用 |
|---|---|---|
| `modify` | `apps/wechat_ai_customer_service/workflows/listen_and_reply.py` | 把“图片自动忽略”改成“转交 `customer_image_turn_router`” |
| `modify` | `apps/wechat_ai_customer_service/workflows/customer_service_brain.py` | 仅增加一个可选 `visual_bridge_input` 入口 |
| `modify` | `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py` | 新增 `image-save` action，委托专用保存模块，不改变旧 action 语义 |

约束：

- V1 不计划改 `reply_evidence_builder.py` 主结构。
- V1 不计划改 `wechat_message_envelope.py` 主结构。
- V1 不要求改共享 example config 文件后才能开工。

## 4. 可选二期文件

| 类型 | 路径 | 作用 |
|---|---|---|
| `optional` | `apps/wechat_ai_customer_service/admin_backend/api/raw_messages.py` | 后台查看识图审计摘要 |
| `optional` | `apps/wechat_ai_customer_service/admin_backend/services/raw_message_store.py` | 持久化图片资产索引与识图摘要 |
| `optional` | `apps/wechat_ai_customer_service/tests/run_file_transfer_live_regression.py` | 增加发图 live 回归 |

## 5. 建议实施顺序

### Step 1

- 复核既有 `customer_image_*` 流水线和测试状态。
- 确认本次只补微信保存图入口，不新增第二套识图理解链路。

### Step 2

- 新增 `wechat_image_save_capture.py`
- 补 `image-save` action，真实微信图片优先保存为本地压缩图文件，不以窗口缩略图作为主识图输入
- 返回结构必须兼容 `customer_image_asset_store.py` 的统一资产契约

### Step 3

- 扩展 `customer_image_asset_store.py`
- 优先调用 sidecar `image-save`
- 把 `saved_image_path` 合并进既有 image asset，不新增另一套 asset store

### Step 4

- 扩展 `customer_image_understanding.py`
- 优先读取 `saved_image_path`
- 保留 `bubble_crop_path/thumbnail_path` 作为诊断或兼容 fallback

### Step 5

- 扩展 `customer_image_turn_router.py`
- 识别 `[图片]` 预览、空捕获图片 pending、直接 image message
- 仍然调用既有 catalog assist 和 brain bridge

### Step 6

- 修改 `listen_and_reply.py`
- 把图片 turn 从“忽略”改成“转交路由模块”

### Step 7

- 修改 `customer_service_brain.py`
- 只增加一个最小 `visual_bridge_input` 可选入口

### Step 8

- 补测试、回归、审计与 live 验收

## 6. 预编码检查表

### 6.1 架构检查

- 识图模块是否明确不是客户可见回复 owner。
- Brain 是否仍是唯一客户可见回复作者。
- 图片 OCR 和图片语义是否没有混写进普通 `history_text/current_batch_text`。
- 商品事实是否仍只从 `product_master/formal_knowledge` 授权。
- 旧代码改动面是否被限制在 `listen_and_reply.py`、`customer_service_brain.py`、`wechat_win32_ocr_sidecar.py` 三个窄接点内。

### 6.2 契约检查

- 没有改名现有 `type/content/message_id/route/json field`。
- 所有新增字段都是可选字段。
- 旧路径在新增字段缺失时仍可运行。
- `visual_context_state` 明确是会话内短时元数据，不是事实源。
- `visual_bridge_input` 缺失时，Brain 行为是否与旧版本一致。

### 6.3 provider 检查

- 识图 provider 与 Brain provider 配置解耦。
- 识图 provider 有独立 `api_key/base_url/model/request_style/timeout`。
- 不复用 Brain 的 `OPENAI_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN` 作为唯一入口。
- 识图 provider 超时不会拖死 Brain 主链路。

### 6.4 数据污染检查

- 视觉 OCR 文本不会被写进学习语料。
- 非车图不会误进入商品库事实链。
- 低置信度车型识别不会被当作已命中商品库。

### 6.5 多会话安全检查

- 图片资产与 `conversation_id/session_key/message_id` 绑定。
- 不会把 A 会话的图识别结果喂给 B 会话。
- 视觉上下文有 TTL，过期即失效。

### 6.6 微信图片保存闭环检查

- `[图片]` 预览不会再走旧 `monitor_pending` 文本合成。
- 图片保存成功后，即使 OCR 文字消息为空，也能生成 `type=image` 的 proxy batch。
- `saved_image_path` 是识图主输入，`bubble_crop_path/thumbnail_path` 只作为诊断或兼容输入。
- 保存失败必须有明确 reason、诊断截图和 retry/alert，不允许静默变成 `message_count=0` 后跳过。
- sidecar 新增 `image-save` 不改变 `messages/send/sessions/voice-transcribe` 旧 action 语义。

### 6.7 非识图链路零影响检查

- 没有图片 pending 或 image message 时，普通文字消息不调用 `image-save`，不调用识图 provider。
- 普通文字客服、发送验证、会话绑定、商品事实授权、RAG 学习、cloud gate、recorder、add_friend 行为不因本次改动变化。
- `listen_and_reply.py` 的新增逻辑只在明确图片触发条件下执行。
- `wechat_win32_ocr_sidecar.py` 只新增 `image-save`，不改旧 action 的返回契约。
- `customer_service_brain.py` 只接收可选 `visual_bridge_input`，缺失时行为与旧版本一致。

## 7. 命名建议

建议新增命名：

- `customer_image_understanding`
- `customer_image_assets`
- `visual_catalog_bridge`
- `visual_context_state`
- `brain_visual_context_used`

不要做的命名动作：

- 不把现有 `customer_service_brain` 改名成“multimodal brain”。
- 不把现有 `visual_ocr_non_text` 语义改成“允许进文字 history”。
- 不把 `type` 直接改写成一套全新枚举。

## 8. 配置与环境变量建议

建议新增环境变量：

- `CUSTOMER_IMAGE_UNDERSTANDING_API_KEY`
- `CUSTOMER_IMAGE_UNDERSTANDING_BASE_URL`
- `CUSTOMER_IMAGE_UNDERSTANDING_MODEL`
- `CUSTOMER_IMAGE_UNDERSTANDING_REQUEST_STYLE`
- `CUSTOMER_IMAGE_UNDERSTANDING_TIMEOUT_SECONDS`

如需 fallback，再新增：

- `CUSTOMER_IMAGE_UNDERSTANDING_FALLBACK_API_KEY`
- `CUSTOMER_IMAGE_UNDERSTANDING_FALLBACK_BASE_URL`
- `CUSTOMER_IMAGE_UNDERSTANDING_FALLBACK_MODEL`
- `CUSTOMER_IMAGE_UNDERSTANDING_FALLBACK_REQUEST_STYLE`
