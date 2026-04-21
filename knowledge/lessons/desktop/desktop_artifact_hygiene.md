# Desktop Artifact Hygiene

## Lesson

Desktop and visual-automation work becomes much easier to maintain when every screenshot, temp document, and debugging artifact is centralized and task-scoped.

## Why It Matters

Desktop investigations produce many more side effects than clean browser tests.
Without a stable artifact home, the repo turns noisy and future debugging loses context.

## Recommended Handling

1. Write raw investigation outputs to `runtime/test_artifacts/`.
2. Use task-scoped subdirectories such as `manual_wps/` or `verification/minesweeper/`.
3. Keep formal business outputs in `runtime/data/` or `runtime/outputs/`, not mixed into debugging directories.
4. Promote the lasting takeaway into `knowledge/` once the experiment is understood.

## Evidence

- Related tasks:
  - `../tasks/desktop/wps_hardinput_reliability_probes.md`
  - `../tasks/desktop/minesweeper_solver_exploration.md`
- Related artifact roots:
  - `../../runtime/test_artifacts/manual_wps/`
  - `../../runtime/test_artifacts/verification/minesweeper/`
