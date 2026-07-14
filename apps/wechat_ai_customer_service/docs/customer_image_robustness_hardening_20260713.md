# Customer Image Robustness Hardening (2026-07-13)

> Scope: this change is limited to the independent vision/image-understanding domain. It must not alter Brain reply ownership, scheduler behavior, voice behavior, public field names, plugin protocol, or configuration contracts.

This hardening work follows [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md) and [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md).

## Goals

1. Fail closed when an explicit `customer_image_assets` payload contains a known self-authored image.
2. Keep normal WeChat-compressed images unchanged, but bound oversized or unusually large local visual analysis and provider payloads through in-memory normalization.
3. Preserve the existing `customer_image_*` input/output fields and route all visible reply authoring to `customer_service_brain`.
4. Strengthen image-module-only regression coverage for viewport variation and context-menu visual noise.

## Compatibility Rules

- Existing function names, signatures, payload keys, reason codes, and defaults remain valid.
- New diagnostics are additive and optional. Callers that do not read them behave unchanged.
- The asset guard rejects only assets explicitly marked as self/outbound. Legacy assets with no side metadata retain their existing compatibility behavior.
- Payload normalization occurs only inside the visual provider adapter. It does not change stored source images, message assets, prompt fields, or catalog facts.
- Voice modules, scheduler modules, Brain modules, and customer-visible wording are out of scope.

## Verification

- Existing image capture, image turn routing, image understanding, multimodal ledger, plugin isolation, and scheduler image checks.
- New checks cover explicit self-asset rejection, oversized image re-encoding, invalid image payload failure, and varied image-bubble layouts.
