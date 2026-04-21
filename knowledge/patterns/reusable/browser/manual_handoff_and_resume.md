# Manual Handoff And Resume

## Purpose

Preserve forward progress when a task hits a boundary that should be cleared by a human instead of by runtime automation.

## When To Use It

1. SMS-code login
2. Captcha or punish pages
3. High-trust checkpoints where the workflow should pause instead of guessing

## Core Steps

1. Detect the boundary explicitly.
2. Stop the active workflow in place.
3. Write handoff metadata, status, and screenshots.
4. Preserve the current browser profile and task context.
5. Poll or wait for the user to clear the boundary.
6. Resume from the current workflow state instead of restarting from scratch.

## Evidence

- Related tasks:
  - `../tasks/browser/taobao_login_top_shop_verification.md`
  - `../tasks/marketplaces/1688_research_family.md`
  - `../tasks/platform/browser_recovery_and_manual_handoff_upgrade.md`
- Related tests:
- `../../platform/tests/integration/test_browser_handoff_and_ai_recovery.py`

## Boundaries

1. Handoff is for explicit boundaries, not for every minor hiccup.
2. The resume path should preserve determinism; it should not become a runtime AI free-for-all.

## Promotion Notes

- This pattern is a candidate upstream source for future skills and templates.
