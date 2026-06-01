# RPA 多会话调度防白屏优化架构（2026-06-01）

## 1. 背景与问题

当前多会话链路在三会话场景下出现如下高风险现象：

1. 前台会话切换频繁，行为机械。
2. 当某个会话出现 `target_not_confirmed_for_messages` 或 `blank_render` 后，仍可能在后续 tick 里快速重复尝试。
3. 调度次序在“多会话轮询 + 失败重试”叠加时容易混乱，出现“看似切错会话/输入错位”的感知。

本轮仅优化 RPA 控制层与调度层，不改变业务回复逻辑、知识层级、话术策略。

## 2. 设计目标

1. 降低机械切换，改为“未读驱动 + 粘性会话”。
2. 让切换节流参数真实生效，而不是停留在未使用逻辑。
3. 会话失败后进入退避冷却，避免连续重试放大白屏/风控风险。
4. 保持“RPA 串行、LLM 并发”的既有安全边界。
5. 保持对多会话并发的支持（不丢消息、不重复回复）。

## 3. 架构改造点

### 3.1 会话选择从“全 pending 喂入”改为“可调度目标选择”

- 当前桥接层会将 `pending_targets()` 的结果直接喂给调度状态。
- 改造后由 `SessionMonitor` 提供“下一批可调度会话”：
  - 未读优先；
  - 粘性会话优先（同一会话连续处理，减少跨会话跳转）；
  - 最小切换间隔约束（跨会话时生效）。

### 3.2 会话失败退避机制

对 capture 失败（尤其 `target_not_confirmed_for_messages` / `blank_render`）引入会话级退避：

- `failure_count` 累加；
- `retry_after`（指数退避，带上限）；
- `select_capture_sessions()` 在冷却期内跳过该会话。

该机制避免“同一失败会话每轮都重试”的行为放大。

### 3.3 低扰动默认参数收敛

在 `live_safety_guard.low_risk_single_target_scan=true` 场景下，默认策略收敛为：

- 单轮 capture 目标更少（默认 1）；
- 扫描批次更小；
- 跨会话最小切换间隔更长；
- 默认启用事件驱动调度策略。

说明：这不会取消多会话支持，只是降低每轮前台动作密度。

### 3.4 未读信号稳态化

未读判定优先使用明确信号（如视觉红点），对仅 preview/time 抖动造成的变化增加确认机制，降低 OCR 抖动导致的误触发。

## 4. 数据与状态字段变更

新增或增强的状态字段（会话级）：

- `risk_state.capture_fail_count`
- `risk_state.capture_retry_not_before`
- `risk_state.last_capture_failed_at`

新增调度参数（`concurrency_scheduler`）：

- 本轮使用内建退避策略（代码内指数退避，上限 90s），暂未新增外露配置项。

新增多会话策略参数（`multi_target`）：

- `dispatch_strategy`（`event_driven` / `legacy_pending_scan`）
- `sticky_target_hold_seconds`
- `preview_change_confirmations`

## 5. 兼容与回滚

### 5.1 向后兼容

- 未配置新字段时使用安全默认值；
- 旧状态文件可无缝加载（缺字段自动补默认）。

### 5.2 快速回滚

如需快速回退：

1. 将 `multi_target.dispatch_strategy` 设为 `legacy_pending_scan`。
2. 将 capture 失败退避参数设为低值或关闭（仅用于应急排障，不建议长期）。

## 6. 验收标准

1. 三会话监听时，前台切换次数显著下降，无连续机械跳转。
2. 出现单会话异常时，不再每轮重复尝试同一失败会话。
3. 白屏/掉线风险不被放大，异常时可被及时阻断并恢复到安全态。
4. 现有核心回归测试通过，且多会话功能仍正常。
