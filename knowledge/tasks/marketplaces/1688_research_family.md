# 1688 Research Family

## Summary

- Status: active task family with reusable patterns
- Domain: marketplace research
- Why it mattered: this is the strongest body of evidence for real-world browser collection, low-disturbance behavior, and partial-report delivery under risk constraints

## Primary Assets

- Workflow scripts:
  - `../../../../workflows/generated/marketplaces/1688_cat_litter_50.py`
  - `../../../../workflows/generated/marketplaces/1688_nvzhuang_5.py`
  - `../../../../workflows/generated/marketplaces/1688_nvzhuang_5_retry.py`
  - `../../../../workflows/generated/marketplaces/1688_single_rocking_chair_5.py`
  - `../../../../workflows/generated/marketplaces/1688_tire_255_5.py`
  - `../../../../workflows/generated/marketplaces/1688_women_clothing_5.py`
- Report directories:
- `../../../../runtime/data/reports/1688_cat_litter_50/`
- `../../../../runtime/data/reports/1688_cat_tree_50/`
- `../../../../runtime/data/reports/1688_cat_tree_v2/`
- `../../../../runtime/data/reports/1688_nvzhuang_5/`
- `../../../../runtime/data/reports/1688_nvzhuang_5_retry/`
- `../../../../runtime/data/reports/1688_phone_case_v2/`
- `../../../../runtime/data/reports/1688_single_rocking_chair_5/`
- `../../../../runtime/data/reports/1688_tire_255_5/`
- `../../../../runtime/data/reports/1688_tire_research/`
- `../../../../runtime/data/reports/1688_tire_suv_50/`
- `../../../../runtime/data/reports/1688_tire_suv_research/`
- `../../../../runtime/data/reports/1688_tire_v2/`
- `../../../../runtime/data/reports/1688_women_clothing_5/`

## What Was Proven

1. The project can execute real 1688 search-and-collect workflows with deterministic scripts.
2. The safest successful path is list-page-first collection with very limited detail enrichment.
3. Marketplace tasks can still deliver useful partial reports when verification or punish pages interrupt enrichment.
4. Report directories can act as self-contained task evidence bundles with `report_data.json`, screenshots, run status, and handoff metadata.

## Reusable Takeaways

1. Reuse a persistent profile and stop early at login, captcha, punish, or identity boundaries.
2. Prefer low-disturbance browsing: fewer retries, fewer page hops, and minimal detail-page sampling.
3. Treat `report_data.json` plus screenshots as the minimum durable deliverable even if enrichment cannot finish.
4. Store handoff and resume evidence next to the report so the task can continue without context loss.

## Promoted Knowledge

- Related patterns:
- `../../patterns/reusable/marketplaces/low_disturbance_risk_flow.md`
- `../../patterns/reusable/browser/manual_handoff_and_resume.md`
- Related capabilities:
- `../../capabilities/observed/current_capability_map.md`

## Boundaries

1. These flows do not attempt to bypass verification challenges.
2. Current success is strongest on constrained collection tasks, not on arbitrary deep browsing.
3. Some report directories are historical variants without a surviving generated script sibling, so the report folder itself is part of the evidence.
