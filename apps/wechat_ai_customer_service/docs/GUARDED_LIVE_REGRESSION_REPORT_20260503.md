# Guarded Live Regression Report - 2026-05-03

## Scope

This report covers the guarded File Transfer Assistant live regression after the customer-data completion and evidence-boundary fixes.

Primary acceptance target:

- Real WeChat send-mode regression through 文件传输助手.
- Temporary full-auto customer-service mode during the run.
- Automatic restore to disabled/manual-assist mode after the run.
- Lock-screen monitoring and idle-prevention enabled.
- No residual live-regression processes after completion.

## Fixes Verified

1. Incomplete customer data can be completed by a later message even when live-regression markers are present.
   - Scenario 17 asks for missing name.
   - Scenario 18 supplies `联系人：李补全`.
   - The final lead is written successfully.

2. Weak answer-only policy matches no longer authorize unrelated business-adjacent questions.
   - `你们老板喜欢什么颜色的包装？` previously matched unrelated policy text and produced `no_rule_matched`.
   - It now correctly produces `evidence_safety:no_relevant_business_evidence`.

3. Tenant/customer formal knowledge still overrides conflicting shared public risk-control knowledge.
   - Direct tenant keyword/title policy matches are treated as authoritative evidence.
   - Conflicting shared risk-control items are suppressed when tenant formal knowledge applies.

## Live Result

Artifact set:

- Result: `runtime/apps/wechat_ai_customer_service/test_artifacts/file_transfer_live_full_guarded_20260503_191929.json`
- Summary: `runtime/apps/wechat_ai_customer_service/test_artifacts/file_transfer_live_full_guarded_20260503_191929_summary.json`
- Guard status: `runtime/apps/wechat_ai_customer_service/test_artifacts/file_transfer_live_full_guarded_20260503_191929_status.json`

Summary:

- Started: `2026-05-03T19:19:30+0800`
- Finished: `2026-05-03T19:55:13+0800`
- Selected scenarios: 20
- Passed: 20
- Failed: 0
- Pending: 0
- Supervisor invocations: 5
- Timed out chunks: 0
- Lock-screen interruption: none

Covered live scenarios:

- Greeting and catalog replies.
- Product quote, quantity quote, shipping city, and contextual product continuation.
- Public discount reply and below-tier discount handoff.
- Company profile, invoice, payment, logistics, and warranty replies.
- After-sales sensitive issue, installation, contract/monthly-credit handoff.
- Complete customer data write.
- Incomplete customer data prompt and later completion write.
- Unknown business-adjacent question handoff with missing-evidence reason.
- Mixed discount plus customer-data batch handoff without writing risky customer data.

## Post-Run Environment Checks

- Customer-service settings restored to:
  - `enabled=false`
  - `reply_mode=manual_assist`
  - `record_messages=true`
  - `auto_learn=true`
  - `use_llm=true`
  - `rag_enabled=true`
  - `data_capture_enabled=true`
  - `handoff_enabled=true`
  - `operator_alert_enabled=true`
- No residual `run_file_transfer_live_guarded.py`, `run_file_transfer_live_supervisor.py`, or `run_file_transfer_live_regression.py` Python processes.

## Regression Checks

Passed after the fixes:

- `python -m compileall -q apps/wechat_ai_customer_service`
- `run_knowledge_runtime_checks.py`: 13/13
- `run_workflow_logic_checks.py`: 13/13
- `run_boundary_matrix_checks.py`: 15/15
- `run_rag_boundary_checks.py`: 9/9
- `run_rag_layer_checks.py`: 4/4
- `run_admin_backend_checks.py --chapter all`: 17/17
- `run_vps_admin_control_plane_checks.py`: 8/8
- `run_multi_tenant_auth_sync_checks.py`: 9/9
- `run_smart_recorder_checks.py`: 4/4

## Notes

- Some stdout tails in PowerShell show mojibake for Chinese text, but JSON artifacts are UTF-8 and the functional assertions passed.
- The run did not hit the previous lock-screen interruption path.
- This report is ready for user acceptance review.
