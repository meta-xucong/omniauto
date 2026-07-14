# Brain First Non-Blocking Quality Reply Contract

Reference baseline: [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md).

## 1. Incident And Root Cause

On 2026-07-12, the `新数据测试` session reached capture and Brain normally. Brain returned a non-empty short social reply, and both the main Brain call and the quality-repair call returned HTTP 200. The runtime then classified the reply as `delay_followup_reply_looks_like_fresh_greeting`, cleared the visible reply, and entered `customer_service_brain_no_visible_reply`.

The defect was not that Brain produced a mechanical answer. The defect was an authority inversion: a lexical continuity heuristic treated an ordinary short social acknowledgement as a hard quality failure. The failure was amplified because this error was not in the soft-quality set, so a failed repair was allowed to swallow an otherwise valid Brain reply.

## 2. Target Architecture

The reply pipeline now uses four decision classes:

1. `BrainPlan`: Brain understands the current turn, uses authorized evidence, chooses the reply strategy, and owns all visible wording.
2. Hard boundary: structural invalidity, empty text, unsupported authoritative facts, prompt/identity leakage, unsafe commitments, cross-session binding risk, or an explicit Brain hard handoff can block sending.
3. Soft quality: wording, naturalness, recommendation shape, continuity suggestions, and other non-dangerous reviewer concerns. These may trigger one Brain repair, then remain audit warnings if the plan is still structurally and factually safe.
4. Operational attention: soft warnings that deserve human review are carried as `brain_quality_review` and recorded by the scheduler as `scheduler_operator_attention_required`. This signal does not rewrite the visible reply or turn a valid Brain reply into a local handoff template.

## 3. Short Social Reply Standard

For a current social probe such as "在吗", "人呢", or "在不在", a short Brain-authored reply is normal. The quality layer must not decide that phrases such as "在呢" or "您说" are mechanical by keyword alone.

The acceptance standard is semantic and structural:

- `recommended_action=send_reply`
- `can_answer=true`
- non-empty `reply_segments`
- no unsupported product or policy facts
- no hard-risk tags or unauthorized commitment
- Brain remains the visible reply owner

If these conditions hold, the reply remains sendable. `delay_followup_short_social_reply_review` is an advisory warning only. It is deliberately excluded from the extra semantic-review LLM trigger to avoid adding latency for a low-risk social turn.

## 4. Frontend And Backend Behavior

When a valid Brain reply survives the hard checks:

- frontend sends the Brain-authored text exactly through the existing final-polish and RPA path;
- `customer_service_brain_adopted.applied` remains `true`;
- the reply decision carries `brain_quality_review` with `visible_reply_preserved=true`;
- the scheduler records `scheduler_operator_attention_required` when operator attention is needed;
- no legacy route, local fallback, or handoff template takes over the customer-visible wording.

If Brain has no usable visible text or a true hard boundary cannot be verified, the existing Brain First safety block remains. The system must not invent a local customer reply merely to hide a missing Brain result.

## 5. Files And Contracts

- `workflows/customer_service_brain_contract.py`: turns short social continuity from a blocking error into an advisory warning.
- `workflows/customer_service_quality_reviewer.py`: does not invoke another semantic-review LLM solely for this advisory warning.
- `workflows/customer_service_brain.py`: preserves safe Brain social replies after soft repair doubts and emits `brain_quality_review` metadata.
- `workflows/listen_and_reply.py`: carries the metadata without changing Brain reply ownership.
- `admin_backend/services/customer_service_scheduler.py`: records operator-attention events without blocking send.

## 6. Acceptance Matrix

| Case | Visible reply | Backend signal | Send blocked |
| --- | --- | --- | --- |
| "在吗" + Brain reply "在呢，您说" | Brain reply preserved | Optional quality review | No |
| Soft continuity/recommendation doubt after Brain repair | Brain reply preserved if hard checks pass | Quality warning / review | No |
| Empty Brain reply | None | Internal handoff/alert | Yes |
| Unsupported product fact or cross-session mismatch | None | Hard-boundary alert | Yes |
| RPA target/freshness mismatch | None for that stale reply | Requeue or send safety event | Yes |

## 7. Regression Commands

```powershell
python apps/wechat_ai_customer_service/tests/run_customer_service_brain_contract_checks.py
python apps/wechat_ai_customer_service/tests/run_customer_service_multi_session_scheduler_checks.py
python apps/wechat_ai_customer_service/tests/run_brain_first_static_architecture_audit.py
python -m py_compile apps/wechat_ai_customer_service/workflows/customer_service_brain_contract.py apps/wechat_ai_customer_service/workflows/customer_service_brain.py apps/wechat_ai_customer_service/workflows/customer_service_quality_reviewer.py apps/wechat_ai_customer_service/workflows/listen_and_reply.py apps/wechat_ai_customer_service/admin_backend/services/customer_service_scheduler.py
```
