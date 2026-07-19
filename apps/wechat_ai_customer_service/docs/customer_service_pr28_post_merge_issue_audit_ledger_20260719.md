# 微信客服 PR #28 合并前后问题台账与逐项复审清单（2026-07-19）

## 0. 文档用途、约束与配套方案

本文不是一次性故障总结，而是贯穿“Vision 独立化、PR #28 原样合并、外围适配、自动测试、真实微信手测、朋友后续修复、二次合并”的永久问题台账。所有目前已经发现但不能或不应在 PR 文件内直接修改的问题，都必须保留编号、证据、处理边界和关闭条件。后续不得以“整体测试通过”“暂时没复现”或“已经换了实现”为理由删除记录。

本文必须和以下文档一起使用：

- [customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md](customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md)：本轮最终开发、合并和测试总方案。
- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)：所有客户可见回复只能由 `customer_service_brain` 编写。
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)：外部合同冻结，Vision/Voice 是严格独立的可选模块。
- [customer_service_absolute_independent_vision_module_refactor_plan_20260718.md](customer_service_absolute_independent_vision_module_refactor_plan_20260718.md)：Vision 原始独立化要求；其中过宽的“已经完全收口”结论由总方案和本台账重新限定。

本文不授权：

1. 改动 PR #28 拥有的七个文件来消除本地冲突。
2. 增删、改名或改变任何现有跨模块字段、函数签名、返回结构、CLI route、错误码和状态文件结构。
3. 为某个会话、车型、短语或测试账号堆叠结构化特判。
4. 降低 exact session key、exact title、候选唯一性和发送目标确认的防串发门禁。
5. 由 Vision、RPA、Guard、Reviewer、Fallback 或本地模板生成客户可见回复。

---

## 1. 台账如何记录和维护

### 1.1 一条问题的固定字段

每条问题必须保留下列字段；未知项写“待确认”，不得省略：

| 字段 | 含义 |
| --- | --- |
| `issue_id` | 永久编号。编号一旦被引用，不复用、不改号。 |
| `title` | 可复现问题的简短标题。 |
| `severity` | `P0` 至 `P3`，定义见 1.2。 |
| `owner` | `local_integration`、`pr_author`、`shared` 或指定负责人。 |
| `source_scope` | 问题位于本地模块、PR 原文件、二者接缝、运行状态或文档。 |
| `first_seen` | 首次发现日期、分支/提交、实机或离线场景。 |
| `evidence` | 日志、状态记录、测试、代码位置、截图和精确 SHA。 |
| `reproduction` | 能重现问题的最短步骤。 |
| `actual` | 当前实际行为。 |
| `expected_invariant` | 不依赖具体账号/关键词的通用正确性。 |
| `local_containment` | 不修改 PR 原文件时，本地如何隔离或阻止风险。 |
| `upstream_request` | 需要朋友在 PR 后续版本解决的根因。 |
| `verification` | 自动、模拟和实机测试清单。 |
| `status` | 使用 1.3 的固定状态。 |
| `audit_stamp` | 最后一次核对的日期、PR head、本地提交和审计人。 |

### 1.2 严重级别

| 级别 | 定义 | 发布规则 |
| --- | --- | --- |
| `P0` | 可能串会话、错发、突破客户可见回复所有权、绕过安全门禁或破坏不可恢复数据 | 未关闭或未被可靠 fail-closed 隔离时禁止实机自动发送 |
| `P1` | 新消息不回、图片丢失、会话反复点击/隐藏、被踢下线、生产路径重复所有者 | 未解释、未测试或本地隔离不可靠时禁止交付 |
| `P2` | 架构边界不纯、上游残留、测试盲区、状态污染、延迟或维护风险 | 可在明确隔离、owner 和复审日期下进入受控测试 |
| `P3` | 文档、诊断信息、非生产死代码或可观测性缺口 | 可延期，但必须保留 owner 和验证方式 |

### 1.3 状态机

只允许使用以下状态，状态前进必须附证据：

1. `DISCOVERED`：已有可信线索，尚未形成稳定复现。
2. `REPRODUCED`：已用代码、日志或实机步骤稳定复现。
3. `LOCAL_GUARD_REQUIRED`：问题在 PR 文件或上游语义中，本地必须先做外围隔离。
4. `LOCAL_GUARD_VERIFIED`：本地隔离已通过单元、集成和对应实机场景，但上游根因仍在。
5. `UPSTREAM_REPORT_REQUIRED`：需要整理给朋友的最小复现和建议。
6. `UPSTREAM_REPORTED`：已提交给朋友，记录链接/提交/日期。
7. `UPSTREAM_FIXED`：朋友声称修复；尚未在合并后的完整系统验证。
8. `MERGED_AND_RETESTED`：修复已进入目标分支并完成规定测试。
9. `CLOSED`：满足本问题全部关闭条件，证据可追溯。
10. `ACCEPTED_DEBT`：仓库所有者明确接受风险、边界和复审日期；不能由开发者自行决定。
11. `NOT_REPRODUCIBLE`：多次严格按原场景复测仍不能复现；不是关闭，后续仍可重新激活。

禁止从 `DISCOVERED` 直接跳到 `CLOSED`。PR 原文件中的问题即便已被本地外围隔离，也只能到 `LOCAL_GUARD_VERIFIED`，直到朋友上游修复并重新合并验证。

### 1.4 证据和审计纪律

- 每次合并、测试或手测都追加审计记录，不覆盖旧结果。
- 必须记录 PR head SHA 和本地 commit；“最新版本”不是有效证据。
- 日志必须能关联 `session_key`、exact title、目标类型观测、消息事件和发送结果。
- 涉及图片时，记录本次剪贴板事务 ID/时间窗口、方向、消息 occurrence 和 Vision 结果引用；不保存图片字节作为历史上下文。
- 涉及客户可见文字时，记录 Brain draft、Guard/Reviewer 反馈和最终发送文本的作者链；不以关键词命中作为唯一判定。
- 自动测试、离线回放、模拟桌面和真实微信手测属于不同证据层，不能互相替代。
- 一个问题的外围规避和上游根修是两个结论，必须分别记录。

---

## 2. 当前审计基线

| 项目 | 2026-07-19 基线 |
| --- | --- |
| PR | GitHub PR #28 `Improve WeChat C2 OCR monitoring` |
| PR head | `2120f16744aebe3d8edbdf9c3f407375bfeed279` |
| PR parent / 当时 master | `378cc3f7b3b24e88ff8d9f145c185bb5c48d509c` |
| PR 文件数 | 7 个，清单见总方案 0.2 |
| GitHub 状态 | Draft、mergeable/clean；没有 GitHub CI checks |
| PR 作者声明测试 | 229/229 OCR、28/28 Window Action Planning；尚需本地复跑 |
| 当前本地 Vision 边界回归 | 6/6 + 3/3 + 7/7 + 7/7 + 3/3，共 26 项通过 |
| 当前 Sidecar 图片专用 token | 本地当前版本为 0；PR head 中仍有旧图片残留 |
| 已确认故障会话 | `新数据测试`，实际标题显示 `新数据测试(2)` |
| 已确认 session key | `wx:rpa:v1:178877830fefdaa357d6` |
| 已确认类型漂移 | 请求/侧栏推断 `private`，打开聊天区结构确认 `group` |
| 已确认结果 | Brain/最终润色已完成，最终发送守卫以类型不一致阻断 |
| 工作区状态 | 大量未提交改动；合并前必须先建立可恢复检查点 |

以上基线只代表审计时事实。合并时若 PR head、文件清单、测试声明或工作区状态变化，必须先更新本节，再开始实施。

---

## 3. 问题总表

| issue_id | 严重度 | 简述 | owner | 当前状态 |
| --- | --- | --- | --- | --- |
| `PR28-IMG-001` | P2 | PR Sidecar 保留旧图片执行函数及依赖 | pr_author | REPRODUCED |
| `PR28-IMG-002` | P2 | PR Sidecar 的图片 action 处于半退役不一致状态 | pr_author | REPRODUCED |
| `PR28-IMG-003` | P1 | PR Connector 仍拥有旧剪贴板图片事务，形成双所有者 | shared | LOCAL_GUARD_REQUIRED |
| `VIS-BOUND-001` | P2 | Scheduler 直接导入具体 Vision compatibility | local_integration | REPRODUCED |
| `VIS-BOUND-002` | P2 | Brain 与 listen_and_reply 直接导入具体 Vision compatibility | local_integration | REPRODUCED |
| `VIS-BOUND-003` | P2 | Scheduler vision_bridge 直接 importlib 到具体实现 | local_integration | REPRODUCED |
| `VIS-RUNTIME-001` | P1 | Vision 某些路径仍调用 Connector 图片专用方法 | local_integration | REPRODUCED |
| `VIS-TEST-001` | P2 | 当前边界测试不能证明 PR 原样合并后的生产唯一性 | local_integration | DISCOVERED |
| `VIS-IDENT-001` | P1 | Vision 目标准备继承 private/group 硬冲突 | shared | REPRODUCED |
| `SID-001` | P1 | exact key/title 相同，仅因类型漂移而不发送 | pr_author | REPRODUCED |
| `SID-002` | P1 | 会话查找策略与最终发送守卫语义不一致 | shared | REPRODUCED |
| `SID-003` | P2 | session key seed 含易漂移的类型/行指纹 | pr_author | REPRODUCED |
| `SID-004` | P1 | stale key 重新获取后，旧请求 key 与新 active key 仍可能冲突 | pr_author | DISCOVERED |
| `SID-005` | P1 | 已知类型强制再次定位/点击，可能隐藏或切错聊天区 | pr_author | REPRODUCED |
| `SID-006` | P0 | 同名 stale/physical/synthetic 记录并存，错误合并可导致串发 | local_integration | LOCAL_GUARD_REQUIRED |
| `SID-007` | P1 | 缺少 sidebar private 到 header group 再发送的端到端回归 | shared | REPRODUCED |
| `SID-008` | P2 | 测试把真实群标题样例硬断言为 private，掩盖漂移 | pr_author | REPRODUCED |
| `OBS-001` | P1 | 同一视觉状态曾反复刷成新消息，PR 后需重验事件去重 | shared | DISCOVERED |
| `STATE-001` | P2 | synthetic/configured 记录可能污染活动会话候选 | local_integration | DISCOVERED |
| `SCHED-001` | P1 | 一个会话正常时，其他合格新会话或追加消息可能饥饿 | shared | REPRODUCED |
| `SEND-001` | P1 | 回复已写入输入框但发送动作/确认未完成 | shared | REPRODUCED |
| `RPA-BEHAVIOR-001` | P1 | 机械化高频操作存在微信踢下线风险 | shared | DISCOVERED |
| `FILTER-001` | P1 | 服务号排除与“其余新会话全覆盖”边界需回归 | local_integration | DISCOVERED |
| `RPA-TEST-001` | P2 | PR 无 GitHub checks，作者测试声明尚未本地独立验证 | shared | REPRODUCED |
| `BRN-ROLE-001` | P1 | 回复出现“后续由人工同事”并暴露角色断裂 | local_integration | REPRODUCED |
| `BRN-PIPE-001` | P2 | 减负后 Reviewer/Guard 仍需证明不漏角色连续性 | local_integration | DISCOVERED |
| `PROC-001` | P1 | 工作区改动过大且检查点不足，难以定位最近回归 | local_integration | REPRODUCED |
| `DOC-001` | P2 | 历史身份文档把 conversation type 当永久硬身份 | local_integration | REPRODUCED |
| `DOC-002` | P2 | 历史 Vision 文档“完全收口”结论过宽 | local_integration | REPRODUCED |

---

## 4. PR #28 旧图片残留

### PR28-IMG-001：PR Sidecar 保留旧图片执行函数及依赖

- `severity`：P2。
- `owner`：`pr_author`。
- `source_scope`：PR #28 的 `adapters/wechat_win32_ocr_sidecar.py`。
- `first_seen`：2026-07-19，对 PR head `2120f167...` 做 blob 级文本对照。
- `evidence`：当前本地 Sidecar 对 `wechat_image_save_capture`、`image-clipboard-copy`、`image-save` 和图片执行函数的计数均为 0；PR head 分别仍有 3、1、2 和 4 处，另有视觉图片消息辅助函数残留。
- `reproduction`：从 PR head 读取 Sidecar blob，搜索上述 token，并和当前本地 Sidecar 对照。
- `actual`：一个宣称聚焦 OCR/RPA 的 PR 仍带有旧图片获取实现依赖。
- `expected_invariant`：PR Sidecar 只负责 OCR/窗口动作；图片复制与理解由可选 Vision 模块唯一拥有。
- `local_containment`：PR 七文件保持原样；在 PR 外确保这些函数不注册为生产可达入口，Vision 不调用它们。
- `upstream_request`：朋友后续独立提交删除确认无调用的图片残留，并给出无入口证明。
- `verification`：静态调用图、CLI 枚举、进程命令审计、Vision 启停矩阵、真实客户图/我方图测试。
- `status`：`REPRODUCED`。
- `audit_stamp`：2026-07-19 / PR `2120f167...` / 本地提交待建立。
- `关闭条件`：上游新提交移除残留；合并后 PR OCR 测试和 Vision 全矩阵均通过；无第三方调用者被破坏。

### PR28-IMG-002：图片 action 半退役不一致

- `severity`：P2。
- `owner`：`pr_author`。
- `source_scope`：PR Sidecar CLI/daemon action 映射。
- `first_seen`：2026-07-19 PR 静态审计。
- `evidence`：图片 action 仍存在参数、daemon mapping 或分支，但公开 choices/主路径已部分移除，形成“代码还在、入口不完整”的状态。
- `reproduction`：逐项对照 argparse choices、daemon action map、dispatch branch 和执行函数。
- `actual`：残留既不是完整受支持能力，也不是已彻底删除的死代码。
- `expected_invariant`：每个 action 要么有完整、受测、对外稳定的合同，要么在确认无消费者后完整退役；不得半存在。
- `local_containment`：本地不恢复历史 route，不给 Vision 建兼容调用，不用它做失败回退。
- `upstream_request`：上游先做消费者审计，再以独立提交完整删除或正式恢复；不得在本地猜测意图。
- `verification`：CLI 合同快照、未知 action 错误行为、daemon mapping、OCR 229 项、本地第三方导入检索。
- `status`：`REPRODUCED`。
- `audit_stamp`：2026-07-19 / PR `2120f167...`。
- `关闭条件`：上游 action 生命周期一致，合同测试和下游兼容证据齐全。

### PR28-IMG-003：Connector 旧剪贴板事务造成图片能力双所有者

- `severity`：P1。
- `owner`：`shared`；上游负责旧实现，本地负责确保不可达。
- `source_scope`：PR `adapters/wechat_connector.py` 与本地 Vision 接缝。
- `first_seen`：2026-07-19 PR/当前分支对比。
- `evidence`：PR Connector 主动执行旧 clipboard transaction 并调用 `image-clipboard-copy`；当前 Connector 已被改为 Vision 薄委托，但该文件属于 PR 七文件，原样合并会恢复旧逻辑。
- `reproduction`：对照 PR 和当前 Connector 的图片方法调用图；将 Vision 运行路径追踪到 Connector。
- `actual`：若不先解耦，合并后 Vision 和 Connector/Sidecar 都可能拥有图片捕获事务。
- `expected_invariant`：一次微信图片获取只有一个生产 owner，即 Vision；Connector 只提供中性桌面原语，不编排图片语义事务。
- `local_containment`：合并前把 Vision 改为依赖 PR 外的中性 host adapter；合并后不调用 Connector 图片专用方法；PR 旧动作生产不可达。
- `upstream_request`：朋友后续将旧 clipboard image transaction 从 Connector 移除或下沉为不含图片语义的原子桌面操作。
- `verification`：运行时调用计数、故障注入、剪贴板新鲜度、客户图/我方图、Vision disabled/core-only、PR 文件 blob 校验。
- `status`：`LOCAL_GUARD_REQUIRED`。
- `audit_stamp`：2026-07-19 / PR `2120f167...`。
- `关闭条件`：本地外围隔离只能到 `LOCAL_GUARD_VERIFIED`；上游删除并重新合并、全矩阵通过后才可 `CLOSED`。

---

## 5. Vision 模块边界和运行时接缝

### VIS-BOUND-001：Scheduler 直接导入具体 Vision compatibility

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：Scheduler 存在对 `optional_plugins.vision.compatibility` 的直接导入。
- `actual`：核心调度在模块导入期知道具体 Vision 包。
- `expected_invariant`：Scheduler 只依赖中性插件协议/registry 和既有兼容 payload；Vision 缺失时核心仍可启动。
- `修复边界`：保持现有公共调用和字段不变，把解析/调用放到中性 capability lookup；懒加载且 absence-safe。
- `verification`：core-only、core+voice、core+vision、core+both、custom-vision、Vision 依赖缺失、Vision 初始化异常。
- `status`：`REPRODUCED`。
- `关闭条件`：禁止导入扫描、插件矩阵和旧调用路径合同全部通过。

### VIS-BOUND-002：Brain 与 listen_and_reply 直接导入具体 Vision compatibility

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：Brain 和 `listen_and_reply` 当前存在具体 Vision compatibility 导入。
- `actual`：Brain/RPA 编排层知道 Vision 实现包，独立摘取和替换不彻底。
- `expected_invariant`：Brain 只消费既有消息/上下文字段中的图片理解文字和授权商品证据；监听层只调用中性能力。
- `修复边界`：不改变 Brain 外层 evidence contract、不新增共享字段；通过中性适配填充现有字段。
- `verification`：无 Vision 模块时文本客服全流程、custom Vision、图片结果注入、Brain 不接触图片字节、客户可见作者链。
- `status`：`REPRODUCED`。
- `关闭条件`：静态边界、导入故障、运行时插件矩阵和 Brain fixture 均通过。

### VIS-BOUND-003：vision_bridge 直接定位具体 occurrence

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：`internal/scheduler/vision_bridge.py` 使用 importlib 直达具体 Vision occurrence。
- `actual`：名为 bridge 的内部层仍把具体 Vision 对象形状泄漏给 Scheduler。
- `expected_invariant`：bridge 应实现中性协议的宿主侧适配，不应使 Scheduler 依赖具体实现路径。
- `修复边界`：保留旧 facade 和返回结构；实现移入插件侧或 registry binding，外部调用无感。
- `verification`：旧 import path、返回对象 key、异常/None 行为、第三方自定义 Vision。
- `status`：`REPRODUCED`。
- `关闭条件`：具体包路径不再出现在核心禁止导入清单，兼容合同不变。

### VIS-RUNTIME-001：Vision 仍调用 Connector 图片专用方法

- `severity`：P1；`owner`：`local_integration`。
- `evidence`：某些 Vision runtime 分支会调用 Connector 的图片方法；PR 原样合并后这些方法将回到旧 Sidecar action。
- `actual`：Vision 源码虽集中，关键执行仍可能穿回 PR 拥有的旧图片能力。
- `expected_invariant`：Vision 自己编排右键复制和当前剪贴板事务，只从中性 host port 获得点击、菜单选择、剪贴板读取等原语。
- `修复边界`：先于 PR 合并完成 host adapter；禁止以旧 Connector 图片方法作为 fallback。
- `verification`：mock Connector 拒绝图片专用方法仍能完成 Vision；调用追踪中旧 action 为 0；真实图片方向双测。
- `status`：`REPRODUCED`。
- `关闭条件`：V1/V2 冻结矩阵通过，PR 合并后同一测试再通过。

### VIS-TEST-001：当前边界测试没有覆盖 PR 原样树

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：当前 26 项 Vision 边界/契约测试通过的是本地当前树，而 PR head 的 Sidecar/Connector 含旧残留。
- `actual`：若把“当前 source-zero”直接当作合并后判定，会得出错误结论，甚至诱使修改 PR 文件。
- `expected_invariant`：同时区分“本地冻结树源码零残留”和“PR 原样树中已登记残留但生产不可达”。
- `修复边界`：新增两类门禁：Vision 自身绝对边界；PR 文件 blob 不变 + 旧入口运行时不可达。
- `verification`：在 V2 checkpoint 和 P0 checkpoint 各跑一次，报告分开出结果。
- `status`：`DISCOVERED`。
- `关闭条件`：两类门禁均可重复运行并在 CI/本地报告中明确区分。

### VIS-IDENT-001：Vision 继承会话类型硬冲突

- `severity`：P1；`owner`：`shared`。
- `evidence`：Vision worker `_prepare_target` 把 `conversation_type` 传入 PR 会话身份硬守卫；文字路径中已确认 private/group 漂移。
- `actual`：同一图片消息可能在 exact key/title 相同的情况下，仅因类型校正而捕获失败。
- `expected_invariant`：图片路径与文字路径使用同一物理身份规则；类型是可校正语义属性，不能单独否定 exact key/title。
- `local_containment`：Vision host adapter 使用统一会话 resolution；仍对 key/title/候选歧义 fail-closed。
- `upstream_request`：上游会话确认 API 区分 physical identity 和 semantic type。
- `verification`：侧栏 private→群 header、未知→private、单聊/群聊同名歧义、图片方向双测。
- `status`：`REPRODUCED`。
- `关闭条件`：文字/图片共用矩阵通过，不能出现跨会话图片绑定。

---

## 6. 会话身份、调度和发送

### SID-001：exact key/title 相同却因类型漂移阻断

- `severity`：P1；`owner`：`pr_author`。
- `first_seen`：`新数据测试` 实机；2026-07-19 复盘状态记录。
- `evidence`：请求与确认 session key 均为 `wx:rpa:v1:178877830fefdaa357d6`，exact title 匹配；请求类型 `group`/此前侧栏 `private` 与最终确认类型不一致，Guard 给出 `conversation_type_not_confirmed` 或 `target_session_type_not_confirmed`；Brain 和 polish 已成功。
- `actual`：消息捕获和回复生成完成，但最终不发。
- `expected_invariant`：已签发且唯一的 exact session key + exact title 是物理身份；从更可靠聊天区结构得到的类型可纠正旧语义，不制造新物理会话。
- `local_containment`：PR 外 resolver 统一类型观测并向 PR 传递一致语义；不得绕过 key/title。
- `upstream_request`：修改 PR 内 `session_matches_key` 和最终守卫的身份/语义分层。
- `verification`：真实 `新数据测试(2)`、普通私聊、同名私聊/群聊、key 或 title 错误负例。
- `status`：`REPRODUCED`。
- `关闭条件`：同一 key/title 的合法类型校正可发送；任何 key/title 不一致仍阻断且无错发。

### SID-002：查找策略和最终守卫语义不一致

- `severity`：P1；`owner`：`shared`。
- `evidence`：会话 lookup 某些阶段允许按 key/title 继续，最终 send guard 又把 type mismatch 作为绝对拒绝。
- `actual`：前半链路认为目标成立并消耗 Brain，最后才失败，造成慢和已读不回。
- `expected_invariant`：capture、schedule、Brain、ready reply、reacquire、send 使用同一身份谓词；语义冲突应尽早解析或明确失败。
- `local_containment`：外围 resolver 在进入 Brain 前产出规范化但不改字段的身份视图；最终再次用同一谓词确认。
- `upstream_request`：抽取单一 PR 内身份判定函数，所有阶段复用。
- `verification`：属性测试覆盖 key/title/type/row/staleness 组合；阶段间 decision trace 必须一致。
- `status`：`REPRODUCED`。
- `关闭条件`：不存在“前面 adopt、最后仅因同一旧冲突 reject”的路径。

### SID-003：session key seed 含易漂移语义

- `severity`：P2；`owner`：`pr_author`。
- `evidence`：PR 生成 session key 的 seed 包含 conversation type 和/或 sidebar row fingerprint；这些值会受 OCR、群头确认、排序和 UI 状态影响。
- `actual`：同一物理会话可能随观测来源变化签发不同 key。
- `expected_invariant`：物理 key 应稳定；可变语义和观测证据应作为附属状态，不参与不可逆身份漂移。
- `local_containment`：本地维护已签发 key 到最新可靠观测的显式绑定；禁止仅靠名称 fuzzy 重建。
- `upstream_request`：设计稳定 key seed 和向后兼容映射，不能直接改名/改格式破坏外部合同。
- `verification`：同一会话重启、排序、未读标记、private→group 校正、多日状态回放。
- `status`：`REPRODUCED`。
- `关闭条件`：保持旧 key 兼容读取，同一物理会话跨合法 UI 变化 key 稳定。

### SID-004：stale key 重新获取后的新旧 key 冲突

- `severity`：P1；`owner`：`pr_author`。
- `evidence`：PR 有 stale-key semantic reacquire，但存在 active target 被刷新为新 key、调用方仍携带旧 requested key 的可能；最终 guard 仍比较二者。
- `actual`：重新获取看似成功，发送阶段仍可能阻断。
- `expected_invariant`：一次合法 rebind 必须返回可审计的旧→新绑定，并在本事务所有阶段一致使用；不能静默替换。
- `local_containment`：外围不把猜测的新 key直接覆盖旧请求；只有唯一 exact title/物理证据且带映射记录才继续。
- `upstream_request`：明确 rebind return contract 和生命周期。
- `verification`：构造 stale old key、唯一新 row、多候选、title 改变、重启恢复。
- `status`：`DISCOVERED`。
- `关闭条件`：稳定复现被消除，映射可审计，歧义 fail-closed。

### SID-005：强制重复定位/点击导致聊天区隐藏或误操作

- `severity`：P1；`owner`：`pr_author`。
- `evidence`：PR `open_chat_for_identity` 对已知类型设置 `force_session_row_resolution=True`；用户实测观察到会话被点击隐藏。
- `actual`：即使目标会话已打开，也可能再次点击侧栏行，触发 UI 状态变化或失焦。
- `expected_invariant`：先无动作验证当前活动会话；只有无法确认或目标不一致时才定位并点击；每次动作后重新观察。
- `local_containment`：外围先做 active-header exact verification，命中则走 no-op；不通过才允许 PR 选择会话。
- `upstream_request`：PR 内把“确认”和“操作”分开，去除 known type 自动强制点击。
- `verification`：同会话连续两条、两会话交替、已打开群聊、窗口失焦、侧栏滚动；记录点击次数。
- `status`：`REPRODUCED`。
- `关闭条件`：已打开正确会话点击次数为 0，切换时最小动作且不隐藏聊天区。

### SID-006：同名多来源记录的歧义和串发风险

- `severity`：P0；`owner`：`local_integration`。
- `evidence`：状态中可能并存 stale group、当前 physical group、配置生成的 synthetic record；显示名相同不能证明同一会话。
- `actual`：若为解决不回复而 fuzzy 合并或降级到名称发送，会产生跨会话风险。
- `expected_invariant`：同名不是身份；只能用已签发 key、exact title 和唯一物理候选解析。多候选必须阻断并告警。
- `local_containment`：明确记录来源和 freshness；synthetic 不能冒充当前物理确认；禁用 name-only send fallback。
- `verification`：同名私聊/群聊、同名两个群、stale+active+synthetic 三候选、负例错 key/title。
- `status`：`LOCAL_GUARD_REQUIRED`。
- `关闭条件`：所有歧义负例都 fail-closed；合法唯一候选正常发送；零串发。

### SID-007：缺少 private→group 的端到端回归

- `severity`：P1；`owner`：`shared`。
- `evidence`：现有测试有局部 identity 断言，但未覆盖侧栏初判 private、打开后结构判 group、Brain 生成并最终发送的完整链路。
- `actual`：局部测试都绿，实机仍在最后一环不回。
- `expected_invariant`：同一测试必须贯穿 capture→ledger→Brain→ready→reacquire→send，并检查每阶段 key/title 一致。
- `local_containment`：新增不改 PR 文件的集成 fixture；PR 自身测试仍原样保留。
- `upstream_request`：朋友在 PR 测试集中加入同语义回归。
- `verification`：离线 screenshot replay、mock desktop、真实微信三层。
- `status`：`REPRODUCED`。
- `关闭条件`：三层通过，并包含 key/title 负例。

### SID-008：测试样例把真实群标题断言为 private

- `severity`：P2；`owner`：`pr_author`。
- `evidence`：PR 测试包含 `infer_conversation_type("新数据测试") == private`，而实机 header 为 `新数据测试(2)`，代表群聊。
- `actual`：测试锁定了侧栏模糊推断，却未验证打开后的结构校正。
- `expected_invariant`：显示名无群标记时允许 `unknown`/初始推断，但结构证据必须可校正；测试不能把账号特例当通用事实。
- `local_containment`：本地新增通用结构证据优先测试，不删除或修改 PR 原测试。
- `upstream_request`：上游用通用 fixture 表达 provisional inference 与 confirmed type。
- `verification`：无括号群名、带成员数、普通私聊、群/私同名。
- `status`：`REPRODUCED`。
- `关闭条件`：上游测试不再掩盖类型校正路径。

---

## 7. 事件去重、状态和测试基础设施

### OBS-001：同一视觉状态反复生成新事件

- `severity`：P1；`owner`：`shared`。
- `history`：此前出现旧图片/同一消息反复刷为新信号，已经做过 observation event 去重修复。
- `risk`：PR 重写 OCR/Sidecar 行为后，边界哈希、行排序或 speaker metadata 变化可能再次突破去重。
- `expected_invariant`：相同会话、相同消息 occurrence 和相同视觉证据只能消费一次；真正新增消息仍立即触发。
- `verification`：静止窗口长轮询、旧图片停留、新文字追加、切会话再返回、重启基线、OCR 小抖动。
- `status`：`DISCOVERED`，代表 PR 后必须复验，不代表当前已再次失败。
- `关闭条件`：PR 合并后长轮询无重复，新增事件零漏检，历史文档回归通过。

### STATE-001：synthetic/configured 记录污染活动候选

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：历史状态中存在配置/合成会话条目，与实时 OCR/物理观察条目可能同名并存。
- `actual`：如果候选排序未区分证据等级，可能反复选择陈旧或非物理记录。
- `expected_invariant`：configured 只能提供期望/提示，不能充当本次发送的物理确认；实时 exact evidence 优先。
- `verification`：删除/保留 synthetic 的 A/B replay、stale freshness、同名多候选、重启恢复。
- `status`：`DISCOVERED`。
- `关闭条件`：候选来源和优先级可观测，synthetic 永远不能单独通过发送守卫。

### SCHED-001：多会话监听和调度饥饿

- `severity`：P1；`owner`：`shared`。
- `first_seen`：多轮真实微信手测；一个会话能回复，另一个合格会话完全不回，或首条回复后追加消息不再处理。
- `evidence`：问题不总发生在 Brain；部分轮次另一会话没有形成完整 capture→schedule→send 链，且“自问自答单会话通过、人工双会话失败”反复出现。
- `actual`：监听/调度可能围绕当前活动会话、单目标锁、陈旧任务或未释放状态运行，其他有新消息的合格会话被饥饿。
- `expected_invariant`：除显式排除的系统/服务会话外，每个观察到新消息的会话都必须形成独立、可追踪任务；一个会话阻塞、Vision 慢、Brain 慢或发送失败不能阻塞其他会话。
- `local_containment`：保留现有外部队列和 payload；在模块内部做逐会话公平扫描、短临界区、失败释放和任务可观测性，不引入“单目标模式”。
- `upstream_request`：若 PR 的窗口扫描/当前会话策略造成 starvation，提供跨会话观察列表和无副作用确认原语。
- `verification`：两个/三个会话同时首条、交替追加、一会话 Brain 超时、一会话图片慢、一会话发送失败、新会话第一次出现；断言其他任务仍完成且零串发。
- `status`：`REPRODUCED`。
- `关闭条件`：多轮自动回放和真实微信同时满足全覆盖、公平进展、失败隔离和零错发。

### SEND-001：输入框已有文本但未完成发送

- `severity`：P1；`owner`：`shared`。
- `first_seen`：2026-07-19 前的真实微信自问自答测试；截图显示回复停留在输入框，随后微信被踢下线。
- `evidence`：可见草稿“有的，2018款奥迪A4L 40 TF...”已进入输入区域，但没有形成客户可见气泡；说明 Brain/文本写入已经完成，失败窗口位于最终发送动作、窗口状态、掉线或发送确认。
- `actual`：系统可能把“已写入”误当“已发送”，或在点击/按键和可见发送确认之间失去窗口/登录态。
- `expected_invariant`：文本 staged、send action dispatched、outgoing bubble confirmed 是三个独立状态；只有确认本会话出现对应新 outgoing occurrence 才算发送完成。
- `local_containment`：保持现有发送接口和字段；内部补齐幂等发送事务、活动目标再确认、登录态检查、单次安全动作和结果确认。确认不明时停止并告警，不能机械重复发送造成双发。
- `upstream_request`：朋友复核 PR window action planning 的发送动作/确认边界，提供可区分 `staged`、`dispatched`、`confirmed` 的内部证据，不改变外部返回合同。
- `verification`：正常点击、Enter 策略、窗口失焦、微信掉线、按钮不可用、发送后 OCR 延迟、重复确认、双会话切换；断言不丢、不双发、不跨发。
- `status`：`REPRODUCED`。
- `关闭条件`：故障注入和真实微信多轮均有明确终态；未确认发送不会记为成功，也不会盲目重发。

### RPA-BEHAVIOR-001：机械化高频行为与踢下线风险

- `severity`：P1；`owner`：`shared`。
- `first_seen`：自问自答实机测试中微信被踢下线；仓库所有者明确要求保留自问自答能力，通过拟人化通用行为优化解决，而不是禁止测试场景。
- `evidence`：掉线前存在连续点击、复制、切换、输入/发送等自动动作；确切触发阈值和动作组合仍待日志复现，因此根因状态为风险已发现而非已证明单一动作。
- `actual`：动作节奏、重试、重复定位或并发争抢可能过于机械，触发客户端异常或平台风控。
- `expected_invariant`：任何正常业务消息来源（包括自问自答测试）都走统一、低扰动、可中止的 RPA 行为；不通过禁用某个会话或关键词规避。相同目的动作不重复，动作之间有带上限的自然抖动和全局背压。
- `local_containment`：在代码机制层统一动作预算、互斥 lease、退避、窗口稳定等待、登录态观察和熔断；不得改变 Brain 内容，不用结构化会话特判。
- `upstream_request`：PR 作者复核 window action planning 的重复点击和时序，对高频调用暴露统一的无副作用状态确认。
- `verification`：长时间单会话、多会话交替、自问自答、图片右键、失败重试、窗口切换；统计每分钟点击/按键/切换、重复动作、登录态和踢下线事件。
- `status`：`DISCOVERED`。
- `关闭条件`：先完成因果定位；通用节奏/背压长测通过，且自问自答不被特殊禁用。

### FILTER-001：排除系统会话但覆盖所有普通新会话

- `severity`：P1；`owner`：`local_integration`。
- `first_seen`：历史实机中自动点击“服务号”；修复后仓库所有者进一步明确：除服务号等显式排除对象外，所有新会话只要有新消息都必须回复。
- `actual`：若排除逻辑过宽，会把普通新会话误过滤；若过窄，会反复进入服务号/系统通知并扰乱调度。
- `expected_invariant`：排除判定只依据稳定的系统会话身份/能力证据，不根据普通显示名关键词扩张；未命中排除证据的会话必须进入正常观察和调度。
- `local_containment`：保持现有过滤接口；内部输出可审计的 include/exclude 决策来源，禁止把“当前只监听某目标”当成过滤。
- `verification`：文件传输助手、服务号/订阅号/系统通知、普通私聊、新群聊、名称含相似词的普通联系人、多个新会话同时到达。
- `status`：`DISCOVERED`。
- `关闭条件`：系统会话零误点，所有普通新消息零漏调度；决策有稳定证据且不堆账号词条。

### RPA-TEST-001：缺少 GitHub checks 和独立复跑

- `severity`：P2；`owner`：`shared`。
- `evidence`：审计时 PR 页面没有 checks；229/229 和 28/28 是作者说明。
- `actual`：无法证明结果在当前机器、当前依赖和原样 blob 上可重复。
- `expected_invariant`：先校验七文件 blob，再在本地双端口/离线环境复跑 PR 原生测试并保存报告。
- `verification`：OCR compatibility、screenshot replay、window planning、现有外部合同和 Vision 矩阵。
- `status`：`REPRODUCED`。
- `关闭条件`：本地报告含命令、耗时、通过数、失败项、SHA；有条件时再补 CI。

---

## 8. Brain 角色连续性和减负边界

### BRN-ROLE-001：客户可见回复暴露“另有人工同事”

- `severity`：P1；`owner`：`local_integration`。
- `first_seen`：ES6 价格咨询回复出现“后续由人工同事与您具体沟通”。
- `actual`：回复把当前客服和“人工同事”对立，破坏商家客服角色连续性，间接暴露自动化身份。
- `expected_invariant`：Brain 始终以统一商家客服身份回应；需要升级、核实或后续处理时表达业务动作，不声明自身是 AI，也不建立“我 vs 人工”的角色分裂。
- `修复边界`：通过 Brain 的通用角色目标、语义 reviewer feedback 和一次修复回路处理；禁止堆“人工同事/专员/真人”等短语黑名单作为主要方案。
- `verification`：价格优惠、预约、售后、未知信息、必须升级、闲聊转业务、多轮追问；使用语义判定和人工抽检。
- `status`：`REPRODUCED`。
- `关闭条件`：通用场景不暴露 AI/人工分裂，同时不虚构权限、不承诺未授权事实。

### BRN-PIPE-001：减负后角色连续性检查的覆盖风险

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：近期为降低 Brain 负担已清理多层 reviewer/补丁；需要确认简化链路没有跳过必要的语义角色审查。
- `actual`：问题尚属风险项；不能因一条错误回复就恢复多层结构化引擎。
- `expected_invariant`：主链保持“Brain 理解并生成→Guard/语义审查→必要时反馈 Brain 重做→发送”，Reviewer 不另写答案。
- `verification`：延迟分段统计、每轮 LLM 次数、repair 触发率、角色/事实/安全/多会话用例。
- `status`：`DISCOVERED`。
- `关闭条件`：性能目标和语义正确率同时达标，非 Brain 模块没有客户可见措辞所有权。

---

## 9. 工程过程和文档冲突

### PROC-001：工作区过大且缺少可定位检查点

- `severity`：P1；`owner`：`local_integration`。
- `evidence`：审计时工作区约 111 个状态项、80 个 tracked change，约 7438 insertions/6531 deletions。
- `actual`：无法可靠判断最近若干“修复”具体改变了什么，也不利于 bisect、回滚和 PR 原样校验。
- `expected_invariant`：先封存现状；Vision、PR merge、外围 adapter、测试修复分别形成独立可恢复 checkpoint。
- `local_containment`：不得 reset/覆盖用户改动；先做状态清单、diff 归档和明确分支/提交策略。
- `verification`：每阶段 `git status`、七文件 blob、测试报告和回滚演练。
- `status`：`REPRODUCED`。
- `关闭条件`：阶段 checkpoint 完整，任一失败能回到前一状态且不丢用户工作。

### DOC-001：历史会话身份硬类型规则已与最终方案冲突

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：2026-07-12/13 文档把 conversation type 当硬身份，并把 type mismatch 设计为 fail/re-resolution；实机证明同一 key/title 会从 sidebar private 校正为 header group。
- `actual`：继续照旧文档开发会重复制造已读不回和重复点击。
- `expected_invariant`：exact issued key + exact title 是物理身份；type 是可校正语义；歧义和 key/title mismatch 仍 fail-closed。
- `修复边界`：旧文档顶部加优先级说明，不删除历史复盘；总方案成为新实施依据。
- `verification`：所有新开发文档交叉引用总方案；代码测试表达新规则。
- `status`：`REPRODUCED`。
- `关闭条件`：旧文档已标记，代码和测试无旧规则残留，朋友问题包包含该差异。

### DOC-002：历史 Vision “完全收口”结论过宽

- `severity`：P2；`owner`：`local_integration`。
- `evidence`：旧文档称独立模块改造完成，但严格审计仍发现 Scheduler/Brain/listen_and_reply 具体导入、bridge importlib 和 Vision→Connector 图片方法。
- `actual`：实现代码大部分集中，不等于宿主依赖和 PR 合并接缝已完全独立。
- `expected_invariant`：完成声明必须同时满足源码所有权、运行时唯一入口、中性协议、缺失安全、第三方替换和 PR 合并后复验。
- `修复边界`：旧文档顶部加限定；总方案 V1/V2 退出门禁重新验收。
- `verification`：禁止导入扫描、插件矩阵、mock connector、PR 合并后同套测试。
- `status`：`REPRODUCED`。
- `关闭条件`：旧声明已标记，全部 V1/V2 门禁和合并后矩阵通过。

---

## 10. 合并与测试完成后的逐项复审流程

### 10.1 合并前复审

逐项核对：

1. PR head 是否仍为 `2120f167...`；变化则重新审计全部七文件。
2. Vision 是否已完成 V1/V2，尤其是 `VIS-BOUND-*`、`VIS-RUNTIME-001` 和 `VIS-IDENT-001`。
3. 工作区是否已建立安全 checkpoint，`PROC-001` 是否具备回滚证据。
4. 当前 26 项 Vision 回归是否仍通过。
5. PR 七文件是否没有被本地 Vision 先行改造触碰。
6. 每个 P0/P1 是否有明确本地隔离方案和负例测试。

### 10.2 PR 原样合并后立即复审

1. 用 Git blob/hash 比较七文件是否与 PR head 字节一致。
2. 复跑 PR 原生三组测试，记录耗时和完整通过数。
3. 搜索 PR 旧图片 token，确认计数与审计一致，不误称已经删除。
4. 运行时证明旧图片入口不可达，Vision 是唯一事务 owner。
5. 复跑外部合同、插件矩阵、Brain fixture、会话 identity fixture。
6. 对每条问题更新 `audit_stamp`，不得批量写“已解决”。

### 10.3 外围适配后离线/模拟复审

按以下顺序，失败即停在当前层：

1. 纯函数和合同测试。
2. screenshot replay/OCR 回放。
3. mock Connector/Sidecar 故障注入。
4. 本地双端口云模拟（涉及 cloud gate 时）。
5. 单会话多轮文字。
6. 两会话交替文字，验证零串发。
7. 客户图片、我方图片、商品图片匹配。
8. private/group 漂移和同名歧义负例。
9. Brain 角色连续性和边界回复。
10. 长轮询事件去重、延迟和资源占用。

### 10.4 真实微信手测复审

真实手测至少记录：

- 会话名和物理类型；敏感信息可脱敏，但 key 必须可追踪。
- 用户发出时间、捕获时间、Brain 开始/结束、ready time、RPA 开始/结束、发送确认时间。
- 每条消息的 `session_key`、exact title、requested/observed type。
- 是否发生额外点击、失焦、聊天区隐藏、已读不回、重复捕获或踢下线。
- 图片方向、当前剪贴板事务是否新鲜、Vision 结果是否进入正确历史。
- 最终客户可见文字是否只有 Brain 编写，是否保持统一客服角色。

不能只测一个持续复用的会话。最低场景为：普通私聊、真实群聊、两个会话交替、同一会话连续追问、完全新会话首条、双方图片各一条。

### 10.5 朋友上游修复后的二次核对

对每个 `pr_author/shared` 问题：

1. 朋友回复必须引用 issue ID。
2. 记录修复提交 SHA 和改动文件，不接受只有口头“处理了”。
3. 先对上游独立复现，再合入本地。
4. 重新检查 PR/上游文件是否影响 Vision 外围 adapter。
5. 运行该问题专属测试，再运行全矩阵。
6. 若本地 guard 因上游根修已冗余，先证明移除不改变外部合同，再单独提交清理。
7. 状态依次改为 `UPSTREAM_FIXED`、`MERGED_AND_RETESTED`、`CLOSED`；不得跳级。

---

## 11. 给朋友的上游问题包格式

每个上游问题按以下固定格式导出：

```text
Issue ID:
PR head / commit:
Affected PR file(s):
Severity:
Minimal reproduction:
Observed behavior:
Expected general invariant:
Why local code will not modify the PR file:
Current local containment:
Suggested upstream direction (not mandatory implementation):
Positive tests:
Negative/safety tests:
Compatibility contracts that must not change:
Evidence attachments:
```

必须明确：本地外围 guard 是兼容措施，不代表上游根因不存在；建议只描述通用不变量，不能要求朋友针对“新数据测试”账号或某个标题写特判。

---

## 12. 每轮审计追加模板

后续在本文末尾追加，不覆盖本节以前内容：

```markdown
### Audit Run YYYY-MM-DD HH:mm

- auditor:
- local branch / commit:
- PR head:
- environment:
- test layer:
- commands / scripts:
- elapsed time:
- issues reviewed:
- state transitions:
- new evidence:
- regressions/new issue IDs:
- manual observations:
- rollback/checkpoint:
- decision: continue / stop / rollback / ready for next layer
```

---

## 13. 当前逐项核对结论（开发前）

| 检查问题 | 结论 |
| --- | --- |
| PR 是否包含完整图像理解 Provider | 否；包含旧图片获取/剪贴板兼容残留，不是 Vision 模型能力 |
| 当前 Vision 是否已经绝对独立 | 尚不能宣称；实现所有权基本集中，但具体导入和 Connector 接缝未全部解除 |
| 能否先做完 Vision 再合并 | 能，且是降低风险的正确顺序 |
| PR 七文件能否原样保留 | 能；本地通过 PR 外 adapter 适配，七文件做 blob 门禁 |
| 原样合并是否自动修复不回复 | 不能；类型漂移和硬守卫本身仍在 PR 中，必须外围适配并上报 |
| 是否应删除 PR 图片残留 | 本地不得删除；先标记、隔离为生产不可达，交朋友后续处理 |
| 是否可为恢复回复放宽到按名称发送 | 不可；同名歧义属于 P0，key/title/唯一性仍是硬边界 |
| 是否可以用短语黑名单解决 AI 身份暴露 | 不可作为主要方案；应以 Brain 通用角色连续性和语义反馈修复 |
| 是否能凭自动测试关闭问题 | 不能；图片、双会话、群聊、UI 点击和踢下线必须有真实微信证据 |
| 后续如何与当前发现逐一核对 | 以本台账 issue ID、状态机、专属关闭条件和 audit run 逐项推进 |

开发前结论：当前已发现的问题均已编号并保留。后续合并和测试的目标不是把台账“清空”，而是让每个问题都有可证明的状态：本地根修、上游根修、可靠外围隔离、明确接受的技术债，或带足够证据的不可复现。任何未解释的 P0/P1 都阻止交付。
