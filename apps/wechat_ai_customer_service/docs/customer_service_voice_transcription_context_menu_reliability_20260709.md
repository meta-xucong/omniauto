# WeChat Customer Service Voice Transcription Context-Menu Reliability 2026-07-09

Reference baseline: `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`

## Goal

Stabilize WeChat voice transcription in the customer-service code mechanism layer without changing Brain reply ownership.

This change targets four runtime goals:

1. Stop treating WeChat voice UI text such as duration bubbles or `转文字` affordances as customer message content.
2. Change voice transcription from direct click on the right-side affordance to `right-click voice bubble -> click context-menu action`.
3. Transcribe visible untranslated voice bubbles regardless of unread status and regardless of whether the bubble belongs to the customer or self.
4. Preserve self-authored visible text and successful self/customer voice transcripts in session ledger history so Brain context stays complete.

## Scope Boundary

This is a code mechanism layer change only.

- No customer-visible wording is authored here.
- No Brain business strategy, guard policy, or final visible ownership is changed.
- No new product/business hard-coded reply branch is introduced.

Touched layers are limited to:

- Win32/OCR sidecar capture and UI action logic
- connector retry/orchestration
- scheduler-to-sidecar metadata propagation
- capture/session ledger history completeness
- compatibility and scheduler regression tests

## Root Cause Summary

### 1. Wrong conversation type inference for private contacts

The Win32/OCR sidecar previously inferred conversation type from display name alone.

`新数据测试` was incorrectly classified as `group` because the legacy heuristic treated `测试` as a group indicator. That downgraded left-side customer bubbles to `unknown/group_member`, which then polluted Brain input and increased `customer_service_brain_no_visible_reply` risk.

### 2. OCR self-tail fragmentation

Some self-authored right-side reply tails were split into a second OCR row with a slight negative overlap. The previous continuation merge rejected that overlap, so the self tail could leak into a fresh captured batch as if it were a new customer line.

### 3. Voice UI text leaked into reply-input batch

The message parser already ignored pure voice-duration bubbles such as `4"`, but it did not suppress the combined UI pattern:

- first line: voice duration
- second line: `转文字`

That allowed `4" + 转文字` to become a normal customer text turn.

### 4. Direct-click voice transcription was brittle

The old flow attempted to click the visible right-side `转文字` affordance directly. In live WeChat this was less stable than right-clicking the voice bubble and selecting `语音转文字` from the context menu.

When the direct target was not found or the conversion result was not read immediately, the runtime could still continue with normal OCR capture and accidentally feed UI residue into Brain.

## Design

### A. Conversation type becomes authoritative metadata, not name guess

Scheduler already knows the session-level `conversation_type`.

The runtime now passes that value through:

- scheduler -> workflow voice-transcription call
- scheduler -> connector `get_messages`
- connector -> sidecar CLI arguments
- sidecar -> `parse_messages_from_ocr(...)`

Name-based inference remains as fallback only when explicit metadata is absent.

### B. Voice translation uses context-menu route

The new live route is:

1. detect latest visible untranslated voice-duration bubble
2. right-click the voice bubble anchor region
3. OCR the popup menu
4. click the visible `语音转文字` / `转文字` menu action
5. wait for transcript materialization
6. recapture chat OCR and diff against pre-action messages

This replaces the direct-click affordance path as the main runtime route.

2026-07-09 follow-up refinement:

The context-menu route is deliberately fail-closed. A visible untranslated voice bubble is required before any mouse action. The first right-click is allowed only while the target WeChat main window is still visible. The second click is allowed only after the popup OCR identifies the `语音转文字` / `转文字` row directly, or identifies enough neighboring menu rows to infer the row order.

Locator priority:

1. If OCR sees `语音转文字` / `转文字` / equivalent text, click that menu item.
2. If OCR misses the first row but sees later voice-menu rows such as `收藏`, `多选`, `提醒`, `引用`, or `删除`, infer the first row from menu row order and click it.
3. If OCR sees no usable menu evidence, stop without a menu click. Do not infer a first row from the anchor and do not click a stale or shifted coordinate.

After one physical right-click or menu click, the connector does not repeat the same physical action when the transcript is not observed. It preserves the screenshot, OCR samples, coordinates, and window probes for diagnosis. It does not fall back to a customer-visible local reply and does not synthesize transcript text.

The normal text/image capture path reads messages first and runs voice RPA only when the payload contains explicit voice evidence. This prevents a numeric OCR fragment inside a photo, a product price, or ordinary text from entering the voice click path.

### C. Untranslated voice is defined by missing transcript below the bubble

The sidecar treats a voice bubble as already converted only when a transcript-like text block is visible below the duration bubble in the chat surface.

Unread status is not required.

Bubble ownership is not required.

Therefore:

- customer voice can be transcribed
- self voice can also be transcribed
- old read bubbles can still be transcribed if the transcript is not visible below

### D. Voice UI residue is filtered before Brain

The parser now rejects groups that represent voice conversion UI instead of semantic message content, especially:

- `duration + 转文字`

This guarantees that failed or partial voice UI states do not become customer reply-input text.

### E. Self history stays complete

Session ledger capture already stores the full `messages` list, not only reply-input `batch`.

This implementation preserves that behavior and ensures:

- self-authored visible OCR text remains in `recent_messages`
- successful self/customer voice transcripts merged into `messages` are also persisted
- Brain can read `ledger_recent_messages` and `context_summary` with a fuller conversation trace

## Contracts

### New/extended internal connector parameters

`WeChatConnector.get_messages(...)`

- new optional arg: `conversation_type`

`WeChatConnector.transcribe_voice_messages(...)`

- new optional arg: `conversation_type`

### New/extended sidecar CLI arg

`wechat_win32_ocr_sidecar.py`

- new optional flag: `--conversation-type`

### New/adjusted sidecar states

Possible voice states now include:

- `voice_transcribe_target_not_found`
- `voice_transcribe_context_menu_target_not_found`
- `voice_transcribe_context_menu_click_failed`
- `voice_transcribe_context_menu_no_new_text`
- `voice_transcribe_completed`
- `voice_transcribe_no_visible_voice`
- `voice_transcribe_no_new_text`

These are internal observability states only.

## Files

Primary code:

- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr/text_normalization.py`
- `apps/wechat_ai_customer_service/adapters/wechat_connector.py`
- `apps/wechat_ai_customer_service/adapters/wechat_sidecar_runner.py`
- `apps/wechat_ai_customer_service/adapters/wechat_win32_ocr_sidecar.py`
- `apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py`
- `apps/wechat_ai_customer_service/workflows/listen_and_reply.py`

Primary tests:

- `apps/wechat_ai_customer_service/tests/run_wechat_win32_ocr_compat_checks.py`
- `apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py`

## Verification Plan

Static/runtime checks:

1. `py_compile` for touched files
2. Win32/OCR compatibility regression checks
3. multi-session scheduler regression checks

Live acceptance focus:

1. Two sessions active in parallel
2. One session receives customer voice, one receives text/image
3. Voice route must use context-menu transcription path
4. No `4" + 转文字` UI residue may enter Brain input
5. Private contact named with `测试` must remain `private`, not `group`
6. Self reply tails must not re-enter as new customer turns

## Risks And Guardrails

Risk: stale or shifted coordinates could create an unintended UI click.

Guardrail:

- the target must be a visually plausible grey incoming or green self voice bubble, not bare numeric OCR
- the target WeChat main window must remain visible after the right-click and after the menu click
- empty or unrelated menu OCR fails closed; no anchor-only first-row fallback exists in the live path
- after one physical interaction, the same sidecar request never repeats the click on a stale target
- no direct-click affordance path is used; the only action path is right-click voice bubble, then evidence-confirmed context-menu click

Risk: context menu OCR may fail occasionally.

Guardrail:

- OCR failure prevents the context-menu row click rather than risking a wrong menu action
- failure details are recorded as internal state, including menu screenshot path and OCR text samples when available
- UI residue is filtered before Brain
- no fake “heard unclear” or fake “transcribed text” should be synthesized from menu residue

Risk: changing conversation-type inference might affect legacy tests or ad hoc group-like names.

Guardrail:

- explicit scheduler/session `conversation_type` now overrides name guess
- fallback name inference still keeps obvious `群/chatroom/room`
