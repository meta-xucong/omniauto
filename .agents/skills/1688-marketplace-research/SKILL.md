---
name: 1688-marketplace-research
description: 运行、诊断、补跑并生成 1688 关键词调研报告。用于按关键词抓取前 N 页、使用价格排序搜索、抽样详情页、生成完整 HTML 报告、在验证码出现时切到人工接管、以及复盘 1688 调研产物时。
---

# 1688 Marketplace Research

## Core Assets

- App package: `../../../apps/marketplace_1688_research/`
- Base workflow: `../../../apps/marketplace_1688_research/workflows/base_1688_research.py`
- Runtime runner: `../../../apps/marketplace_1688_research/scripts/run-report.ps1`
- Workflow builder: `../../../apps/marketplace_1688_research/workflows/build_1688_workflow.py`
- Meaningful-only closeout helper: `../../../apps/marketplace_1688_research/scripts/closeout_marketplace_run.py`
- Report template: `../../../platform/src/omniauto/templates/reports/ecom_report.html.j2`
- Manual handoff bar: `../../../platform/src/omniauto/recovery/manual_handoff_bar.py`
- Formal project entry: `../../../skills/task_skills/marketplace_1688_research/README.md`

## Standard Workflow

1. Confirm the requested keyword, page count, and whether a complete report should include detail sampling.
   - Default pages: `3`
   - Default detail samples: `27`
2. Prefer `apps/marketplace_1688_research/scripts/run-report.ps1` over hand-editing wrappers.
   - It generates a task-specific workflow under `runtime/apps/marketplace_1688_research/generated_workflows/marketplaces/`
   - It runs with the current dedicated 1688 Chrome profile through CDP attach
   - It performs meaningful-only knowledge closeout by default
3. Default assumptions:
   - no proxy unless the user explicitly asks for it
   - ordinary Chrome profile + CDP attach
   - 1688 search page uses price sorting
   - final report uses the current complete template:
     - stats cards
     - full list table
     - detail sample cards
     - compact parameter chips
     - clickable screenshot lightbox
4. If verification appears:
   - do not attempt to bypass or fake a human browser
   - let the workflow stop in manual handoff mode
   - keep the black-bottom prompt visible for the user
   - after the user completes verification manually, rerun `scripts/run-report.ps1` with the same `-TaskSlug` to continue from the preserved profile state
   - completing verification alone does not auto-resume the workflow
5. Diagnose from artifacts before editing code.
6. Reuse the app-local base workflow and template unless the user explicitly asks for platformization or a structural rewrite.
7. If detail-page screenshots fail but the page content is already present, prefer continuing the run and generating the report without that screenshot instead of treating it as a fatal error.

## Run Commands

Use the wrapper for normal operation:

```powershell
powershell -ExecutionPolicy Bypass -File apps/marketplace_1688_research/scripts/run-report.ps1 -Keyword 色谱柱 -Pages 3 -DetailSampleSize 27 -TaskSlug sepuzhu_3
```

Read `references/usage.md` for common invocation patterns.
Read `references/run-modes.md` for supported runner parameters.

## Diagnostic Order

1. Check `run_status.json` in the current report directory.
2. If the run stopped early, check:
   - `manual_handoff.json`
   - `manual_browser_launch.json`
   - `browser_artifacts/`
3. If the report looks incomplete, compare:
   - `report_data.json`
   - `report.html`
   - `detail_*.png`
4. Decide whether the issue is:
   - login / session / CDP attach
   - manual verification handoff
   - list extraction
   - detail sampling
   - report rendering / layout

## Boundaries

- This skill supports safer marketplace research and human handoff.
- It must not be used to evade site detection or defeat captcha challenges.
- Manual verification is allowed; captcha solving or stealth-evasion implementation is not.
- This skill formalizes the task family; it does not by itself move the implementation into `platform/src/omniauto/skills/`.

## References

- `references/usage.md`
- `references/run-modes.md`
- `references/artifacts.md`
- `references/diagnostics.md`
- `references/report-format.md`
