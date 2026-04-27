# 微信客服自动化调试复盘与开发路线

日期：2026-04-25

## 目的

本文记录本轮微信个人版客服自动化调试中已经验证成功的底层方案、踩坑结论、标准入口和后续开发顺序。后续实现微信客服任务时，以本文和 `WECHAT_CUSTOMER_SERVICE_FINAL_BASELINE.md` 为底层依据。

## 已验证的底层方案

最终采用：

```text
OmniAuto 主系统 Python 3.13
  -> subprocess
  -> Python 3.12 wxauto4 sidecar
  -> wxauto4
  -> Windows 微信 4.1.x UIAutomation
```

当前微信版本：

```text
Windows 微信 4.1.8.107
```

主项目 Python 是 3.13，而 `wxauto4` 当前只提供到 Python 3.12 的 Windows wheel，因此不能直接放进主项目环境。正确做法是保留独立 sidecar 环境：

```text
runtime/tool_envs/wxauto4-py312
```

## 已成功验证的能力

已在 `文件传输助手` 上验证：

- 识别已登录主窗口。
- 读取当前登录用户：已登录的本机微信账号。
- 读取会话列表。
- 切换到指定会话。
- 读取指定会话消息。
- 发送文本消息。
- 发送后读回确认。
- 在已登录状态下运行时，不再自动切到登录页。

已成功发送并读回的测试消息包括：

```text
hello world
omniauto stable check 20260425
omniauto stable check 20260425_042502
omniauto login-fix check 20260425
```

## 标准入口

以后正常调试和开发只使用 runner：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py sessions
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py messages --target "文件传输助手"
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py send --target "文件传输助手" --text "hello world"
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py smoke
```

默认行为必须是：只连接已经登录的微信主窗口，不自动启动微信。

只有明确允许进入登录/手机确认流程时，才使用：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status --start-if-missing
```

## 关键调试经验

### 1. 截图/OCR 不是主链路

微信主窗口可能启用 `WDA_EXCLUDEFROMCAPTURE`。本轮验证过的截图路径都不稳定：

- PIL `ImageGrab`
- `mss`
- GDI `BitBlt`
- `PrintWindow`
- OmniAuto 当前截图链路
- OCR over screenshot

常见失败表现：

- 黑屏。
- 空白。
- 透明。
- 捕获到微信背后的 Codex 页面。
- 人眼看到微信，但程序截图看不到真实微信内容。

结论：截图和 OCR 只保留为诊断工具，不进入客服主流程。

### 2. 不直接操控 `WeChatAppEx` 渲染窗口

新版微信存在多个 `WeChatAppEx.exe`、`Chrome_WidgetWin_0`、`Intermediate D3D Window`、`Chrome_RenderWidgetHostHWND` 等窗口。它们可能是渲染层、插件层、辅助层或空白壳。

本轮经验：

- 枚举这些窗口会产生大量误目标。
- 置顶/最大化这些窗口可能造成桌面异常。
- 对这些窗口截图通常仍然是黑屏或空白。

结论：正常流程不要直接操控 `WeChatAppEx`。只通过 `wxauto4`/UIAutomation 操作微信主窗口抽象。

### 3. 不默认启动微信

问题现象：用户明明已经登录，但自动化流程启动时切到了登录页，需要重新手动登录。

原因：

- 旧 sidecar 每次先创建 `LoginWnd()`，可能触发或命中登录窗口。
- 旧 runner 在检测不到微信进程时默认 `Start-Process Weixin.exe`。
- 微信进程退出后重新启动，进入登录/手机确认页是正常行为，不等于已登录主窗口。

修复：

- sidecar 先尝试连接已登录主窗口。
- 只有连接失败时才检查登录页。
- runner 默认只连接已登录主窗口。
- 只有显式传入 `--start-if-missing` 才启动 `Weixin.exe`。

验证结果：

```json
{
  "login_window_exists": false,
  "online": true
}
```

### 4. 中文输入不要走易乱码路径

早期测试中出现过中文变成问号的问题，例如搜索 `文件传输助手` 变成 `????????`。后续应避免让中文命令经过不可靠的控制台编码路径。

当前做法：

- runner/sidecar 使用 `PYTHONUTF8=1`。
- Python 内部保留 Unicode 字符串。
- 必要时用 code point 构造关键中文常量。
- 所有 sidecar 输出统一为 UTF-8 JSON。

### 5. 发送必须带目标对象并读回确认

曾经调用 `SendMsg(..., who=None)` 失败：

```text
未找到聊天窗口：None
```

稳定做法：

- 发送时总是显式传入 `target`。
- 发送后调用 `messages --target ...`。
- 用消息内容或消息 id 做读回验证。

## 当前保留文件

主 runner：

```text
workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py
```

底层 Connector：

```text
workflows/temporary/desktop/wechat_customer_service/wechat_connector.py
```

sidecar：

```text
workflows/temporary/desktop/wechat_customer_service/wxauto4_sidecar.py
```

最小客服循环：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py
```

配置驱动 guarded workflow：

```text
workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py
```

人工复核队列：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py
```

真实联系人预检：

```text
workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py
```

白名单主动发送：

```text
workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py
```

结构化意图建议：

```text
workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py
```

guarded workflow 示例配置：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.example.json
workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json
```

规则话术示例：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_rules.example.json
```

状态文件：

```text
runtime/state/wechat_customer_service/minimal_loop_state.json
runtime/state/wechat_customer_service/guarded_workflow_state.json
```

审计日志：

```text
runtime/logs/wechat_customer_service/audit.jsonl
```

诊断探针：

```text
workflows/temporary/desktop/wechat_customer_service/probe_wechat_observability.py
```

诊断探针只用于问题排查，不作为主链路。

## 立即开发顺序

### 阶段 1：底层 Connector 固化（已完成初版）

目标：把临时 runner 抽象成 OmniAuto 可调用的 `WeChatConnector`。

建议能力：

- `status()`
- `list_sessions()`
- `get_messages(target)`
- `send_text(target, text)`
- `smoke_test(target)`

当前初版已提供：

- `status()`
- `list_sessions()`
- `get_messages(target)`
- `send_text(target, text)`
- `send_text_and_verify(target, text)`

要求：

- 所有返回值是结构化 JSON。
- 所有失败都带错误码和原始错误信息。
- 默认不启动微信。
- 默认不向非白名单对象发送。
- 发送后必须读回确认。

### 阶段 2：消息轮询与去重（已完成最小单轮）

目标：稳定发现“哪些消息是新的、哪些需要回复”。

建议实现：

- 定时读取会话列表。
- 只处理白名单会话。
- 按 `message.id` 去重。
- 维护本地状态文件或 SQLite。
- 区分 `self`、`friend`、`system` 消息。
- 对连续消息做短延迟聚合，避免用户连发三句时回复三次。

当前最小循环已提供：

- 默认只处理 `文件传输助手`。
- 默认 dry-run，不发送。
- 默认跳过 `self` 消息。
- `--allow-self-for-test` 只允许在 `文件传输助手` 中测试。
- `--send` 才真实发送。
- 发送后读回确认。
- 已处理消息 id 持久化。

### 阶段 3：规则话术优先（已完成初版）

目标：先不用 LLM，做确定性客服回复。

建议实现：

- 关键词匹配。
- FAQ 话术库。
- 欢迎语。
- 无法识别时转人工。
- 只在 `文件传输助手` 或测试联系人中验证。

当前初版规则文件：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_rules.example.json
```

已验证：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py --allow-self-for-test --send
```

该命令能选中测试消息、生成规则回复、发送到文件传输助手、读回验证，并记录 processed message id。

### 阶段 4：数据抽取、Excel 写入与复核队列（已完成初版）

目标：收到特定格式数据时，抽取字段并写入固定 Excel。

建议实现：

- 先定义 Excel schema。
- 先做规则抽取。
- 再补 LLM 结构化抽取。
- 每次写入保留来源消息 id、会话名、时间、原文。
- 写入后发确认消息前，先验证 Excel 落盘成功。

当前初版已提供：

- 规则抽取客户资料字段。
- 完整客户资料写入 Excel。
- 写入成功后发送确认并读回验证。
- 不完整客户资料不写入 Excel，发送缺字段追问。
- 把不完整资料写入 `pending_customer_data` 状态。
- 收到后续补充信息时，合并 pending 原文和新消息，再写入 Excel。
- 写入完成后关闭 pending 状态。
- 人工复核队列读取 state/audit，列出待补资料、转人工、拦截和错误事件。
- 复核队列可导出 JSON 和 Excel。

已验证命令：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --write-data --send
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py --include-resolved
```

### 阶段 5：LLM/结构化意图回复决策（已完成建议层初版）

目标：将 LLM 限制在“语义理解和候选回复生成”，不让它直接操作微信。

建议实现：

- 输入：最近 N 条消息、用户画像、话术库、业务状态。
- 输出：结构化 JSON，例如 `reply_text`、`need_handoff`、`fields`。
- workflow 层校验 JSON。
- 发送前做敏感词、长度、频率、白名单校验。

当前初版已提供：

- `customer_intent_assist.py` 无副作用结构化意图建议工具。
- 输出 `intent`、`confidence`、`suggested_reply`、`recommended_action`、`safe_to_auto_send`、`needs_handoff`、`fields`。
- 第一版 provider 是本地 heuristic，不调用外部模型。
- 已接入 guarded workflow 的 `intent_assist` 审计字段。
- 测试联系人配置开启 `advisory_only`，只记录建议，不覆盖规则回复，不操作微信。
- 通用样例配置默认关闭。
- LLM provider 接口底座已完成：`--emit-llm-prompt` 输出 prompt pack 和 JSON schema。
- `--candidate-file` 可校验 LLM 候选 JSON，并与 heuristic 结果对比。
- workflow 支持 `llm_advisory.candidate_json_path`，有候选文件时写入校验结果；没有候选文件时只标记 `prompt_pack_ready`。
- DeepSeek provider 已完成初版：读取 `DEEPSEEK_API_KEY`，调用 `deepseek-chat`，要求 JSON object 输出，随后按本地 schema 校验。
- DeepSeek 只在 `advisory_only` 模式使用，不覆盖规则回复，不自动发微信。

已验证离线样例：

```text
你好，我想问一下价格 -> quote_request
冰箱的价格是多少 -> quote_with_product_detail
测试产品，5个 -> product_detail
姓名：张三 / 电话：13813813888 / 产品：测试产品 -> customer_data_complete
```

已验证 LLM 候选校验：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --candidate-file workflows/temporary/desktop/wechat_customer_service/llm_intent_candidate.example.json
```

结果：候选 JSON 通过 schema 校验，且与 heuristic 的 `quote_with_product_detail` 意图一致。

已验证 DeepSeek 真实调用：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/deepseek_connection_test.py
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --call-deepseek
```

结果：

- 连接测试返回 `pong`。
- `customer_intent_assist.py --call-deepseek` 返回合规 JSON。
- `冰箱的价格是多少` 被识别为 `quote_with_product_detail`。
- 测试联系人 workflow dry-run 已真实调用 DeepSeek，并把 usage 写入 audit。
- 一条重复测试消息已用 `--mark-dry-run` 标记 processed，避免重复消耗 tokens。

### 阶段 6：定时触达（已完成白名单发送底座）

目标：给目标客户发送既定信息。

建议实现：

- 必须有白名单。
- 必须有频控。
- 必须有发送窗口时间。
- 必须记录发送日志。
- 批量发送先走人工审核队列，不直接全自动群发。

当前初版已提供：

- `approved_outbound_send.py` 白名单主动发送工具。
- 默认 dry-run，不发消息。
- 目标必须已经写入配置白名单。
- 复核队列必须干净。
- 复用频控。
- 真实发送必须显式 `--send`。
- 发送后读回验证。
- 写入 state 中的 `outbound_sends` 和 audit log。

已验证：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。"
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。" --send
```

验证结果：消息已发送给 `许聪`，并在 `许聪` 会话中读回确认。

## 推荐的下一步任务

下一步不要继续研究截图，也不要直接上 LLM。可配置 guarded workflow 已完成初版：

```text
读取配置
  -> 加载白名单联系人
  -> 轮询每个白名单会话
  -> 聚合短时间内连续消息
  -> 规则话术回复
  -> 发送前安全校验
  -> 发送并读回确认
  -> 写审计日志
```

当前 guarded workflow 已提供：

- 白名单目标配置。
- 真实联系人预检。
- 单轮或多轮轮询。
- 新增目标 bootstrap，避免回复历史消息。
- 临时 `--target` bootstrap/dry-run。
- 发送模式阻止未写入配置白名单的临时目标。
- 状态文件锁，避免多个 workflow 实例并发写 state。
- 多条连续未处理文本聚合。
- 规则话术回复。
- 简单频控。
- dry-run 默认行为。
- `--send` 显式发送。
- 发送后读回验证。
- 状态持久化。
- JSONL 审计日志。
- 客户资料规则抽取。
- Excel 写入。
- 写入成功后发送确认并读回验证。
- 不完整资料追问、pending 状态保存、补充后合并写入。
- 人工复核队列与 JSON/Excel 导出。
- 测试联系人专用配置。
- 白名单主动发送 dry-run/真实发送。

当前已验证客户资料示例：

```text
姓名：林晓晨
电话：13800138001
地址：上海市浦东新区张江路88号
产品：净水器滤芯
数量：20件
规格：标准款
预算：3000元以内
```

写入位置：

```text
runtime/test_artifacts/wechat_customer_service/customer_leads.xlsx
```

复核导出位置：

```text
runtime/test_artifacts/wechat_customer_service/review_queue.json
runtime/test_artifacts/wechat_customer_service/review_queue.xlsx
```

下一步建议：先把目标从 `文件传输助手` 扩展到一个测试联系人，运行 `--bootstrap` 后只做 dry-run 观察；稳定后再启用 `--send`。确认真实聊天消息的 sender、message.id、连续消息聚合都符合预期后，再接入 LLM 结构化决策和 ERP 表单写入。

当前真实联系人 dry-run 预检结果：

- `许聪` 在最近会话中精确命中。
- 当前登录账号为本机已登录微信账号，未与目标名重名。
- `许聪` 已加入测试联系人专用配置白名单。
- 已串行运行 `--bootstrap --target "许聪"`，标记历史文本 0 条。
- 已串行运行 `--target "许聪"` dry-run，结果为没有待处理新消息。
- 已通过 `approved_outbound_send.py` 向 `许聪` 发送一条白名单测试消息，并读回验证。
- 发送后复核队列为空，guarded dry-run 正确跳过自己的测试消息。
- 已启动短时监听并完成真实 inbound 测试。
- `你好，我想问一下价格`、`冰箱的价格是多少`、客户资料消息均被识别并自动回复。
- 客户资料 `姓名：张三 / 电话：13813813888 / 产品：测试产品` 已写入测试联系人专用 Excel。
- 频控对连续消息生效：短时间内的新消息先 blocked，稍后自动重试并成功发送。
- 复核队列已修正：如果 blocked 消息后来成功 sent/captured/bootstrapped，不再作为待处理审计项展示。
- 规则引擎已修正：按 priority、命中数和关键词长度选择最佳规则，避免 greeting 抢占 quote。
- `test` 规则已移除中文 `测试` 关键词，避免 `测试产品` 误触发测试话术。

### 2026-04-25 限流卡住复盘

现象：真实联系人压测过程中，前面的问价、资料收集、FAQ 回复均正常；最后一条 `商用冰箱，7台 / ？` 迟迟不回复。

结论：不是 WeChat UIA 读取失败，也不是发送动作失败；日志显示该消息已经被正确识别，并由产品知识库生成了可发送话术：

```text
[OmniAuto客服测试] 商用冰箱 BX-200 参考价 999 元/台，7台 预估小计 6993 元。5 台起 950 元/台，10 台起 920 元/台。请再补充联系人姓名、电话和收货城市。
```

真正阻断点是 `max_replies_per_hour`。测试时 1 小时内已经达到 10 条自动回复，后续消息被限流；旧逻辑没有给限流消息做退避，所以同一批 message ids 在每轮继续被处理，并重复调用 DeepSeek advisory。审计日志中共出现 24 次 `max_replies_per_hour` blocked，其中 24 次都调用了 DeepSeek，约消耗 20,985 tokens。

修正：

- 限流结果现在返回 `retry_after_at` 和 `retry_after_seconds`。
- 被限流的同一批消息会写入 `rate_limit_backoff`，退避期内只记录 skipped，不再反复跑规则/LLM/发送。
- DeepSeek advisory 已移动到限流通过之后；限流、fallback blocked、客户资料写入 blocked 时只写入 `intent_assist.skipped`。
- 客户资料 Excel 写入改为在限流通过后执行，避免被限流时反复写入重复行。

后续原则：限流应被视为“队列等待状态”，不是异常；被限流消息不能重复消耗 LLM，也不能重复执行有副作用的写入。

### 2026-04-25 客服逻辑升级

基于真实压测观察，已把客服逻辑从“关键词命中后直接答”升级为“可回答问题、需补充资料、需请示上级、限流等待”四类状态。

变更点：

- 限流改为按单个客户维度：10 分钟最多 20 条、1 小时最多 100 条，默认取消 30 秒最小间隔。
- 超限时会向客户发送一次冷却提示，记录 `retry_after_at`，冷却前不再重复跑规则、DeepSeek 或写 Excel。
- 姓名/联系人识别不再强依赖 `姓名：xxx` 格式，支持 `姓名李四`、`联系人李四 电话...`、`电话... 姓名李四`、以及 pending 状态下单独补一句 `李四`。
- 产品知识库增加结构化 `discount_tiers`，可以明确回答 7 台冰箱按 5 台阶梯价 950 元/台、小计 6650 元。
- 客户要求破例价格、跨档优惠、特批让利时，不自动拍板；客服回复“请示上级”，同时写入 operator alert 队列。
- 未命中知识库/规则的问题不再沉默，也不让大模型编；发送稳妥请示回复，并进入人工接管队列。
- LLM prompt 增加客服人设、边界和上下文：只能基于规则、资料抽取、产品知识、FAQ 回答；缺少依据或涉及授权必须 handoff。

新增/更新的运行产物：

```text
runtime/logs/wechat_customer_service/operator_alerts.jsonl
runtime/logs/wechat_customer_service/test_contact_operator_alerts.jsonl
```

当前仍需后续接入的实操提醒通道：短信、企业微信/个人微信管理员号、桌面弹窗或系统托盘通知。当前版本先以 JSONL 队列落地，保证不漏单。

### 2026-04-25 测试知识库补全

`product_knowledge.example.json` 已扩充为完整测试数据集，覆盖：

- 商品信息：5 个测试商品，含商用冰箱、测试产品、净水器滤芯、办公椅、包装纸箱。
- 商品字段：别名、类目、价格、单位、起订量、库存、发货时效、物流、质保、规格、阶梯价。
- 开票信息：普票/专票、所需字段、开票时效、红冲/重开边界。
- 物流信息：默认仓、承运商、截单时间、偏远地区、大件送货上楼规则。
- 付款信息：对公转账、微信/支付宝、定金尾款、账期/月结转人工。
- 我方公司信息：公司名、品牌名、地址、营业时间、客服电话、税号、测试对公账户。
- 售后信息：签收破损、质量问题、退换货、退款赔偿转人工。
- 人工接管边界：月结/合同/安装/退款/投诉/破例优惠等会写入 operator alert。

已验证样例：

```text
商用冰箱多少钱 -> 产品报价
商用冰箱发货多久 -> 产品物流
商用冰箱能开票吗 -> 开票 FAQ
你们公司叫什么，在哪里 -> 公司信息 FAQ
对公账户发我一下 -> 对公账户 FAQ
净水器滤芯500件多少钱 -> 按 500 件阶梯价核算
办公椅30把有优惠吗 -> 按 30 把阶梯价核算
可以月结吗 -> 转人工提醒
我要退款投诉 -> 转人工提醒
能上门安装吗 -> 转人工提醒
```

### 2026-04-25 真实监听第二轮复盘

监听窗口：14:50-15:06，目标 `许聪`。整体链路正常：自动发送、产品知识库、开票 FAQ、公司信息 FAQ、客户资料写入、人工接管 alert 均生效。

暴露问题与修正：

- `你有哪些商品？把简单的介绍信息列一下` 未命中。已增加 catalog 意图，自动列出测试商品、类目、参考价和规格摘要。
- `买7台能按920元每台算吗？` 省略了产品名，旧逻辑无法继承上一轮 `商用冰箱`。已增加会话上下文 `conversation_context`，保存最近商品、数量、城市、单价、小计。
- `一共多少钱？包含货的价格和运费，给我一个总价` 被物流 FAQ 抢答。已调整意图优先级：`一共/合计/总价/多少钱` 优先按报价处理，并在有城市时合并运费判断。
- `买5台一共多少钱` 省略产品名时旧逻辑只触发通用报价规则。已用上一轮商品上下文补全，可直接核算商用冰箱 5 台小计。

当前离线回归样例：

```text
你有哪些商品？把简单的介绍信息列一下 -> catalog
商用冰箱多少钱？ -> 商品报价
买7台能按920元每台算吗？ -> 继承商用冰箱，上级请示
那先买5台。发江苏南京，包邮吗？ -> 继承商用冰箱，回答产品物流
一共多少钱？包含货的价格和运费，给我一个总价 -> 继承商用冰箱/5台/江苏南京，回复 4750 元且预计包邮
买5台一共多少钱 -> 继承商用冰箱/江苏南京，回复 4750 元且预计包邮
```

残留观察：15:06:24 出现一次 `打开微信失败，请指定微信路径`，下一轮又恢复为 skipped，判断为 wxauto4 sidecar 偶发打开/绑定失败，当前 workflow 会记录 error 但不中断。后续可增加短延迟重试以减少 audit 噪音。
