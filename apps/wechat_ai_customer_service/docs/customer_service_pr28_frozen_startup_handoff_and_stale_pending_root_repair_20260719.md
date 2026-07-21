# PR #28 冻结条件下的启动消息交接与遗留待办根因修复开发文档

> **当前状态（2026-07-21）：历史实施文档。** 原始冻结 head 和阶段结论仅作证据；当前状态以 [PR #28 / Vision 残留问题收口索引](customer_service_pr28_residual_issue_closeout_20260721.md) 为准。

状态：本地适配层离线验收完成，PR 冻结基线自相矛盾项已隔离记录，待仓库所有者实机手测  
日期：2026-07-19  
适用范围：`apps/wechat_ai_customer_service` 的非 PR 启动 bootstrap、SessionMonitor、Scheduler 内部协调  
冻结前提：PR #28 head `2120f16744aebe3d8edbdf9c3f407375bfeed279` 的七个文件保持字节级不变

## 1. 强制基线

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)
- [customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)
- [customer_service_pr28_frozen_local_session_truth_and_fairness_repair_plan_20260719.md](customer_service_pr28_frozen_local_session_truth_and_fairness_repair_plan_20260719.md)

本文是上一份“本地会话真值与调度隔离修复”的根因补充。上一版已经阻止侧栏预览直接进入 Brain，并限制了空捕获重试，但没有闭合“启动读取结果到 live Scheduler 的交接”，也没有在新进程启动时区分旧 pending 与当前真实未读。因此上一版不能单独作为手测通过依据。

硬约束：

1. 客户可见回复仍只能由 `customer_service_brain` 创作；本修复只交接真实聊天区消息，不生成回复文案。
2. 不增加客户名、会话名、车型、问法、内容关键词、数字角标形态或坐标特判。
3. 不修改模块间现有函数签名、参数、返回字段、JSON 字段、配置键、路径和外部错误语义。
4. 不修改 Vision/Voice 插件合同，不把图片能力重新塞回 Sidecar 或 Scheduler。
5. 不修改 PR #28 的任何源码、注释、格式、测试或换行。

## 2. PR 字节级冻结清单

以下文件在实施前后都必须与 PR head 的 blob 完全一致：

| 文件 | PR blob |
|---|---|
| `adapters/wechat_connector.py` | `00e1da58a982265556394e7b19271bd5bcec545f` |
| `adapters/wechat_win32_ocr/text_normalization.py` | `7a09c6ddd2d218ee941686f4985cc2f184f03a4d` |
| `adapters/wechat_win32_ocr_sidecar.py` | `dc015f4a6b5f28d6e11017ab9665eb1e86a41910` |
| `tests/run_wechat_win32_ocr_compat_checks.py` | `f55fcee1a9b702e09415688735af363246f71fe0` |
| `tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py` | `0832a0be250093ef3c8384d6c0296b50f9d2b4c8` |
| `tests/run_wechat_win32_ocr_window_action_planning_checks.py` | `a0efe8031f79165654b97185e0ed94d84919033b` |
| `wechat_message_envelope.py` | `3c81ea47717b67ea3b82d9224fc7d83941eed722` |

## 3. 现场事实与根因

### 3.1 STARTUP-HANDOFF-01：bootstrap 读到真实客户气泡，但没有交给 live Scheduler

2026-07-19 22:14:28 的启动 bootstrap 在“新数据测试”中读到四个可见 occurrence，其中三个是客户消息、一个是我方消息。客户 occurrence ID 已写入 bootstrap 审计的 `deferred_customer_message_ids`，却没有进入按 `session_key` 隔离的 Scheduler capture/ledger/task。

live 进程随后只能再次点击并读取同一会话。此时历史锚点位于可见消息末尾，`messages_after_anchor_count=0`，于是三次捕获均得到 `empty_capture_no_verified_message`。Brain 从未收到客户消息，因此不是 Brain 慢、Brain 不理解或发送失败。

根因是两个生命周期之间没有事务性交接：

```text
启动 bootstrap：聊天区真实消息 -> 只写 name-keyed bootstrap 审计
live Scheduler：session_key-keyed capture -> 必须重新读屏 -> 被锚点切空
```

### 3.2 STARTUP-STALE-02：旧进程 pending 被新进程当成当前未读

“杨潇Eve”的 pending 形成于旧运行，其侧栏预览是我方上一条回复被 OCR 截断/重复后的内容。新进程启动时该会话没有当前红点，也没有新的聊天区客户气泡，但持久化的 `unread_detected=true` 仍然进入有限调度窗口，造成三次无意义点击。

上一版有限重试只阻止了无限循环和错误回复，没有阻止第一次、第二次、第三次物理访问。根因是新进程没有一次“当前可见证据基线化”：旧 pending 的时间和观测属于旧生命周期，却没有在第一次被动会话列表轮询时重新认证。

### 3.3 OBSERVATION-DRIFT-03：同一物理红点被 OCR 文本抖动改造成新事件

当前 `pending_observation_id` 间接包含侧栏预览全文。同一条预览被 OCR 识别成一次文本或重复两次时，raw observation ID 变化，Scheduler 会把它当成全新事件并恢复捕获预算。

物理事件身份应由稳定的会话行、消息时间和红点上升沿 epoch 构成；预览正文只负责辅助发现，不能在红点未消失/重现时独立创造新物理事件。

### 3.4 SESSION-IDENTITY-04：同名历史 key 不应按“数据最多”自动合并

同一显示名曾出现 `group/private` 不同 session key。现有 Monitor 的旧兼容分支会在多个历史 key 中按 ledger 数量选一个 canonical key 并合并上下文。这不是可证明的身份绑定，可能把两个真实会话合并。

正确边界是：唯一明确 key 可以复用；多个候选时保留当前精确 key，禁止猜测、禁止跨已确认类型合并。显示名只用于 UI，不作为跨会话主键。

## 4. 获批实现方案

### 4.1 启动真实消息直接复用现有 Scheduler 持久化合同

visible-only bootstrap 在点击目标前，先通过现有 `list_sessions()` 做一次被动读取：

1. 只接受显示名唯一匹配且具有非空 `session_key` 的当前行。
2. 保留该行当前红点/未读证据、conversation type 和 observation ID。
3. 使用这个精确 session key 调用现有 `get_messages()`；不使用名称模糊绑定。
4. 对聊天区消息执行与 live 捕获相同的规范化和 `select_batch_details()`。
5. 若存在真实客户 batch，调用现有 `record_capture_result()` 和 `enqueue_llm_task()`，直接写入现有 Scheduler state/capture/ledger/task；不新增交接字段或新状态格式。
6. 若只有媒体信号、尚不能在 bootstrap 中形成客户文字 batch，则调用现有 `record_session_signal()` 留下近期、精确、具有当前未读证据的 capture pending，由 live Scheduler 和独立 Vision/Voice 插件继续处理。
7. 若当前行没有未读证据，则 bootstrap 只做既有安全基线，不创建回复任务。

该方案没有第二套队列，也没有把侧栏 preview 伪造成客户正文。交接的数据来源仍是当前目标聊天区真实 capture。

### 4.2 新进程首次轮询关闭无当前证据的旧 pending

SessionMonitor 第一次成功被动轮询时：

1. 当前仍有物理未读红点的会话正常保留/派发。
2. 当前没有红点、且 pending 来自旧进程的会话只做基线更新，清除逻辑 pending，不执行点击。
3. Scheduler 中旧的 `pending_capture` 也要在首次协调时复核：当前 Monitor 没有 pending、没有 Brain/发送等 active work、`last_detected_at` 早于本进程启动窗口的记录，关闭为 idle。
4. bootstrap 刚在启动前写入的近期精确 capture/task 或媒体 pending 必须保留。
5. 后续真实红点上升沿或新的无红点当前消息变化仍可创建新事件，不能永久屏蔽该会话。

### 4.3 物理事件 ID 与 OCR 正文解耦

1. raw `session_observation_id` 保留现状用于审计，不改变 PR 字段。
2. 当当前行有红点时，本地 pending 事件种子使用 `session_key + message_time + badge_epoch`，不使用预览全文。
3. 同一 badge epoch 内的 OCR 重复、截断、标点或空格变化不得恢复捕获预算。
4. 红点消失后再次出现会增加 epoch，哪怕客户再次发送相同文字，也必须成为新事件。
5. 无红点的运行中预览变化仍使用既有双确认机制；仅增加通用的相邻重复片段归一化，不能按具体话术过滤。

### 4.4 身份漂移 fail closed

1. 一个显示名只有一个历史生成 key 时，可维持旧兼容复用。
2. 存在多个历史 key 时，不再按 ledger 数量自动选主或合并。
3. 当前连接器提供的精确 key 原样使用；缺少精确 key 且候选不唯一时不得跨 key 猜测。
4. Scheduler 现有“一个 confirmed key + 一个 unknown 历史 alias”的保守迁移桥保持不变；confirmed group/private 之间不合并。

## 5. 不变量与失败安全

1. 没有当前红点，也没有启动期真实聊天区 capture 时，不点击、不进 Brain、不发送。
2. bootstrap 已确认的真实客户 batch 只能进入其精确 session key，不能按显示名串到另一个会话。
3. 同一 batch 重复执行 bootstrap 时，现有 Scheduler/ledger occurrence 去重必须保证只形成一份有效任务。
4. bootstrap 交接失败时不得把客户消息标成已处理；启动检查应返回内部错误，不允许静默吞消息。
5. 侧栏 preview 永远不能成为 Brain 回复正文。
6. 客户再次发送与历史完全相同的文字，只要发生新的物理红点 epoch 或新的聊天区 occurrence，就仍然正常处理。
7. 一个会话的失败不得阻止其他会话轮询、捕获、Brain 和发送。
8. Vision/Voice 缺失或失败不影响纯文字 core；媒体能力仍只由独立插件实现。

## 6. 测试矩阵

### 6.1 定向特征化

1. 旧 pending + 首次轮询无红点：零派发、零点击资格。
2. 旧 pending + 当前红点：保留并派发。
3. 新会话无红点短 preview：首轮只建立基线，不点击。
4. 同一 badge epoch 下 OCR 单份/重复份切换：不生成新 pending。
5. 红点下降再上升、客户发送相同文本：生成新 pending。
6. 唯一精确 bootstrap 行 + 当前未读 + 三条客户消息：形成同 session key 的 durable capture 和 queued LLM task。
7. 同一 bootstrap batch 重放：不形成第二个有效客户任务。
8. bootstrap 只有媒体当前未读：形成近期 exact capture pending，交给 live 插件链路。
9. bootstrap 无当前未读：不创建 capture/task。
10. 同名多行或 session key 缺失：fail closed，不做跨会话交接。
11. 多个历史 group/private key：不再自动合并 ledger。
12. 侧栏我方回复 OCR 截断/重复：不进 Brain。

### 6.2 回归与合同

- 本地 session truth/fairness 定向测试。
- workflow logic、burst/history anchor、多会话 scheduler、session ledger 测试。
- Brain First、客户可见回复所有权、发送目标确认与 no-cross-send 测试。
- core-only / core+Vision / core+Voice / core+both 的可选插件合同测试。
- PR #28 三个原生测试。
- 七个冻结文件实施后逐一 `git hash-object` 与 PR blob 比对。

## 7. 交付条件

只有同时满足以下条件才允许交给仓库所有者手测：

1. 本文所有定向场景通过。
2. 现有多会话、Brain、发送、Vision/Voice 合同测试通过。
3. PR 七文件 7/7 字节一致。
4. `git diff` 中没有 PR 文件、没有外部接口或字段改名/增删。
5. 没有账户、客户、车型、具体话术或 OCR 数字形态特判。
6. 未启动微信自动客服；是否启动客户端由仓库所有者另行指示。

## 8. 实施结果

### 8.1 已落代码

- 新增 `admin_backend/services/bootstrap_scheduler_handoff.py`：把启动期聊天区已验证客户 occurrence 通过既有 Scheduler capture/task 合同持久交接；没有新队列、没有新对外字段。
- 新增 `admin_backend/services/session_runtime_reconciliation.py`：按精确 `session_key + observation_id` 协调 Monitor/Scheduler，并在新进程第一次调度前关闭没有当前证据的旧 capture pending。
- 修改 `workflows/listen_and_reply.py`：visible-only bootstrap 只在当前唯一会话行具有未读证据时交接真实聊天区 batch；无未读不造任务，交接写入失败则启动失败关闭。
- 修改 `admin_backend/services/session_monitor.py`：旧进程 pending 首轮重新认证；红点事件 ID 与 OCR preview 抖动解耦；多历史 key 时不再按数据量猜测合并。
- 修改 `admin_backend/services/customer_service_scheduler.py`：启动清理先于任何会话点击；存储失败时整轮失败关闭并允许幂等重试；有 key 只认 key，同名不同 key 不互相保活；空聊天区捕获只做三次通用有限重试，侧栏 preview 永不进入 Brain。
- 未修改任何对外函数签名、参数、返回字段、状态字段、配置键、路由或 Brain/RPA/Vision/Voice 合同。

### 8.2 模拟与合同测试

| 测试 | 结果 | 覆盖重点 |
|---|---:|---|
| 本地会话真值/公平性 | 13/13 | 启动交接、旧 pending、OCR 抖动、同名不同 key、存储失败关闭、有限重试 |
| 多会话 Scheduler | 189/189 | 两会话并发、连续追问、会话隔离、Brain/发送生命周期、no-cross-send |
| Workflow logic | 127/127 | bootstrap、历史锚点、动态全会话、Brain First 与发送守卫 |
| Burst/semantic batch | 27/27 | 多条未读、历史补读、锚点缺失与连续消息 |
| 外部合同兼容 | 3/3 | 对外快照、Voice/Vision 兼容形状、Scheduler 状态语义 |
| 可选插件矩阵 | 7/7 | core-only、Voice/Vision 独立加载、缺失依赖关闭 |
| 当前图片桥/图片合同 | 2/2、6/6 | 当前剪贴板 generation、内存图片、路径/归档禁用、插件端口关闭 |
| Brain First 静态审计 | 9/9 | Brain 唯一客户可见回复权、无本地 fallback |
| Brain/代码机制合同与 Brain 主回归 | 通过 | 权威数据边界、身份暴露守卫、上下文、商品候选和异常关闭 |
| Python 编译与 `git diff --check` | 通过 | 本次代码可导入、无空白错误 |

模拟测试中的 `check_runtime_manual_like_two_sessions_and_followup_all_send` 已通过：两个会话都能进入各自 capture/Brain/ready/send 生命周期，其中一个会话的后续追问仍能继续发送，不依赖账户名或消息内容特判。

### 8.3 PR 冻结核验与 PR 自身遗留

七个 PR 文件的工作区 blob 与 `2120f16744aebe3d8edbdf9c3f407375bfeed279` 比对为 **7/7 完全一致**，本次没有通过外围修改改写其文件内容。

PR 原生测试运行后确认一项 PR 自身已有的合同矛盾，当前按“不修改 PR”约束保留：

1. PR 将 `wechat_win32_ocr_sidecar.py` 中 `WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN` 的缺省值从 `True` 改为 `False`。
2. 同一 PR 的 `run_wechat_win32_ocr_compat_checks.py` 和 `run_wechat_win32_ocr_window_action_planning_checks.py` 仍按缺省 `True` 断言窗口从 `(-180, 80)` 移到 `(0, 0)`；实际 PR 代码按缺省 `False` 移到 `(0, 80)`。
3. 因此两个冻结测试各在同一窗口 `top` 断言停止。用修改规划器依赖来偷偷抵消 PR 的 `False` 语义，虽然可让测试变绿，但实质上会突破“PR 语义也不得改”的底线，故未采用。
4. sender-role 截图回放脚本因未配置两张外部截图环境变量而按设计 `skipped`，不是产品失败。

该 PR 自身矛盾与本次“新数据测试不回、杨潇Eve 被误点”的根因和修复路径无交叉；它不改变本地适配层模拟结果，但应由 PR 作者决定保留非固定原点语义还是恢复固定原点语义，然后同步修正冻结测试。

## 9. 最终审计结论

1. 本次问题已从启动交接缺口、旧生命周期 pending、OCR 事件身份漂移、同名 key 猜测四个根因闭环，不是增加账户/车型/问法特判。
2. 侧栏 preview 仍只作为唤醒证据，不能授权 Brain 回复；客户可见文字仍只来自 `customer_service_brain`。
3. 启动状态持久化失败会在物理点击之前终止本轮，不会带着未认证旧状态继续操作微信。
4. 当前有未读证据的每个精确会话都独立进入调度；单个会话失败有有限重试且不会长期占用其他会话的派发窗口。
5. 未启动微信自动客服，代码已达到本次修复范围的实机手测条件。
