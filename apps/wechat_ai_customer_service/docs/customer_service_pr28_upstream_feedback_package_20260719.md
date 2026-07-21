# 微信客服 PR #28 上游问题反馈包（2026-07-19）

> **当前状态（2026-07-21）：历史上游反馈包。** 不删除其中的证据和建议；当前代码状态请以 [PR #28 / Vision 残留问题收口索引](customer_service_pr28_residual_issue_closeout_20260721.md) 为准。

## 1. 用途与不可突破边界

本文把 PR #28 原样合并后仍需由上游作者复核的问题，整理为可逐项引用的反馈包。它与以下基线共同生效：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)
- [customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)
- [customer_service_pr28_post_merge_issue_audit_ledger_20260719.md](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)

本地遵守以下原则：

1. PR head `2120f16744aebe3d8edbdf9c3f407375bfeed279` 的七个文件保持字节级不变。
2. 本地兼容只放在 PR 文件之外；它是临时 containment，不代表上游根因已关闭。
3. 不改现有跨模块接口、字段、错误码和返回结构。
4. 不用会话名、车型、账号或客户措辞做结构化特判。
5. exact session key、exact title 和候选唯一性仍是发送硬边界；不会降级为按名称发送。
6. Vision 是独立可选模块，PR Connector/Sidecar 的旧图片能力不再作为生产回退。

## 2. 审计基线和复现提交

| 项目 | 值 |
| --- | --- |
| PR head | `2120f16744aebe3d8edbdf9c3f407375bfeed279` |
| PR parent | `378cc3f7b3b24e88ff8d9f145c185bb5c48d509c` |
| 独立 Vision 检查点 | `b576844b787fce4dfeeebdd08b1111544a1ad90b` |
| PR 原样 merge commit | `f678edb6dac5340dc86e4a84500115af3e2f27b8` |
| 本地外围适配 commit | `94638305` |
| Brain 角色连续性/内部路由隔离 commit | `e3db0c0f` |
| PR blob 门禁 | 7/7 精确一致 |
| 本地有效 OCR | 229/229 |
| 本地有效 Window Planning | 28/28 |
| 多会话 Scheduler | 189/189 |
| 外部合同 | 3/3 |
| Vision 绝对边界 | 7/7 |

七个 PR 文件及 blob：

| 文件 | blob |
| --- | --- |
| `adapters/wechat_connector.py` | `00e1da58a982265556394e7b19271bd5bcec545f` |
| `adapters/wechat_win32_ocr/text_normalization.py` | `7a09c6ddd2d218ee941686f4985cc2f184f03a4d` |
| `adapters/wechat_win32_ocr_sidecar.py` | `dc015f4a6b5f28d6e11017ab9665eb1e86a41910` |
| `tests/run_wechat_win32_ocr_compat_checks.py` | `f55fcee1a9b702e09415688735af363246f71fe0` |
| `tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py` | `0832a0be250093ef3c8384d6c0296b50f9d2b4c8` |
| `tests/run_wechat_win32_ocr_window_action_planning_checks.py` | `a0efe8031f79165654b97185e0ed94d84919033b` |
| `wechat_message_envelope.py` | `3c81ea47717b67ea3b82d9224fc7d83941eed722` |

## 3. 上游问题摘要

| Issue ID | 级别 | 上游需要确认的根因 | 本地当前处理 |
| --- | --- | --- | --- |
| `PR28-RPA-001` | P1 | fixed-origin 默认值与 PR 自带测试矛盾 | PR 外环境适配 |
| `PR28-CONTRACT-001` | P1 | 九个 Sidecar callable 新增可选参数 | 精确快照并保留旧调用 |
| `PR28-IMG-001` | P2 | Sidecar 仍包含旧图片实现和依赖 | 生产入口隔离 |
| `PR28-IMG-002` | P2 | 图片 action 半退役、入口生命周期不一致 | 不恢复、不调用 |
| `PR28-IMG-003` | P1 | Connector 仍拥有旧剪贴板图片事务 | runtime adapter fail-closed |
| `SID-001/002` | P1 | key/title 已一致时，type 漂移仍在末端阻断 | 物理边界不再用 type 过滤 |
| `SID-003/004` | P1/P2 | key seed 漂移和 stale key rebind 生命周期 | 保留旧 key，不做名称猜测 |
| `SID-005` | P1 | 已打开目标仍可能被强制重新定位/点击 | 真实手测前保持风险开放 |
| `SID-007/008` | P1/P2 | 缺少 private→group 全链路回归，测试锁定 provisional 推断 | PR 外增加通用 fixture |
| `SCHED-001` | P1 | 多会话观察与窗口动作可能导致饥饿 | 本地 189 项调度回归 |
| `SEND-001` | P1 | staged/dispatched/confirmed 发送状态需分离 | 不明状态 fail-closed |
| `RPA-BEHAVIOR-001` | P1 | 高频重复动作可能导致掉线/踢下线 | 有界节奏、互斥和真实长测门禁 |

## 4. 逐项反馈

### 4.1 `PR28-RPA-001`：fixed-origin 默认值与原生测试冲突

- `Affected PR files`：Sidecar、OCR compatibility test、window action planning test。
- `Minimal reproduction`：清除 `WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN` 后原样运行两组 PR 测试。
- `Observed`：Sidecar 默认 `False`，窗口从 `(-180, 80)` 得到 `(0, 80)`；测试却断言 `(0, 0)`，两组都在同一规则失败。
- `Expected invariant`：默认值、测试预期和生产窗口坐标策略必须一致；显式用户配置优先。
- `Local containment`：仅在调用者没有显式设置时，通过 PR 外 Connector `env_overrides` 注入 `1`。
- `Upstream request`：明确产品默认策略并统一实现与测试；若改变默认值，补迁移说明和显式 false 回归。
- `Positive tests`：缺省配置 229/229、28/28。
- `Negative tests`：显式 `0/false` 不被覆盖；非目标窗口不移动；已在正确位置时无多余动作。

### 4.2 `PR28-CONTRACT-001`：九个 Sidecar 函数新增参数

- `Affected callable`：`capture_message_history_snapshots`、`capture_message_history_snapshots_until_anchor`、`consume_recent_target_switch_validation`、`dismiss_voice_transcribe_context_menu`、`messages_payload`、`open_chat`、`parse_messages_from_ocr`、`validate_active_send_target`、`voice_transcribe_payload`。
- `Observed`：九个签名新增 keyword-only 可选参数；旧调用可运行，但反射合同发生变化。
- `Expected invariant`：每项参数必须标注 public/private、默认语义、兼容窗口和删除策略。
- `Local containment`：合同快照记录 PR 精确签名，继续验证旧必填参数和返回形状；本地不借此扩张跨模块字段。
- `Upstream request`：逐项确认是否是有意公开扩展；公开则补文档/合同测试，私有则收束导出面。

### 4.3 `PR28-IMG-001/002/003`：旧图片能力残留与双所有者

- `Affected PR files`：Connector、Sidecar。
- `Observed`：PR 原样树仍含旧 image clipboard transaction、图片 action/dispatch 和依赖；部分 action 处于入口不完整状态。
- `Expected invariant`：图片理解和当前剪贴板事务由独立 Vision 插件唯一拥有；OCR/窗口层最多暴露中性桌面原语。
- `Local containment`：PR 旧图片方法返回 `pr28_legacy_image_entry_quarantined / vision_owned_transaction_required`；Vision 生产链不调用它们。
- `Upstream request`：先审计未知消费者，再用独立提交完整退役旧图片事务，或把确需保留的部分降为无图片语义的原子操作；不要在 OCR PR 内重建 Vision。
- `Compatibility`：不得重引入历史 CLI route；第三方 Vision 可替换；Vision 缺失不影响核心和 Voice。

### 4.4 `SID-001/002`：物理身份与语义类型混为一个硬谓词

- `Minimal reproduction`：侧栏初判 `private`，打开聊天区后结构确认 `group`；exact issued key 和 exact title 均不变。
- `Observed`：capture/Brain/polish 可以完成，最终 send guard 因 `conversation_type_not_confirmed` 阻断。
- `Expected invariant`：已签发且唯一的 key + exact title 是物理身份；更可靠结构观测可以校正 type。key/title 不一致或候选歧义仍必须阻断。
- `Local containment`：已存在 session key 时，仅从 PR 物理调用过滤器移除 type；共享载荷中的原字段和值不改名、不删除。
- `Upstream request`：在 PR 内明确拆分 physical identity 与 semantic type，所有 capture/reacquire/send 阶段复用同一物理谓词。
- `Negative tests`：错 key、错 title、同名多候选、过期 key 无唯一映射必须 fail-closed。

### 4.5 `SID-003/004/005`：key 漂移、rebind 和重复 UI 动作

- `Observed`：key seed 可能受 type/row fingerprint 影响；stale re-acquire 后存在新旧 key 生命周期不清；已知 type 可能触发强制 row resolution。
- `Expected invariant`：同一物理会话的 key 跨合法 UI 变化稳定；任何 rebind 都返回可审计旧→新映射；已经无动作确认正确的活动会话不再点击。
- `Local containment`：不覆盖旧 key、不按名称 fuzzy 重建；真实 UI 长测未完成前问题保持开放。
- `Upstream request`：提供稳定 key seed/向后映射、明确 rebind return contract，并把“只读确认”和“执行点击”拆开。
- `Tests`：重启、排序变化、侧栏滚动、未读变化、同会话连续两条、两会话交替、窗口失焦、同名私聊/群聊。

### 4.6 `SID-007/008`：缺少结构校正的完整回归

- `Observed`：PR 测试可把无群标记标题 provisional 推断为 private，但没有贯穿 `private → header group → Brain → send` 的完整路径。
- `Expected invariant`：显示名推断只能是 provisional；结构证据可校正语义，不能重新签发错误物理会话。
- `Local containment`：PR 外适配和多会话测试覆盖 key/title/type 投影，但真实微信证据仍待补。
- `Upstream request`：新增通用 fixture，不写具体账号标题特判；同时包含 key/title 错误负例。

### 4.7 `SCHED-001 / SEND-001 / RPA-BEHAVIOR-001`：联合实机复核项

这些问题未被归因成某一个 PR 函数，需由双方用相同 trace 联合复核：

- 每个新消息会话必须有独立 `capture → plan → ready → reacquire → send` 进度；一个慢会话不得饿死其他会话。
- 发送必须区分 `staged`、`action_dispatched`、`outgoing_occurrence_confirmed`；确认不明不得盲目重发。
- 同一目的 UI 动作不得重复；全局互斥、自然有界间隔、失败退避、登录态熔断均需可观测。
- 自问自答仍走正常规则，不通过禁用测试会话规避平台行为问题。

建议上游补充只读 observation/action trace，不改变现有外部返回字段；本地通过兼容 audit 字段或日志关联，不把内部状态写入客户可见消息。

## 5. 上游修复后的验收顺序

1. 记录上游 commit SHA，并逐项引用 Issue ID。
2. 独立运行该 issue 的最小复现和负例。
3. 合入后重新验证七个目标文件的新 blob，不再沿用旧 head 结论。
4. 运行 OCR compatibility、window planning、sender-role replay。
5. 运行外部合同、Vision 插件矩阵、Vision 唯一 owner、Scheduler 及 Brain 所有权测试。
6. 真实微信测试普通私聊、群聊、双会话交替、连续追问、双方图片、同名歧义和掉线恢复。
7. 只有上游修复、合并和真实场景均通过，才从 `UPSTREAM_FIXED` 依次推进到 `MERGED_AND_RETESTED`、`CLOSED`。

本地外围 guard 在上游修复后不自动删除。需先证明移除 guard 不改变外部合同、不恢复旧 Vision 路径、也不降低 key/title/唯一性门禁，再用独立提交清理。
