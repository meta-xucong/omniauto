# WPS Hard-Input Reliability Probes

## Summary

- Status: exploratory but operationally useful
- Domain: desktop automation
- Why it mattered: these probes explored where WPS automation stays reliable and where GUI-only input becomes brittle

## Primary Assets

- Example script:
  - `../../../../workflows/examples/desktop/wps_word_hardinput.py`
- Related desktop examples:
  - `../../../../workflows/examples/desktop/wps_word_visual.py`
  - `../../../../workflows/examples/desktop/wps_word_com.py`
  - `../../../../workflows/examples/desktop/wps_excel.py`
- Main artifacts:
- `../../../../runtime/test_artifacts/manual_wps/`
- `../../../../runtime/test_artifacts/legacy_root/`

## What Was Proven

1. Desktop and WPS automation needs artifact-heavy debugging because focus, window state, and input path matter.
2. Hard-input probes can surface real reliability boundaries that would not be obvious from source code alone.
3. Centralized artifact storage makes these investigations maintainable instead of letting screenshots and temp files scatter across the repo.

## Reusable Takeaways

1. Keep every WPS probe tied to a named artifact directory.
2. Prefer stable file-generation or native automation paths over brittle GUI-only formatting when possible.
3. Treat screenshot and temp-document evidence as part of the debugging record, not as noise.

## Promoted Knowledge

- Related lesson:
- `../../lessons/desktop/desktop_artifact_hygiene.md`
- Related capability:
- `../../capabilities/observed/current_capability_map.md`

## Boundaries

1. These probes do not yet imply that any arbitrary WPS editing workflow is stable.
2. Desktop input remains highly environment-sensitive compared with browser automation.
