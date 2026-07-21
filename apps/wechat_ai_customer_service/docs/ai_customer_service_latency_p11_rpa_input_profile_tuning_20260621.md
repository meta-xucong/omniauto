# P11 RPA Input Profile Tuning

Date: 2026-06-21

> Superseded clause (2026-07-19): this document remains historical latency evidence, but its requirement to force every live send through `clipboard_chunks` is no longer current. See [customer_service_wechat_account_behavior_risk_retrospective_20260719.md](customer_service_wechat_account_behavior_risk_retrospective_20260719.md). Live safety now preserves an explicitly selected existing input method and keeps the same target, focus, confirmation, trigger, and post-send guards.

Current development also follows:

- [customer_visible_reply_ownership_baseline.md](customer_visible_reply_ownership_baseline.md)
- [customer_service_external_contract_and_optional_plugin_baseline.md](customer_service_external_contract_and_optional_plugin_baseline.md)

## Goal

P11 continues the latency optimization work after P9/P10. P9 removed scheduler blocking during slow RPA sends, and P10 avoided duplicate target-ready work for same-target follow-up segments. The remaining measured live cost is mostly inside the actual Win32/OCR send payload:

- `input_operation`
- `send_trigger`
- fixed post-input / after-trigger humanized waits

This phase only tunes existing internal humanized input profile parameters. It does not change the framework, public names, external APIs, CLI routes, JSON fields, Brain First reply ownership, final polish, freshness checks, session envelope, target confirmation, or RPA safety guards.

## Non-Negotiable Boundaries

- Do not rename variables, constants, paths, CLI commands, JSON output fields, routes, or public function names.
- Do not change `send_text`, `send_text_and_verify`, worker-facing commands, or public call signatures.
- Do not bypass `customer_service_brain`, final visible polish, freshness validation, session binding, target/session recheck, pre-send OCR guard, input confirmation, or post-send safety checks.
- Do not optimize by shortening a timeout and sending partial/no result.
- Do not reintroduce dual send triggers, click-send fallback, repeated same-pixel clicking, or keyboard/mouse overlap.
- Keep live customer-service send on randomized `clipboard_chunks`, typo disabled by live safety defaults, and `enter_only` send trigger.

## Evidence

P10 final live timing showed:

- average real send segment `send_total ~= 14.362s`
- average `payload ~= 9.399s`
- average `input_operation ~= 3.361s`
- average `send_trigger ~= 1.734s`
- same-target continuation already reduces duplicate `target_ready` to `0.0s`

So the next safe target is the internal humanized input profile, not Brain quality logic or target-confirmation guards.

## Chapter Plan

### Chapter 1: Tune Existing Profiles

Keep the existing profile names:

- `short_natural`
- `medium_natural`
- `long_natural_capped`

Only adjust internal numeric windows:

- slightly larger chunk sizes, still bounded and randomized
- lower per-character delay windows, still above mechanical zero-delay behavior
- less frequent micro-pauses, still present on longer text
- narrower post-input, pre-trigger, and after-trigger randomized windows

Expected effect:

- short greeting / simple reply RPA payload should save about 1-3 seconds per send on this machine
- long replies should become moderately faster without skipping Brain or evidence work
- same-target multi-bubble follow-up segments should benefit most because P10 already removed duplicate target-ready work

### Chapter 2: Contract And Static Regression

Run focused tests for:

- profile adaptation contracts
- sidecar/helper parity
- send trigger safety
- workflow logic
- scheduler behavior
- Brain First static ownership

Tests must prove the optimization remains parameter-only and does not alter external contracts.

### Chapter 3: Live-Oriented Evaluation

Use dry-run for broad behavior coverage, then low-volume live tests only after static checks pass.

Evaluation should compare against P10 baseline:

- `send_total`
- `payload`
- `input_operation`
- `send_trigger`
- danger scan signals: `blank_render`, `send_failed`, target/session mismatch, security/login prompts, red exclamation, emergency/risk stop

If any live test shows unsafe behavior, revert the profile numbers first. Do not solve RPA safety regressions by disabling search, disabling guards, or changing public APIs.

## Rollback

Rollback is simple because P11 is parameter-only:

- restore the old values inside `adapt_humanized_input_settings`
- restore matching test expectations
- rerun the same focused tests

No migration is required because no external contract changes are allowed in this phase.

## 2026-06-21 Evaluation

Implemented scope:

- tuned existing adaptive profile values only
- preserved profile names, env names, function names, CLI routes, JSON fields, and send call signatures
- preserved `clipboard_chunks`, `enter_only`, strict pre-send OCR target validation, input confirmation, post-send guard, Brain First, and final polish

Verification:

- `py_compile` passed for touched Win32/OCR modules and focused tests
- `run_wechat_win32_ocr_humanized_input_checks.py` passed 5 checks
- `run_wechat_win32_ocr_send_action_risk_checks.py` passed 4 checks
- `run_brain_first_static_architecture_audit.py` passed 9 checks
- `run_wechat_win32_ocr_compat_checks.py` passed 170 checks
- `run_workflow_logic_checks.py` passed 120 checks
- `run_customer_service_multi_session_scheduler_checks.py` passed 129 checks
- dry short-greeting passed with 2 simulated sends
- dry boundary passed with 4 simulated sends
- live short-greeting passed with 2 verified real AI customer-service replies

Live reply-send comparison against the P10 short-greeting artifact:

- P10 reply `payload` average: about `6.79s`
- P11 reply `payload` average: about `6.09s`
- P10 reply `send_trigger` average: about `1.47s`
- P11 reply `send_trigger` average: about `1.06s`
- P11 short reply `input_operation`: `0.71s`
- P11 longer greeting-context reply `input_operation`: `2.47s`

Interpretation:

P11 safely reduced the fixed send-trigger and short-payload tail without changing reply quality ownership or RPA safety gates. The effect is real but bounded because target activation and OCR confirmation still cost several seconds per cross-session send, and longer replies still spend time in chunked input plus OCR input confirmation.

No danger signals were found in the live run: target/session matched, WeChat remained online and OCR-readable, and no `blank_render`, send failure, login/security prompt, red-exclamation send failure, service-container wrong target, `emergency_stop`, or `risk_stop` signal appeared.
