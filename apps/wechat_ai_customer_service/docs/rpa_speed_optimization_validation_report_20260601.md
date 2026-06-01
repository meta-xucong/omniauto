# 微信自动客服 RPA 响应加速验证报告（2026-06-01）

## 1. 范围
- 基于 `rpa_speed_optimization_architecture_20260601.md` 与实施清单落地。
- 覆盖全量离线、模拟并发、实盘链路。

## 2. 关键补丁（本轮新增）
- 发送焦点守卫恢复：`recover_send_window_guard(...)`。
- 前台焦点异常兼容：
  - `WECHAT_WIN32_OCR_ALLOW_UNKNOWN_FOREGROUND=1`（前台句柄为0时走“降级允许+OCR输入区确认”）。
  - `WECHAT_WIN32_OCR_FOCUS_CLICK_FALLBACK`（焦点锁死时启用标题栏轻点击抢焦点）。
- `send_rpa_env()` 同步注入上述发送侧环境变量。

## 3. 全量离线结果
- `run_workflow_logic_checks.py`：`72/72 PASS`
- `run_customer_service_multi_session_scheduler_checks.py`：`35/35 PASS`
- `run_wechat_win32_ocr_compat_checks.py`：`78/78 PASS`
- `run_realtime_reply_optimization_checks.py`：`PASS`
- `run_jiangsu_chejin_used_car_checks.py`：`PASS`
- `run_vps_local_two_port_shared_sync_checks.py`：`PASS`
- `run_runtime_start_cloud_guard_checks.py`：`PASS`
- `run_knowledge_compiler_checks.py`：`PASS`

## 4. 模拟并发结果
- `runtime/live_three_session_synthetic_pressure.py --run-id speedopt_syn_20260601_fix3 --rounds 1 --force-live-pressure --min-interval-seconds 0`
- 结果：`sent=3, failed=0, stale=0`，通过。
- 产物：`runtime/apps/wechat_ai_customer_service/test_artifacts/three_session_synthetic_pressure/speedopt_syn_20260601_fix3/result.json`

## 5. 实盘结果
- 文件传输助手连续实盘：
  - `runtime/file_transfer_scheduler_continuous_live.py --tenant-id chejin --scenario used_car --use-llm --max-turns 6 --preflight-cooldown-seconds 35 --preflight-cooldown-jitter-seconds 6`
  - 结果：`turn_count=3`，`3/3 PASS`
  - 产物：`runtime/apps/wechat_ai_customer_service/test_artifacts/file_transfer_scheduler_continuous_live/20260601_202545/result.json`
- 三会话实盘压力：
  - `runtime/live_three_session_pressure.py --rounds 1 --run-id speedopt_20260601_sim_fix_final`
  - 结果：`sent=3, failed=0, stale=0`，通过。
  - 产物：`runtime/apps/wechat_ai_customer_service/test_artifacts/three_session_pressure/speedopt_20260601_sim_fix_final/result.json`

## 6. 性能对比（本轮）
- 基线文件：`runtime/apps/wechat_ai_customer_service/test_artifacts/speed_optimization_20260601/baseline_metrics.json`
- 本轮对比：`runtime/apps/wechat_ai_customer_service/test_artifacts/speed_optimization_20260601/after_metrics_20260601.json`
- 核心结果：
  - baseline capture->send `p50=96.0s`
  - after live turn `p50=74.99s`
  - `p50` 改善约 `21.89%`

## 7. 验收结论
- 本轮“文档 -> 落地 -> 全量测试 -> 模拟测试 -> 实盘测试”已闭环完成。
- 未出现新增错会话发送、漏回/重复回、白屏或掉线回归。
- 在质量不降前提下，响应速度达到可量化改善。

