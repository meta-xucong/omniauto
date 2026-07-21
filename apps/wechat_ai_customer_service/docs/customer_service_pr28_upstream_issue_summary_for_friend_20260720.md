# PR #28 上游问题总结与修复对照单

> **当前状态（2026-07-21）：历史上游反馈包。** 本文针对旧 PR head 的逐项证据仍有效，但不代表当前分支源码状态；当前状态以 [PR #28 / Vision 残留问题收口索引](customer_service_pr28_residual_issue_closeout_20260721.md) 为准。

**文档状态：** 待交给 PR 作者修复的上游问题包
**整理日期：** 2026-07-20
**适用 PR：** `Improve WeChat C2 OCR monitoring`
**PR head：** `2120f16744aebe3d8edbdf9c3f407375bfeed279`
**本地原样合并提交：** `f678edb6dac5340dc86e4a84500115af3e2f27b8`
**合并前本地检查点：** `b576844b787fce4dfeeebdd08b1111544a1ad90b`

本文只整理 PR #28 本身及其与本地代码的接缝问题，不在本地修改 PR 文件。朋友修复后，应提供新的上游提交，再重新做字节级核对、专属回归和真实微信验证。

本文件同时遵循以下两个底层基线：

- [客户可见回复所有权基线](customer_visible_reply_ownership_baseline.md)
- [客户服务外部合同与可选插件基线](customer_service_external_contract_and_optional_plugin_baseline.md)

## 1. 结论先行

这次合并后的主要回归不是 Brain、商品库或 Vision 模型造成的，而是 PR 对微信 OCR/RPA 的三类处理存在缺陷：

1. **群聊结构兼容缺陷**：把实际群聊按私聊解析，成员名称被当成消息或导致正文被丢弃。
2. **会话身份设计缺陷**：把可变化的 `conversation_type`、OCR 行指纹和重定位结果混入物理会话身份，导致同一会话在不同观测阶段被判定为不同目标，或者前面允许、发送前又拒绝。
3. **窗口动作与旧能力残留缺陷**：重复点击可能隐藏已打开的会话，固定原点默认值与测试不一致，旧图片入口仍在 PR 文件中形成潜在双所有者。

本次最直接的“已读不回”证据是：

- 00:57:31 检测到“新数据测试”有新信号；
- 00:57:49、00:58:09、00:58:34 三次捕获均得到 `message_count=0`；
- 真实聊天窗口中实际存在图片、“这个车，我记得你们有个老款的，还在吗？”和“在？”；
- 捕获结果只留下“许聪”等成员标签；
- 连续空捕获达到上限后，调度器标记 `capture_failed`，没有创建 Brain 任务。

打开会话本身会使微信变为已读，因此“已读”不代表 Brain 已收到消息。

## 2. 合并事实与回归来源

### 2.1 合并拓扑

合并提交 `f678edb6` 的两个父提交是：

- 本地合并前检查点：`b576844b`；
- PR head：`2120f167`。

合并提交对 PR 的七个冻结文件采用了 PR head 的完整内容。逐文件 blob 核对结果为 7/7 相同：

1. `adapters/wechat_connector.py`
2. `adapters/wechat_win32_ocr/text_normalization.py`
3. `adapters/wechat_win32_ocr_sidecar.py`
4. `tests/run_wechat_win32_ocr_compat_checks.py`
5. `tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py`
6. `tests/run_wechat_win32_ocr_window_action_planning_checks.py`
7. `wechat_message_envelope.py`

因此，本地 `b576844b` 中已经存在的群聊兼容和无副作用目标确认改动，被 PR 版本覆盖。这不是普通的外围适配小差异，而是合并时文件级语义替换造成的回归来源。

### 2.2 合并前后关键差异

| 机制 | 合并前 `b576844b` | PR/合并后 | 结果 |
|---|---|---|---|
| 群标题 `(2)` | 有结构证据识别，可把侧栏 provisional private 校正为 group | 删除该结构证据 | “新数据测试(2)”按名称推成 private |
| 群成员名前缀 | 有几何确认的前缀剥离 | 删除该处理 | “许聪”可能进入正文或成为错误消息 |
| exact session key | 类型不阻断已签发的物理 key | `conversation_type` 不一致即失败 | 同一物理会话可能在发送前被拒绝 |
| 已打开会话 | 有 no-op 保护，避免重复点击 | `open_chat_for_identity` 对已知类型强制行解析/点击 | 可能隐藏聊天区或改变活动目标 |
| fixed origin | 默认值与旧窗口规划测试一致 | Sidecar 默认改为 `False`，测试仍按固定原点断言 | PR 原样默认测试自相矛盾 |
| 图片所有权 | 本地 Vision 已完成隔离 | PR Sidecar/Connector 仍保留旧图片事务和 action | 形成潜在双入口、双所有者 |

### 2.3 可复核证据

本次结论不是根据单次主观观察得出，以下证据可以由朋友独立复核：

- PR 文件差异：`git diff b576844b 2120f167 -- apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`；
- 合并关系：`git show --no-patch --format=fuller f678edb6`；
- 合并前群聊处理：`_active_header_has_structural_group_count`、`_strip_structural_group_speaker_prefix`；
- PR 测试变化：删除结构化群聊测试，保留 `infer_conversation_type("新数据测试") == "private"`；
- 实机监听日志：`runtime/apps/wechat_ai_customer_service/tenants/chejin/logs/customer_service_managed_listener.log`；
- 事件账本：`runtime/apps/wechat_ai_customer_service/tenants/chejin/customer_service/session_ledgers/wx_rpa_v1_178877830fefdaa357d6/events.jsonl`；
- 实机截图：`C:\Users\T14S\AppData\Local\Temp\codex_messages_artifacts\messages_1784480672725.png`。

日志中的三次空捕获均对应同一 `session_key=wx:rpa:v1:178877830fefdaa357d6`，不是 Brain 超时或发送失败。

## 3. 按最近发生顺序的问题清单

下面的问题按最近真实测试暴露的顺序排列。每一项都标明合并前状态和本次合并是否造成回归。

### PR28-GROUP-001 / SID-007 / SID-008：群聊被当成私聊，真实消息被丢弃

**严重度：** P0/P1
**归属：** PR 原文件，群聊结构解析
**涉及：** `wechat_win32_ocr_sidecar.py`、PR OCR 兼容测试

#### 现场现象

真实窗口标题为 `新数据测试(2)`，说明这是群聊。窗口中能看到：

- 群成员“许聪”发出的图片；
- “这个车，我记得你们有个老款的，还在吗？”；
- “在？”。

但 PR 版本的 `messages` 结果只得到三个“许聪”标签，真实文字和图片没有形成有效消息。结果连续三次为空捕获，最终没有进入 Brain。

#### 根因

合并前版本有 `_active_header_has_structural_group_count`，会优先读取聊天标题中的成员数 `(2)`，把类型从侧栏的 provisional `private` 修正为 `group`；同时有 `_strip_structural_group_speaker_prefix`，会把成员名称作为元数据，从正文中剥离。

PR 版本删除了这两段通用结构处理，并继续使用：

```text
infer_conversation_type("新数据测试") == "private"
```

此外，当前 PR 版本在解析消息时不再把已确认的 `normalized_conversation_type` 传给 `sender_fields_for_message_side`，导致群成员角色也无法可靠表达。

PR 新增的头像行校验没有替代群聊结构解析；在当前截图中反而保留了成员标签，丢失真实正文。

#### 合并前状态

**已修复并有测试覆盖。** `b576844b` 包含标题结构校正和成员名前缀剥离。

#### 本次合并是否回归

**是，明确回归。** PR 测试还删除了“结构化群标题 + 成员名前缀剥离”的测试，新增了“`新数据测试` 不应因测试二字推断为群”的断言，锁定了侧栏名称而不是活动聊天窗口的结构证据。

#### 建议上游修复

1. 会话类型分两阶段：侧栏名称只能产生 provisional 类型；活动聊天标题、成员数、群成员标签和气泡布局可以产生 confirmed 类型。
2. confirmed 结构证据优先于名称启发式，但不写死任何账号、标题或关键词。
3. 发送者名称必须作为 OCR/RPA 元数据，不能成为客户正文。
4. 文本气泡、图片气泡、语音气泡都必须按同一行几何关系绑定到发送者。
5. 解析器返回空批次时，必须保留原始 OCR/截图证据，不能静默丢弃。

#### 必须新增的测试

- 侧栏暂判 private、聊天标题带 `(2)`、最终确认 group；
- 群标题没有“群”字但存在成员数；
- 普通私聊与同名群聊并存；
- 成员名 + 文本气泡；
- 成员名 + 图片气泡；
- 成员名与正文分成两个 OCR 框、合成一个 OCR 框、OCR 顺序抖动；
- 负例：仅有名称没有结构证据时不能擅自升级为 group；
- 从 capture 到 ledger、Brain、ready、send 的完整端到端回放。

---

### PR28-OCR-001：侧栏增强 OCR 可能把数字角标、头像或预览片段当成会话标题

**严重度：** P1/P2（已确认设计风险，需继续用真实截图回放确认具体误点）
**归属：** PR 原文件的会话列表增强 OCR

#### 问题

PR 新增 `sidebar_visible_list_enhanced_ocr_items` 和 `session_list_ocr_items`，对侧栏再次放大 OCR，并把结果重新合并到会话候选。该路径可能把以下非标题内容提升为会话名或候选行：

- 未读数字角标；
- 头像或头像旁的 OCR 片段；
- 预览文本截断后的残片；
- 搜索框、时间、状态文字；
- 同一物理行的重复 OCR 结果。

这会污染候选列表，使后续点击面对一个“看起来像真实会话”的伪候选。它与此前“普通会话没有新消息却被错误点击”的本地现象存在接缝关系，但不能直接把某一次具体误点全部归因给 PR；必须通过原始截图和候选来源证明。

#### 合并前状态

合并前 `b576844b` 没有这套新增的侧栏增强 OCR 合并路径，只有原有列表 OCR 和 unread evidence。该风险在合并前没有以当前形式出现。

#### 本次合并是否回归

**是，至少引入了新的候选污染风险。** 当前本地外围修复没有用“排除 2、3、纯数字”之类特判绕过它，因为那会破坏通用性；问题应由 PR 上游修复。

#### 建议上游修复

1. 增强 OCR 只能作为同一物理行的补充证据，不能单独创建新的会话候选。
2. 标题候选必须经过侧栏行几何、标题区域、头像/预览/时间区域排他校验。
3. 重复 OCR 结果按稳定行身份合并，不能把角标或预览当标题拼接。
4. 保留 `source`、原始框、置信度和过滤原因，便于审计；不能静默丢弃。
5. 对无法确认的候选使用 `unknown/unconfirmed`，不得进入物理点击。

#### 必须新增的测试

- 任意未读数字角标（不限定数字 2 或 3）；
- 头像、时间、预览和标题同一行；
- OCR 把 `0/O/Q`、数字和中文混淆；
- 同一行基础 OCR 与增强 OCR 重复；
- 真正的新会话与伪候选同时出现；
- 伪候选只能被记录和告警，不能触发点击或发送。

---

### SID-001 / VIS-IDENT-001：exact key/title 正确，仅因类型漂移被阻断

**严重度：** P1
**归属：** PR 原文件与 Vision 接缝
**涉及：** `session_matches_key`、最终发送守卫、Vision worker target preparation

#### 现场现象

同一物理会话的 `session_key` 和 exact title 均正确，但侧栏观测为 `private`、活动聊天窗口修正为 `group` 后，发送前出现 `conversation_type_not_confirmed` 或 `target_session_type_not_confirmed`，Brain 和 polish 已经成功，最终仍不发送。

#### 根因

合并前版本明确规定：已签发的 opaque `session_key` 是物理身份，类型只是可修正语义，不能因为类型修正而否定同一个 key。

PR 版本将 `session_matches_key` 改为同时比较 `session_key` 和 `conversation_type`。这把两个不同层次的概念混成了一个硬身份。

#### 合并前状态

**合并前已有通用修复。** `b576844b` 的实现和注释明确说明类型不能否决 exact key。

#### 本次合并是否回归

**是。** PR 原样替换恢复了类型硬否决。

#### 建议上游修复

将身份拆为：

- 物理身份：稳定 `session_key` + exact active title/唯一物理候选；
- 语义属性：`conversation_type`、成员数、发送者角色、OCR 证据。

允许更可靠的活动窗口证据把 `private` 校正为 `group`，但以下情况必须继续阻断：key 不一致、exact title 不一致、存在多个物理候选、活动窗口不可确认。

---

### SID-002：查找阶段允许，发送阶段又拒绝

**严重度：** P1
**归属：** PR 与本地发送接缝

#### 问题

部分路径在 capture/lookup 阶段按 key/title 继续执行，消耗了 OCR、Brain 和 polish；最终 send guard 又把同一类型漂移判为绝对失败。

#### 后果

出现“前面都成功，最后不回”的长耗时路径，用户看到已读但没有回复。

#### 合并前状态

合并前已有外围修复方向，但没有完整覆盖 PR 原样身份语义；属于**部分修复**。

#### 本次合并是否回归

**PR 使问题重新暴露并扩大。** PR 的查找和最终守卫继续使用不完全一致的身份谓词。

#### 建议

上游抽取一个内部身份决策函数，capture、schedule、Brain、ready、reacquire、send 全部复用同一判定。任何无法解决的冲突必须在进入 Brain 前失败，不能到发送阶段才失败。

---

### SID-003：session key seed 混入易漂移的类型和行指纹

**严重度：** P2/P1
**归属：** PR 原文件

#### 问题

PR 生成 session key 时使用了 conversation type、sidebar row fingerprint 等可能被以下因素改变的值：

- OCR 小抖动；
- 未读角标变化；
- 侧栏排序；
- 群聊确认前后类型变化；
- UI 滚动或行内容变化。

同一个物理会话可能因此生成不同 key。

#### 合并前状态

**未完全修复。** 这不是本次新引入的全部问题，但合并前已有的外围身份审计已明确不应继续扩大这一设计。

#### 本次合并是否回归

**保留并放大风险。** PR 的类型硬匹配使 key 漂移更容易转化为 capture/send 阻断。

#### 建议

物理 key 必须基于稳定、可迁移的物理身份。可变 OCR 行指纹只能作为观测证据，不能成为不可逆的身份 seed。若必须重新绑定，必须提供明确的旧 key → 新 key rebind 记录，并让同一事务所有阶段使用同一映射。

---

### SID-004：stale key 重新获取后，新旧 key 仍可能在同一事务冲突

**严重度：** P1
**归属：** PR 原文件

#### 问题

PR 有 stale-key semantic reacquire，但存在“active target 已刷新为新 key，调用方仍携带旧 requested key”的路径。看起来重新获取成功，发送阶段仍使用旧 key 做最终比较并阻断。

#### 合并前状态

**未完全修复，属于 PR 设计风险。**

#### 本次合并是否回归

**未证明是本次新引入，但在本次合并后仍存在。** 不能因为当前某轮未复现就关闭。

#### 建议

rebind 必须是显式内部结果：

```text
old_session_key
new_session_key
rebind_reason
physical_evidence
valid_until
```

有歧义时 fail-closed；不能静默覆盖调用方 key。

---

### SID-005：已打开会话被重复定位/点击，导致聊天区隐藏或误操作

**严重度：** P1
**归属：** PR 原文件

#### 现场现象

用户观察到会话被点击隐藏。PR 版本的 `open_chat_for_identity` 在已知 `conversation_type` 时设置 `force_session_row_resolution=True`，即使活动窗口已经是目标，也可能再次解析并点击侧栏行。

#### 合并前状态

**合并前已有明确保护。** `b576844b` 的实现说明已打开且确认的会话应走 no-op，不应因为类型信息再次点击。

#### 本次合并是否回归

**是，明确回归。** PR 版本恢复了强制行解析行为。

#### 建议

1. 先读取当前活动标题、窗口句柄和 session key；
2. 已确认目标时零点击；
3. 只有目标不一致或无法确认时才选择侧栏行；
4. 每个物理动作后重新读取活动状态；
5. 记录点击次数，连续两条同一会话应为零额外点击。

---

### PR28-IMG-001 / IMG-002 / IMG-003：PR 中仍保留旧图片入口，形成双所有者

**严重度：** P1/P2
**归属：** PR 原文件与 Vision 接缝
**涉及：** Sidecar 旧图片 action、Connector 旧剪贴板事务

#### 问题

PR 并不包含完整图像理解 Provider，但仍保留：

- `image-save` / `image-clipboard-copy` action 映射；
- 旧的图片执行函数和依赖；
- Connector 中主动执行旧 clipboard image transaction 的路径。

这与当前要求的“Vision 独立、图片能力唯一归属 Vision”不一致。若 Vision 某条路径回退到 Connector 旧方法，就会重新进入 PR 的旧图片入口，造成双路径、双状态、双失败处理。

#### 合并前状态

**本地 Vision 版本已经基本隔离。** 合并前的本地 Sidecar/Connector 已将生产图片入口收束到独立 Vision 方向。

#### 本次合并是否回归

**是，PR 原样合并把旧残留重新带回源代码。** 当前外围 adapter 只能保证生产不可达，不能声称 PR 源码已清理。

#### 建议

朋友后续版本应：

1. 明确 PR 只拥有通用 OCR/RPA host 能力，不拥有图片复制/理解事务；
2. 移除或正式废弃旧图片 action、daemon 映射和 Connector 图片事务；
3. 若必须保留兼容符号，明确标记 deprecated、不可注册生产入口，并增加调用计数为零的测试；
4. Vision 只通过中性 host port 调用图片能力，不回退到旧 Connector 方法。

必须保留客户图片、我方图片、商品图片三种方向测试，且不改变现有外部字段。

---

### PR28-RPA-001：固定原点默认值与 PR 自带测试相互矛盾

**严重度：** P1
**归属：** PR 原文件和 PR 原生测试

#### 问题

PR Sidecar 在环境变量缺失时将 `WECHAT_WIN32_OCR_WINDOW_FIXED_ORIGIN` 默认设为 `False`，但同一 PR 的兼容测试和窗口规划测试清除环境变量后，仍断言窗口会从 `(-180, 80)` 移动到 `(0, 0)`。原样运行实际得到 `(0, 80)`，所以作者声称的默认测试结果不能在 PR 原样环境复现。

#### 合并前状态

合并前本地基线默认值与旧测试语义一致，未出现这组自相矛盾。

#### 本次合并是否回归

**是，PR 自身引入。** 目前只能在 PR 外通过不覆盖用户显式配置的 adapter 注入兼容默认，不能把它当成上游根修。

#### 建议

统一三者：生产默认值、测试默认值、窗口规划语义。若要改变默认值，必须同步更新测试、迁移说明和外部行为说明；显式用户配置始终优先。

---

### PR28-CONTRACT-001：九个 Sidecar 函数增加可选参数，但没有合同说明

**严重度：** P1/P2
**归属：** PR 原文件

#### 问题

检测到以下 callable 增加了 keyword-only 可选参数：

- `capture_message_history_snapshots`
- `capture_message_history_snapshots_until_anchor`
- `consume_recent_target_switch_validation`
- `dismiss_voice_transcribe_context_menu`
- `messages_payload`
- `open_chat`
- `parse_messages_from_ocr`
- `validate_active_send_target`
- `voice_transcribe_payload`

旧调用目前仍可运行，因此它是行为上的 additive extension；但项目底层规则要求模块间接口、字段和签名冻结，PR 没有说明哪些是 public、哪些是 private，也没有迁移窗口。

#### 合并前状态

外部合同已冻结，未批准这九项扩展。

#### 本次合并是否回归

**是，PR 引入了合同审计问题。** 不是立即运行崩溃，但会给外部调用者带来未记录的边界变化。

#### 建议

逐项说明：

- 是否公开接口；
- 参数用途、默认值和 nullability；
- 旧调用兼容期限；
- 返回字段是否变化；
- 后续是否允许收回。

如果只是内部参数，应从外部导出面隔离；如果确实公开，应补合同快照和兼容测试。

---

### PR28-OBS-001：OCR 重写可能重新突破事件去重

**严重度：** P1（潜在，需复现确认）
**归属：** PR 与本地 observation/scheduler 接缝

#### 背景

合并前曾出现同一视觉状态反复刷成新信号。此前已增加 occurrence/event 去重。PR 大幅重写 OCR 行聚类、speaker metadata 和边界哈希后，以下变化可能让同一物理状态得到不同事件 ID：

- 行排序变化；
- 成员名称是否进入 content；
- private/group 角色变化；
- bubble rect 或 avatar evidence 变化；
- OCR 轻微抖动。

#### 合并前状态

**已有修复，但需要 PR 合并后重新验证。**

#### 本次合并是否回归

目前登记为潜在回归，不能宣称已经再次复现或已经关闭。

#### 建议

事件身份应基于物理 occurrence、稳定会话 key 和可靠消息内容；speaker 元数据与视觉证据只能作为辅助审计，不应让同一消息因 OCR 表现变化而变成新事件。测试要覆盖静止窗口长轮询、旧图片停留、追加文字、切会话返回、重启和 OCR 小抖动。

---

### PR28-RPA-TEST-001：没有可验证的 CI/独立测试证据

**严重度：** P2
**归属：** PR 流程与上游交付

#### 问题

PR 页面没有可核对的 GitHub checks，229/229 OCR 和 28/28 Window Action Planning 主要是作者声明。原样运行时还发现 fixed-origin 默认值冲突；在 PR 外做兼容适配后才得到 effective tests 通过。

#### 合并前状态

合并前没有对 PR 原样树做充分独立复跑。

#### 本次合并是否回归

**不是运行逻辑回归，但属于合并门禁缺陷。** 它使本次合并无法在合并前发现群聊回归、默认值冲突和身份语义覆盖。

#### 建议

以后上游 PR 至少提供：

1. 固定 commit SHA；
2. 原样运行命令和环境；
3. 通过/失败计数、耗时、跳过原因；
4. screenshot replay 资产；
5. 群聊、同名私聊、类型漂移和发送确认的负例。

## 4. PR 接缝问题：不能单独归罪 PR，但必须一起验收

以下问题在实机中出现过，PR 的窗口动作或类型语义可能参与，但目前不能证明全部由 PR 单独引入。它们仍应交给朋友作为联合回归项，不应被错误归类为 Brain 问题。

### 4.1 多会话调度饥饿

现象是一个会话正常回复，另一个有新消息的会话不回，或同一会话首条回复后追加消息不再处理。PR 的窗口扫描、目标确认和重定位可能让一个会话占用物理动作；但本地 Scheduler 也存在任务释放、空捕获和公平性问题。

**合并前：** 历史上已有类似问题，不能证明由 PR 首次引入。
**合并后：** 需要跨会话联合回归，不能只测自问自答单会话。
**建议：** 每个会话独立事件、短临界区、失败释放、无单目标锁；一个会话 OCR/Vision/Brain/发送失败不能阻塞其他合格会话。

### 4.2 输入框已有文本但发送未确认

现象是文字已经写入输入框，但没有形成客户可见气泡，随后可能掉线。PR 的 Window Action Planning 可能贡献动作或确认缺口，但 Brain 已经完成，发送合同也需要本地完善。

**合并前：** 已存在风险。
**合并后：** PR 的窗口行为必须重新做 staged/dispatched/confirmed 三态回归。
**建议：** 只有确认目标会话出现对应 outgoing occurrence 才算发送成功；不明确时停止并告警，不能盲目重复点击或重复发送。

### 4.3 机械化动作与微信掉线

连续点击、复制、切换、输入、重试可能触发微信风控或异常掉线。用户明确要求保留自问自答能力，不能通过禁用测试来规避。

**合并前：** 已有风险，但不是 PR 单独定因。
**合并后：** PR 的重复定位和强制点击使风险上升。
**建议：** 统一动作预算、互斥 lease、自然抖动、背压、登录态观察和熔断；同一目的动作不得重复执行。

## 5. 明确不应归咎 PR 的问题

为避免朋友误修错误层，以下问题目前属于本地外围机制，不应要求朋友在 PR OCR 文件中加入账号特判：

| 问题 | 当前归属 | 说明 |
|---|---|---|
| `杨潇Eve` 无新消息却被点击 | 本地会话候选/状态污染 | 涉及 synthetic、stale、configured 记录与活动候选排序，不等同于 PR 群聊解析缺陷 |
| 启动时旧 pending 被新进程继承 | 本地 bootstrap/Scheduler 生命周期 | 需要按进程生命周期基线化，不应写进 PR OCR |
| 同一视觉状态反复刷信号的最终去重 | 本地 observation/scheduler 接缝 | PR 需提供稳定输出，但事件账本和消费策略属于本地 |
| “人工同事”等客户可见话术 | Brain/Guard/证据包 | PR 不得生成或修改客户回复 |
| 商品库字段、A4L 识别、Vision Provider | Product Master/Vision | PR 只提供通用 host OCR/RPA，不负责商品事实或视觉理解 |
| 服务号过滤及普通新会话全覆盖 | 本地过滤与调度 | 不应通过 PR 里写联系人名称黑名单解决 |

这些问题仍要留在本地问题台账，但不能作为 PR 作者修改 OCR parser 的理由。

## 6. 给朋友的修复优先级

### P0：先修群聊和物理身份

1. 恢复通用活动窗口结构证据优先级；
2. 分离物理 key/title 身份与 conversation type 语义；
3. 修复群成员标签、文字、图片、语音的行绑定；
4. 增加 private→group、同名私聊/群聊和最终发送端到端测试；
5. 取消已确认活动会话的强制重复点击。

### P1：修复可交付性和窗口动作

1. 统一 fixed-origin 默认值、测试和文档；
2. 明确 stale key rebind contract；
3. staged/dispatched/confirmed 发送状态分离；
4. 长轮询事件 ID 稳定，避免 OCR 小抖动重复触发；
5. 补齐真实截图回放和 CI 证据。

### P2：清理残留和合同

1. 清理或正式隔离旧图片 action/Connector 事务；
2. 逐项说明九个新增可选参数的 public/private 属性；
3. 补迁移说明、返回结构和兼容窗口；
4. 为未来 OCR 字段扩展保留未知字段，但不改变现有外部字段。

## 7. 上游修复的通用底线

朋友修复时请遵守以下原则：

- 不写死“新数据测试”“许聪”等账号或标题特判；
- 不通过关键词黑名单替代结构证据；
- 不放宽到 name-only send，不允许同名会话串发；
- 不让 Sidebar preview 伪造客户正文；
- 不让 OCR/RPA/Guard/Reviewer 创作客户可见回复；
- 不改变 Brain、RPA、Vision 对外字段和函数合同；
- 不把 `conversation_type` 当永久物理身份；
- 不因一轮自动测试通过就关闭实机问题；
- 新提交应明确列出修复了哪些 issue ID，并提供正例和负例证据。

## 8. 二次合并前的验收清单

朋友提交新版本后，先不要直接合并。逐项完成：

1. 核对新 PR head 和七个文件清单；
2. 在 PR 分支独立运行 OCR compatibility、window planning、sender-role screenshot replay；
3. 新增并通过群聊结构回放；
4. 新增并通过 private→group 类型校正；
5. 新增并通过同名私聊/群聊负例；
6. 新增并通过已打开会话零重复点击；
7. 新增并通过 stale key rebind；
8. 新增并通过文字、图片、语音的统一消息行绑定；
9. 核对 fixed-origin 默认值、测试和文档一致；
10. 核对旧图片入口是否清理或明确生产不可达；
11. 核对外部签名、返回字段、默认值和旧调用兼容；
12. 在本地合并前建立新的可回滚检查点；
13. 合并后再次执行七文件 blob、Vision 边界、Brain 合同、Scheduler 多会话和发送确认测试；
14. 最后才进行真实微信手测：普通私聊、真实群聊、两会话交替、同一会话连续追问、图片消息和新会话首条。

任何 P0/P1 项没有专属正例、负例和实机证据，都不能认为 PR 已经修好。

## 9. 当前状态与责任边界

本文件记录的是 PR head `2120f167` 的问题，不代表朋友后续修复版本仍然存在同样缺陷。朋友提供新提交后，应在每个 issue 后追加：

```text
Issue ID:
修复提交 SHA:
涉及文件:
新增测试:
正例结果:
负例结果:
合并前 b576 是否已有修复:
是否仍需本地外围适配:
真实微信结果:
最终状态:
```

在上游新版本通过逐项复核前，当前结论保持：

- PR 七个文件原样合并事实成立；
- 群聊解析、类型硬身份、重复点击、旧图片残留、fixed-origin 和合同说明问题仍需上游处理；
- 本地外围适配只能隔离风险，不能宣称 PR 根因已经消失；
- 本轮只新增本总结文档，没有修改 PR 文件，也没有关闭任何既有问题。
