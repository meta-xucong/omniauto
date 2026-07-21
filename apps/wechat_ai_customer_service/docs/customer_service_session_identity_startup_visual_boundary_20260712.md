# 微信客服会话身份与启动视觉基线修复

> **2026-07-19 规则更新：** 本文关于 `session_key` 贯穿 capture/Brain/reply/send、exact title、候选唯一性和防串发的要求继续有效；把 `conversation_type` 当成不可变永久身份、类型不一致即否定同一会话的结论已被 [PR #28 原样合并与独立 Vision 总方案](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)取代。新规则以已签发 exact session key + exact title 作为物理身份，conversation type 是可被更可靠结构证据校正的语义属性；key/title 不匹配或候选歧义仍必须 fail-closed。逐项迁移见[问题台账](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)。

## 1. 目标与边界

本次修复针对双会话并发实测中出现的“回复看起来串号”和“重启后历史图片再次触发”风险，只改代码机制层：会话身份传递、RPA 发送前守卫、监听器启动首轮视觉预览基线和审计字段。

本方案必须遵守 [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：所有客户可见文字仍只能由 `customer_service_brain` 产生。本次不修改 Brain prompt、商品库、识图专用模块、意图判断、final polish 策略或 RPA 真人化发送节奏。

## 2. 实测证据

本次两会话运行中：

- “许聪”的图片任务和短消息任务都绑定 `wx:rpa:v1:ef121d8ed196ccc76c22`，两条已完成发送的 RPA 守卫均确认目标为“许聪”。
- “新数据测试”私聊任务绑定 `wx:rpa:v1:178877830fefdaa357d6`，在用户停止前才进入 `sending`，没有 `scheduler_send_completed`。
- 同时存在“新数据测试”群聊和私聊两个不同 `session_key`，仅依赖显示名称存在同名会话风险。
- 底层发送调用虽然已经携带 `session_key`，但没有把 `conversation_type` 传到 send sidecar；活动窗口强校验主要仍是标题名称。

因此本次既修复已经确认的身份传递缺口，也把潜在错发路径改为 fail-closed：目标身份无法确认时不发送，不把消息发送到另一个会话。

## 3. 会话身份契约

客户服务回复的目标身份必须同时携带：

| 字段 | 用途 | 规则 |
| --- | --- | --- |
| `target_name` | UI 标题和白名单显示名 | 不能单独授权发送 |
| `session_key` | 唯一会话/列表行身份 | Brain task、capture、reply、RPA 全链路保持不变 |
| `conversation_type` | `private`、`group` 等会话类型 | 参与同名会话候选行筛选和审计 |

发送前必须满足：

1. ready reply 与 capture 的 `target_name`、`session_key`、`conversation_type` 一致。
2. connector 将 `session_key` 和 `conversation_type` 传到 Win32/OCR sidecar。
3. sidecar 使用 `session_key` 找到会话列表行，并在类型不一致时拒绝激活。
4. 激活后再次确认活动会话缓存中的 `session_key`；只有标题相同但唯一会话身份未确认时，必须拒绝发送。
5. 发送结果和 guard 审计中保留 requested/confirmed session identity。
6. 多会话监听器把活动会话转换为发送目标时，必须保留 `session_key` 和 `conversation_type`；活动会话合并也只能按会话身份合并，不能按显示名合并。

## 4. 启动视觉基线

监听器每次进程启动后的首轮 session-list 观察建立视觉基线：

- 仅有 `[图片]`、`[语音]` 等媒体预览，且没有未读角标证据时，首轮只更新基线，不切换会话、不触发 Brain。
- 该基线写入 `startup_visual_baseline_at`，用于事后解释为什么没有把历史可见媒体当成新消息。
- 有未读角标的媒体预览仍然进入既有图片/语音捕获链路。
- 低风险模式已有的“角标被人工点掉但运行中媒体预览发生变化”路径保持不变，不被启动基线覆盖。
- 原始图片资产仍然可以按现有规则留档；本规则只控制是否触发本轮回复工作。

这是一条保守边界：重启瞬间已经被人工读掉、且没有任何未读/事件证据的历史媒体可能不会自动触发回复；这是为了避免重启后把旧图片再次当作新客户消息。

## 5. 代码改动清单

- `workflows/listen_and_reply.py`
  - `TargetConfig` 增加 `conversation_type`。
  - 普通回复、拆分回复和限流通知发送均传递会话类型。
  - 活动会话构建发送目标时保留 `session_key + conversation_type`，同名会话按身份合并。
- `admin_backend/services/customer_service_scheduler.py`
  - 从 session-bound target 构建带 `session_key + conversation_type` 的 TargetConfig。
- `adapters/wechat_connector.py`
  - send/send-and-verify 增加 `conversation_type` 参数和 sidecar 参数传递。
- `adapters/wechat_sidecar_runner.py`
  - send/smoke 路径传递 `conversation_type`。
- `adapters/wechat_win32_ocr_sidecar.py`
  - 按 session key 和 conversation type 解析会话行。
  - 发送前确认活动 session key/type；身份不完整时 fail-closed。
  - 保留旧测试/兼容调用的可选参数行为，不改变旧 CLI 名称。
- `admin_backend/services/session_monitor.py`
  - 增加启动媒体基线和 `startup_visual_baseline_at` 审计字段。
- `tests/run_customer_service_multi_session_scheduler_checks.py`
  - 增加启动历史媒体基线与带未读证据新媒体回归。
- `tests/run_wechat_win32_ocr_compat_checks.py`
  - 增加同名会话按 session key/type 解析回归。

## 6. 明确不改动

- 不增加新的 Brain 层级，不改变现有 Brain、识图专用模块或商品库结构。
- 不新增客户可见兜底文案，不改变 Brain First 回复所有权。
- 不改变图片保存、豆包识图、语音右键转文字和已有 session ledger 结构。
- 不改变 RPA 发送拆分、延迟、点击和防风控保险策略。
- 不改变普通文字消息的识别和回复逻辑；只增强目标身份校验。
- 不增加额外运行时层级；活动会话身份增强仍属于现有代码机制层。

## 7. 审计清单

- 不同 session key、相同显示名：发送目标不能互相覆盖。
- 相同 session key、错误 conversation type：sidecar 不得找到并激活错误行。
- 活动标题匹配但 active session key 不匹配：必须阻断发送。
- 新图片带未读角标：仍能进入图片捕获和 Brain 规划。
- 启动首轮旧图片无未读证据：只建立基线，不产生 Brain task。
- 运行中角标清除的语音/图片预览变化：原有 capture-only 信号继续工作。
- 发送失败或身份未确认：不生成本地客户可见替代文案。
- Brain、商品库、识图和普通文字链路的测试保持通过。

## 8. 验证命令

```powershell
python -m py_compile apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py apps/wechat_ai_customer_service/admin_backend/services/session_monitor.py apps/wechat_ai_customer_service/adapters/wechat_connector.py apps/wechat_ai_customer_service/adapters/wechat_sidecar_runner.py apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/workflows/approved_outbound_send.py apps/wechat_ai_customer_service/workflows/customer_service_loop.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py
python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_brain_contract_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multimodal_session_context_checks.py
python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py
python apps/wechat_ai_customer_service/tests/run_brain_first_static_architecture_audit.py
git diff --check
```
