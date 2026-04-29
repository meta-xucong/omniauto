# WeChat Customer Service Probe

This directory contains the first feasibility probes for building a guarded
WeChat customer service workflow on top of OmniAuto.

## Accepted Baseline

As of 2026-04-25, the accepted baseline is:

```text
OmniAuto main process -> Python 3.12 wxauto4 sidecar -> Windows WeChat 4.1.x
```

The baseline intentionally does not use screenshot/OCR/window-capture for normal
WeChat operation. WeChat 4.1.x can mark the main window with
`WDA_EXCLUDEFROMCAPTURE`, so screenshot-based observation is unreliable.

Use this runner for future work:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py sessions
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py messages --target "文件传输助手"
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py send --target "文件传输助手" --text "hello world"
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py smoke
```

Use this minimal guarded customer-service loop for workflow development:

```powershell
# Safe default: read messages and plan a reply, but do not send.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py

# Test mode for File Transfer Assistant only: treat self messages as incoming.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py --allow-self-for-test

# Send mode for File Transfer Assistant tests. This sends only when a rule matches.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py --allow-self-for-test --send
```

Use the config-driven guarded workflow for the next development stage:

```powershell
# Read-only preflight before touching a test contact.
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py --target "许聪"

# First run for a newly whitelisted target: mark existing messages as processed.
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --bootstrap

# Safe default: poll configured whitelist and plan replies only.
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once

# Temporary runtime targets are allowed only for bootstrap/dry-run checks.
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --bootstrap --target "许聪"
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --target "许聪"

# Real send mode. Keep this limited to File Transfer Assistant or test contacts.
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --send

# Capture structured customer data, write Excel, then send a confirmation.
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --once --write-data --send
```

Runtime `--target` is intentionally blocked in `--send` mode unless that target
is already enabled in the config. Add real send targets to the config whitelist,
then bootstrap and dry-run before sending.

Use the dedicated test-contact config when validating a real contact:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --once --bootstrap
uv run python workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --once
```

Use the approved outbound sender for one-off whitelisted test sends or future
scheduled outreach:

```powershell
# Dry-run by default.
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。"

# Real send only after preflight, bootstrap, dry-run, clean review queue, and rate-limit checks.
uv run python workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py --config workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json --target "许聪" --text "[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。" --send
```

Real-contact listener test result:

- The workflow received inbound messages from `许聪`, sent replies, and verified
  them by reading the chat back.
- A labeled customer-data message was written to
  `runtime/test_artifacts/wechat_customer_service/test_contact_customer_leads.xlsx`.
- Frequency limits blocked rapid follow-ups first, then retried successfully
  after the interval elapsed.
- Rule selection now prefers higher-priority and stronger keyword matches, so
  quote intent wins over a simple greeting.

Use the structured intent assistant as an advisory layer:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少"
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --emit-llm-prompt
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --candidate-file workflows/temporary/desktop/wechat_customer_service/llm_intent_candidate.example.json
uv run python workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py --text "冰箱的价格是多少" --call-deepseek
```

The assistant is side-effect free. It returns structured JSON such as intent,
confidence, suggested reply, recommended action, and whether the suggestion is
safe to auto-send. In the test-contact config it is enabled as
`advisory_only`, so the guarded workflow records the advice in audit events but
does not let it operate WeChat or override the rule reply.

The current LLM provider path is intentionally manual: `--emit-llm-prompt`
produces the prompt pack and JSON schema, while `--candidate-file` validates a
candidate response and compares it with the heuristic result. This is the safe
bridge before wiring in a real model provider.

DeepSeek is also supported in advisory-only mode. It reads `DEEPSEEK_API_KEY`
from the environment and validates model output against the same schema. It
must remain advisory-only until enough audit samples prove it is safer than the
rules for a specific intent.

The guarded workflow uses a state lock beside the state file:

```text
runtime/state/wechat_customer_service/guarded_workflow_state.json.lock
```

Do not run multiple state-writing workflow commands in parallel. The lock is a
guardrail for accidental overlap from scheduled jobs or manual runs.

Use the manual review queue before expanding to real contacts:

```powershell
# Read current unresolved review items.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py

# Include completed pending customer-data records for traceability.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py --include-resolved

# Export the queue for human review.
uv run python workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py --export-json runtime/test_artifacts/wechat_customer_service/review_queue.json --export-excel runtime/test_artifacts/wechat_customer_service/review_queue.xlsx
```

The loop persists processed message ids under:

```text
runtime/state/wechat_customer_service/minimal_loop_state.json
```

The guarded workflow persists state and audit logs under:

```text
runtime/state/wechat_customer_service/guarded_workflow_state.json
runtime/logs/wechat_customer_service/audit.jsonl
```

The example customer-data workbook is:

```text
runtime/test_artifacts/wechat_customer_service/customer_leads.xlsx
```

The optional review exports are:

```text
runtime/test_artifacts/wechat_customer_service/review_queue.json
runtime/test_artifacts/wechat_customer_service/review_queue.xlsx
```

By default, the runner only connects to an already logged-in WeChat main
window. It does not start WeChat automatically, because starting
`Weixin.exe` can legitimately show the login confirmation page. Use explicit
startup only when that behavior is acceptable:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py status --start-if-missing
```

The sidecar environment is:

```text
runtime/tool_envs/wxauto4-py312
```

The engineering lessons and next implementation roadmap are recorded in:

```text
docs/WECHAT_CUSTOMER_SERVICE_DEBUG_LESSONS_AND_ROADMAP.md
```

Keep the older probes below for diagnostics only. They are no longer the primary
implementation path.

The probes are intentionally conservative:

- Window and capture probes are read-only.
- The send probe defaults to `clipboard-only` and will not send a message unless
  `--mode send` is passed explicitly.
- All probes write artifacts under
  `runtime/test_artifacts/wechat_customer_service/`.

## Prerequisites

1. Log in to the official Windows WeChat client.
2. Keep the Windows session unlocked.
3. Prefer a controlled test conversation such as File Transfer Assistant or an
   internal test account.
4. Avoid using these probes on real customer conversations until the workflow
   has explicit safety gates.

## Probe 1: Window Discovery

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_window.py
```

This probe:

- Finds candidate WeChat windows by title.
- Activates the best candidate.
- Dumps a shallow UIA control summary.
- Saves a window screenshot.

Useful options:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_window.py --title-pattern "微信|WeChat"
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_window.py --max-controls 300
```

## Probe 2: Text Capture

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_capture.py
```

This probe:

- Captures a WeChat window screenshot.
- Runs OCR over the screenshot by default.
- Dumps visible UIA text candidates.

Clipboard capture is disabled by default because it sends hotkeys to the active
window. Enable it only when you are in a controlled conversation:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_capture.py --copy-selected
```

## Probe 3: Controlled Send

Default mode only puts text on the clipboard and focuses WeChat:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_send.py --text "OmniAuto probe message"
```

To paste into the currently focused WeChat input box without pressing Enter:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_send.py --mode paste --text "OmniAuto probe message"
```

To paste and send, first manually focus a safe test conversation input box, then
run:

```powershell
uv run python workflows/temporary/desktop/wechat_customer_service/probe_wechat_send.py --mode send --text "OmniAuto probe message"
```

## Expected Next Step

After these probes produce artifacts, inspect:

```text
runtime/test_artifacts/wechat_customer_service/
```

Then decide which capture path is reliable on this machine:

1. UI Automation via `pywinauto`.
2. Clipboard capture.
3. OCR over screenshot regions.
4. Manual handoff.

## First Local Probe Result

Initial probe on this machine:

- `pywinauto` found and focused one WeChat window.
- The WeChat top-level window class was `Qt51514QWindowIcon`.
- UIA descendants were empty in the first window probe, so WeChat did not expose
  a useful control tree in that run.
- OCR over the captured WeChat window returned text candidates, so OCR is a
  viable fallback path for message reading.
- A later guarded open probe found two official `Weixin.exe` candidates:
  - one large window whose screenshot surface was actually Codex, so it was
    blocked as the wrong surface;
  - one `mmui::LoginWindow` surface showing login / transfer-only controls, so
    it was blocked as not being the logged-in chat main window.

Implication:

```text
pywinauto: window discovery and focusing
OCR: message/text observation fallback
clipboard + HardInput: text placement and sending
OmniAuto workflow: state, validation, retries, and artifacts
```

Before any real send test, Windows WeChat must be logged in and the visible
candidate window must pass screenshot surface validation as the chat main
window.

## Customer-Service Guardrails

The guarded workflow now separates customer messages into four outcomes:

- direct auto reply when a rule or product/FAQ knowledge item is sufficient;
- ask for missing fields when customer data is incomplete;
- rate-limit cooldown notice when one customer exceeds 20 replies per 10 minutes
  or 100 replies per hour;
- operator handoff when the knowledge base cannot answer safely or the customer
  requests an exception such as off-policy discounts.

Operator handoff events are written to:

```text
runtime/logs/wechat_customer_service/operator_alerts.jsonl
runtime/logs/wechat_customer_service/test_contact_operator_alerts.jsonl
```

These JSONL files are the current implementation hook for later SMS, WeChat, or
desktop notifications.
