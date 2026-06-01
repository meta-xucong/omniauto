# RPA 多会话调度防白屏验证报告（2026-06-01）

## 1. 本轮目标

1. 多会话由机械轮询切换为事件驱动派发，降低白屏/风控风险。
2. capture 失败引入退避冷却，避免同会话重复重试。
3. 保持 RPA 串行 + LLM 并发框架不变。

## 2. 已落地改造

1. `SessionMonitor` 增加事件驱动派发、粘性会话、preview 变化确认计数、白名单过滤。
2. `scheduler` 侧接入 `select_dispatch_targets()`，并在 capture 失败时写入指数退避冷却。
3. `scheduler_state` 增加冷却拦截与成功后的失败状态清理。
4. `live_safety_guard` 参数收敛：
   - 单目标默认关闭 `multi_target`，走稳定单目标路径。
   - 多目标保留 `multi_target`，使用 `event_driven`。

## 3. 静态与离线测试结果

1. `python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py` 通过（28/28）。
2. `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py` 通过（69/69）。
3. `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py` 通过（73/73）。
4. `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py` 通过（全量通过）。

## 4. 实盘测试结果

### 4.1 单会话实盘（通过）

命令：

```powershell
python runtime/file_transfer_scheduler_continuous_live.py --tenant-id chejin --max-turns 1 --delay-between-turns 0 --tick-timeout-seconds 120 --tick-interval-seconds 2 --preflight-cooldown-seconds 0 --preflight-cooldown-jitter-seconds 0 --use-llm
```

结果：

1. `ok=true`。
2. `reply_sent=1`，链路完整（捕获 -> 规划 -> 发送）。
3. 产物示例：`runtime/apps/wechat_ai_customer_service/test_artifacts/file_transfer_scheduler_continuous_live/20260601_122332/result.json`。

### 4.2 两会话并发实盘（部分通过，发现测试侧约束问题）

观测：

1. 两会话并发阶段可同时入队与并发规划（`sessions=2`、`llm_running=2`）。
2. 发送阶段出现 `send_rate_limited`，来自测试配置里的严格发送频控（非本轮调度改造引入）。
3. 证据：`runtime/apps/wechat_ai_customer_service/test_artifacts/two_session_customer_service_live_acceptance/quick_two_session_20260601_124215/quick_result.json`。

结论：

1. 本轮调度改造目标已生效。
2. 两会话长测中断主因是测试脚本的发送频控阈值与多气泡发送冲突，属于后续测试参数/发送策略联调项。

## 5. 后续建议（已进入待办）

1. 对两会话验收脚本增加“自动回复场景频控豁免/延迟协调”选项，避免误报失败。
2. 在多气泡发送时加入同一 `reply_trace` 的频控协调，减少 `send_rate_limited`。
3. 增加两会话专用短链路验收脚本（仅并发核心，不串三段长流程）作为日常回归。

