# Artifact Map

For a run launched with `-TaskSlug foo`, the main output directory is:

- `runtime/data/reports/1688_foo/`

## Primary Files

- `run_status.json`
  - final run state
  - workflow outputs
  - stopped reason when present
- `report_data.json`
  - structured report payload
  - full list items
  - detail sample items
- `report.html`
  - final human-readable report
- `manual_handoff.json`
  - present when the workflow stops for human verification
- `manual_browser_launch.json`
  - present when ordinary Chrome handoff has been launched

## Screenshots

- `detail_001.png`, `detail_002.png`, ...
  - captured detail-page screenshots for sampled items
- `browser_artifacts/`
  - browser-level screenshots and recovery artifacts
  - includes `manual_handoff.png` when verification blocks progress

## Generated Workflow

The wrapper itself is generated under:

- `runtime/generated_workflows/marketplaces/1688_<slug>.py`

This generated workflow should usually be treated as a runtime artifact, not as a hand-maintained project asset.
