# Artifacts

Main artifact root:

- `../../../runtime/test_artifacts/verification/minesweeper/`
- Knowledge closeout root: `../../../runtime/knowledge_runs/`

## Key Files

### `solver_stop_summary.txt`

Primary stop summary for the latest run.

Read first when a run ended on its own.

Key fields:

- `reason`
- `attempt`
- `elapsed_seconds`
- `run_mode`
- `configured_max_attempts`
- `configured_stop_on_loss`
- `configured_repeat_failure_seconds`
- `last_actions`

### `cell_action_diagnostics.txt`

Focused click/visual diagnostics.

Useful for:

- wrong target
- no effect
- blocked variants
- visual-open sync clues

### `attempt_*_step_*_consensus_01.png`

Per-step board snapshots after read-board consensus.

Use these to reconstruct what the solver believed the board looked like.

### `attempt_*_step_*_pre_guess_consensus_01.png`

Board snapshots captured just before the solver moves toward guessing.

Use these when deciding whether a guess was premature.

### `attempt_*_lost_*.png` and `attempt_*_lost_guess_*.png`

Terminal loss frames.

Use these to judge whether the final failure came from:

- direct misread
- wrong click
- true late-game ambiguity

### `*.out.log` and `*.err.log`

Process logs for a concrete run.

Use when:

- the solver exited unexpectedly
- stop behavior seems inconsistent with the requested run mode

### `runtime/knowledge_runs/<date>/<run_id>/`

Automatic closeout records written by the wrapper after a meaningful solver run finishes.

Use when:

- checking whether the skill run actually produced a knowledge closeout
- verifying which `final_state` and note were sent into OmniAuto knowledge
- reviewing any AI-candidate sidecar output referenced by the closeout summary

## Practical Review Order

1. `solver_stop_summary.txt`
2. latest `*_err.log`
3. latest terminal failure image
4. nearest `step_*_consensus_01.png`
5. `cell_action_diagnostics.txt`
