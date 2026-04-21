# Final Repository Refactor Blueprint

## Status

- Type: implementation blueprint
- Scope: repository information architecture and path migration
- Approval model:
  - soft upgrades: automatic
  - hard landings into `skills/` or `platform/`: user-approved only

## Design Goal

Refactor the repository so that:

1. infrastructure is grouped under `platform/` instead of being spread at the root;
2. runtime artifacts are grouped under `runtime/`;
3. temporary tasks are isolated from reusable and historical workflow assets;
4. the repository keeps a memory layer that can evolve automatically from task evidence;
5. only the user can approve promotion into formal `skills/` or deeper `platform/` hardening.

## Core Promotion Model

### Automatic soft upgrades

These upgrades are allowed to happen as tasks complete:

1. task records in `knowledge/tasks/`
2. reusable patterns in `knowledge/patterns/`
3. durable lessons in `knowledge/lessons/`
4. observed and candidate capability notes in `knowledge/capabilities/`
5. skill or platform proposal files in `knowledge/proposals/`
6. index updates that improve retrieval for humans and AI

### Manual hard landings

These upgrades must only happen after an explicit user instruction:

1. promotion into `skills/`
2. promotion into `platform/src/`
3. promotion into `platform/tests/` as a formal stability guarantee

## Target Repository Shape

```text
AI_RPA/
├─ README.md
├─ START_HERE.md
├─ PROJECT_STRUCTURE.md
├─ pyproject.toml
├─ uv.lock
├─ .agents/
├─ platform/
│  ├─ README.md
│  ├─ src/
│  ├─ tests/
│  ├─ tools/
│  └─ docs/
├─ workflows/
│  ├─ temporary/
│  ├─ generated/
│  ├─ verification/
│  ├─ examples/
│  └─ archive/
├─ knowledge/
│  ├─ tasks/
│  ├─ patterns/
│  │  ├─ emerging/
│  │  └─ reusable/
│  ├─ lessons/
│  ├─ capabilities/
│  │  ├─ observed/
│  │  └─ candidate/
│  ├─ proposals/
│  │  ├─ skill_candidates/
│  │  └─ platform_candidates/
│  ├─ index/
│  └─ _templates/
├─ skills/
│  ├─ task_skills/
│  ├─ capability_skills/
│  ├─ SKILL_CATALOG.md
│  └─ UPGRADE_POLICY.md
└─ runtime/
   ├─ data/
   ├─ outputs/
   └─ test_artifacts/
```

## Chapter Plan

### Chapter 1: Governance and skeleton

Create the final scaffolding without moving core code yet.

Deliverables:

1. `platform/README.md`
2. `runtime/README.md`
3. `workflows/temporary/` with subfolders
4. `skills/task_skills/`, `skills/capability_skills/`, `skills/SKILL_CATALOG.md`, `skills/UPGRADE_POLICY.md`
5. `knowledge/patterns/emerging/`, `knowledge/patterns/reusable/`
6. `knowledge/capabilities/observed/`, `knowledge/capabilities/candidate/`
7. `knowledge/proposals/skill_candidates/`, `knowledge/proposals/platform_candidates/`
8. updated repository governance docs explaining soft vs hard upgrades

Validation gate:

1. Markdown link and path check passes.
2. New directories exist exactly where expected.

### Chapter 2: Platform migration

Move stable infrastructure into `platform/`.

Deliverables:

1. `src/` -> `platform/src/`
2. `tests/` -> `platform/tests/`
3. `tools/` -> `platform/tools/`
4. technical docs -> `platform/docs/`
5. packaging and test config updated for new paths
6. all known documentation and knowledge references updated

Validation gate:

1. Markdown link and path check passes.
2. `python -m pytest --collect-only -q` succeeds.
3. package import paths resolve under the new layout.

### Chapter 3: Runtime migration

Move mutable data and artifact roots into `runtime/`.

Deliverables:

1. `data/` -> `runtime/data/`
2. `outputs/` -> `runtime/outputs/`
3. `test_artifacts/` -> `runtime/test_artifacts/`
4. code, templates, tests, and workflow scripts updated for new paths
5. pytest cache and temp settings updated to `runtime/test_artifacts/`

Validation gate:

1. Markdown link and path check passes.
2. targeted path audit shows no expected production references to the old roots.
3. `python -m pytest --collect-only -q` succeeds.

### Chapter 4: Workflow and knowledge promotion flow

Separate temporary tasks from retained workflows and finalize the soft-upgrade information model.

Deliverables:

1. move clear one-off scripts into `workflows/temporary/`
2. update workflow docs to explain `temporary` vs `generated` vs `verification`
3. move current reusable patterns into `knowledge/patterns/reusable/`
4. move current capability documents into `knowledge/capabilities/observed/`
5. create proposal stubs and indexes for future manual promotions
6. update start and structure docs to reflect the final flow

Validation gate:

1. Markdown link and path check passes.
2. knowledge registry and catalogs point to the new locations.
3. `python -m pytest --collect-only -q` succeeds.

### Chapter 5: Full regression

Run the full suite only after all chapters finish.

Validation gate:

1. full `pytest -q` passes.
2. final repository path audit and `git status` review are cleanly explainable.

## Non-Goals

1. Do not package prior task families into formal skills in this refactor.
2. Do not silently promote task-derived behavior into `platform/src/` just because it appears reusable.
3. Do not erase historical evidence or artifacts that still matter for project memory.

## Expected Outcome

After this refactor:

1. humans can quickly tell what is infrastructure, what is runtime data, what is temporary work, and what is memory;
2. AI can learn from task history automatically through `knowledge/`;
3. future formalization into `skills/` or `platform/` stays deliberate and user-approved.
