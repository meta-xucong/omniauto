# Knowledge Layer

This directory is the project's long-term memory layer.

It exists to answer four questions quickly:

1. What has this project already done?
2. Which outputs, scripts, and artifacts prove that work?
3. Which lessons are reusable across future tasks?
4. Which capabilities have been observed, inferred, or proposed?

## Soft Upgrade Contract

`knowledge/` is the automatic growth layer of the repository.

As tasks complete, the project may automatically:

1. add task records
2. extract reusable patterns
3. record durable lessons
4. update observed or candidate capability notes
5. prepare skill or platform proposals

## Hard-Landing Boundary

`knowledge/` is not the same as:

1. `skills/`
2. `platform/`

Promotion into those layers requires explicit user approval.

That gives the repository two distinct paths:

- soft upgrades:
  - `knowledge/`
- hard landings:
  - `skills/`
  - `platform/`

## Directory Map

- `tasks/`
  - One record per completed initiative or task family.
- `patterns/emerging/`
  - New patterns that are useful but not yet the default reusable shape, grouped by domain.
- `patterns/reusable/`
  - Patterns that have stabilized enough to recommend by default, without becoming skills, grouped by domain.
- `lessons/`
  - Long-lived pitfalls, maintenance notes, and operating guidance, grouped by domain.
- `capabilities/observed/`
  - Capability notes supported by evidence from tasks and artifacts, with domain subdirectories for detailed notes.
- `capabilities/candidate/`
  - Capability notes that may be worth future formalization.
- `proposals/skill_candidates/`
  - Potential future skills awaiting user approval, grouped by domain.
- `proposals/platform_candidates/`
  - Potential future platform hardenings awaiting user approval, grouped by domain.
- `review/ai_candidates/`
  - Strict AI-assisted review candidates, isolated from the formal knowledge layer until a human promotes or rewrites them.
- `index/`
  - Fast lookup tables for humans and AI.
- `_templates/`
  - Authoring templates for future closeout updates.

## What Goes Here vs. Elsewhere

- `knowledge/` stores structured memory and interpretation.
- `workflows/` stores executable task scripts.
- `platform/tests/` store automated regression coverage.
- `runtime/test_artifacts/` store raw test and debugging traces.
- `runtime/data/` and `runtime/outputs/` store business outputs and run outputs.
- `skills/` and `.agents/skills/` store approved AI-facing operating instructions.
