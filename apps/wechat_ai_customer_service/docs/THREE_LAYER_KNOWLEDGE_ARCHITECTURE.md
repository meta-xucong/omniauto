# WeChat AI Customer Service Three-Layer Knowledge Architecture

## Goal

The WeChat AI customer-service app must support multiple customer tenants while still allowing shared assistant knowledge to improve over time. Knowledge is separated by ownership and applicability so the runtime can load only the useful slice for each reply.

## Three Layers

### 1. Shared Global Assistant Knowledge

Path: `apps/wechat_ai_customer_service/data/shared_knowledge/`

Ownership: platform/operator maintained.

Scope: reusable by every WeChat AI customer-service tenant.

Typical content:

- General customer-service tone and safety guidelines.
- Small-talk pivots that are not tied to one company or product.
- Generic boundary principles such as "do not invent price, stock, logistics, or policy facts".

Runtime behavior:

- Used as compact style and safety context.
- Must not contain tenant facts, product prices, stock, company bank accounts, invoices, or customer-specific promises.
- Some global guidelines may be marked `always_include=true` when they are short and broadly useful.

### 2. Tenant-Wide Knowledge

Path: `apps/wechat_ai_customer_service/data/tenants/<tenant_id>/knowledge_bases/`

Ownership: each customer tenant.

Scope: applies to the tenant as a whole, regardless of product.

Typical content:

- Company profile, invoice policy, payment policy, logistics policy.
- Tenant-specific common after-sales, sample, contract, and manual-handoff rules.
- Tenant-specific chat templates and reply style examples.
- ERP import records for this tenant.

Runtime behavior:

- Loaded only for the active tenant.
- Can override or enrich shared global behavior, but cannot mutate global knowledge.
- Customer-admin UI edits this layer by default.

### 3. Product-Scoped Detailed Knowledge

Path: `apps/wechat_ai_customer_service/data/tenants/<tenant_id>/product_item_knowledge/<product_id>/`

Ownership: each customer tenant.

Scope: applies only after a specific product is matched or is already active in conversation context.

Subdirectories:

- `faq/`: product-specific Q&A.
- `rules/`: product-specific policies, risks, handoff rules, pricing boundaries, service limits.
- `explanations/`: product-specific explanations, usage notes, parameter clarifications.

Runtime behavior:

- Not globally searched as tenant policy.
- Loaded only when the customer message matches the product, or conversation context already points to the product.
- Product-scoped rules can still trigger handoff and block auto-reply.

## Why This Structure

This prevents three common failure modes:

- Global pollution: one customer's "包邮" or "售后" rule should not leak into another tenant.
- Tenant pollution: one product's special installation or compensation rule should not affect unrelated products.
- Token waste: runtime should not load every rule for every message; it should load shared compact guidance, tenant-wide candidates, and only matched product detail.

## Default Tenant

Until real multi-tenant management exists, the current test/demo customer uses:

`tenant_id = default`

The legacy root `data/knowledge_bases/` remains as migration source and fallback, but new writes and runtime reads should use:

`data/tenants/default/knowledge_bases/`

## Knowledge Placement Rules

- Put reusable customer-service principles in `shared_knowledge/global_guidelines`.
- Put tenant company-wide policies in `tenants/<tenant_id>/knowledge_bases/policies`.
- Put tenant company-wide chat templates in `tenants/<tenant_id>/knowledge_bases/chats`.
- Put product master records in `tenants/<tenant_id>/knowledge_bases/products/items`.
- Put product-only policy or explanation under `product_item_knowledge/<product_id>/`.

## Matching Rules

Runtime matching order:

1. Detect intent tags from the customer message.
2. Search shared global guidance and tenant-wide categories.
3. Match products by name, alias, SKU, or conversation context.
4. Load product-scoped `faq`, `rules`, and `explanations` for matched product IDs.
5. Build an evidence pack.
6. Let deterministic rules answer when sufficient; let DeepSeek reason only inside evidence boundaries.

## Admin Rules

The normal customer-facing admin console edits tenant-wide knowledge by default. Shared global knowledge is developer/operator maintained. Product-scoped `product_faq`, `product_rules`, and `product_explanations` are exposed as virtual admin categories; saving an item in those categories writes it into `product_item_knowledge/<product_id>/<faq|rules|explanations>/` instead of mixing it into tenant-wide policies.
