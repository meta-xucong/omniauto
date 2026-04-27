# WeChat AI Customer Service

This application package contains the task-specific implementation for the OmniAuto-based WeChat AI customer-service workflow.

The current stable prototype still lives under:

```text
workflows/temporary/desktop/wechat_customer_service/
```

During the migration, this package becomes the permanent home for:

- customer-service workflows;
- WeChat adapters and sidecars;
- task-specific configs;
- structured business data;
- raw data inboxes;
- review-only AI candidates;
- offline regression scenarios;
- task-specific operation docs.

OmniAuto platform code should only receive reusable infrastructure. WeChat business data, customer-service prompts, test contacts, product knowledge, and operator policies belong here.

For safe live smoke tests, prefer `configs/file_transfer_smoke.example.json`. It targets only `文件传输助手`, enables product knowledge, keeps LLM advisory disabled, and writes state/audit artifacts under `runtime/apps/wechat_ai_customer_service/`.

## Local Knowledge Admin

Start the local Web admin console:

```powershell
uv run python -m apps.wechat_ai_customer_service.admin_backend.app
```

Default URL:

```text
http://127.0.0.1:8765
```

The admin console is local-first. It can view formal knowledge, create drafts, validate and apply changes with version snapshots, upload raw materials, generate review candidates, apply or reject candidates, run diagnostics, and inspect runtime status.

## Directory Guide

```text
configs/                 Runtime configs for dry-run, test-contact, and later production profiles.
workflows/               Executable task workflows.
adapters/                Thin WeChat-specific adapters over OmniAuto infrastructure.
prompts/                 Persona, reply policy, handoff policy, and evidence-pack templates.
data/structured/         Reviewed business data used by the workflow.
data/raw_inbox/          Raw chats, product sheets, policy files, and ERP exports awaiting extraction.
data/review_candidates/  AI-generated candidates awaiting human review.
tests/scenarios/         Offline customer-service regression scenarios.
docs/                    Task-specific operation and debugging notes.
```

## Planning Docs

- `docs/KNOWLEDGE_ADMIN_REQUIREMENTS.md`: 知识管理台需求文档。
- `docs/KNOWLEDGE_ADMIN_DEVELOPMENT_GUIDE.md`: 知识管理台开发文档。
- `docs/KNOWLEDGE_ADMIN_CODE_ROADMAP.md`: 知识管理台代码落地清单。

## Migration Rule

Keep the old temporary workflow runnable until the new application entry points pass their own dry-run and offline regression checks.
