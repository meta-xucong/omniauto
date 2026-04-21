"""Knowledge policy and AI-assist isolation tests."""

from pathlib import Path
import textwrap

import pytest

from omniauto.core.state_machine import StateStore
from omniauto.knowledge import KnowledgeManager, KnowledgePolicy, StrictCandidateAIAssist
from omniauto.service import OmniAutoService


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
        '{"version": 2, "root": "", "tasks": [], "patterns": [], "lessons": [], "capabilities": [], "proposals": [], "ai_candidates": []}',
        encoding="utf-8",
    )
    (tmp_path / "knowledge/index/capability_matrix.md").write_text(
        "# Capability Matrix\n\n| Capability | Maturity | Primary Evidence | Main Boundaries |\n| --- | --- | --- | --- |\n",
        encoding="utf-8",
    )
    return tmp_path


def _write_heuristic_verification_probe(repo_root: Path) -> Path:
    script = repo_root / "workflows" / "verification" / "general" / "heuristic_probe.py"
    script.write_text(
        textwrap.dedent(
            """
            # Task: Heuristic knowledge policy probe

            from omniauto.core.state_machine import Workflow, AtomicStep

            requires_browser = False


            def run_probe(context):
                return {"status": "ok"}


            workflow = Workflow(
                task_id="heuristic_policy_probe",
                steps=[AtomicStep("run_probe", run_probe, lambda result: result.get("status") == "ok", retry=1)],
            )
            """
        ),
        encoding="utf-8",
    )
    return script


def _service(repo_root: Path, manager: KnowledgeManager) -> OmniAutoService:
    return OmniAutoService(
        state_store=StateStore(db_path=str(repo_root / "runtime" / "state.db")),
        knowledge_manager=manager,
    )


def test_default_policy_preserves_current_controlled_root_behavior(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    policy = KnowledgePolicy()
    controlled = repo_root / "workflows" / "verification" / "general" / "probe.py"
    controlled.parent.mkdir(parents=True, exist_ok=True)
    controlled.write_text("print('ok')\n", encoding="utf-8")
    external = repo_root / "probe.py"
    external.write_text("print('outside')\n", encoding="utf-8")

    assert policy.is_controlled_task(repo_root, controlled) is True
    assert policy.is_controlled_task(repo_root, external) is False


@pytest.mark.asyncio
async def test_ai_assist_off_keeps_existing_closeout_behavior(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = _write_heuristic_verification_probe(repo_root)
    policy = KnowledgePolicy(ai_assist_mode="off")
    ai_assistant = StrictCandidateAIAssist(
        policy=policy,
        provider=lambda evidence_pack: [
            {
                "kind": "pattern",
                "title": "Should stay disabled",
                "summary": "This should never be written when AI assist is off.",
                "evidence_refs": [evidence_pack["script"]],
            }
        ],
    )
    manager = KnowledgeManager(repo_root=repo_root, policy=policy, ai_assistant=ai_assistant)

    result = await _service(repo_root, manager).run_workflow(
        str(script),
        headless=True,
        entrypoint="test.policy.off",
    )

    assert result["final_state"] == "COMPLETED"
    assert result["knowledge_closeout"]["ai_assist"]["reason"] == "ai_assist_disabled"
    assert list((repo_root / "knowledge" / "review" / "ai_candidates").rglob("*.md")) == []


@pytest.mark.asyncio
async def test_strict_ai_assist_writes_review_candidate_only(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = _write_heuristic_verification_probe(repo_root)
    policy = KnowledgePolicy(ai_assist_mode="strict_candidate", ai_trigger_min_duration_seconds=0.0)

    def provider(evidence_pack):
        return [
            {
                "kind": "pattern",
                "title": "Review only AI pattern",
                "summary": "Strict AI assist should write only review candidates, never formal pattern files.",
                "domain": "general",
                "confidence": "medium",
                "evidence_refs": [evidence_pack["script"], evidence_pack["task_record"]],
            }
        ]

    manager = KnowledgeManager(
        repo_root=repo_root,
        policy=policy,
        ai_assistant=StrictCandidateAIAssist(policy=policy, provider=provider),
    )

    result = await _service(repo_root, manager).run_workflow(
        str(script),
        headless=True,
        entrypoint="test.policy.strict",
    )

    assert result["final_state"] == "COMPLETED"
    assert result["knowledge_closeout"]["ai_assist"]["applied"] is True
    candidate = repo_root / "knowledge" / "review" / "ai_candidates" / "patterns" / "general" / "review_only_ai_pattern.md"
    assert candidate.exists()
    assert not (repo_root / "knowledge" / "patterns" / "emerging" / "general" / "review_only_ai_pattern.md").exists()
    assert "Review only AI pattern" in (repo_root / "knowledge" / "index" / "ai_candidate_queue.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_invalid_ai_candidate_does_not_break_workflow(tmp_path):
    repo_root = _make_repo_root(tmp_path)
    script = _write_heuristic_verification_probe(repo_root)
    policy = KnowledgePolicy(ai_assist_mode="strict_candidate", ai_trigger_min_duration_seconds=0.0)
    manager = KnowledgeManager(
        repo_root=repo_root,
        policy=policy,
        ai_assistant=StrictCandidateAIAssist(
            policy=policy,
            provider=lambda evidence_pack: [
                {
                    "kind": "pattern",
                    "title": "Broken AI candidate",
                    "summary": "Missing evidence should keep this candidate isolated.",
                    "domain": "general",
                    "confidence": "medium",
                    "evidence_refs": [],
                }
            ],
        ),
    )

    result = await _service(repo_root, manager).run_workflow(
        str(script),
        headless=True,
        entrypoint="test.policy.invalid",
    )

    assert result["final_state"] == "COMPLETED"
    assert result["knowledge_closeout"]["ai_assist"]["applied"] is False
    assert result["knowledge_closeout"]["ai_assist"]["reason"] == "no_valid_candidates"
    assert "missing_evidence" in result["knowledge_closeout"]["ai_assist"]["errors"]
    assert not (repo_root / "knowledge" / "review" / "ai_candidates" / "patterns" / "general" / "broken_ai_candidate.md").exists()
