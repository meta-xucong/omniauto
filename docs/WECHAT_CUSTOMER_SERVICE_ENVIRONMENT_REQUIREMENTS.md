# WeChat Customer Service RPA Environment and Component Requirements

## 1. Purpose

This file records the environment and component gaps for building a WeChat
customer service automation system on top of OmniAuto.

It separates components into three groups:

1. Components that should be added to OmniAuto platform core soon.
2. Components that should remain in workflow/task layer until proven stable.
3. Business configuration that should not be mixed into the RPA platform.

## 2. Current OmniAuto Capabilities

OmniAuto already has several useful foundations:

- Workflow and `AtomicStep` state-machine execution.
- `VisualEngine` based on `pyauto-desktop` for screenshot, image location,
  coordinate clicking, typing, hotkeys, and visual fallback.
- `HardInputEngine` based on Interception for physical-like keyboard and mouse
  events.
- Clipboard-based text input in hard-input paths.
- `openpyxl` dependency for direct Excel writing.
- `apscheduler` dependency for scheduled jobs.
- Runtime artifact directories for screenshots, logs, and debugging evidence.
- Recovery and manual-handoff primitives.

Relevant existing files:

```text
platform/src/omniauto/engines/visual.py
platform/src/omniauto/hard_input/engine.py
platform/src/omniauto/core/state_machine.py
platform/src/omniauto/recovery/
pyproject.toml
```

## 3. Key Missing Components

### 3.1 pywinauto dependency

Status: missing.

Purpose:

- Access Windows UI Automation / Win32 control trees.
- Find and focus desktop windows.
- Inspect visible controls.
- Try reading control text without OCR.
- Click or type into exposed controls.

Why it matters:

Current OmniAuto desktop automation is strong at visual and physical-like input,
but it does not have a semantic Windows control layer. `pywinauto` can improve
window targeting and reduce reliance on fragile coordinates where UIA data is
available.

Recommended action:

- Add `pywinauto` as a dependency after a focused feasibility probe.
- Wrap it behind an OmniAuto adapter rather than calling it directly from every
  workflow.

### 3.2 Generic DesktopWindowAdapter

Status: missing.

Recommended placement: platform core.

Suggested path:

```text
platform/src/omniauto/desktop/window_adapter.py
```

Responsibilities:

```text
find_window(title_regex=None, process_name=None)
activate_window(window)
get_window_rect(window)
list_controls(window)
find_control(window, name=None, control_type=None, automation_id=None)
read_control_text(control)
click_control(control)
type_to_control(control, text)
```

Reason to add to core:

This is not WeChat-specific. It will help with WeChat, WPS, ERP desktop apps,
and other Windows software.

### 3.3 TextCaptureEngine

Status: missing.

Recommended placement: platform core interface, with task-specific strategies.

Suggested path:

```text
platform/src/omniauto/desktop/text_capture.py
```

Responsibilities:

```text
capture_by_uia()
capture_by_clipboard_copy()
capture_by_ocr()
capture_best_effort()
```

Reason to add to core:

Many desktop RPA tasks need reliable text capture. WeChat is only one example.

Implementation note:

The first version can expose the interface and implement UIA/clipboard paths.
OCR can be added as a later provider if the local environment has a reliable OCR
engine.

### 3.4 ClipboardManager

Status: partially present inside `HardInputEngine`.

Recommended placement: platform core utility.

Suggested path:

```text
platform/src/omniauto/utils/clipboard.py
```

Responsibilities:

```text
save_current_clipboard()
set_text(text)
paste()
restore_clipboard()
copy_selected_text()
```

Reason to add to core:

Clipboard operations are central to Chinese text input, long-message sending,
and text capture. They should be reusable and carefully restored after use.

### 3.5 MessageStore and TaskQueue

Status: missing.

Recommended placement: platform candidate after workflow proof.

Initial placement:

```text
workflows/temporary/desktop/wechat_customer_service/message_store.py
```

Future platform path:

```text
platform/src/omniauto/messaging/store.py
```

Responsibilities:

- Store conversations.
- Store inbound/outbound messages.
- Deduplicate captured messages.
- Track reply tasks.
- Track scheduled send tasks.
- Preserve source artifacts.

Reason to add eventually:

Message/event queues are useful beyond WeChat, but the schema should be proven
in a real workflow before promotion.

### 3.6 RiskGuard / RateLimiter

Status: missing.

Recommended placement: platform core or platform candidate.

Suggested future path:

```text
platform/src/omniauto/messaging/rate_limit.py
platform/src/omniauto/messaging/risk_guard.py
```

Responsibilities:

```text
per_contact_daily_limit
global_hourly_limit
duplicate_reply_check
quiet_hours
whitelist/blacklist
sensitive_intent_handoff
manual_pause_switch
```

Reason to add soon:

Any messaging automation needs safety gates. For WeChat personal accounts, the
risk guard is not optional.

### 3.7 WeChatDesktopAdapter

Status: missing.

Recommended placement: workflow layer first.

Initial path:

```text
workflows/temporary/desktop/wechat_customer_service/wechat_adapter.py
```

Do not add directly to platform core yet.

Reason:

WeChat UI is version-sensitive and can change. The adapter should be validated
against the target client version, display scale, login state, and conversation
types before being promoted.

### 3.8 OCR provider

Status: missing or not formalized.

Recommended placement: optional platform provider after evaluation.

Purpose:

- Capture message text from self-rendered UI areas when UIA and clipboard
  capture fail.

Decision needed:

- Which OCR engine to use locally.
- Whether Chinese OCR accuracy is sufficient.
- Whether screenshots contain sensitive customer data and how artifacts should
  be stored/cleaned.

### 3.9 CustomerServiceDecisionEngine

Status: missing.

Recommended placement: workflow/business layer.

Responsibilities:

- Intent classification.
- Script lookup.
- Persona application.
- Field extraction.
- LLM JSON decision generation.
- Human handoff decision.

Reason not to add to platform core:

The logic is business-specific. The platform should provide execution, storage,
and safety primitives, not a fixed customer service personality.

### 3.10 Excel and ERP sinks

Status: Excel dependency exists; business sink missing.

Recommended placement: workflow/business layer first.

Initial path:

```text
workflows/temporary/desktop/wechat_customer_service/excel_sink.py
```

Responsibilities:

- Validate extracted records.
- Deduplicate records.
- Append rows to Excel with `openpyxl`.
- Link rows back to source messages.

ERP path:

1. Prefer ERP API.
2. Use browser automation if ERP is web-based.
3. Use desktop UI automation only when no API or browser path exists.

## 4. What Should Be Added to OmniAuto Core Soon

These are general-purpose capabilities and worth adding once the first probe
confirms the need:

```text
1. pywinauto dependency.
2. Generic DesktopWindowAdapter.
3. Generic ClipboardManager.
4. TextCaptureEngine interface.
5. RateLimiter / RiskGuard primitives.
```

Potential platform paths:

```text
platform/src/omniauto/desktop/window_adapter.py
platform/src/omniauto/desktop/text_capture.py
platform/src/omniauto/utils/clipboard.py
platform/src/omniauto/messaging/rate_limit.py
platform/src/omniauto/messaging/risk_guard.py
```

Promotion criteria:

- Useful outside WeChat.
- Covered by unit tests.
- Does not encode WeChat-specific UI selectors or text.
- Has clear fallback behavior.
- Does not require risky WeChat internals.

## 5. What Should Stay in Workflow Layer First

These components are too WeChat-specific or business-specific to promote early:

```text
1. WeChatDesktopAdapter.
2. WeChat unread conversation detection.
3. WeChat recent-message capture strategy.
4. WeChat send-success verification.
5. WeChat screenshot templates and region coordinates.
6. Customer service persona.
7. Script library.
8. Excel field mapping.
9. ERP field mapping.
10. Scheduled customer message campaigns.
```

Recommended workflow path:

```text
workflows/temporary/desktop/wechat_customer_service/
```

Promotion criteria:

- Works on at least the target production WeChat version.
- Handles login/security prompts safely.
- Has artifact-backed failure cases.
- Has stable selectors or fallback strategies.
- Has no high-risk protocol or process-injection behavior.

## 6. What Should Remain as Configuration

These should be editable runtime/business configuration files:

```text
runtime/data/wechat_customer_service/persona.yaml
runtime/data/wechat_customer_service/scripts.yaml
runtime/data/wechat_customer_service/rules.yaml
runtime/data/wechat_customer_service/customer_whitelist.csv
runtime/data/wechat_customer_service/customer_blacklist.csv
runtime/data/wechat_customer_service/excel_schema.yaml
```

They should not be hard-coded into platform modules.

## 7. Environment Requirements

### 7.1 Operating system

- Windows desktop environment.
- Same Windows user session where WeChat is logged in.
- Screen must remain unlocked for UI automation.

### 7.2 WeChat client

- Official Windows WeChat client.
- Fixed target version should be recorded during the first probe.
- Avoid unofficial clients, protocol reverse engineering, hooks, and process
  injection.

### 7.3 Python environment

Existing project requirement:

```text
Python >= 3.13
uv-managed environment
```

Likely new dependencies:

```text
pywinauto
pyperclip already available transitively or via current hard-input usage
optional OCR dependency to be selected later
```

### 7.4 Display environment

Record and lock down during pilot:

```text
screen resolution
display scale / DPI
single or multiple monitors
WeChat window size and position
input method behavior
```

### 7.5 Account-risk environment

Operational limits should be configured before any auto-send:

```text
max_auto_replies_per_contact_per_day
max_total_auto_sends_per_hour
quiet_hours
manual_approval_required_for_scheduled_sends
allowed_contacts
blocked_contacts
sensitive_intents
```

## 8. Recommended Development Order

### Step 1: Feasibility probe

Build scripts that answer:

- Can `pywinauto` find and activate the WeChat window?
- Can it inspect useful controls?
- Can recent chat text be captured without OCR?
- Can text be pasted and sent reliably?
- What screenshots/artifacts are needed for failures?

### Step 2: Workflow-layer WeChat MVP

Implement:

- `wechat_adapter.py`
- `message_store.py`
- `risk_guard.py`
- `run_incoming_assistant.py`

Keep auto-send disabled by default.

### Step 3: Platform promotion candidates

After the MVP proves stable, promote only generic pieces:

- DesktopWindowAdapter.
- ClipboardManager.
- TextCaptureEngine interface.
- RateLimiter primitives.

### Step 4: Business expansion

Add:

- Script library.
- LLM decision engine.
- Excel sink.
- Scheduled sender.
- ERP integration.

## 9. Immediate Recommendation

Do not immediately add a full WeChat customer service module into OmniAuto core.

Do immediately prepare the generic lower-level capabilities:

```text
pywinauto probe
DesktopWindowAdapter
ClipboardManager
TextCaptureEngine interface
RiskGuard primitives
```

Then keep WeChat-specific logic in the workflow layer until real-world evidence
shows which parts are stable enough to promote.

