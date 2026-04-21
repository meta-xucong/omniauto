# Local JSON To Excel Report

## Purpose

Convert structured local task output into a spreadsheet deliverable that users can inspect or open with WPS.

## When To Use It

1. A browser or collection task already produced structured JSON.
2. The user needs a sortable, readable tabular deliverable.
3. The transformation can be done locally without reopening the source website.

## Core Steps

1. Treat `report_data.json` as the canonical intermediate data.
2. Normalize fields and compute the columns the user cares about.
3. Write an `.xlsx` output or equivalent spreadsheet artifact.
4. Keep the spreadsheet next to the source report bundle.

## Evidence

- Related task:
  - `../tasks/marketplaces/single_rocking_chair_local_excel_report.md`
- Related test:
- `../../platform/tests/unit/test_local_excel_report_generation.py`

## Boundaries

1. This pattern is strongest for structured tabular output.
2. It should not be confused with arbitrary GUI authoring inside WPS.
