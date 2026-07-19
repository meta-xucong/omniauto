# 微信客服双向图片方向、持久化与 Brain 上下文闭环修复方案（2026-07-18）

> [!WARNING]
> **文档状态：功能规则保留、实施落点已废止（2026-07-18）。** 客户/我方方向、当前剪贴板、原子提交、去重和 Brain 上下文要求继续有效；Sidecar occurrence、Scheduler 图片路由、Ledger/Workflow 图片状态机及本文文件级修改表不得作为新实现依据。现行架构见 [完全独立图像识别模块改造方案](customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)。

## 0. 文档地位与强制基线

本文是 `apps/wechat_ai_customer_service` 当前双向聊天图片链路的功能修复和 Bug 修复规格。实施对象包括客户发送的图片和客服/我方发送的图片；“保存图片”在本文中只表示保存图片对应的 LLM 文字理解、方向、会话身份和最小事务审计，**不保存图片文件或图片内容**。

本文必须同时服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：所有客户可见回复只能由 `customer_service_brain` 编写；视觉插件、方向解析、Scheduler、ledger、guard 和 fallback 均不得生成客户可见措辞。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：视觉能力必须保持独立、可选、懒加载；不得改变现有模块接口、导入路径、函数签名、共享字段、状态文件结构、HTTP/CLI 合同或语音插件行为。
- [customer_service_ephemeral_clipboard_vision_rebuild_20260713.md](customer_service_ephemeral_clipboard_vision_rebuild_20260713.md)：图片内容的唯一来源是当前目标图片的一次右键“复制”以及同一事务内读取的当前剪贴板图片；不得使用聊天气泡截图裁切、历史图片路径、旧剪贴板、缩略图或图片资产回退。

当更早的图片文档仍然描述保存图片文件、裁切归档、`saved_image_path`、图片资产队列或异步读取历史图片时，以 2026-07-13 的剪贴板瞬时理解规则和本文为准。本文不恢复任何已废止的图片落盘路径。

## 1. 本次现场证据与问题边界

2026-07-18 “许聪”会话的现场链路证明以下事实：

1. 05:38:17，我方图片被右侧结构观察器识别并完成当前剪贴板理解，文字结果为“一名穿浅蓝色艾莎公主纱裙的小女孩在粉色花簇旁触摸花朵”。ledger 中方向为 `sender=self`。
2. 同一个会话列表预览 `[图片]` 又被 Scheduler 无条件构造成 `sender=customer`、正文为“客户发来了一张图片”的临时消息。
3. 客户图片事务在左侧找不到目标，返回 `customer_image_target_not_found`；但错误的客户占位消息已经进入捕获和规划链路。
4. 05:40:04，客户追问“你刚发给我的是啥图”；系统再次识别了同一张我方图片并把文字结果写入 ledger。
5. 本轮 Brain 事件显示 `brain_visual_context_used=false`、`referenced_context_count=0`，并进入 `low_authority_fast`；同时 `latest_turn_only_candidate` 清空了历史。Brain 最终只看到客户文字，没有看到已经保存的我方图片理解。
6. 现有图片和多模态测试均通过，因为测试只验证“文字理解写进 ledger”，没有验证“后续客户追问时 Brain 实际收到该理解”。

因此本次不是单点识图失败，而是以下独立缺陷串联：

- 会话列表媒体预览被错误当作方向证据；
- 客户路径和我方路径没有互斥归属；
- 我方图片在普通文字轮次被重复识别；
- 已持久化的图片文字没有进入 Brain 的有效历史；
- 快速通道和上下文恢复共同裁掉了紧邻图片上下文；
- 测试只覆盖存储，没有覆盖消费闭环。

## 2. 不可突破的总原则

### 2.1 外部合同完全冻结

本修复不允许：

- 增加、删除或改名模块间共享字段；
- 改变 `SessionState`、`ActiveTarget`、Scheduler state、session ledger、Brain 外层 payload 的既有结构；
- 改变现有公开函数、参数、返回键、import path、CLI、HTTP route、event/action/reason/state/error code；
- 要求外部调用方、第三方视觉插件或现有配置文件同步修改；
- 改变 RPA 发送、ready reply、会话绑定、freshness 或多会话调度的对外工作方式。

只允许新增模块内部私有 helper/class，且不得跨越原有模块边界暴露。现有字段只按原含义使用：

| 既有字段 | 本次允许用途 |
| --- | --- |
| `sender` / `sender_role` | 持久化确认后的 `customer` 或 `self` 方向 |
| `visual_side` | 适配器内部结构方向；不得由图片内容推断 |
| `pending_signal_id` / `pending_observation_id` | 绑定一次媒体事件，不授权方向 |
| `message_id` / `canonical_*` | 保持原身份合同，不用观察时间制造新业务消息 |
| `image_understanding` / `vision_summary` | 保存 LLM 文字理解，不保存图片内容 |
| `conversation.history_text` / `conversation_summary` | 向 Brain 提供有界、已确认的会话历史 |
| `quality_flags` | 保留现有审计语义；不得用新字段旁路 |

### 2.2 会话列表预览只触发捕获，不授权发送方

左侧 `[图片]`、`[照片]`、红点和时间只能证明“该会话可能有媒体活动”。它们不能证明图片来自客户，也不能证明来自我方。

严禁继续执行：

```text
看到 [图片] -> 默认 customer -> 写入“客户发来了一张图片”
```

正确链路必须是：

```text
看到 [图片] -> 激活并严格确认目标会话 -> 在聊天区按左右结构确认 occurrence 方向
            -> customer 或 self -> 再进入对应处理链路
```

### 2.3 方向只能由结构确认

方向主证据只有：

- 当前活动会话的 `session_key + conversation_type + target_name`；
- 聊天区、输入区、左右头像列、左右媒体列和消息纵向顺序；
- 当前待处理事件与可见 occurrence 的时间/顺序/未处理身份关联。

颜色、纹理、车型、人物、图片 OCR、LLM 内容分类、图片 hash、历史文件或会话列表预览均不得决定 `customer/self`。

### 2.4 图片内容只来自当前剪贴板事务

每个已确认图片 occurrence 最多执行一次物理右键复制；同一 occurrence 的重复轮询不得再次右键。必须验证：

1. 当前活动会话仍严格匹配；
2. 右键目标属于已确认方向的媒体列；
3. 菜单中确认“复制”；
4. 剪贴板序号发生变化；
5. 当前剪贴板内容是有效图片；
6. LLM 调用结束后立即释放内存图片。

禁止图片文件、裁切图、base64、路径、hash、边界或原始视觉 prompt 进入磁盘、ledger、state、日志或 Brain。

### 2.5 双向都记录，但回复资格不同

- 客户图片：保存方向和文字理解，并可作为当前客户轮次进入 Brain。
- 我方图片：保存方向和文字理解，只补充会话上下文；不得独立创建 customer reply、polish、ready reply 或 send。
- 方向未确认：不得伪装成任一方，不得生成客户占位消息，不得调用 Brain 猜方向。

## 3. 私有方向状态机

以下状态只允许存在于视觉模块/捕获函数的私有局部对象中，不写入共享 JSON，不增加外部字段或 reason code：

| 私有状态 | 含义 | 允许动作 |
| --- | --- | --- |
| `sidebar_signal_only` | 只有会话列表媒体信号 | 只激活并读取目标会话 |
| `customer_confirmed` | 当前新 occurrence 位于客户媒体列 | 进入客户剪贴板事务 |
| `self_confirmed` | 当前新 occurrence 位于我方媒体列 | 进入我方上下文事务 |
| `ambiguous` | 同时存在多个无法唯一关联的候选 | 不右键、不构造消息，有限重观测 |
| `no_candidate` | 当前表面找不到对应媒体 occurrence | 不右键，按既有捕获重试/告警边界处理 |
| `completed` | 文字结果已成功绑定 ledger occurrence | 消费该事件，重复轮询只读既有结果 |

任一 occurrence 在一次捕获中只能拥有一个方向所有者。`customer_confirmed` 与 `self_confirmed` 必须互斥。

### 3.1 pending signal 与 occurrence 的确定关系

`pending_signal_id/pending_observation_id` 是“需要检查这个会话”的活动身份，不等于一张图片，也不等于发送方。为了避免一个侧边栏信号被反复拿来盲点多张图片，内部解析必须按以下顺序执行：

1. 先以严格会话身份打开目标聊天，并一次性捕获当前聊天表面；
2. 仅按聊天区结构枚举左右两侧可见媒体 occurrence，不读取图片内容；
3. 用现有 canonical/message 身份和 ledger 已完成记录排除已经处理的 occurrence；
4. 再按微信显示时间、纵向顺序和当前 pending 活动窗口，确定本次尚未处理的 occurrence 集合；
5. 每个确定 occurrence 在模块私有内存中独立排队、独立确认方向、独立执行最多一次右键事务；处理下一张前重新确认活动会话；
6. 若不能证明哪些 occurrence 属于当前新活动，整个不确定子集进入 `ambiguous`，不得为了“尽量处理”而右键历史候选。

因此，“一个 pending 下有多张图”只表示一次活动可能合并了多个确定的新 occurrence；不表示可以凭一个 pending 身份重复读取剪贴板。不得为该拆分增加共享任务类型、持久化字段或插件协议方法。

## 4. 独立修复项

以下修复必须逐项落地、逐项测试。一个修复项未通过，不得用后续修复项掩盖。

### R-01：修复会话列表 `[图片]` 被默认成客户图片

**现状**

`session_monitor` 的媒体信号没有方向字段，这是合理的；错误发生在 Scheduler 看到 `image_capture` 后直接写入 `sender=customer`。

**修改**

1. 保持 `SessionState`、`ActiveTarget` 和 pending signal payload 完全不变。
2. `customer_image_capture_trigger` 仍只表示“需要检查图片”，不得把 `should_run=true` 解释为客户方向已确认。
3. 删除 Scheduler 在方向确认前构造 `clipboard_image_pending` 客户占位消息的可达路径。
4. `[图片]` 只让现有捕获流程打开并确认会话，再交给结构方向解析。

**禁止**

- 不给 pending signal 新增 `direction` 字段；
- 不把红点、群成员预览或联系人名称当方向；
- 不用“没有发现 self”直接证明 customer。

**验收**

- 我方图片 + `[图片]` 预览不能生成“客户发来了一张图片”；
- 方向未确认时 `batch` 中没有客户图片代理；
- 普通文字和语音信号行为不变。

### R-02：建立当前聊天表面的双向结构 occurrence 解析

**现状**

当前 surface helper 只把最新右侧图片暴露成 `self` 上下文消息；客户图片方向主要依赖后续客户侧事务，双方没有统一的 occurrence 归属步骤。

**修改**

1. 在 Win32/OCR 适配器内部新增私有双向结构解析 helper；既有公开函数继续保留并作为兼容门面。
2. 同一次已捕获的微信表面中，按左右媒体列和纵向行解析所有当前可见图片 occurrence。
3. 所有坐标、候选框和截图只在适配器内存中使用；跨模块仍只输出既有消息 envelope 字段。
4. 根据现有 `pending_signal_id/pending_observation_id`、微信显示时间、同会话未处理 occurrence 和纵向顺序关联当前事件。
5. 同屏多张图逐 occurrence 确认方向；同一 pending 事件可以包含多个 occurrence，但每个 occurrence 只处理一次。
6. 无法唯一关联时返回私有 `ambiguous`，不得选择“最像图片”的候选。

**禁止**

- 不用图片特征判断方向；
- 不把绝对坐标、边界或截图路径写出适配器；
- 不改变 `messages_payload` 的外层键或公开 sidecar CLI。

**验收**

- 左图、右图、同屏左右都有图、白图、黑图、截图、人物照和车辆图的方向只由结构决定；
- 窗口尺寸、DPI 和图片内容变化不改变方向规则；
- 同一聊天表面重复读取不会产生新的业务 occurrence。

### R-03：客户图片处理链路只接受 `customer_confirmed`

**现状**

当前客户图片事务可能在没有方向证明时启动，失败后错误占位消息仍可进入 Brain。

**修改**

1. 只有私有方向解析得到 `customer_confirmed`，才允许构造既有客户图片 pending/proxy 消息。
2. 客户代理继续使用现有字段、现有 plugin `run()` 和现有 `visual_bridge_input`；不改变 Brain 外层合同。
3. 右键事务必须再次校验客户媒体列和目标会话，方向校验失败即不读取剪贴板。
4. 成功后把文字理解绑定到同一 customer occurrence，再允许该客户轮次进入 Brain。
5. 已确认是客户图片但复制/理解失败时，只把既有事实性失败结果交给 Brain；客户可见澄清或重发请求仍由 Brain 编写。

**禁止**

- 不在方向确认前写 `sender=customer`；
- 不因客户事务失败切换到 self 或历史图片；
- 不由视觉插件生成“请重发”等客户话术。

**验收**

- 客户图成功：`sender=customer`、文字理解入 ledger、Brain 收到当前视觉文字；
- 客户图复制失败：无裁切/旧图回退，Brain 只收到事实性失败；
- 我方图绝不进入客户图片 router。

### R-04：我方图片处理链路只补上下文

**现状**

我方图片能够识图并写 ledger，但它在每次普通文字捕获时都可能再次被观察和识别，且其文字结果没有稳定进入后续 Brain 历史。

**修改**

1. 只有新的、未处理的 `self_confirmed` occurrence 才执行我方剪贴板事务。
2. 将当前既有 pending/observation 身份绑定到我方消息的既有 `pending_signal_id` 语义，确保同一事件只消费一次。
3. 成功后以现有 `sender=self`、`sender_role=self`、`modality=image`、`image_understanding`、`vision_summary` 写入 ledger。
4. 我方图片捕获完成后，Scheduler 必须得到空客户 batch，不创建 reply/planner/polish/ready/send。
5. 后续客户文字轮次只能读取已保存的我方图片文字，不能再次右键或再次调用视觉 LLM。

**禁止**

- 不在每次 `get_messages` 时无条件执行 self vision；
- 不把我方图片改写成 customer 代理以便启动 Brain；
- 不保存图片文件。

**验收**

- 我方发一张图：视觉 LLM 一次、ledger 一次、客户回复任务零次；
- 随后客户追问：视觉 LLM 零次、Brain 一次，并能读到此前 `vision_summary`；
- 重复轮询和普通文字轮次不重复识图。

### R-05：客户路径与我方路径必须互斥并完成冲突撤销

**现状**

同一图片既生成 `sender=self` 记录，又生成了“客户发来了一张图片”的客户占位，两个机制互相打架。

**修改**

1. 在任何持久化和任务入队前完成 occurrence 所有权判定。
2. `self_confirmed` 时，当前 occurrence 的客户 placeholder/proxy 创建路径必须不可达。
3. `customer_confirmed` 时，不运行同一 occurrence 的 self context 路径。
4. 若旧兼容入口已经生成未确认的 synthetic placeholder，在同一捕获提交前必须丢弃，不能写入 reply batch、ledger context summary 或 Brain。
5. `customer_image_target_not_found` 不能再与一个成功的 self enrichment 并存后继续生成客户回复。

**验收**

- 每个 occurrence 在 ledger 只出现一个方向；
- 同一 capture 中不得同时出现同一事件的 customer proxy 与 self enrichment；
- 冲突检测失败时 fail closed，不默认任一方向。

### R-06：方向、文字理解和事件消费必须原子闭环

**现状**

“捕获占位”“文字理解完成”“事件已处理”分散写入，可能出现 placeholder 已存在但方向/理解未完成的半状态。

**修改**

1. `capture_recorded` 继续保留原始机制审计，不改变事件合同。
2. ledger 可见语义记录只接受方向已确认的 occurrence。
3. `multimodal_context_enriched` 只有在匹配到同一 occurrence 并写入文字结果后才更新 summary。
4. 成功消费必须同时满足：session 匹配、方向明确、occurrence 匹配、文字结果已绑定。
5. 客户复制失败可以保留已确认的客户媒体事实和失败状态；我方复制失败只进入内部告警/审计，不触发客户回复。
6. 视觉 Provider 失败可在同一个内存图片对象上进行现有有限 failover/重试；不得通过再次右键或读取历史图片重试。

**禁止**

- 不把未经 enrichment 的 synthetic placeholder 当历史事实；
- 不在 ledger 更新失败时仍标记视觉事件成功；
- 不让一半成功状态跨会话或跨 occurrence 复用。

**验收**

- 模拟 ledger 写失败、Provider 超时、进程中断、回调异常时均没有假成功；
- 成功结果重启后可读，失败结果不会无限重放；
- 图片对象在所有异常分支释放。

### R-07：修复 occurrence 去重和重复识图

**现状**

同一我方图片在 05:38 和 05:40 被生成两个 `visual_self_context_*` 身份并重复识图，说明当前结构 anchor/观察位置不够稳定。

**修改**

1. 业务 occurrence 身份只依赖现有会话身份、pending/observation 事件身份、已确认方向、微信显示时间和同事件 occurrence 顺序。
2. `captured_at`、本次截图时间、绝对坐标、窗口滚动位置、视觉摘要和图片内容不得决定业务 occurrence。
3. 同一 occurrence 多次观察复用既有 canonical 身份/ledger 记录。
4. 相同图片内容被客户或我方再次发送且 pending 事件不同，必须视为新的 occurrence，不能按内容去重吞掉。
5. 普通文字 pending signal 不允许重新激活旧的 self image occurrence。

**验收**

- 同一 occurrence 不同截图时间：只识别一次；
- 相同图片重新发送：每次真实发送各有一条方向明确记录；
- 同一分钟连续多图依靠 occurrence 顺序区分，不互相覆盖；
- 重启后旧可见图片不被重新理解。

### R-08：把 ledger 中的图片文字真正接入 Brain 历史

**现状**

ledger 已有 `vision_summary`，但 `RawMessageStore` 当前未记录本轮消息；低资料 evidence pack 又把 `history=[]`、`history_text=""`，而 prompt 的 context 压缩也不读取 `ledger_context_summary/ledger_recent_messages`。

**修改**

1. 在 `reply_evidence_builder` 和 Brain 输入构建的内部实现中，从现有 `target_state.conversation_context.ledger_recent_messages` 选择有界、方向明确、已 enrichment 的最近会话记录。
2. 将选中的文字投影到现有 `conversation.history_text`/`conversation_summary`，不增加 Brain 字段。
3. 图片历史只包含：方向标签、`vision_summary`、消息时间和既有消息身份的最小文字投影。
4. 排除：`synthetic_visual_turn`、`image_capture_pending`、无方向、无 `vision_summary`、旧路径/asset/hash/bounds 和其他会话记录。
5. 当前客户文字前紧邻的我方图片必须被保留，让 Brain 自己判断指代关系；代码机制不编写答案。
6. ledger 文字投影是这类多模态上下文的稳定来源；无论可选的 `RawMessageStore` 记录开关开启或关闭，都必须得到相同的 Brain 历史结果，且不得为了补上下文强制开启原始消息存储。

**禁止**

- 不把整个 ledger 或原始 OCR 历史塞进 prompt；
- 不把图片理解当产品事实；
- 不改变 `brain_visual_context_used` 的既有“当前客户图片 bridge”含义来伪装成功。

**验收**

- Brain 实际 prompt/输入中包含最近我方图片的文字摘要；
- `RawMessageStore` 开启和关闭两种配置下，Brain 输入包含相同的可信图片文字投影；
- `referenced_context_count=0` 不能再意味着整个紧邻图片历史为空；应检查现有 `history_text`；
- 图片路径、base64、hash 和边界在 Brain 输入中为零。

### R-09：短消息快速通道不得裁掉紧邻多模态上下文

**现状**

“你刚发给我的是啥图”仅因字符短且没有商品关键词，被归类为 `short_low_authority_turn`，快速 evidence pack 清空了历史。

**修改**

1. 不通过穷举“刚发、什么图”等句式修补。
2. 增加纯数据型内部判据：当前会话最近一条非当前消息若是方向明确、已 enrichment 的多模态记录，则本轮不是无上下文低资料轮次。
3. 该判据只阻止 `low_authority_fast` 清空历史，不决定客户意图、不生成回复。
4. 仍由 Brain 判断当前文字是否在问上一张图片；若无关，Brain 可忽略该上下文。
5. 没有相邻多模态记录的普通问候、感谢、催促继续使用原快速通道。

**验收**

- 使用多种自然说法、错字、口语和不含“图”字的指代测试，均依靠邻接数据而非关键词保留上下文；
- 普通“在吗/谢谢”性能不退化；
- 不能因任意很久以前的图片永久禁用快速通道。

### R-10：上下文恢复不能删除可信的紧邻图片记录

**现状**

`overflow_unanchored + stale_unsent_reply + unread` 触发 `latest_turn_only_candidate` 后，代码把 `history_text` 和 `conversation_summary` 直接清空。现场中的 stale reply 又来自错误客户图片占位，最终导致正确图片上下文被反向删除。

**修改**

1. `latest_turn_only_candidate` 仍可裁剪旧的、不可信或跨人工介入历史。
2. 裁剪时必须保留同 session、方向明确、已 enrichment、时间上紧邻当前客户轮次的最多若干条可信多模态文字记录。
3. 可信记录只进入现有 `history_text`；不增加 recovery 字段，不改变 recovery 的外层合同。
4. synthetic placeholder、失败占位、无方向媒体和旧会话记录继续被删除。
5. stale reply 只表示发送生命周期中断，不能单独证明最近的已确认 ledger 事实不可信。

**验收**

- 现场三信号同时存在时，最近我方 `vision_summary` 仍进入 Brain；
- 真正跨会话、会话身份不明或未 enrichment 的旧内容仍被裁掉；
- 不把整个历史恢复回来导致 prompt 膨胀。

### R-11：修复启动、红点和旧媒体重复触发

**现状**

重启后会话预览 `[图片]` 与视觉红点可能重新创建图片事件。启动基线只在“无未读证据”时抑制旧媒体；一旦红点被判定存在，旧我方图片仍可能进入客户图片链路。

**修改**

1. 保留现有启动视觉基线、observation identity 和 unread epoch 字段。
2. 红点只提高“需要检查该会话”的优先级，不授权 customer 方向。
3. 打开会话后，若最新未处理 occurrence 为 self，则只补 self context 或复用已完成记录，不能生成客户图片事件。
4. 已确认 occurrence 的 pending/observation identity 被现有 acknowledged/processed 机制消费后，持续红点不得重建同一事件。
5. 重启时 ledger 已有成功文字结果的 occurrence 不再次右键、不再次调用视觉 LLM。

**验收**

- 重启 + 历史我方图片 + 无红点：不触发；
- 重启 + 错误/残留红点 + 我方图片：最多检查一次，不产生客户回复；
- 重启 + 真实新客户图片：正常进入客户链路；
- 同名会话、多会话不能共享 observation 或视觉结果。

### R-12：方向不明和失败必须有终态，不能静默或死循环

**现状**

错误方向会导致客户事务失败；过去的补丁可能重复轮询、重复右键，或让假占位进入 Brain。

**修改**

1. `ambiguous/no_candidate` 只允许现有捕获重试机制进行有限次数的重新观察；重新观察不读取旧剪贴板、不调用 LLM。
2. 达到既有重试上限后，使用现有内部 handoff/alert 接口告警，不创建本地客户可见话术。
3. 已确认客户图片但复制/理解失败：进入 Brain 的是事实性失败，Brain 决定如何向客户澄清。
4. 我方图片失败：记录内部失败和会话身份，不触发客户回复；不自动无限右键。
5. 任何路径都必须释放锁、剪贴板对象和内存载荷。

**验收**

- 无候选、菜单失败、剪贴板不变、非图片、Provider 失败、ledger 失败各有确定终态；
- 没有静默丢失、无限重试、重复发送或本地 fallback；
- 一个会话的失败不会阻塞其他会话或语音插件。

### R-13：清除既有假客户图片对未来上下文的污染

**现状**

当前 ledger summary 已存在带 `synthetic_visual_turn + image_capture_pending`、但没有成功客户图片理解的“客户发来了一张图片”。直接删除 immutable audit event 会破坏审计。

**修改**

1. 不删除历史 `events.jsonl`，不伪造历史。
2. 在现有 summary/context 投影中排除“方向未确认且未 enrichment”的 synthetic 图片占位。
3. summary 重新生成必须幂等：多次读取/刷新结果一致，不改变真实 customer/self 消息。
4. 历史已经实际发送给客户的错误回复仍作为真实聊天事实保留，不偷偷改写；但它不能授权图片内容。
5. 历史重复 self 识图只在 Brain 有界投影中选取最近、方向明确的一条；未经可靠 occurrence 证明不得破坏性合并原始审计记录。

**验收**

- 许聪当前 context 不再把假占位当客户事实；
- self 图片文字仍保留；
- 原始审计事件可追溯，summary 重建不新增字段或文件格式。

## 5. 模块内实施落点

所有改动必须保持原门面，且只能沿现有调用方向进行：

| 模块 | 允许的内部修改 | 明确禁止 |
| --- | --- | --- |
| `adapters/wechat_win32_ocr_sidecar.py` | 私有双向结构 occurrence 解析；既有 self helper 保留为门面 | 不导入 Brain/Scheduler/视觉 Provider；不输出坐标或截图 |
| `optional_plugins/vision/trigger.py` | 把 sidebar 媒体视为触发器而非方向结论 | 不做 RPA/LLM；不改返回键 |
| `optional_plugins/vision/compatibility.py` | 在既有 `should_run/run/capture_self_context` 门面后协调私有实现 | 不加插件协议方法；不改第三方插件合同 |
| `workflows/customer_image_turn_router.py` | customer 只接受确认后的 occurrence；self 只输出 context enrichment | 不生成客户话术；不读历史图片 |
| `admin_backend/services/customer_service_scheduler.py` | 方向互斥、占位延后、事件消费、ledger 汇合 | 不新增队列/任务类型/状态字段；不直接 import 视觉实现 |
| `admin_backend/services/session_monitor.py` | 保持 sidebar activity-only 语义，修正重复 observation 消费 | 不新增方向字段；不把红点当 sender |
| `admin_backend/services/customer_service_session_ledger.py` | 原子绑定文字 enrichment；过滤未确认 synthetic context | 不存图片；不删除 immutable audit |
| `workflows/reply_evidence_builder.py` | 从现有 ledger context 构建有界可信 `history_text` | 不改变函数签名或 Brain 外层字段 |
| `workflows/customer_service_brain.py` | 快速通道数据门控；recovery 保留紧邻可信多模态文字 | 不加图片专用回复模板；不改回复所有权 |

不得修改语音实现；视觉与语音不得互相 import。核心程序在视觉插件缺失或失败时必须继续运行。

## 6. 严格实施顺序与逐项门禁

### 阶段 A：先补失败的 characterization tests

先新增测试并确认当前代码会失败：

1. self `[图片]` 预览不得生成 customer placeholder；
2. self 识图落 ledger 后，客户文字追问的 Brain 输入必须含 `vision_summary`；
3. 同一 self occurrence 普通文字轮次不得再次视觉调用；
4. `low_authority_fast + latest_turn_only_candidate` 同时存在仍保留紧邻 self 图片文字；
5. 同屏左右图片方向互斥。

阶段 A 不改生产逻辑。

### 阶段 B：只修方向和路径互斥

只实施 R-01、R-02、R-03、R-04、R-05。门禁：

- 方向回放全通过；
- self-only 不创建回复任务；
- customer-only 仍进入原视觉插件；
- 不修改 Brain prompt/evidence。

阶段 B 未通过，不进入 ledger/Brain 修改。

### 阶段 C：只修原子持久化和去重

只实施 R-06、R-07、R-11、R-12、R-13。门禁：

- 重启、重复轮询、同图重发、多图同批通过；
- 无图片落盘；
- 现有 summary 可幂等读取；
- 不修改 Brain reply 策略。

### 阶段 D：只修 Brain 上下文消费

只实施 R-08、R-09、R-10。门禁：

- Brain 输入 fixture 的外层字段完全不变；
- 许聪场景中 `history_text` 包含小女孩/艾莎裙文字摘要；
- Brain 仍是唯一回复作者；
- 普通短问候继续走快速通道。

### 阶段 E：全矩阵回归和真实微信验收

各阶段都通过后，才允许组合运行多会话、插件矩阵和真实微信测试。发现缺陷必须回到对应修复项，不允许跨项打补丁。

## 7. 必须新增的测试矩阵

### 7.1 方向与 occurrence

- sidebar `[图片]` + 最新 self 图片；
- sidebar `[图片]` + 最新 customer 图片；
- 同屏先 customer 后 self；
- 同屏先 self 后 customer；
- 同一 pending 下多张同方向图片；
- 同一 pending 下 customer/self 混合图片；
- 一个 pending 下混有已完成旧图和确定新图，只处理确定的新 occurrence；
- 一个 pending 下的新旧 occurrence 无法唯一关联时，进入 `ambiguous` 且物理右键为零；
- 方向候选并列、窗口遮挡、图片只露一部分；
- 同一图片重复观察与相同图片重新发送。

### 7.2 当前剪贴板硬规则

- 正确方向右键、菜单复制、序号变化、有效图片；
- 右键点错列、复制项缺失、序号不变、文本剪贴板、空剪贴板；
- Provider 成功、超时、failover、异常；
- 每个 occurrence 物理右键次数不超过一次；
- 所有分支无 PNG/JPG/WebP/BMP/meta/base64/path 落盘。

### 7.3 双向持久化

- customer：`sender=customer` + `vision_summary`；
- self：`sender=self` + `vision_summary`；
- self 记录不能进入 reply batch；
- unknown/ambiguous 不得伪装成 customer/self；
- enrichment 写失败不产生假成功；
- 重启后成功文字结果可恢复且不重新识图。

### 7.4 Brain 消费闭环

必须新增完整场景，而非只测 ledger：

```text
客服发送图片
-> self current clipboard vision 成功
-> ledger 保存 sender=self + vision_summary
-> 客户发送任意自然指代文字
-> 不再次调用 vision
-> Brain 输入现有 history_text 含该 vision_summary
-> BrainPlan 基于该上下文直接回答
-> guard/final polish/发送保持原链路
```

测试至少覆盖：

- “你刚发给我的是啥图”；
- 不含固定关键词的口语指代；
- 错字、短句、追问、连续两条文字；
- `low_authority_fast` 候选；
- `latest_turn_only_candidate` 候选；
- 两者同时存在；
- `RawMessageStore` 开启与关闭；
- 图片与当前问题无关时 Brain 可以忽略，而代码不替 Brain 决定。

以上 Brain 消费测试必须使用可检查输入的确定性 Brain spy/stub，直接断言 Brain 收到的既有字段和值；不得只依据模型最终碰巧回答正确来判定通过。随后再以真实 Brain 做语义回归，两者不能互相替代。

### 7.5 合同、隔离和多会话

- 旧公开 import path、函数签名、返回键和 payload fixture 的字段集合、类型、默认值、nullability 与错误语义逐项不变；
- core only、core+voice、core+vision、core+both、第三方插件、依赖缺失矩阵；
- 视觉插件缺失/加载失败时 core 与 voice 继续工作；已确认客户图片沿既有失败/Brain-handoff 边界处理，我方图片只内部审计，不产生客户回复；
- 私聊“许聪”和同名群成员不串；
- `session_key + conversation_type` 不匹配时不右键、不读取剪贴板、不发送；
- 一个会话视觉失败不阻塞其他会话；
- Brain First 静态所有权审计通过。

## 8. 性能门槛

本修复不能用更多重复识图换正确性：

- 方向解析复用当前捕获表面，不增加视觉 LLM；纯结构计算目标增量应低于 300ms。
- 一个新图片 occurrence 最多调用一次视觉理解主事务；Provider failover 只能复用同一内存图片。
- self 图片后的文字追问不得再次执行右键或视觉 LLM，只执行正常 Brain 调用。
- 无图片的普通文字轮次不得进入视觉模块。
- prompt 只加入最近、方向明确、已 enrichment 的有界多模态文字；不得恢复整个 ledger。

测试报告必须分别记录：结构方向耗时、右键复制耗时、视觉 LLM 耗时、ledger 写入耗时、后续 Brain 耗时和端到端耗时，不能只报总时间。

## 9. 验证命令与交付证据

实施后至少运行：

```powershell
python -m py_compile apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py apps/wechat_ai_customer_service/optional_plugins/vision/trigger.py apps/wechat_ai_customer_service/optional_plugins/vision/compatibility.py apps/wechat_ai_customer_service/workflows/customer_image_turn_router.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py apps/wechat_ai_customer_service/admin_backend/services/session_monitor.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_session_ledger.py apps/wechat_ai_customer_service/workflows/reply_evidence_builder.py apps/wechat_ai_customer_service/workflows/customer_service_brain.py
python apps/wechat_ai_customer_service/tests/run_customer_image_turn_router_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multimodal_session_context_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_scheduler_current_image_bridge_checks.py
python apps/wechat_ai_customer_service/tests/run_wechat_image_save_capture_contract_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_brain_contract_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_external_contract_compat_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_optional_plugin_matrix_checks.py
python apps/wechat_ai_customer_service/tests/run_brain_first_static_architecture_audit.py
git diff --check
```

并新增两个聚焦测试入口：

- `run_customer_service_bidirectional_image_direction_checks.py`
- `run_customer_service_self_image_brain_context_checks.py`

交付报告必须包含：

1. 每个 R-01 至 R-13 的独立测试结果；
2. 许聪现场 fixture 的重放结果；
3. Brain 实际输入中保留的图片文字、且不存在图片内容的证据；
4. 视觉调用次数和右键次数；
5. tenant runtime、临时目录和 prompt archive 无新增图片文件/路径/base64 的扫描结果；
6. 外部合同 fixture 前后对比；
7. 多会话无串线、无错右键、无错发证明。

## 10. 回滚与数据安全

- 不执行状态格式迁移，不删除 ledger event，不修改外部配置。
- 生产修改按阶段独立提交；任一阶段失败，只回滚该阶段代码，不回滚或覆盖用户数据。
- summary 污染修复采用读取/投影过滤和幂等重建，不破坏 immutable audit。
- 历史图片文件不在本任务中删除；生产代码继续拒绝读取它们。
- 回滚后旧调用方、旧 import 和旧状态文件仍可读取；不得要求人工改 JSON。

## 11. 闭环完成定义

只有同时满足以下条件，才可宣告修复完成：

1. sidebar 媒体预览不再授权方向；
2. 每个图片 occurrence 由结构唯一标记为 customer 或 self；
3. customer/self 两条路径互斥，方向不明不猜测；
4. 双向图片均只保存 LLM 文字理解和现有方向字段，不保存图片内容；
5. self 图片不触发回复，但其文字能在后续客户追问时进入 Brain；
6. 同一 occurrence 不重复右键、不重复识图，相同图片重新发送仍能分别记录；
7. `low_authority_fast` 和 context recovery 不再裁掉紧邻可信多模态上下文；
8. 未确认 synthetic placeholder 不再污染 ledger summary 或 Brain；
9. 图片失败有确定终态、内部告警或 Brain 处理，不静默、不死循环；
10. 所有客户可见回复仍由 Brain 编写；
11. 外部接口、字段、框架、RPA 工作方式和插件合同全部不变；
12. 单元、合同、插件、多会话、真实回放和无图片落盘审计全部通过。

## 12. 开发前审计结论

本方案属于代码机制层闭环修复，不需要更换 Scheduler、Brain、ledger、RPA 或插件框架，也不需要结构化约束客户回复。可在现有接口和字段不变的前提下实施。

审计确认的关键约束是：

- 必须先修方向，再修持久化，再修 Brain 消费；顺序不可颠倒；
- 不允许通过关键词补丁代替通用的邻接多模态上下文；
- 不允许恢复图片文件、截图裁切或历史资产读取；
- 不允许用 self 识图成功掩盖 customer 假占位，也不允许用 context recovery 掩盖方向错误；
- 不允许以“测试写入 ledger 成功”代替 Brain 端到端消费验收。

按 R-01 至 R-13 和阶段 A 至 E 实施并全部通过后，才能进入手动微信验收。

## 13. 开发方案闭环审计

本节审计的是“方案是否留下设计漏洞”，不是用文档代替实施后的代码审计。结论如下：

| 审计维度 | 对应条目 | 审计结果 |
| --- | --- | --- |
| 根因是否被拆开 | R-01 至 R-13 分别处理触发、方向、双路径、原子提交、去重、Brain 消费、快速通道、恢复、启动和历史污染 | 通过；每项有独立现状、修改、禁止与验收，不靠后续项掩盖前项 |
| 双向图片是否都记录 | R-03、R-04、R-06 | 通过；customer/self 都写既有方向和 LLM 文字，self 明确禁止触发回复 |
| 是否仍可能“无方向” | 2.2、2.3、3、3.1、R-01、R-02、R-05 | 通过；sidebar 只触发，聊天区结构才定方向，不明即 fail closed |
| 是否可能重复识图 | 2.4、3.1、R-04、R-07、R-11 | 通过；逐 occurrence 最多一次右键，后续追问只读文字结果 |
| 是否重新引入错误读图方式 | 0、2.4、7.2 | 通过；唯一内容源仍是目标图右键复制后的当前剪贴板，无裁切、文件、历史图或旧剪贴板回退 |
| 是否把图片内容错误当业务事实 | R-08、R-09、R-10 | 通过；图片理解仅是会话上下文，产品事实仍受原权威资料约束，指代判断由 Brain 完成 |
| Brain 是否真实能消费 | R-08、R-09、R-10、7.4 | 通过；既有 ledger 文字投影进入现有 history 字段，并覆盖 RawMessageStore 关闭的现场配置 |
| 是否产生本地客户话术 | R-03、R-04、R-12、5、7.5 | 通过；失败、guard、视觉和 Scheduler 均不编写回复，Brain 仍为唯一作者 |
| 接口和字段是否变化 | 2.1、3、3.1、5、7.5 | 通过；只允许私有内部对象/helper，公开路径、签名、字段、类型、默认值、错误语义全部冻结 |
| 是否破坏插件隔离 | 5、7.5 | 通过；vision 独立可选、懒加载，voice 不改且不互相 import，缺失矩阵纳入测试 |
| 是否可能跨会话错读/错发 | 2.3、2.4、3.1、R-06、R-11、7.5 | 通过；解析、每次右键前和发送链路均维持严格 session identity 边界 |
| 失败是否会静默或死循环 | R-06、R-12 | 通过；每个失败有有限重观测、既有告警/Brain 边界和资源释放，不读旧图止血 |
| 旧污染如何处理 | R-13、10 | 通过；不删 immutable event，只在现有投影中幂等排除假占位 |
| 性能是否有退化通道 | R-04、R-07、R-09、8 | 通过；普通文字零视觉调用，self 后续追问零重复识图，逐阶段记录耗时 |

### 13.1 冲突审计

- 本文没有要求新增、删除或改名任何模块间接口、共享字段、队列、任务类型、状态文件或 error/reason code。
- 本文没有恢复图片文件保存；“双向都存”严格指保存既有方向标记与 LLM 文字理解。
- 本文没有要求 Brain 接受新的外层结构；上下文只投影到既有 `conversation.history_text/conversation_summary`。
- 本文没有用客户问法关键词判断图片指代；代码只保留可信邻接数据，语义仍由 Brain 判断。
- 本文没有通过图片内容、颜色、车型或 OCR 判断方向；这些信息在方向确认之后才可由视觉 LLM 理解。
- 本文没有让 self 图片进入客户发送链路；self 只补历史，真正客户文字到达后才由 Brain 决定是否回复。

### 13.2 审计结论

开发前方案审计通过，未发现需要改变框架、外部接口或共享字段才能解决的阻塞项。实施时仍必须按阶段 A 至 E 执行：先用失败测试锁定现状，再逐项修改；任何阶段若出现合同差异、图片落盘、重复右键、跨会话或非 Brain 客户话术，立即判定该阶段失败，不得进入下一阶段。

## 14. 实施与内部验证记录（2026-07-18）

本轮已完成阶段 A 至 E 的内部代码实施和非实盘验证，真实微信操作留给人工手测。实施结果按修复域收束如下：

| 修复域 | 落地结果 | 内部验证 |
| --- | --- | --- |
| R-01 至 R-05：方向与路径互斥 | sidecar 在同一表面输出 customer/self 双向结构 envelope；Scheduler 只在当前图片 pending 且结构方向确认后选择唯一当前 occurrence；self 不再创建 customer proxy，普通文字不再重启旧图 | 双向方向 7/7；router 7/7；当前图片桥 2/2 |
| R-06、R-07、R-11 至 R-13：持久化、去重与污染 | customer/self enrichment 必须实际命中 ledger 消息才算成功；未 enrichment 的图片占位不进入 context summary；旧 summary 每次读取都幂等重建；self 只补上下文、不生成回复任务 | 多模态上下文 7/7；多会话 Scheduler 164/164；剪贴板取图合同 7/7 |
| R-08 至 R-10：Brain 消费 | 新增中立内部文字投影，从既有 ledger recent messages 把方向明确、已 enrichment 的最近图片摘要放入原有 `conversation.history/history_text`；快速通道与 latest-turn recovery 均不能裁掉紧邻可信图片文字 | self→客户追问闭环 5/5；Brain preflight 9/9；Brain contract 全通过；workflow 125/125 |
| 外部合同与模块隔离 | 公开 import、函数签名、外层 payload、共享字段、语音/视觉插件协议均未改变；Brain 仍是客户可见回复唯一作者 | 外部合同 3/3；可选插件 7/7；Brain First 静态审计通过 |
| 图片数据边界 | 识图内容仍只来自目标方向右键复制后的当前剪贴板；内存图片在调用后释放；ledger/Brain 只保留文字，不恢复文件、裁切、路径、base64 或历史图片回退 | 图片理解合同 6/6；车辆图片检索 7/7；本轮 runtime/tenant 扫描新增或改写图片文件 0 个 |

性能基准使用 20,000 次纯内部循环：结构方向投影平均 `0.0134ms`，Brain 多模态文字投影平均 `0.0060ms`，合计平均 `0.0194ms`，远低于 300ms 增量门槛。图片右键、视觉 LLM 与真实 Brain 的实际耗时必须由随后人工微信手测记录；内部测试未伪造该实盘数据。

最终内部审计通过：Python 编译、聚焦回归、合同快照、插件矩阵、Brain 所有权、多会话隔离以及 `git diff --check` 均通过。当前交付状态为“代码与内部验证完成，等待真实微信手测”，不得在人工手测前宣称真实桌面链路已验收。
