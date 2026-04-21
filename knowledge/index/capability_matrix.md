# Capability Matrix

| Capability | Maturity | Primary Evidence | Main Boundaries |
| --- | --- | --- | --- |
| Deterministic browser workflows | Stable | `../../platform/src/omniauto/core/state_machine.py`, `../../platform/tests/unit/test_state_machine.py` | Needs explicit scripts or generated workflows |
| Browser interaction with recovery hooks | Emerging | `../../platform/src/omniauto/engines/browser.py`, `../../platform/tests/integration/test_browser_recovery.py` | Does not turn runtime into free-form AI control |
| Manual handoff on login or risk pages | Emerging | `../tasks/platform/browser_recovery_and_manual_handoff_upgrade.md` | Stops at verification boundaries instead of bypassing them |
| 1688 low-disturbance marketplace collection | Emerging | `../tasks/marketplaces/1688_research_family.md` | Sensitive-site strategy intentionally favors partial results |
| Local structured report to Excel/WPS-friendly output | Emerging | `../tasks/marketplaces/single_rocking_chair_local_excel_report.md`, `../../platform/tests/unit/test_local_excel_report_generation.py` | Stronger for structured data than for arbitrary rich documents |
| WPS desktop automation | Exploratory to emerging | `../tasks/desktop/wps_hardinput_reliability_probes.md` | GUI paths can still be environment-sensitive |
| Visual desktop solver experimentation | Exploratory | `../tasks/desktop/minesweeper_solver_exploration.md` | Not yet a generic promise for arbitrary desktop apps |
| Agent runtime prompt-to-script generation | Emerging | `../../platform/src/omniauto/agent_runtime.py`, `../tasks/browser/legacy_agent_browser_tasks.md` | Legacy generated scripts should not be treated as polished exemplars |

## Auto-Observed Capability Notes

| Capability Note | Domain | Maturity | Record | Main Boundaries |
| --- | --- | --- | --- | --- |
| Automatic knowledge closeout | general | emerging | `../capabilities/observed/general/automatic_knowledge_closeout.md` | Applies to controlled workflow entrypoints; legacy ad-hoc scripts still need manual closeout. |
| Verify automatic knowledge growth closeout verification path | general | emerging | `../capabilities/observed/general/knowledge_growth_probe_verification_path.md` | Represents a runnable verification asset, not a broad guarantee beyond this workflow. |
| Verify heuristic knowledge closeout verification path | general | emerging | `../capabilities/observed/general/knowledge_growth_heuristic_probe_verification_path.md` | Represents a runnable verification asset, not a broad guarantee beyond this workflow. |
