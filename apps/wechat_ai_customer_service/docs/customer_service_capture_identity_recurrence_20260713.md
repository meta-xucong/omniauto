# 微信客服会话切换后不回复复盘与采集身份修复

> **2026-07-19 规则更新：** 本文对 capture→Brain→ready reply→send 身份贯穿、禁止按显示名兜底和防串发的复盘继续有效；其中把 `conversation_type` 冲突作为永久物理身份冲突的处理已被 [PR #28 原样合并与独立 Vision 总方案](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)取代。类型现作为可校正语义观测，不能单独否定相同 exact session key + exact title。实施时按[问题台账](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)中的 `SID-001` 至 `SID-008` 逐项验证，不能靠名称 fuzzy 合并。

## 1. 结论

本次问题不是 Brain 没有产出回复，而是会话切换期间出现了两类身份缺口：

1. `许聪` 的 ready reply 携带了 `conversation_type=unknown`，实际活动会话已经确认是 `private`，发送守卫把默认未知值误判成类型冲突。
2. `新数据测试` 的发送目标是 `wx:rpa:v1:178877830fefdaa357d6`，但发送前活动窗口仍确认成 `wx:rpa:v1:ef121d8ed196ccc76c22`（许聪）。系统因此阻止了错发，但此前采集入口只按显示名确认，已经把许聪的 OCR 内容混入了新数据测试的 capture。

这说明问题发生在 `capture -> Brain -> ready reply -> send` 的身份契约没有真正贯穿，而不是单纯的发送按钮故障。

本文遵守 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)。本修复只属于代码机制层，不改变 Brain 的客户可见话术所有权。

## 2. 历史文档对照

- `rpa_session_key_ledger_overflow_backfill_design_20260607.md` 已明确要求 capture、Brain、ready reply、send 全链路携带 `session_key`，并要求同名会话不能只按显示名发送。
- `rpa_multi_session_dispatch_hardening_architecture_20260601.md` 已明确要求 `target_not_confirmed_for_messages` 进入会话级退避，不能连续机械重试。
- `brain_code_mechanism_layer_integration_design_20260609.md` 已明确规定每个 capture、Brain task、ready reply、send 都应携带 `session_key`、`target_name`、`conversation_type` 等机制元数据。
- `customer_service_voice_transcription_context_menu_reliability_20260709.md` 已要求会话类型从 scheduler 传到 sidecar，但当时主要覆盖语音路径，普通 `messages` capture 入口仍保留旧的局部校验。
- `customer_service_session_identity_startup_visual_boundary_20260712.md` 修复了活动目标构建和发送侧身份传递，但当时把采集 sidecar 误视为既有稳定链路，没有覆盖本次暴露的采集前确认缺口。

## 3. 为什么会反复出现

历史修复采用的是分阶段补丁：先修 ledger，再修发送 guard，再修活动目标，再修媒体入口。每一轮局部测试都能通过，但“会话身份包”没有作为一个不可拆分的运行时契约进入所有入口。

具体表现为：

- send 路径有 `session_key`，messages 路径虽然 CLI 接收参数，却没有用 `conversation_type` 做 row 激活和最终确认。
- messages 路径失败后仍可进入 wxauto4 reserve，而 reserve 只理解显示名，存在绕过身份约束的风险。
- scheduler capture 返回值漏掉 `conversation_type`，后续 polish、freshness、send target 重新构造时又回到默认 `unknown`。
- 测试覆盖了 `find_session_candidate_by_key` 和 send guard，但没有真实执行 `run_action(messages)` 的 session-key/type 绑定，也没有断言 reserve 不得接管身份失败。

因此，旧文档的设计结论是正确的，但实现和测试没有把它落实为单一入口契约。

## 4. 本次修复

### Sidecar 与 Connector

- `messages`、`voice-transcribe`、`image-save` 都使用同一套 `session_key + conversation_type` 活动目标确认。
- `unknown` 只表示缺少类型，不再作为实际类型与 `private/group` 比较。
- 活动目标确认失败时，messages/send 不再回退到只按显示名工作的 wxauto4 reserve。
- 已确认的目标类型会强制重新解析会话列表行，避免沿用错误的活动窗口缓存。

### Scheduler

- capture 返回值补齐 `conversation_type`。
- capture、polish、freshness、send target 统一从当前 session/capture/reply 的有效身份构造目标。
- 当采集前目标确认失败时，保留现有 capture cooldown/retry 机制，不把错误窗口内容送入 Brain。

## 5. 验收要求

- 先切到许聪，再切到新数据测试，采集前必须确认对应 `session_key`。
- capture 目标身份不匹配时，不产生有效 messages payload，不调用名称兜底，不创建 Brain task。
- `unknown -> private/group` 不应误阻断；真实 session key 不匹配必须阻断并重试。
- 文字、图片、语音三类入口都必须复用同一套身份确认。
- 同一轮多个会话不能把一个会话的 OCR 内容写入另一个会话 ledger。

## 6. 离线验证

- Win32/OCR 兼容测试：206 项通过。
- 调度器测试：156 项通过。
- 工作流逻辑测试：125 项通过。
- Brain 合同、Brain First 架构审计：通过。
- `py_compile`：通过。

本次修复后暂未重启微信客服做第二次实盘验证；当前进程已由用户手动停止。
