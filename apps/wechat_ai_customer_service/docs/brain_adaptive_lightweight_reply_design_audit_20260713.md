# Brain Adaptive Lightweight Reply Design Audit

> **Status (2026-07-13): supporting audit for an archived design reserve. No implementation, enablement, configuration change, or runtime behavior change is authorized at this time.**

## Scope

Audited document: [brain_adaptive_lightweight_reply_plan_and_audit_20260713.md](brain_adaptive_lightweight_reply_plan_and_audit_20260713.md).

Required baselines:

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

Audited code context:

- `workflows/customer_service_brain.py`
- `workflows/customer_service_quality_reviewer.py`
- `workflows/listen_and_reply.py`

This is a design audit only. No runtime reply, scheduler, RPA, voice, vision, or external-contract code was changed.

## Evidence Reviewed

1. The current short-social helper only skips a preflight; it does not select the reply execution profile.
2. The current low-authority fast profile is an internal prompt-budget profile with a 40-character and one-message bound.
3. The observed self-test was excluded from that profile because the regression marker created a 45-character, two-message batch.
4. The observed short reply spent 12.5941 seconds in the main Brain call and 11.5434 seconds in a repair call, while final visible polish was already local and took 0.0005 seconds.
5. Current Brain First ownership permits only Brain or Brain-repair wording to become customer-visible.
6. Existing semantic review is configured as `suspicious_only`; any adaptive mode must not silently make suspicious or hard-boundary turns sendable.

## Findings And Resolutions

| Severity | Finding | Resolution Required In Design |
| --- | --- | --- |
| P1 | A compact model cannot be the sole authority for declaring a turn safe. | Retain independent structural validation, authority/evidence checks, guard, local final verification, freshness, and target confirmation. Any failure routes to full Brain or hard block. |
| P1 | A permissive or malformed internal route object could accidentally authorize sending. | Use a closed private schema; unknown route, missing fields, mixed route/plan content, oversized output, parse error, or timeout always routes to full Brain. |
| P1 | Silent model downgrade for the lightweight path could weaken safety. | New profile uses the currently approved Brain model unless a separately configured, tenant-scoped fast model has passed the same acceptance suite. |
| P1 | Global behavior changes would break unknown external consumers. | New setting is additive, default-off, and tenant-scoped. Existing `low_authority_fast_profile` behavior remains unchanged when the new setting is absent. |
| P1 | A local fallback would violate Brain First. | Compact output is a BrainPlan only. It may not use templates, guard text, reviewer text, RAG, or legacy local synthesis. |
| P2 | Short text can be a continuation of a business request. | Active business state, delay-follow-up, unresolved references, media, and session uncertainty exclude single-pass completion; uncertain cases use full Brain. |
| P2 | The existing audit overwrites the first quality failure after repair. | Preserve an additive `initial_quality_snapshot` before repair; do not reinterpret existing `quality_verification`. |
| P2 | A test marker distorted short-turn eligibility in the live regression. | Treat synthetic markers as test-only observability metadata. Production customer content must never be stripped or made eligible because it resembles a marker. |
| P2 | Candidate complex turns can pay an extra compact call before full Brain. | Restrict invocation using neutral resource/surface bounds, measure fallback rate, and keep the feature tenant-scoped until same-provider live samples show a net gain. This is accepted because safety and correct routing take priority over worst-case latency. |
| P3 | New audit keys could be consumed by unknown tooling. | Add optional nested keys only, retain all current fields and meanings, and add contract tests for absent/new-key readers. |

## Boundary Audit

### Reply Ownership

Pass, conditional on implementation retaining the compact response as a normalized BrainPlan and never exposing the private route object as customer text. A compact `full_brain_required` outcome must be non-visible.

### Authority And Safety

Pass, conditional on compact mode carrying no product/formal evidence and delegating every authority-bound or uncertain turn. The model declaration is advisory until independent hard checks pass.

### Context And Session Isolation

Pass, conditional on preserving the existing target state, freshness, and RPA target-confirmation paths. The adaptive helper must neither own session state nor modify scheduler dispatch.

### Optional Plugin Isolation

Pass. The proposed helper is a core Brain-internal pure module. It must not import concrete voice or vision implementations. Media presence is consumed only through existing compatibility context fields.

### Compatibility

Pass, conditional on the additive default-off setting, no public signature changes, no state migration, and characterization tests at existing import paths. The plan correctly avoids modifying `listen_and_reply` call signatures.

### Observability

Pass with mandatory work. Initial reviewer/quality outcome, selected route, fallback reason, and per-stage durations must be retained without including hidden prompts, secrets, or additional customer-visible content.

## Audit Conclusion

The design is approved for implementation planning with no unresolved critical blocker. It is safe to proceed only when every P1 control is implemented and tested first. The implementation must remain default-off for external consumers, must fail closed to the unchanged full Brain path, and must preserve Brain-only visible reply ownership.

The design does not promise universal latency reduction. It targets a measurable one-LLM happy path for Brain-recognized low-risk social turns while intentionally accepting a bounded extra decision call for ambiguous candidate turns rather than risking an under-informed reply.
