# 微信 AI 客服单 Brain、当前消息优先与全链路减负完整优化方案

日期：2026-07-18
状态：**已按本文完成代码实施、内部审计与回归测试；待用户手工实测**

本文引用并服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

本文承接并收束：

- [customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md](customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md)
- [customer_service_runtime_single_brain_cleanup_design_20260717.md](customer_service_runtime_single_brain_cleanup_design_20260717.md)
- [customer_service_context_rupture_recovery_20260710.md](customer_service_context_rupture_recovery_20260710.md)

以下旧方向不再作为本方案的实施依据：

- [brain_adaptive_lightweight_reply_plan_and_audit_20260713.md](brain_adaptive_lightweight_reply_plan_and_audit_20260713.md) 已明确归档；本方案不增加“轻量 Brain 先路由、完整 Brain 再作答”的前置模型调用。
- 现有 `context_recovery`、车型追问词表和上下文指针可继续保留为兼容审计数据，但不得继续扩展成语义路由器或回复决策器。

## 1. 最终审计结论

本方案可以进入后续实施阶段，理由如下：

1. **通用性通过**：方案不依赖奥迪、蔚来、Polo、某个账号、某种问法或某组中文关键词；同样适用于商品切换、图片切换、闲聊、追问、纠正和上下文断裂。
2. **反结构化倾向通过**：不新增 intent schema、continuity schema、车型追问词表、上下文相关性分数或本地回复分支；保留既有 BrainPlan 兼容合同，但不再给它外叠一套语义状态机。
3. **减负方向通过**：正常路径固定为一次主 Brain 和一次必须的最终可见润色；移除正常路径中的前置 LLM 路由、重复 evidence、宽泛 reviewer 和多处各自拥有的 repair/retry。
4. **回复质量通过但有硬控制**：商品事实、正式知识、图片理解、会话事实、硬安全、事实校验、最终润色和发送前会话确认均保留；减少的是重复判断和无权创作回复的模型调用，不是事实来源或安全边界。
5. **边界会话通过**：同一个测试会话可以连续换车型、插入无关图片、跳到闲聊或重新问另一辆车；Brain 不强迫上下文连贯。能独立回答就回答最近消息，确需指代信息时只问一个最小澄清问题。
6. **外部合同通过**：不增加、删除、改名或重解释任何模块间接口、字段、函数签名、返回值、配置、事件、状态文件或路径；新增实现只能是模块私有内存对象、私有 helper 和测试。
7. **插件隔离通过**：不修改识图和语音的外部合同，不让两者互相 import，不让插件参与回复写作、调度状态或语义路由。

审计发现的最大风险不是方案本身，而是实施时又把它做成“更多分类字段 + 更多 if/else + 更多补丁词表”。因此本文把禁止项和逐阶段闸门写成强制验收条件。

## 2. 当前问题的证据与根因

### 2.1 正常一轮存在过多模型阶段

当前 Brain First 链路可能依次发生：

```text
前置 evidence / preflight
  -> 主 Brain
  -> 非法输出重试
  -> deterministic quality
  -> semantic reviewer
  -> quality repair
  -> repair 后再次 reviewer
  -> guard repair
  -> final visible polish
  -> scheduler 整轮恢复或重排
```

普通业务轮次理论上可能触发 5 至 7 次 LLM 请求。近期审计样本已经出现：

- 主 Brain 约 6.02 秒，semantic reviewer 约 11.88 秒，quality repair 约 13.52 秒，三段合计约 31.42 秒，尚未计入捕获、证据和发送。
- 另一轮主 Brain 约 7.65 秒，随后同 capture 的无效计划重试约 24.21 秒。
- 2026-07-17 状态样本中，planner 总耗时达到 83.6 至 153.7 秒；Brain 前还有 30.6 至 48.9 秒未被合理收束的同步工作。

结论：慢不是简单的“模型速度不够”，而是多个阶段重复理解、重复取证、超时累加和重试所有权分散。

### 2.2 上下文已经被多套局部机制同时解释

当前代码同时存在：

- `AMBIGUOUS_PRODUCT_FOLLOWUP_TERMS` 和 `is_ambiguous_product_followup()`；
- `ambiguous_followup_product_drift` 的特定修复指令；
- `context_recovery` 的多信号启发式判断和 `latest_turn_only_candidate`；
- `last_product_id`、`recent_product_ids`、`conversation_strategy_state`、`conversation_interaction_state` 等多个上下文提示；
- 针对短社交、短商品问句、证据缺口、图片、追问的不同 preflight/profile 分支。

这些机制单独看都有局部理由，但叠加后会产生三个问题：

1. 代码层开始替 Brain 判断“客户在指哪辆车”和“这句话是否延续上文”。
2. 同一条消息可能被多个规则给出不同方向，后加入的补丁只能继续覆盖旧补丁。
3. 测试会逐渐变成“命中词条测试”，而不是对真实语义、上下文切换和事实边界的测试。

### 2.3 证据包重复且过宽

近期对 `许聪` 会话的离线 dry run 中，即使当前车型锚点已经明确，最终 plan 的商品权威选择仍可能为空，同时 evidence 审计携带约 16 个商品/目录证据标识。说明当前链路存在“信息很多，但焦点和权威绑定不够清楚”的问题。

重复读取全库、重复构建 RAG/knowledge/evidence、把宽目录候选交给每一层，不会自然提升质量，反而会：

- 增加 prompt、模型耗时和干扰；
- 让旧车型压过当前明确车型；
- 让 reviewer 和 repair 再次重复同样的理解工作。

### 2.4 超时不等于物理执行已经停止

现有 scheduler 和 LLM wall-timeout 可能在逻辑超时后移除 future 或返回，但底层线程/网络请求并未真正结束。结果可能是：

- 同一 capture 被再次提交；
- 旧请求继续占用 worker；
- 晚到结果失去清晰归属；
- 后续消息捕获到了，却没有真实可用的执行容量。

这既增加延迟，也会表现成“第一轮回了，第二轮不回”。该问题必须用执行所有权和统一 deadline 解决，不能继续调大并发或增加重试。

## 3. 目标与非目标

### 3.1 目标

1. 正常轮次只保留一个语义决策中心：`customer_service_brain`。
2. 当前消息优先，但不是机械丢弃历史；历史只在语义相关时被 Brain 使用。
3. 上下文接不上、车型突然切换或测试内容互不相关时，仍由 Brain 对最近消息作出可见回应。
4. 一轮只构建一次权威 evidence，并在该轮所有阶段复用同一快照。
5. 正常路径只有两次 LLM：主 Brain + 必须的 final visible polish。
6. 任何异常路径都有全链路总时限和唯一 retry/repair 所有者。
7. 保持事实正确、风险边界、多会话隔离、图片/语音上下文和 RPA 发送安全。

### 3.2 非目标

- 不重写客服框架。
- 不改变 BrainPlan、scheduler、RPA、商品库、识图或语音的外部合同。
- 不用一套新的 JSON schema 描述用户意图、上下文连续性或回复路线。
- 不建立车型词表、追问短语表、问候表或账号专用分支。
- 不让本地代码、guard、reviewer、RAG、final polish 或插件创作客户可见回复。
- 不把大风车完整源 payload、受限字段或上游实时 API 放入聊天热路径。
- 不承诺 Brain/provider 完全不可用时仍由本地话术回复；按既有底线，此时必须阻断发送并内部告警。

## 4. 不可突破的设计原则

### 4.1 Brain 唯一作答

客户可见文字只能来自：

- `brain`；
- 接收明确反馈后的 `brain_repair`。

其他层只能提供事实、提示风险、验证、轻度自然化或执行发送。它们不得生成、拼接、替换或补写客户话术。

### 4.2 当前消息优先，相关上下文才继承

Brain 每轮遵循自然语义原则，而不是结构化路由：

1. 当前消息明确提出新车型、新商品、新图片或新问题时，以当前消息为主。
2. 当前消息自然承接上文且指代明确时，使用相关历史。
3. 当前消息指代不足时，直接问一个最小澄清问题，例如确认“您问的是刚才哪一台”，而不是沉默或绕行。
4. 当前消息和历史无明显关系时，就事论事回答当前消息，不强行把旧车型、旧预算或旧销售话题拉回来。

`last_product_id` 只能是一个事实指针或检索提示，不能成为“客户一定在问它”的语义判决。

### 4.3 上下文不连贯不是硬失败

以下情况本身都不得触发无回复、阻断或转人工：

- 同一个会话连续切换多辆车；
- 上一轮聊 A4L，下一轮直接问 ES6；
- 客户或客服发过一张图片，随后问无关问题；
- 历史内容很脏、很长或来自反复测试；
- Brain 判断不出当前短指代对应哪一个旧对象。

前三种能直接答就直接答；最后一种由 Brain 发出最小澄清。只有真正的硬安全、权限、身份、事实授权或人工审批边界，才允许进入 handoff。

### 4.4 事实权威不减

- 车辆名称、价格、库存、车况、里程、位置和可售状态：只认 product master。
- 政策、贷款、置换、合同、售后、审批和承诺边界：只认 formal knowledge。
- 图片理解：只作为带来源的当前/历史会话材料，不能自行授权商品事实。
- 当前会话内容：只在当前会话内有效。
- 历史聊天、RAG、经验池和风格样本：只辅助表达，不授权事实。

### 4.5 不新增语义结构

本轮禁止新增：

- 新 intent 字段或枚举；
- 新的 continuity/relevance/route/confidence schema；
- 新商品专用关键词、正则或追问短语表；
- 以消息长度、标点、车型词命中直接决定回复路线的规则；
- 用 `last_product_id`、图片相似度或候选数量直接替代 Brain 的上下文理解。

允许保留的结构仅限已经冻结的兼容 payload、事实权威记录、会话/消息身份、来源、时序、安全和发送状态。

## 5. 目标运行链路

### 5.1 正常路径

```text
已捕获消息 + session ledger
  -> 私有上下文编译（无 LLM）
  -> 一次本地权威 evidence 构建（无上游实时调用）
  -> 一次 customer_service_brain
  -> deterministic hard guard
  -> 一次必须的 final visible polish
  -> freshness / target / session 复核
  -> RPA send
```

正常路径固定为两次 LLM 调用：

1. 主 Brain：理解、上下文取舍、事实引用、回复策略和客户可见初稿。
2. final visible polish：验证并轻度自然化，不改变事实、策略、推荐或风险姿态。

### 5.2 可修复异常路径

当且仅当存在一个明确、可修复的问题时：

```text
主 Brain
  -> 明确失败反馈
  -> 最多一次 brain_repair
  -> hard guard
  -> final visible polish
```

一轮共享一个 Brain repair 配额。非法输出、证据引用错误、硬 guard 的可修复反馈、final polish 的策略性阻断不能各自再拥有一套无限重试。配额用完仍不可采用时，阻断并内部告警，不发送旧回复或本地兜底。

如果 final polish 在 Brain repair 之前已经执行并发现必须回 Brain 的问题，repair 后可以再执行一次 polish；这属于罕见异常路径，不是正常调用预算。

### 5.3 高风险复核路径

独立 semantic reviewer 只在以下事实性条件出现时运行：

- Brain 声称的权威事实与 evidence 无法一一对应；
- 同一权威事实存在冲突版本；
- 涉及价格、库存、贷款、合同、违法要求、明确承诺等硬边界，且 deterministic guard 无法仅靠已有权威数据判定；
- 图片实体锚点与 Brain 采用的商品证据发生明确冲突。

“回复不够直接”“可能没接上文”“车型追问像不像”“措辞风格一般”不再触发独立 reviewer。正常语义质量由主 Brain 和必须执行的 final polish 共同承担。

reviewer 只能返回反馈，不能返回客户回复。若需修复，仍消耗同一个 Brain repair 配额。

### 5.4 调用次数上限

| 路径 | 主 Brain | reviewer | Brain repair | final polish | 总调用 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 正常 | 1 | 0 | 0 | 1 | 2 |
| 普通可修复异常 | 1 | 0 | 最多 1 | 1 至 2 | 最多 4 |
| 高风险复核 | 1 | 最多 1 | 0 至 1 | 1 | 最多 4 |

高风险上限是故障保护，不是目标常态。reviewer 复核/repair 必须发生在首次 final polish 之前；如果已经走过 reviewer 链，final polish 再阻断时不得另起第二条 reviewer + repair 链。另一种异常是跳过 reviewer、由首次 final polish 把明确反馈交给一次 Brain repair，再做第二次 polish；两类异常路径互斥，因此总调用仍不超过 4。验收时正常业务、上下文切换和普通图片追问不得进入 reviewer。

## 6. 上下文编译方案

### 6.1 事实源与提示窗口分开

- Session Ledger 是已观察对话事实源，不能因为 prompt 裁切而丢失。
- Brain prompt 只携带最近 8 至 12 个有意义 turn 的原始自然语言内容，具体上限通过私有预算控制，不新增配置字段。
- 更老内容仍保留在 ledger；已有且新鲜的异步摘要可以作为非权威背景使用，但不得同步调用 LLM 现算摘要。
- 摘要、`last_product_id`、strategy state 和 recovery hint 都可重建，只是缓存/提示，不是对话事实本身。

### 6.2 什么必须进入最近窗口

- 当前客户消息，保持最高优先级；
- 最近真实发送成功的客服回复；
- 客户发送图片的识图自然语言摘要及方向标记；
- 客服自己发送图片的识图自然语言摘要及方向标记；
- 最近相关的文本、语音转写和明确纠正；
- 必要的时间顺序和消息身份，用于防串会话、去重和引用。

未发送成功的旧草稿、旧 ready reply、调试日志、OCR 会话标题、联系人名、内部状态字段和模型错误不得伪装成对话内容。

### 6.3 代码只做机械清理，不做语义裁决

上下文编译器可以确定性处理：

- session/message/sender 身份；
- 消息顺序、去重、已发送/未发送状态；
- OCR 元数据与正文分离；
- 图片/语音已有摘要的方向标记；
- 明确的运行日志、系统标记和空占位清理；
- prompt 字符预算和最近窗口裁切。

它不得判断：

- “这句话一定指向上一辆车”；
- “客户已经换车型”；
- “这段历史一定无关”；
- “这是一条安全闲聊，所以可以走本地快速回复”。

这些都交给 Brain 在自然语言上下文中判断。

### 6.4 高污染单会话的处理

用户长期用同一个 `许聪` 会话切换车型，作为强制边界用例：

1. 当前明确提到 ES6，就不能被上一轮 A4L 覆盖。
2. 当前只说“这台呢”，且紧邻一张已理解的图片，优先让 Brain结合该图片摘要判断。
3. 当前只说“车况怎么样”，而最近有多个同等可能对象，Brain 只问一个简短澄清问题。
4. 当前突然问“你们几点下班”，直接回答当前问题，不继续推荐旧车型。
5. 当前再问 A4L 价格，重新从 product master 取 A4L 权威事实，不受中间 ES6/Polo 对话污染。

这些行为由同一条通用原则产生，不为每种句子建立单独分支。

## 7. Evidence 一次构建与聚焦

### 7.1 一轮一个私有只读快照

同一 planner worker 内只构建一次 evidence。该快照：

- 只存在于模块私有内存；
- 不写入新的 event/state/config/payload 字段；
- 被主 Brain、hard guard、必要 reviewer、Brain repair 和 final polish 复用；
- 不允许各阶段再次读取全库、再次跑 RAG 或再次调用大风车。

旧公开函数仍保留原签名；内部兼容门面把同一份现有形状数据传给旧投影。没有私有快照的外部直接调用仍按旧行为工作。

### 7.2 先聚焦，再给详情

本地 evidence builder 按以下通用信息聚焦候选，但不替 Brain做最终语义判断：

- 当前消息中的明确商品实体；
- 当前或紧邻图片已经生成的商品匹配候选；
- 最近会话中的候选指针；
- product master 的现有别名、模糊检索和语义索引结果。

输出给 Brain 的内容遵循：

- 一个明确对象：给该对象全部允许展示且与本轮有关的详情；
- 比较/推荐：给最相关的少量候选摘要，通常 2 至 3 个；
- 指代不清：给必要候选线索，让 Brain澄清，不把整个目录塞进 prompt；
- 未命中：Brain基于当前消息自然说明或澄清，不编造商品。

图片相似度只负责提供候选证据，不直接宣判客户正在问哪辆车。

### 7.3 正常路径取消同步 LLM preflight

正常路径不再先调用一个 LLM 判断要不要查证据。替代方式是：

1. 本地 evidence builder 一次完成已有权限范围内的检索；
2. 主 Brain直接使用聚焦后的权威证据；
3. 若 Brain产出事实无法被 hard guard 绑定到权威来源，才把这个具体缺口作为一次 repair 反馈；
4. 若没有足够事实，Brain可以在已知边界内回答或澄清，不能用本地模板，也不能因为“证据可能不够”先沉默。

现有 preflight 相关外部字段、函数和 fixture 保持兼容；Brain First 正常路径可输出与既有禁用/no-op 语义一致的投影，但不再产生额外模型调用。

## 8. 各层职责收束

| 层 | 保留职责 | 明确禁止 |
| --- | --- | --- |
| Capture/RPA | 捕获、方向、顺序、去重、会话绑定、发送前目标确认 | 判断客户意图、选车型、写回复 |
| Session Ledger | 保存双方实际对话和多模态摘要 | 把旧草稿当成已发送事实 |
| Context compiler | 机械清理、最近窗口、预算、元数据分离 | 判定上下文语义相关性 |
| Product/evidence | 提供允许展示的权威事实和候选 | 写回复、用历史/RAG授权商品事实 |
| Brain | 理解当前消息与相关历史、选择事实、制定策略、写可见回复 | 越过商品/政策/安全边界 |
| Deterministic guard | 权威引用、受限字段、硬安全、空/截断、会话绑定 | 审美、语气、车型指代猜测 |
| Semantic reviewer | 罕见事实冲突和高风险不确定性 | 常态运行、写回复、因软意见吞回复 |
| Final polish | 必须执行的轻度自然化与最终可见检查 | 改事实、改策略、换推荐、独立写答案 |
| Scheduler | 生命周期、deadline、capacity、freshness、send | 拥有语义重试或客户话术 |

## 9. 现有链路的减法清单

| 当前负担 | 目标处理 | 兼容要求 |
| --- | --- | --- |
| 同步通用 intent advisory | Brain First 正常路径不执行 | 旧字段保留 no-op/审计投影 |
| 多次 evidence pack | 合并为一次私有快照 | 旧公开入口和返回形状不变 |
| LLM preflight | 正常路径取消 | 旧字段、函数、reason 值不改名 |
| short/social/profile 语义分流 | 主 Brain统一理解 | 不新增轻量路由 schema |
| 车型追问词表 | 从阻断/修复判决降为无权审计兼容 | 不继续扩词；公共符号若已被依赖则保留 |
| context recovery 语义裁切 | 降为机械噪声提示；Brain判断相关性 | 既有状态/字段继续可读 |
| routine semantic reviewer | 取消 | 只在事实冲突/硬风险触发 |
| 多处 quality/guard/polish repair | 共享一次 Brain repair 配额 | 原审计字段保持现有形状 |
| scheduler 与 Brain 各自 retry | Brain拥有同 turn repair；scheduler只恢复真实结束的物理任务 | 状态和值域不改 |
| additive stage timeouts | 一个私有全链路 deadline | 不新增配置字段 |
| 重复 provider 故障等待 | 私有健康状态与熔断/切换 | provider 对外配置不变 |

## 10. 延迟与执行生命周期

### 10.1 共享总时限

一轮开始时在 planner worker 私有内存建立 monotonic deadline。各阶段读取剩余时间，而不是每层重新获得完整 timeout。

目标预算：

| 阶段 | 目标 |
| --- | ---: |
| 上下文 + evidence | p95 小于 0.5 秒 |
| 正常主 Brain | 常态 8 至 12 秒预算 |
| final visible polish | 常态 3 至 5 秒预算 |
| 正常 planner 端到端 | p50 不高于 12 秒，p95 不高于 22 秒 |
| 高风险/一次修复 | 硬上限 30 至 35 秒 |

上述是实施后的同 provider、同消息样本目标，不把 RPA 物理点击等待混入 Brain planner 指标，也不能通过缩短 timeout 后静默失败来“达标”。

### 10.2 唯一 execution lease

每个 capture 在任一时刻只能有一个真实 planner execution lease：

- future 未物理结束前始终占用 capacity；
- soft timeout 不能把正在运行的请求伪装成已经取消；
- 同 capture 未结束时禁止再次 submit；
- transport 真正结束后才允许恢复；
- scheduler crash recovery 最多一次，且不能与 Brain repair 并行。

lease、deadline、provider health 都是进程私有实现，不进入任何冻结 state/event/payload。

### 10.3 Provider 熔断与切换

同一 provider 在短时间内连续 timeout/transport failure 后，后续阶段不得继续逐层等待同一条坏线路。使用模块私有健康状态：

- 只处理 transport 可用性，不评价回复语义；
- 有已批准备用 provider 时按现有配置切换；
- 无可用 provider 时快速失败、阻断并告警；
- 不发送本地兜底话术。

## 11. 外部合同与插件边界

本轮按“零字段变化”实施，以下全部冻结：

- 现有 import path、公开类、函数、参数、默认值和返回类型；
- `process_target()`、`maybe_run_customer_service_brain()`、scheduler bridge 和 LLM config 的对外行为；
- 既有 event/state/config/JSON 的字段数量、字段名、类型、缺省值和值域；
- `ProductMasterStore`、Brain evidence 外层合同和大风车 V2 商品库调用缝；
- RPA capture/send/session/freshness/target 绑定；
- 识图和语音的插件合同、配置、生命周期及故障隔离；
- final visible polish 门禁和 Brain 唯一回复所有权。

内部收束时必须采用：

- 原文件保留兼容 facade；
- 私有 helper 不作为新 SDK，也不得形成新的跨模块 payload；第一阶段应留在职责所属模块内部，后续即使仅为缩小文件而拆出私有实现，其他既有模块仍只能通过原 facade 和原字段访问；
- 旧字段继续由 compatibility projector 生成原形 no-op/disabled 结果；
- 不要求外部调用者改 import 或适配新字段；
- 不读取大风车实时接口回答客户，只读本地 product master mirror。

## 12. 实施批次

### 批次 A：合同画像与行为基线

先不改变运行行为，锁定：

- 公开 import/signature/default；
- 典型 event/state/Brain/RPA payload fixture；
- 当前正常、repair、reviewer、timeout、handoff 的调用次数；
- 高污染单会话、多会话、双方图片上下文的现状；
- provider、planner、polish 和 RPA 分段耗时。

闸门：未取得可重复基线，不进入后续批次。

### 批次 B：先修物理执行所有权

- 增加私有 execution lease；
- 统一 planner/transport deadline；
- 确保逻辑超时不释放未结束 worker；
- 明确 Brain repair 与 scheduler recovery 的唯一所有权。

闸门：同 capture 任何超时条件下都不得存在两个物理执行实例。

### 批次 C：一次上下文与 evidence

- 在 planner worker 内建立私有 prepared context；
- 最近自然语言窗口包含双方真实文本、语音和图片摘要；
- 一轮只构建一次权威 evidence；
- 旧入口通过 facade 读取同一份现有形状投影。

闸门：一轮 evidence 构建计数必须为 1；外部 payload 逐字段相同。

### 批次 D：正常路径收束为两次 LLM

- 正常 Brain First 跳过同步 intent advisory 和 LLM preflight；
- Brain成功后不再实际运行旧 RAG/realtime/legacy generator；
- deterministic hard guard 后直接进入必须的 final polish；
- 旧审计字段由兼容 projector 保持。

闸门：普通问候、商品详情、明确追问、随机换车型、普通图片追问都必须为 Brain 1 次 + polish 1 次。

### 批次 E：语义补丁降权与 repair 合并

- `AMBIGUOUS_PRODUCT_FOLLOWUP_TERMS` 不再决定产品指代或触发阻断；
- `context_recovery` 不再强制删除全部历史，只做机械污染提示和兼容审计；
- semantic reviewer 改为事实冲突/硬风险按需；
- invalid/quality/guard/polish 的修复收束到共享一次 Brain repair 配额。

闸门：不得新增替代词表、枚举、regex 或 route schema。

### 批次 F：性能校准与灰度

- 离线多轮和本地双端口 cloud simulation；
- 相同 provider、相同 fixture 做前后耗时对照；
- 只启动客户端，由用户手工开启 AI 客服进行低频实测；
- 出现跨会话、事实错误或静默时回退该私有阶段，不迁移外部数据。

## 13. 强制测试矩阵

### 13.1 高污染单会话

至少覆盖以下连续序列，不允许拆成互不相关的单元测试规避污染：

```text
A4L 详细信息
-> 客户图片
-> “这台车况呢”
-> 改问 ES6 是否在售
-> 无关闲聊
-> 客服自己发送一张图片
-> “刚才发的是什么图”
-> 改问 Polo
-> “价格呢”
-> 再回到 A4L
```

验收：每轮都有 Brain 回复；明确新对象覆盖旧对象；真正模糊时只做最小澄清；无旧对象串入；双方图片摘要都可被 Brain 使用。

### 13.2 语义通用性

- 同一意思使用多种改写、错字、简称、口语和省略表达；
- 不出现测试词表中的表达也能正确处理；
- 当前消息与历史有关、部分有关和完全无关三类；
- 客户纠正“不是这辆，是另一辆”；
- 多候选比较、明确新车型、真正无指代对象；
- 问候、催促、异议、闲聊、政策、价格和看车流程。

测试断言结果和边界，不断言某个关键词命中了某条内部路线。

### 13.3 事实与安全

- 商品详情只来自 product master；
- 正式政策只来自 formal knowledge；
- 历史/RAG/图片摘要不能授权价格、库存和车况；
- VIN、车牌、成本价、底价和其他受限字段不进 Brain；
- stale product data 不得被说成实时在售；
- hard failure 只能 block + alert，不能本地兜底。

### 13.4 多会话与媒体

- 两个及以上会话并发，无 capture、context、reply 或 send 串绑；
- 客户图片和客服图片都有方向、识图摘要和历史记录；
- 无关图片仍进入理解和历史，但 Brain可判断与当前问题无关；
- 识图或语音插件缺失/失败不影响纯文字核心和另一插件；
- 插件不生成客户可见话术。

### 13.5 调用次数与性能

- 普通路径严格 2 次 LLM；
- 普通随机换车型不触发 reviewer 或 repair；
- 一轮 evidence build 恰好 1 次；
- 同 capture 同时物理 planner 数量恒为 1；
- repair 总配额为 1；
- 记录 p50/p95、超时率、provider 切换、block 原因和最终 send 结果；
- 不允许通过吞回复、缩短历史到失真或跳过 final polish 获得速度。

### 13.6 合同与架构

- 外部合同 snapshot 逐字段一致；
- Brain/RPA fixture 无变化；
- optional plugin matrix 全通过；
- Brain 唯一可见回复 owner 静态审计通过；
- 禁止 import 边界通过；
- 本地双端口 cloud simulation 通过；
- 工作区现有未提交改动不被 reset、checkout 或覆盖。

## 14. 可观测性与验收数据

新增观测只能写入私有诊断输出，不加入模块间 payload。每轮最少统计：

- context/evidence/Brain/reviewer/repair/polish 的耗时；
- evidence 构建次数；
- LLM 总调用次数；
- repair 配额消耗原因；
- planner 物理执行数量和 deadline 结果；
- 是否产生可采用 Brain reply；
- 是否被 hard boundary 阻断；
- send 前 target/session/freshness 结果。

日志不得保存完整 prompt、密钥、受限车辆字段或不必要的客户隐私。

交付前需要给出至少以下对照表：

| 场景 | 轮数 | 成功回复 | LLM p50/p95 | planner p50/p95 | reviewer 率 | repair 率 | 串会话/静默 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 普通商品咨询 |  |  |  |  |  |  |  |
| 高污染单会话 |  |  |  |  |  |  |  |
| 图片上下文 |  |  |  |  |  |  |  |
| 多会话并发 |  |  |  |  |  |  |  |
| 高风险/权威冲突 |  |  |  |  |  |  |  |

## 15. 明确禁止的实施方式

- 为“现车还在吗”“这台车况呢”等句子继续添加专用规则。
- 为某个车型、某个联系人或 chejin 账号添加回复分支。
- 用新字段保存 `current_topic`、`active_vehicle`、`continuity_score` 并让代码据此决定语义。
- 用模型先生成结构化路由，再调用另一个模型正式作答。
- 同步调用 LLM 总结历史后再调用主 Brain。
- 让 reviewer、guard、final polish 或 legacy synthesis 输出替代回复。
- 因软 reviewer 意见、上下文不连贯或历史污染吞掉安全且非空的 Brain 回复。
- 把全部商品目录、完整大风车 source payload 或不受控未知字段塞入 prompt。
- 逻辑 timeout 后重复提交仍在运行的 capture。
- 修改或新增模块间字段以方便内部重构。
- 为了降低平均耗时跳过 final visible polish、事实 guard、freshness 或 target/session 确认。

## 16. 复审矩阵

| 审计项 | 结果 | 控制条件 |
| --- | --- | --- |
| 通用性 | 通过 | 不依赖账号、车型、语言词表或固定问法；用污染会话和改写测试证明 |
| 反结构化倾向 | 通过 | 不新增语义 schema/route/score；现有语义词表降权且禁止扩展 |
| Brain 唯一回复权 | 通过 | 只有 `brain` / `brain_repair` 可写客户可见文字 |
| 当前消息优先 | 通过 | 明确新消息优先；相关历史才继承；不确定时 Brain最小澄清 |
| 不连贯仍回复 | 通过 | context ambiguity 是软问题，不是 block/handoff；Brain/provider 硬失败例外 |
| 商品与政策正确性 | 通过 | product master / formal knowledge 权威和 hard guard 不减 |
| 回复质量 | 通过但需回归 | 主 Brain保留完整语义能力，final polish 必须执行，高风险 reviewer 按需 |
| 减负 | 通过 | 正常 2 次 LLM、一次 evidence、共享 deadline、共享 repair 配额 |
| 外部合同 | 通过 | 零字段、零签名、零路径变化；compatibility facade + 私有实现 |
| 多会话/RPA | 通过 | capture/session/target/freshness/send 保护不变 |
| 语音/识图隔离 | 通过 | 不改插件合同，不交叉 import，不参与回复创作 |
| 大风车边界 | 通过 | 聊天只读本地镜像，不访问实时上游，不泄露受限字段 |

## 17. 最终 Go / No-Go 条件

可以进入代码实施，前提是严格按批次推进，并同时满足：

1. 先建立合同和行为基线，再改调用链。
2. 每批只改内部实现，不夹带字段、接口或数据迁移。
3. 正常路径两次 LLM、一次 evidence 的调用计数测试先于性能结论。
4. 高污染单会话是必须通过的主验收，不是特殊测试。
5. 上下文断裂、软 reviewer 或历史噪声不能成为无回复原因。
6. Brain/provider 真正失败时仍遵守 block + internal alert，不新增本地兜底。
7. 任一批次若需要新增语义字段、车型词表或本地路由才能通过测试，应判定设计实现偏航并停止，而不是继续补丁。

在这些条件下，本方案能同时实现：减少重复模型调用、降低 prompt 和线程阻塞、保留 Brain 的自然语义能力、保证商品/政策权威，并让反复切换车型的测试会话成为长期有效的鲁棒性基准。

## 18. 2026-07-18 实施结果

本次实施严格保留了既有模块、配置、状态、事件、Brain、RPA、识图、语音和商品库对外合同，只调整模块内部执行方式。落地结果如下：

1. `customer_service_brain` 每轮建立一个私有 monotonic deadline；主规划、备用线路、reviewer 和 repair 共享剩余时间，不再各自获得一套可叠加的完整超时。
2. 非法 JSON、证据校验、quality、guard 共用一次 Brain repair 配额；repair 已消耗后，scheduler 不再对同一语义失败重新启动一条修复链。
3. 普通文本轮次不再运行同步 LLM preflight，也不再二次重建 evidence；既有 preflight 字段仍以原形输出 no-op/disabled 审计结果。
4. `context_recovery` 只保留兼容审计作用，不再强制裁掉历史或替 Brain 判定当前对象。
5. Brain prompt 明确“当前消息优先、相关历史才继承、不确定时最小澄清”，最近窗口保留最多 12 个有效自然语言 turn，包含客户与客服双方的图片理解文本。
6. prompt 删除重复的 strategy、interaction、audit 和经验池内容；普通商品轮次只携带本轮需要的权威事实、最近历史和必要边界。
7. semantic reviewer 只为确定性错误、缺失商品权威锚点、明确高风险/硬安全边界运行。`no_relevant_business_evidence` 等既有软 advisory handoff 原因不再把问候、闲聊或上下文断裂升级为 reviewer 调用。
8. 空值、无来源且无实体内容的截断 `facts_claimed` 占位会在内部规范化时丢弃；任何包含实际值、来源或 ID 的事实声明仍执行原有严格权威校验。
9. scheduler 保持正在运行的 planner/polish 任务所有权，直到 worker 物理退出；普通 planner 语义失败不再由 scheduler 重复提交，final polish 反馈仅在本轮 Brain repair 尚未使用时保留一次既有恢复机会。
10. 没有添加车型、账号、联系人、问法、上下文连续性词表或本地客户话术分支；客户可见回复仍只来自 Brain，失败继续 block + internal alert。

涉及的主要内部实现文件：

- `workflows/customer_service_brain.py`
- `workflows/customer_service_brain_contract.py`
- `workflows/customer_service_brain_preflight.py`
- `workflows/customer_service_quality_reviewer.py`
- `admin_backend/services/customer_service_scheduler.py`
- `admin_backend/services/customer_service_scheduler_state.py`

新增的专项回归位于 `tests/run_customer_service_single_brain_context_slimming_checks.py`，只测试行为和硬边界，不依赖某个车型关键词命中某条本地路线。

## 19. 最终审计结果

| 审计项 | 结果 | 证据 |
| --- | --- | --- |
| 外部函数/类签名 | 通过 | 对 6 个本次核心源文件做 AST 对照，公开顶层符号新增 0、删除 0、签名变化 0；新 helper 已全部收束为模块私有名称 |
| 外部 payload 合同 | 通过 | external contract snapshot 3/3 |
| Brain 唯一回复权 | 通过 | static architecture audit 全通过；Brain 失败无本地可见 fallback |
| 当前消息优先且不强制断史 | 通过 | 污染会话专项、最近历史窗口和 5 轮车型切换专项通过 |
| 普通路径单 evidence | 通过 | preflight 专项断言 evidence build=1、preflight LLM=0、主 Brain=1 |
| reviewer 收束 | 通过 | 普通措辞、上下文短语、软 advisory handoff 不触发；硬事实/高风险仍触发 |
| 共享 repair 与 scheduler 所有权 | 通过 | scheduler 165/165，含未物理退出 worker 不释放、prior repair 判定和 final polish 恢复预算 |
| 多会话隔离 | 通过 | 并发 session history、同名会话 session key、ready reply/send target 绑定均通过 |
| 双向图片上下文 | 通过 | 客户图、客服图、方向封装、ledger 与 Brain 历史专项均通过 |
| 语音/识图插件隔离 | 通过 | optional plugin matrix 7/7；core、voice、vision、both/custom/missing 组合均可加载 |
| 大风车/Product Master 边界 | 通过 | 大风车 6/6、V2 控制台 11/11、product master split 7/7 |
| 云链路前置条件 | 通过 | 本地双端口 shared sync simulation 通过 |
| UTF-8/语法/补丁完整性 | 通过 | `py_compile` 与 `git diff --check` 通过；控制台乱码仅是 PowerShell 输出代码页，不是源文件编码变化 |

审计中发现并当场修正了两个内部偏差：

- 三个新 helper 初版名称看起来像公共函数，已改为模块私有名称，避免形成意外 SDK 接口。
- 旧 evidence safety 的软转人工 advisory 曾会触发额外 reviewer；现已只保留硬安全/权威冲突 reviewer，软 advisory 不再增加一轮模型等待。

## 20. 内部测试与耗时记录

### 20.1 回归结果

| 测试 | 结果 | 本轮耗时/规模 |
| --- | --- | --- |
| 单 Brain、污染上下文与减负专项 | 10/10 | 约 1 秒 |
| Brain contract 全量 | 通过 | 约 10 秒 |
| Brain preflight | 10/10 | 与 scheduler 合计约 10 秒 |
| scheduler / 多会话 | 165/165 | 与 preflight 合计约 10 秒 |
| workflow logic | 125/125 | 约 53 秒，独立运行通过 |
| external contract | 3/3 | 通过 |
| optional plugin matrix | 7/7 | 通过 |
| Brain First 静态架构 | 全通过 | 9 项 |
| 多模态 session context | 全通过 | 7 项 |
| 客服自发图片 Brain context | 5/5 | 通过 |
| 图片方向闭环 | 7/7 | 通过 |
| 识图内存/剪贴板合同 | 6/6 | 只接受当前代剪贴板内存图，不恢复错误文件路径链路 |
| 大风车 Product Master | 6/6 | 通过 |
| AI 经验池权威隔离 | 14/14 | 通过 |
| Product Console V2 | 11/11 | 通过 |
| Product Master split | 7/7 | 通过 |
| LLM provider config | 15/15 | 通过 |
| 本地双端口云模拟 | 通过 | `vps_admin` + `admin_backend` shared sync |

曾在并行启动两个会修改同一测试状态的套件时出现一次 console switch 用例干扰；相应用例单独复跑通过，完整 `workflow logic` 随后独立运行 125/125。结论是测试夹具共享状态竞争，不是产品运行缺陷；最终验收数据全部来自串行、独立运行。

### 20.2 性能结果

稳定缓存状态下，对 10 类真实客服问题循环构建 20 次完整 evidence：

| 指标 | 结果 | 目标 |
| --- | ---: | ---: |
| evidence p50 | 0.126 秒 | 小于 0.5 秒 |
| evidence p95 | 0.296 秒 | 小于 0.5 秒 |
| evidence max | 0.296 秒 | 小于 0.5 秒 |

AI 经验参考索引在开发测试修改数据后首次失效重建曾出现一次约 4.7 至 6.2 秒冷启动；索引落盘后新进程文件缓存读取约 0.08 秒，后续内存命中约 0.02 秒。该冷重建没有产生重复 planner、错误发送或静默，当前手测前缓存已经建立。后续若经验池频繁在线更新，应单独把索引重建迁到后台维护任务，不能重新放回客户回复热路径。

真实 provider 边界矩阵共 11 类场景。首次连续运行 9/11 直接发出正确 Brain 回复，2 例因上游模型把商品证据 ID 拼错或修复请求返回空响应而被安全阻断，没有发送错误事实；两例分别独立复跑后均通过。最终针对普通闲聊和无关聊天再跑 2/2 通过，reviewer 调用为 0，planner 分别约 17.70 秒和 6.61 秒。高风险违法/贷款场景仍保留按需 reviewer 与安全边界。

真实模型的瞬时超时、空 JSON 或证据 ID 拼写错误不能被伪装成成功；本次实现选择正确的失败关闭，并把恢复限制在唯一 repair 配额内。内部确定性测试、契约测试、架构测试和所有真实场景的独立复跑均已通过，可以进入用户手工实测阶段。
