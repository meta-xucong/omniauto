# Guarded Knowledge Closeout

This is a user-approved governance skill for OmniAuto's knowledge closeout system.

- Runtime skill bundle: `.agents/skills/guarded-knowledge-closeout/`
- Scope: automatic closeout rules, observation hygiene, manual closeout fallback, and strict review-only AI candidates
- Hard rule: this skill governs promotion boundaries, but does not allow automatic writes into `skills/` or `platform/`

Use this skill when changing:
- `platform/src/omniauto/knowledge/`
- `knowledge/` closeout structure
- `omni closeout`
- AI-assisted candidate generation rules
