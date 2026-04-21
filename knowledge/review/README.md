# Review Layer

This directory stores AI-generated knowledge candidates that are intentionally isolated from the formal knowledge layer.

## Rules

1. Files here are review-only candidates.
2. They may inform future human review, but they are not formal `knowledge/patterns/`, `knowledge/lessons/`, or `knowledge/capabilities/` entries.
3. Automatic candidate generation must never write directly into `skills/` or `platform/`.

## Structure

- `ai_candidates/patterns/<domain>/`
- `ai_candidates/lessons/<domain>/`
- `ai_candidates/capabilities/<domain>/`

Use `knowledge/index/ai_candidate_queue.md` as the first navigation entry before opening candidate bodies.
