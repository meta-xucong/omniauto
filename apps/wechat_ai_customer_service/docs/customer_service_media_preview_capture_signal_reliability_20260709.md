# Customer Service Media Preview Capture Signal Reliability - 2026-07-09

Reference baseline: `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`.

## Scope

This note covers a code-mechanism-layer reliability fix for WeChat session-list media previews. It does not change Brain ownership of customer-visible replies and does not add local business reply wording.

## Problem

In live low-risk mode the session monitor required unread-badge evidence before dispatching a session to scheduler capture. When an operator opened a voice-only chat before the scheduler captured it, WeChat cleared the unread badge. The session-list preview and time changed, but the monitor treated that badge-cleared preview change as a passive baseline update. The result was a read-without-reply case: the voice session never reached capture, voice transcription, Brain planning, or sending.

## Design

- Treat media previews as capture-only signals when the preview changes even if the unread badge has already disappeared.
- Use explicit pending signal kinds: `voice_capture`, `image_capture`, and `media_capture`.
- Preserve preview text, preview time, unread badge, session key, and conversation type when bridging the monitor signal into scheduler state.
- Do not synthesize media preview text such as `[Voice]` or `[语音]` into Brain input. Media previews only trigger real chat-pane capture. Brain receives content only after the sidecar reads an actual transcript, image proxy, or normal customer message.
- Keep empty media captures pending for a bounded retry window so transient OCR/UI misses do not immediately lose the customer turn.

## Acceptance Checks

- Badge-cleared voice preview changes dispatch a capture signal.
- Scheduler state preserves `voice_capture` instead of downgrading it to normal text.
- Monitor-to-scheduler bridging carries preview metadata.
- Voice/media preview recovery does not create synthetic customer text for Brain.
