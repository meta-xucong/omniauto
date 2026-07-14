# 微信会话观测与新消息事件去重修复（2026-07-14）

## 0. 基线与适用范围

本文件修复 Windows 微信会话列表中“同一条未读状态被每轮 OCR 当成新消息”的根因，适用于 `apps/wechat_ai_customer_service` 的 Win32/OCR 会话监控、调度和 freshness 链路。

必须同时遵守：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：本改动只改变 RPA/调度正确性；`customer_service_brain` 仍是唯一客户可见回复作者。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：只作可选视觉/核心调度的加性元数据扩展；不让核心加载视觉实现，也不改变 Brain、RPA、语音或外部调用方既有合同。

不修改产品主数据、知识库、Brain 回答策略、聊天内容或发送接口。

## 1. 故障根因

现场事件中，同一客户预览文本和同一未读标记在数秒轮询内持续出现。`SessionMonitor` 正确地把 `unread_detected` 保留为“尚未处理”的**状态**；但 `record_session_signal` 错误地把这个状态本身作为“本轮有新消息”的**事件**。每轮都会创建一个带当前时间的新 `pending_signal_id`。旧回复引用旧 ID，发送前 freshness 看到新 ID，遂错误报 `scheduler_pending_signal_mismatch_before_send`，反复捕获而不发送。

根因不是 Brain、历史上下文或消息识别文本，而是三个层次混淆了：

```text
OCR 再读同一行  ≠  新的侧边栏观测  ≠  新的客户消息事件
```

## 2. 修复后的契约

### 2.1 Sidecar：稳定观测身份与可审计红点证据

`wechat_win32_ocr_sidecar` 对每个会话行新增：

- `session_observation_id`：由会话键、预览、时间、未读标记、相对红点框和行身份确定性计算；不含轮询时间、截图路径或临时文件。
- `unread_badge_evidence`：红点边界、连通像素数量和检测原因；`bbox` 是 `red_box` 的兼容别名。

它们只属于内部 RPA 观测，不进入客户可见内容，不保存截图内容，也不作为 Brain 事实证据。

### 2.2 Monitor：状态、事件与确认分离

持久化的 `SessionState` 新增（均为可选/加性）：

- `last_observation_id`：最后读到的原始侧栏观测；
- `pending_observation_id`：当前待处理事件；
- `acknowledged_observation_id`：捕获完成后确认过的事件；
- `last_observed_unread_badge`、`unread_badge_epoch`：识别“红点消失后重新出现”的真实边沿。
- `acknowledged_unread_badge_epoch`、`candidate_observation_id`、`candidate_preview_hits`：红点持续存在时，隔离一次性 OCR 预览修正；文本变化须在连续两次相同观测中确认后，才可能作为同一红点周期内的新事件。

`reset_unread` 在成功处理后确认当前 `pending_observation_id`，但不抹掉对物理红点的最后观测。因此同一个仍显示的红点不会复位为新事件；红点先消失、后重新出现时，epoch 会产生新的事件身份，即便微信预览文字和分钟相同。

### 2.3 Scheduler：以事件身份去重，保留旧调用兼容

`record_session_signal` 优先读取 `pending_observation_id` / `session_observation_id`：

- 同一身份再次上报只刷新观察，不新建 `pending_capture`，不更换 `pending_signal_id`；
- 新身份才创建/替换 pending window；
- 不带新字段的旧调用仍按摘要、时间、未读标记走兼容路径；首次未读仍能触发捕获；
- `unread_detected` 不再单独作为每轮都为真的“新消息”证据。

`enqueue_pending_session` 在有观测事件时，以该事件生成确定性 `pending_signal_id`；没有事件身份时保留原先的时间窗口 ID。捕获时调度器把自己拥有的 ID 注入待处理信号，使捕获批次与 freshness 使用同一个 ID，不能再因 Monitor 的轮询时间重新计算出第二个 ID。

## 3. 不变量

1. 同一 `pending_observation_id` 在 capture、Brain、polish、send 期间可重复被观测，但不得产生新的 pending window。
2. 只有不同观测身份、或同一行红点“消失→重现”的新 epoch，才可使旧回复过期。
3. 捕获失败、空捕获和人工确认保留既有 retry 规则；确认前 pending 仍可持续。
4. 已处理的同一物理红点不会因 `reset_unread` 清空展示状态而被再次触发。
5. 已确认红点周期内，单次 OCR 文本抖动不会重新触发；相同的新预览需通过连续观测确认。时间变化或“红点消失→重现”仍是立即可判定的新事件。
6. 所有新增字段为内部、可选、可忽略的元数据；历史持久化文件可直接读取。
7. 任何 freshness 判定只控制发送安全，绝不生成、替换或拼接客户可见回复。

## 4. 回归验证

新增/加强回归覆盖：

- 同一红点在确认后仍保持显示，不再重新派发；
- 已确认红点周期内出现一次 OCR 文本修正，不会重新派发；
- 红点消失后重新出现，仍可正确派发新事件；
- 复现现场“同预览、同时间、同未读”的 capture 完成后重复轮询，断言只入队一次、ID 不改变；
- 真实后续观测身份到来，断言创建新 ID；
- 侧边栏红点输出 `bbox` 和稳定 `session_observation_id`。

执行：

```powershell
python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
```

## 5. 运维观察点

若再遇到“不回”，优先检查 scheduler event 中同一 `session_key` 的：`pending_signal_id`、`pending_observation_id`、capture 批次中的 `pending_signal_id`，以及 monitor state 中的 `acknowledged_observation_id`。同一稳定观测若反复产生不同事件 ID，才视为回归缺陷；不要通过缩短上下文、关闭 freshness 或加入本地回复模板来绕过。
