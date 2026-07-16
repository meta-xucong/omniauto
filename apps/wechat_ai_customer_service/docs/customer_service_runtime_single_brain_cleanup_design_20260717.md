# 微信 AI 客服运行时单 Brain 收束：开发设计与实施前审计

日期：2026-07-17
状态：**设计审计完成，未批准修改运行时代码**

本文引用并服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

同时承接但不替代：

- [customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md](customer_service_contract_preserving_optimization_and_slimming_audit_20260713.md)
- [ai_customer_service_latency_optimization_master_plan_20260619.md](ai_customer_service_latency_optimization_master_plan_20260619.md)

## 1. 目的与硬边界

本次目标不是继续叠加局部补丁，也不是重写客服框架；而是在**不改变任何既有对外接口或字段**的条件下，把运行时收束为一条可理解、可测量、可取消且不重复决策的 Brain First 主链路。

本轮采用最严格的零接口变化原则：模块之间的接口、函数签名、配置结构、返回 payload、event、state、嵌套字段、字段类型、字段数量、字段名和字段语义均不得增加、删减、删除、改名或重解释。性能观测、execution lease、缓存和中间 evidence 只能存在于模块私有内存或私有诊断实现中，不能进入任何模块间 payload。

以下内容全部冻结，不得改名、删除、改变签名、改变既有字段含义，或要求调用方迁移：

| 边界 | 保持项 |
| --- | --- |
| Python 入口 | `listen_and_reply.py`、`customer_service_brain.py`、`customer_service_scheduler.py`、`llm_config.py` 的既有公开导入路径、类、函数、参数与默认值 |
| 工作流输出 | `process_target()` 既有 event 字段、`action/reason` 语义、Brain 审计字段、产品/意图/媒体兼容字段 |
| 调度状态 | `sessions`、`captures`、`llm_tasks`、`polish_tasks`、`ready_replies`、`events` 等既有顶层结构及既有状态值 |
| 调度与发送 | `ProductMasterStore`、Brain evidence 外层合同、RPA capture/send/session 绑定、发送前目标确认、最终可见话术润色门禁 |
| 插件 | 语音与识图继续独立、懒加载、只补充输入，不拥有 scheduler/Brain 状态，不创作客户可见话术 |
| 客户可见文本 | 只能由 `customer_service_brain` 或其 Brain repair 产出；任何失败都阻断发送并告警，不能回退到本地模板 |

允许的变化仅限内部实现、私有 helper、兼容门面后的调用顺序、去重缓存以及新测试/文档。**不新增任何接口字段，即使 optional 也不允许。**

## 2. 本轮实测审计结论

### 2.1 已完成任务的阶段耗时

从 chejin 的本地 scheduler state 提取了三条已完成 planner 记录；以下均是进入 RPA send 前的耗时：

| 场景 | planner worker | Brain 前未分段区间 | Brain evidence | Brain 主 LLM | 语义复核 | final polish |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 短追问（两条短消息） | 153.7s | 30.6s | 0.7s | 120.4s | 0s | 5s |
| 常规推荐 | 83.6s | 35.0s | 3.5s | 26.8s | 12.3s | 6s |
| 图片相关会话 | 145.8s | 48.9s | 18.2s | 58.7s | 11.6s | 6s |

结论：慢不是单一模型问题。主模型是最大项，但 Brain 前存在 31–49 秒的未分段阻塞；语义复核在普通业务会话中又可增加约 12 秒。

### 2.2 Prompt 预算没有真正成为硬约束

同一批记录的实际 Brain 输入如下：

| profile | prompt 字符数 | 实际 prompt token | completion token | reasoning token | 主调用耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `lean` | 30,356 | 12,292 | 1,443 | 1,126 | 120.4s |
| `lean` | 11,787 | 4,650 | 578 | 334 | 58.7s |
| `routine_product_fast` | 6,881 | 2,599 | 861 | 352 | 26.8s |

“快速 profile”目前只缩减了部分配置值，没有验证最终序列化内容是否真的在预算内。`compact_product_master_for_prompt()`、`compact_formal_knowledge_for_prompt()` 和 `compact_rag_for_prompt()` 仍采用“保留所有非列表顶层键”的策略；未来字段或大对象可绕过 item 裁切进入 prompt。这是结构性风险，必须改成严格白名单投影和最终序列化预算检查。

### 2.3 已读不回的根因是执行生命周期失真

现有 scheduler 在 `_collect_llm_results()` 发现 planner 超时时，会从 `_planner_futures` 移除 future、调用 `future.cancel()`、把任务恢复为可重排状态。该做法不等于停止正在执行的 Python 线程。

`call_llm_request_once_with_wall_timeout()` 也使用后台线程等待 wall timeout；超时后返回给上层，但底层网络线程不保证停止。因此会发生：

1. task 状态被认为已超时、可恢复；
2. 实际 planner worker 和网络请求仍占用线程池；
3. scheduler 只按 `_planner_futures` 计数，以为容量已经释放；
4. 同一 capture 被再次提交；
5. 旧 worker 的晚到结果失去归属，多个物理 worker 被旧请求占满；
6. 后续会话表现为捕获到消息却没有可执行的 planner 容量。

这是 P0 正确性问题，不是调大并发或缩短 timeout 能解决的问题。

### 2.4 冗余和权责重叠

普通 Brain First 业务路径当前结构为：

```text
消息规范化/历史/媒体桥接
  -> 旧 evidence pack
  -> intent router
  -> data capture / product knowledge / legacy decision
  -> intent assist（再次 evidence pack）
  -> customer_service_brain（再次构建 Brain evidence）
  -> 已禁用的 RAG / realtime / legacy synthesis 入口
  -> 重新采用 Brain reply
  -> final visible polish
```

其中的历史兼容字段有价值，但以下重复工作没有必要成为客户回复关键路径：

- 同一消息多次建立知识、RAG 和 safety evidence；
- Brain 已是最终策略/话术作者，旧 `decision` 仍在 Brain 前完成一次完整候选决定；
- Brain 已可采用后仍执行 RAG、实时路由和旧综合回复入口，再在末尾覆盖为 Brain reply；
- Brain 内部重试、JSON repair、quality repair 与 scheduler 超时恢复没有统一的重试所有权；
- `semantic_reviewer_mode=suspicious_only`，但当前“可疑”定义过宽，使普通推荐也进入第二个模型调用。

以上不表示立即删除旧字段或旧模块。正确方式是保留兼容投影，把它们从“并列决策链”降为“共享 evidence 的审计/顾问投影”。

## 3. 当前接口与实现审计

### 3.1 入口和调用关系

| 位置 | 当前职责 | 本次可改/不可改 |
| --- | --- | --- |
| `workflows/listen_and_reply.py::process_target` | 捕获 payload 到 planner event 的兼容入口 | 不改函数签名/返回字段；可将长流程改为调用私有 planning core |
| `workflows/customer_service_brain.py::maybe_run_customer_service_brain` | Brain First 兼容入口 | 不改签名；可把实现委托给接收 prepared evidence 的私有 core |
| `admin_backend/services/customer_service_scheduler.py::plan_reply_with_listen_workflow` | scheduler 到 workflow 的兼容桥 | 不改参数/返回字段；可附加 latency trace |
| `CustomerServiceSchedulerRuntime` | future 生命周期、队列和 RPA 串行化 | 不改公开 class/config/state contract；可重做内部 future ownership |
| `llm_config.py::call_llm_request_once_with_wall_timeout` | 统一 LLM wall-timeout 兼容入口 | 不改签名/返回 shape；可替换后台线程实现 |
| voice/vision compatibility | 给现有 message/event 字段补充媒体输入 | 不改字段；不得并入 Brain 或互相 import |

### 3.2 既有字段的兼容处理

后续收束后，以下字段仍必须存在于原本会出现它们的 Brain First planner event 中：

- `intent_result`、`data_capture`、`product_knowledge`、`intent_assist`
- `customer_service_brain`、`customer_service_brain_adopted`、`customer_service_brain_legacy_generators`
- `rag_reply`、`llm_reply`、`realtime_context`、`runtime_route`、`realtime_reply`、`token_budget`、`llm_reply_synthesis`
- `reply_style_adapter`、`brain_first_reply_audit`、`outbound_naturalness`
- 已有 `latency_trace`、final polish 以及 scheduler task/result 字段

不允许通过“成功后提前 return”直接让这些字段消失，也不允许新增任何兼容标识字段。若不再执行旧 reply generator，必须由 compatibility projector 生成与当前禁用态逐字段完全一致的 no-op payload（相同字段、类型、reason 和语义）。该 projector 必须先经过旧 fixture 和外部合同快照测试。

## 4. 目标内部结构

只新增私有实现模块；旧文件保留为唯一公开门面：

```text
workflows/internal/
  brain_first_planning_core.py       # 私有：一次准备、一次 Brain、兼容投影
  planning_evidence.py               # 私有：共享 evidence envelope 与预算投影
  planning_latency.py                # 私有：阶段计时，不含客户内容

admin_backend/services/internal/
  scheduler_execution_lease.py       # 私有：future/lease/超时状态机
```

这些文件不作为新 SDK、不由 RPA、商品库、Brain 外部调用方直接 import。既有入口仅作薄门面。

目标关键路径：

```text
capture 的已规范化消息
  -> 一次 PreparedPlanningContext
       - 会话/历史/媒体 bridge
       - 一次权威 evidence
       - 必要的兼容性审计投影
  -> customer_service_brain（唯一客户策略与话术作者）
  -> 硬边界 guard
  -> 仅风险触发的 semantic review / Brain repair
  -> final visible polish（仅轻度自然化）
  -> ready reply / RPA send
```

`PreparedPlanningContext` 只在一次 planner worker 内存中存在，不能写入 state、event、配置、返回 payload 或任何模块间对象。需要审计时，使用私有诊断 logger 在本进程内输出聚合耗时；它不能修改既有 `latency_trace`、event 或 state 的字段，也绝不保存完整 prompt、密钥或原始受限产品字段。

## 5. 分阶段实施设计

### 阶段 A：先锁定合同和精确计时（零业务行为变化）

目标：在修改调用图前，能够证明每个接口和阶段仍然相同。

1. 在 `process_target()` 的私有实现中接入不出站的阶段计时器，记录：
   - `capture_payload_prepare`
   - `history_backfill`
   - `media_bridge`
   - `legacy_evidence_prepare`
   - `intent_route`
   - `data_capture`
   - `product_knowledge`
   - `intent_assist`
   - `brain_start` / `brain_done`
   - legacy no-op projection
2. 计时结果只供私有诊断 logger 和本地测试断言使用；`plan_reply_with_listen_workflow()`、既有 `latency_trace`、event、scheduler state 和任何返回 payload 不增加、不修改任何字段。
3. 先增加 characterization tests：函数签名、事件字段、状态顶层字段、常见 `reason` 值、Brain/RPA envelope。
4. 用三类离线 fixture（短社会消息、明确车辆咨询、图片/上下文追问）建立基线；禁止用真实微信发送来调试此阶段。

验收：模块间 payload 完全零字段变化；私有诊断能够定位每个 Brain 前阶段，31–49 秒不再是黑盒。

### 阶段 B：建立一次性 PreparedPlanningContext（先复用，后删重）

目标：让同一 turn 的 evidence、conversation snapshot、媒体 bridge 只有一个权威构建点。

1. 新建私有 `prepare_planning_context()`，输入为既有 `process_target` 局部变量，输出只供本 worker 使用。
2. 保留 `build_evidence_pack()`、`maybe_analyze_intent()`、`maybe_run_customer_service_brain()` 的旧公开入口和签名；为内部调用增加私有 helper，例如：
   - `_maybe_analyze_intent_with_prepared_evidence(...)`
   - `_run_customer_service_brain_with_prepared_evidence(...)`
3. 旧入口在未提供内部上下文时，仍走原实现，保证外部直接调用兼容。
4. `intent_assist`、RAG、realtime、legacy synthesis 读取同一份 prepared evidence 的内部兼容投影；不得重新读取整库或重新执行 runtime RAG，且所有既有 event 字段和值域保持原形。
5. `product_knowledge`、数据采集和 intent 路由保留原字段与失败语义；Brain First 下它们只提供 evidence/审计，不能阻断或改写 Brain 策略。

验收：构建计数测试证明同一 turn 的 authority evidence 最多构建一次；旧 event 字段、现有 Brain adoption/blocked 语义和非 Brain First 旧路径不变。

### 阶段 C：收束 Brain First 后置链路，但保留兼容投影

目标：Brain 可采用时，不再运行无权写出客户可见话术的旧生成器。

1. Brain 失败、不可采用或 hard boundary 的现有阻断路径不变。
2. Brain 成功可采用后，进入私有 `project_brain_first_legacy_audit_fields()`：
   - 生成旧字段形状和禁用态 reason；
   - 不调用 RAG/realtime/legacy synthesis 的实际检索或 LLM；
   - 不改变 `customer_service_brain_adopted`、`reply_style_adapter`、`brain_first_reply_audit` 的既有语义。
3. 此 projector 的输出必须逐字段与当前“生成器已禁用”路径的 fixture 比较。任何无法兼容的字段，不得擅自删除，需继续保留原 no-op 调用。
4. 非 Brain First 和 shadow 模式继续走其现有路径；此次不借机改写历史模式行为。

验收：Brain First 成功 case 中不再调用旧 RAG/realtime/synthesis provider；event 形状保持；客户可见 reply owner 仍只能是 `brain` 或 `brain_repair`。

### 阶段 D：Prompt 预算成为可验证的最终约束

目标：减少模型输入和隐藏推理，而不是缩短 timeout 后丢回复。

1. 在 `build_sized_brain_prompt()` 后、真正调用 provider 前，增加私有 `BrainPromptBudget` 校验；它不向 `prompt_estimate`、event 或 state 增加字段。
2. 使用白名单投影替换“复制所有非 item 顶层键”的 compact 策略：
   - 商品只可带 customer-visible 且 field-policy 允许的身份、价格、车况、里程、位置、可售状态、图片语义摘要；
   - 明确排除完整 source payload、sync audit、内部身份、VIN/车牌、成本/底价、全量图片元数据、任意未知大对象；
   - 正式知识、RAG、经验池、上下文、runtime strategy 都有独立条数和字符上限；
   - 最新客户内容和必要的对话摘要优先，不能被历史/审计挤掉。
3. 预算按 profile 可不同，但必须对最终序列化 JSON 生效；现有 `prompt_estimate` 的字段和值域不变，不保存原 prompt。
4. 不增加新的客户可见结构化约束。BrainPlan schema、reply ownership 和 repair 协议保持；只减少无关输入、设置合理 completion 上限，并在 provider 基准中比较低延迟模型。

建议的起始性能预算（以离线序列化实测校准，非对外配置迁移）：

| 场景 | Brain 输入目标 | 主 Brain 总预算 | reviewer |
| --- | ---: | ---: | --- |
| 社交/追问 | <= 4,000 chars | <= 15s | 默认跳过 |
| 一般车辆咨询 | <= 8,000 chars | <= 25s | 仅事实/边界风险触发 |
| 图片或复杂多约束 | <= 12,000 chars | <= 35s | 仅风险触发 |

超出预算时的正确行为是按权威优先级裁切并让 Brain 在可用证据内回答或说明需核实；不是本地模板回复，也不是静默超时。

### 阶段 E：统一 scheduler 与 LLM 的执行所有权

目标：一个 capture 在任何时刻只有一个物理执行实例，逻辑 timeout 不再伪造“线程已经结束”。

#### E.1 Execution lease

为每个 planner future 建立私有 execution lease，最少包含 task/capture identity、future、submitted/started/deadline、cancel_requested 与 physical_completion。它只能是 runtime 内存结构；不得向既有 task、event、state 或配置增加 timing/lease/audit 字段。

规则：

1. `_planner_futures` 未完成就始终计入实际容量；不能因 soft timeout 先移除。
2. 同一 `capture_id` 和同一 session 的 lease 未结束时禁止重新 submit。
3. soft timeout 只在私有 lease 记录观察时间并发起协作取消请求；task 不会立即伪装成 queued。
4. future 真正结束后：成功且仍 fresh 则接受结果；失败/确认取消后才走现有 recovery，并且最多恢复一次。
5. `queued/running`、已有事件名、`recoverable_retry_count` 和 task state 的外部读法、字段和值域保持完全兼容；不新增状态字段，也不复用旧 status 表达新含义。

#### E.2 取消与请求 timeout

`future.cancel()` 只能取消尚未开始的 future，不能作为运行中请求的终止机制。`call_llm_request_once_with_wall_timeout()` 的公开签名和结果 shape 保持，但内部需要从“后台 daemon thread + wait”迁移为可由 transport 自身保证 connect/read/overall deadline 的调用方式。

实现顺序：

1. 先修 scheduler lease，让未终止 worker 永远不被重复提交；
2. 再为 LLM transport 增加真正的 deadline/cancellation adapter；
3. 仅在 transport 确认停止或 future 已结束时释放 capacity；
4. 每个请求链只有一个 retry owner：Brain 内部负责同 capture 的可解释 retry/repair；scheduler 只负责物理执行结束后的 crash/recovery，二者不得并发重复。

在 transport 没有可中断能力时，宁可保留 worker 占用并阻断重复执行，也不能伪造取消成功。

### 阶段 F：复核与最终润色分层

1. deterministic guard 永远执行，且只审核事实、硬风险、会话/目标绑定和完整性。
2. semantic reviewer 只在以下条件任一命中时进入：权威事实冲突、价格/库存/承诺、图片实体与商品候选冲突、硬边界相邻风险、确定的证据缺口。
3. 普通措辞、短社交、推荐形状等软问题先形成 Brain repair feedback；修复后若 hard gate 通过，只记录 warning，不能因此阻断或二次审查。
4. final visible polish 继续保留在发送门禁内，但输入限定为 Brain draft、保护 token、最小必要上下文；只能轻度自然化，不能改变事实、策略或风险姿态。

## 6. 迁移顺序与回退

每个批次必须独立合并、独立验证，不能把文件拆分、性能优化、timeout 语义调整混在一次改动中。

1. A：合同画像和 timing；
2. B：共享 evidence，仅复用不删路径；
3. C：Brain First 后置 generator compatibility projector；
4. D：prompt 白名单和 hard budget；
5. E：execution lease 与 transport timeout；
6. F：reviewer gate；
7. 离线稳定性与本地双端口 cloud simulation；最后才允许用户手工低频实测。

任一批次失败时，只回退该私有 helper 的调用，保留原 public facade、state reader 和旧 data files；不做数据库/商品库迁移，不触碰大风车镜像、RPA 物理操作或识图资产保存协议。

## 7. 必须新增的测试矩阵

### 7.1 外部兼容

- `run_customer_service_external_contract_compat_checks.py`：旧 import、signature、payload/state fixture。
- `run_customer_service_optional_plugin_matrix_checks.py`：core/voice/vision 独立矩阵。
- `run_brain_first_static_architecture_audit.py`：无本地客户可见 fallback、Brain 唯一 owner。
- 新增 event compatibility fixture：Brain First 成功、Brain 阻断、非 Brain First 三种 event 字段和类型不变。

### 7.2 重复工作和输入预算

- 单 turn evidence build 次数为一；未命中媒体时不加载具体媒体 provider。
- 短追问、常规车辆咨询、图片桥接、长上下文分别验证最终 `prompt_estimate` 不超预算。
- 构造未知大字段/source payload，证明不会进入 Brain prompt。
- 保留 customer-visible field policy，受限字段永远不可进入 Brain。

### 7.3 Scheduler 生命周期

- 两个 planner 同时卡住时，timeout 后不得出现同 capture 的第二个物理执行。
- `future.cancel()` 失败/无效时，capacity 仍按实际 future 计算。
- 晚到的成功结果在 fresh 时可安全进入 polish；取消/失败后只恢复一次。
- 两会话并发、同会话单 inflight、多会话无串发、restart orphan recovery。
- `llm_task_runtime_timeout` 等既有审计 reason 在其原有适用条件下仍可被读取。

### 7.4 Brain First 质量与发送

- 问候、明确车型、模糊别名、上下文追问、异议、闲聊、图片匹配、权威冲突、转人工。
- reviewer soft warning 不得吞掉一个结构完整的 Brain 短回复。
- hard failure 必须 block + internal alert，不能生成本地客户话术。
- final polish 不能改写事实/策略；RPA send 前仍完成 target/session envelope 检查。

## 8. 实施前审计结论

**结论：可实施，没有需要改变外部接口的硬性阻塞。**

但进入代码前必须满足以下门槛：

1. 当前工作区存在尚未提交的 scheduler、Brain、workflow、识图和商品库改动；实施者必须以当前工作树为基线，不能 checkout/reset/覆盖它们。
2. 先运行并记录当前外部合同、Brain、scheduler、optional plugin 的基线测试；任何已有失败需先分类为历史失败或本轮阻塞。
3. 先落阶段 A 的 characterization/timing，再动一次性 evidence 或 scheduler lifecycle；不允许直接删除旧分支。
4. 不新增或修改任何 event/state/config/return payload 的字段；所有诊断只能处于模块私有实现，且不含客户原文、完整 prompt、密钥或受限车辆字段。
5. 不做真实微信自动发送测试；代码和离线审计通过后，由用户进行手工低频验收。

满足以上门槛后，按第 6 节顺序实施，能够在不改 Brain、RPA、商品库对外工作方式的前提下系统性去重、缩短关键路径并消除 timeout 重排造成的线程饥饿。

### 8.1 2026-07-17 当前工作树基线结果

本轮只运行了离线检查，未启动微信、未启动客服 listener、未修改运行时代码。结果如下：

| 检查 | 结果 | 审计结论 |
| --- | --- | --- |
| `run_customer_service_external_contract_compat_checks.py` | 3/3 通过 | 现有公开 contract snapshot、媒体 legacy result shape、scheduler state compact semantics 可读 |
| `run_customer_service_optional_plugin_matrix_checks.py` | 7/7 通过 | core/voice/vision 独立与 lazy import 基线可用 |
| `run_brain_first_static_architecture_audit.py` | 9/9 通过 | 客户可见话术仍由 Brain 独占，未发现本地 fallback source |
| `run_customer_service_brain_contract_checks.py` | 通过 | Brain adoption、阻断与既有 event compatibility 基线可执行 |
| `run_customer_service_multi_session_scheduler_checks.py` | 通过 | 多会话 scheduler 基线可执行 |
| `run_workflow_logic_checks.py` | 通过 | workflow 兼容逻辑基线可执行 |
| `run_realtime_reply_optimization_checks.py` | 通过 | 旧 realtime 兼容/优化检查基线可执行 |
| `run_customer_service_multimodal_session_context_checks.py` | 通过 | 语音/图片上下文边界基线可执行 |
| `run_customer_service_brain_preflight_checks.py` | **前 5 项执行中 4 项通过、1 项失败；脚本按既有行为提前停止，剩余 4 项未执行** | 见下方，不允许在本设计审计阶段直接修复 |

失败项为 `check_short_text_product_gap_uses_llm_preflight_query`。根因已定位为当前工作树中未提交的 `low_authority_fast_catalog_alias_matches()` 改动：它在低权限快速 profile 决策阶段提前用本地 alias 命中“奥迪a四l”，将 profile 切到 `catalog_alias_requires_authoritative_evidence`，从而不再执行该测试所期待的 text-gap preflight 分支。测试本身未同步修改。

这不是对外接口或字段破坏，但证明当前工作树已经存在“新增补丁改变旧分支覆盖”的结构债务，正是本次收束需要处理的对象。它被记录为实施前已知问题：进入阶段 A 后，必须先将这个分支的旧行为、Brain 证据质量和一次性 PreparedPlanningContext 的期望写成 characterization tests，再决定保留、替代或删除该内部短路；在此之前不得以修改测试掩盖失败。
