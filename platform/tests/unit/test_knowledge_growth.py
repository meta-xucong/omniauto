"""Automatic knowledge growth tests."""

from pathlib import Path
import time
import textwrap

import pytest

from omniauto.knowledge import KnowledgeManager
from omniauto.service import OmniAutoService
from omniauto.core.state_machine import StateStore


def _make_repo_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='omniauto'\n", encoding="utf-8")
    for rel in (
        "knowledge/index",
        "knowledge/tasks/general",
        "workflows/verification/general",
        "runtime",
    ):
        (tmp_path / rel).mkdir(parents=True, exist_ok=True)
    (tmp_path / "knowledge/index/knowledge_registry.json").write_text(
        '{"version": 2, "root": "", "tasks": [], "patterns": [], "lessons": [], "capabilities": [], "proposals": []}',
        encoding="utf-8",
    )
    (tmp_path / "knowledge/index/capability_matrix.md").write_text(
        "# Capability Matrix\n\n| Capability | Maturity | Primary Evidence | Main Boundaries |\n| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_controlled_probe(repo_root: Path) -> Path:
    script = repo_root / "workflows" / "verification" / "general" / "probe.py"
    script.write_text(
        textwrap.dedent(
            """
            # Task: Temporary knowledge probe

            from omniauto.core.state_machine import Workflow, AtomicStep
            from omniauto.knowledge import record_knowledge_observation

            requires_browser = False


            def emit(context):
                record_knowledge_observation(
                    context,
                    kind="pattern",
                    title="Tmp probe pattern",
                    summary="Pattern notes can be written automatically from a controlled workflow.",
                    domain="general",
                    stage="emerging",
                )
                record_knowledge_observation(
                    context,
                    kind="lesson",
                    title="Tmp probe lesson",
                    summary="Lesson notes can be emitted during execution and persisted on closeout.",
                    domain="general",
                    trigger="tmp_probe",
                )
                record_knowledge_observation(
                    context,
                    kind="capability",
                    title="Tmp probe capability",
                    summary="Controlled workflows can update observed capability notes automatically.",
                    domain="general",
                    stage="observed",
                    boundaries="Probe-only boundary",
                )
                return {"ok": True}


            workflow = Workflow(
                task_id="tmp_probe_task",
                steps=[AtomicStep("emit", emit, lambda result: result.get("ok") is True, retry=1)],
            )
            """
        ),
        encoding="utf-8",
    )
    return script


def _write_heuristic_verification_probe(repo_root: Path) -> Path:
    script = repo_root / "workflows" / "verification" / "general" / "heuristic_probe.py"
    script.write_text(
        textwrap.dedent(
            """
            # Task: Heuristic knowledge probe

            from omniauto.core.state_machine import Workflow, AtomicStep

            requires_browser = False


            def run_probe(context):
                return {"status": "ok"}


            workflow = Workflow(
                task_id="heuristic_probe",
                steps=[AtomicStep("run_probe", run_probe, lambda result: result.get("status") == "ok", retry=1)],
            )
            """
        ),
        encoding="utf-8",
    )
    return script


@pytest.mark.asyncio
async def test_run_workflow_auto_closeout_updates_knowledge(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = _write_controlled_probe(repo_root)

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    result = await service.run_workflow(str(script), headless=True, entrypoint="test.controlled")

    assert result["final_state"] == "COMPLETED"
    closeout = result["knowledge_closeout"]
    assert closeout["applied"] is True
    assert (repo_root / "knowledge" / closeout["task_record"]).exists()
    assert (repo_root / "knowledge" / "patterns" / "emerging" / "general" / "tmp_probe_pattern.md").exists()
    assert (repo_root / "knowledge" / "lessons" / "general" / "tmp_probe_lesson.md").exists()
    assert (repo_root / "knowledge" / "capabilities" / "observed" / "general" / "tmp_probe_capability.md").exists()
    assert (repo_root / "knowledge" / "index" / "task_catalog.md").exists()
    assert (repo_root / "knowledge" / "index" / "pattern_index.md").exists()
    assert (repo_root / "knowledge" / "index" / "lesson_index.md").exists()
    registry = (repo_root / "knowledge" / "index" / "knowledge_registry.json").read_text(encoding="utf-8")
    assert "tmp-probe-pattern" in registry or "tmp_probe_pattern" in registry


@pytest.mark.asyncio
async def test_verification_workflow_derives_capability_without_explicit_observation(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = _write_heuristic_verification_probe(repo_root)

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    result = await service.run_workflow(str(script), headless=True, entrypoint="test.heuristic")

    assert result["final_state"] == "COMPLETED"
    capability = repo_root / "knowledge" / "capabilities" / "observed" / "general" / "heuristic_probe_verification_path.md"
    assert capability.exists()
    content = capability.read_text(encoding="utf-8")
    assert "verification path remains runnable" in content


@pytest.mark.asyncio
async def test_uncontrolled_script_skips_auto_closeout(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = tmp_path / "outside_probe.py"
    script.write_text(
        textwrap.dedent(
            """
            from omniauto.core.state_machine import Workflow, AtomicStep

            requires_browser = False
            workflow = Workflow(
                task_id="outside_probe",
                steps=[AtomicStep("noop", lambda ctx: {"ok": True}, lambda result: result.get("ok") is True, retry=1)],
            )
            """
        ),
        encoding="utf-8",
    )

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    result = await service.run_workflow(str(script), headless=True, entrypoint="test.uncontrolled")

    assert result["final_state"] == "COMPLETED"
    assert result["knowledge_closeout"]["applied"] is False
    assert result["knowledge_closeout"]["reason"] == "script_outside_controlled_workflows"


@pytest.mark.asyncio
async def test_validation_failure_derives_platform_lesson(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = repo_root / "workflows" / "generated" / "general" / "bad_probe.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("eval('1+1')\n", encoding="utf-8")

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    result = await service.run_workflow(str(script), headless=True, entrypoint="test.validation")

    assert result["final_state"] == "VALIDATION_FAILED"
    lesson = repo_root / "knowledge" / "lessons" / "platform" / "workflow_validation_guard_coverage.md"
    assert lesson.exists()
    assert "validator blocked" in lesson.read_text(encoding="utf-8")


def test_manual_closeout_forces_task_record(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    external_script = tmp_path / "manual_only.py"
    external_script.write_text("print('manual closeout')\n", encoding="utf-8")

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    summary = service.closeout_task(
        str(external_script),
        task_id="manual_closeout_probe",
        final_state="MANUAL",
        description="Manual closeout probe",
        note="Used to verify the fallback closeout path.",
        domain="general",
    )

    assert summary["applied"] is True
    assert (repo_root / "knowledge" / summary["task_record"]).exists()


def test_manual_closeout_refreshes_task_record_summary_to_latest_run(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    external_script = tmp_path / "manual_refresh.py"
    external_script.write_text("print('manual closeout refresh')\n", encoding="utf-8")

    service = OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=KnowledgeManager(repo_root=repo_root),
    )

    first = service.closeout_task(
        str(external_script),
        task_id="manual_refresh_probe",
        final_state="FAILED",
        description="Manual refresh probe",
        note="First run failed.",
        domain="general",
    )
    time.sleep(1.1)
    second = service.closeout_task(
        str(external_script),
        task_id="manual_refresh_probe",
        final_state="COMPLETED",
        description="Manual refresh probe",
        note="Second run completed.",
        domain="general",
    )

    record_path = repo_root / "knowledge" / second["task_record"]
    content = record_path.read_text(encoding="utf-8")

    assert first["task_record"] == second["task_record"]
    assert "status: completed" in content
    assert "- Status: completed" in content
    assert "First run failed." in content
    assert "Second run completed." in content
