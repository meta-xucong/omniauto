# Low-Disturbance Risk Flow

## Purpose

Keep automation successful with the fewest possible site-visible actions.

This pattern is the canonical knowledge-layer home for the low-disturbance strategy previously documented in the repo.

## When To Use It

1. Marketplace or sensitive-site collection tasks
2. Login-adjacent flows where retries increase risk
3. Tasks where partial deliverables are better than aggressive probing

## Default Strategy

1. Reuse a stable profile and warm up once.
2. Prefer list-page collection over deep navigation.
3. Keep retries and page hops low.
4. Stop early at login, captcha, punish, or identity boundaries.
5. Preserve artifacts and handoff metadata immediately.
6. Resume only after the user clears the boundary.
7. Emit a partial report if useful structured data already exists.

## What The System May Auto-Recover

1. Cookie banners
2. Agreement checkboxes
3. Low-risk popups
4. Focus loss
5. Benign close, later, skip, or got-it dialogs

## What The System Must Not Auto-Solve

1. Slider challenges
2. Punish pages
3. Captcha or identity verification
4. Login verification boundaries
5. Security-sensitive site checks

## Evidence

- Related task:
  - `../tasks/marketplaces/1688_research_family.md`
- Related platform work:
  - `../tasks/platform/browser_recovery_and_manual_handoff_upgrade.md`
- Related implementation docs:
- `../../platform/docs/recovery_architecture.md`

## Why It Matters

This pattern keeps the project aligned with its philosophy:

- AI manages flow and context
- the runtime executes deterministic steps
- the system does not burn trust by improvising at risk boundaries
