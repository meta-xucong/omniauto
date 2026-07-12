# WeChat AI Customer Service Context Rupture Recovery

Date: 2026-07-10

Related baseline: [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)

## Problem

Live testing found a recurring read-without-reply shape after human intervention:

- A session may contain a backlog of unrelated manual chat, logs, quoted/group records, API errors, images, voice transcripts, or test content.
- The scheduler may correctly capture the latest text/image/voice turn, but Brain receives too much old context plus `stale_unsent_reply_context`.
- Brain can over-weight the stale context, or a later freshness check can treat the old anchor/gap as a reason to block, even when no truly newer customer message is present.

This is not an image, voice, or product-matching-only defect. It is a context continuity defect at the boundary between capture/session ledger and Brain input.

## Design Goal

Add a lightweight, reusable context-rupture recovery mechanism:

- Mechanism layer detects only that the current capture is a candidate for context rupture.
- Brain remains the only owner of customer-visible reply understanding and wording.
- Product facts still come only from product master; policies still come only from formal knowledge.
- Send-target/session envelope checks, guard verification, final visible polish, and true-new-message freshness remain hard protections.

## Runtime Flow

1. Scheduler capture evaluates the current raw messages, selected Brain batch, history backfill, pending signal, and stale reply context.
2. If multiple weak signals point to human intervention or incomplete context, capture records `context_recovery`.
3. Scheduler state persists that metadata and emits a non-customer-visible audit event.
4. Brain input receives a compact recovery hint under `current_message.context_recovery`.
5. In `latest_turn_only_candidate` mode, Brain prompt keeps the latest current turn prominent and prunes old ledger/history/stale context from prompt-visible context.
6. Brain decides whether the old context is noise. If the latest turn is actionable, Brain replies normally using current turn plus authority evidence.
7. Freshness can soft-pass only old-anchor/gap style uncertainty when there is no corroborated newer message. It must not send if a real newer message is detected.

## Candidate Signals

The detector is intentionally heuristic but generic. It does not try to understand every business intent with regex. It only marks context continuity risk when signals combine:

- `history_continuity=overflow_unanchored`
- A stale unsent reply context exists from a previous interrupted turn
- Raw visible message count or selected batch count is unusually high
- The latest actionable customer turn is a visual proxy, image, voice transcript, short summon, or otherwise fresh turn
- Text contains obvious non-dialogue noise such as copied chat records, API/debug logs, Codex/system text, token/URL fragments, or service errors
- Pending media/session-list signal indicates a fresh turn while the visible history looks older or mixed

The detector produces metadata, not a reply.

## Prompt Contract

When `context_recovery.applied=true`:

- `current_message.context_priority_policy` tells Brain: old context may be contaminated; judge continuity first; if old context is unrelated, answer the latest actionable customer turn.
- Prompt-visible `conversation.history_text`, `conversation.summary`, `ledger_context_summary`, `ledger_recent_messages`, and `stale_unsent_reply_context` are removed or replaced with recovery policy notes.
- Authority evidence, visual bridge input, product master, formal knowledge, current message text, message ids, and session identity are preserved.

## Freshness Boundary

Allowed soft pass:

- Strict scan reports only uncorroborated old-anchor/gap uncertainty.
- Session preview does not show unread/newer content.
- Capture has `context_recovery.applied=true`.

Never soft pass:

- Confirmed newer customer messages exist.
- Session envelope mismatches target/session/content digest.
- Guard or final polish blocks the reply.
- Brain result is missing, empty, or non-adoptable.

## Restart Stale Work Boundary

Live restart testing on 2026-07-10 exposed a separate mechanism-layer risk: a durable scheduler state can contain old queued/running LLM tasks, queued polish tasks, or ready replies from before manual intervention. If the listener restarts later, those old tasks must not resume and send as if they were fresh customer turns.

Policy:

- Queued LLM and polish tasks older than `pending_session_ttl_seconds` are marked stale before submission.
- Orphaned running LLM and polish tasks older than `pending_session_ttl_seconds` are expired instead of requeued after restart.
- Ready replies older than `reply_ready_ttl_seconds` are marked stale before send.
- Expired work remains auditable in scheduler state/events, but it cannot create or send customer-visible text.
- Fresh messages are still captured through the normal session monitor/RPA path; Brain remains the only owner of visible replies.

## Files

- `admin_backend/services/customer_service_scheduler.py`
  - Builds context recovery metadata during capture.
  - Carries metadata through scheduler capture result.
  - Applies narrow freshness soft pass for uncorroborated old-context gaps only.
  - Prevents stale orphaned running tasks from being requeued after restart.

- `admin_backend/services/customer_service_scheduler_state.py`
  - Persists `context_recovery` into capture/session state.
  - Emits audit events for recovery candidates.
  - Expires old queued LLM/polish work and old ready replies before they can run/send.

- `workflows/customer_service_brain.py`
  - Adds compact recovery hint to Brain input.
  - Prunes prompt-visible stale/ledger/history context when latest-turn-only candidate mode is active.

- `tests/run_customer_service_multi_session_scheduler_checks.py`
  - Verifies scheduler state persistence and freshness boundary.
  - Verifies stale restart work cannot resume or send.

- `tests/run_customer_service_brain_contract_checks.py`
  - Verifies Brain input/prompt pruning without bypassing authority evidence.

## Acceptance

- No customer-visible wording is authored outside `customer_service_brain`.
- No local fallback reply is introduced.
- Context recovery metadata is auditable after capture.
- Brain prompt focuses on latest content when context rupture is likely.
- Real newer messages still block stale replies.
- Restarting the listener cannot resume old queued/orphaned/ready work beyond TTL.
- Focused scheduler and Brain contract tests pass.
