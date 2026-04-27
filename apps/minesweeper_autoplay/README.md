# Minesweeper Autoplay App

This app package is the formal home for the OmniAuto Windows Minesweeper autoplay workflow.

Use this package for:

- Minesweeper solver code.
- Runner scripts.
- Closeout helpers.
- Run configuration.
- Offline checks.
- Task-specific documentation.

The historical solver at `workflows/temporary/desktop/minesweeper_solver.py` remains available for compatibility, but new development should prefer this app package.

## Main Entrypoints

```powershell
powershell -ExecutionPolicy Bypass -File apps/minesweeper_autoplay/scripts/run-solver.ps1 -Mode single
```

Preview without launching Minesweeper:

```powershell
powershell -ExecutionPolicy Bypass -File apps/minesweeper_autoplay/scripts/run-solver.ps1 -Mode single -Preview
```

