# RPA 多会话调度防白屏开发清单（2026-06-01）

## 1. 目标范围

只改调度与 RPA 控制层，不改业务回复逻辑。

## 2. 代码改造清单

### A. `admin_backend/services/session_monitor.py`

1. 增加事件驱动调度输出方法（可调度目标选择）。
2. 引入粘性会话策略：
   - 同一会话在短窗口内优先持续处理。
3. 让跨会话切换最小间隔真正生效。
4. 引入 preview/time 变化确认计数，降低 OCR 抖动误报。
5. 保留 `pending_targets()` 作为 UI/兼容读接口。

### B. `admin_backend/services/customer_service_scheduler_state.py`

1. 会话状态字段新增：
   - `risk_state.capture_fail_count`
   - `risk_state.capture_retry_not_before`
   - `risk_state.last_capture_failed_at`
2. `record_session_signal()` 增加冷却期阻断（冷却未到期不重复入队）。
3. `record_capture_result()` 成功时重置 failure/cooldown。

### C. `admin_backend/services/customer_service_scheduler.py`

1. `_collect_session_signals()` 改为使用会话监控的“可调度目标选择”。
2. `mark_session_capture_failed()` 增加退避冷却写入。
3. `_ensure_session_monitor()` 接入 `dispatch_strategy/sticky/preview_confirmation` 参数。
4. 保持 LLM 并发与 RPA 串行模型不变。

### D. `customer_service_live_safety.py`

1. 在 `low_risk_single_target_scan=true` 下收敛默认多会话参数：
   - 更保守的切换频率
   - 更小扫描批次
   - 默认事件驱动策略
2. 保留显式配置覆盖能力。

### E. 配置样例与运行时默认

1. `configs/default.example.json`
2. `configs/jiangsu_chejin_xucong_live.example.json`

补充新参数说明，确保新部署可见。

## 3. 测试改造清单

### A. `tests/run_customer_service_multi_session_scheduler_checks.py`

新增用例：

1. 切换节流是否在事件驱动路径生效。
2. 粘性会话优先是否生效。
3. capture 失败退避是否生效（冷却期间不再被捕获）。
4. 冷却到期后是否可恢复。

### B. 既有回归

必须复跑：

1. `run_customer_service_multi_session_scheduler_checks.py`
2. `run_wechat_win32_ocr_compat_checks.py`
3. `run_workflow_logic_checks.py`
4. `run_realtime_reply_optimization_checks.py`

## 4. 实盘验证清单

1. 三会话同时监听，仅随机对一个会话发消息：
   - 观察是否仍机械来回切换。
2. 人工制造一个“目标不可确认”会话：
   - 观察是否进入退避而非每轮重试。
3. 恢复后继续发消息：
   - 验证会话可恢复处理。
4. 检查运行日志：
   - `managed_listener_scheduler_tick`
   - `scheduler_capture_failed`
   - `capture_retry_after`

## 5. 回滚预案

1. 将 `multi_target.dispatch_strategy=legacy_pending_scan`。
2. 将 `capture_failure_base_cooldown_seconds` 调小。
3. 保留 `concurrency_scheduler.enabled` 控制开关应急回退。

## 6. 交付物

1. 架构文档（本轮）
2. 开发清单（本文件）
3. 测试计划（独立文件）
4. 代码与测试结果
