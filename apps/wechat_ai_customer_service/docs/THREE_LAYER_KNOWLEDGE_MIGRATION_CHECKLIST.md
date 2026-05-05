# Three-Layer Knowledge Migration Checklist

> 2026-05-05 更新：本清单中的 `data/shared_knowledge` 迁移项现在只代表 legacy 本地数据留存。新链路以云端 `shared_library` 为正式共享公共知识库，并由客户端拉取只读快照。

## Before Migration

- Confirm the current tenant ID. Default: `default`.
- Make sure no live listener process is running.
- Keep `data/knowledge_bases/` as source/fallback until verification passes.

## Migration Output

Expected paths:

- `data/shared_knowledge/registry.json`
- `data/shared_knowledge/global_guidelines/schema.json`
- `data/shared_knowledge/global_guidelines/resolver.json`
- `data/shared_knowledge/global_guidelines/items/customer_service_style_guidelines.json`
- `data/tenants/default/tenant.json`
- `data/tenants/default/knowledge_bases/registry.json`
- `data/tenants/default/knowledge_bases/products/items/`
- `data/tenants/default/knowledge_bases/policies/items/`
- `data/tenants/default/knowledge_bases/chats/items/`
- `data/tenants/default/product_item_knowledge/<product_id>/faq|rules|explanations/`

## Initial Product-Scoped Moves

The migration script should classify these existing examples as product-scoped:

- `policies/items/door-lock-installation.json` -> `product_item_knowledge/fl-920/rules/door-lock-installation.json`
- `policies/items/after-sales-ap88-noise.json` -> `product_item_knowledge/ap-88/rules/after-sales-ap88-noise.json`
- `policies/items/after-sales-mt160-compensation.json` -> `product_item_knowledge/office_chair_oc_300/rules/after-sales-mt160-compensation.json` only if no better `mt-160` product exists; otherwise keep tenant-wide and mark for manual review.

## Acceptance Criteria

- Runtime reads the tenant root by default.
- Admin edits the tenant root by default.
- Shared global guidelines appear as style examples, not policy facts.
- Product-scoped rules only appear when the related product is matched or active in context.
- Existing customer-service regressions still pass.
- Live File Transfer Assistant test passes or is blocked only by external WeChat availability.
