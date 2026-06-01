# RPA实盘全场景验收清单（2026-05-31）

## 目标
- 对当前 RPA 优先微信自动客服/AI记录员链路做一次完整实盘验收。
- 覆盖账号切换、锚点回滚、多会话并发、键鼠守护、异常恢复、记录员导出、状态稳定性与性能预算。
- 仅当全部场景通过，才进入“可验收”。

## 执行策略
- 主策略：先低风险基线，再进入实盘发送，再做受控异常演练，最后做稳定性与性能复盘。
- 风控策略：所有发送均走低频节奏与已有守护，不做高压刷屏，不做越权目标发送。
- 产物策略：每一项都必须生成 `runtime/apps/wechat_ai_customer_service/test_artifacts/...` 证据。

## 测试清单（必须全部通过）

| ID | 场景 | 方式 | 执行命令/脚本 | 通过标准 | 产物 |
|---|---|---|---|---|---|
| L0 | 基线健康检查 | 实盘前置 | `WeChatConnector.status/capabilities` + `8765/8766 health` | 微信在线、`adapter=win32_ocr`、服务健康 | 本轮总报告 preflight |
| L1 | 账号切换一致性（chejin→test02→chejin） | 实盘 | `runtime/two_session_customer_service_live_acceptance.py`（chejin）→`tests/run_smart_recorder_live_wechat.py --tenant test02`→`runtime/file_transfer_scheduler_continuous_live.py --tenant-id chejin` | 三段均通过，且能力/目标/模块与账号匹配，切回后客服链路正常 | 三段 artifact + 汇总 |
| L2 | 记录员CSV导出 UTC+8 日期+时分秒 | 实盘+导出 | `run_smart_recorder_live_wechat.py --tenant test02` 后触发 `RecorderExportRunService.process_run` | 导出成功，CSV含日期列与时分秒列（UTC+8）且非空 | export run artifact + CSV审计 |
| L3 | 锚点回滚最小化（可见锚点不回滚） | 实盘 | `runtime/file_transfer_scheduler_continuous_live.py`（连续对话）并审计 `history_backfill` | 出现可见锚点时 `reason=visible_anchor_found_no_scroll`，无多余上翻 | 审计日志切片 + 汇总 |
| L4 | 多会话并发调度（两会话/三会话） | 实盘 | `runtime/two_session_customer_service_live_acceptance.py` + `runtime/live_three_session_pressure.py` | 不漏不重、FIFO发送、慢会话不阻塞其余会话 | 两份 pressure artifact |
| L5 | F8键鼠守护与悬浮球状态联动（客服+记录员） | 实盘 | 在 L1/L2 运行中抓取 runtime status 与 operator_guard state | 两模块运行时均能观测 guard active；暂停/恢复状态一致 | status快照与日志 |
| L6 | 异常演练（窗口异常恢复/失焦保护） | 实盘受控演练 | `runtime/rpa_customer_window_abnormal_live.py` | 异常后可恢复，发送不误投，未导致链路失控 | abnormal artifact |
| L7 | 抢焦点安全（输入中断不误打） | 实盘受控演练 | 复用 L6 + send guard 日志审计 | 焦点异常时应中止/重试到微信，不向其他窗口写入 | send_guard/audit 证据 |
| L8 | 长跑状态稳定性（state 不失控增长） | 实盘长轮次 | 复用 L4 + 运行后检查 state 关键数组长度与文件体积 | 关键 state 数组裁剪生效，体积可控 | state审计结果 |
| L9 | 性能预算（30s/60s目标） | 实盘复盘 | 统计 L1/L4 对话轮次耗时（p50/p90） | 短消息尽量逼近30s，长消息控制在60s级；给出量化取舍报告 | latency 汇总 |

## 验收门槛
- 必须：L0-L9 全部 `PASS`。
- 若任一项 `FAIL`：立即进入“修复→回归→重测”闭环，不可跳项验收。
- 若触发掉线/风控：立即停止发送链路，保留日志并转人工告警，再决定是否继续。

## 结果记录规范
- 每个场景记录：
  - 命令
  - 开始/结束时间
  - PASS/FAIL
  - 关键证据路径
  - 失败时的修复动作与复测结果
- 最终输出：
  - 一份总报告（本轮通过矩阵）
  - 一份问题清单（若有）
  - 一份后续优化建议（仅基于证据）

