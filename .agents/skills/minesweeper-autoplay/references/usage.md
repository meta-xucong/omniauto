# Usage Examples

Use these examples when invoking the `minesweeper-autoplay` skill from conversation or when running the wrapper script directly.

## 1. Single Game Verification

User-facing invocation:

```text
使用 minesweeper-autoplay skill，跑一局 single 模式，直到自然胜负后停下，并总结结果。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode single
```

Default behavior:

- The wrapper will automatically close out the run into `runtime/knowledge_runs/` and refresh the corresponding `knowledge/tasks/...` record after the game ends.
- This closeout is meaningful-only. Short low-value failures are skipped instead of being written into formal OmniAuto knowledge.

## 2. Multi-Game Regression

User-facing invocation:

```text
使用 minesweeper-autoplay skill，跑 3 局 retry 模式，统计每局失败原因。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode retry -MaxAttempts 3
```

## 3. Stop On First Loss

User-facing invocation:

```text
使用 minesweeper-autoplay skill，跑最多 5 局，但一旦踩雷失败就立刻停止并复盘。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode retry -MaxAttempts 5 -StopOnLoss
```

## 4. Retry Until Success

User-facing invocation:

```text
使用 minesweeper-autoplay skill，持续重试直到通关，不限制局数。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode until_success -MaxAttempts 0 -MaxRepeatFailureSeconds 0
```

## 5. Time-Limited Long Test

User-facing invocation:

```text
使用 minesweeper-autoplay skill，持续重试，但连续失败超过 10 分钟就停下并总结。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode until_success -MaxAttempts 0 -MaxRepeatFailureSeconds 600
```

## 6. Preview The Final Command

User-facing invocation:

```text
使用 minesweeper-autoplay skill，先只输出本次将执行的命令，不要真正启动求解器。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode single -Preview
```

## 6b. Debug Without Knowledge Closeout

Use this only when checking wrapper behavior itself.

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode single -SkipCloseout
```

## 7. Limit Single-Game Step Count

User-facing invocation:

```text
使用 minesweeper-autoplay skill，跑一局，但把单局最大步数限制到 2000。
```

Direct command:

```powershell
powershell -ExecutionPolicy Bypass -File D:\AI\AI_RPA\.agents\skills\minesweeper-autoplay\scripts\run-solver.ps1 -Mode single -SingleAttemptSteps 2000
```

## 8. Diagnose Latest Artifacts Without New Run

User-facing invocation:

```text
使用 minesweeper-autoplay skill，只分析最新失败产物，不启动新测试。
```

In this mode, inspect:

- `D:\AI\AI_RPA\runtime\test_artifacts\verification\minesweeper\solver_stop_summary.txt`
- `D:\AI\AI_RPA\runtime\test_artifacts\verification\minesweeper\cell_action_diagnostics.txt`
- latest `attempt_*_step_*_consensus_01.png`
- latest terminal `*_lost_*.png` or `*_lost_guess_*.png`

## Recommended Invocation Pattern

When speaking to the AI, prefer this format:

```text
使用 minesweeper-autoplay skill，<目标>，<运行模式>，<停止条件>，<是否需要复盘>。
```

Examples:

- `使用 minesweeper-autoplay skill，跑一局 single 模式并复盘。`
- `使用 minesweeper-autoplay skill，继续优化识图后做 3 局回归。`
- `使用 minesweeper-autoplay skill，长测直到成功或失败，并给出停止摘要。`
- `使用 minesweeper-autoplay skill，只分析最新失败产物，不启动新测试。`
