---
name: minesweeper-autoplay
description: 运行、长测、诊断和优化 Windows 扫雷自动游玩流程。用于用户要求自动打开扫雷、自动玩、跑单局或多局测试、监控长测、分析失败截图、排查识图/几何/点击/策略问题、或继续迭代 `apps/minesweeper_autoplay/workflows/minesweeper_solver.py` 时。
---

# Minesweeper Autoplay

## Core Assets

- App package: `../../../apps/minesweeper_autoplay/`
- Main solver: `../../../apps/minesweeper_autoplay/workflows/minesweeper_solver.py`
- Runtime artifacts: `../../../runtime/apps/minesweeper_autoplay/test_artifacts/`
- Knowledge closeout runs: `../../../runtime/knowledge_runs/`
- Runner script: `../../../apps/minesweeper_autoplay/scripts/run-solver.ps1`
- Formal project entry: `../../../skills/task_skills/minesweeper_autoplay/README.md`

## Standard Workflow

1. Confirm the requested run mode.
   - `single`: 单局跑到自然胜负或单局结束即停
   - `retry`: 最多跑 N 局
   - `until_success`: 持续重试直到成功，或直到额外限制命中
2. Start the solver with `apps/minesweeper_autoplay/scripts/run-solver.ps1` unless there is a good reason to call the Python entry directly.
   - Automatic knowledge closeout is meaningful-only by default. Normal low-value short failures are skipped; successful, long-running, or boundary-signaling runs are closed out automatically.
3. Monitor runtime artifacts instead of guessing what happened.
4. Classify failures before editing code:
   - recognition / geometry / click targeting
   - strategy / pending rules / guessing quality
   - run-control / retry-policy / stop-policy mismatch
5. When changing the solver, patch `../../../apps/minesweeper_autoplay/workflows/minesweeper_solver.py`, run `py_compile`, then rerun a targeted smoke test before longer tests.
6. Keep the historical temporary solver path only for compatibility; new work belongs in the app package unless the user explicitly asks for platformization.

## Run Commands

Use the wrapper script for normal operation:

```powershell
powershell -ExecutionPolicy Bypass -File apps/minesweeper_autoplay/scripts/run-solver.ps1 -Mode single
```

Read `references/run-modes.md` for the supported parameter combinations.
Read `references/usage.md` for common user-facing invocation patterns.

## Diagnostic Order

1. Read `../../../runtime/apps/minesweeper_autoplay/test_artifacts/solver_stop_summary.txt` when present.
2. Inspect the latest `attempt_*_step_*_consensus_01.png` and terminal failure screenshots.
3. Check `cell_action_diagnostics.txt` for `no_effect`, `blocked`, `wrong_target`, or visual-sync clues.
4. Decide whether the issue is:
   - board reading / classification
   - click placement / geometry drift
   - rule scheduling / safe moves not exhausted
   - late-game guess quality
   - run mode / stop condition mismatch

Read `references/diagnostics.md` and `references/artifacts.md` when diagnosing non-trivial failures.

## Boundaries

- This skill formalizes the task family; it does not by itself promote code into `platform/src/omniauto/skills/`.
- Formal platformization requires separate user approval.
- Keep human-readable catalog updates in `../../../skills/` aligned with runtime bundle updates in `.agents/skills/`.

## References

- `references/run-modes.md`
- `references/usage.md`
- `references/diagnostics.md`
- `references/artifacts.md`
