# Guarded Knowledge Closeout

This document describes the governance layer that now sits above OmniAuto's automatic knowledge closeout.

## Components

1. `platform/src/omniauto/knowledge/policy.py`
   - centralized runtime policy
   - preserves the current rule-based closeout defaults
2. `platform/src/omniauto/knowledge/manager.py`
   - executes the automatic closeout path
   - remains the authoritative implementation of controlled task closeout
3. `.agents/skills/guarded-knowledge-closeout/SKILL.md`
   - shared governance instructions for AI work on closeout, observation, and candidate review

## Default Invariants

1. The existing rule-based closeout path remains the default source of truth.
2. Controlled automatic closeout is still limited to workflows under `workflows/`.
3. Automatic writes still stop at `knowledge/` and `runtime/knowledge_runs/`.
4. Formal `skills/` and `platform/` landings still require explicit user approval.

## AI Assist Boundary

AI-assisted closeout is implemented as a strict sidecar:

1. default mode is conservative auto-strict candidate mode
2. candidate output is isolated under `knowledge/review/ai_candidates/`
3. candidate summaries are navigated from `knowledge/index/ai_candidate_queue.md`
4. invalid candidates are discarded instead of being forced into formal knowledge
5. AI candidate generation must not change task success or failure outcomes

## Auto-Enable Threshold

The default AI assist mode now uses `auto_strict_candidate`.

It will only attempt candidate generation when all of the following remain true:

1. the task is running through the controlled closeout path
2. no explicit `record_knowledge_observation(...)` notes were already emitted for the run
3. a provider is configured

Then it must also satisfy one high-signal trigger:

1. final state is `ERROR`, `TIMEOUT`, `FAILED`, or `VALIDATION_FAILED`
2. the error text includes `timeout`, `not found`, `manual_handoff`, or `verification challenge`
3. the task is a `verification`, `temporary`, or `generated` workflow that completes successfully after a longer run threshold

Manual `strict_candidate` mode still exists and bypasses the auto threshold when you explicitly want to force a candidate pass.

## Why This Exists

This split keeps the system stable:

- `policy.py` makes the runtime rules auditable
- the skill keeps AI behavior aligned with those rules
- the sidecar allows future AI assistance without weakening the current deterministic closeout path
