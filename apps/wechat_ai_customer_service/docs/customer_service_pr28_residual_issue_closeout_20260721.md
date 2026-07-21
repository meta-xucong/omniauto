# PR #28 / Vision 残留问题收口索引（2026-07-21）

> **这是当前分支唯一有效的残留问题状态索引。** 旧文档仍保留原始审计证据，但其中的历史 head、历史 blob、阶段结论和“待处理”描述不得单独用于判断当前代码状态；先读本文，再按 issue id 回看旧证据。

## 1. 当前基线

| 项目 | 当前值 |
| --- | --- |
| 当前分支 | `codex/pr28-internal-hardening-20260721` |
| 当前提交 | `d27ce1ece0be6b4b5e4866c732ac6d4d0e2cb07a` |
| 上游主线基线 | `60452fa9130e9ac237f466aba3e2e63992a0d570` |
| 受控 PR/Vision 清理基线 | `b44b37a3ff635ffec08a807f34a7e3067a66675f` |
| 当前草稿 PR | [#30](https://github.com/meta-xucong/omniauto/pull/30) |
| 群聊范围 | 按所有者要求冻结，不进入本轮关闭条件 |
| 同名 P0 | 按所有者“备注已保证唯一”前提暂不处理 |

本轮没有新增模块、字段、变量名、外部参数或调用协议。Sidecar/Connector 的图片残留清理是所有者在 2026-07-21 明确授权的受控变更；原始上游 head 仍在历史文档中保留，不被伪称为当前源码。

本索引必须同时遵守：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

## 2. 已关闭（当前代码已验证）

| issue | 当前结论 | 证据 |
| --- | --- | --- |
| `PR28-IMG-001` | **CLOSED_LOCAL**：Sidecar 不再导出旧图片观察空门面；图片观察只由独立 Vision 捕获模块负责。 | 2026-07-21 旧符号删除记录；绝对 Vision 边界、图片契约通过 |
| `PR28-IMG-002` | **CLOSED_LOCAL**：旧 `image-save`、文件读取、裁切、归档和旧图片资产构造入口已删除；当前唯一入口是右键复制后读取当前剪贴板。 | 2026-07-21 旧符号删除记录；图片契约通过 |
| `PR28-IMG-003` | **CLOSED_LOCAL**：PR 运行时适配器不再导出失效图片事务空门面；当前图片事务仍由 Vision 捕获桥执行，Scheduler 当前桥接方法保持不变。 | Vision worker、scheduler bridge、运行时适配审计通过 |
| `VIS-BOUND-001/002/003` | **LOCAL_VERIFIED**：核心、Brain、Scheduler 只通过既有中性桥/兼容门面使用 Vision。 | 绝对 Vision 边界 7/7；可选插件矩阵 7/7 |
| `VIS-RUNTIME-001` | **CLOSED_LOCAL**：生产调用不再穿回 Connector 图片方法。 | Vision worker 3/3；scheduler current-image bridge 2/2 |
| `VIS-TEST-001` | **CLOSED_LOCAL**：当前门禁同时验证 Vision 单一 owner 和受控 PR blob 基线。 | PR additive audit 4/4；runtime adapter 5/5 |
| `OBS-001` | **LOCAL_VERIFIED**：重复视觉 occurrence、相同短消息和新 occurrence 的模拟去重/重触发已覆盖；尚无真实微信长轮询关闭证据。 | Vision structural recovery 12/12；多会话调度 189/189 |
| `PR28-RPA-001` 的本地兜底 | **LOCAL_GUARD_VERIFIED**：显式配置优先，未配置时由外围注入既有安全默认值。 | RPA acceptance 10/10；不得视为 PR 根因已修复 |
| `PR28-CONTRACT-001` 的旧调用兼容 | **LOCAL_VERIFIED**：旧必填参数和返回形状继续通过快照；新增可选参数的上游合同争议仍登记。 | 外部合同 3/3；不等于上游已批准扩展 |
| `DOC-001/002` | **CLOSED_DOC**：旧身份/旧 Vision“完全收口”结论已在本文和各旧文档顶部标记为历史。 | 本文第 4 节 |

“CLOSED_LOCAL/LOCAL_VERIFIED”表示当前仓库路径有代码和测试证据，不表示第三方外部调用者或真实微信桌面已经完成验收。

## 3. 仍开放的问题

### 3.1 需要真实微信桌面长测

| issue | 当前状态 | 不在本轮强行修复的原因 |
| --- | --- | --- |
| `SID-004` stale key 重新获取后的新旧绑定 | **OPEN_REAL_ENV** | 模拟已覆盖旧 key 保护，但真实 UI 切换、OCR 重新定位和 active key 生命周期仍需日志证明。 |
| `SID-005` 已打开会话的重复定位/点击 | **OPEN_REAL_ENV** | 代码已有 active-header no-op 门禁；需真实截图确认不会隐藏/切错会话。 |
| `SCHED-001` 多会话公平与追加消息 | **OPEN_REAL_ENV** | 189 项调度模拟通过；仍需至少两个真实会话交错发送的长测。 |
| `SEND-001` staged/dispatched/confirmed 发送闭环 | **OPEN_REAL_ENV** | 测试已区分三态；仍需真实微信发送确认、登录态变化和未确认停止证据。 |
| `RPA-BEHAVIOR-001` 机械节奏/踢下线风险 | **OPEN_REAL_ENV** | 已有节奏、背压、互斥和熔断；没有真实账号长测阈值证据。 |
| `FILTER-001` 系统会话排除与普通新会话全覆盖 | **OPEN_REAL_ENV** | 模拟过滤通过；需真实服务号、文件助手、普通联系人同时出现时验证零误点零漏调度。 |

### 3.2 需要朋友 PR 根修或合同确认

| issue | 当前状态 | 责任 |
| --- | --- | --- |
| `SID-001/002/003/007/008` | **UPSTREAM_OPEN**；涉及类型纠正、稳定身份、私聊/群聊结构证据和 PR 自带测试语义。 | PR 作者；群聊部分继续冻结 |
| `PR28-RPA-001` 根因 | **UPSTREAM_OPEN**；本地默认注入只是兼容兜底。 | PR 作者 |
| `PR28-CONTRACT-001` | **UPSTREAM_OPEN**；九个 Sidecar callable 的新增可选参数需要正式合同说明或回滚策略。 | PR 作者/仓库所有者 |

### 3.3 回复质量的遗留审计

`BRN-ROLE-001`/`BRN-PIPE-001` 不属于图片残留。当前 Guard/Polish 和 Brain 契约测试通过，但历史知识、测试种子和旧经验材料中仍能搜索到“转人工/人工客服”等表达。它们是训练/审计素材，不等于客户可见输出；在真实 chejin 会话回放前仍应保留为 **OPEN_REPLAY_AUDIT**，不能用一次模拟绿灯宣称永久关闭。

## 4. 历史文档如何使用

以下文件保留为证据，不删除、不改写原始事实；它们的当前状态以本文为准：

| 历史文件 | 当前地位 |
| --- | --- |
| `customer_service_absolute_independent_vision_module_refactor_plan_20260718.md` | Vision 需求和架构历史 |
| `customer_service_pr28_immutable_merge_independent_vision_master_plan_20260719.md` | 原始“先 Vision、再 PR”方案历史 |
| `customer_service_pr28_post_merge_issue_audit_ledger_20260719.md` | 完整 issue 证据台账；图片条目的旧 `LOCAL_GUARD_VERIFIED` 已被本文升级为 `CLOSED_LOCAL` |
| `customer_service_pr28_upstream_feedback_package_20260719.md` | 发给朋友的上游问题包 |
| `customer_service_pr28_upstream_issue_summary_for_friend_20260720.md` | 旧 PR head 的详细反馈 |
| `customer_service_pr28_upstream_issue_summary_plain_20260720.md` | 旧 PR head 的简明反馈 |
| `customer_service_pr28_frozen_local_session_truth_and_fairness_repair_plan_20260719.md` | 本地会话真值/公平修复历史 |
| `customer_service_pr28_frozen_startup_handoff_and_stale_pending_root_repair_20260719.md` | 启动交接和旧 pending 修复历史 |
| `customer_service_vision_missed_trigger_two_phase_repair_20260719.md` | Vision 漏触发阶段方案历史 |
| `customer_service_pr28_latest_head_byte_preserving_merge_and_nonpr_containment_plan_20260721.md` | 最新合并实施记录；第 11 节已记录本次图片清理授权 |

旧文档中的旧 head（例如 `2120f167`、`8f832dd7`）是当时审计对象，不得拿来覆盖当前 `b44b37a3` 受控清理基线。

## 5. 本轮验收门槛

已通过的离线门禁：

- 外部合同 3/3；Vision 边界 7/7；可选插件矩阵 7/7；图片契约 8/8；
- OCR/RPA 兼容 241/241；Win32 捕获 14/14；PR runtime adapter 5/5；PR additive audit 4/4；
- Vision worker 3/3；scheduler image bridge 2/2；结构触发恢复 12/12；多模态历史 8/8；
- 本地会话真值 13/13；多会话调度 189/189；会话定位 6/6；发送风险 4/4；RPA 验收 10/10。

未通过真实微信桌面长测前，不得把第 3.1 节的 `OPEN_REAL_ENV` 项改为关闭。旧图片兼容门面已按所有者明确授权删除；当前 Vision 桥接和独立插件契约仍须保留并继续回归。

本轮删除的完整范围和授权边界见：[customer_service_retired_image_interface_removal_20260721.md](customer_service_retired_image_interface_removal_20260721.md)。
