# Codex Project Rules

## Windows Encoding Safety

This project may contain Chinese text. Treat all source files as UTF-8.

- Prefer `apply_patch` for manual source edits.
- Do not rewrite source files with Windows PowerShell 5.1 text pipelines such as:
  - `Get-Content file | Set-Content file`
  - `Out-File`
  - `>`
  - `>>`
- This applies especially to `.js`, `.ts`, `.tsx`, `.vue`, `.html`, `.css`, `.json`, `.py`, and `.md` files.
- If a bulk rewrite is required, explicitly read and write UTF-8 without BOM, or use Node.js `fs` APIs with `utf8`.
- After editing frontend JavaScript or TypeScript files, run `node --check`, lint, or the relevant project test command.

## Naming And Contract Stability

Do not casually rename existing variables, constants, CLI commands, route names, artifact scopes, file paths, JSON field names, or public function names.

- Treat names such as the current add_friend route `add-friend-entry-click-plan-windows`, worker-facing CLI routes, JSON output fields, and shared constants as collaboration contracts, not local implementation details.
- Historical add_friend routes such as `add-friend-entry-click-plan` and `add-friend-entry-click-plan-windows-1080p-reference` must not be silently reintroduced after PR #21; document and confirm any compatibility bridge before adding them back.
- Preserve the original name and add aliases or adapter layers when platform-specific behavior is needed.
- Rename only when the user explicitly approves the exact old name, new name, and migration plan.
- Before any approved rename, update compatibility tests, documentation, and downstream references in the same change.
- If a name looks wrong or misleading, document the issue and propose a migration instead of silently changing it.

## External Contract Freeze And Optional Module Isolation (Required)

This repository is consumed by external developers. Treat every value that can cross a module, process, plugin, CLI, HTTP, file, or import boundary as a frozen compatibility contract unless the repository owner explicitly approves a migration.

- Frozen contracts include exported variable/constant/class/function names, import paths, function signatures, positional/keyword argument names, return-object keys, JSON fields, event names, state-file paths and shapes, configuration keys, environment variables, CLI commands/options, HTTP routes, connector methods, artifact names, error codes, default values, nullability, and externally observable semantics.
- Internal refactors must preserve the existing external name, type, meaning, default, optionality, and error behavior. Keep a facade, wrapper, re-export, alias, or adapter at the old boundary when moving implementation code.
- Do not move or rename a public symbol and require downstream callers to update. Unknown external consumers must be assumed to exist.
- Additive extensions must be optional and backward compatible. Existing callers that do not send, read, or understand the new field/module must continue to work unchanged.
- Any unavoidable breaking change requires the repository owner's explicit approval of the exact old contract, new contract, compatibility window, migration adapter, downstream impact, and removal date. Documentation and contract tests must land before the breaking implementation.
- Before a large internal refactor, inventory the affected boundary and add characterization/contract tests. After the refactor, run the same tests against the old import path and external payload shape.
- State-format changes must keep backward readers or an idempotent migration. Never silently reinterpret an existing field.

For `apps/wechat_ai_customer_service`, voice and image-understanding capabilities are strictly independent optional plugin domains:

- Voice and image-understanding implementations must live in separate modules/packages, have separate configuration, dependencies, lifecycle, enablement, failure handling, and tests, and must never import each other's implementation.
- The core program may expose a small neutral plugin protocol/registry that has no voice, vision, model-provider, OCR, clipboard, image, audio, or other optional dependency. Sharing that protocol does not make the implementations one module.
- The core must not import an optional voice or image implementation at module-import time. Discovery and loading must be lazy, capability-based, and absence-safe.
- Core-only, core+voice, core+image, core+both, custom-voice, custom-image, and missing-optional-dependency configurations must all remain valid. Absence or failure of one plugin must not disable the core or the other plugin.
- Third-party developers must be able to mount their own voice or image plugin without importing the bundled counterpart or changing existing inter-module payload fields.
- Plugins may enrich existing message/context fields through compatibility adapters, but they must not rename shared fields, change Brain contracts, own scheduler state, or author customer-visible replies.
- The scheduler and Brain bridge may depend only on the neutral plugin contract and existing compatibility payloads, never on a concrete voice/vision provider implementation.

Within those boundaries, internal cleanup is encouraged: split oversized files, extract pure helpers, isolate state transitions, remove verified-dead private code, and improve naming inside private modules. Prefer a compatibility facade plus small cohesive internal modules over a framework rewrite.

All future WeChat customer-service architecture or refactor documents must reference both:

- `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`
- `apps/wechat_ai_customer_service/docs/customer_service_external_contract_and_optional_plugin_baseline.md`

## WeChat Cloud Simulation Baseline (Required)

For `apps/wechat_ai_customer_service`, the test environment has an approved local cloud simulation mode:

- When real VPS/cloud is unavailable, default to local dual-port simulation (`vps_admin` + `admin_backend`) for cloud-link validation.
- Prefer running `apps/wechat_ai_customer_service/tests/run_vps_local_two_port_shared_sync_checks.py` before diagnosing cloud-gate failures.
- Under `WECHAT_CLOUD_REQUIRED=1`, `cloud_base_url_missing` means environment precondition is not satisfied, not a product bug by itself.
- Do not report cloud-gate lock as a code defect unless it also fails under:
  - local dual-port simulation, or
  - a real reachable VPS base URL.
- For live regression scripts, if bootstrap is blocked by `cloud_authoritative_access_required` + `cloud_base_url_missing`, classify as expected environment block and fix the connection path first.

## WeChat AI Customer Service Brain First Baseline (Required)

For `apps/wechat_ai_customer_service`, customer-facing reply work must follow the Brain First architecture documented under `apps/wechat_ai_customer_service/docs/brain_first_customer_service_20260603/`.

Core rule: normal customer-service replies should be designed around an LLM customer-service brain that understands the customer message, plans the reply, cites allowed evidence, then passes through guard verification and final visible polish. Do not keep solving reply-quality defects by adding more local hard-coded response branches.

Hard ownership rule: all customer-visible replies must be authored by `customer_service_brain`. Guard, quality gates, semantic reviewers, realtime/RAG/local routes, legacy synthesis, final polish, and fallback modules must not author, replace, splice, or finalize customer-visible wording. When Brain is unavailable, times out, is non-adoptable, or repair fails, block outbound send and trigger internal handoff/alert; do not send a local safe fallback.

Documentation rule: every future customer-service development document must reference `apps/wechat_ai_customer_service/docs/customer_visible_reply_ownership_baseline.md`; exceptions require updating this AGENTS.md section, that baseline document, and contract tests before code changes.

- Treat `customer_service_brain` / guarded LLM synthesis as the intended owner of normal dialogue understanding, intent resolution, fuzzy entity matching, context handling, customer objections, social small talk, and final reply strategy.
- Brain authority is the default optimization direction: hand every customer-reply decision that can reasonably be handled by `customer_service_brain` to the Brain, while keeping product master, formal knowledge, and safety boundaries as hard constraints. Structured routes, deterministic checks, quality gates, guards, RAG retrieval, historical examples, and final polish are advisory/control layers, not competing answer engines.
- When an advisory/control layer finds a Brain draft wrong, incomplete, unsafe, off-topic, over-structured, or poorly phrased, convert that finding into feedback for the Brain to rethink and repair. Do not replace the Brain answer with a new local template, hard-coded branch, route-specific wording, or account-specific patch.
- Final customer-visible wording should still be controlled by the Brain's strategy. Final polish is weakened to verification and light naturalization: it may flag, trim, split, or lightly smooth text, but it must not change facts, strategy, recommendation, risk posture, or conversation intent chosen by the Brain.
- Optimize reply quality through global, reusable Brain reasoning, evidence, feedback, and repair mechanisms. Avoid fixing one bad reply by adding narrow keyword rules, product-specific branches, or structural phrase patches unless the issue is truly an authority-source, safety, or data-quality bug.
- Before adding or modifying deterministic reply logic, run a correction audit: identify whether the defect is a Brain-reasoning defect, evidence-pack defect, authority-data defect, guard/polish overreach, OCR/RPA metadata contamination, or multi-session binding bug. Only authority-data, hard-safety, capture, or binding defects should be fixed primarily with deterministic rules.
- Treat product master as the highest authority for product facts such as product name, aliases, price, stock, year, mileage, condition, location, and availability.
- Treat formal knowledge as the highest authority for policies, processes, risk boundaries, financing, trade-in, after-sales, transfer, contracts, invoices, and handoff rules.
- Treat current conversation facts as valid only inside the current conversation context.
- Treat AI experience pool, historical chats, style memory, and real chat examples as auxiliary style/experience material only. They must not authorize product facts, prices, stock, condition, policies, or commitments.
- Treat LLM common sense as auxiliary reasoning only. It may support general tradeoff analysis and clearer recommendations, but it must not invent product facts or business commitments.
- Keep all customer-visible replies behind guard verification and final visible LLM polish. Do not add speed shortcuts that bypass final polish for greetings, short replies, explicit price questions, or simple answers.
- Demote RAG/realtime/local route logic to evidence retrieval, risk classification, latency profile selection, system-error handling, and fallback. Normal business replies should not be finalized by local templates when Brain First is enabled.
- Treat the explicit `Brain层` as the synchronous runtime reasoning layer for customer dialogue. It owns understanding, strategy, context use, fuzzy matching, social small talk, repair after reviewer feedback, and `BrainPlan.reply_segments`; it may only cite authorized facts from product master, formal knowledge, and current conversation facts.
- Treat the explicit `代码机制层` as the operational correctness layer for OCR/RPA/session scheduling, session ledger, reply envelope, send-target confirmation, freshness, low-disturbance listening, anti-cross-send checks, and WeChat safety guards. It must never author customer-visible wording or decide business reply content.
- Treat `conversation_strategy_state` as per-session, non-authoritative strategy metadata maintained by the code mechanism layer and consumed by the Brain layer. It may track repeated small talk, probing, customer resistance to business redirection, and redirect fatigue, but it must not authorize facts, appear in customer-visible text, or generate replies. When the customer returns to a business request, the state must decay or reset so Brain can resume normal service.
- Do not hard-code account-specific products, prices, car models, or sales answers in route code. Product-specific facts must come from product master or product-scoped formal knowledge.
- Preserve multi-session isolation: every captured message, Brain input, ready reply, and send operation must remain bound to the correct conversation/target/session. Before RPA sends a reply, re-check that the active WeChat conversation matches the reply target.
- OCR or RPA speaker labels such as contact names, group sender names, and chat titles are metadata, not customer message content. Apply this rule consistently to both WeChat AI customer service and AI smart recorder flows.
- When modifying reply logic, include tests for short greetings, explicit product questions, fuzzy names/typos, context follow-ups, customer objections, off-topic friendly redirection, authority-source conflicts, and multi-session no-cross-send behavior.
- If a change touches cloud gate or live startup, use the local cloud simulation baseline above before reporting a cloud authorization failure as a product defect.

## Local Test Secrets Policy (Project-Specific Override)

For `apps/wechat_ai_customer_service` local/test migration workflows, the repository owner explicitly allows plaintext test credentials in runtime/test artifacts when needed for direct environment migration and replay.

- Do **not** auto-redact or auto-remove plaintext test keys/tokens from local runtime/test files unless explicitly requested by the user in that task.
- Treat this as an intentional test-environment decision, not an automatic bug.
- Scope: local runtime/test artifacts and migration payloads only.
- Production/public release hardening is still a separate step and must be requested explicitly.
