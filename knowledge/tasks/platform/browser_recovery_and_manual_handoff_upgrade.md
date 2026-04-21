# Browser Recovery And Manual Handoff Upgrade

## Summary

- Status: capability-building
- Domain: platform
- Why it mattered: this initiative upgraded the runtime from strict deterministic failure into constrained recovery plus explicit manual handoff

## Primary Assets

- Recovery code:
- `../../../../platform/src/omniauto/recovery/models.py`
- `../../../../platform/src/omniauto/recovery/policy.py`
- `../../../../platform/src/omniauto/recovery/registry.py`
- `../../../../platform/src/omniauto/recovery/fallback.py`
- `../../../../platform/src/omniauto/recovery/manager.py`
- Integration points:
- `../../../../platform/src/omniauto/engines/browser.py`
- `../../../../platform/src/omniauto/core/state_machine.py`
- Tests:
- `../../../../platform/tests/integration/test_browser_recovery.py`
- `../../../../platform/tests/integration/test_browser_handoff_and_ai_recovery.py`
- `../../../../platform/tests/unit/test_recovery_registry.py`
- `../../../../platform/tests/unit/test_workflow_recovery.py`
- Supporting docs:
- `../../../../platform/docs/recovery_architecture.md`
- `../../../../platform/docs/recovery_authoring.md`

## What Was Proven

1. Common browser interruptions can be detected and cleared through rule-based recovery packs.
2. The runtime can stop cleanly at higher-risk boundaries and persist enough context for a human to continue.
3. Recovery behavior can stay deterministic and whitelisted instead of turning into free-form runtime AI.

## Reusable Takeaways

1. Add small, explainable recovery rules before expanding global runtime behavior.
2. Treat manual handoff as a first-class path, not as an ad hoc exception.
3. Record recovery events and artifacts so later debugging stays cheap.

## Promoted Knowledge

- Related patterns:
- `../../patterns/reusable/browser/manual_handoff_and_resume.md`
- `../../patterns/reusable/platform/recovery_pack_authoring.md`
- `../../patterns/reusable/marketplaces/low_disturbance_risk_flow.md`
- Related capabilities:
- `../../capabilities/observed/current_capability_map.md`

## Boundaries

1. The runtime still does not permit arbitrary AI-driven UI improvisation.
2. Verification, punish, and security-sensitive pages remain escalation boundaries.
