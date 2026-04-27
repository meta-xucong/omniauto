# Diagnostics

Use this order when the 1688 report flow does not finish as expected.

## 1. Verify Session / Browser State

Check:

- `run_status.json`
- current Chrome profile path
- whether CDP attach was used

Typical symptoms:

- cannot attach to browser
- login state not reused
- search page redirects to login immediately

## 2. Verification / Manual Handoff

Check:

- `manual_handoff.json`
- `manual_browser_launch.json`
- `browser_artifacts/manual_handoff.png`

Meaning:

- the run reached a real human verification boundary
- the correct next step is user handoff, not captcha bypass
- after the user finishes verification, rerun the wrapper with the same `-TaskSlug`
- manual verification does not automatically resume the workflow on its own

## 3. List Extraction Problems

Check:

- `report_data.json`
- `all_items`
- `list_pages_completed`

Typical symptoms:

- too few items
- wrong page count
- empty shop names or unstable links

## 4. Detail Sampling Problems

Check:

- `detail_sample_target`
- `detail_sample_completed`
- `items`
- `detail_*.png`

Typical symptoms:

- report has list table only
- detail cards missing
- screenshots missing
- detail cards show `detail_error`
- if detail data exists but screenshot capture fails, treat it as a screenshot-path reliability issue first, not as proof that the detail extraction itself failed

## 5. Report Rendering Problems

Check:

- `report_data.json`
- `report.html`
- current template `platform/src/omniauto/templates/reports/ecom_report.html.j2`

Typical symptoms:

- report text says sorted but table is actually capture-order
- parameter block wastes too much space
- screenshot thumbnails are too small or not interactive
- HTML contains data but layout is poor
