# Legacy Agent Browser Tasks

## Summary

- Status: historical reference
- Domain: browser task generation
- Why it mattered: these files preserve the earliest prompt-to-script experiments and their outputs, which still help explain how the project evolved

## Primary Assets

- Archived scripts:
  - `../../../../workflows/archive/google_search_kimi_agent.py`
  - `../../../../workflows/archive/hacker_news_top5_to_excel_agent.py`
  - `../../../../workflows/archive/queue_agent.py`
  - `../../../../workflows/archive/scheduled_tasks_agent.py`
- Temporary browser prototypes:
  - `../../../../workflows/temporary/browser/agent__.py`
  - `../../../../workflows/temporary/browser/agent_有哪些步骤.py`
  - `../../../../workflows/temporary/browser/agent_查看队列.py`
  - `../../../../workflows/temporary/browser/agent_查看队列_fix_wait.py`
- Legacy outputs:
  - `../../../../runtime/outputs/google_ai_news.json`
  - `../../../../runtime/outputs/google_ai_news_debug.png`
  - `../../../../runtime/outputs/x_openai_posts.json`
  - `../../../../runtime/outputs/x_openai_debug.png`
  - `../../../../runtime/outputs/1688_nvzhuang_debug.png`

## What Was Proven

1. The project already had an end-to-end idea of "prompt -> generated browser task -> output artifact."
2. Some early agent outputs were intentionally simple or incomplete, which is useful historical context.
3. The repository keeps both archived scripts and temporary prototypes to preserve the path from experimentation to current structure.

## Reusable Takeaways

1. Treat archived or temporary agent scripts as lineage evidence, not as the current best implementation style.
2. Preserve debug outputs when they help explain why a generated script was later replaced or archived.
3. When a generated task becomes important, it should graduate into clearer task records, patterns, tests, or templates.

## Promoted Knowledge

- Related capability:
  - `../../capabilities/observed/current_capability_map.md`
- Related task:
  - `../platform/repository_knowledge_restructure.md`

## Boundaries

1. These artifacts are useful for orientation but should not be presented as polished examples.
2. Some filenames reflect older naming or generation behavior and are preserved for history.
