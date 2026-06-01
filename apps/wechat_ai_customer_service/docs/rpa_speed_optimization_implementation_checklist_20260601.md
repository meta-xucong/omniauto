# 微信自动客服 RPA 响应加速实施清单（2026-06-01）

## A. 代码改造清单
### A1. Freshness 快速通道（调度层）
- [x] 文件：`apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- [x] 新增 `scheduler_freshness` 配置读取与默认值处理。
- [x] 在 `_freshness_check` 增加“session preview 快速判定”分支。
- [x] 增加“周期严检 + 长 LLM 严检”兜底逻辑。
- [x] 保留并复用现有 `detect_newer_messages_before_send` 作为严格路径。

### A2. 多段发送验证策略优化（工作流层）
- [x] 文件：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- [x] `reply_multi_bubble_settings` 增加：
  - `verify_each_segment`
  - `three_segment_threshold_chars`
- [x] `send_reply_with_optional_multi_bubble` 改为：
  - 中间段 `send_text`（轻确认）
  - 末段 `send_text_and_verify`（强确认）
- [x] 输出 `verification_strategy` 与段级结果元数据，便于审计。

### A3. 默认拆段参数调优
- [x] 文件：`apps/wechat_ai_customer_service/workflows/listen_and_reply.py`
- [x] 在配置合并阶段调整默认拆段参数，使默认更偏 2 段。
- [x] 保证长文本仍支持 3 段（阈值触发）。

### A4. 配置样例与文档同步
- [x] 文件：`apps/wechat_ai_customer_service/configs/default.example.json`
- [x] 文件：`apps/wechat_ai_customer_service/configs/jiangsu_chejin_xucong_live.example.json`
- [x] 新增/同步 `scheduler_freshness`、`reply_multi_bubble` 新字段注释。

## B. 测试改造清单
### B1. 工作流单测
- [x] 文件：`apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- [x] 新增“多段发送末段强验证”检查。
- [x] 新增“多段发送 verify_each_segment=true 兼容检查”。

### B2. 调度器单测
- [x] 文件：`apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- [x] 新增“freshness preview 快速放行”检查。
- [x] 新增“preview 有未读则 stale”检查。
- [x] 新增“达到严检间隔后回落严格检查”检查。

### B3. 静态检查
- [x] `python -m py_compile` 覆盖改动文件。

## C. 运行验证清单
### C1. 全量离线
- [x] `python apps/wechat_ai_customer_service/tests/run_workflow_logic_checks.py`
- [x] `python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`
- [x] `python apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- [x] `python apps/wechat_ai_customer_service/tests/run_realtime_reply_optimization_checks.py`

### C2. 模拟/半实盘
- [x] 三会话压力脚本跑 1~2 轮，观察发送成功率与错位率。

### C3. 实盘
- [x] 文件传输助手连续问答（短句/长句/连续追问/跨会话切换）。
- [x] 记录响应耗时（p50/p90）与回复质量审计。

## D. 验收标准
- [x] 无新增错会话发送。
- [x] 无新增漏回/重复回。
- [x] 无新增白屏/掉线风险回归。
- [x] 质量审计不回退（答非所问、边界错判、风格僵硬不增加）。
- [x] 性能较基线可量化改善。

