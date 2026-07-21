# WeChat Win32/OCR Sidecar Callable Contract v1

## 1. Boundary

The stable external boundary is the Sidecar CLI/daemon action payload. The
Python callables below are implementation hooks used by the connector and
tests. They remain backward compatible for existing in-repository callers,
but new integrations should use the action payload instead of importing them.

All parameters listed below are additive keyword-only parameters. Omitting
them preserves the behavior that existed before PR #28. Existing return types
and required fields remain unchanged; new diagnostic fields are additive.

## 2. Optional Parameters

| Callable | Additive parameter defaults | Default behavior |
| --- | --- | --- |
| `capture_message_history_snapshots` | `conversation_type=""`, `include_untranscribed_voice_placeholders=False` | Infer type when absent; omit untranscribed voice placeholders. |
| `capture_message_history_snapshots_until_anchor` | `include_untranscribed_voice_placeholders=False` | Keep the existing bounded anchor search and omit placeholders. |
| `consume_recent_target_switch_validation` | `ttl_seconds=None`, `minimum_cached_at=None`, `require_session_key_match=False` | Use configured TTL, no lower timestamp bound, and retain legacy target/title validation. |
| `dismiss_voice_transcribe_context_menu` | `artifact_dir=None`, `label="voice_transcribe_context_menu_dismissed"`, `menu_bounds=None` | Dismiss safely without requiring diagnostics or a known menu rectangle. |
| `messages_payload` | `confirm_target=""`, `confirm_exact=False`, `include_untranscribed_voice_placeholders=False` | Preserve the existing message read; no extra target confirmation and no placeholder emission. |
| `open_chat` | `session_key=""`, `conversation_type=""`, `force_session_row_resolution=False`, `semantic_target=""` | Preserve title-based opening; do not force a second row click. Type is mutable metadata, not physical identity. |
| `parse_messages_from_ocr` | `conversation_type=""`, `screenshot=None`, `include_untranscribed_voice_placeholders=False` | Infer type, allow parser-only tests, and omit untranscribed voice placeholders. |
| `validate_active_send_target` | `session_key=""`, `conversation_type=""`, `screenshot=None`, `ocr_items=None`, `screenshot_path=""` | Capture fresh evidence when no reusable same-frame evidence is supplied. |
| `voice_transcribe_payload` | `conversation_type=""`, `max_duration_seconds=240`, `confirm_target=""`, `confirm_exact=False` | Use the existing progress-bounded voice flow and skip an extra target assertion unless requested. |

## 3. Compatibility Rules

1. Positional parameters and existing required keyword parameters cannot be
   removed or reordered within contract v1.
2. Optional parameter defaults cannot change without a new contract version.
3. A supplied `conversation_type` may refine message semantics but cannot
   replace a confirmed physical `session_key`.
4. A reusable screenshot or OCR list is read-only evidence. Supplying it must
   not trigger an extra screenshot or UI action by itself.
5. The retired `image-save` and `image-clipboard-copy` actions are not part of
   this contract and must not be restored through compatibility wrappers.

## 4. Verification

- `run_wechat_win32_ocr_compat_checks.py` verifies the optional defaults and
  legacy invocation compatibility.
- `run_customer_service_external_contract_compat_checks.py` freezes callable
  signatures and exported symbols.
- `run_wechat_win32_ocr_window_action_planning_checks.py` verifies the window
  planning defaults independently of a live Windows desktop.
