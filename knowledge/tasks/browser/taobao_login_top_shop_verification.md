# Taobao Login And Top-Shop Verification

## Summary

- Status: verification asset
- Domain: browser verification
- Why it mattered: it proved that sensitive-site flows can combine deterministic steps with human-assisted login and still preserve enough context to continue

## Primary Assets

- Verification script:
  - `../../../../workflows/verification/browser/taobao_login_top_shop.py`
- Config example:
  - `../../../../workflows/verification/browser/taobao_search_shop_config.example.json`
- Artifact directory:
- `../../../../runtime/test_artifacts/verification/browser/taobao_login_top_shop/`
- Related browser engine:
- `../../../../platform/src/omniauto/engines/browser.py`

## What Was Proven

1. Persistent browser profiles can reuse Taobao login state when available.
2. When login state is missing, the flow can intentionally pause for SMS-code completion instead of failing blindly.
3. After login, the task can continue deterministically into keyword search and shop entry.
4. Task-specific choices can stay in config instead of being improvised at runtime.

## Reusable Takeaways

1. Sensitive-site verification flows should be deterministic around the risky boundary, not "AI figures it out live."
2. Handoff metadata, status files, and waiting screenshots should be written as first-class outputs.
3. Search and selection logic should stay explicit and configurable.

## Promoted Knowledge

- Related pattern:
- `../../patterns/reusable/browser/manual_handoff_and_resume.md`
- Related capabilities:
- `../../capabilities/observed/current_capability_map.md`

## Boundaries

1. This verifies assisted continuation, not automatic bypass of login or security challenges.
2. It is a strong verification asset for one flow family, not yet a blanket promise for all Taobao tasks.
