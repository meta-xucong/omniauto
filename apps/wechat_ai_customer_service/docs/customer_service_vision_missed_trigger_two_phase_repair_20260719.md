# 微信图片漏触发两阶段修复开发文档

> **当前状态（2026-07-21）：历史阶段方案。** 阶段结论和测试证据继续保留；当前 Vision 残留问题状态以 [PR #28 / Vision 残留问题收口索引](customer_service_pr28_residual_issue_closeout_20260721.md) 为准。

状态：阶段一已授权实施；阶段二仅设计、未授权、不得实施  
日期：2026-07-19  
适用范围：`apps/wechat_ai_customer_service` 独立 Vision 可选模块

## 1. 强制基线

本方案必须同时服从：

- `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`
- `apps/wechat_ai_customer_service/docs/customer_service_external_contract_and_optional_plugin_baseline.md`
- `apps/wechat_ai_customer_service/docs/customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md`
- `apps/wechat_ai_customer_service/docs/customer_service_absolute_independent_vision_module_refactor_plan_20260718.md`
- `apps/wechat_ai_customer_service/docs/customer_service_ephemeral_clipboard_vision_rebuild_20260713.md`

本方案只纠正旧设计中“侧栏预览必须先被识别为图片，才允许观察当前聊天区”的错误前置关系。它不放宽 Brain 唯一出话权、当前剪贴板唯一图片来源、会话绑定、防错发、插件隔离或 PR 原样保留等既有基线。

## 2. 已复现现象与根因

2026-07-19 实机日志表明：普通文字消息能够完成捕获、Brain 规划和发送；同轮图片没有生成新的 Vision media task，`media_context_completed` 仍停留在历史值，当前日期也没有新增图片理解记录。因此故障发生在 Vision 进入右键复制之前，不是模型识图失败，也不是 Brain 或发送失败。

现有链路形成了循环依赖：

1. Scheduler 每次真实捕获都通过中性插件协议调用 Vision 的 `prepare_scheduler_capture`。
2. Vision 只有在 `pending_signal_kind` 是 `image_capture/media_capture`，或侧栏预览文字含 `[图片]` 等提示时，才观察当前聊天区。
3. 客户发图后立即补一句文字时，侧栏预览已被文字覆盖。
4. Vision 因“没有图片侧栏信号”而跳过聊天区结构观察，于是永远无法发现聊天区中真实存在的图片气泡。

这不是图片内容特征覆盖不足，而是触发拓扑错误。继续增加图片特征、预览词条或账号特判都不能根治。

## 3. 不可变边界

### 3.1 PR #28 七文件字节级冻结

以下文件必须始终与 PR head `2120f16744aebe3d8edbdf9c3f407375bfeed279` 的 blob 完全一致：

1. `apps/wechat_ai_customer_service/adapters/wechat_connector.py`
2. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py`
3. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
4. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
5. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py`
6. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py`
7. `apps/wechat_ai_customer_service/wechat_message_envelope.py`

阶段一和阶段二都不得修改这七个文件。每个阶段必须在实施前后执行逐文件 blob 校验。

### 3.2 外部合同冻结

- 不增删、改名或改变现有模块间字段、函数签名、路径、事件、状态、错误语义和默认值。
- Core、Scheduler、Brain 只能依赖中性可选插件协议，不得直接导入具体 Vision 实现。
- Vision 不拥有 Scheduler 状态，不改变 Brain 输入外层合同，不生成客户可见回复。
- 客户可见文字只能由 `customer_service_brain` 产生；Vision 只提交识图证据或我方图片上下文。
- 不增加车型、账号、会话名、客户问法、关键词或固定话术特判。

### 3.3 图片获取底线

- 当前微信聊天区中，经过目标会话确认后，对当前图片气泡执行右键并点击“复制图片”。
- 只有紧接该复制动作、且剪贴板代次已变化的当前剪贴板图片可被读取。
- 图片仅在内存中交给理解模块，使用后释放。
- 禁止截图裁切充当识图输入，禁止读取历史文件，禁止旧剪贴板复用，禁止保存原图或派生图。

## 4. 总体分阶段设计

```text
阶段一：已有捕获内恢复触发（本次实施）
新消息捕获 -> 中性插件调用 -> Vision 当前表面结构观察
          -> 新鲜图片 occurrence 绑定 -> 当前右键复制 -> 当前剪贴板理解

阶段二：无捕获时的低扰动观察（本次不实施）
Scheduler 安全空闲点 -> 中性可选观察钩子 -> Vision 自有去重与上下文投影
```

阶段一解决“图片之后有文字，因此 Scheduler 已有一次真实捕获，但侧栏图片预览被覆盖”的主故障。阶段二只处理“图片预览被覆盖，同时此后再也没有任何可触发捕获的信息”这种没有宿主调用机会的剩余场景。

## 5. 阶段一：已有捕获内的 Vision 结构触发恢复

### 5.1 授权范围

只允许修改：

- `apps/wechat_ai_customer_service/optional_plugins/vision/` 内部实现；
- PR 七文件之外的新增 Vision 专项测试；
- 本文档和长任务审计记录。

不得修改 Scheduler、Brain、Listener、Connector、Sidecar 或其他宿主业务实现。

### 5.2 运行算法

1. Scheduler 按现有方式获得一个真实会话捕获，并通过中性插件协议调用 `prepare_scheduler_capture`。
2. Vision 对每个有当前 pending signal 的捕获执行一次轻量的“当前聊天表面结构观察”。侧栏图片信号仍可作为优化和诊断证据，但不再是进入结构观察的硬门。
3. 结构观察只做当前窗口截图、OCR 和图片气泡几何定位，不右键、不读剪贴板、不调用图片理解模型。
4. Vision 保持现有 occurrence `message_id` 生成合同不变；相邻文本锚只作为本次捕获内的私有绑定证据，返回 Core 前必须移除。屏幕坐标只用于当前定位，不作为图片内容身份或跨模块数据。
5. 当侧栏明确是图片时，继续按现有“最新、方向确定、未处理”的 occurrence 处理。
6. 当侧栏已经变成普通文字时，只允许绑定到本次新消息的结构关系：图片必须位于本次最新文字锚之前、与其相邻，且该 occurrence 未在当前目标会话的 ledger/processed state 中出现。历史可见图片加一条无关新消息不得误触发。
7. occurrence 与本轮捕获继续复用原 `pending_signal_id`，不得新造一个与 Scheduler 捕获不一致的发送身份。这保证现有 planner/RPA 的 session/pending signal 防错发校验原样有效。
8. 客户图片走现有客户图片 pending/proxy 投影；右键目标按当前聊天区同方向 occurrence 的相对先后选择最新项，不按图片面积、颜色或内容分数选择。随后只执行一次当前右键复制、剪贴板代次验证和 LLM 图片理解；理解文本进入当前 Brain 证据。
9. 我方图片走现有 context-only 路径：同样右键复制和理解，记录发送方标记及理解文本，但绝不创建客户回复任务。
10. 同一次 occurrence 的重复表面扫描不再执行；同一张图片在后续被重新发送形成新 occurrence 时，应再次执行。
11. 任意观察、定位、复制或理解失败都 fail-closed；不启用裁切、文件、旧剪贴板或本地回复兜底，普通文字链路不得因可选 Vision 失败而失效。

### 5.3 性能与防机械化要求

- 结构观察最多一次/实际捕获，不做独立高频轮询。
- 结构观察阶段不产生右键、菜单、剪贴板或模型调用；只有新鲜 occurrence 被确认后才进入这些重操作。
- 复用宿主既有 RPA 串行锁、目标确认和 humanized action，不新增并行动作或固定节拍。
- 无 Vision 插件、Vision 禁用、依赖缺失和 Vision 异常时，Core 文字链路保持可用。

### 5.4 阶段一验收矩阵

必须新增特征测试并覆盖：

1. 客户只发图片、侧栏仍显示图片：原路径继续工作。
2. 客户发图片后立刻发文字、侧栏只显示文字：发现相邻图片并恰好触发一次。
3. 屏幕上有已处理旧图片，客户新发一条无关文字：不得触发。
4. 我方发图片，随后客户追问：图片被理解并以 `self/context_only` 记录，不创建我方图片回复任务。
5. 同一表面重复扫描：不得再次触发。
6. 同内容图片作为新 occurrence 再次发送：允许再次触发，身份不依赖图片内容 hash。
7. 纯文字捕获：最多做轻量结构观察，不右键、不读剪贴板、不调用 Vision LLM。
8. 多会话：occurrence、pending signal、Brain 证据和发送目标不跨 session。
9. 图片复制失败：不得读旧剪贴板，不得走截图裁切/历史文件兜底，文字链路保持可恢复。
10. Core-only、Core+Vision、Vision 缺失依赖等可选插件矩阵继续通过。

阶段一退出条件：

- 新专项测试全部通过；
- Vision 边界、方向、我方图片、图片路由、可选插件、外部合同、Scheduler 与 OCR/RPA 相关回归通过；
- PR 七文件逐一与 PR head blob 相同；
- `git diff --check` 通过；
- 未启动真实微信自动客服，未产生客户可见发送；
- 将剩余风险和阶段二是否仍必要明确交给仓库所有者决定。

## 6. 阶段二：无宿主捕获时的低扰动观察

状态：**未授权，禁止实施。**

### 6.1 解决范围

仅解决阶段一不可覆盖的场景：某个图片 occurrence 的侧栏预览被覆盖，之后没有新的有效捕获，因此 Scheduler 永远不会调用 Vision。典型例子是我方发图后没有任何客户新消息，但系统仍要求立即补齐我方图片上下文。

### 6.2 候选设计

- 在 Scheduler/Core 的安全空闲点增加中性、可选、absence-safe 的 observation capability；Core 不导入 Vision，也不包含图片/OCR/剪贴板语义。
- Vision 自己决定是否观察、如何去重、如何输出既有兼容投影；它不取得 Scheduler 状态所有权。
- 所有观察必须复用 RPA 串行锁、目标确认、低扰动节流和会话身份防漂移机制。
- 观察结果只能通过既有兼容字段进入 ledger/上下文，不得增加新的跨模块字段。
- 阶段二不得绕开当前右键复制、剪贴板代次验证和 Brain 唯一出话权。

### 6.3 阶段二单独授权门槛

阶段一完成后，先用真实微信手测确认：

- 图片后补文字是否已经稳定识别；
- 我方图片在客户后续追问时是否能补齐上下文；
- 当前性能、微信行为扰动和下线风险是否可接受。

只有仍存在“无任何后续捕获但必须即时记录”的明确商业需求，且仓库所有者接受新增宿主空闲钩子的行为面，才进入阶段二开发。否则阶段二永久保留为未实施设计。

## 7. 明确禁止的修法

- 修改或覆盖 PR #28 七文件。
- 在 Sidecar、Connector、Scheduler 或 Brain 中重新塞入具体图片能力。
- 增加 `[图片]`、车型、账号、会话名或客户措辞词条来扩大触发。
- 把所有当前屏幕图片都当成新图片；或永远选择最后一张而不证明与本轮新消息的关系。
- 用截图裁切、文件监控、历史缓存、旧剪贴板或图片 hash 代替当前右键复制事务。
- 为提高回复率而放松目标会话、session key、pending signal 或发送前 active-target 校验。
- 让 Vision、Guard、Reviewer、RAG 或本地模板生成客户可见回复。

## 8. 审计与交付记录

阶段一交付时必须记录：

- 实际改动文件；
- 新增测试及通过数；
- 回归命令、结果与耗时；
- PR 七文件前后 blob 对照；
- 外部合同、Vision 独立性、Brain 唯一出话权和零图片落盘审计结论；
- 阶段一未覆盖项；
- 阶段二明确保持未实施。

## 9. 阶段一实施与验收结果

完成时间：2026-07-19  
结论：阶段一自动化门禁通过；阶段二未实施，等待仓库所有者决定。

### 9.1 实际代码范围

阶段一只修改独立 Vision 内部：

- `optional_plugins/vision/capture/surface.py`：生成并传递当前捕获内的私有相邻文本锚；不改变既有 occurrence `message_id` 生成合同。
- `optional_plugins/vision/occurrence.py`：普通文字 pending signal 只可绑定相邻、未处理的结构 occurrence；返回 Core 前删除全部 `_vision_*` 私有锚。
- `optional_plugins/vision/scheduler_capture.py`：每次已有真实捕获最多做一次结构观察；默认 PR host 不可用时 absence-safe；我方图片补上下文时不吞掉当前客户文字。
- `optional_plugins/vision/runtime.py`：接受已经由 Scheduler capture 确认并绑定的普通 pending signal，继续复用原 `pending_signal_id` 执行现有右键复制事务。
- `optional_plugins/vision/capture/wechat.py`：最终右键目标按同方向图片在聊天区的相对先后取最新项，不按面积或图片内容评分取旧图。

新增：

- `tests/run_customer_service_vision_structural_trigger_recovery_checks.py`
- 本开发文档。

未修改 Scheduler、Brain、Listener、Connector、Sidecar、消息 envelope 或 PR #28 七文件。没有实现 idle hook、定时轮询或任何阶段二代码。

### 9.2 专项测试过程

特征测试先在旧实现上运行：8 项中 7 项失败，稳定复现无结构观察、无相邻绑定、runtime 拒绝普通 pending signal 等根因。完成实现和边界补测后，最终专项为 12/12：

- 图片后立刻补文字，侧栏只剩文字时触发一次；
- 旧图不复触发；
- 我方图片只补上下文且不吞客户追问；
- 纯文字不进入剪贴板/LLM；
- custom connector 不误启默认桌面 worker；
- runtime 只执行一次当前右键复制事务；
- 同内容新 occurrence 可再次触发；
- 大图旧 occurrence 不得覆盖位置更晚的新 occurrence。

### 9.3 最终回归时间表

| 门禁 | 结果 | 耗时 |
|---|---:|---:|
| 阶段一专项 | 12/12 | 0.554s |
| 双向图片方向 | 7/7 | 0.351s |
| 我方图片 Brain 上下文 | 5/5 | 1.431s |
| Vision worker | 3/3 | 2.334s |
| Vision 绝对边界 | 7/7 | 3.773s |
| 可选插件矩阵 | 7/7 | 4.358s |
| 客户图片路由 | 7/7 | 0.545s |
| Scheduler 当前图片 bridge | 2/2 | 2.118s |
| 图片理解合同 | 6/6 | 0.364s |
| 多模态 session 上下文 | 通过 | 2.737s |
| 外部合同快照 | 3/3 | 18.864s |
| PR #28 additive/blob 审计 | 4/4 | 20.330s |
| PR 有效运行时 OCR + window planning | 229/229 + 28/28 | 18.355s |
| 多会话 Scheduler | 189/189 | 15.072s |
| Workflow | 127/127 | 29.488s |
| Brain 合同 | 通过 | 24.984s |
| Brain First 静态所有权 | 通过 | 4.758s |
| Brain/代码机制分层 | 通过 | 0.372s |
| RPA acceptance | 10/10 | 3.116s |

最终回归累计约 153.904 秒。Python 编译和 `git diff --check` 通过。

### 9.4 PR 与已知上游负例

PR head：`2120f16744aebe3d8edbdf9c3f407375bfeed279`。七文件最终 blob 逐一为：

- `wechat_connector.py`：`00e1da58a982265556394e7b19271bd5bcec545f`
- `text_normalization.py`：`7a09c6ddd2d218ee941686f4985cc2f184f03a4d`
- `wechat_win32_ocr_sidecar.py`：`dc015f4a6b5f28d6e11017ab9665eb1e86a41910`
- `run_wechat_win32_ocr_compat_checks.py`：`f55fcee1a9b702e09415688735af363246f71fe0`
- `run_wechat_win32_ocr_sender_role_screenshot_replay.py`：`0832a0be250093ef3c8384d6c0296b50f9d2b4c8`
- `run_wechat_win32_ocr_window_action_planning_checks.py`：`a0efe8031f79165654b97185e0ed94d84919033b`
- `wechat_message_envelope.py`：`3c81ea47717b67ea3b82d9224fc7d83941eed722`

七个 blob 与 PR head 7/7 完全相同。原样直接运行 PR OCR suite 仍会复现既有 fixed-origin 默认值不一致负例（期望窗口移到 `(0, 0)`，原 PR 默认结果为 `(0, 80)`）；这是合并前已登记的 PR 上游问题，本阶段没有权限修改。通过 PR 外既有 runtime adapter 运行时，OCR 229/229、window planning 28/28 全部通过。

### 9.5 阶段一剩余边界

阶段一依赖“一次已有真实捕获”作为中性插件调用机会。若图片侧栏预览被覆盖，且之后完全没有新消息或其他捕获，阶段一不会主动轮询微信；这正是阶段二的候选范围。当前不以扩大桌面动作面来自动解决，等待真实手测后再决定是否授权阶段二。
