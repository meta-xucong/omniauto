# 微信客服兼容式优化与减负审计

日期：2026-07-13

本文引用并服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

本文只审计和设计内部优化，不批准修改现有导入路径、函数签名、返回字段、配置键、状态字段、事件名称、RPA action、Brain bridge 或其他外部合同。语音与识图仍是两个严格独立、可分别缺席和替换的可选能力域。

## 1. 审计结论

当前最需要解决的不是“缺少一套新框架”，而是以下三类内部负担：

1. 兼容入口与具体实现混在同一个超大文件中，任何局部修改都会扩大回归面。
2. 语音、识图已经有部分独立实现，但主干仍直接 import 和编排具体实现，尚未真正做到可缺席、可替换。
3. 调度状态把大量已终态历史长期保留在一个 JSON 中，每次更新都全量读取、解析、深拷贝、格式化和原子替换，已经形成可测量的运行负担。

因此，当前最合适的路线是：

> 保留原文件作为兼容门面，在门面后抽取内部小模块；用惰性 capability adapter 隔离语音和识图；在不改变状态顶层字段和读写入口的前提下，减少全量状态处理。

不建议重写 scheduler、改成统一 Job、替换现有账本、修改外部字段，或一次性搬走原模块。

## 2. 量化结果

### 2.1 大文件规模

| 文件 | 行数 | 字节数 |
| --- | ---: | ---: |
| `workflows/listen_and_reply.py` | 9,332 | 443,966 |
| `admin_backend/services/customer_service_scheduler.py` | 4,867 | 251,625 |
| `admin_backend/services/customer_service_scheduler_state.py` | 2,647 | 124,345 |
| `adapters/wechat_win32_ocr_sidecar.py` | 10,310 | 496,586 |

四个文件合计约 27,156 行。主要超长实现包括：

- `process_target`：1,533 行。
- `ManagedListenerSchedulerBridge`：2,072 行。
- `CustomerServiceSchedulerRuntime`：1,242 行。
- `_capture_session`：487 行。
- sidecar `run_action`：455 行。
- sidecar `send_payload`：383 行。
- sidecar `voice_transcribe_payload`：163 行，但其相关识别、菜单、几何、校验函数分散在约 1,000 行范围内。

问题不只是文件长，而是“公共门面、兼容逻辑、业务阶段、插件实现、RPA 细节”共同处于同一修改面。

### 2.2 旧入口已经是事实公共合同

仓库 AST 扫描得到：

| 模块 | import 节点数 | 被直接引用的符号数 |
| --- | ---: | ---: |
| `listen_and_reply` | 33 | 92 |
| `wechat_win32_ocr_sidecar` | 17 | 112 |
| `customer_service_scheduler` | 5 | 15 |
| `customer_service_scheduler_state` | 7 | 40 |

这些数字还不包含仓库外部调用方。因此：

- 原文件不能删除或改名。
- 原符号不能只搬走后要求调用方改 import。
- 下划线开头的函数也不能仅凭命名认定为私有，因为现有测试已经直接导入部分下划线函数。
- 所有拆分都必须先保留 wrapper、alias 或 re-export。

### 2.3 当前状态负担

实测 `chejin` 当前调度状态：

`runtime/apps/wechat_ai_customer_service/tenants/chejin/state/customer_service_scheduler_state.json`

| 顶层字段 | 数量 | 紧凑 JSON 估算字节 |
| --- | ---: | ---: |
| `sessions` | 4 | 23,224 |
| `captures` | 405 | 3,230,747 |
| `llm_tasks` | 267 | 6,556,488 |
| `polish_tasks` | 196 | 11,879,636 |
| `media_context_tasks` | 0 | 2 |
| `ready_replies` | 70 | 6,248,257 |
| `events` | 500 | 137,399 |

文件实际大小为 43,315,817 字节。当前样本中：

- 267 个 LLM task 全部是 `completed`、`failed` 或 `stale`。
- 196 个 polish task 全部是 `completed`、`degraded` 或 `stale`。
- 70 个 ready reply 全部是 `sent`、`stale` 或 `send_failed`。
- 没有处于 `queued` 或 `running` 的上述任务。

对当前文件做一次只读本地基准，结果为：

| 阶段 | 单次耗时 |
| --- | ---: |
| 文件读取 | 270 ms |
| JSON 解析 | 458 ms |
| `deepcopy` | 1,040 ms |
| 缩进 JSON 序列化 | 1,529 ms |
| 紧凑 JSON 序列化 | 353 ms |

这是单机单次测量，不等于每轮实盘固定耗时，但足以证明全量状态处理是显著负担。现有 scheduler/state 中另有约 77 处 `deepcopy` 调用，需要逐个区分“边界快照”和“无必要复制”。

## 3. 当前模块隔离缺口

### 3.1 识图已经模块化，但还不是可选加载

识图已有相对完整的独立文件：

- `customer_image_asset_store.py`
- `customer_image_brain_bridge.py`
- `customer_image_catalog_assist.py`
- `customer_image_turn_router.py`
- `customer_image_understanding.py`
- `customer_image_understanding_contract.py`
- `customer_image_understanding_provider.py`
- `wechat_image_save_capture.py`

这是正确基础，不应再创建第二套识图实现。当前缺口是主干仍在模块加载时直接依赖具体实现：

- `listen_and_reply.py` 顶层 import `maybe_route_customer_image_turn`。
- scheduler 顶层 import `build_brain_safe_image_proxy_messages` 和 `customer_image_capture_trigger`。
- sidecar 顶层 import `execute_wechat_image_save`。
- Brain 顶层直接 import 图片 bridge。

结果是识图代码或其依赖缺失时，core 可能在启动或 import 阶段失败，而不是仅让识图能力不可用。

### 3.2 语音实现仍散落在主干

语音目前分布在：

- `listen_and_reply.py`：配置、触发判断、调用、审计字段。
- scheduler：语音 envelope、合并、历史审计和 capture 编排。
- `wechat_connector.py`：语音动作的锁、重试和 sidecar 调用。
- `wechat_win32_ocr_sidecar.py`：语音气泡识别、右键菜单定位、点击、结果确认。

这意味着语音不是一个可单独拿走或替换的实现包。第三方即使不用内置语音，也要加载包含语音逻辑的主干文件。

### 3.3 语音与识图虽未直接互相 import，但被主干揉在同一 capture 流程

scheduler `_capture_session` 同时处理：

- voice trigger 和 transcription。
- image trigger、图片保存和视觉上下文。
- 文本 refresh、history backfill、ledger、Brain payload。

这会造成两个问题：

1. 修改任一媒体能力，都必须修改 487 行 capture 主流程。
2. 插件缺失、异常或返回结构变化，容易污染另一媒体能力和普通文字链路。

正确目标不是建立一个新的“多媒体业务层”，而是让 capture 主流程只调用两个中性的 capability port。两个插件的实现、配置、状态和测试保持严格独立。

## 4. 推荐目标结构

### 4.1 原文件全部保留为兼容门面

以下原入口继续存在：

- `workflows/listen_and_reply.py`
- `admin_backend/services/customer_service_scheduler.py`
- `admin_backend/services/customer_service_scheduler_state.py`
- `adapters/wechat_connector.py`
- `adapters/wechat_win32_ocr_sidecar.py`
- 现有全部 `customer_image_*.py`

原函数继续接受相同参数并返回相同字段。例如：

```python
def voice_transcription_trigger(payload, *, pending_signal_kind=""):
    return _voice_compat.voice_transcription_trigger(
        payload,
        pending_signal_kind=pending_signal_kind,
    )
```

调用方不感知实现已被抽取。

### 4.2 只增加一个中性 capability 协议，不增加运行层级

中性协议只负责：

- 查询 capability 是否可用。
- 判断当前 capture 是否需要运行。
- 调用插件并返回结果。
- 把结果交给各自 compatibility adapter。

它不拥有队列、session、Brain、RPA 窗口或客户回复，不形成新的调度层。

```text
optional_plugins/
  contract.py
  registry.py
  loader.py
  voice/
    trigger.py
    transcription.py
    compatibility.py
    plugin.py
  vision/
    trigger.py
    capture.py
    understanding.py
    compatibility.py
    plugin.py
```

硬约束：

- `voice/` 不 import `vision/`。
- `vision/` 不 import `voice/`。
- `contract.py`、`registry.py`、`loader.py` 不 import 任一具体实现。
- 内置插件只在首次需要时 lazy import。
- core only、voice only、vision only 都能启动和处理普通文字。
- 第三方实现可以注册同一 capability，但 compatibility adapter 仍输出现有字段。

### 4.3 主干只保留阶段编排

建议内部目录：

```text
internal/
  scheduler/
    capture_pipeline.py
    task_lifecycle.py
    freshness.py
    send_pipeline.py
    recovery.py
    context_bridge.py
    state_cleanup.py
  reply_runtime/
    batch_selection.py
    message_normalization.py
    history_backfill.py
    context_builder.py
    brain_bridge.py
    send_orchestration.py
    legacy_state_compat.py
  win32_ocr/
    common_geometry.py
    message_parser.py
    voice_actions.py
    image_actions.py
    send_actions.py
```

`internal` 目录不作为新公共 API。旧模块仍是唯一兼容入口。

## 5. 具体减负方案

### 5.1 P0：先建立合同画像，不改行为

在移动任何实现前，生成并锁定：

- 旧模块可导入符号清单。
- 关键函数 `inspect.signature` 快照。
- 典型输入和返回 dict 的字段、类型和缺省值快照。
- scheduler state 顶层字段和旧 fixture 读取测试。
- action/state/reason/error code 清单。
- core/voice/vision 依赖矩阵。

这一阶段的价值是防止“代码能跑，但外部开发者接口已经变了”。

### 5.2 P0：把具体插件改成惰性加载

优先消除四个顶层具体依赖，但保留旧函数：

1. scheduler 不再顶层 import 图片具体实现。
2. `listen_and_reply` 的图片入口改为旧函数 wrapper + lazy resolver。
3. sidecar 的图片保存入口改为 action 内 lazy resolver。
4. 语音默认插件从 `listen_and_reply` 和 scheduler 中抽出，旧函数继续转发。

插件不可用时，只返回当前合同已有的 `unavailable/not_supported/disabled` 类结果；不能让普通文字链路启动失败，也不能由本地模块生成客户可见兜底回复。

### 5.3 P1：拆出 capture 的语音和识图 bridge

把 scheduler `_capture_session` 中的两段媒体逻辑抽成两个独立内部调用：

```python
payload, voice_meta = run_voice_capture_capability(context, payload)
payload, vision_meta = run_vision_capture_capability(context, payload)
```

这两个函数必须：

- 分属不同模块。
- 不共享实现状态。
- 输入为只读式 context 和当前 payload。
- 输出仍映射到现有 `voice_transcription`、`voice_transcription_merge`、`customer_image_capture_trigger`、图片理解和 history 字段。
- 任何异常只落各自能力的内部结果，不影响另一能力。

`media_context_tasks` 顶层字段继续保留。它可以由 compatibility adapter 承载现有图片异步任务，但不能被改名，也不能变成语音和识图共用实现容器。

### 5.4 P1：减小 scheduler state 的每次处理成本

保持原路径、原顶层字段和 `SchedulerStateStore` 入口，内部依次做：

1. 在同一个 tick/锁范围内复用已加载 state，避免同阶段重复 `load()`。
2. 增加内部 batch mutation/transaction helper，让同一阶段的多个状态变化只写一次文件；旧 `update()` 继续保留。
3. 证明 `json.dumps` 期间没有并发修改后，移除 `save()` 中无必要的全树 `deepcopy`；先用测试保护异常和原子替换语义。
4. 在不改变 JSON 语义的前提下评估紧凑序列化。当前样本可从约 43.3 MB 降到约 28.1 MB，单次序列化测量从约 1.53 秒降到约 0.35 秒。
5. 将终态历史清理与活动任务恢复明确分开，任何 `queued/running/sending` 项都不得清理。

由于外部消费者可能读取历史 map，终态清理应分两步：

- 先提供 opt-in retention，并在清理前把完整终态记录写入现有审计/ledger 归档。
- 对 `chejin` 单独备份和启用，验证外部调用方后，再讨论默认 retention；库级默认行为第一阶段不变。

### 5.5 P1：只复制边界，不复制全树

77 处 `deepcopy` 不能机械删除，应分三类：

- 必须保留：跨线程提交、异步 task 入队、不可变审计快照。
- 可改浅拷贝：只修改顶层补充字段的 payload。
- 可移除：同锁、同线程、只读传递后立即序列化的对象。

每次替换必须有“调用后原输入未被修改”和“异步任务不受后续修改影响”的测试。

### 5.6 P2：逐段缩短大函数

拆分顺序按纯度和风险排序：

1. 纯文本 normalize、identity、batch selection。
2. state cleanup 和 terminal classification。
3. voice/vision compatibility bridge。
4. history backfill 和 context builder。
5. scheduler capture、freshness、send 阶段。
6. sidecar 语音、图片、发送、加好友 action 实现。

每次只搬一类实现，不在同一个变更中同时调整行为。旧函数保留薄 wrapper，原测试不改 import 即可通过。

### 5.7 P2：明确六套状态的职责，不替换它们

当前阶段建议只收紧写入责任：

- `SessionMonitor`：未读和会话变化的唤醒提示，不作为完整对话事实源。
- scheduler state：活动任务、回复生命周期和短期恢复状态。
- Session Ledger：已观察的会话事实、消息 occurrence 和上下文 anchor。
- workflow state：旧工作流兼容投影。
- RawMessageStore：原始消息归档和后续学习材料。
- audit：诊断、耗时和故障轨迹。

不要再让每个状态面都保存一份完整的所有中间 payload。新增内部 helper 应让各阶段引用稳定 identity，并只在既有外部字段要求处生成兼容快照。

## 6. Brain First 边界

本次减负不改变回复所有权：

- 语音插件只把语音转成带 provenance 的文本消息。
- 识图插件只产生图片资产、视觉理解和现有 Brain bridge 输入。
- scheduler 只负责正确会话、正确 occurrence、正确时序和发送保护。
- 商品库、正式知识和当前对话事实仍由现有 evidence/Brain 链路使用。
- 所有客户可见回复仍只能由 `customer_service_brain` 创作。
- 插件缺失、超时或失败不得触发本地客户话术兜底。

因此，插件抽取不会增加一轮 LLM，也不会增加 Brain 层级。正常纯文字消息不需要经过语音或识图 provider。

## 7. 必须补齐的测试

### 7.1 兼容合同

- 原 import path 全部可导入。
- 现有 92 个 `listen_and_reply` 直接引用符号保持。
- 现有 112 个 sidecar 直接引用符号保持。
- 函数签名、默认参数和关键返回字段不变。
- 旧配置、旧状态和旧 fixture 无迁移即可读取。
- 原 action/state/reason/error code 不变。

### 7.2 插件独立矩阵

- core only。
- core + 内置语音。
- core + 内置识图。
- core + 两者。
- core + 第三方语音。
- core + 第三方识图。
- 语音模块 import 失败时，文字和识图正常。
- 识图模块 import 失败时，文字和语音正常。
- 语音 provider 缺依赖时不加载识图。
- 识图 provider 缺依赖时不加载语音。

### 7.3 状态和性能

- 活动任务在任何 retention 下不被清理。
- 终态记录先归档再清理。
- 崩溃恢复、原子替换和 corrupt-state 恢复行为不变。
- 同一 tick 的状态读取和写入次数有可测量下降。
- 43 MB 级 fixture 的读取、解析、复制、序列化基准。
- 多会话、同内容不同时刻、同名会话和跨会话不串发回归。

### 7.4 Brain First

- 短问候、商品明确询问、模糊车型、上下文追问、异议和闲聊。
- 图片理解结果进入 Brain，但识图模块不生成回复。
- 语音转写进入 session history，但语音模块不生成回复。
- Brain 不可采用时阻断发送并内部告警，不发送本地兜底。

## 8. 当前不应执行的方案

- 不用 SQLite 或统一 Job 替换现有框架。
- 不改 `media_context_tasks`、`voice_transcription` 等既有字段名。
- 不删除或移动旧 import path。
- 不把语音和识图合成一个 `media` 实现模块。
- 不让 core 顶层 eager import 可选 provider。
- 不在一次提交中同时做文件搬迁、字段调整和行为优化。
- 不以“仓库内没引用”为理由删除函数。
- 不让插件拥有 scheduler、session 或客户可见回复。
- 不对历史状态直接批量清理；必须先备份、归档和验证。

## 9. 推荐实施批次

### 批次 A：零行为兼容保护

- 建立 import/signature/payload/state contract tests。
- 建立 core/voice/vision import matrix。
- 建立 43 MB 状态基准 fixture。

预期收益：不给运行速度直接加速，但显著降低后续拆分回归风险。

### 批次 B：插件独立

- 抽出语音 trigger、transcription、compatibility。
- 现有识图文件接入 lazy capability adapter，不新建第二套识图业务实现。
- scheduler、workflow、connector、sidecar 原入口保留 wrapper。

预期收益：语音和识图真正可选，普通文字链路不再被插件依赖拖累；媒体修改的回归面明显缩小。

### 批次 C：状态热路径减负

- tick 内复用 state。
- 合并同阶段写入。
- 审计并减少无必要 `deepcopy`。
- 测试紧凑 JSON。
- 对 `chejin` 备份后 opt-in 终态 retention。

预期收益：这是当前最直接的运行性能收益来源。仅当前样本中，全量 deepcopy 与缩进序列化就约占 2.57 秒 CPU 时间，尚未计入解析和实际磁盘写入。

### 批次 D：大文件内部拆分

- 按纯函数、bridge、pipeline、RPA action 分批抽取。
- 每个旧函数保留 wrapper/re-export。
- 每批只做结构迁移，不顺手修改策略。

预期收益：降低维护成本、冲突率和局部修复的回归范围，运行速度收益次于批次 C。

## 10. 最终建议

当前最优先的不是“再设计一套更漂亮的总框架”，而是依次完成：

1. 冻结并自动验证现有公共合同。
2. 让语音和识图通过惰性 adapter 真正独立可插拔。
3. 保留原状态结构，但减少 43 MB 状态的重复全量处理。
4. 最后再用兼容门面逐段拆小三大主文件和 sidecar。

这条路线既能明显减负，也不会要求现有外部开发者修改调用代码。它把“结构整理”和“行为修复”分开，可避免再次出现修一个媒体问题却影响文字、多会话或发送链路的情况。
