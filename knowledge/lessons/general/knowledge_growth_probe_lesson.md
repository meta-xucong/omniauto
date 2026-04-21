---
title: Knowledge growth probe lesson
kind: lesson
domain: general
status: observed
maturity: medium
last_updated: 2026-04-21T01:52:47
tags:
  - knowledge
  - probe
  - lesson
evidence:
  - workflows/verification/general/knowledge_growth_probe.py
  - runtime/knowledge_runs/2026-04-21/20260421_015247_knowledge_growth_probe/task_run.json
approval_required: true
---
# Knowledge growth probe lesson

## Summary

If a task already knows a reusable conclusion during execution, it should emit a structured observation instead of relying on a post-hoc human reminder.

## Evidence Updates

### Run `20260421_015247_knowledge_growth_probe`

- Source task: `knowledge_growth_probe`
- Entry point: `cli.run`
- Related script: `workflows/verification/general/knowledge_growth_probe.py`
- Trigger: verification_probe
- Evidence:
  - `workflows/verification/general/knowledge_growth_probe.py`
  - `runtime/knowledge_runs/2026-04-21/20260421_015247_knowledge_growth_probe/task_run.json`

If a task already knows a reusable conclusion during execution, it should emit a structured observation instead of relying on a post-hoc human reminder.

### Run `20260421_030557_knowledge_growth_probe`

- Source task: `knowledge_growth_probe`
- Entry point: `cli.run`
- Related script: `workflows/verification/general/knowledge_growth_probe.py`
- Trigger: verification_probe
- Evidence:
  - `workflows/verification/general/knowledge_growth_probe.py`
  - `runtime/knowledge_runs/2026-04-21/20260421_030557_knowledge_growth_probe/task_run.json`

If a task already knows a reusable conclusion during execution, it should emit a structured observation instead of relying on a post-hoc human reminder.

