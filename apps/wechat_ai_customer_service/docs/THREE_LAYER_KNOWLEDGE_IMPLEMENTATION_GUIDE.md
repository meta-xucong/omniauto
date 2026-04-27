# Three-Layer Knowledge Implementation Guide

## Phase 1: Documents And State

Create architecture, implementation, and migration documents. Reset long-running task state to the current objective.

Verification:

- Documents exist.
- `.codex-longrun/state.json` validates.

## Phase 2: Directory Layout And Migration

Add a migration script that creates:

- `data/shared_knowledge/registry.json`
- `data/shared_knowledge/global_guidelines/`
- `data/tenants/default/tenant.json`
- `data/tenants/default/knowledge_bases/`
- `data/tenants/default/product_item_knowledge/<product_id>/faq|rules|explanations/`

Migration policy:

- Copy current `data/knowledge_bases/` into `data/tenants/default/knowledge_bases/`.
- Convert `chat_style_guidelines` into `shared_knowledge/global_guidelines/customer_service_style_guidelines.json`.
- Archive tenant-local `chat_style_guidelines` so it no longer behaves like a tenant chat template.
- Copy known product-specific policy items into product-scoped folders.
- Do not delete the legacy root in this phase.

Verification:

- Migration script is idempotent.
- JSON files parse as UTF-8.
- Product-scoped folders exist for known product-specific rules.

## Phase 3: Runtime Layering

Update runtime loaders so the default active tenant is:

`WECHAT_KNOWLEDGE_TENANT || "default"`

Runtime must read:

1. `shared_knowledge`
2. `tenants/<tenant_id>/knowledge_bases`
3. `tenants/<tenant_id>/product_item_knowledge`

The admin registry/store should default to the active tenant root. If the tenant root is absent, it can fall back to the legacy root.

Verification:

- Existing admin tests pass.
- Existing category runtime tests pass.
- New tests prove global guidelines and product-scoped entries are visible in evidence packs.

## Phase 4: Evidence And Compiler

Update `KnowledgeIndex`, `EvidenceResolver`, `knowledge_loader`, and compiler behavior:

- Product-scoped entries are searched only after product IDs are matched or present in conversation context.
- Product-scoped rules can trigger `requires_handoff`.
- Global guidelines are included as style examples and never treated as direct customer facts.
- Compatibility compiler includes enough product-scoped FAQ/rules for legacy direct matching and LLM evidence.

Verification:

- Product-specific installation/after-sales rules do not appear as tenant-wide policy noise.
- Matching the product loads its product-scoped rule.
- Unknown unrelated questions do not load unrelated product-scoped rules.

## Phase 5: Admin Compatibility

Keep the existing admin console stable:

- Category list edits tenant-wide knowledge.
- Existing product/policy/chat/ERP actions still work.
- Product-scoped categories appear as admin-visible virtual categories.
- Product-scoped item create/update/archive writes to the matched product folder using `data.product_id`.
- AI generator and candidate review may target `product_faq`, `product_rules`, or `product_explanations` when a rule only applies to one product.

Verification:

- `run_admin_backend_checks.py --chapter all` passes.
- No frontend syntax errors.

## Phase 6: Full Regression And Live Smoke

Run:

- Python compileall.
- JSON validation.
- Admin checks.
- Knowledge runtime checks.
- Compiler checks.
- Offline regression.
- Workflow logic checks.
- DeepSeek boundary probe when API is available.
- Preflight without WeChat.
- File Transfer Assistant live regression when WeChat is available.

Stop only when all automated tests pass and live smoke is either passed or explicitly blocked by unavailable WeChat UI/access.
