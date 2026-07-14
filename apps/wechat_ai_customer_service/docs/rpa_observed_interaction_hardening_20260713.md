# RPA Observed Interaction Hardening (2026-07-13)

This document follows [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md) and [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md).

## Objective

Reduce unsafe RPA interaction patterns without changing customer-visible reply ownership, Brain behavior, public connector contracts, configuration keys, plugin contracts, or voice/image optional-module boundaries.

The change explicitly does **not** introduce a new send-rate throttle.  It uses two execution rules instead:

1. A click is allowed only after current-screen evidence identifies the exact interaction surface.
2. Once a surface is verified, a bounded per-send random rhythm and point selection avoids a fixed, repeated action trace.

## Scope

Internal Win32/OCR adapter changes only:

- Add a pure `interaction_evidence` helper under `adapters/wechat_win32_ocr/`.
- Require current input-region evidence and make one bounded random input click; remove geometry-only fallback click attempts.
- Require current OCR evidence for the sidebar search field and re-verify search focus before clear/paste keyboard actions.
- Add an audited, bounded random interaction-rhythm profile to existing humanized input settings.

No voice implementation imports image code, no image implementation imports voice code, and neither optional plugin owns RPA scheduling or customer-visible replies.

## Compatibility

Existing public functions, import paths, configuration keys, return keys, and event names remain available.  The only observability additions are optional fields such as `input_click_evidence`, `input_click`, `search_box_evidence`, and `interaction_rhythm` inside existing diagnostic payloads.

When evidence is absent, the adapter returns a normal existing-style failure payload and performs no click, no keyboard input, and no retry against guessed coordinates.  The scheduler/Brain retains its existing ownership of handoff and reply decisions.

## Verification

The implementation must prove:

- an input state without fresh bounds causes zero input clicks;
- search OCR absence causes zero search clicks and zero keystrokes;
- verified interaction points stay inside evidence bounds while varying across runs;
- existing Brain First, external-contract, plugin-isolation, Win32/OCR, scheduler, and simulation checks remain green.
