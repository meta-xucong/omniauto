# 微信客服自动化最终基线方案

日期：2026-04-25

## 结论

后续微信个人版客服自动化以 `wxauto4 sidecar` 为基础，不再以截图、OCR、窗口捕获作为主链路。

最终链路：

```text
OmniAuto 主系统 Python 3.13
  -> subprocess 调用 Python 3.12 sidecar
  -> wxauto4
  -> Windows 微信 4.1.x UIAutomation
```

默认行为：只连接已经登录的微信主窗口，不自动启动微信客户端。

原因：Windows 微信在进程退出后重新启动时，通常会进入登录/手机确认页；这不是“已登录主窗口”，自动启动会打断客服链路。只有显式传入 `--start-if-missing` 时，runner 才会启动 `Weixin.exe`。

## 为什么确定这条路线

已验证当前 Windows 微信版本为 `4.1.8.107`。

截图方案不可靠：

- 微信主窗口曾出现 `WDA_EXCLUDEFROMCAPTURE`。
- `ImageGrab`、`mss`、GDI `BitBlt`、`PrintWindow`、OmniAuto 当前截图链路均无法稳定捕获真实聊天内容。
- 截图中可能出现空白、黑屏、透明，甚至捕获到微信背后的 Codex 页面。

UIAutomation / wxauto4 方案可用：

- 能读取当前登录用户。
- 能读取会话列表。
- 能切到 `文件传输助手`。
- 能读取当前聊天消息。
- 能发送消息并读回验证。

## 当前已验证结果

测试目标：`文件传输助手`

已成功发送并读回：

```text
hello world
omniauto stable check 20260425
omniauto stable check 20260425_042502
```

最新 smoke 测试结果：

```text
send_result.status = 成功
verified = true
```

## 已固化脚本

主 runner：

```text
workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py
```

底层 Connector：

```text
workflows/temporary/desktop/wechat_customer_service/wechat_connector.py
```

Python 3.12 sidecar：

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

规则话术示例：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_rules.example.json
```

guarded workflow 示例配置：

```text
workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.example.json
workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json
```

sidecar 环境：

```text
runtime/tool_envs/wxauto4-py312
```

如需重建：

```powershell
uv venv runtime/tool_envs/wxauto4-py312 --python 3.12
uv pip install --python runtime/tool_envs/wxauto4-py312/Scripts/python.exe wxauto4
```

## 标准命令

检查状态：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status
```

显式允许启动微信：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status --start-if-missing
```

读取会话：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py sessions
```

读取指定聊天消息：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py messages --target "文件传输助手"
```

发送消息：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py send --target "文件传输助手" --text "hello world"
```

最小闭环测试：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py smoke
```

最小客服循环 dry-run：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py
```

文件传输助手测试模式：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py --allow-self-for-test
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py --allow-self-for-test --send
```

配置驱动 workflow：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py --target "许聪"
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --bootstrap
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --bootstrap --target "许聪"
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --target "许聪"
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --send
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --write-data --send
```

临时 `--target` 只用于 bootstrap/dry-run。真实 `--send` 必须先把目标加入配置白名单，防止手滑给未确认联系人发消息。

人工复核队列：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py --include-resolved
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py --export-json runtime/test_artifacts/wechat_customer_service/review_queue.json --export-excel runtime/test_artifacts/wechat_customer_service/review_queue.xlsx
```

白名单主动发送：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。"
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。" --send
```

结构化意图建议：

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少"
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --emit-llm-prompt
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --candidate-file workflows/temporary/desktop/wechat_customer_service/llm_intent_candidate.example.json
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --call-deepseek
```

当前测试 Excel：

```text
runtime/test_artifacts/wechat_customer_service/customer_leads.xlsx
```

已验证字段：

```text
姓名、电话、地址、产品、数量、规格、预算、原文、来源会话、消息 id、写入时间
```

已验证客服数据闭环：

- 完整客户资料：抽取字段、写入 Excel、发送确认、读回验证。
- 不完整客户资料：不写 Excel，发送缺字段追问，记录 pending 状态。
- 后续补充资料：合并 pending 原文和新消息，写入 Excel，关闭 pending 状态。
- 人工复核队列：读取 state/audit，列出待补资料、转人工、拦截和错误事件，并可导出 JSON/Excel。
- 真实联系人 dry-run 前预检：确认登录态、最近会话、目标是否与当前账号重名、复核队列是否干净。
- 状态文件锁：避免定时任务和人工命令重叠写入 state。
- 测试联系人专用配置：`许聪` 独立 state/audit/workbook，不污染文件传输助手样例。
- 白名单主动发送：dry-run 默认，真实发送要求目标在配置白名单、复核队列干净、频控通过、显式 `--send`，发送后读回验证。

已验证真实联系人测试：

- 目标：`许聪`。
- 当前登录账号：本机已登录微信账号。
- 预检通过，最近会话精确命中。
- `--bootstrap` 标记历史文本 0 条。
- guarded dry-run 结果为没有待处理新消息。
- outbound dry-run 通过。
- outbound send 已发送并读回验证：

```text
[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。
```

已验证真实联系人自动客服监听：

- 收到 `许聪` 的问价消息后，自动回复并读回验证。
- 收到 `冰箱的价格是多少` 后，命中 quote 话术并回复。
- 收到客户资料 `姓名/电话/产品` 后，写入
  `runtime/test_artifacts/wechat_customer_service/test_contact_customer_leads.xlsx`，并发送确认。
- 频控工作正常：短时间连续消息会先 `blocked`，到达间隔后自动重试发送。
- 复核队列会过滤已经由后续成功发送解决的 blocked 事件。
- 规则命中已改为 priority/命中数/关键词长度排序，避免普通 greeting 抢占 quote 意图。
- `test` 规则不再包含中文 `测试` 关键词，避免 `测试产品` 这类业务文本误命中测试话术。
- 结构化意图建议层已接入测试联系人配置：默认只写入 `intent_assist` 审计字段，不覆盖实际回复，不操作微信。
- 当前意图建议第一版为本地 heuristic provider；后续可在同一 JSON 接口后接 LLM provider。
- LLM provider 接口底座已完成：可生成 prompt pack 和 JSON schema，可校验 manual candidate JSON，并与 heuristic 结果对比。
- 示例候选文件：`workflows/temporary/desktop/wechat_customer_service/llm_intent_candidate.example.json`。
- DeepSeek provider 已连通：`deepseek-chat` 能返回合规 JSON，校验通过。
- 测试联系人 workflow 已在 advisory-only 模式中真实调用 DeepSeek，并把候选、usage 和校验结果写入 `intent_assist.llm_advisory`。
- DeepSeek key 只从 `DEEPSEEK_API_KEY` 读取，不写入代码、配置、日志或文档。

## 后续开发原则

保留在底层：

- wxauto4 sidecar 调用器。
- 状态检查。
- 只连接已登录主窗口，避免默认启动微信登录页。
- 会话列表读取。
- 聊天消息读取。
- 指定对象发送消息。
- 失败时人工接管。

放在 workflow 层：

- 客服话术库。
- LLM 回复决策。
- 客户信息抽取。
- Excel 写入。
- 定时群发策略。
- 黑名单、频控、人工审核。

不作为主链路：

- 截图识别。
- OCR 读取微信消息。
- 直接操控 `WeChatAppEx` 渲染窗口。
- 反复置顶/最大化/截图验证。

截图和 OCR 只保留为诊断工具，不用于正常客服流程。
