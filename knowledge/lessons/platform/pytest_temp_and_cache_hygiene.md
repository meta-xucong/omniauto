# Pytest Temp And Cache Hygiene

## Lesson

On Windows, pytest temporary directories and cache directories can become long-lived permission traps. Keep them inside a controlled project path instead of relying on broken global temp state.

## Why It Matters

A damaged `%TEMP%\\pytest-of-*` tree or a broken root `.pytest_cache` can keep warning at the end of every test run even when the test suite itself passes.

## Recommended Handling

1. Set pytest `--basetemp` to a project-owned directory.
2. Set `cache_dir` to a project-owned directory.
3. Prefer `runtime/test_artifacts/pytest-tmp` and `runtime/test_artifacts/.pytest_cache` over root-level or user-temp defaults.
4. If historical Windows temp directories are already broken, treat them as cleanup work rather than as a reason to keep noisy warnings.

## Evidence

- Related config:
  - `../../pyproject.toml`
- Related task:
  - `../tasks/platform/repository_knowledge_restructure.md`
