# OmniAuto WeChat Customer Service RPA Development Spec

## 1. Purpose

This document describes how to build a Windows desktop WeChat customer service
automation system on top of OmniAuto.

The target system should:

1. Detect incoming WeChat conversations and reply with a configured customer
   service persona and script library.
2. Extract structured customer/order data from messages and write it into an
   Excel workbook first, with a later path to ERP form filling or ERP API
   integration.
3. Send scheduled messages to selected customers under strict rate limits and
   safety controls.

The implementation must use OmniAuto as the deterministic execution and
recovery layer. LLMs may assist with semantic classification, field extraction,
and reply generation, but they must not directly control WeChat UI actions.

## 2. Design Principles

### 2.1 Deterministic execution first

WeChat UI operations should be modeled as explicit state-machine steps:

1. Observe current window state.
2. Select the target conversation.
3. Read recent messages.
4. Decide whether to reply.
5. Prepare reply text.
6. Send reply.
7. Verify send result.
8. Persist state and artifacts.

Each UI action must have a validator. If validation fails, retry a bounded
number of times and then hand off to a human operator.

### 2.2 LLMs produce decisions, not UI actions

LLMs should receive normalized text/context and return structured JSON only.

Example:

```json
{
  "action": "reply",
  "intent": "ask_price",
  "reply": "您好，这款目前有现货，我帮您确认一下具体规格和价格。",
  "confidence": 0.86,
  "need_human": false,
  "extracted_data": null,
  "risk_flags": []
}
```

The RPA layer decides whether this output is safe to execute.

### 2.3 Human takeover must be first-class

The system must route uncertain or sensitive conversations to a human. Human
takeover should be triggered by:

- Low LLM confidence.
- Refund, complaint, legal, medical, payment dispute, or abuse-related content.
- Repeated failed UI operations.
- Unknown WeChat popups.
- Login expiration or account security prompts.
- Rate-limit or risk-guard blocks.

### 2.4 Avoid protocol reverse engineering

The system should operate through the official Windows WeChat client UI.
Do not use private protocol reverse engineering, process injection, memory
patching, unofficial clients, or message database tampering.

## 3. Target Architecture

```text
Windows WeChat Client
        |
        v
WeChatDesktopAdapter
  - window focus
  - unread detection
  - conversation navigation
  - message capture
  - message sending
        |
        v
MessageStore / TaskQueue
  - SQLite persistence
  - deduplication
  - message state
  - send task state
        |
        v
CustomerServiceDecisionEngine
  - scripts
  - persona
  - rules
  - LLM JSON decisions
        |
        +--------------------+
        |                    |
        v                    v
StructuredDataSink      ScheduledMessageService
  - Excel now             - scheduled tasks
  - ERP later             - retry/frequency control
        |                    |
        +---------+----------+
                  v
              RiskGuard
                  |
                  v
        OmniAuto Workflow / AtomicStep
                  |
                  v
        VisualEngine / HardInput / pywinauto
```

## 4. Component Responsibilities

### 4.1 WeChatDesktopAdapter

The WeChat adapter is a task-specific desktop adapter. It should not be promoted
to platform core until it has been tested across multiple real WeChat versions
and display configurations.

Required methods:

```text
open_or_focus_wechat()
detect_login_state()
detect_locked_or_security_prompt()
get_unread_conversations()
open_conversation(contact_or_row)
read_recent_messages(limit)
read_current_conversation_name()
send_message(text)
verify_message_sent(expected_text)
capture_failure_artifact(reason)
```

Recommended observation strategy:

```text
1. pywinauto / UI Automation where controls are exposed.
2. Clipboard-based text capture where keyboard selection is reliable.
3. Screenshot region capture plus OCR.
4. Manual handoff when none of the above is reliable.
```

Recommended action strategy:

```text
1. pywinauto for window focus and control-level activation.
2. OmniAuto VisualEngine for visual fallback and image/coordinate targeting.
3. HardInputEngine for high-reliability physical-like mouse/keyboard events.
4. Clipboard paste for Chinese or long reply text.
```

### 4.2 DesktopWindowAdapter

This should be a generic platform-level component, not WeChat-specific.

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

Initial implementation can use `pywinauto` with `backend="uia"` and fallback to
Win32 handles when needed.

### 4.3 TextCaptureEngine

This component normalizes the many ways desktop text can be captured.

Required methods:

```text
capture_by_uia(target)
capture_by_clipboard_copy(target)
capture_by_ocr(region)
capture_best_effort(target_or_region)
```

Each captured message should include:

```text
source: uia | clipboard | ocr | manual
text: captured text
confidence: 0.0 - 1.0
artifact_path: optional screenshot or debug file
```

### 4.4 MessageStore

The system must store normalized messages before making reply decisions.

Minimum SQLite tables:

```sql
CREATE TABLE conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_key TEXT NOT NULL,
  display_name TEXT,
  is_whitelisted INTEGER DEFAULT 0,
  is_blacklisted INTEGER DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  direction TEXT NOT NULL,
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL DEFAULT 1.0,
  handled_status TEXT DEFAULT 'pending',
  artifact_path TEXT,
  UNIQUE(conversation_id, direction, content_hash, observed_at)
);

CREATE TABLE reply_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL,
  source_message_id INTEGER,
  reply_text TEXT NOT NULL,
  status TEXT NOT NULL,
  scheduled_at TEXT,
  sent_at TEXT,
  failure_reason TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Suggested statuses:

```text
message.handled_status:
pending | skipped | replied | extracted | human_required | failed

reply_tasks.status:
draft | approved | queued | sending | sent | blocked | failed | cancelled
```

### 4.5 CustomerServiceDecisionEngine

This is a business-layer component.

Inputs:

```text
conversation profile
recent messages
script library
persona config
business rules
current risk limits
```

Outputs:

```text
reply decision
field extraction result
handoff decision
scheduled follow-up suggestion
```

Decision priority:

1. Hard safety rules.
2. Exact script match.
3. Intent classification.
4. Field extraction.
5. LLM reply generation.
6. Human handoff.

LLM output must be schema-validated before use.

### 4.6 Script Library and Persona

Keep these as configuration files, not platform code.

Suggested files:

```text
runtime/data/wechat_customer_service/persona.yaml
runtime/data/wechat_customer_service/scripts.yaml
runtime/data/wechat_customer_service/rules.yaml
```

Persona config should include:

```text
brand_name
service_role
tone
allowed_claims
forbidden_claims
handoff_phrases
signature_policy
```

Script entries should include:

```text
intent
trigger_keywords
required_context
reply_template
handoff_required
cooldown_seconds
```

### 4.7 StructuredDataSink

Initial target is Excel. Later targets may include ERP API or ERP UI automation.

Responsibilities:

```text
validate_schema(record)
deduplicate_record(record)
append_to_excel(record)
mark_source_message(record_id, message_id)
export_error_report()
```

Excel writes should use `openpyxl`, not GUI Excel automation, unless a specific
business requirement requires interacting with an already-open workbook.

Minimum extracted record:

```json
{
  "customer_name": "",
  "phone": "",
  "address": "",
  "product": "",
  "quantity": 1,
  "source_contact": "",
  "source_message_id": 0,
  "created_at": ""
}
```

### 4.8 ScheduledMessageService

Scheduled messages must be queued and risk-checked before sending.

Responsibilities:

```text
create_task(contact, text, scheduled_at)
list_due_tasks(now)
apply_risk_guard(task)
enqueue_for_send(task)
retry_failed(task)
cancel_task(task)
```

Scheduled sending must support:

- Per-contact daily limits.
- Global hourly limits.
- Quiet hours.
- Blacklist and whitelist.
- Duplicate message detection.
- Manual approval mode.

### 4.9 RiskGuard

RiskGuard is mandatory before any automatic send.

Checks:

```text
is_contact_allowed(contact)
is_quiet_hours(now)
is_duplicate_reply(contact, reply_text)
within_contact_daily_limit(contact)
within_global_hourly_limit()
contains_sensitive_content(reply_text)
requires_human_by_intent(intent)
```

Default behavior should be conservative:

- Block unknown contacts for proactive scheduled messages.
- Allow automatic replies only for incoming messages from selected contacts or
  low-risk intents.
- Require human approval for payment, refund, complaint, legal, medical, and
  personal-data-sensitive content.

## 5. Workflow Design

### 5.1 Incoming Message Polling Workflow

```text
Step 1: focus_wechat
Step 2: detect_login_or_security_state
Step 3: scan_unread_conversations
Step 4: open_next_unread_conversation
Step 5: capture_recent_messages
Step 6: persist_new_messages
Step 7: classify_and_decide
Step 8: apply_risk_guard
Step 9: send_or_create_draft
Step 10: verify_and_mark_status
Step 11: capture_artifacts
```

Failure policy:

- UI action failure: retry 2-3 times with fresh screenshot.
- Text capture failure: try next capture backend.
- Unknown popup: screenshot and human handoff.
- Send verification failure: mark `failed`, do not retry indefinitely.

### 5.2 Data Extraction Workflow

```text
Step 1: load_pending_messages
Step 2: identify_messages_with_data
Step 3: extract_fields
Step 4: validate_required_fields
Step 5: write_to_message_store
Step 6: append_to_excel
Step 7: mark_source_message_extracted
Step 8: optional_reply_confirm_received
```

Validation examples:

- Phone format.
- Required fields present.
- Quantity is positive.
- Address length and province/city hints.
- Duplicate phone/order detection.

### 5.3 Scheduled Sending Workflow

```text
Step 1: load_due_scheduled_tasks
Step 2: apply_global_rate_limit
Step 3: apply_contact_policy
Step 4: focus_wechat
Step 5: open_target_conversation
Step 6: send_message
Step 7: verify_send_result
Step 8: mark_task_sent_or_failed
```

Proactive scheduled messages should default to manual approval until the system
has enough operational evidence.

## 6. Safety and Account-Risk Controls

The system cannot guarantee avoidance of WeChat personal account restrictions.
The highest account risk usually comes from behavior patterns rather than the
specific automation library.

Mandatory controls:

1. No private protocol automation.
2. No process injection or WeChat memory/database modification.
3. No bulk unsolicited messaging.
4. No automatic friend adding or group pulling.
5. Per-contact and global send limits.
6. Whitelist for scheduled proactive sends.
7. Sensitive-intent human handoff.
8. Randomized but bounded wait intervals.
9. Complete send logs and screenshots on failure.
10. One-switch pause for all automatic sends.

Recommended initial mode:

```text
Read incoming messages automatically.
Generate reply drafts automatically.
Auto-send only high-confidence, low-risk replies.
Route all other cases to human approval.
```

## 7. Milestones

### Milestone 0: Feasibility Probe

Goal: Prove whether WeChat text and input areas can be accessed reliably on the
target Windows machine.

Deliverables:

- `pywinauto` probe script.
- Screenshot/OCR fallback probe.
- WeChat window focus and input test.
- Artifact directory with screenshots and logs.

Success criteria:

- Can focus WeChat reliably.
- Can detect login/security/locked states.
- Can send a test message to a controlled conversation.
- Can capture recent messages with enough accuracy for a pilot.

### Milestone 1: Minimal Manual-Approval Assistant

Goal: Read messages and draft replies, but require human confirmation.

Deliverables:

- MessageStore.
- WeChatDesktopAdapter MVP.
- Script library MVP.
- LLM decision schema.
- Draft reply queue.

Success criteria:

- No duplicate message processing.
- Drafts are traceable to source messages.
- Human can approve, edit, or reject drafts.

### Milestone 2: Low-Risk Auto Reply

Goal: Auto-send replies for whitelisted contacts and low-risk intents.

Deliverables:

- RiskGuard.
- Send verification.
- Failure screenshots.
- Rate limits.

Success criteria:

- Auto replies only occur under explicit allowed conditions.
- Failed sends are not repeated indefinitely.
- Logs can explain every sent message.

### Milestone 3: Data Extraction to Excel

Goal: Extract structured customer/order data and append to Excel.

Deliverables:

- Field schema.
- Extraction rules and LLM fallback.
- Excel sink.
- Duplicate detection.

Success criteria:

- Valid messages create one Excel row.
- Invalid or incomplete records go to human review.
- Source message linkage is preserved.

### Milestone 4: Scheduled Sending

Goal: Send approved scheduled messages to selected customers.

Deliverables:

- ScheduledMessageService.
- Approval status.
- Per-contact/global limits.
- Quiet hours.

Success criteria:

- Scheduled sends respect all limits.
- Blacklisted contacts are never messaged.
- Duplicate scheduled messages are blocked.

### Milestone 5: ERP Integration

Goal: Replace or augment Excel with ERP integration.

Preferred order:

1. ERP API.
2. Browser automation for ERP web forms.
3. Desktop UI automation only if no better path exists.

## 8. Suggested Repository Layout

Initial exploratory layout:

```text
workflows/temporary/desktop/wechat_customer_service/
  README.md
  probe_wechat_uia.py
  probe_wechat_capture.py
  wechat_adapter.py
  message_store.py
  decision_engine.py
  risk_guard.py
  excel_sink.py
  run_incoming_assistant.py
  run_scheduled_sender.py
```

Runtime data:

```text
runtime/data/wechat_customer_service/
  wechat_customer_service.sqlite3
  persona.yaml
  scripts.yaml
  rules.yaml
  customer_whitelist.csv
  customer_blacklist.csv
  customer_data.xlsx
```

Artifacts:

```text
runtime/test_artifacts/wechat_customer_service/
  screenshots/
  logs/
  ocr/
  failure_cases/
```

Future platform candidates:

```text
platform/src/omniauto/desktop/window_adapter.py
platform/src/omniauto/desktop/text_capture.py
platform/src/omniauto/messaging/store.py
platform/src/omniauto/messaging/rate_limit.py
```

## 9. Testing Strategy

### Unit tests

- Message deduplication.
- RiskGuard limits.
- LLM JSON schema validation.
- Field extraction validation.
- Excel append and duplicate detection.

### Integration tests

- WeChat adapter against controlled test account/conversation.
- End-to-end draft generation without auto-send.
- Scheduled task queue without real sending.

### Manual verification

- Login expired.
- WeChat locked.
- Unknown popup.
- Network delay.
- Long message.
- Image/file message.
- Multiple unread conversations.
- Same customer sends repeated messages.

## 10. Open Questions

1. Which WeChat version and Windows display scale will be the first target?
2. Is the first version allowed to auto-send, or must all replies require manual
   approval?
3. What Excel schema should be treated as authoritative?
4. Which contacts are allowed for scheduled messages?
5. What are the maximum per-hour and per-day send limits?
6. Which LLM provider/model should be used for reply generation?
7. Will ERP provide an API, or must it be filled through UI automation?

