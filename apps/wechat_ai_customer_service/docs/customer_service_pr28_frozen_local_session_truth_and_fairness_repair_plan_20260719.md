# PR #28 冻结条件下的本地会话真值与调度隔离修复开发文档

状态：第一阶段离线验收完成；启动交接与旧 pending 闭环已由 [customer_service_pr28_frozen_startup_handoff_and_stale_pending_root_repair_20260719.md](customer_service_pr28_frozen_startup_handoff_and_stale_pending_root_repair_20260719.md) 完成修正与最终验收；本文不能单独作为手测通过依据  
日期：2026-07-19  
适用范围：`apps/wechat_ai_customer_service` 的非 PR 会话监听、调度、捕获闭环  
明确不包含：PR #28 的 OCR 会话行解析缺陷及其任何源码修正

## 1. 强制基线

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)
- [customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)
- [customer_service_pr28_post_merge_issue_audit_ledger_20260719.md](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)

本方案属于代码机制层修复，不改变 Brain First、商品库、正式知识、客户可见回复所有权、Vision 独立性或 RPA 发送目标确认规则。

核心规则：

1. 客户可见回复只能由 `customer_service_brain` 创作。
2. 会话列表预览只能唤醒检查，不能作为客户消息事实。
3. 一个会话失败、变慢或身份无效，不得阻塞其他会话。
4. 不增加客户名、会话名、车型、问法、话术或数字角标等结构化特判。
5. 不增删、改名或改变现有模块接口、参数、返回字段、状态文件路径、配置键和外部错误语义。
6. 不修改 PR #28 的任何内容。

## 2. PR #28 字节级冻结边界

冻结基线：PR head `2120f16744aebe3d8edbdf9c3f407375bfeed279`。

下列七个文件禁止修改，包括源码、注释、格式、测试和换行：

1. `apps/wechat_ai_customer_service/adapters/wechat_connector.py`
2. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py`
3. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
4. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
5. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py`
6. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py`
7. `apps/wechat_ai_customer_service/wechat_message_envelope.py`

当前冻结 blob：

| 文件 | PR #28 blob |
|---|---|
| `wechat_connector.py` | `00e1da58a982265556394e7b19271bd5bcec545f` |
| `text_normalization.py` | `7a09c6ddd2d218ee941686f4985cc2f184f03a4d` |
| `wechat_win32_ocr_sidecar.py` | `dc015f4a6b5f28d6e11017ab9665eb1e86a41910` |
| `run_wechat_win32_ocr_compat_checks.py` | `f55fcee1a9b702e09415688735af363246f71fe0` |
| `run_wechat_win32_ocr_sender_role_screenshot_replay.py` | `0832a0be250093ef3c8384d6c0296b50f9d2b4c8` |
| `run_wechat_win32_ocr_window_action_planning_checks.py` | `a0efe8031f79165654b97185e0ed94d84919033b` |
| `wechat_message_envelope.py` | `3c81ea47717b67ea3b82d9224fc7d83941eed722` |

实施前后必须分别执行 `HEAD` 与 `2120f167` 的逐文件 blob 比对。任一文件不同，立即停止交付，不允许用“功能测试通过”代替字节级验收。

## 3. 本方案只修复的两个本地问题

### 3.1 LOCAL-RUNTIME-01：异常目标拖死整个多会话队列

现场事实：

1. 上游会话列表曾输出两个无法打开的候选目标。
2. Scheduler 对每个目标进行有限次捕获，最终将其标为 `capture_failed`，并把 `pending_capture` 设为 `false`。
3. 捕获异常或 `blocked` 分支没有经过正常的 `_capture_done()`，因此 SessionMonitor 没有确认或推迟相同观测。
4. SessionMonitor 继续保留这些目标的 `unread_detected=true`。
5. `select_dispatch_targets()` 在候选仍有效时先按优先级截取小批量目标；异常目标持续占据前排。
6. Scheduler 已经拒绝再次捕获相同观测，但 Monitor 仍持续把它们作为最高优先级目标提交。
7. 真实会话虽然已在侧栏被发现，却无法进入捕获阶段。

该问题与上游为何产生异常候选无关。任何连接器、OCR、第三方实现或暂时消失的会话都有可能提供无法确认的目标；本地调度必须具备故障隔离能力。

### 3.2 LOCAL-RUNTIME-02：侧栏预览被伪造成客户消息

现场事实：

1. 某会话没有未读红点，也没有捕获到新的聊天区气泡，真实结果为 `messages=[]`。
2. 我方刚发送的文字改变了侧栏预览。
3. 最近 outbound 预览匹配因 OCR 截断、重复或标点漂移而未命中。
4. 稳定两次的无角标预览变化被提升为待处理信号。
5. `recover_pending_signal_batch_from_monitor()` 把该预览合成为 `sender=unknown` 的 `monitor_pending:*` 文本。
6. 合成文本进入 Brain，导致系统对自己的上一条回复再次作答。

侧栏预览本身不是消息气泡，也不具备可靠的发送方向、完整正文和 occurrence 身份。无论它与最近 outbound 是否相似，都不能成为回复事实。

## 4. 明确不在本方案修复的内容

以下内容仅作为异常输入和联合测试条件，不在本方案中修改：

- PR 增强 OCR 把数字角标识别成会话标题。
- PR 的会话标题横向区域、行聚类和增强 OCR 合并算法。
- PR 的 Connector、Sidecar、Envelope、OCR 原生测试。
- PR 中已登记的会话类型、session key 漂移或 C2 目标定位问题。

本方案不得以外围名称黑名单、纯数字过滤或特定坐标补丁伪装成对 PR 问题的修复。上游错误仍由同事在 PR 后续版本中根治。

## 5. 修复后的硬不变量

### 5.1 调度活性

1. 同一时刻只要存在一个可处理的真实待办会话，有限轮次内必须至少有一个真实会话进入捕获。
2. 一个目标处于捕获冷却期时，不得占用本轮有限调度名额。
3. 一个目标对同一观测达到终止失败状态后，不得继续出现在可调度集合中。
4. 只有不同的 `pending_observation_id` / `session_observation_id` 才能重新获得捕获预算。
5. 一个会话的 OCR、Vision、Brain、polish 或发送变慢，不得停止其他会话的 Monitor 轮询和独立推进。

### 5.2 客户消息真实性

1. 侧栏 `content/time/unread_badge` 只用于发现和排序，不是客户正文。
2. 回复任务必须至少包含一个来自当前目标聊天区捕获的、通过现有角色与批次选择规则的真实 occurrence。
3. 当聊天区捕获为 `messages=[]` 或没有回复合格 occurrence 时，不得用侧栏预览补造 Brain 输入。
4. `monitor_pending_synthesized_from_preview` 和 `short_pending_synthesized_from_monitor` 不能成为客户运行时的回复锚点。
5. 我方文字和图片仍按既有方向进入 ledger/context；除现有显式自测模式外，不得形成客户回复任务。
6. 客户真实发送与我方上一条完全相同的文字时，只要聊天区捕获证明它是新的客户 occurrence，就必须正常回复；不得按内容相似度误删。

### 5.3 失败安全

1. 未能证明客户发了什么时，不发送猜测回复。
2. 空捕获可进行有限、带退避的重新确认，但不得无限重试或永久占队。
3. 达到有限重试上限后，只关闭该次观测并留下内部审计；不得影响其他会话。
4. 新观测到来后正常重新入队，不得永久屏蔽会话。

## 6. 目标内部结构

不替换现有框架。在非 PR 区域增加一个纯内部、无 OCR/Vision/Brain 依赖的协调模块：

```text
PR Connector.list_sessions()  （原样）
              ↓
SessionMonitor.poll()          （保留现有外部接口）
              ↓
本地观测/调度协调器             （新增私有纯逻辑）
  - 对照 Scheduler 现有状态
  - 暂缓冷却中的相同观测
  - 确认终止失败的相同观测
  - 不解析名称或消息内容
              ↓
SessionMonitor.select_dispatch_targets()
              ↓
Scheduler capture              （现有字段不变）
              ↓
聊天区真实消息真值门
  ├─ 有真实回复合格 occurrence → Brain
  ├─ 只有我方 occurrence       → 只记录上下文
  └─ 空捕获/只有侧栏预览        → 有限复核，不进入 Brain
```

建议新增内部文件：

`apps/wechat_ai_customer_service/admin_backend/services/session_runtime_reconciliation.py`

该文件只处理现有状态的只读比较和候选分区，不拥有 SessionMonitor/Scheduler 状态，不定义新的对外 payload，不导入 PR Sidecar、Vision、Voice、Brain 或商品库。

## 7. LOCAL-RUNTIME-01 详细修复设计

### 7.1 使用现有观测身份闭环

现有两侧已经具备可用字段：

- SessionMonitor：`pending_observation_id`、`session_observation_id`、`retry_not_before`。
- Scheduler session：`pending_observation_id`、`last_session_observation_id`、`status`、`pending_capture`、`risk_state.capture_retry_not_before`。

禁止新增跨模块字段。协调器只比较现有 session key 和 observation id。

同一观测的判定顺序：

1. session key 必须精确一致。
2. Scheduler 和 Monitor 的非空 observation id 必须一致。
3. 任一身份缺失或歧义时，不执行跨状态确认，保持 fail-closed。
4. 禁止仅凭显示名模糊合并两个会话。

### 7.2 冷却目标让路

在 `_collect_session_signals()` 中：

1. 先调用现有 `SessionMonitor.poll()` 更新侧栏观测。
2. 在调用 `select_dispatch_targets()` 之前读取 Monitor 的全部待办和 Scheduler 当前状态。
3. 对相同 observation、Scheduler 状态为 `capture_cooldown` 且重试时间未到的目标，使用现有 Monitor 待办退避能力暂缓该目标。
4. 暂缓后再执行现有 sticky/fair dispatch 选择。
5. 被暂缓的目标不占本轮数量上限，后面的正常会话自动补位。

不得通过提高 `max_targets_per_iteration` 掩盖问题。扩大上限只能推迟饥饿，不能建立隔离。

### 7.3 终止失败观测确认

当 Scheduler 对同一 observation 已满足以下条件：

- `status == capture_failed`；
- `pending_capture == false`；
- 没有未来的 `capture_retry_not_before`；
- observation id 与 Monitor 当前待办精确一致；

则通过 SessionMonitor 已有确认能力关闭这一次待办观测。确认只针对该 observation，不删除会话历史，不删除 ledger，不屏蔽后续新观测。

### 7.4 不依赖成功回调

当前捕获异常和 `blocked` 分支不会进入 `_capture_done()`。本方案不改变 `capture_done_fn` 的签名或既有成功语义，也不要求 PR 回调新事件。

协调在下一次 `_collect_session_signals()` 的调度前完成，因此同时覆盖：

- capture 函数抛异常；
- capture 返回 blocked；
- 进程在失败后重启；
- Monitor/Scheduler 状态从磁盘恢复。

### 7.5 全局 active-work 一致性

协调完成后，已经终止确认的 Monitor 观测不得继续让 managed listener 报告 `scheduler_active_work`。Scheduler 无待办与 Monitor 无可调度待办必须收敛为同一结果。

## 8. LOCAL-RUNTIME-02 详细修复设计

### 8.1 预览保留唤醒权，取消内容授权权

继续允许以下行为：

- 已打开会话没有未读角标时，稳定的侧栏预览变化可以触发一次前台检查。
- outbound 预览匹配可以作为减少无效检查的性能优化。
- 图片/语音提示可以唤醒对应的真实捕获或可选插件观察。

取消以下行为：

- `messages=[]` 时直接用侧栏文字构造客户消息。
- 用 `sender=unknown` 的预览代理进入 Brain。
- 因预览重复确认次数达到阈值，就把预览升级为客户正文。

因此 outbound 模糊匹配即使失败，最多产生一次无效会话检查，不再可能产生客户可见乱回复。

### 8.2 保留兼容函数，切断生产授权

`recover_pending_signal_batch_from_monitor()` 及现有函数签名、导入路径保持不变，不在本次删除或改名。

生产捕获链路不再把该函数产生的 preview-only synthetic item 作为回复合格 batch。客户运行时增加基于既有 provenance 的真实性检查：

- item 必须来自本轮聊天区消息集合或已验证的可选媒体 occurrence；
- 只有 `monitor_pending_synthesized_from_preview` / `short_pending_synthesized_from_monitor`、却没有对应真实 occurrence 的 item 必须从回复 batch 中排除；
- 该排除只依据来源和 occurrence，不依据文字内容、关键词或客户名称。

这是一条数据来源硬边界，不是结构化话术规则。

### 8.3 空捕获统一有界处理

现有 `high_sensitivity_short` 可以无限保留空捕获待办，容易再次造成永久 pending。本方案取消按文本长度或内容类别无限续命，改为统一的有限空捕获政策：

1. 第一次空捕获：短退避后复核。
2. 后续空捕获：按既有上限递增退避。
3. 达到统一上限：确认本次观测，记录未能取得真实消息，不生成回复。
4. 新 observation id：重新获得完整复核预算。

媒体 occurrence 仍由独立可选插件处理，但它也不能无限占据主调度名额；媒体失败必须局部化，普通文字会话继续推进。

### 8.4 自己发送内容的边界

- 我方聊天区文字：保留在历史中，标记现有 self/assistant 方向，不触发客户回复。
- 我方图片：继续由独立 Vision 模块理解并以 context-only 方式记录，不触发客户回复。
- 显式自问自答测试：继续服从现有 `allow_self_for_test` 合同；必须来自真实聊天区 occurrence，不能由侧栏预览冒充。
- 普通客户会话：不因名称、内容或话术特征开放 self 回复。

## 9. 允许修改的文件

预期实施范围仅限：

- `apps/wechat_ai_customer_service/admin_backend/services/session_monitor.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- 新增内部纯逻辑模块 `apps/wechat_ai_customer_service/admin_backend/services/session_runtime_reconciliation.py`
- 新增非 PR 专项测试 `apps/wechat_ai_customer_service/tests/run_customer_service_local_session_truth_and_fairness_checks.py`
- 本文档及非 PR 审计记录

原则上不需要修改：

- `customer_service_brain`
- `listen_and_reply`
- `customer_service_live_safety`
- `optional_plugins/vision/`
- `optional_plugins/voice/`
- RPA 物理发送和目标确认代码

如实施时发现必须扩大范围，先停止并更新本文，不得顺手修改。

## 10. 明确禁止的修法

- 修改 PR 七文件中的任何字节。
- 添加“排除 2、3”或“排除纯数字会话”等特判。
- 添加“杨潇Eve”“许聪”等账号/会话名特判。
- 通过扩大每轮目标数掩盖队列饥饿。
- 关闭所有无角标预览唤醒，导致已打开会话追加消息无法发现。
- 继续使用侧栏预览生成客户正文，只增加更多 outbound 相似度规则。
- 在 Brain prompt 中要求模型猜测预览是不是客户说的。
- 让 Vision、Guard、RAG 或本地模板替客户回复。
- 捕获失败后全局暂停监听或持有 RPA 锁等待人工。
- 为清理状态删除整个 Monitor/Scheduler 状态文件或 ledger。

## 11. 测试先行与验收矩阵

### 11.1 当前缺失的特征测试

现有 Scheduler 单元测试证明了 Scheduler 自己会终止同一失败 observation，但没有验证 SessionMonitor 仍保留该 observation 时的联合行为。

现有 preview 测试只覆盖可正常匹配的 outbound 截断形式，没有覆盖：

- OCR 重复片段；
- 非前缀截断；
- 标点和空格漂移；
- ledger 不可读；
- 实际聊天区消息为空；
- preview-only synthetic 是否进入 Brain。

新增专项测试必须先在当前代码上复现失败，再实施修复。

### 11.2 调度隔离测试

1. 两个高优先级异常目标加两个正常会话：异常目标冷却时正常会话必须补位。
2. 异常目标达到终止失败后，Monitor 的同一 observation 被确认，不再占队。
3. 相同 observation 持续可见：不得重新获得捕获预算。
4. 不同 observation 到来：允许重新捕获。
5. 一个真实会话 capture 抛异常：其他会话继续推进。
6. 一个真实会话返回 blocked：其他会话继续推进。
7. 一个会话 Vision 慢或失败：纯文字会话继续捕获和发送。
8. 进程重启后 Scheduler 终止状态与 Monitor pending 状态自动收敛。
9. Scheduler summary 与 managed-listener active-work 判断一致。
10. 不使用具体的“2”“3”名称；以任意不可确认候选证明通用性。

### 11.3 消息真实性测试

1. 无角标 outbound 预览变化，且可精确匹配 ledger：不回复。
2. outbound 预览被截断、重复、变标点，匹配失败，聊天区为空：仍不回复。
3. ledger 暂时不可读，聊天区为空：不回复。
4. 群聊侧栏预览带成员前缀，聊天区为空：不合成客户消息。
5. 普通短文本侧栏预览，聊天区为空：有限复核后关闭，不无限 pending。
6. 客户真实发送与客服上一条相同的文字：聊天区捕获为新的客户 occurrence，正常进入 Brain。
7. 已打开会话追加真实文字且没有红点：预览唤醒后从聊天区捕获并回复。
8. 我方文字在聊天区被捕获：记录 self，不回复。
9. 我方图片被捕获：Vision context-only 记录，不回复。
10. 显式自测模式的真实 self occurrence 继续按现有规则工作；preview-only 仍禁止。

### 11.4 多会话联合测试

1. 会话 A 出现空捕获，会话 B 有真实文字：B 正常回复。
2. 会话 A 出现异常候选，会话 B/C 同时有新消息：B/C 均能推进。
3. 会话 A 图片识别中，会话 B 追加文字：B 不等待 A 完成才进入捕获。
4. 会话 A 自己发送后的预览变化，会话 B 有客户消息：A 不乱回，B 正常回。
5. 所有任务的 session key、target、capture、Brain input 和 send envelope 不跨会话。

### 11.5 回归测试

至少执行：

- 新增的本地真值与公平性专项测试。
- `run_customer_service_multi_session_scheduler_checks.py`。
- Brain First、回复所有权与多会话防串发测试。
- Core-only、Core+Vision、Core+Voice、Core+Vision+Voice 可选插件矩阵。
- PR 三个原生测试脚本；只能运行，不能修改。
- PR 七文件 blob 校验。
- `git diff --check`。

## 12. 性能与微信行为要求

- 不增加新的 OCR 轮询。
- 不增加 Sidecar 截图次数。
- 不增加前台点击、搜索、键盘或剪贴板操作。
- 调度协调只读取现有内存/状态数据，单轮耗时应为毫秒级。
- 冷却目标提前让路后，前台无效切换次数应下降。
- 空预览不再进入 Brain，减少无效 LLM 调用和自我回复。
- 不通过更快的机械点击提高吞吐；继续服从既有人性化动作、串行 RPA 锁和发送前目标确认。

## 13. 实施阶段

### Phase L0：特征测试

- 固化本次两个故障的非账号化回放。
- 证明当前代码会出现 Monitor/Scheduler 分裂和 preview-only Brain input。
- 校验 PR 七文件基线。

退出条件：新增测试在当前代码上以预期原因失败，且没有触碰 PR。

### Phase L1：调度隔离

- 增加私有 reconciliation 纯逻辑。
- 在目标截断前协调冷却和终止 observation。
- 保留现有 session key、状态字段和调度接口。

退出条件：异常目标不能占满有限队列，正常会话持续推进。

### Phase L2：消息真实性

- 取消 preview-only synthetic item 的生产回复授权。
- 空捕获使用统一有限复核。
- outbound 匹配降级为性能优化，不再承担正确性。

退出条件：所有空聊天区场景均不进入 Brain；真实客户 occurrence 不被误杀。

### Phase L3：联合回归和审计

- 跑完整离线矩阵。
- 审计 Brain/Vision/Voice/RPA 边界。
- 校验 PR blobs、外部合同和状态兼容。
- 不自动启动真实微信客服。

退出条件：全部自动测试通过后，才由仓库所有者决定是否进入受控手测。

## 14. 审计清单

实施完成后逐项回答：

- [x] PR 七文件是否与 `2120f167` 的 blob 完全一致？
- [x] 是否没有新增会话名、数字、车型、问法或话术特判？
- [x] 是否没有修改外部函数签名、字段、路径、配置和默认值？
- [x] 是否只用现有 session key 和 observation id 做跨状态绑定？
- [x] 同一失败 observation 是否不能反复复活？
- [x] 冷却/失败目标是否不再占据有限调度名额？
- [x] `messages=[]` 是否绝不产生 Brain 回复任务？
- [x] outbound 匹配完全失败时是否仍不会自我回复？
- [x] 客户真实重复同一句话是否仍能正常回复？
- [x] 我方文字和图片是否保留上下文方向但不误触发客户回复？
- [x] 一个会话失败时其他会话是否继续推进？
- [x] Vision/Voice 是否仍为互相独立、absence-safe 的可选插件？
- [x] Brain 是否仍是唯一客户可见回复作者？
- [x] 是否没有增加新的 RPA 动作和机械化风险？

## 15. 最终判断

本方案不替 PR 修 OCR，也不隐藏 PR 的异常候选。它修复的是本地系统必须具备的两项通用能力：

1. 面对任意坏目标时，多会话调度仍能隔离失败并保持活性。
2. 面对任意侧栏预览漂移时，只有聊天区真实 occurrence 才能授权客户回复。

这两项修复与具体账号、未读数字、车型、文本内容和 Vision provider 无关；能够在 PR 七文件字节级冻结、外部合同不变和 Brain First 不变的前提下实施。

## 16. 2026-07-19 实施与验收记录

实际变更严格收束在第 9 节允许范围内：

- 新增纯内部协调模块 `admin_backend/services/session_runtime_reconciliation.py`，只按既有 session key 与 observation id 协调 Monitor/Scheduler 状态。
- `session_monitor.py` 复用既有 `retry_not_before` 实现相同观测暂缓，并把所有空聊天区复核统一限制为有限次数。
- `customer_service_scheduler.py` 在截取有限调度目标前完成冷却/终止观测协调；生产捕获不再用侧栏预览合成 Brain 输入；空聊天区进入有界退避，真实 self occurrence 只记录并关闭观测。
- 保留 `recover_pending_signal_batch_from_monitor()` 的原导入路径和签名，仅撤销其在生产客户回复链路中的内容授权。
- 新增专项测试 `tests/run_customer_service_local_session_truth_and_fairness_checks.py`，不修改 PR 测试。

离线验收结果：

- 本地会话真值与公平性专项：7/7 通过。
- 多会话 Scheduler 回归：189/189 通过。
- 外部合同兼容：3/3 通过；可选插件矩阵：7/7 通过。
- Brain 合同、代码机制层合同与 Brain First 静态架构审计：全部通过。
- 当前图片桥接：2/2 通过；图片理解合同：6/6 通过。
- PR runtime adapter：5/5 通过；PR effective runtime：2/2 通过，其中原生 OCR 兼容 229/229、窗口动作规划 28/28 通过；PR additive integration audit：4/4 通过。
- PR sender-role 实机截图回放脚本正常退出，但因当前环境未提供明色/暗色截图变量而明确跳过；该项不计为截图回放通过。
- Python 编译检查和 `git diff --check` 通过。
- PR 七个冻结文件与 `2120f16744aebe3d8edbdf9c3f407375bfeed279` 的 blob：7/7 完全一致。

审计结论：未增加账号、会话名、数字、车型、关键词或话术特判；未改变外部接口、共享字段、状态路径和可选插件边界；未增加 OCR、截图、点击、键盘、剪贴板或发送动作；Brain 仍是唯一客户可见回复作者。
