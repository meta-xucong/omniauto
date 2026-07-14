# Customer Image Independent Module Trigger Audit

## Scope

This change keeps customer-visible reply ownership unchanged. Normal customer-facing wording remains owned by `customer_service_brain`; the scheduler only captures evidence, selects the session batch, and forwards the image proxy to the existing Brain pipeline. See `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`.

## Runtime Contract

1. `customer_image_turn_router.customer_image_capture_trigger` is a metadata-only gate. It does not call OCR, clipboard APIs, WeChat actions, or an LLM.
2. The scheduler calls the existing image module only when the gate sees an image signal, an image preview, or a recent image bubble. Normal text does not enter the image module.
3. Passive visual capture remains responsible for archiving both customer-side and self-side image bubbles when an image trigger exists.
4. A fresh customer image asset becomes a Brain-safe text proxy and is admitted through an explicitly authorized scheduler capture batch. The existing Brain image router still performs image understanding, catalog alignment, and reply planning.
5. Stable visual identity is used for ordinary de-duplication. A new pending image signal takes precedence over an old stable visual identity, so a newly received identical image can be processed once.
6. The session ledger preserves `pending_signal_id` on visual messages and maintains `processed_visual_pending_signal_ids`; this is the durable state used by the next scheduler poll.
7. If the same pending image signal is observed again after its image has already been archived, the scheduler consumes the signal without invoking context-menu copy again.

## Failure Prevented

Previously, a successful passive crop followed by `visual_image_already_seen` left the image batch empty. The scheduler then entered the legacy context-menu copy path on every poll, while the resulting image proxy was excluded from the normal reply batch. The new state transition separates `not requested`, `fresh image ready`, and `already-seen signal consumed` outcomes.

## Audit Checks

- Normal text does not call `capture_visual_images`.
- Image signals call the independent image module without requiring preview text.
- Historical image identity does not suppress a new pending image signal.
- A consumed visual signal survives the capture-to-ledger boundary and prevents a second module invocation after restart or the next poll.
- A customer image proxy is filtered by default and accepted only by an authorized image capture batch.
- Existing Brain, product master, guard, polish, session isolation, and RPA send paths remain unchanged.
