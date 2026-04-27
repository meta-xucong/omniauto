# WeChat Customer Service RPA Blueprint

## Summary

- Task name: WeChat customer service automation blueprint
- Status: baseline validated with File Transfer Assistant
- Domain: desktop automation
- Why it mattered: the user wants to use OmniAuto to operate Windows WeChat as
  a personal customer service assistant that can reply to chats, collect
  structured data into Excel, and later send data into an ERP system.

## Inputs

- Natural-language request:
  - Design the best implementation approach for Windows WeChat customer service
    automation using OmniAuto.
  - Explain the role of `pywinauto` versus existing OmniAuto mouse/keyboard
    automation.
  - Analyze account-risk boundaries for WeChat personal account automation.
  - Produce detailed development and environment/component requirement
    documents for future implementation.
- External systems:
  - Windows WeChat personal client.
  - Excel workbook.
  - Future ERP system.
  - Optional LLM provider for reply decisions and field extraction.
- Required local files:
  - `docs/WECHAT_CUSTOMER_SERVICE_RPA_SPEC.md`
  - `docs/WECHAT_CUSTOMER_SERVICE_ENVIRONMENT_REQUIREMENTS.md`

## Assets

- Development spec:
  - `../../../docs/WECHAT_CUSTOMER_SERVICE_RPA_SPEC.md`
- Environment and component requirements:
  - `../../../docs/WECHAT_CUSTOMER_SERVICE_ENVIRONMENT_REQUIREMENTS.md`
- Primary workflow scripts:
  - `../../../workflows/temporary/desktop/wechat_customer_service/wechat_sidecar_runner.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/wechat_connector.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_service_loop.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_service_rules.example.json`
  - `../../../workflows/temporary/desktop/wechat_customer_service/guarded_customer_service_workflow.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.example.json`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_service_workflow.test_contact.example.json`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_service_review_queue.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/wechat_customer_service_preflight.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/approved_outbound_send.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/customer_intent_assist.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/llm_intent_candidate.example.json`
  - `../../../workflows/temporary/desktop/wechat_customer_service/deepseek_connection_test.py`
- Verification scripts:
  - `../../../workflows/temporary/desktop/wechat_customer_service/wxauto4_sidecar.py`
  - `../../../workflows/temporary/desktop/wechat_customer_service/probe_wechat_observability.py`
- Formal outputs:
  - `../../../docs/WECHAT_CUSTOMER_SERVICE_FINAL_BASELINE.md`
  - `../../../docs/WECHAT_CUSTOMER_SERVICE_DEBUG_LESSONS_AND_ROADMAP.md`
- Raw artifacts:
  - `../../../runtime/test_artifacts/wechat_customer_service/customer_leads.xlsx`
  - `../../../runtime/test_artifacts/wechat_customer_service/review_queue.json`
  - `../../../runtime/test_artifacts/wechat_customer_service/review_queue.xlsx`
- Related tests:
  - None yet.

## What Was Proven

1. Current OmniAuto already has useful desktop RPA foundations: visual
   automation, hard input, workflow/state-machine execution, Excel dependency,
   scheduled-job dependency, and recovery primitives.
2. `pywinauto` is not currently integrated and should be considered a Windows
   UI Automation/control-inspection layer, not a replacement for OmniAuto's
   existing visual and hard-input engines.
3. The best architecture is hybrid: deterministic OmniAuto execution with LLMs
   limited to structured semantic decisions.
4. For Windows WeChat 4.1.8.107 on this machine, screenshot/OCR/window-capture
   is not a reliable primary path. The WeChat main window can use
   `WDA_EXCLUDEFROMCAPTURE`, and capture attempts may return black, blank,
   transparent, or background-window pixels.
5. The reliable baseline is a Python 3.12 `wxauto4` sidecar called from the
   Python 3.13 OmniAuto process. It can read the logged-in user, sessions,
   messages, send to File Transfer Assistant, and read back the sent message.
6. The runner must not start WeChat by default. It should connect only to an
   already logged-in main window; explicit startup is allowed only with
   `--start-if-missing`.
7. A minimal guarded loop now works against File Transfer Assistant: it can
   select an eligible text message, generate a deterministic rule reply, send
   only when explicitly requested, verify by reading back, and persist the
   processed message id.
8. A config-driven guarded workflow now supports whitelisted targets, bootstrap
   for existing history, message aggregation, simple rate limits, dry-run by
   default, explicit send mode, read-back verification, persistent state, and
   JSONL audit logs.
9. Customer-data capture is now validated on File Transfer Assistant: a
   synthetic customer profile was extracted, written to
   `runtime/test_artifacts/wechat_customer_service/customer_leads.xlsx`, and a
   confirmation reply was sent and verified.
10. Incomplete customer-data handling is validated: the workflow detects
    missing required fields, asks for the missing field, stores pending state,
    merges the later supplement, writes the completed row to Excel, and marks
    the pending record completed.
11. A manual review queue is available. It reads workflow state and audit logs,
    lists pending customer-data records, handoff events, blocked/error audit
    events, and can export JSON or Excel for human review.
12. Real-contact preflight is available. It checks login state, sidecar files,
    config paths, review-queue health, recent session presence, and whether a
    target name matches the current logged-in account.
13. Runtime `--target` is available for bootstrap/dry-run only. Send mode is
    blocked for runtime targets unless the target is in the config whitelist.
14. The guarded workflow now uses a state-file lock to avoid overlapping
    state writes from scheduled jobs or manual runs.
15. A real-contact dry-run probe was performed for `许聪`: preflight passed
    with a whitelist warning, bootstrap marked zero existing text messages, and
    dry-run found no eligible unprocessed messages. No message was sent.
16. A dedicated test-contact config now whitelists `许聪` with separate state,
    audit, and workbook paths.
17. A guarded outbound sender is available for one-off test sends and future
    scheduled outreach. It is dry-run by default and requires a configured
    whitelist target, clean review queue, passing rate limit, explicit
    `--send`, and read-back verification.
18. The outbound sender was validated against `许聪` with the message
    `[OmniAuto客服测试] 这是一条自动化客服白名单发送测试，请忽略。`;
    the send succeeded and was read back from the target chat.
19. A short real-contact listener test was validated. The workflow received
    inbound messages from `许聪`, replied automatically, verified sent replies,
    captured a customer-data message into the test-contact Excel workbook, and
    skipped its own bot replies afterward.
20. Two follow-up hardening fixes were applied from the test: rule selection now
    chooses the best keyword match by priority/match strength instead of first
    match, and the manual review queue suppresses blocked audit events that
    were later resolved by a successful send/capture/bootstrap.
21. A structured intent assistant is now available as an advisory layer. It
    returns JSON-shaped intent advice and is connected to the guarded workflow
    audit events in advisory-only mode for the test-contact config. It does not
    override replies or operate WeChat.
22. The LLM provider bridge is scaffolded without making model calls: prompt
    packs and JSON schema can be emitted, manual candidate JSON can be
    validated, and validated candidates can be compared with the heuristic
    result in workflow audit fields.
23. DeepSeek API connectivity was validated through `DEEPSEEK_API_KEY`.
    `deepseek-chat` returned `pong` for the connection test, then returned a
    schema-valid advisory JSON for `冰箱的价格是多少`. The test-contact workflow
    now supports DeepSeek advisory-only calls and records usage/validation in
    audit fields.

## Reusable Takeaways

1. For messaging automation, the highest operational risk comes from behavior
   patterns such as bulk proactive sending, not only from the local input
   library used.
2. WeChat-specific UI logic should begin in `workflows/temporary/desktop/`
   because the client UI is version-sensitive.
3. Generic desktop capabilities such as a `pywinauto`-backed window adapter,
   clipboard manager, text-capture interface, message queue, and rate limiter
   are plausible platform candidates after a focused probe.
4. For WeChat 4.1.x, normal operation should use UIAutomation through
   `wxauto4`; screenshot/OCR probes should remain diagnostics only.
5. Always send with an explicit target and verify by reading the message back.
6. Keep the sidecar boundary until `wxauto4` supports the main project Python
   version or OmniAuto provides an equivalent native connector.

## Promoted Knowledge

- Related patterns:
  - None promoted yet.
- Related lessons:
  - None promoted yet.
- Related capabilities:
  - Potential future capability: desktop messaging automation with guarded
    send workflows.
- Related skills:
  - None.

## Follow-Up

- Remaining limitations:
  - `wxauto4` is currently isolated in a Python 3.12 sidecar because the main
    project uses Python 3.13.
  - The implementation has only been validated on File Transfer Assistant, not
    on real customer chats.
  - The current Excel schema is a test schema, not the user's final business
    schema.
  - No LLM reply policy or deterministic FAQ library has been implemented yet.
  - ERP form filling has not been implemented yet.
- Next recommended improvement:
  - Run another short test-contact listener with DeepSeek advisory-only enabled
    over several inbound customer-service examples, then review audit
    differences before considering any controlled LLM reply override.
