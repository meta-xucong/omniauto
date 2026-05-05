# 文件传输助手实盘长测监督器

`run_file_transfer_live_supervisor.py` 用来把较慢的微信实盘回归变成“一键启动，自动分批跑完”的任务。

它不会让微信发送、LLM 推理和写库验证变快，但会自动处理这些事情：

- 按场景分批运行，避免单个子进程运行太久。
- 每个子进程都有超时限制，超时会杀掉子进程并继续续跑。
- 子测试每跑完一条就落盘，已通过的场景不会重复跑。
- 输出完整汇总，能看到通过、失败、待跑、超时次数。
- 可选临时打开客服全自动测试，结束后恢复原设置。

## 推荐实盘命令

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_file_transfer_live_supervisor.py `
  --send `
  --temporary-full-auto `
  --reset-state `
  --chunk-size 4 `
  --per-run-timeout-seconds 1200 `
  --delay-seconds 0.6 `
  --result-path runtime\apps\wechat_ai_customer_service\test_artifacts\file_transfer_live_full_supervised.json `
  --summary-path runtime\apps\wechat_ai_customer_service\test_artifacts\file_transfer_live_full_supervised_summary.json
```

## 从中断处继续

如果电脑、微信或命令窗口中途断了，直接重新执行同一条命令，但去掉 `--reset-state`：

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_file_transfer_live_supervisor.py `
  --send `
  --temporary-full-auto `
  --chunk-size 4 `
  --per-run-timeout-seconds 1200 `
  --delay-seconds 0.6 `
  --result-path runtime\apps\wechat_ai_customer_service\test_artifacts\file_transfer_live_full_supervised.json `
  --summary-path runtime\apps\wechat_ai_customer_service\test_artifacts\file_transfer_live_full_supervised_summary.json
```

## 只跑一段

```powershell
.\.venv\Scripts\python.exe apps\wechat_ai_customer_service\tests\run_file_transfer_live_supervisor.py `
  --send `
  --temporary-full-auto `
  --start-index 1 `
  --end-index 5
```

## 注意事项

- 真实微信实盘测试不能安全并发，因为聊天上下文、状态文件、RAG 写入和客服回复都依赖顺序。
- `--temporary-full-auto` 只用于测试。它会临时把默认客户空间的客服设置改为全自动，监督器正常结束后会恢复。
- 如果监督器进程本身被系统强杀，可能来不及恢复设置；此时可在客户端“微信智能客服”里手动确认开关状态。
