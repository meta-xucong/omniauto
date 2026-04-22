# Skill Upgrade Policy

This repository uses a soft-upgrade / hard-landing model.

## Soft Upgrades

The system may automatically improve its memory layer by updating:

1. `knowledge/tasks/`
2. `knowledge/patterns/`
3. `knowledge/lessons/`
4. `knowledge/capabilities/`
5. `knowledge/proposals/`

## Hard Landings

The system must **not** create or modify formal project-local skills unless the user explicitly asks for it.

That means:

1. no automatic promotion into `skills/task_skills/`
2. no automatic promotion into `skills/capability_skills/`
3. proposals may be generated, but formal skills require user approval

## Why This Exists

This keeps the project from confusing:

1. a useful past task
2. a reusable pattern
3. a formally supported skill

Only the third case belongs in `skills/`.

## Operational Guide

For the concrete repository workflow that turns mature task knowledge into an OmniAuto formal skill, follow:

- [OMNIAUTO_SKILL_UPGRADE_GUIDE.md](OMNIAUTO_SKILL_UPGRADE_GUIDE.md)
