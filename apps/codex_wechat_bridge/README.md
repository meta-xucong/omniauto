# Codex WeChat Bridge

This app is an independent bridge for sending WeChat task messages into Codex
threads that remain visible/resumable in Codex Desktop.

It intentionally does not use the WeChat AI customer-service knowledge base,
RAG layer, reply rules, admin console, or customer-data capture. The bridge only:

- Reads task text from a configured WeChat chat, usually File Transfer Assistant.
- Creates or resumes a Codex `app-server` thread.
- Sends the task text to Codex.
- Captures the final Codex response.
- Optionally sends the response back to WeChat when `--send` is passed.
- Maintains a local task ledger so WeChat and the monitor page stay in sync
  even when Codex Desktop has not refreshed its session index yet.

WeChat must already be open, logged in, and showing a real main window. The
bridge deliberately refuses to start WeChat or operate on the login window.

## Dry Direct Prompt

This creates or resumes the active Desktop-visible Codex thread without touching
WeChat:

```powershell
.\.venv\Scripts\python.exe apps\codex_wechat_bridge\workflows\bridge_loop.py --config apps\codex_wechat_bridge\configs\default.example.json --prompt "Reply with one line: bridge smoke"
```

## WeChat One-Shot Poll

Only WeChat messages that start with the configured command prefix are treated
as Codex bridge input. The default input prefix is `[ToCodex]`; bridge replies
still use `[Codex]`, so outbound replies do not trigger new tasks.

Supported WeChat commands:

```text
[ToCodex] <task>
[ToCodex] /new <task>
[ToCodex] /list [limit]
[ToCodex] /use <thread_id>
[ToCodex] /status
[ToCodex] /stop
[ToCodex] /help
```

`[ToCodex] <task>` continues the active bridge thread. `/new` creates a fresh
Desktop-visible Codex thread before running the task. `/list` returns recent
Desktop-visible threads, `/use` switches the active thread for later tasks, and
`/stop` asks a running `--loop` process to exit after it sends the stop
acknowledgement. `/status` returns the active thread, latest `run_id`, latest
task status, and monitor URL.

Before the first live run, mark the messages already visible in the chat as
processed. This prevents the bridge from treating old File Transfer Assistant
messages as new Codex tasks:

```powershell
.\.venv\Scripts\python.exe apps\codex_wechat_bridge\workflows\bridge_loop.py --config apps\codex_wechat_bridge\configs\default.example.json --bootstrap
```

This reads configured WeChat messages and prints the planned reply without
sending it back:

```powershell
.\.venv\Scripts\python.exe apps\codex_wechat_bridge\workflows\bridge_loop.py --config apps\codex_wechat_bridge\configs\default.example.json --once
```

Send the Codex result back to WeChat only when you are ready:

```powershell
.\.venv\Scripts\python.exe apps\codex_wechat_bridge\workflows\bridge_loop.py --config apps\codex_wechat_bridge\configs\default.example.json --once --send
```

For continuous polling:

```powershell
.\apps\codex_wechat_bridge\scripts\run-bridge.ps1 -Loop -Send -IntervalSeconds 5
```

## Daily Start / Stop

For normal use, prefer the productized scripts under `scripts/`.

Start the bridge, rotate old live logs, bootstrap currently visible WeChat
messages, start the monitor, and start the polling loop:

```powershell
.\apps\codex_wechat_bridge\scripts\start-bridge.ps1
```

The start script also clears any stale `/stop` marker left by an earlier manual
or scripted shutdown before it launches the loop. This prevents a fresh start
from exiting after one poll because of an old stop request.

Stop both the polling loop and monitor:

```powershell
.\apps\codex_wechat_bridge\scripts\stop-bridge.ps1
```

Check whether the bridge is running:

```powershell
.\apps\codex_wechat_bridge\scripts\status-bridge.ps1
```

The status output can be `running`, `stopped`, `monitor_only`, or `loop_only`.
Only `running` means both the polling loop and monitor are alive.

For double-click style launching, the matching `.cmd` wrappers call the same
PowerShell scripts with `ExecutionPolicy Bypass`:

```text
apps\codex_wechat_bridge\scripts\start-bridge.cmd
apps\codex_wechat_bridge\scripts\stop-bridge.cmd
apps\codex_wechat_bridge\scripts\status-bridge.cmd
```

The start script writes fresh logs to:

```text
runtime/apps/codex_wechat_bridge/live_logs/
```

Before each start, existing `*.log` files in that directory are moved under:

```text
runtime/apps/codex_wechat_bridge/live_logs/archive/<timestamp>/
```

The latest process metadata is written to:

```text
runtime/apps/codex_wechat_bridge/state/processes.json
```

On Windows, the start and stop scripts also try to show a small tray balloon
notification. If Windows blocks that notification, the scripts still print JSON
status output and write `processes.json`.

## Task Ledger And Monitor

When a WeChat task is accepted, the bridge creates a `run_id` in
`runtime/apps/codex_wechat_bridge/state/task_ledger.json` and advances it
through statuses such as `queued`, `running`, `codex_completed`, `done`, and
`send_failed`.

With `--send` and `wechat.send_receipts=true`, the bridge sends an immediate
receipt to WeChat before Codex starts doing the work:

```text
[Codex] 已识别到问题：...
正在思考中。
run_id: cw_...
thread_id: ...
```

Start the local monitor page:

```powershell
.\apps\codex_wechat_bridge\scripts\run-bridge.ps1 -Monitor
```

Then open:

```text
http://127.0.0.1:17911
```

The monitor reads the bridge state and task ledger directly. It is the realtime
source of truth; Codex Desktop remains a convenient viewer that may refresh its
local session index later.

## Notes

- The Codex thread is created through `codex app-server`, not by editing local
  SQLite files.
- The example config runs Codex with `danger-full-access` because this bridge is
  meant to execute real tasks from explicit `[ToCodex]` commands. Change the
  `codex.sandbox` field back to `read-only` for smoke tests.
- The created thread should appear as `source=vscode` to Codex app-server
  listing, which is the path proven to be Desktop-compatible in the probe.
- Runtime state and artifacts live under `runtime/apps/codex_wechat_bridge/`.
