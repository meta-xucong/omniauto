# Run Modes

Use `scripts/run-solver.ps1` as the default entry point.

By default, the wrapper performs a meaningful-only `closeout_task(...)` after each run. Low-value short failures are skipped; meaningful runs can land in `runtime/knowledge_runs/` and refresh the task record under `knowledge/`.

## Common Modes

### Single Attempt

Run one game and stop when that game naturally ends:

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/minesweeper-autoplay/scripts/run-solver.ps1 -Mode single
```

Use when:

- the user asks for one verification round
- the goal is to inspect one full game from start to finish
- the user wants the process to stop after a single result

### Retry With Limit

Run up to a fixed number of games:

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/minesweeper-autoplay/scripts/run-solver.ps1 -Mode retry -MaxAttempts 3
```

Use when:

- the user asks for several retries
- you want more than one sample without unbounded looping

### Stop On First Loss

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/minesweeper-autoplay/scripts/run-solver.ps1 -Mode retry -MaxAttempts 5 -StopOnLoss
```

Use when:

- the user wants "stop on first failure"
- a regression check should end immediately on loss

### Until Success

```powershell
powershell -ExecutionPolicy Bypass -File .agents/skills/minesweeper-autoplay/scripts/run-solver.ps1 -Mode until_success -MaxAttempts 0 -MaxRepeatFailureSeconds 0
```

Use when:

- the user explicitly wants continuous retries until a win
- there is no attempt cap and no failure-time cap

## Direct Python Entry

The wrapper script ultimately calls:

```powershell
D:\AI\AI_RPA\.venv\Scripts\python.exe D:\AI\AI_RPA\workflows\temporary\desktop\minesweeper_solver.py ...
```

Direct Python execution is acceptable when:

- debugging CLI parsing
- testing a new run-mode parameter
- reproducing a wrapper-script issue

## Notes

- `MaxAttempts <= 0` means "no limit" where the mode supports it.
- `MaxRepeatFailureSeconds <= 0` means "no failure-time limit".
- `single` mode ignores attempt-count semantics and always means one game.
- Add `-SkipCloseout` only when you intentionally want to debug the wrapper or solver entry without producing knowledge closeout output.
