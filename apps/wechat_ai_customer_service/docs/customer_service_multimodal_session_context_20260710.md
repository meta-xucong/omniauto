# WeChat AI Customer Service Unified Multimodal Session Context

Date: 2026-07-10

Related baseline: [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)

## Correction Audit

The live defects belong to the code mechanism layer, not to customer-visible reply wording:

- Text from both sides is usually captured, but group peer identity can remain `unknown` and one display name can be split across session keys when conversation-type metadata drifts.
- WeChat voice transcription can succeed through the right-click menu, but the normalized transcript and its provenance are not reliably retained when the follow-up OCR message already exists.
- Images from both sides are archived, but image-understanding output is held inside the current planner event and is not written back to the durable session ledger.
- Self-side media must enrich context but must never become a customer reply trigger.

This change therefore extends the existing capture -> scheduler -> session ledger -> Brain path. It does not add a competing reply engine, and it does not authorize product facts or customer-visible wording.

## Goals

1. Represent text, voice transcript, and image semantics with one durable message envelope.
2. Record both customer-side and self-side messages in chronological session context.
3. Keep reply eligibility separate from context retention: only fresh customer messages may enqueue Brain reply work.
4. Preserve voice and image provenance so an operator can audit what the Brain actually received later.
5. Run image understanding outside foreground RPA capture so the WeChat interaction path is not blocked by model latency.
6. Preserve duplicate-name and cross-session safety checks.

## Unified Message Envelope

Every ledger message keeps the existing identifiers and adds only optional compatible fields:

```json
{
  "sender": "customer|self|assistant|unknown",
  "sender_role": "customer|group_member|self|assistant|unknown",
  "type": "text|image",
  "modality": "text|voice|image",
  "source_type": "ocr_text|voice_transcription|visual_capture|assistant_reply",
  "content": "normalized visible text",
  "quality_flags": [],
  "voice_transcription_text": "",
  "voice_transcribed": false,
  "voice_transcribed_at": "",
  "image_understanding": {
    "vision_summary": "",
    "classification": {},
    "entities": {},
    "intent_hints": {},
    "bridge": {},
    "catalog_alignment": {},
    "source_messages": [],
    "reason": ""
  }
}
```

Compatibility rules:

- Existing `sender`, `type`, `content`, message ids, visual ids, asset ids, and file paths are not renamed.
- Optional fields are sanitized and size-limited before ledger persistence.
- OCR speaker labels remain metadata (`speaker_name` / `group_member_name`) and are never concatenated into customer content.
- In a group, a left-side peer bubble is customer input with `sender_role=group_member`; lack of a detected speaker name does not turn genuine peer content into `unknown`.

## Text Flow

1. OCR classifies the visual side independently from message wording.
2. Right/self bubbles are recorded as `sender=self` and never enter the reply batch.
3. Left peer bubbles are recorded as `sender=customer`; private chat uses `sender_role=customer`, group chat uses `sender_role=group_member`.
4. All messages enter `recent_messages`; only `message_is_reply_input_candidate` can place a fresh customer message into the Brain batch.
5. For a unique visible display name, an inferred `private/unknown` key may reuse the existing stable session key instead of opening a second context ledger. Ambiguous duplicate display names remain blocked and are never merged.

## Voice Flow

1. The existing right-click `语音转文字` RPA remains the only transcription action for both sides.
2. Follow-up OCR messages returned by the sidecar are normalized as `modality=voice`, `source_type=voice_transcription`.
3. If the same OCR message is already present in the capture payload, merge provenance into that existing message instead of dropping the transcription metadata as a duplicate.
4. Persist compact transcript records in `history_backfill.voice_transcription.transcribed_messages` for audit.
5. Store customer and self transcripts in the session ledger; only customer transcripts are reply eligible.
6. Duration/button UI text is never treated as a transcript.

## Image Flow

1. Visual capture continues to archive both customer and self image bubbles with side, bounds, occurrence id, asset id, and saved path.
2. Customer images keep the existing customer-image router and Brain bridge. Their understanding result is extracted from the planner event and written back to the source image message in the session ledger.
3. Self-only images create a lightweight context-enrichment task in the existing scheduler runtime. The task calls the same image-understanding provider, writes semantics to the same ledger, and cannot create a reply, polish task, ready reply, or send action.
4. Image understanding remains asynchronous and never runs inside the foreground RPA capture function.
5. Image semantics use the dedicated `image_understanding` variable. Brain context summaries may include its compact `vision_summary`, but it never becomes authority for stock, price, condition, policy, or commitments.
6. Customer and self images are analyzed separately so a self-side historical image cannot be mistaken for the customer image that triggered the current reply.

## Persistence And Recovery

- `capture_recorded` remains the immutable capture audit event.
- `multimodal_context_enriched` is appended after voice/image semantics are available.
- Enrichment updates matching recent messages by canonical id, source message id, visual occurrence id, asset id, or saved path.
- Pending self-image context tasks are stored in scheduler state. A process restart can requeue an unfinished task without replaying any customer reply.
- A failed context-only image task remains auditable and may be retried within a bounded count; it never blocks normal text/voice reply work.

## Brain First Boundary

- `customer_service_brain` remains the sole author of customer-visible replies.
- This change only improves capture facts, modality provenance, session continuity, and Brain context.
- The image model describes visible content and supplies non-authoritative intent/entity hints only.
- Product master and formal knowledge retain their existing authority.
- Guard, final polish, freshness, target confirmation, and no-cross-send checks remain unchanged.
- No local fallback reply or media-specific customer wording is introduced.

## Media Candidate Guard Review

The 2026-07-10 live test exposed two separate mechanisms, not one Brain defect:

- The text turn reached Brain and produced an adoptable reply at `21:29:19`; the listener was manually stopped at `21:29:29` while its polish task was still running, so no send was reached. This is an interrupted lifecycle, not an empty Brain result.
- The image turn entered the old unconditional voice preflight before `get_messages`. OCR duration matching could mistake a number inside an image for a voice bubble and trigger the right-click flow. The image capture then lost its normal path when WeChat was hidden in the tray.

The corrected contract is:

1. The scheduler reads the pending media signal before any voice RPA action.
2. `image_capture` and other non-voice media signals skip voice RPA and continue to the image/message capture path.
3. `voice_capture` and ordinary text polling retain the existing right-click transcription behavior, including self-side voice messages.
4. Before a right-click is allowed, a duration-like OCR item must sit on a visually plausible grey incoming or green self voice bubble. Numbers detected in a photo or other textured region are rejected before any mouse action.
5. Once a voice bubble passes this guard, the existing single right-click menu action remains authoritative; this is a candidate gate, not a second transcription implementation.

This preserves both-side voice recording while preventing image OCR from becoming a voice action. It also keeps the Brain First ownership boundary unchanged; see [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md).

## Code Changes

- `admin_backend/services/customer_service_session_ledger.py`
  - Preserve multimodal envelope fields.
  - Add bounded semantic enrichment and context-summary rendering.
- `adapters/wechat_win32_ocr_sidecar.py`
  - Normalize group peer identity while retaining speaker metadata.
  - Reject numeric OCR inside photo-like regions before voice right-click actions.
- `workflows/listen_and_reply.py`
  - Skip the voice preflight for image/non-voice media signals without changing the voice path.
- `admin_backend/services/session_monitor.py`
  - Reuse a unique existing session identity when inferred type metadata drifts; preserve duplicate-name blocking.
- `admin_backend/services/customer_service_scheduler.py`
  - Merge voice provenance into existing OCR messages.
  - Persist transcript audit bodies.
  - Extract customer image semantics from planner results.
  - Run self-image context-only enrichment asynchronously.
- `admin_backend/services/customer_service_scheduler_state.py`
  - Persist bounded context-only media tasks and enrichment state.
- Focused tests
  - Verify both-side text identity and ledger context.
  - Verify voice duplicate merge keeps transcript provenance for both sides.
  - Verify customer image planner semantics and self-only image semantics reach the same ledger.
  - Verify self media cannot enqueue or send a reply.
  - Verify unique-name session drift is repaired while duplicate names remain isolated.

## Acceptance Criteria

- Both-side text is correctly classified and retained in one session context.
- Both-side voice bubbles are right-click transcribed; normalized transcript text and provenance are retained.
- Both-side image files and image-understanding semantics are retained under dedicated variables.
- Customer image semantics are available to Brain and durable after the planner turn.
- Self media enriches context without triggering a customer-visible reply.
- A unique conversation does not split merely because inferred conversation type changes.
- Duplicate-name chats remain fail-closed and cannot cross-send.
- Brain First static audit, scheduler tests, Win32/OCR compatibility tests, image tests, compilation, and diff checks pass.
- Image signals do not invoke voice RPA; genuine incoming and self voice bubbles remain actionable.
