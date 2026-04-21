# Runtime Layer

This directory is the mutable runtime layer of the project.

It groups outputs and evidence that change as tasks run:

1. runtime data
2. formal task outputs
3. test and debugging artifacts

## Internal Structure

```text
runtime/
├─ data/
├─ outputs/
└─ test_artifacts/
```

Unlike `platform/`, this layer is expected to change constantly as the project runs.

## What Lives Here

- `runtime/data/`
  - auth state
  - browser profiles
  - logs
  - reports
- `runtime/outputs/`
  - direct task outputs and generated result files
- `runtime/test_artifacts/`
  - screenshots, probe state, pytest cache and logs, verification traces, debugging leftovers
