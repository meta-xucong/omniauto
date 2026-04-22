# Diagnostics

Classify failures before patching the solver.

## 1. Recognition / Board Reading

Typical symptoms:

- already-open empty cells are treated as hidden
- red `3` and flag states get confused
- right/bottom darker regions behave differently from central cells
- screenshots show the board is readable to a human, but internal decisions contradict it

Primary artifacts:

- `solver_stop_summary.txt`
- `cell_action_diagnostics.txt`
- `attempt_*_step_*_consensus_01.png`
- `attempt_*_step_*_pre_guess_consensus_01.png`

Common clues:

- `skip_visual_open_0`
- `late_visual_open_*`
- repeated `post_click_wrong_target`
- safe moves that obviously exist on the screenshot but are not executed

## 2. Geometry / Click Targeting

Typical symptoms:

- repeated `blocked` or `no_effect` on one cell
- clicks land near the intended cell but not on it
- edge or corner cells are less reliable

Primary artifacts:

- `cell_action_diagnostics.txt`
- `*_blocked_*.png`
- `*_no_effect_*.png`
- nearby `step_*_consensus_01.png`

Common clues:

- `post_click_wrong_target`
- `blocked_variant_*`
- repeated retries on the same coordinate with no board change

## 3. Strategy / Rule Scheduling

Typical symptoms:

- there are still deterministic safe opens or flags, but the solver pauses, reconfirms, or moves toward guessing too early
- `flags_pending` or `csp_flags_pending` repeats without enough downstream progress
- `pre_guess` still finds rules, but the solver trends toward guessing

Primary artifacts:

- `solver_stop_summary.txt`
- `attempt_*_step_*_consensus_01.png`
- `attempt_*_step_*_pre_guess_consensus_01.png`

Recent strategy terms to watch:

- `prioritized_flags`
- `subset_opens`
- `det_opens`
- `pre_guess_rules_found`
- `pre_guess_rules_resync`

## 4. Guess Quality

Typical symptoms:

- the board is genuinely ambiguous and the final loss occurs after healthy deterministic progress
- no obvious remaining deterministic moves are visible on the final board

Primary artifacts:

- `*_guess_*.png`
- `*_lost_guess_*.png`
- final `step_*_consensus_01.png`

This category usually points to probability / ranking improvements, not recognition fixes.

## 5. Run-Control / Policy Mismatch

Typical symptoms:

- the user asked for one game, but the solver retried multiple games
- the solver process exits while the Minesweeper window remains open
- the stop reason is policy-driven rather than game-driven

Primary artifacts:

- `solver_stop_summary.txt`
- stderr/stdout logs for that run

Check:

- `run_mode`
- `configured_max_attempts`
- `configured_stop_on_loss`
- `configured_repeat_failure_seconds`

Those fields are written into the stop summary by the current solver.
