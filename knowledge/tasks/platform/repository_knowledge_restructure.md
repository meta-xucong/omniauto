# Knowledge-Layer Introduction And Backfill

## Summary

- Status: completed
- Domain: platform
- Why it mattered: the repository needed a dedicated memory layer so future humans and AI could understand past work, current capabilities, and reusable guidance without scanning the whole tree

## Primary Assets

- New knowledge layer:
  - `../../README.md`
  - `../../index/task_catalog.md`
  - `../../index/capability_matrix.md`
  - `../../index/knowledge_registry.json`
- Updated entry docs:
  - `../../../../START_HERE.md`
  - `../../../../PROJECT_STRUCTURE.md`
- Updated support docs:
- `../../../../runtime/test_artifacts/README.md`
- `../../../../platform/tests/README.md`
  - `../../../../skills/README.md`
  - `../../../../scripts/README.md`

## What Was Proven

1. The repository can separate executable assets from long-term memory without moving core scripts or outputs out of place.
2. Prior work can be backfilled into structured task records and reusable patterns.
3. A machine-readable knowledge registry is practical alongside Markdown indexes.

## Reusable Takeaways

1. Future tasks should close out through the knowledge layer, not only through raw outputs and scattered docs.
2. Task records, patterns, lessons, and capability claims should stay distinct.
3. AI onboarding becomes faster when there is a stable reading order and a compact registry.

## Promoted Knowledge

- Related lesson:
- `../../lessons/platform/pytest_temp_and_cache_hygiene.md`
- Related capability:
- `../../capabilities/observed/current_capability_map.md`

## Boundaries

1. The knowledge layer is only useful if future task closeout keeps it current.
2. Raw outputs still belong in their original directories; `knowledge/` is the interpretation layer, not the artifact dump.
