# 微信客服识图 pending-aware 锚点与有限回溯设计 2026-07-28

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

## 1. 背景与目标

当前识图链路在客户发送图片后，如果客户马上又发送文字或连续消息，图片气泡会被顶偏，甚至顶出当前会话可见区域。现有捕获更接近“后置查看当前窗口并复制当前可见图片”，不是“绑定 pending 事件对应图片”。这会导致识图找不到图片、复制错误图片，或在日志上显示复制动作成功但实际未绑定到原 pending 图片。

本设计只修复代码机制层的图片捕获稳定性，不改变客户可见回复所有权。图片模块只负责 occurrence、捕获、理解结果和 Brain evidence；客户可见回复仍只能由 `customer_service_brain` 生成。

目标：

- 最大程度借鉴语音转写模块的分层锚点、候选排除、有限回溯和操作后绑定校验。
- 不直接 import 或依赖语音模块实现，保持 voice 与 vision 的可选插件独立。
- 不增加 scheduler、Brain、RPA send、外部插件调用方可见的必填参数或字段。
- 不把坐标、anchor、hash、cache token、cache 路径泄漏到外部 payload、Brain bridge 或客户消息。
- 将图片复制从“当前可见最新图”升级为“pending-aware 组合身份选图”。

非目标：

- 不实现“图片刚出现就立即取资产”的长期资产预取路线。
- 不做无限离屏找图；证据不足或歧义时 fail-closed。
- 不改变无 `pending_signal_id` 的旧直接调用语义。
- 不生成任何本地客户可见 fallback 文案。

## 2. 硬性合同约束

### 2.1 对外合同不变

本次改造不得改变现有公共调用方式、返回 shape、字段含义和默认兼容行为。特别是：

- `pending_signal_id` 仍是现有外部字段，不改名、不改必填性、不重解释为“单张图片 ID”。
- 现有 vision 插件入口、worker 调用、Brain bridge 和 compatibility facade 保持旧调用方可用。
- 新增字段只允许存在于 vision 私有数据结构、私有日志或私有 store 内。
- 最终进入 scheduler/Brain/messages 的数据必须递归剥离所有私有字段，例如 bounds、anchor、hash、cache token、cache path、visual private key 等。

### 2.2 pending_signal_id 不是单张图片身份

`pending_signal_id` 只能表示一次待处理事件或捕获窗口，不能单独作为图片身份。选图必须使用组合身份，至少包含：

- `session_key`
- target 的确认身份或归一化 target 证明
- `conversation_type`
- `pending_signal_id`
- `pending_observation_id`，当现有调度身份中提供该值时参与绑定
- customer/self side
- structural occurrence/message identity
- 邻近文字关系，例如 preceding/following text id 或内容 key
- 时间标记
- 纵向顺序或 occurrence ordinal

一个 signal 对应多个候选，或组合证据不足时，必须 fail-closed，不能凭“最新可见图”冒险复制。

`pending_observation_id` 是当前仓库已有的可选活动身份，不是本设计新增的外部字段，也不得变成新必填合同。使用规则：

- 当 `pending_observation_id` 存在时，它必须与 `pending_signal_id` 一起参与 occurrence 绑定、store claim 和失效判断。
- 当 observation id 存在且发生变化时，旧 occurrence、旧 claim、旧候选排除状态不得复用。
- 当 observation id 缺失时，保持现有兼容路径，不能因为缺失而拒绝旧调用。
- target-state/freshness 相关测试必须覆盖 signal/observation 一致、不一致、缺失三种情况。

### 2.3 voice/image 严格独立

识图模块可以复用语音方案的设计思想，但不得 import 语音实现，也不得依赖语音字段、语音配置或语音状态。

允许借鉴：

- 分层锚点 key。
- exclusion set。
- bounded backsearch。
- 操作后结果绑定。
- 测试思想。

不允许：

- `optional_plugins/vision` import `optional_plugins/voice`。
- 让 voice import vision。
- 将 voice 专用字段变成 image 公共字段。
- 把语音转写状态作为图片捕获判断依据。

只有在抽出真正中立、无 voice/image/provider/OCR/clipboard 依赖的纯 helper，且不改变公共 import path 或字段合同时，才可以考虑共享；否则优先在 vision 内实现 visual 版。

## 3. 总体设计

设计分两阶段落地。

### 阶段一：vision 内部 pending-aware selector 与 bounded backsearch

Owner：`apps/wechat_ai_customer_service/optional_plugins/vision`。

阶段一不引入跨进程 occurrence store。它在现有复制事务内，通过当前截图和有限回溯截图建立临时候选集合，并选择最可能属于当前 pending 事件的图片。

关键变化：

1. 当前截图先构建 visual observations，而不是直接选择 `_latest_visual_bubble()`。
2. 选择器使用可执行的“硬门槛 + 软证据 + margin”判定：
   - 硬门槛先过滤 session、target、conversation_type、side、pending signal/observation 一致性、未 processed、未 excluded。
   - 软证据再比较邻近文字关系、时间标记、结构身份、跨帧 ordinal、纵向关系。
   - 只有 best candidate 达到 vision 内部最小置信度，且与第二候选有明确 margin 时才允许 UI 操作。
   - 多候选平分、仅凭最新/最低位置、只有模糊 OCR 文本时一律 fail-closed。
   - 跨回溯帧优先复用 structural id；没有 structural id 时，只能使用 side、归一化时间、邻近文字身份、ordinal 等组合证据，不能以当前 y 坐标或“最新可见”重新猜。
3. 当前截图无明确候选时，进入 bounded backsearch。
4. 每次候选操作失败后，将 visual exclusion key 加入本次 transaction 的排除集合。
5. 歧义、target 不一致、菜单不可信、剪贴板未变或剪贴板不是图片时 fail-closed。

阶段一保留无 pending 的旧兼容路径：

- 若没有 `pending_signal_id`，且调用方属于旧“复制当前可见图片”路径，则保留旧的当前可见选择行为。
- 新 scheduler 路径在携带现有 `pending_observation_id` 时必须走严格 pending-aware selector；仅有 `pending_signal_id` 且缺失 observation 的历史路径保持旧兼容，不把 observation 变成新必填合同。
- 不得把 `pending_signal_id` 变成新必填合同。

### 阶段二：vision 私有跨进程 occurrence store

Owner：仍为 `optional_plugins/vision`；store 不属于 scheduler、Brain、语音或全局公共状态。

阶段二解决 `observe_current_surface` 与 `copy-current-image` 可能运行在不同进程的问题。进程内 dict cache 不可用。必须采用以下两种之一：

1. vision-owned bounded TTL 私有 store。
2. 将 observation 与 copy 合并到同一个 vision-owned transaction。

推荐路线是私有 store，因为它保持现有外部调用方式更稳定。

私有 store 要求：

- 有 TTL，过期自动清理。
- 有总量上限和单 session 上限。
- 原子读写，避免半写文件被 worker 读取。
- 可并发消费，避免两个 worker 抢同一 occurrence。
- 不改变任何现有公共状态文件形状。
- store 路径、cache token、坐标和 hash 不进入外部 payload。
- key 至少隔离 `session_key`、target 确认身份、`conversation_type`、side、`pending_signal_id`，以及存在时的 `pending_observation_id`。
- record 主身份不得包含瞬时坐标或 `visual_anchor_key`。同一图片因滚动上下移动时，应优先依赖 structural message id，其次使用 structural/stable key。
- 能处理重复 occurrence、过期、会话切换、target 切换和消费失败。
- 写入时 candidate 的非空身份字段可以覆盖 request；空字符串、None、空列表等不得覆盖 request 中有效的 pending identity。
- 从 request 继承的 pending identity 只用于隔离和 TTL，不等同于“已证明是该图片”；claim 时仍必须有邻近文字或 reference record 等关系证据。

建议私有记录结构只存在于 vision 内部，概念字段如下：

```text
VisualOccurrenceRecord
  schema_version
  recorded_at
  expires_at
  session_key
  target_identity
  target_display_name
  conversation_type
  pending_signal_id
  pending_observation_id
  side
  structural_message_id
  visual_anchor_key
  visual_stable_key
  visual_structural_key
  neighboring_text_keys
  wechat_message_time
  ordinal_evidence
  bounds_or_anchor_snapshot
  weak_visual_fingerprint
  processed_or_failed_anchor_keys
```

这些字段是私有实现细节，不是外部合同。开发时应通过 contract tests 证明它们不会出现在最终 messages、Brain bridge、customer image proxy、scheduler raw capture 对外可见结构中。

## 4. Visual anchor 设计

图片版 anchor 应模仿语音的分层思路，但不能复制语音字段。

建议视觉身份分三层：

1. `visual_anchor_key`
   - 当前截图内的操作锚点。
   - 可包含 side、bounds bucket、time marker、neighbor key、occurrence ordinal。
   - 用于单次 transaction 内 exclusion。

2. `visual_stable_key`
   - 对轻微纵向移动更稳定。
   - 不应使用精确绝对 y 坐标。
   - 可使用 y bucket 半径、side、time marker、邻近文字、宽高比例 bucket。

3. `visual_structural_key`
   - 尽量脱离当前坐标。
   - 可使用 side、pending window、neighboring text、time marker、同侧 ordinal-from-bottom。
   - 用于跨帧、回溯和 occurrence cache。

注意：

- hash/thumbnail 只能作为弱校验，不得作为唯一身份。
- 同内容多图片必须保持可区分。
- 同一图片上下移动不应产生全新身份。
- 无法区分时必须返回歧义失败。

## 5. Bounded backsearch 约束

图片回溯必须整体运行在现有 vision/RPA lease 内，例如当前 `image_clipboard_transaction` 等同类互斥动作。不得在 lease 外滚动或点击微信。

每次回溯必须遵守：

1. 滚动前确认当前 target/session。
2. 每次截图后确认 target/session 未变化。
3. 每次候选右键/菜单点击前再次确认 target/session。
4. 恢复到最新后再次确认 target/session。
5. 发现焦点变化、target 不匹配、pending identity 变化，立即中止。
6. `finally` 尽力恢复到最新位置。
7. 恢复后必须再次复核 target/session。恢复失败或恢复后 target/session 不匹配时，当前 transaction 必须 fail-closed，不能把已复制结果交给后续 clipboard consumer。
8. 恢复失败只写内部审计，不得把恢复原因、坐标、cache 或 claim 信息写入公共 transaction。
9. 不得跨会话滚动查找，不得影响 send safety。

推荐限制：

- 小步向上滚动。
- 最大滚动步数可配置在 vision 内部默认值中，但不能新增外部必填配置。
- 最大耗时和最大截图数必须有硬上限。
- 每步间隔使用现有人类化动作节奏。

## 6. 操作后绑定校验

图片复制成功不能只依赖剪贴板 generation 变化。短期主要校验：

- 当前 target/session 仍匹配。
- context menu 明确包含“复制图片”或等价文案。
- right-click anchor 与选中的 visual observation 一致。
- side/customer-self 方向一致。
- 剪贴板 generation 变化。
- 剪贴板内容确实是图片。
- copy action 成功后，仍需等待 bounded backsearch 的恢复最新与恢复后 target/session 复核通过，整个 transaction 才可返回成功。
- store claim 只能在恢复与复核均通过后 `consumed=True`；若 copy 已成功但恢复 gate 失败，必须 release claim，不能标记 consumed。

中期可加入弱视觉校验：

- 候选 crop 的尺寸/比例 bucket。
- clipboard bitmap 尺寸/比例。
- thumbnail/crop hash 或 perceptual hash。

弱视觉校验限制：

- 只用于 vision 内部验证或调试。
- 不进入客户消息、Brain evidence 或外部诊断字段。
- 不能替代 target/session/side/组合锚点校验。
- 不能作为长期客户事实或持久证据。

## 7. 旧调用兼容策略

保持无 `pending_signal_id` 的旧直接调用兼容。

兼容规则：

- 没有 pending 事件时，不得把 pending-aware 组合身份作为必填前置。
- 旧路径可以继续使用当前可见图片选择逻辑。
- 如果未来要将旧路径改成 fail-closed，必须单独提交合同变更方案并取得仓库所有者批准。
- 若只有 `pending_signal_id` 而缺失 `pending_observation_id`，按现有兼容路径处理，不能把 observation id 变成事实必填。
- 携带 `pending_observation_id` 的新 scheduler 路径不得降级为旧“最新可见图”选择，除非已通过 selector 证明只有一个安全候选。

## 8. 数据隔离与清理

私有 occurrence store 必须按会话隔离：

- `session_key`
- target 确认身份
- `conversation_type`
- side
- `pending_signal_id`

清理策略：

- 每次读写前 opportunistic cleanup。
- TTL 到期删除。
- 总量超过上限时先删过期，再删最旧。
- 成功消费后可标记 consumed，保留短 TTL 审计窗口。
- 同一 occurrence 已 consumed 时，重复 observation 不得将其复活为未消费。
- 失败 occurrence 可记录 failed keys，但不能永久拉黑。

并发策略：

- 写入使用临时文件 + 原子替换，或等价原子机制。
- 消费使用短租约/claim 标记，避免并发 worker 同时操作同一 occurrence。
- claim 超时后可自动释放。
- active claim 存在时，新的 observation 不得覆盖记录或重置 claim。
- consume 必须检查 claim 是否过期；过期 claim 即使 claim_id 相同也必须安全失败。
- 成功或失败结束后要清理 claim，或等待严格 TTL，避免 stale claim 长期影响后续。
- 任何锁失败或 store 损坏都应 fail-closed 或回退到阶段一当前事务 selector，不得崩溃 core。

## 9. 文件与模块建议

建议新增或调整的模块均在 vision 内部：

```text
apps/wechat_ai_customer_service/optional_plugins/vision/
  capture/
    visual_anchor.py          # visual key、candidate score、exclusion helpers
    backsearch.py             # bounded screenshot/OCR/detect/scroll loop
    clipboard_binding.py      # copy result 与 visual anchor 的内部绑定校验
  occurrence_store.py         # 私有 TTL store 抽象与默认实现
```

现有门面保持不变：

- `optional_plugins/vision/plugin.py`
- `optional_plugins/vision/service.py`
- `optional_plugins/vision/runtime.py`
- `optional_plugins/vision/integrations/wechat_current.py`
- `optional_plugins/vision/integrations/wechat_worker.py`
- `internal/vision_bridge.py`
- `workflows/customer_image_*` compatibility aliases

如果需要给 worker 增加内部 operation 或 optional CLI flag，必须是 additive optional，旧命令继续可用。优先选择 vision 私有 store，减少外部 CLI 合同变化。

## 10. 测试计划

### 10.1 结构与合同测试

- vision 不 import voice。
- voice 不 import vision。
- core-only、core+voice、core+image、core+both 仍可 import。
- 旧 vision public import path、facade 和 compatibility alias 仍可用。
- 无 `pending_signal_id` 的旧调用保持兼容。
- `pending_observation_id` 是已有可选身份，不成为新必填字段。
- private visual fields 不出现在：
  - scheduler messages
  - Brain bridge
  - customer image proxy
  - final customer-visible reply input
  - public audit messages

### 10.2 图片 pending 与回溯测试

- 图片后立即跟文字，当前截图中图片仍可见：选择图片而不是后续文字。
- 图片被后续消息顶偏：visual identity 不因整体纵向移动改变。
- 图片被顶出当前可见区：bounded backsearch 找回并复制。
- 同一 pending 下多张客户图：证据不足时 fail-closed。
- 同一 `pending_signal_id` 但不同 `pending_observation_id`：不得复用旧 occurrence 或旧 store claim。
- `pending_signal_id` 与 `pending_observation_id` 均一致：允许复用仍在 TTL 内且 target/session 匹配的 occurrence。
- 缺失 `pending_observation_id`：保持旧兼容路径，不把 observation id 变成必填。
- 两张图片具有相同时间标记或相同内容证据且候选平分：fail-closed。
- best candidate 与第二候选 margin 足够时才允许复制。
- 跨回溯帧有 structural id 时优先复用 structural id；无 structural id 时必须依赖 side、归一化时间、邻近文字、ordinal 的组合证据。
- 同内容多图片：不能用 hash 折叠成同一 occurrence。
- self 图片只进入 self context，不触发 customer image reply turn。
- 旧可见历史图片遇到新文字时不被重新激活。
- 无 pending 的旧直接复制仍按兼容路径运行。

### 10.3 UI 动作与失败测试

- 右键后菜单不是“复制图片”：候选加入 exclusion，继续或 fail-closed。
- 剪贴板 generation 未变：失败并记录内部原因。
- 剪贴板内容不是图片：失败并释放资源。
- 复制后 target/session 变化：失败，不向 Brain 提供 adoptable 结果。
- 回溯后恢复最新成功/失败均有内部审计。
- backsearch 达到最大步数/最大耗时/最大截图数时停止。

### 10.4 多进程、多会话与 TTL 测试

- observe 写入私有 store，copy worker 从另一个进程读取。
- TTL 过期后不可被消费。
- session A 的 occurrence 不能被 session B 消费。
- 同 target 不同 conversation_type 不串。
- 同 signal 不同 observation 的 cache claim 不串。
- 并发 worker claim 同一 occurrence 时只有一个成功。
- store 损坏或锁失败不会导致 core 崩溃。

### 10.5 Brain First 测试

- 图片捕获失败不得生成本地客户可见 fallback。
- Brain 不可用时仍按 Brain First 规则阻断/交接，不由 vision 生成话术。
- 视觉理解只作为 evidence/context，不能改写 Brain 策略。

## 11. 验收标准

方案实现后必须满足：

1. 客户发图片后紧跟文字，图片被顶偏时，vision 能优先绑定 pending 图片。
2. 图片被顶出当前可见区但仍在有限回溯范围内时，vision 能找回或明确 fail-closed。
3. 多候选、跨会话、target 焦点变化、剪贴板异常时不误复制、不误入 Brain。
4. 无 pending 旧调用保持兼容。
5. 所有 private anchor/cache/hash 字段不泄漏到外部合同。
6. voice/image 插件仍严格独立。
7. 客户可见回复所有权仍归 `customer_service_brain`。

## 12. 人工确认点

代码实现前需要仓库所有者确认：

- 是否接受 vision 内新增私有 TTL occurrence store。
- 是否接受阶段一保留无 pending 旧路径的“当前可见图”兼容行为。
- 是否接受 bounded backsearch 的默认上限由 vision 内部定义，不新增外部必填配置。
- 是否接受 hash/thumbnail 仅作内部弱校验，不进入外部诊断字段。

确认后再进入代码实现与回归测试。
