# 微信识图消息身份与发送新鲜度修复方案

## 1. 文档目的

本次修复解决同一张图片被重复观测、同一张图片被客户分时发送、以及 Brain 已经产出回复却被后续重复识图误判为过期的问题。

本方案遵循 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：Brain 仍是所有正常客户可见回复的唯一作者。本次只调整代码机制层的消息身份、图片留档、调度状态和发送前新鲜度判断，不改变 Brain 的提示词策略、商品库检索或回复文案。

## 2. 线上问题复盘

一次实测中，前后两次图片元数据的图片 SHA、`asset_id`、`message_id`、气泡位置和 `visual_occurrence_id` 全部相同，但 `captured_at` 不同。后一次只是 RPA 轮询再次看到了屏幕上的旧气泡，却被调度器当成了新的待处理消息，最终触发 `scheduler_send_freshness_stale`，已经生成的回复没有发送出去。

根因是把三类不同概念混在了一起：

1. 图片内容相同，不代表微信消息发生在同一时刻。
2. 程序再次截图，不代表客户又发了一次图片。
3. `captured_at` 是程序观察时间，不是微信消息发生时间。

## 3. 三层身份模型

| 字段 | 含义 | 是否参与去重/新鲜度 |
| --- | --- | --- |
| `asset_id` | 图片文件内容身份，按图片 SHA 生成 | 用于内容复用，不单独代表一次发送 |
| `visual_occurrence_id` | 一次微信图片气泡的业务发生身份 | 参与消息去重、session ledger 和 Brain 输入身份 |
| `pending_signal_id` | 调度器为一次待处理消息生成的事件身份 | 最高优先级，参与跨轮询稳定绑定和发送新鲜度 |
| `wechat_message_time` | 从微信聊天区时间分隔线关联出的消息时间 | 在没有显式事件 ID 时增强发生身份和审计能力 |
| `visual_index` | 同一次采集中多个图片气泡的序号 | 区分同一事件中的多张图 |
| `visual_observation_id` | 某次程序截图/裁剪/保存行为的观察身份 | 仅用于留档和排障，不参与业务去重 |
| `captured_at` | 程序完成截图或保存的时间 | 仅用于性能和审计，不参与消息去重 |

### 身份优先级

`visual_occurrence_id` 的生成优先使用：

1. 显式传入的 `visual_occurrence_id`；
2. 当前待处理事件的 `pending_signal_id`；
3. 微信界面可见的 `wechat_message_time`；
4. 兼容旧数据的图片内容、会话和气泡几何静态组合。

`captured_at` 和 `visual_observation_id` 不进入 occurrence 身份计算，避免 RPA 每次轮询都生成一条“新消息”。

## 4. 事件生命周期

### 4.1 一次真实新消息

1. session monitor 发现新的未读/新预览。
2. `enqueue_pending_session()` 在 `pending_capture` 从 false 变 true 的瞬间生成新的 `pending_signal_id`。
3. 同一 pending 窗口的后续轮询复用该 ID，不因 `last_detected_at` 变化而换 ID。
4. 识图模块收到该 ID，写入图片资产、Brain 安全代理消息和 session ledger。
5. Brain reply 保存其 capture 中的消息身份。
6. 发送前 freshness 读取当前 session 的 pending ID，并与 reply capture 中的 ID 比较。

### 4.2 同一事件的重复观测

如果 reply capture 中出现了当前 `pending_signal_id`，则判定为同一事件的重复观测，直接通过 freshness，不再次 stale，也不重新触发识图闭环。

### 4.3 后续真实新消息

如果 reply capture 中保存了另一个 pending ID，则当前 session 的事件比 reply 更新，freshness 明确判定为 stale，等待新事件的 capture/Brain 流程，不发送旧回复。即使两次发送的图片字节完全相同，也不会混淆。

### 4.4 旧数据兼容

历史 capture 没有 `pending_signal_id` 时继续使用已有的 session-list preview 内容匹配逻辑。新采集从本次版本开始写入显式事件 ID，因此不会让旧数据迁移阻塞运行。

## 5. 微信时间关联

识图采集阶段复用同一张 OCR 截图中的聊天区时间分隔线，只识别位于聊天区中部的 `HH:MM`、昨天/前天/星期时间标记，并把气泡上方最近的时间标记写入 `wechat_message_time`。

时间分隔线不是消息内容，不进入 Brain 的可见文本；它只作为身份增强和审计字段。若 OCR 未识别到时间，仍以 `pending_signal_id` 为准，不因时间缺失而阻塞图片处理。

## 6. 改动范围

### 新增或修改的代码机制

- `adapters/wechat_image_save_capture.py`
  - 识别聊天区时间标记。
  - 让 occurrence 使用事件身份/微信时间和多图序号。
  - 新增 observation 身份和审计字段。
- `adapters/wechat_connector.py`
- `adapters/wechat_win32_ocr_sidecar.py`
- `workflows/customer_image_asset_store.py`
  - 传递 `pending_signal_id` 并保留视觉身份字段。
- `admin_backend/services/customer_service_scheduler_state.py`
  - 管理 pending 事件 ID 生命周期。
- `admin_backend/services/customer_service_scheduler.py`
  - 发送前优先执行 pending 事件 ID 比对。
- `admin_backend/services/customer_service_session_ledger.py`
  - 留存视觉事件和观察字段。

### 明确不改动

- Brain 的层级、调用协议和回复所有权。
- 商品库、商品匹配、意图识别和 final polish 的文案职责。
- 普通文字消息的回复生成逻辑。
- 微信 RPA 的发送行为、真人化拆分和安全等待策略。

## 7. 审计清单

- 同一图片、同一 pending ID、不同 `captured_at`：occurrence 不变，observation 可不同。
- 同一图片、不同 pending ID：occurrence 必须不同，不能被内容 hash 去重吞掉。
- 同一 pending ID 多轮轮询：不会反复进入图片保存/Brain 重算闭环。
- 新 pending ID 到达旧 reply 发送前：旧 reply 必须 stale，不能错发。
- 时间识别失败：不阻塞，仍由 pending ID 提供事件身份。
- 多图同批：`visual_index` 区分图片，且每张图有独立 observation。
- 同一 session 与其他 session：身份和 freshness 不得跨会话匹配。
- 所有新增字段只进入机制层/ledger，不能改变 Brain 的可见回复所有权。

## 8. 验证命令

```powershell
python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_image_save_capture.py apps/wechat_ai_customer_service/adapters/wechat_connector.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler_state.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_session_ledger.py apps/wechat_ai_customer_service/workflows/customer_image_asset_store.py
python apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multimodal_session_context_checks.py
python apps/wechat_ai_customer_service/tests/run_brain_first_static_architecture_audit.py
git diff --check
```

## 9. 重启烟测补充

本次重启发现并修复了一个启动环境问题：管理台在导入 scheduler/customer-image 模块时，listener 的 workflow/adapters 路径 bootstrap 尚未执行，导致 `reply_evidence_builder` 无法加载 `knowledge_loader`。已在该模块增加局部、兼容性的路径 bootstrap，仅修复导入时序，不改变任何业务调用协议或回复逻辑。

重启后验证：

- `http://127.0.0.1:8765/api/health` 返回 `ok: true`。
- `http://127.0.0.1:8766/v1/health` 返回 `ok: true`。
- 未启动微信 AI 客服 listener 和 RPA operator guard。
