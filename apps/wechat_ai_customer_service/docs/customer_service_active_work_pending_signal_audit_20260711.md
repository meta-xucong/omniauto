# Active-Work Pending Signal Audit

## Scope

This change follows the Brain First customer-visible reply ownership baseline in
`apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`.
It changes only scheduler signal retention. It does not change image capture,
Brain prompting, product evidence, visible reply wording, or RPA sending.

## Root Cause

After a listener restart, a persisted running Brain task may be requeued while
its Python future is gone. The same-session active-work guard correctly prevents
a second foreground capture, but the bridge previously removed busy targets
from the scheduler input. A new unread signal could therefore disappear before
the old task finished. Later polls could produce empty captures because no
durable pending signal remained.

## Contract

1. A busy session is still protected from a second concurrent RPA capture.
2. A busy session with unread, voice, image, media, or short-sensitive evidence
   remains in scheduler input and is persisted as pending work.
3. Ordinary preview drift without durable unread/media evidence remains filtered
   and does not cause foreground hopping.
4. After the older Brain/send task finishes, the retained signal becomes
   dispatchable and the normal capture path continues.
5. Session isolation and Brain-owned customer-visible wording remain unchanged.

## Audit Evidence

- The live trace showed `llm_task_orphan_requeued`, followed by
  `active_lock_reason=llm_or_polish_running` and `pending_sessions=0`.
- The old bridge then produced `batch=0` captures after the old task finished.
- The fixed regression covers both the state-layer unread-only signal and the
  bridge-layer busy unread signal.
