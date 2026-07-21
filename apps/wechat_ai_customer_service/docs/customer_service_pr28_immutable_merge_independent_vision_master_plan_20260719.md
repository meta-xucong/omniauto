# 微信客服独立 Vision 先行、PR #28 原样合并与外围适配总开发方案（2026-07-19）

> **当前状态（2026-07-21）：历史总方案。** 原样合并阶段已结束；当前分支包含经所有者授权的 Vision 残留清理。当前状态以 [PR #28 / Vision 残留问题收口索引](customer_service_pr28_residual_issue_closeout_20260721.md) 为准。

## 0. 文档地位、决策与适用范围

本文是以下工作的最终总开发规格：

1. 先把微信图片理解能力做成真正独立、可移植、可替换的 Vision 模块。
2. 在 Vision 独立验收通过后，字节级原样合并朋友提交的 PR #28。
3. 不在 PR 拥有的文件内修补本地功能；所有本地能力通过 PR 外围适配。
4. 把 PR 中继承的旧图片残留、会话身份漂移、重复点击和测试缺口完整记录，交给 PR 作者后续优化。
5. 合并、自动测试和真实微信手测完成后，按独立问题台账逐项复审，不允许仅凭“测试绿了”关闭已知问题。

本文服从并引用：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：所有客户可见回复只能由 `customer_service_brain` 编写；Vision、RPA、Guard、Reviewer 和适配器不得生成或替换客户可见措辞。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：外部合同冻结；Vision 与 Voice 必须严格独立、可选、懒加载，核心只能依赖中性插件协议和既有兼容字段。
- [customer_service_absolute_independent_vision_module_refactor_plan_20260718.md](customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)：保留其中“只认当前剪贴板、图片能力单一所有者、Brain 不接收图片字节”的硬原则；其“已经完全收口”的结论由本文重新限定和复审。
- [customer_service_ephemeral_clipboard_vision_rebuild_20260713.md](customer_service_ephemeral_clipboard_vision_rebuild_20260713.md)：微信图片内容只允许来自本次右键复制后同一事务内读取到的当前剪贴板位图。
- [customer_service_pr28_post_merge_issue_audit_ledger_20260719.md](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)：本文的伴随问题台账；任何实施、合并、测试和交付都必须同步更新该台账。

本文不授权修改任何外部接口、模块间字段、公共函数签名、CLI route、错误码或状态文件结构。除仓库所有者另行批准外，所有改造都必须发生在模块内部或新增的兼容适配层中。

### 0.1 已确认的上游对象

| 项目 | 固定值 |
| --- | --- |
| GitHub PR | [PR #28 Improve WeChat C2 OCR monitoring](https://github.com/meta-xucong/omniauto/pull/28) |
| 审计时 PR head | `2120f16744aebe3d8edbdf9c3f407375bfeed279` |
| PR 父提交 / 审计时 master | `378cc3f7b3b24e88ff8d9f145c185bb5c48d509c` |
| PR 状态 | Draft、GitHub 显示 mergeable/clean；审计时没有 GitHub CI checks |
| PR 作者声明测试 | 229/229 OCR 兼容检查、28/28 Window Action Planning；必须在本地重新验证，不能只引用声明 |

### 0.2 PR 拥有的七个文件

以下七个文件属于 PR #28 的不可修改上游范围：

1. `apps/wechat_ai_customer_service/adapters/wechat_connector.py`
2. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py`
3. `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
4. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
5. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py`
6. `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py`
7. `apps/wechat_ai_customer_service/wechat_message_envelope.py`

“原样合并”在本文中的正式定义是：

- PR 提交对象、提交父子关系和所有 diff hunk 完整进入集成分支。
- 合并完成的 PR 基线检查点中，上述七个文件的 blob 必须与 `2120f167` 完全一致。
- 本地功能不得通过挑选 PR hunk、手工抄写、ours/theirs 混合或在 PR 文件中二次改写来适配。
- PR 合并后的本地开发只允许修改 PR 之外的文件；若最终必须修改上述七个文件，必须停止实施，先由仓库所有者决定是放弃“最终 blob 不变”，还是请求 PR 作者更新上游。

---

## 1. 最终架构决策

### 1.1 两层所有权

系统分为两个相互独立的层：

```text
PR #28：不可修改的通用微信 OCR/RPA 上游
  ├─ 窗口发现、激活和可见性
  ├─ 会话列表 OCR 和目标确认
  ├─ 通用截图/OCR 帧
  ├─ 通用鼠标、键盘、右键和安全等待原语
  ├─ 普通消息读取、语音动作和文字发送
  └─ RPA 安全守卫与审计

本地独立 Vision：唯一图片能力所有者
  ├─ 图片 occurrence、方向和 freshness
  ├─ 图片气泡结构定位
  ├─ 当前目标图片右键“复制”
  ├─ 剪贴板代次校验和当前位图读取
  ├─ 内存生命周期和清零
  ├─ LLM 图像理解
  ├─ 客户/我方图片上下文投影
  ├─ 商品图片描述、索引和相似匹配
  └─ 模块私有失败、审计和测试
```

PR 不理解图片；Vision 不拥有通用会话调度、Brain、发送或 PR 内部状态。

### 1.2 三种身份必须分开

当前事故证明，把 `conversation_type` 同时当作会话语义和物理 RPA 身份会产生矛盾。内部实现必须区分：

| 内部概念 | 用途 | 是否可漂移 | 是否允许新增外部字段 |
| --- | --- | --- | --- |
| 已签发会话身份 `session_key` | 绑定 capture、Brain task、ready reply、send | 同一待处理任务中不可静默改变 | 否；继续使用既有字段 |
| 可见标题 `target_name` | UI 标题确认和人类审计 | OCR 可抖动，但精确规范化后必须匹配 | 否 |
| 语义会话类型 | Brain/历史判断 private/group | 可以由聊天区结构从 private 修正为 group | 否；继续使用既有 `conversation_type` |
| RPA 行候选类型过滤 | 帮助同名行消歧 | 只是一次 UI 观测，不是永久身份 | 不对外暴露；私有变量 |

硬规则：

1. 已签发的精确 `session_key` 命中同一物理行时，`conversation_type` 漂移不得否定该 key。
2. 发送前精确标题必须匹配；标题不匹配继续硬停止。
3. session key 不匹配或无法确认时继续硬停止；不能降级为只按显示名发送。
4. 同名可见候选不唯一时继续硬停止；不得模糊合并。
5. `conversation_type` 可以进入 Brain 和历史，但不能在 exact key + exact title 已确认时单独阻止发送。
6. 上述规则只能在 PR 外围适配中落实；PR 内部缺陷另行记录给作者。

### 1.3 客户可见回复所有权不变

Vision 只能输出：

- 当前图片的文字理解。
- 图片方向、occurrence 和 provenance。
- 已授权的商品匹配候选。
- 进入既有消息、Ledger 和 Brain evidence 字段的兼容投影。

Vision 不得：

- 写客户回复。
- 决定转人工、报价、库存、政策或承诺。
- 在失败时生成“看不到图片”等客户可见模板。
- 直接发送消息。
- 修改 ready reply 或 final polish。

图片理解失败后，是否以及如何回复仍由 Brain 根据当前文字、图片失败事实和授权证据决定；如果 Brain 不可用或不可采纳，必须阻止发送并进入内部告警/人工接管，不得由本地模块写兜底。

---

## 2. 为什么必须先完成 Vision 再合并 PR

### 2.1 当前已确认事实

当前工作区的共享 Sidecar 已达到图片专用符号零命中，图片执行迁入 `optional_plugins/vision`；但系统整体仍存在以下未完成项：

- Scheduler 在模块导入时直接引用 `optional_plugins.vision.compatibility`。
- Brain 在模块导入时直接引用 Vision 的兼容投影函数。
- `listen_and_reply` 在模块导入时直接引用 Vision 兼容入口。
- `internal/scheduler/vision_bridge.py` 直接导入并替换为 Vision occurrence 实现。
- Connector 当前虽只保留薄委托，但 Connector 属于 PR 文件，合并后会被 PR 版本覆盖。
- 当前 Vision runtime 的部分路径仍调用 Connector 图片专用方法；PR 版本的这些方法会重新走旧 Sidecar 图片 action。

所以“Sidecar 已清空”不等于“Vision 已经与 PR 可无缝替换”。Vision 必须先做到：即使 Connector 和 Sidecar 整体替换为 PR 版本，生产运行仍不调用它们的旧图片入口。

### 2.2 先行完成的收益

先完成并冻结 Vision，可以把后续问题清晰分类：

- 合并前 Vision 独立测试失败：Vision 自身问题。
- PR 原样合并后 OCR/RPA 测试失败：PR 或 PR 适配问题。
- 联合测试中图片失败：Vision Host Adapter 问题。
- 联合测试中普通文字发送失败：PR 会话/发送或外围身份适配问题。
- Brain 回复质量失败：Brain/evidence/Guard 问题，不能甩给 Vision 或 RPA。

禁止在一次提交中同时搬迁 Vision、合并 PR、修改 Scheduler 身份和优化 Brain；那会重新失去可归因性。

---

## 3. Phase V0：实施前封存与特征锁定

### 3.1 当前工作区保护

当前工作区存在大量已修改和未跟踪文件。进入任何合并前必须：

1. 记录 `git status --short --branch`。
2. 记录 `git diff --stat`、`git diff --numstat` 和所有未跟踪路径。
3. 把当前状态放入独立安全分支或可恢复检查点；不得直接 reset、checkout 覆盖或删除。
4. 记录当前 master、origin/master、PR head 和 merge-base。
5. 为 Vision 相关文件建立单独清单，区分“真正实现”“冻结兼容壳”“宿主字段透传”“测试/文档”。
6. 记录真实运行数据、测试账号状态和 runtime 状态文件；禁止把现场状态混入代码提交。

退出门禁：可以在不依赖当前工作目录的情况下完整恢复合并前状态。

### 3.2 冻结既有合同

合并前从现有合同测试和快照中固化：

- `WeChatConnector` 公开方法签名。
- Sidecar CLI route、参数和 JSON 结果字段。
- `TargetConfig`、capture、ready reply、send payload 的既有字段。
- Message envelope、Ledger、Scheduler state 的形状。
- Vision 旧 import path 和旧方法签名。
- Brain evidence 的图片兼容字段。
- 商品图片索引字段。
- 所有 reason/state/error code。

不得以“PR 没用到”“仓库内没有调用”为由删除或改名。

---

## 4. Phase V1：Vision 完全独立化

### 4.1 唯一生产所有者

以下能力只能存在于 `apps/wechat_ai_customer_service/optional_plugins/vision/`：

1. 图片信号触发。
2. 客户/我方方向判断。
3. 图片气泡候选和唯一性判断。
4. 右键图片和点击“复制”。
5. 剪贴板代次验证、当前位图读取和内存释放。
6. 视觉 Provider 调用、Prompt、重试、超时和结果归一化。
7. 图片 occurrence、去重、freshness 和幂等。
8. 客户图片 proxy、我方图片 context-only 投影。
9. Brain evidence、Ledger 和商品候选兼容投影。
10. 商品图片描述、索引、指纹和匹配。

外部旧路径若属于冻结合同，只能是无状态、无分支、无缓存的门面。

### 4.2 中性宿主协议

Vision 只能依赖中性 Host Ports：

- `RpaLeasePort`
- `ConversationTargetPort`
- `WindowFramePort`
- `UiActionPort`
- `ClipboardPort`
- `VisionProviderPort`
- `ProductImageRepositoryPort`
- `VisionAuditPort`

Host Port 的名称和 payload 不得出现：

- Brain 回复策略。
- Scheduler 队列状态。
- Voice Provider。
- 图片业务分类词条。
- 客户可见措辞。

### 4.3 生产微信绑定

`optional_plugins/vision/integrations/` 内建立唯一微信绑定：

1. 启动 Vision 自有 worker。
2. Worker 懒加载 PR/当前 Sidecar 作为通用 Host Ops。
3. Worker 调用通用窗口选择、目标确认、截图、OCR 和鼠标原语。
4. 图片结构、方向、右键 Copy 和剪贴板证明仍由 Vision 内部实现。
5. 生产路径不得构造 `image-save` 或 `image-clipboard-copy` Sidecar action。
6. 不得调用 PR Connector 的旧 `run_customer_clipboard_image_transaction` 实现。
7. PR Host Ops 缺少某个通用函数时，Vision 返回确定性 unavailable/adapter error，不得回退到截图裁切或历史文件。

### 4.4 核心调用解耦

必须完成：

- Scheduler 只依赖 `optional_plugins.contract.OptionalCapabilityPlugin` 和 registry，不直接 import `optional_plugins.vision.*`。
- Brain 不 import Vision 具体实现；图片文字事实通过既有 payload/evidence 字段进入。
- `listen_and_reply` 不 import Vision 实现；只通过中性插件协议调用。
- `internal/scheduler/vision_bridge.py` 若必须保留旧 import path，只能是中性 registry/facade，不能 import Vision occurrence 实现。
- Voice 与 Vision 不互相 import，不共享 Provider、配置、状态或生命周期。

### 4.5 当前剪贴板原子事务

一次成功取图必须满足：

1. 获取全局 RPA lease。
2. 确认目标会话，保存不可变目标证明。
3. 获取当前窗口帧和 OCR items。
4. Vision 确认唯一图片气泡和 customer/self 方向。
5. 读取右键前剪贴板 sequence number。
6. 在目标图片相对位置执行一次右键。
7. 定位并点击“复制”。
8. 确认剪贴板 sequence number 发生变化。
9. 只读取新 sequence 的位图。
10. 在锁内接管图片内存对象。
11. 释放 RPA lease 后调用 Provider。
12. Provider 重试只复用本次内存图片，不重新右键。
13. 生成文字理解和兼容投影。
14. `finally` 清零可变图片内存。

任何一步失败都不得：

- 使用旧剪贴板。
- 使用截图裁切。
- 保存图片文件。
- 换取另一张历史图片。
- 把占位消息伪装成成功识图。
- 因 Vision 失败阻塞无关文字会话。

### 4.6 客户图、我方图、商品图

| 类型 | 必须识图 | 是否触发客户回复任务 | 是否进入历史 | 商品匹配 |
| --- | --- | --- | --- | --- |
| 客户图片 | 是 | 作为客户当前轮证据，由 Brain 决定回复 | 是，标记 customer | 可执行 |
| 我方图片 | 是 | 否 | 是，标记 self/context-only | 可选，只作上下文 |
| 商品库图片 | 上传/同步后异步索引 | 否 | 不作为聊天消息 | 生成描述、指纹和索引 |

### 4.7 Phase V1 退出条件

- Vision 直接 API 可在第三方 Host Ports 上完成端到端内存图片理解。
- 默认微信生产路径不调用任何旧 Sidecar 图片 action。
- Scheduler、Brain、Listener 不直接 import Vision 实现。
- core-only、voice-only、vision-only、both、自定义 vision、缺依赖组合全部通过。
- 客户图和我方图的方向、上下文和幂等通过。
- 图片匹配通过；索引失败不影响商品保存/大风车同步。
- 没有新增图片落盘。
- 外部合同快照保持不变。

---

## 5. Phase V2：Vision 冻结基线

Vision 完成后必须形成独立检查点，建议命名：

```text
pre-pr28-independent-vision-20260719
```

检查点必须包含：

- 代码提交 SHA。
- Vision 目录清单和源文件 hash。
- 公共 API/signature 快照。
- Host Ports 快照。
- 测试命令、测试数量、耗时和结果。
- 未完成真实微信手测项。
- 当前已知问题台账版本。

禁止用“工作区现在能跑”代替提交检查点。

---

## 6. Phase P0：PR #28 字节级原样合并

### 6.1 合并前置条件

- Vision V1/V2 全部通过。
- 当前工作区已安全封存。
- 新建干净集成分支，不在脏 master 上直接 merge。
- PR head 仍是 `2120f167`；如果发生变化，必须重新审计并更新本文和问题台账。
- merge-base 仍为预期提交；不同则停止并重新制定合并方案。

### 6.2 合并方式

在父提交仍为 `378cc3f7` 时，优先使用 fast-forward only，使 PR 提交对象原样进入：

```powershell
git fetch origin pull/28/head:refs/remotes/origin/pr/28
git switch -c codex/pr28-immutable-integration 378cc3f7
git merge --ff-only origin/pr/28
```

若不能 fast-forward：

- 不自动解决。
- 不手工复制 PR 文件。
- 不使用 `-X ours` 或 `-X theirs` 直接吞掉冲突。
- 先更新 PR 基线审计，再由仓库所有者批准新的合并方式。

### 6.3 字节级验证

合并检查点立即执行：

```powershell
git diff --exit-code origin/pr/28 -- `
  apps/wechat_ai_customer_service/adapters/wechat_connector.py `
  apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py `
  apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py `
  apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py `
  apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_sender_role_screenshot_replay.py `
  apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_window_action_planning_checks.py `
  apps/wechat_ai_customer_service/wechat_message_envelope.py
```

并逐个记录 `git rev-parse HEAD:<path>` 与 `git rev-parse origin/pr/28:<path>` 的 blob id。任何一个不同都视为原样合并失败。

---

## 7. Phase P1：PR 外围 Vision 联合适配

### 7.1 不修改 PR 文件

联合适配只允许发生在：

- `optional_plugins/vision/`
- 中性可选插件 registry/contract
- PR 不拥有的 Scheduler/Listener/Brain 内部适配点
- 新增的 tests/docs

不得在 PR 七个文件内删除旧图片残留、改变调用、增加 Vision import 或修会话 BUG。

### 7.2 PR 旧图片残留处理

PR branch tree 中仍存在旧图片兼容函数、参数、daemon 映射和 Connector 剪贴板事务。处理规则：

- 不调用。
- 不注册为生产 action。
- 不作为 Vision fallback。
- 不纳入图片成功路径。
- 在问题台账标记为 upstream residual。
- 把具体路径、符号、可达性和建议交给 PR 作者。
- 在 PR 作者修复前，用运行时调用追踪测试证明生产未触发。

这些残留存在于 PR 文件意味着“最终 source zero vision”暂时不能与“PR 七文件字节级不变”同时成立。本文选择：PR 文件不变、生产所有权保持 Vision 单一、残留作为已知上游债务公开记录，不伪称已经从源码消失。

### 7.3 Vision Host Adapter

Vision Adapter 需要适配 PR 提供的通用函数，但不得适配 PR 的图片入口。至少验证：

- 窗口选择和 DPI 标准化。
- 目标会话确认。
- 当前标题和 session key 证明。
- 窗口帧/OCR items 获取。
- 通用右键/点击。
- 失焦、登录页、白屏、服务号容器的 fail-closed。
- 无效 hwnd 和进程下线。

Adapter 自身必须小、可替换、无 Provider/商品匹配/Brain 逻辑。

---

## 8. Phase P2：PR 外围会话身份适配

### 8.1 当前实测故障

2026-07-19 `新数据测试` 实测中：

- requested session key：`wx:rpa:v1:178877830fefdaa357d6`
- confirmed session key：相同
- requested title / confirmed title：均为 `新数据测试`
- requested conversation type：`group`
- confirmed conversation type：`private`
- 最终 Guard：`conversation_type_not_confirmed` / `target_session_type_not_confirmed`

Brain 和 polish 已经生成可发送回复，RPA 在最终类型硬校验处阻断。这不是 Brain、商品库或消息捕获失败。

### 8.2 本地外围策略

在不修改 PR 的前提下：

1. Scheduler/Ledger/Brain 保留真实语义 `conversation_type=group`。
2. 调用 PR 的物理 RPA 目标确认时，不把语义类型当作永久身份硬条件。
3. 内部只向 PR 传：
   - 已签发 session key；
   - 精确规范化标题；
   - 必要时传本次侧栏物理观测类型或 `unknown/empty`，而不是聊天区校正后的语义类型。
4. 外部方法签名、参数名和 payload 字段不变；区别只存在于私有适配变量。
5. exact key 或 exact title 不匹配仍然硬停止。
6. key 陈旧时，只允许唯一、可证明的可见语义重定位；歧义即停止。
7. 不能按显示名模糊合并 stale/active/configured 三类 session 记录。

### 8.3 已打开会话重复点击

PR 对已知 `conversation_type` 会设置 `force_session_row_resolution=True`。本地适配必须保证：

- 已经确认 active key + title 时不再次点击左侧会话行。
- 仅当需要真实切换且候选唯一时点击一次。
- 点击后只被动等待并确认，不重复机械点击。
- “会话被点击隐藏”必须有专门回归和实机证据。

### 8.4 Vision 同样受身份策略约束

Vision worker 的 `_prepare_target` 不得单独复制 PR 的硬类型策略。图片目标必须与文字目标使用同一外围身份原则，否则文字能回、图片却会因为同一 private/group 漂移无法启动。

---

## 9. Phase T：测试、审计与迭代闭环

### 9.1 测试层级

必须按顺序执行：

1. 静态边界和合同测试。
2. Vision 纯端口测试。
3. Vision worker 模拟。
4. PR 原生 OCR/RPA 测试。
5. Scheduler/Listener 多会话模拟。
6. Brain First、Guard 和角色连续性测试。
7. PR + Vision + Scheduler 联合离线测试。
8. 本地微信受控单会话实测。
9. 本地微信双会话/群聊实测。
10. 图片双方方向和后续追问实测。

任何低层测试失败，不进入更高层实测。

### 9.2 必测场景

#### 普通文字

- 新私聊首条消息。
- 同一私聊连续追问。
- 两个会话同时出现新消息。
- 一个会话正常、另一个追加消息。
- 群聊标题包含成员数。
- 同名私聊/群聊候选。
- 当前会话已打开，不重复点击。
- 服务号、订阅号等排除项。

#### RPA 行为与发送确认

- 除明确排除的系统/服务会话外，全部新会话首条和追加消息都形成独立任务。
- 一个会话 Brain 超时、图片慢或发送失败时，其他会话继续公平进展。
- 回复进入输入框后，分别记录 staged、send action 和 outgoing bubble confirmed；未确认不得记作成功。
- 发送结果不明时不得机械重复发送，避免双发；必须停止当前事务并留下可追踪原因。
- 已打开正确会话不重复点击；切换目标时使用最少动作并在动作后重新观察。
- 自问自答测试继续允许，不能用禁用会话或关键词规避踢下线；统一使用低扰动、带抖动、带背压和可中止的通用 RPA 节奏。
- 长测统计每分钟点击、按键、切换、重复动作、登录状态变化和任务等待时间。
- 服务号/系统会话零误点，普通私聊/群聊名称与系统词相似时不得误过滤。

#### 会话身份

- exact key + exact title + type 一致。
- exact key + exact title + private/group 漂移。
- exact key + 错误 title。
- 错误 key + exact title。
- key 陈旧、唯一可见候选。
- key 陈旧、多个候选。
- stale/active/configured 三条同名记录并存。
- 进程重启后旧状态重放。

#### 图片

- 客户单图、连续多图。
- 我方单图、连续多图。
- 客户无关图片。
- 客户发送与商品库相同图片。
- 图片后立即文字追问。
- 我方图片后客户追问“刚才发的是什么”。
- 剪贴板不变、被抢占、非位图。
- Provider 超时/失败。
- Vision 禁用/缺依赖。
- 两会话同时出现图片。

#### Brain 和可见回复

- 奥迪 A4L 等商品详情能从商品库证据回答。
- 不暴露 AI、自动化、内部角色或“人工同事接管”。
- Reviewer 只给反馈，Brain 修复后仍是唯一回复作者。
- Brain 不可用时不发送本地模板。
- 无关图片也必须由 Brain 就当前消息作出适当响应或明确处理，不能静默不回。

### 9.3 每轮迭代记录

每轮必须记录：

- 代码 SHA、PR SHA、配置摘要。
- 测试名称、命令、开始/结束时间和耗时。
- 会话、session key、title、semantic/physical type。
- capture/Brain/polish/send 的事件 id。
- 成功或失败的唯一根因。
- 是否新增、关闭或重开问题台账项。
- 是否触碰 PR 七文件 blob。

禁止只记录“通过”“没回”“可能是 OCR”。

---

## 10. 问题台账与朋友反馈机制

所有问题必须进入 [customer_service_pr28_post_merge_issue_audit_ledger_20260719.md](customer_service_pr28_post_merge_issue_audit_ledger_20260719.md)。

### 10.1 状态机

```text
DISCOVERED
  → REPRODUCED
  → LOCAL_GUARD_REQUIRED / UPSTREAM_REPORT_REQUIRED
  → LOCAL_GUARD_VERIFIED / UPSTREAM_REPORTED
  → UPSTREAM_FIXED
  → MERGED_AND_RETESTED
  → CLOSED
```

允许的终态还包括：

- `ACCEPTED_DEBT`：仓库所有者明确接受，记录风险和复审日期。
- `NOT_REPRODUCIBLE`：必须附完整环境和三轮复测证据，不能因一次没出现就关闭。
- `OUT_OF_SCOPE`：必须说明真正所有者和转移位置。

### 10.2 关闭条件

问题不能因为以下理由关闭：

- 单元测试通过。
- 代码看起来合理。
- PR 作者说本地通过。
- 一次手测没有复现。
- 通过禁用功能绕开。
- 通过把群聊误判成私聊掩盖。

每项必须满足台账规定的独立验收。

### 10.3 给朋友的上游报告

每个 upstream issue 至少包含：

1. PR SHA 和父提交。
2. 精确文件、函数和行范围。
3. 最小复现步骤。
4. requested/confirmed identity。
5. 实际结果和期望不变量。
6. 为什么不是业务层/Brain/Vision 问题。
7. 本地临时外围适配，不要求 PR 接受本地实现。
8. 建议补充的通用测试。
9. 修复后回归结果。

---

## 11. 回滚、发布和停止条件

### 11.1 回滚点

- R0：当前工作区安全封存。
- R1：Vision 独立完成检查点。
- R2：PR 原样合并检查点。
- R3：外围 Vision 适配通过。
- R4：外围身份适配通过。
- R5：离线全矩阵通过。
- R6：真实微信手测通过。

每个阶段单独提交，不跨阶段 squash 到无法定位。

### 11.2 必须停止的情况

- PR head 变化但未重新审计。
- PR 文件 blob 与 head 不一致。
- 必须修改 PR 文件才能继续。
- 需要新增/改名外部字段。
- Vision 必须回退到旧 Sidecar 图片 action 才能工作。
- exact key/title 不一致仍被允许发送。
- 两会话出现串图、串上下文或串发。
- 客户可见回复由非 Brain 模块生成。
- 自动化导致微信被踢下线，且行为原因未根治。

### 11.3 交付标准

只有同时满足以下条件才可宣称可交付：

- Vision 独立矩阵通过。
- PR 七文件字节级验证通过。
- PR 原生测试本地复跑通过。
- 外围身份适配完整通过。
- 多会话、群聊、图片和发送实机通过。
- 客户可见角色连续性通过。
- 问题台账没有未解释的 P0/P1。
- P2/P3 均有明确 owner、临时边界和复审日期。
- 朋友反馈包已经生成，所有上游问题有编号。

---

## 12. 历史文档优先级和被取代结论

### 12.1 Vision 文档

[customer_service_absolute_independent_vision_module_refactor_plan_20260718.md](customer_service_absolute_independent_vision_module_refactor_plan_20260718.md) 的需求、目录、当前剪贴板、单一所有者和测试原则继续有效；以下结论由本文取代：

- “模块已完全收口”改为“图片实现所有权基本收束，但中性协议依赖和 PR 合并后残留仍待完成”。
- “Sidecar source zero vision 是永久门禁”改为“当前本地 Sidecar 为零；PR 字节级不变阶段允许存在已登记、生产不可达的上游残留”。
- “Scheduler/Brain 只经中性协议”必须重新验收，不能由兼容模块位于 vision 目录就自动视为通过。

### 12.2 会话身份文档

[customer_service_session_identity_startup_visual_boundary_20260712.md](customer_service_session_identity_startup_visual_boundary_20260712.md) 和 [customer_service_capture_identity_recurrence_20260713.md](customer_service_capture_identity_recurrence_20260713.md) 中“conversation type 不一致必须否定相同 session key”的部分由本文取代。

继续有效的部分：

- capture、Brain、reply、send 必须保持 session key 绑定。
- 标题不匹配和 key 不匹配必须 fail-closed。
- 同名会话不得只按显示名发送。
- 身份失败不得进入名称兜底或本地客户回复。

被取代的部分：

- conversation type 作为不可变永久身份。
- 为确认类型而强制重复点击已打开会话。
- 把聊天区结构校正后的 group 与侧栏 private 视为两个会话。

### 12.3 观测去重文档

[customer_service_session_observation_event_dedup_20260714.md](customer_service_session_observation_event_dedup_20260714.md) 继续有效；合并后必须重新验证同一红点状态不会反复产生新事件。不得用取消 freshness 或缩短上下文绕过。

---

## 13. 开发前最终审计

| 审计项 | 结论 |
| --- | --- |
| 是否先完成 Vision 再合并 | 是，Phase V1/V2 是 PR 合并硬门禁 |
| 是否原样保留朋友 PR | 是，PR 七文件在合并检查点必须与 head blob 一致 |
| 是否在 PR 文件内修本地 BUG | 否，全部使用 PR 外围适配并登记 upstream issue |
| 是否允许两套图片生产路径 | 否，PR 旧图片入口必须生产不可达，Vision 是唯一 owner |
| 是否误称 PR 包含识图模型 | 否，PR 残留属于图片获取/兼容，不是视觉理解 Provider |
| 是否保留 Brain 回复所有权 | 是，Vision/RPA/Guard 只提供证据和控制 |
| 是否改变现有字段和接口 | 否，内部适配不新增、删除、改名任何跨边界字段 |
| 是否解决 private/group 漂移 | 本地外围可规避；PR 内部缺陷进入上游问题台账 |
| 是否降低错发保护 | 否，exact key/title 和候选唯一性仍是硬门禁 |
| 是否把单测当实机 | 否，真实微信单/双会话和双方图片为独立交付门禁 |
| 是否保留问题复审机制 | 是，所有当前问题已进入伴随台账，关闭必须有证据 |

最终判断：本方案可以最大限度同时满足 PR 上游完整性、Vision 独立性、外部合同稳定、Brain First、多会话安全和可追责开发。但它不宣称“原样合并即自动修复所有问题”；真正的闭环由“Vision 先行冻结 + PR 原样合并 + 外围适配 + 上游问题登记 + 分层测试 + 逐项复审”共同构成。
