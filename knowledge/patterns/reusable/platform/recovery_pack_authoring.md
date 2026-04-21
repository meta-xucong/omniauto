# Recovery Pack Authoring

## Purpose

Turn common browser interruptions into reusable low-risk assets without weakening the deterministic runtime model.

## When To Use It

1. A blocker is common enough to justify reuse.
2. The blocker is recognizable from a compact snapshot.
3. The recovery action is low-risk and explainable.

## Core Steps

1. Reproduce the interruption and capture its visible signals.
2. Decide whether it is global, product-specific, or too risky for auto-recovery.
3. Encode it as a narrow recovery rule.
4. Keep the action plan inside the whitelist.
5. Add focused tests for matching and execution behavior.

## Preferred Action Types

1. `check_text`
2. `click_text`
3. `click_selector`
4. `press_key`
5. `wait`

## Evidence

- Related platform task:
  - `../tasks/platform/browser_recovery_and_manual_handoff_upgrade.md`
- Related docs:
- `../../platform/docs/recovery_authoring.md`
- `../../platform/docs/recovery_architecture.md`

## Boundaries

1. Do not use recovery packs for destructive or ambiguous decisions.
2. If a new rule needs a new action type, treat that as an architecture change.
