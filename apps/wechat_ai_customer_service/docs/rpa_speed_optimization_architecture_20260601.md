# 微信自动客服 RPA 响应加速方案（2026-06-01）

## 1. 背景与目标
- 目标优先级：
1. 不降低回复质量与业务正确性。
2. 在此基础上显著缩短平均响应时间。
- 现状基线（`runtime/apps/wechat_ai_customer_service/test_artifacts/speed_optimization_20260601/baseline_metrics.json`）：
1. `capture p50=10s`
2. `llm p50=29s, p90=86s`
3. `send_stage p50=61s, p90=71s`
4. `end_to_end p50=96s, p90=125s`

结论：当前主要瓶颈在 `send_stage`，其次是 `llm` 长尾。

## 2. 根因分析
### 2.1 发送前 freshness 检查过重
- 调度器在每次发送前都会调用 `detect_newer_messages_before_send()`，该逻辑默认执行 `get_messages`（RPA 打开会话并 OCR 读取）。
- 随后 `send_text_and_verify()` 又可能再次读取消息做发送验证，形成重复重操作。

### 2.2 多段发送每段都“完整验证”
- 长消息拆段后，每段都走 `send_text_and_verify`，每段都触发一次重验证。
- 在多会话下切换成本被叠加，造成 `send_stage` 明显放大。

### 2.3 拆段策略偏保守，导致段数偏多
- 当前默认阈值更容易拆成 3 段，发送次数与窗口操作次数增加。

## 3. 方案总览
### 3.1 Freshness 采用“预览优先 + 严检兜底”
- 新增 `scheduler_freshness` 配置：
1. `mode=preview_first`：优先使用 `SessionMonitor` 未读信号做轻量 freshness 判定。
2. `strict_check_interval_seconds`：周期性强制严检（RPA 全量读取）作为兜底，防漏判。
3. `strict_check_after_llm_seconds`：LLM 运行过久时强制严检，保证稳健性。
- 判定策略：
1. 若 `SessionMonitor` 显示目标会话未读/pending，直接判 stale（不发送旧回复）。
2. 若预览无未读且未触发严检条件，直接放行，跳过一次重 OCR freshness。
3. 达到严检触发条件再执行现有 `detect_newer_messages_before_send()`。

### 3.2 多段发送改为“中间段轻确认，末段强确认”
- 新增多段发送策略参数 `verify_each_segment`（默认 `false`）：
1. 中间段：调用 `send_text`（保留发送护栏与目标确认，不做消息回读验证）。
2. 最后一段：调用 `send_text_and_verify`（保留最终强验证）。
- 这样不牺牲最终可验证性，同时减少重复重验证次数。

### 3.3 拆段阈值调优（减少无必要分段）
- 默认策略改为更偏向 2 段：
1. `min_split_chars` 上调。
2. `preferred_segment_chars` 上调。
3. 新增 `three_segment_threshold_chars`，仅在非常长文本才拆 3 段。
- 保证“长文本仍可分段拟人”，但降低多会话切换与发送开销。

### 3.4 观测增强
- 对 freshness 结果补充 `freshness_mode` 与 `preview_snapshot` 字段，便于区分是快速放行还是严格校验。
- 多段发送结果补充 `verification_strategy`，便于后续统计与回归审计。

## 4. 兼容与风险控制
### 4.1 兼容性
- 所有新策略默认“保守开启 + 严检兜底可回退”。
- 发送最终段仍强验证，不改变现有“发送必须可确认”的原则。

### 4.2 风险与防护
- 风险：预览信号偶发漏检。
- 防护：
1. 周期性严检（`strict_check_interval_seconds`）。
2. 长 LLM 时强制严检（`strict_check_after_llm_seconds`）。
3. 检测到 pending/unread 时直接 stale，不发送旧回复。

## 5. 预期收益
- 预期显著降低 `send_stage` 的重复读取开销，尤其在多段消息和多会话场景下。
- 目标区间（以当前环境估算）：
1. `send_stage p50` 下降 25%~45%
2. `end_to_end p50` 下降 20%~35%
- 质量目标：回复正确性、风格、边界合规不低于现网版本。

## 6. 回滚策略
- 回滚开关：
1. `scheduler_freshness.mode` 切回 strict-only（或关闭 preview fast path）。
2. `reply_multi_bubble.verify_each_segment=true` 恢复旧行为。
3. `reply_multi_bubble.three_segment_threshold_chars` 下调恢复旧拆段密度。
- 出现异常时按模块级别逐项回滚，不做大范围回退。
