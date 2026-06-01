# RPA 多会话调度防白屏测试计划（2026-06-01）

## 1. 测试目标

验证以下能力在改造后成立：

1. 多会话前台切换行为显著降噪。
2. capture 失败后进入退避，不再高频重试。
3. 调度顺序稳定，不出现输入会话错位。
4. 不破坏既有业务回复链路与回归能力。

## 2. 测试分层

## 2.1 静态检查

1. `python -m py_compile` 覆盖本轮改动文件。
2. 触达前端文件时执行 `node --check`（本轮预计无需）。

## 2.2 模拟/离线测试

1. `python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
2. `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
3. `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
4. `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py`

新增断言覆盖：

1. 事件驱动会话选择与切换节流生效。
2. 会话粘性策略生效。
3. capture 失败冷却生效与恢复生效。

## 2.3 实盘短测（低扰动）

前提：

1. 微信已登录且主窗口可见。
2. 不做高压刷屏，不做复制粘贴批量灌入。

步骤：

1. 开启三会话监听（文件传输助手/许聪/新数据测试）。
2. 在其中一个会话发送新消息，观察切换次数与顺序。
3. 观察另一个会话是否被机械频繁探测。
4. 若出现 target confirm 失败，确认是否进入退避再重试。

判定：

1. 无连续机械跳转。
2. 无输入会话错位。
3. 无白屏放大（即出现异常后不会持续重复激进操作）。

## 3. 日志与证据

需要保存：

1. `customer_service_managed_listener.log` 关键事件窗口。
2. `customer_service_scheduler_state.json` 中 failure/cooldown 字段变化。
3. `wechat_win32_ocr_ui_actions.jsonl` 的切换动作频率片段。

## 4. 验收门槛

1. 静态检查通过。
2. 聚焦回归全部通过。
3. 实盘短测满足“低机械切换 + 失败退避 + 顺序稳定”。
4. 无新增 P0/P1 风险。
