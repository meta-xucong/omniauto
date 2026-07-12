# Customer-Visible Reply Ownership Baseline

## Hard Rule

For `apps/wechat_ai_customer_service`, every customer-visible reply must be authored by `customer_service_brain`.

Allowed customer-visible reply sources are only:

- `brain`: the first valid BrainPlan.
- `brain_repair`: a repaired BrainPlan produced after reviewer feedback.
- Brain-authored hard-boundary, refusal, or handoff wording when the Brain itself decides the boundary response inside formal/safety constraints.

Forbidden customer-visible reply sources:

- `guard_handoff_ack`, quality-gate templates, semantic-reviewer templates, final-polish strategy rewrites.
- Legacy realtime/RAG/local route templates or old LLM synthesis when Brain First is enabled.
- Local safe fallback text when Brain is unavailable, times out, is non-adoptable, or repair fails.

## Reviewer Contract

Guard, quality gate, semantic reviewer, evidence/retrieval layers, realtime route logic, and final polish are reviewers or advisors. They may provide evidence, risk labels, warnings, repair instructions, audit fields, or light naturalization. They must not decide or replace customer-facing meaning, facts, recommendation strategy, risk posture, or conversation intent.

If a reviewer finds a Brain draft wrong, incomplete, unsafe, off-topic, over-structured, or poorly phrased, it must return feedback for Brain repair. If the Brain cannot produce an adoptable reply, the runtime must block outbound send, record audit, and trigger the internal handoff/alert interface. It must not send a locally generated customer-visible fallback.

## Quality Gate Authority

Quality gates are reviewer layers, not answer owners. Deterministic quality findings must be classified before they affect outbound send:

- Hard blockers: empty visible reply, AI identity leakage, truncated or incomplete wording, unsupported product facts, price/policy conflicts, hard safety risks, session/cross-chat binding risks, and unresolved authority-boundary violations.
- Soft reviewer findings: wording directness, recommendation shape, missing preferred phrasing, incomplete but non-dangerous answer focus, deterministic uncertainty after Brain repair, and short-social continuity/naturalness notes such as `delay_followup_short_social_reply_review`.

Soft reviewer findings must be fed back to Brain for repair first. After Brain repair, if validation and hard-boundary checks pass, remaining soft quality doubts may only become audit warnings or semantic-review feedback; they must not be escalated into `customer_service_brain_no_visible_reply` by themselves.

In particular, a non-empty Brain-authored short acknowledgement such as a response to "在吗" remains sendable when structural validation, authority, session binding, and hard-risk checks pass. Operator attention may be recorded separately, but it must not replace or erase the Brain reply.

## Development Requirement

Every new customer-service development document must reference this baseline. Any exception requires updating `AGENTS.md`, this baseline, and contract tests before code changes.
