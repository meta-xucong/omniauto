# Current Capability Map

This file is the quickest human-readable view of what OmniAuto can currently do with evidence.

## Stable Or Emerging Capability Areas

### Browser Automation Core

- Deterministic browser workflows using `Workflow + AtomicStep`
- Playwright-backed browser execution through `StealthBrowser`
- Verification scripts for real-world browser flows
- Evidence:
  - `../tasks/browser/taobao_login_top_shop_verification.md`
  - `../../workflows/verification/browser/taobao_login_top_shop.py`
  - `../../platform/tests/integration/test_browser_engine.py`

### Marketplace Research And Report Collection

- Low-disturbance 1688 search and collection workflows
- Partial-deliverable-first strategy under login or risk boundaries
- Report outputs captured under `runtime/data/reports/`
- Evidence:
  - `../tasks/marketplaces/1688_research_family.md`
  - `../../workflows/generated/marketplaces/`
  - `../../runtime/data/reports/`

### Manual Handoff And Recovery

- Runtime interruption detection around browser actions
- Recovery registry and constrained fallback
- Manual handoff with resume after login or verification boundaries
- Evidence:
  - `../tasks/platform/browser_recovery_and_manual_handoff_upgrade.md`
  - `../../platform/src/omniauto/recovery/`
  - `../../platform/tests/integration/test_browser_handoff_and_ai_recovery.py`

### Local JSON To Excel Or WPS-Friendly Reporting

- Report data can be post-processed into tabular outputs
- The strongest proven path is local structured data to spreadsheet output
- Evidence:
  - `../tasks/marketplaces/single_rocking_chair_local_excel_report.md`
  - `../../runtime/data/reports/1688_single_rocking_chair_5/`
  - `../../platform/tests/unit/test_local_excel_report_generation.py`

### Desktop And WPS Automation

- WPS and desktop-focused probes exist and are documented
- Reliability differs by path: scripted native operations are stronger than brittle GUI-only editing
- Evidence:
  - `../tasks/desktop/wps_hardinput_reliability_probes.md`
  - `../../workflows/examples/desktop/`
  - `../../runtime/test_artifacts/manual_wps/`

### Visual Desktop Experimentation

- Complex visual-only tasks can be explored with artifact-heavy verification loops
- Current maturity is exploratory, not general-purpose
- Evidence:
  - `../tasks/desktop/minesweeper_solver_exploration.md`
  - `../../workflows/temporary/desktop/minesweeper_solver.py`
  - `../../runtime/test_artifacts/verification/minesweeper/`

### Agent Runtime And Generated Task Prototypes

- The system can generate simple browser task scripts from natural-language prompts
- Some early generated agents are historical prototypes and should be treated as legacy evidence, not current best practice
- Evidence:
  - `../tasks/browser/legacy_agent_browser_tasks.md`
  - `../../workflows/generated/browser/`
  - `../../workflows/archive/`

## Capability Interpretation Rules

- "Stable" means there is at least one runnable path plus either tests or repeated task evidence.
- "Emerging" means there is promising evidence but the boundary is still being shaped.
- "Exploratory" means useful task work exists, but the project should not promise broad repeatability yet.
