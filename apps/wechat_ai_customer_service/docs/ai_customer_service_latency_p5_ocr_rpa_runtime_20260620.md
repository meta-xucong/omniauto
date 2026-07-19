# P5 OCR/RPA Runtime Latency Plan

> 状态修订（2026-07-19）：本文保留为历史性能证据；其中“固定保持 `clipboard_chunks`”已被 [customer_service_wechat_account_behavior_risk_retrospective_20260719.md](customer_service_wechat_account_behavior_risk_retrospective_20260719.md) 取代。当前 live safety 必须保留既有 input-method 枚举中的显式选择，不能无条件扩张为分块剪贴板动作。

当前开发服从：

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

## 背景

P0-P4 已完成当前一轮速度优化闭环。最新 P4.2 实盘短问候双会话验证通过，关键数据如下：

- `send_payload`: 当前约 8.3s - 8.5s，早期 P2 约 12.6s。
- `target_ready`: 当前约 3.5s - 3.7s，早期 P2 约 6.8s。
- `open_chat_main_list`: 已通过一次性 OCR seed 复用降到约 0.0001s - 0.0002s。
- `typing/input confirmation`: 当前仍约 4.7s - 5.1s。
- `pre_send_strict_ocr` / `activation_validation_ocr`: 单次仍约 0.8s - 1.1s。

P4 结论是：继续直接缩短等待不合适。剩余耗时主要来自 OCR 本身、输入确认和发送前强校验，而不是可随便砍掉的 sleep。P5 应进入 OCR/RPA 运行时性能优化阶段。

## 不可越界约束

- 不改框架，不改变量名，不改 CLI 命令、路径、JSON 字段、公共函数名、外部 API 参数名。
- 不把 `add-friend-entry-click-plan` 等协作契约改名。
- 不新增账号、商品、行业、关键词专项硬编码。
- 不绕过 Brain First：客户可见回复仍由 `customer_service_brain` 生成。
- 不关闭或跳过商品库、正式知识、RAG 证据检索、guard、final polish。
- 不为短句速度跳过 final polish 或发送前目标校验。
- 不用缩短 LLM/RPA 上限超时然后超时放弃结果的方式制造速度提升。
- 不跳过最终 `send_payload` 前强目标/会话校验。
- 不增加机械重复点击、固定像素连点、鼠标键盘同时触发等高风险动作。
- 所有优化必须失败可回退：局部 OCR、缓存、视觉确认失败时必须回到旧的全图 OCR/强确认路径。

## P5 目标

P5 的目标不是降低 Brain 思考质量，而是在保持原有业务回复质量和发送安全的前提下，压缩 OCR/RPA 尾部耗时。

预期目标：

- 单条 `send_payload` 从当前约 8.3s - 8.5s 降到约 5.5s - 7.0s。
- `target_ready` 从当前约 3.5s - 3.7s 降到约 2.2s - 2.8s。
- `typing/input confirmation` 从当前约 4.7s - 5.1s 降到约 3.0s - 4.0s。
- 长业务对话不牺牲 Brain 检索、推理、审稿和 final polish，只减少 RPA/OCR 尾部时间。

## 阶段设计

### P5.0 端到端基线与 OCR 调用审计

目的：先确认不同场景下 OCR/RPA 慢点是否一致，避免误修。

采样场景：

- 当前已在目标会话，只需发送回复。
- 从一个会话切到另一个会话后发送。
- 短问候，例如“你好”“在吗”。
- 短业务，例如“多少钱”“能看车吗”。
- 长业务，例如预算、用途、比较、推荐、政策或承接上下文的复杂问题。

需要记录：

- 每次 OCR 的调用用途：标题确认、主列表扫描、点击后确认、输入框确认、发送前强校验、发送后检查。
- 每次 OCR 的截图尺寸、ROI 尺寸、耗时、结果数量。
- Brain、final polish、scheduler、RPA send 的端到端耗时。
- 是否命中 P3/P4 缓存或 seed。

实现原则：

- 优先使用现有 timing 字段。
- 只补缺失的内部观测字段。
- 不改变行为逻辑。

验收：

- 静态测试通过。
- 至少一轮 dry-run 和一轮低量实盘能输出可读的 OCR 调用分布。
- 能明确指出下一步最值得局部 OCR 的位置。

### P5.1 标题区域 ROI OCR

目的：把 `validate_active_send_target` 中用于确认当前聊天对象的 OCR 从全图优先改为标题区域 ROI 优先。

思路：

- 内部新增 ROI OCR helper，对截图裁剪指定区域后 OCR，再把 OCR 坐标映射回原图坐标。
- 优先在标题区域跑 ROI OCR，用于 active title 严格确认。
- ROI OCR 失败、结果不足、检测到异常表面或不确定时，回退全图 OCR。
- 保留登录页、白屏、辅助窗口、阻塞页、安全页检测；不能因为 ROI OCR 只看标题而漏掉硬阻塞。

安全边界：

- ROI OCR 只能加速确认，不能降低确认标准。
- 不能让弱匹配升级成强匹配。
- 不能跳过 `send_payload` 前强校验。
- 不能把 body、speaker label、群成员名误当标题。

验收：

- 标题确认相关兼容测试覆盖浅色/深色、981x860、不同标题长度、群聊 speaker label 干扰。
- ROI 失败时回退全图。
- 实盘 `pre_send_strict_ocr` 和 `activation_validation_ocr` 平均下降。
- 双会话实盘 target/session 仍匹配，无误发、掉线、红感叹号。

### P5.2 输入框 ROI OCR 与输入确认优化

目的：减少输入确认阶段的全图 OCR 成本，同时保留“确认内容已进入输入框再发送”的安全闭环。

思路：

- 输入后优先对输入框区域做 ROI OCR 或视觉确认。
- 短文本仍必须确认，但确认范围可以局部化。
- `fast visual confirm` 可以重新基于真实截图校准，但必须保留失败回退。
- 保持 `clipboard_chunks`、`typo=0`、`enter_only`、单一发送触发。

禁止：

- 不能不确认就发送。
- 不能同时按 Enter 和点击发送按钮。
- 不能通过减少确认次数到 0 来提速。
- 不能对短句绕过 final polish。

验收：

- 输入框 ROI 失败时回退旧全图/旧 OCR 确认。
- 输入确认测试覆盖空输入框、已有草稿、长句、多行、OCR 噪声。
- 实盘 `typing/input confirmation` 平均下降。
- 发送内容 verified，未出现空发、错发、残留草稿发送。

### P5.3 同阶段 OCR 结果复用

目的：避免同一阶段、同一截图、同一窗口几何下重复 OCR。

候选复用范围：

- 同一 `send_payload` 内，刚用于标题确认的截图/OCR 可供同阶段后续只读判断复用。
- 同一输入确认阶段，同一输入框截图的 OCR 结果可重复读。
- 同 hwnd、同 target、同 exact、同 geometry、极短 TTL 下，允许一次性复用。

安全条件：

- 缓存必须极短 TTL。
- 缓存必须绑定 hwnd、geometry、target、exact、必要时绑定 session_key。
- 只能复用到只读判断，不能复用到点击后页面已变化的确认。
- 缓存不满足条件必须无感回退旧路径。

验收：

- 目标不同、窗口变化、session_key 不同、缓存过期、异常表面全部不命中。
- 实盘 timing 能看到 OCR 调用次数下降。
- 没有降低最终发送前强目标确认。

### P5.4 发送后轻量检查评估

目的：评估发送后检查是否能更多依赖轻量窗口可读性/状态检查，而不是默认全图 OCR。

边界：

- 发送前强校验必须保留。
- 发送后检查不能替代发送前校验。
- 若出现白屏、登录、安全验证、渲染异常，必须硬停。
- 只允许在发送前已强确认、发送触发已成功、窗口仍可读的情况下走轻量检查。

验收：

- 白屏/登录/安全页仍被拦截。
- 红感叹号或发送失败迹象不能被忽略。
- 实盘无发送失败痕迹。

### P5.5 端到端验收与质量复核

目的：确认 P5 没有为了速度牺牲回复质量和安全。

必须覆盖：

- 短问候双会话实盘。
- 短业务双会话 dry-run 和至少一轮实盘。
- 长业务 dry-run：预算、推荐、比较、政策、承接上下文。
- 文件传输助手低风险实盘。
- Brain contract、workflow、scheduler、Win32/OCR compat、动作风险、人性化输入。

质量检查：

- 长业务仍由 Brain 生成客户可见回复。
- 商品事实仍来自 product master。
- 政策流程仍来自 formal knowledge。
- RAG/经验池仍只能辅助表达，不能授权事实。
- final polish 仍只做验证和轻量自然化，不改事实和策略。
- 复杂问题不能被短问候快速路径截走。

## 推荐推进顺序

1. P5.0 先补 OCR 调用用途和 ROI/全图耗时统计。
2. 基于 P5.0 数据，只选择最高收益的第一个 ROI 点。
3. P5.1 做标题区域 ROI OCR，失败回退全图。
4. 跑静态、compat、risk、dry-run、低量实盘。
5. P5.2 做输入框 ROI OCR/视觉确认优化。
6. 再跑同样测试和实盘。
7. P5.3 只在数据证明重复 OCR 仍明显时做同阶段复用。
8. P5.4 作为最后的发送后轻量检查评估，不提前动。
9. P5.5 全量验收，通过后再考虑提交和 merge。

## 交付标准

- 不改外部契约，不改变量名，不改公共函数名。
- 不降低 Brain First 回复质量。
- 不绕过证据检索、guard、final polish 和发送前强校验。
- 每个阶段都能用 timing 证明实际省在哪。
- 每个阶段都有失败回退测试。
- 实盘无白屏、掉线、安全验证、红感叹号、目标不确认、机械重复点击迹象。
- 若 P5 任意阶段实盘出现异常，立即停止下一阶段，先复盘高危行为和回退路径。

## 2026-06-20 实施记录

### P5.0 OCR 调用审计

- 已为 Win32/OCR sidecar 增加内部 OCR trace，记录 `purpose`、`region`、截图尺寸、耗时和识别数量。
- `send_payload`、`send_with_guarded_clicks`、`paste_text_with_confirmation`、`validate_active_send_target` 均能在 timing 中看到 OCR 分布。
- 该变更只增加可观测字段，不改变 CLI/API/JSON 既有字段语义。

### P5.1 标题区域 ROI OCR

- 已实现标题/右侧区域 ROI OCR 实验路径，失败可回退全图。
- 经过实盘验证后保持默认关闭：当前 OCR 引擎调用固定成本较高，标题 ROI 对总耗时收益不稳定，并且曾暴露 prevalidation seed 误用风险。
- 已修复 seed 隔离：只有 full/full_fallback OCR 可进入 open_chat main-list seed，ROI-only 不再作为主列表 OCR seed。

### P5.2 输入框 ROI OCR

- 输入前草稿检查和输入后 token 确认均改为输入框 ROI 优先。
- 输入后 ROI 未识别到 token 时，仍自动回退旧全图 OCR + 视觉确认路径。
- 兼容测试覆盖 ROI 命中与全图回退。

### P5.3 输入区 precheck seed 复用

- `validate_active_send_target` 强校验成功后，生成一次性输入区只读 seed。
- `send_payload` 只在同 hwnd、同 target、同 exact、同 geometry、短 TTL 内消费该 seed。
- `paste_text_with_confirmation` 仅第 1 次尝试复用 seed 判断输入框是否为空；重试仍回到截图 + ROI OCR。
- 发送前强目标校验、输入后 token 确认、Enter-only 发送触发均未减少。

### P5.4 发送后轻量检查评估

- 当前代码已默认使用轻量 post-send guard：发送前强校验之后，发送后优先做 foreground/几何/截图 blank-render 检测。
- 严格 OCR post-send confirm 仍可通过 `WECHAT_WIN32_OCR_POST_SEND_STRICT_CONFIRM` 打开。
- 本轮不再修改 P5.4，避免把最后一道发送后异常检测复杂化。

### 验收数据

- P5.3 双会话短问候实盘通过，operator guard 启动且锁键鼠。
- 实盘 `p5_input_seed_live_20260620`：
  - 新数据测试：`send_payload` 6.05s，`typing` 3.14s，`send` 10.55s，粘贴前 seed 命中，输入确认只剩 1 次 492x122 ROI OCR。
  - 许聪：`send_payload` 6.71s，`typing` 3.42s，`send` 11.78s，粘贴前 seed 命中，输入确认只剩 1 次 492x122 ROI OCR。
- 对比 P5 前后，短句 RPA send 已从早期约 14-16s 稳定降到约 10.5-11.8s；其中 `send_payload` 从约 8-9s 降到约 6-7s。
- 短业务 dry、boundary 长业务 dry、Brain contract、workflow、scheduler、Win32/OCR compat、动作风险、人性化输入、文件传输助手 safety 和文件传输助手 greeting 实盘均通过。
