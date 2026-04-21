---
name: guarded-knowledge-closeout
description: Use when working on OmniAuto knowledge closeout, observation emission, manual closeout, or AI-assisted candidate generation. This skill governs both AI behavior and the platform policy boundaries for automatic knowledge growth, and should be used whenever a task touches `platform/src/omniauto/knowledge/`, `knowledge/`, `omni closeout`, or candidate promotion rules.
---

# Guarded Knowledge Closeout

This skill is the governance layer for OmniAuto's automatic knowledge growth.

Use it whenever you:
- change `platform/src/omniauto/knowledge/`
- add or refine `record_knowledge_observation(...)`
- adjust `omni run` / `omni closeout` closeout behavior
- review or generate AI-assisted knowledge candidates
- update closeout-related docs or tests

## Read First

Before changing behavior, open:
- `../../platform/src/omniauto/knowledge/policy.py`
- `../../platform/src/omniauto/knowledge/manager.py`
- `../../docs/KNOWLEDGE_WORKFLOW.md`

## Non-Negotiable Rules

1. Treat the existing rule-based closeout path as the authoritative base. Preserve default behavior unless the user explicitly requests a policy change.
2. Automatic writes may only land in `knowledge/` and `runtime/knowledge_runs/`.
3. Automatic writes must never touch `skills/`, `platform/src/`, or `platform/tests/`.
4. AI-assisted output is review-only by default. It may write candidate notes under `knowledge/review/ai_candidates/`, but it must not directly edit formal knowledge files.
5. `skills/` and hard `platform/` landings always require explicit user approval.

## Controlled Task Rules

- Controlled automatic closeout is for workflows under `workflows/`.
- External or ad hoc scripts should use `omni closeout` or `OmniAutoService.closeout_task(...)`.
- If you need to change what counts as controlled, update `policy.py`, `manager.py`, docs, and tests together.

## Observation Rules

When task code emits observations, keep them structured and minimal:
- `kind`: `pattern`, `lesson`, `capability`, or `proposal`
- `title`
- `summary`
- `domain`
- `evidence`

Prefer the smallest reliable observation over a long narrative. If evidence is weak, do not emit a stronger claim.

## AI Candidate Rules

AI-assisted closeout is a strict sidecar, not the main pipeline.

- Default mode should remain conservative.
- AI input must be an evidence pack, not a free-form repository scan.
- AI output must be schema-shaped and evidence-bound.
- Invalid candidates should be discarded, not coerced into formal knowledge.
- Candidate files stay in `knowledge/review/ai_candidates/` until a human promotes or rewrites them.

## Change Checklist

When changing closeout governance:
1. Update `policy.py` first if the rule itself changes.
2. Update `manager.py` only after the policy boundary is clear.
3. Keep AI-assist behavior isolated from the main success/failure path.
4. Add or update unit tests for policy preservation and write boundaries.
5. Run static compile, targeted closeout tests, a real `omni run` probe, then full `pytest`.
