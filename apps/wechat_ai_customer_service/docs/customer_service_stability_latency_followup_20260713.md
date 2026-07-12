# 微信客服稳定性与延迟持续优化（2026-07-13）

本轮优化遵守 [customer_visible_reply_ownership_baseline.md](./customer_visible_reply_ownership_baseline.md)：客户可见回复继续只由 `customer_service_brain` 生成；质量门、意图辅助、修复器和代码机制层不得编写本地兜底话术。

## 实测证据

- 双会话连续模拟第 1 轮均成功，第 2 轮中 `许聪` 的原始 BrainPlan 完整且权威校验通过。
- 原始 Brain 用时约 12.6 秒，随后质量门识别到过度确定的销售表达并要求修复。
- 修复调用耗时约 18.4 秒，最终经备用 `deepseek-v4-flash` 返回合法 JSON，但 `reply_segments` 为空，导致 `customer_service_brain_no_visible_reply`。
- 正常轮次在 Brain 前还同步执行了一次通用意图 LLM advisory。该调用不拥有回复权，且与 Brain 的理解工作重复，使 planner 总耗时从约 15 秒扩大到约 29 至 63 秒。

## 内部优化

1. Brain First 模式继续生成启发式 intent assist 和证据摘要，但跳过同步通用意图 LLM advisory。图片和疑似商品证据缺口仍由现有 Brain preflight 按需调用，不改视觉模块、语音模块或普通 RPA。
2. 当质量修复返回可解析但没有任何 `reply_segments` 的 BrainPlan 时，在同一捕获内执行一次 Brain 修复重试。重试仍由 Brain 生成完整 BrainPlan，不采用规则话术、本地改写或旧回复兜底。
3. 修复审计保留 `failover`、重试原因和上一版状态，区分主模型失败、备用模型采用和无效修复结果。
4. 商品类 Brain prompt 预先说明“可以明确主推，但不能替客户定车、下单、留车或锁车”的通用边界，减少原始回复因高压销售表达进入二次 LLM 修复。

## 兼容边界

- 不改现有公开函数签名、导入路径、配置字段、状态字段、动作名和出口变量。
- 不改发送前目标确认、会话键绑定、新鲜度检查、多气泡发送和防自动化节奏。
- 不改变语音与识图插件的独立、可选、延迟加载结构。
- 非 Brain First 模式保持原 intent assist LLM 行为。

## 验收

- 契约、Brain First、工作流、多会话和插件矩阵测试通过。
- 复现用例不再产生空修复后静默。
- 多轮模拟无漏回、无串回，planner 中不再出现重复意图 LLM 阻塞。
- 多轮微信双会话实盘保持目标和 session key 一致，并量化 capture、Brain、polish、send 与端到端耗时。
