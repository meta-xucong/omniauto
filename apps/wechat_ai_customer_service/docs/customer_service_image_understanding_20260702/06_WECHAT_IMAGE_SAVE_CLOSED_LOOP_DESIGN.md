> [!CAUTION]
> **文档状态：生产方案已完全废止（2026-07-18）。** 图片落盘、`image_assets`、`saved_image_path`、截图裁切、另存为回退、Sidecar `image-save` 及其重试链路均禁止恢复。本文只保留现场故障证据；现行唯一取图规则和模块架构见 [完全独立图像识别模块改造方案](../customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)。

> Customer-service development baseline: [../customer_visible_reply_ownership_baseline.md](../customer_visible_reply_ownership_baseline.md).

# 微信图片保存闭环开发设计

## 1. 背景与实盘证据

2026-07-06 人工实盘测试结论：

- 文字消息可以正常捕获、进入 Brain、发送回复。
- 图片消息在会话列表层能看到未读红点和预览 `许聪:[图片]`。
- 调度层多次进入 `新数据测试` 会话捕获，但 `message_count=0`，`empty_capture_retries=5`。
- 识图模块没有被调用，原因不是 provider 或 Brain 失败，而是微信端图片没有被保存成 `image asset`。
- 后续实盘复核发现，程序已能定位图片并右键，但旧实现使用窗口离屏截图识别右键菜单，微信右键菜单作为独立弹层没有出现在 `capture_wechat(hwnd)` 截图里，导致连续返回 `image_context_menu_save_item_missing` 并按 3/6/12/24/48 秒重试。
- 人工截图确认当前微信图片菜单第一项是 `复制`，底部有 `另存为...`；因此真实采集应优先走 `复制 -> 读取剪贴板图片 -> 保存到 image_assets`，`另存为...` 只作为后备路径。
- 第二轮实盘复核发现，第二张图片可以成功复制并保存成新 asset，但 scheduler 旧的 `content_key` 只使用 proxy 文案 `客户发来了一张图片`，导致不同图片被当成同一条内容去重，`context_version` 不前进、Brain 不启动，并反复采集同一图片。图片 proxy 的 content key 必须包含 `asset_id/source_message_id/saved_image_path` 等图片身份。

因此，本轮要补的是微信端真实图片入口闭环：

`发现 [图片] 预览 -> 点开正确会话 -> 定位客户侧图片气泡 -> 直接保存微信压缩图 -> 交给既有 customer_image_asset_store 统一生成图片资产 -> 调用既有 customer_image_understanding -> 传 visual_bridge_input 给 Brain -> Brain 回复 -> 发送前继续做会话复核`

## 2. 方案选择

主方案：直接保存微信聊天里的压缩图片文件，默认通过右键菜单 `复制` 把微信压缩图放入系统剪贴板，再由 sidecar 读取剪贴板图片并写入专属 `image_assets` 目录。

不采用缩略图作为主输入，原因：

- 聊天窗口缩略图可能太小，车型、车标、细节不稳定。
- 微信压缩后的图片通常已经足够清楚，体积小，适合视觉模型。
- 不需要双击打开原图或等待原图加载，可以减少 RPA 步骤和卡顿。

允许的辅助材料：

- 当前会话截图仅用于定位、诊断和审计。
- 图片气泡裁剪图仅作为诊断 fallback 证据，默认不作为识图主输入。
- 如果微信菜单没有 `复制/复制图片` 或剪贴板读取失败，允许后备尝试 `另存为.../保存图片`，但仍然要标记具体 `save_method`；不能把截图裁剪伪装成微信保存图。

## 3. 硬边界

- 不改 Brain First 所有权：客户可见回复仍只能由 `customer_service_brain` 生成。
- 不新增第二套识图流水线；现有 `customer_image_*` 是唯一识图流水线。
- `wechat_image_save_capture.py` 只是微信图片保存采集适配器，不调用 LLM、不做商品匹配、不构造 `visual_bridge_input`、不生成客户可见回复。
- 不把识图摘要、图片 OCR、车型猜测塞进普通 `message.content/history_text/current_batch_text`。
- 不把 `[图片]` 预览合成为旧文本问题继续交给 Brain。
- 不新增本地模板兜底回复；图片保存失败后的客户可见澄清也必须由 Brain 生成，或触发内部阻断/告警。
- 不为了识图而重构现有文字消息主链路。
- 不改已有 route、字段、函数名语义；新增能力采用新增 action、可选字段和新增模块。

## 3.1 非识图链路零影响边界

本次开发只允许改动“识图专用模块”和必要的主程序窄接点。没有图片信号时，文字客服、发送、会话监听、商品库、RAG、学习、后台、云门禁、录音、加好友等非识图链路必须保持旧行为。

明确允许的范围：

- 复用并小幅扩展既有 `customer_image_*` 识图专用模块。
- 新增 `apps/wechat_ai_customer_service/adapters/wechat_image_save_capture.py` 作为微信图片保存采集适配器。
- 在 `wechat_win32_ocr_sidecar.py` 中只新增 `image-save` action，并委托专用模块。
- 在 `listen_and_reply.py` 中只新增图片 pending 分流、图片 asset 传递、阻断旧 `[图片] -> monitor_pending` 文本合成。
- 在 `customer_service_brain.py` 中只保留已有 `visual_bridge_input` 可选入参，不改 Brain 主输入合同。

明确禁止的范围：

- 不改 `messages/send/sessions/voice-transcribe` 旧 sidecar action 语义。
- 不改普通文字消息捕获、批处理、发送验证、会话绑定和 stale/freshness 主逻辑。
- 不改商品事实来源、价格/库存授权规则、RAG 学习入口、customer profile、cloud gate、recorder、add_friend 路线。
- 不把识图失败变成任何本地客户可见模板回复。
- 不为了识图改名现有函数、字段、route、JSON key 或 CLI 参数。

验收标准：

- 没有图片 pending、没有 image message、没有 `visual_bridge_input` 时，现有文字路径 contract tests 和 live 文本自测必须与修改前一致。
- 新增逻辑必须由明确图片触发条件进入，不能在普通文本 turn 中额外调用识图 provider 或图片保存 RPA。

## 4. 本地保存目录

新增专属暂存目录：

```text
runtime/apps/wechat_ai_customer_service/tenants/{tenant_id}/customer_service/image_assets/{safe_session_key}/{yyyyMMdd}/
```

建议文件命名：

```text
wx_image_{HHmmss}_{sha256_12}.{ext}
wx_image_{HHmmss}_{sha256_12}.meta.json
wx_image_{HHmmss}_{sha256_12}.diagnostic.png
```

目录规则：

- `{tenant_id}` 使用当前租户，例如 `chejin`。
- `{safe_session_key}` 优先使用 `session_key` 的安全化版本；缺失时使用安全化 `target_name`。
- 默认只暂存，不作为长期素材库。
- 默认保留 `artifact_retention_days` 天，清理任务后续可独立实现。
- `meta.json` 必须记录 `target_name/session_key/conversation_type/message_id/speaker_name/save_method/source_preview/sha256/width/height/size_bytes/captured_at`。

## 5. 代码清单

### 5.1 新增文件

| 文件 | 作用 |
|---|---|
| `apps/wechat_ai_customer_service/adapters/wechat_image_save_capture.py` | 真实微信图片气泡定位、右键菜单复制优先、另存为后备、剪贴板图片落盘、资产元数据生成 |
| `apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py` | 纯函数与返回契约测试，不依赖真实微信 |
| `apps/wechat_ai_customer_service/tests/run_customer_image_live_capture_replay_checks.py` | 用保存好的截图/菜单 fixture 回放图片捕获链路 |

### 5.2 修改文件

| 文件 | 修改点 |
|---|---|
| `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py` | 新增 `image-save` action，解析参数后委托给 `wechat_image_save_capture.py` |
| `apps/wechat_ai_customer_service/workflows/customer_image_asset_store.py` | 作为唯一资产入口优先调用 sidecar `image-save`，把 `saved_image_path` 合并进既有 asset |
| `apps/wechat_ai_customer_service/workflows/customer_image_turn_router.py` | 识别 `[图片]` 预览、空捕获图片 pending、直接 image message，统一进入图片路由 |
| `apps/wechat_ai_customer_service/workflows/listen_and_reply.py` | 把 session monitor 的图片 pending 信号传给图片路由；阻止 `[图片]` 走旧 `monitor_pending` 文本合成 |
| `apps/wechat_ai_customer_service/workflows/customer_image_understanding.py` | 在既有识图编排中优先读取 `saved_image_path`，保留 `bubble_crop_path` 兼容 |

### 5.3 不修改

- 不改 `customer_service_brain` 主结构，只继续使用已有 `visual_bridge_input`。
- 不改 `wechat_message_envelope.py` 旧字段语义。
- 不改现有文字捕获、文字回复、发送动作名称。
- 不新增第二套 `customer_image_understanding_provider/catalog_assist/brain_bridge/turn_router`。

## 6. Sidecar 接口清单

### 6.1 新增 action

```powershell
python apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py image-save `
  --target "新数据测试" `
  --exact `
  --session-key "wx:rpa:v1:c68501c9149abc8c3d54" `
  --artifact-dir "runtime/apps/wechat_ai_customer_service/tenants/chejin/customer_service/image_assets/wx_rpa_v1_c68501c9149abc8c3d54/20260706" `
  --sidecar-run-id "capture_xxx"
```

新增 parser 参数建议：

- `--max-images`，默认 `1`，最大 `3`
- `--source-preview`，例如 `许聪:[图片]`
- `--speaker-name`，群聊中来自列表预览的发送人，例如 `许聪`
- `--image-save-mode`，预留参数；当前默认策略为 `context_menu_copy_clipboard`，`context_menu_save_as` 仅作后备
- `--retention-days`，默认读配置

### 6.2 返回契约

成功：

```json
{
  "ok": true,
  "adapter": "win32_ocr",
  "state": "image_saved",
  "target": "新数据测试",
  "session_key": "wx:rpa:v1:c68501c9149abc8c3d54",
  "assets": [
    {
      "asset_id": "visual_asset_wx_20260706_abcd1234",
      "message_id": "visual_msg_wx_20260706_abcd1234",
      "message_type": "image",
      "target_name": "新数据测试",
      "conversation_type": "group",
      "speaker_name": "许聪",
      "session_key": "wx:rpa:v1:c68501c9149abc8c3d54",
      "saved_image_path": "runtime/.../wx_image_110920_abcd1234ef56.jpg",
      "sha256": "abcd1234ef56...",
      "width": 960,
      "height": 1280,
      "size_bytes": 184232,
      "save_method": "context_menu_save_as",
      "source_preview": "许聪:[图片]",
      "captured_at": "2026-07-06T11:09:20"
    }
  ],
  "messages": [
    {
      "id": "visual_msg_wx_20260706_abcd1234",
      "type": "image",
      "sender": "customer",
      "sender_role": "customer",
      "content": "[图片]",
      "speaker_name": "许聪",
      "image_assets": ["visual_asset_wx_20260706_abcd1234"]
    }
  ],
  "diagnostics": {
    "screenshot_path": "runtime/.../diagnostic.png",
    "bubble_anchor": {"x": 452, "y": 612},
    "context_menu_label": "另存为...",
    "dialog_result": "saved"
  }
}
```

失败：

```json
{
  "ok": false,
  "adapter": "win32_ocr",
  "state": "image_save_failed",
  "reason": "image_bubble_not_found",
  "target": "新数据测试",
  "session_key": "wx:rpa:v1:c68501c9149abc8c3d54",
  "assets": [],
  "diagnostics": {
    "screenshot_path": "runtime/.../image_save_failed.png",
    "source_preview": "许聪:[图片]"
  }
}
```

## 7. 图片保存流程

### 7.1 触发条件

任一条件成立就进入图片保存链路：

- `payload.messages` 中出现 `type=image/picture/photo`。
- session monitor 的 `pending_signal_text` 包含 `[图片]`、`[照片]`、`[Image]`。
- 会话列表预览包含 `发送了一张图片`、`图片` 且有未读红点。
- 捕获结果 `message_count=0`，但该 session 的最新 pending signal 是图片。

### 7.2 RPA 步骤

1. 使用现有 `open_chat` / `session_key` 打开并确认目标会话。
2. 截图并 OCR，用现有 `validate_active_send_target` 复核聊天标题。
3. 在聊天区域内定位最新客户侧图片气泡。
4. 右键图片气泡，不双击，不打开原图查看器。
5. 用可见屏幕截图识别右键菜单，避免离屏窗口截图漏掉菜单弹层。
6. 优先点击 `复制` / `复制图片` / `Copy Image`，从系统剪贴板读取图片并保存为 `.png`。
7. 如果没有复制项，可后备点击 `另存为...` / `保存图片` / `Save As`，保存到完整绝对路径。
8. 等待文件出现并稳定，读取文件头、尺寸、sha256。
9. 返回 `assets` 和 `type=image` 的 synthetic message。

### 7.3 图片气泡定位

定位原则：

- 只在聊天内容区域内找，排除左侧 session list、顶部标题、底部输入框。
- 优先选择客户侧、靠近底部、未被已有文字消息 bubble 覆盖的大块图片区域。
- 群聊中如果预览有 `speaker_name`，必须记录到资产和 message。
- 如果同屏多张图，默认取最新一张，最多取 `max_images=3`。
- 如果无法判断图片在客户侧还是自己侧，返回 `image_bubble_side_uncertain`，不要保存。

## 8. Workflow 接入

### 8.1 `customer_image_asset_store`

新增行为：

- 它仍是唯一图片资产入口。
- 如果 `source_preview` 或 `target_state.pending_signal_text` 是图片，先调用 `image-save`。
- `image-save` 返回的资产必须合并为既有 image asset 结构，而不是生成第二套资产对象。
- `saved_image_path` 是真实微信图片的识图主输入。
- `bubble_crop_path/thumbnail_path` 只做诊断或兼容。
- 返回 reason 使用：
  - `wechat_image_saved`
  - `wechat_image_save_failed`
  - `wechat_image_bubble_not_found`
  - `wechat_image_save_dialog_failed`
  - `wechat_image_file_unstable`

### 8.2 `customer_image_turn_router`

新增行为：

- `source_reason=preview_image_message`：来自会话列表 `[图片]`。
- `source_reason=empty_capture_image_pending`：进入会话后无文字，但 pending signal 是图片。
- 如果保存成功，生成 `proxy_batch`：

```json
{
  "id": "visual_msg_wx_20260706_abcd1234",
  "type": "image",
  "sender": "customer",
  "sender_role": "customer",
  "content": "[图片]",
  "image_assets": ["visual_asset_wx_20260706_abcd1234"]
}
```

- 传给 Brain 的 `combined_text_override` 可以是 `客户发来了一张图片`，但只能作为 turn 描述，不能混入长期 history。

### 8.3 `listen_and_reply`

新增约束：

- 当 session preview 是 `[图片]` 时，不得把旧文字 preview 合成为 `monitor_pending` 文本任务。
- 图片保存成功后，即使 OCR `message_count=0`，也应通过 image proxy batch 进入 Brain 任务。
- 图片 proxy 的调度身份必须包含图片资产身份，不能只按固定文案 `客户发来了一张图片` 去重。
- 图片保存失败时，保持 pending retry；超过重试次数后走 Brain 生成澄清或内部告警，不能静默 `skipped`。
- 如果旧文字回复正在发送前发现新图片，现有 freshness stale 应拦截旧回复，并触发图片捕获任务。

## 9. 失败处理

| 失败点 | 行为 |
|---|---|
| 打不开目标会话 | 沿用现有 target validation failure，不处理图片 |
| 找不到图片气泡 | 保留 pending，指数退避重试 |
| 右键菜单无复制项和保存项 | 返回 `image_context_menu_save_item_missing`，不调用识图 |
| 剪贴板没有图片或读取失败 | 返回 `clipboard_image_missing` / `clipboard_image_read_failed`，不调用识图 |
| 保存对话框失败 | 不发送客户回复，保留 retry 和诊断截图 |
| 文件没有生成或尺寸为 0 | 返回 `image_file_unstable`，不调用识图 |
| 识图 provider 失败 | 将失败结构传给 Brain，由 Brain 决定澄清；不能本地模板回复 |
| Brain 无可见回复 | 按 Brain First 现有规则阻断发送并告警 |

重试策略建议：

- 单轮最多保存尝试 `1` 次；失败交给调度层 retry，避免在同一菜单状态里重复右键。
- 每次失败记录 `retry_not_before`。图片采集类 UI 失败使用更长冷却下限，避免 3 秒级机械重复右键。
- 超过阈值后生成内部 `operator_alert`，并可让 Brain 基于 `image_asset_save_failed` 生成温和澄清。

## 10. 测试清单

### 10.1 Contract tests

- `image-save` 成功返回 `assets/messages/diagnostics`。
- `saved_image_path` 缺失时 `customer_image_understanding` 不调用 provider。
- `[图片]` pending 不会生成 `monitor_pending` 旧文本任务。
- image proxy batch 不进入普通 learning/history。
- `saved_image_path` 优先级高于 `bubble_crop_path/thumbnail_path`。

### 10.2 Fixture replay

用保存的截图 fixture 回放：

- 单张客户侧图片。
- 群聊 `许聪:[图片]`。
- 同屏多图，只取最新图。
- 自己发送的图片，不应被当作客户图。
- 菜单无保存项。
- 保存对话框失败。

### 10.3 Live tests

按顺序测试：

1. 发文字：`这款车你们这里有吗`，确认文字链路不回归。
2. 发文字：`你这里有白色特斯拉model3吗`，确认 Brain 正常。
3. 发一张 Model 3 图片，不配文字。
4. 发一张 Model 3 图片，配文字：`这款多少钱`。
5. 发一张非车图片。

必须检查：

- `session_monitor_state.pending_signal_text`。
- `customer_image_assets.assets[0].saved_image_path`。
- `customer_image_understanding.applied=true`。
- `brain_visual_context_used=true`。
- `reply_sent` 增加。
- 图片资产路径位于 tenant 专属目录。

## 11. 审计清单

### 11.1 结构审计

- 新增 sidecar action 是否只是能力入口，没有改变 `messages/send/sessions` 旧语义。
- 图片保存模块是否独立，sidecar 只做最薄委托。
- 图片保存模块是否完全不调用 LLM、不做商品匹配、不构造 Brain bridge。
- 识图仍是否只走既有 `customer_image_understanding -> customer_image_catalog_assist -> customer_image_brain_bridge`。
- `listen_and_reply.py` 是否只增加图片 pending 分流和少量上下文透传。
- Brain 是否仍只接收 `visual_bridge_input`，没有被改造成多模态主入口。

### 11.2 数据安全审计

- 文件路径是否 tenant 隔离、session 隔离。
- 元数据是否包含 `session_key/message_id/speaker_name`。
- A 会话图片是否不可能被 B 会话读取。
- 资产清理是否只清理 image asset 目录，不递归误删 runtime 根目录。

### 11.3 回复所有权审计

- 识图模块不返回客户可见话术。
- 保存失败不返回本地模板话术。
- 商品价格、库存、车况仍只能由 product master/formal knowledge 授权。
- Final polish 仍只轻量自然化，不能替 Brain 改事实或策略。

### 11.4 RPA 安全审计

- 右键、保存对话框、输入文件名之前都要确认微信窗口和目标会话。
- 保存路径输入必须使用绝对路径。
- 操作完成后关闭菜单/对话框，避免影响后续发送。
- 图片保存动作不能向聊天窗口输入任何文本。
- 点击右键菜单项时优先使用屏幕坐标点击，避免重新激活主窗口导致菜单弹层消失。

## 12. 设计审计结论

按以上方案开发，闭环补的是“微信图片成为本地 image asset”的入口缺口，不会改变现有 Brain First 主结构。

当前方案仍有三类实现风险，需要落代码时重点验证：

- 微信右键菜单文案、剪贴板格式和保存对话框可能随版本变化，必须有 OCR/截图诊断和 fixture 回放。
- 图片气泡定位必须严格区分客户侧/自己侧，否则会出现自发图片误识别。
- `[图片]` pending 必须阻断旧 `monitor_pending` 文本合成，否则仍可能出现“图片没识别，Brain 却回复旧文字”的错位。

只要这三点在测试里卡住，这个方向可以进入落代码阶段。
