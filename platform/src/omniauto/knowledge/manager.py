"""Automatic knowledge growth manager."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .ai_assist import StrictCandidateAIAssist
from .policy import DEFAULT_KNOWLEDGE_POLICY, KnowledgePolicy
from .schemas import AIAssistResult, AICandidate
from ..core.context import TaskContext


DOMAINS = DEFAULT_KNOWLEDGE_POLICY.domains
PATTERN_STAGES = DEFAULT_KNOWLEDGE_POLICY.pattern_stages
CAPABILITY_STAGES = DEFAULT_KNOWLEDGE_POLICY.capability_stages
PROPOSAL_KINDS = DEFAULT_KNOWLEDGE_POLICY.proposal_kinds


@dataclass
class KnowledgeObservation:
    """Structured knowledge note emitted during a task run."""

    kind: str
    title: str
    summary: str
    domain: str = "general"
    slug: str = ""
    stage: str = ""
    maturity: str = "medium"
    tags: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    trigger: str = ""
    boundaries: str = ""
    proposal_kind: str = ""
    approval_required: bool = True

    def normalized_slug(self) -> str:
        return self.slug or slugify(self.title)


@dataclass
class TaskRun:
    """Metadata for one controlled task execution."""

    run_id: str
    started_at: str
    entrypoint: str
    script_path: str
    description: str
    task_id: str
    domain: str
    controlled: bool
    run_dir: str = ""
    category: str = ""
    finished_at: str = ""


def slugify(text: str) -> str:
    """Build a stable filesystem slug."""

    raw = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", (text or "").strip(), flags=re.UNICODE)
    raw = re.sub(r"_+", "_", raw).strip("_")
    return raw.lower() or "untitled"


def _now() -> datetime:
    return datetime.now()


def _iso_now() -> str:
    return _now().isoformat(timespec="seconds")


def _discover_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in current.parents:
        if (candidate / "pyproject.toml").exists() and (candidate / "knowledge").exists():
            return candidate
    raise RuntimeError("Unable to locate OmniAuto repository root")


def record_knowledge_observation(context: TaskContext, **payload: Any) -> None:
    """Append one knowledge observation to the current task context."""

    obs = KnowledgeObservation(**payload)
    context.metadata.setdefault("knowledge_observations", [])
    context.metadata["knowledge_observations"].append(asdict(obs))


class KnowledgeManager:
    """Coordinates automatic closeout into the repository knowledge layer."""

    def __init__(
        self,
        repo_root: Optional[str | Path] = None,
        *,
        policy: Optional[KnowledgePolicy] = None,
        ai_assistant: Optional[StrictCandidateAIAssist] = None,
    ) -> None:
        self.policy = policy or DEFAULT_KNOWLEDGE_POLICY
        self.repo_root = Path(repo_root).resolve() if repo_root else _discover_repo_root()
        self.knowledge_root = self.repo_root / "knowledge"
        self.runtime_runs_root = self.repo_root / "runtime" / "knowledge_runs"
        self.registry_path = self.knowledge_root / "index" / "knowledge_registry.json"
        self.ai_candidate_root = self.knowledge_root / "review" / "ai_candidates"
        self.ai_candidate_queue_path = self.knowledge_root / "index" / "ai_candidate_queue.md"
        self.ai_assistant = ai_assistant or StrictCandidateAIAssist(policy=self.policy)
        self.bootstrap_structure()

    def bootstrap_structure(self) -> None:
        """Ensure runtime and knowledge directories exist."""

        dirs = [
            self.runtime_runs_root,
            self.knowledge_root / "index",
            self.knowledge_root / "tasks" / "general",
        ]
        for stage in self.policy.pattern_stages:
            for domain in self.policy.domains:
                dirs.append(self.knowledge_root / "patterns" / stage / domain)
        for domain in self.policy.domains:
            dirs.append(self.knowledge_root / "lessons" / domain)
        for stage in self.policy.capability_stages:
            for domain in self.policy.domains:
                dirs.append(self.knowledge_root / "capabilities" / stage / domain)
        for proposal_kind in self.policy.proposal_kinds:
            bucket = self.policy.proposal_bucket(proposal_kind)
            for domain in self.policy.domains:
                dirs.append(self.knowledge_root / "proposals" / bucket / domain)
        for kind in self.policy.ai_candidate_kinds:
            bucket = self.policy.candidate_bucket(kind)
            for domain in self.policy.domains:
                dirs.append(self.ai_candidate_root / bucket / domain)
        for path in dirs:
            path.mkdir(parents=True, exist_ok=True)

        for placeholder in (
            self.knowledge_root / "index" / "pattern_index.md",
            self.knowledge_root / "index" / "lesson_index.md",
            self.knowledge_root / "index" / "proposal_queue.md",
            self.ai_candidate_queue_path,
        ):
            if not placeholder.exists():
                placeholder.write_text("# Pending Index Build\n", encoding="utf-8")

        if not self.registry_path.exists():
            self._write_registry(
                {
                    "version": 2,
                    "root": self.knowledge_root.as_posix(),
                    "tasks": [],
                    "patterns": [],
                    "lessons": [],
                    "capabilities": [],
                    "proposals": [],
                    "ai_candidates": [],
                }
            )

    def start_task_run(
        self,
        *,
        script_path: str | Path,
        task_id: str,
        entrypoint: str,
        description: str = "",
        force: bool = False,
    ) -> TaskRun:
        """Create an execution record for a controlled task run."""

        script = Path(script_path).resolve()
        domain, category = self._classify_script(script)
        controlled = force or self.is_controlled_task(script)
        timestamp = _now()
        run_id = f"{timestamp.strftime('%Y%m%d_%H%M%S')}_{slugify(task_id or script.stem)}"
        run_dir = ""
        task_run = TaskRun(
            run_id=run_id,
            started_at=timestamp.isoformat(timespec="seconds"),
            entrypoint=entrypoint,
            script_path=script.as_posix(),
            description=description or self.extract_task_description(script),
            task_id=task_id,
            domain=domain,
            controlled=controlled,
            category=category,
        )
        if controlled:
            day_dir = self.runtime_runs_root / timestamp.strftime("%Y-%m-%d")
            day_dir.mkdir(parents=True, exist_ok=True)
            run_path = day_dir / run_id
            run_path.mkdir(parents=True, exist_ok=True)
            task_run.run_dir = run_path.as_posix()
            self._write_json(
                run_path / "task_run.json",
                {
                    **asdict(task_run),
                    "status": "started",
                },
            )
        return task_run

    def finalize_task_run(
        self,
        task_run: TaskRun,
        *,
        result: Dict[str, Any],
        context: Optional[TaskContext] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Write automatic closeout results into the knowledge layer."""

        if not (task_run.controlled or force):
            return {
                "enabled": False,
                "applied": False,
                "reason": "script_outside_controlled_workflows",
            }

        task_run.finished_at = _iso_now()
        registry = self._load_registry()
        script_rel = self._relative(Path(task_run.script_path))
        task_entry = self._upsert_task_record(
            registry=registry,
            task_run=task_run,
            result=result,
            script_rel=script_rel,
        )

        observations = self._load_observations(context)
        observations.extend(
            self._derive_automatic_observations(
                task_run=task_run,
                result=result,
                explicit_observations=observations,
            )
        )
        applied_observations = []
        for observation in observations:
            entry = self._apply_observation(
                registry=registry,
                task_run=task_run,
                observation=observation,
                script_rel=script_rel,
            )
            if entry is not None:
                applied_observations.append(entry)

        ai_result = self._maybe_apply_ai_candidates(
            registry=registry,
            task_run=task_run,
            result=result,
            task_record=task_entry,
            script_rel=script_rel,
        )

        self._write_registry(registry)
        self._render_indexes(registry)

        summary = {
            "enabled": True,
            "applied": True,
            "task_record": task_entry["record"],
            "run_dir": self._relative(Path(task_run.run_dir)) if task_run.run_dir else "",
            "observation_files": [entry["path"] for entry in applied_observations if entry.get("path")],
            "ai_assist": ai_result["summary"],
            "ai_candidate_files": ai_result["paths"],
        }
        if task_run.run_dir:
            run_dir = Path(task_run.run_dir)
            self._write_json(
                run_dir / "task_run.json",
                {
                    **asdict(task_run),
                    "status": "finished",
                    "result": result,
                    "knowledge_closeout": summary,
                },
            )
            self._write_json(run_dir / "knowledge_closeout.json", summary)
        return summary

    def manual_closeout(
        self,
        *,
        script_path: str | Path,
        task_id: str,
        final_state: str,
        description: str = "",
        note: str = "",
        domain: str = "",
    ) -> Dict[str, Any]:
        """Fallback closeout for tasks that did not run through a controlled entrypoint."""

        task_run = self.start_task_run(
            script_path=script_path,
            task_id=task_id,
            entrypoint="service.manual_closeout",
            description=description,
            force=True,
        )
        if domain:
            task_run.domain = self._normalize_domain(domain)
        return self.finalize_task_run(
            task_run,
            result={
                "task_id": task_id,
                "final_state": final_state,
                "outputs": {},
                "duration_seconds": 0.0,
                "manual_note": note,
            },
            context=None,
            force=True,
        )

    def is_controlled_task(self, script_path: Path) -> bool:
        """Return True when a script is inside repo workflows."""

        return self.policy.is_controlled_task(self.repo_root, script_path)

    def extract_task_description(self, script_path: Path) -> str:
        """Read the script header to get a human-readable task description."""

        try:
            lines = script_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return script_path.stem.replace("_", " ")
        for line in lines[:12]:
            if line.startswith("# Task:"):
                return line.split(":", 1)[1].strip()
        return script_path.stem.replace("_", " ")

    def _classify_script(self, script_path: Path) -> tuple[str, str]:
        try:
            relative = script_path.resolve().relative_to(self.repo_root / "workflows")
        except ValueError:
            return "general", "external"
        parts = relative.parts
        category = parts[0] if parts else "external"
        domain = parts[1] if len(parts) >= 2 and parts[1] in self.policy.domains else "general"
        return domain, category

    def _normalize_domain(self, domain: str) -> str:
        return self.policy.normalize_domain(domain)

    def _relative(self, path: Path) -> str:
        if not path:
            return ""
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except Exception:
            return path.as_posix()

    def _load_observations(self, context: Optional[TaskContext]) -> list[KnowledgeObservation]:
        if context is None:
            return []
        raw = context.metadata.get("knowledge_observations", []) if context.metadata else []
        observations: list[KnowledgeObservation] = []
        for item in raw:
            try:
                observations.append(KnowledgeObservation(**item))
            except TypeError:
                continue
        return observations

    def _derive_automatic_observations(
        self,
        *,
        task_run: TaskRun,
        result: Dict[str, Any],
        explicit_observations: list[KnowledgeObservation],
    ) -> list[KnowledgeObservation]:
        """Derive low-risk observations from stable execution signals."""

        if not self.policy.enable_automatic_derivations:
            return []
        derived: list[KnowledgeObservation] = []
        explicit_keys = {
            (item.kind, item.normalized_slug())
            for item in explicit_observations
        }
        final_state = str(result.get("final_state", "")).upper()
        error_blob = " ".join(
            str(part or "")
            for part in [result.get("error", ""), result.get("validation_report", "")]
        ).lower()
        script_slug = slugify(Path(task_run.script_path).stem)
        task_title = self._human_title(task_run)

        def maybe_add(observation: KnowledgeObservation) -> None:
            key = (observation.kind, observation.normalized_slug())
            if key in explicit_keys:
                return
            if key in {(item.kind, item.normalized_slug()) for item in derived}:
                return
            derived.append(observation)

        if task_run.category == "verification" and final_state == "COMPLETED":
            maybe_add(
                KnowledgeObservation(
                    kind="capability",
                    title=f"{task_title} verification path",
                    slug=f"{script_slug}_verification_path",
                    summary=(
                        f"Verification workflow `{self._relative(Path(task_run.script_path))}` completed successfully through "
                        f"`{task_run.entrypoint}`, so this verification path remains runnable under controlled execution."
                    ),
                    domain=task_run.domain,
                    stage="observed",
                    maturity="emerging",
                    boundaries="Represents a runnable verification asset, not a broad guarantee beyond this workflow.",
                    tags=["auto-derived", "verification", "controlled-run"],
                    evidence=[self._relative(Path(task_run.script_path))],
                )
            )

        if final_state == "VALIDATION_FAILED":
            maybe_add(
                KnowledgeObservation(
                    kind="lesson",
                    title="Workflow validation guard coverage",
                    slug="workflow_validation_guard_coverage",
                    summary=(
                        "The workflow validator blocked a controlled script before execution, so validation failures now leave "
                        "task records and reusable lessons instead of disappearing as terminal CLI output."
                    ),
                    domain="platform",
                    trigger="validation_failed",
                    maturity="emerging",
                    tags=["auto-derived", "validation", "safety"],
                    evidence=[self._relative(Path(task_run.script_path))],
                )
            )

        if "timeout" in error_blob or "not found" in error_blob or "未找到" in error_blob:
            domain = task_run.domain if task_run.domain in {"browser", "marketplaces", "desktop"} else "general"
            maybe_add(
                KnowledgeObservation(
                    kind="lesson",
                    title="Timing or selector fragility",
                    slug=f"{domain}_timing_or_selector_fragility",
                    summary=(
                        f"Task `{task_run.task_id}` ended with timeout or lookup-style failures, so this run should be treated "
                        "as evidence that timing and target resolution still need explicit guards."
                    ),
                    domain=domain,
                    trigger="timeout_or_not_found",
                    maturity="medium",
                    tags=["auto-derived", "timing", "selector"],
                    evidence=[self._relative(Path(task_run.script_path))],
                )
            )

        if "manual_handoff" in error_blob or "verification challenge" in error_blob or "安全验证" in error_blob:
            maybe_add(
                KnowledgeObservation(
                    kind="lesson",
                    title="Manual handoff boundary signal",
                    slug=f"{task_run.domain}_manual_handoff_boundary",
                    summary=(
                        "This run surfaced a verification or manual-handoff boundary, reinforcing that controlled workflows should "
                        "pause and collect evidence rather than attempt to bypass those checkpoints."
                    ),
                    domain=task_run.domain,
                    trigger="manual_handoff_signal",
                    maturity="medium",
                    tags=["auto-derived", "manual-handoff", "boundary"],
                    evidence=[self._relative(Path(task_run.script_path))],
                )
            )

        return derived

    def _load_registry(self) -> Dict[str, Any]:
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        registry.setdefault("version", 2)
        registry.setdefault("root", self.knowledge_root.as_posix())
        registry.setdefault("tasks", [])
        registry.setdefault("patterns", [])
        registry.setdefault("lessons", [])
        registry.setdefault("capabilities", [])
        registry.setdefault("proposals", [])
        registry.setdefault("ai_candidates", [])
        return registry

    def _write_registry(self, registry: Dict[str, Any]) -> None:
        registry["root"] = self.knowledge_root.as_posix()
        self._write_json(self.registry_path, registry)

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _front_matter(self, payload: Dict[str, Any]) -> str:
        lines = ["---"]
        for key, value in payload.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
            elif isinstance(value, bool):
                lines.append(f"{key}: {'true' if value else 'false'}")
            else:
                lines.append(f"{key}: {value}")
        lines.append("---")
        return "\n".join(lines)

    def _existing_task_entry(self, registry: Dict[str, Any], script_rel: str) -> Optional[Dict[str, Any]]:
        normalized = script_rel.strip()
        for entry in registry.get("tasks", []):
            evidence = [str(item).strip() for item in entry.get("evidence", [])]
            if normalized in evidence:
                return entry
        return None

    def _upsert_task_record(
        self,
        *,
        registry: Dict[str, Any],
        task_run: TaskRun,
        result: Dict[str, Any],
        script_rel: str,
    ) -> Dict[str, Any]:
        existing = self._existing_task_entry(registry, script_rel)
        slug = existing["slug"] if existing else slugify(Path(task_run.script_path).stem)
        record = existing["record"] if existing else f"tasks/{task_run.domain}/{slug}.md"
        record_path = self.knowledge_root / record
        record_path.parent.mkdir(parents=True, exist_ok=True)
        title = existing["title"] if existing else (task_run.description or Path(task_run.script_path).stem.replace("_", " "))
        if not record_path.exists():
            content = [
                self._front_matter(
                    {
                        "title": title,
                        "kind": "task",
                        "domain": task_run.domain,
                        "status": "observed",
                        "last_updated": task_run.finished_at or _iso_now(),
                        "managed_by": "automatic_closeout",
                        "evidence": [script_rel],
                    }
                ),
                f"# {title}",
                "",
                "## Summary",
                "",
                f"- Status: {result.get('final_state', 'UNKNOWN').lower()}",
                f"- Domain: {task_run.domain}",
                f"- Controlled entrypoint: `{task_run.entrypoint}`",
                f"- Primary script: `{script_rel}`",
                "",
                "## Automated Runs",
                "",
            ]
            record_path.write_text("\n".join(content), encoding="utf-8")
        self._append_run_section(record_path, task_run=task_run, result=result)
        entry = {
            "slug": slug,
            "title": title,
            "domain": task_run.domain,
            "record": record,
            "status": (result.get("final_state", "UNKNOWN") or "UNKNOWN").lower(),
            "summary": f"Latest run via {task_run.entrypoint}",
            "evidence": self._merge_unique(
                [
                    script_rel,
                    self._relative(Path(task_run.run_dir) / "task_run.json") if task_run.run_dir else "",
                    record,
                ],
                existing.get("evidence", []) if existing else [],
            ),
            "managed": True,
            "last_updated": task_run.finished_at or _iso_now(),
        }
        registry["tasks"] = self._replace_entry(registry.get("tasks", []), entry, key="slug")
        return entry

    def _append_run_section(self, record_path: Path, *, task_run: TaskRun, result: Dict[str, Any]) -> None:
        text = record_path.read_text(encoding="utf-8")
        marker = f"### Run `{task_run.run_id}`"
        if marker in text:
            return
        lines = [
            marker,
            "",
            f"- Started at: `{task_run.started_at}`",
            f"- Finished at: `{task_run.finished_at or _iso_now()}`",
            f"- Final state: `{result.get('final_state', 'UNKNOWN')}`",
            f"- Duration seconds: `{result.get('duration_seconds', 0.0)}`",
            f"- Script: `{self._relative(Path(task_run.script_path))}`",
        ]
        if result.get("error"):
            lines.append(f"- Error: `{result['error']}`")
        outputs = result.get("outputs", {})
        if outputs:
            lines.append(f"- Outputs: `{json.dumps(outputs, ensure_ascii=False, default=str)}`")
        if result.get("manual_note"):
            lines.append(f"- Note: {result['manual_note']}")
        if task_run.run_dir:
            lines.append(f"- Run record: `{self._relative(Path(task_run.run_dir) / 'task_run.json')}`")
        lines.extend(["", ""])
        record_path.write_text(text.rstrip() + "\n\n" + "\n".join(lines), encoding="utf-8")

    def _apply_observation(
        self,
        *,
        registry: Dict[str, Any],
        task_run: TaskRun,
        observation: KnowledgeObservation,
        script_rel: str,
    ) -> Optional[Dict[str, Any]]:
        domain = self._normalize_domain(observation.domain or task_run.domain)
        slug = observation.normalized_slug()
        evidence = self._merge_unique(
            observation.evidence,
            [
                script_rel,
                self._relative(Path(task_run.run_dir) / "task_run.json") if task_run.run_dir else "",
            ],
        )
        path = ""
        entry: Dict[str, Any]
        if observation.kind == "pattern":
            stage = self.policy.normalize_pattern_stage(observation.stage)
            path = f"patterns/{stage}/{domain}/{slug}.md"
            entry = {
                "slug": slug,
                "title": observation.title,
                "domain": domain,
                "path": path,
                "stage": stage,
                "maturity": observation.maturity,
                "summary": observation.summary,
                "evidence": evidence,
                "managed": True,
                "last_updated": task_run.finished_at or _iso_now(),
            }
            registry["patterns"] = self._replace_entry(registry.get("patterns", []), entry, key="slug")
        elif observation.kind == "lesson":
            path = f"lessons/{domain}/{slug}.md"
            entry = {
                "slug": slug,
                "title": observation.title,
                "domain": domain,
                "path": path,
                "trigger": observation.trigger or "task closeout",
                "summary": observation.summary,
                "evidence": evidence,
                "managed": True,
                "last_updated": task_run.finished_at or _iso_now(),
            }
            registry["lessons"] = self._replace_entry(registry.get("lessons", []), entry, key="slug")
        elif observation.kind == "capability":
            stage = self.policy.normalize_capability_stage(observation.stage)
            path = f"capabilities/{stage}/{domain}/{slug}.md"
            entry = {
                "slug": slug,
                "title": observation.title,
                "domain": domain,
                "path": path,
                "maturity": observation.maturity,
                "summary": observation.summary,
                "boundaries": observation.boundaries,
                "evidence": evidence,
                "managed": True,
                "last_updated": task_run.finished_at or _iso_now(),
            }
            registry["capabilities"] = self._replace_entry(registry.get("capabilities", []), entry, key="slug")
        elif observation.kind == "proposal":
            proposal_kind = self.policy.normalize_proposal_kind(observation.proposal_kind)
            bucket = self.policy.proposal_bucket(proposal_kind)
            path = f"proposals/{bucket}/{domain}/{slug}.md"
            entry = {
                "slug": slug,
                "title": observation.title,
                "domain": domain,
                "path": path,
                "proposal_kind": proposal_kind,
                "status": "pending_manual_approval",
                "summary": observation.summary,
                "evidence": evidence,
                "managed": True,
                "last_updated": task_run.finished_at or _iso_now(),
            }
            registry["proposals"] = self._replace_entry(registry.get("proposals", []), entry, key="slug")
        else:
            return None

        self._write_observation_file(
            self.knowledge_root / path,
            task_run=task_run,
            observation=observation,
            evidence=evidence,
        )
        return entry

    def _write_observation_file(
        self,
        path: Path,
        *,
        task_run: TaskRun,
        observation: KnowledgeObservation,
        evidence: Iterable[str],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            content = [
                self._front_matter(
                    {
                        "title": observation.title,
                        "kind": observation.kind,
                        "domain": self._normalize_domain(observation.domain or task_run.domain),
                        "status": observation.stage or "observed",
                        "maturity": observation.maturity,
                        "last_updated": task_run.finished_at or _iso_now(),
                        "tags": observation.tags,
                        "evidence": [item for item in evidence if item],
                        "approval_required": observation.approval_required,
                    }
                ),
                f"# {observation.title}",
                "",
                "## Summary",
                "",
                observation.summary,
                "",
                "## Evidence Updates",
                "",
            ]
            path.write_text("\n".join(content), encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        marker = f"### Run `{task_run.run_id}`"
        if marker in text:
            return
        lines = [
            marker,
            "",
            f"- Source task: `{task_run.task_id}`",
            f"- Entry point: `{task_run.entrypoint}`",
            f"- Related script: `{self._relative(Path(task_run.script_path))}`",
        ]
        if observation.trigger:
            lines.append(f"- Trigger: {observation.trigger}")
        if observation.boundaries:
            lines.append(f"- Boundaries: {observation.boundaries}")
        if evidence:
            lines.append("- Evidence:")
            for item in evidence:
                lines.append(f"  - `{item}`")
        lines.extend(["", observation.summary, "", ""])
        path.write_text(text.rstrip() + "\n\n" + "\n".join(lines), encoding="utf-8")

    def _maybe_apply_ai_candidates(
        self,
        *,
        registry: Dict[str, Any],
        task_run: TaskRun,
        result: Dict[str, Any],
        task_record: Dict[str, Any],
        script_rel: str,
    ) -> Dict[str, Any]:
        try:
            ai_result = self.ai_assistant.maybe_generate(
                task_run=task_run,
                result=result,
                task_record={
                    **task_record,
                    "run_record": self._relative(Path(task_run.run_dir) / "task_run.json") if task_run.run_dir else "",
                },
                script_rel=script_rel,
            )
        except Exception as exc:
            fallback = AIAssistResult(
                enabled=self.policy.normalize_ai_mode(self.policy.ai_assist_mode) == "strict_candidate",
                applied=False,
                reason="ai_assist_exception",
                errors=[str(exc)],
            )
            return {"summary": fallback.to_dict(), "paths": []}

        applied_paths: list[str] = []
        if ai_result.applied:
            for candidate in ai_result.candidates:
                entry = self._apply_ai_candidate(
                    registry=registry,
                    task_run=task_run,
                    candidate=candidate,
                )
                if entry is not None and entry.get("path"):
                    applied_paths.append(entry["path"])
        return {"summary": ai_result.to_dict(), "paths": applied_paths}

    def _apply_ai_candidate(
        self,
        *,
        registry: Dict[str, Any],
        task_run: TaskRun,
        candidate: AICandidate,
    ) -> Optional[Dict[str, Any]]:
        domain = self._normalize_domain(candidate.domain or task_run.domain)
        slug = candidate.slug or slugify(candidate.title)
        bucket = self.policy.candidate_bucket(candidate.kind)
        path = f"review/ai_candidates/{bucket}/{domain}/{slug}.md"
        evidence = self._merge_unique(
            candidate.evidence_refs,
            [
                self._relative(Path(task_run.run_dir) / "task_run.json") if task_run.run_dir else "",
            ],
        )
        entry = {
            "slug": slug,
            "title": candidate.title,
            "domain": domain,
            "kind": candidate.kind,
            "path": path,
            "status": self.policy.candidate_status,
            "confidence": candidate.confidence,
            "summary": candidate.summary,
            "evidence": evidence,
            "managed": True,
            "last_updated": task_run.finished_at or _iso_now(),
        }
        registry["ai_candidates"] = self._replace_entry(registry.get("ai_candidates", []), entry, key="slug")
        self._write_ai_candidate_file(
            self.knowledge_root / path,
            task_run=task_run,
            candidate=candidate,
            evidence=evidence,
        )
        return entry

    def _write_ai_candidate_file(
        self,
        path: Path,
        *,
        task_run: TaskRun,
        candidate: AICandidate,
        evidence: Iterable[str],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            content = [
                self._front_matter(
                    {
                        "title": candidate.title,
                        "kind": f"{candidate.kind}_candidate",
                        "domain": self._normalize_domain(candidate.domain or task_run.domain),
                        "status": self.policy.candidate_status,
                        "maturity": candidate.maturity,
                        "confidence": candidate.confidence,
                        "last_updated": task_run.finished_at or _iso_now(),
                        "tags": candidate.tags,
                        "evidence": [item for item in evidence if item],
                        "approval_required": True,
                    }
                ),
                f"# {candidate.title}",
                "",
                "## Summary",
                "",
                candidate.summary,
                "",
                "## Review Notes",
                "",
                "This candidate was generated under strict AI-assist mode.",
                "It must remain in the review bucket until a human explicitly promotes or rewrites it.",
                "",
                "## Evidence Updates",
                "",
            ]
            path.write_text("\n".join(content), encoding="utf-8")
        text = path.read_text(encoding="utf-8")
        marker = f"### Run `{task_run.run_id}`"
        if marker in text:
            return
        lines = [
            marker,
            "",
            f"- Source task: `{task_run.task_id}`",
            f"- Entry point: `{task_run.entrypoint}`",
            f"- Candidate kind: `{candidate.kind}`",
            f"- Confidence: `{candidate.confidence}`",
            f"- Related script: `{self._relative(Path(task_run.script_path))}`",
        ]
        if candidate.boundaries:
            lines.append(f"- Boundaries: {candidate.boundaries}")
        if candidate.uncertainty_note:
            lines.append(f"- Uncertainty note: {candidate.uncertainty_note}")
        if evidence:
            lines.append("- Evidence:")
            for item in evidence:
                lines.append(f"  - `{item}`")
        lines.extend(["", candidate.summary, "", ""])
        path.write_text(text.rstrip() + "\n\n" + "\n".join(lines), encoding="utf-8")

    def _replace_entry(self, items: list[Dict[str, Any]], entry: Dict[str, Any], *, key: str) -> list[Dict[str, Any]]:
        replaced = False
        updated: list[Dict[str, Any]] = []
        for item in items:
            if item.get(key) == entry.get(key):
                updated.append({**item, **entry})
                replaced = True
            else:
                updated.append(item)
        if not replaced:
            updated.append(entry)
        return sorted(updated, key=lambda item: (str(item.get("domain", "")), str(item.get("title", item.get(key, ""))).lower()))

    def _merge_unique(self, primary: Iterable[str], secondary: Iterable[str] = ()) -> list[str]:
        merged: list[str] = []
        for item in [*secondary, *primary]:
            text = str(item or "").strip()
            if not text or text in merged:
                continue
            merged.append(text)
        return merged

    def _render_indexes(self, registry: Dict[str, Any]) -> None:
        self._render_task_catalog(registry.get("tasks", []))
        self._render_pattern_index(registry.get("patterns", []))
        self._render_lesson_index(registry.get("lessons", []))
        self._render_proposal_queue(registry.get("proposals", []))
        self._render_ai_candidate_queue(registry.get("ai_candidates", []))
        self._render_capability_auto_section(registry.get("capabilities", []))

    def _render_task_catalog(self, tasks: list[Dict[str, Any]]) -> None:
        lines = [
            "# Task Catalog",
            "",
            "| Initiative | Domain | State | Record | Key Evidence |",
            "| --- | --- | --- | --- | --- |",
        ]
        for entry in tasks:
            evidence = ", ".join(f"`{item}`" for item in entry.get("evidence", [])[:2])
            lines.append(
                f"| {entry.get('title', '')} | {entry.get('domain', '')} | {entry.get('status', '')} | "
                f"`../{entry.get('record', '')}` | {evidence or '-'} |"
            )
        lines.append("")
        (self.knowledge_root / "index" / "task_catalog.md").write_text("\n".join(lines), encoding="utf-8")

    def _render_pattern_index(self, patterns: list[Dict[str, Any]]) -> None:
        lines = [
            "# Pattern Index",
            "",
            "| Pattern | Layer | Domain | Maturity | Record | Use When |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for entry in patterns:
            lines.append(
                f"| {entry.get('title', '')} | {entry.get('stage', '')} | {entry.get('domain', '')} | {entry.get('maturity', '')} | "
                f"`../{entry.get('path', '')}` | {entry.get('summary', '')} |"
            )
        lines.append("")
        (self.knowledge_root / "index" / "pattern_index.md").write_text("\n".join(lines), encoding="utf-8")

    def _render_lesson_index(self, lessons: list[Dict[str, Any]]) -> None:
        lines = [
            "# Lesson Index",
            "",
            "| Lesson | Domain | Trigger | Record |",
            "| --- | --- | --- | --- |",
        ]
        for entry in lessons:
            lines.append(
                f"| {entry.get('title', '')} | {entry.get('domain', '')} | {entry.get('trigger', '')} | "
                f"`../{entry.get('path', '')}` |"
            )
        lines.append("")
        (self.knowledge_root / "index" / "lesson_index.md").write_text("\n".join(lines), encoding="utf-8")

    def _render_proposal_queue(self, proposals: list[Dict[str, Any]]) -> None:
        skill_lines = []
        platform_lines = []
        for entry in proposals:
            target = skill_lines if entry.get("proposal_kind") == "skill" else platform_lines
            target.append(
                f"| {entry.get('title', '')} | {entry.get('domain', '')} | {entry.get('status', '')} | "
                f"`../{entry.get('path', '')}` | {entry.get('summary', '')} |"
            )
        lines = [
            "# Proposal Queue",
            "",
            "This file is the human-facing overview of possible hard landings.",
            "",
            "## Rule",
            "",
            "Items may appear here automatically as proposals.",
            "",
            "They do **not** become real `skills/` or `platform/` changes until the user explicitly approves them.",
            "",
            "## Skill Candidates",
            "",
            "| Proposal | Domain | Status | Record | Summary |",
            "| --- | --- | --- | --- | --- |",
            *(skill_lines or ["| - | - | - | - | - |"]),
            "",
            "## Platform Candidates",
            "",
            "| Proposal | Domain | Status | Record | Summary |",
            "| --- | --- | --- | --- | --- |",
            *(platform_lines or ["| - | - | - | - | - |"]),
            "",
        ]
        proposal_path = self.knowledge_root / "index" / "proposal_queue.md"
        proposal_path.write_text("\n".join(lines), encoding="utf-8")
        compatibility = [
            "# Promotion Queue",
            "",
            "This file is kept for compatibility.",
            "",
            "- See [proposal_queue.md](proposal_queue.md)",
            "",
        ]
        (self.knowledge_root / "index" / "promotion_queue.md").write_text("\n".join(compatibility), encoding="utf-8")

    def _render_ai_candidate_queue(self, candidates: list[Dict[str, Any]]) -> None:
        lines = [
            "# AI Candidate Queue",
            "",
            "This file lists strict-mode AI suggestions that are still isolated from the formal knowledge layer.",
            "",
            "| Candidate | Kind | Domain | Confidence | Record | Summary |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        if not candidates:
            lines.append("| - | - | - | - | - | - |")
        else:
            for entry in candidates:
                lines.append(
                    f"| {entry.get('title', '')} | {entry.get('kind', '')} | {entry.get('domain', '')} | "
                    f"{entry.get('confidence', '')} | `../{entry.get('path', '')}` | {entry.get('summary', '')} |"
                )
        lines.append("")
        self.ai_candidate_queue_path.write_text("\n".join(lines), encoding="utf-8")

    def _render_capability_auto_section(self, capabilities: list[Dict[str, Any]]) -> None:
        matrix_path = self.knowledge_root / "index" / "capability_matrix.md"
        if not matrix_path.exists():
            return
        text = matrix_path.read_text(encoding="utf-8")
        marker = "## Auto-Observed Capability Notes"
        prefix = text.split(marker, 1)[0].rstrip()
        lines = [
            marker,
            "",
            "| Capability Note | Domain | Maturity | Record | Main Boundaries |",
            "| --- | --- | --- | --- | --- |",
        ]
        managed = [entry for entry in capabilities if entry.get("managed")]
        for entry in managed:
            lines.append(
                f"| {entry.get('title', '')} | {entry.get('domain', '')} | {entry.get('maturity', '')} | "
                f"`../{entry.get('path', '')}` | {entry.get('boundaries', '') or 'See note'} |"
            )
        if not managed:
            lines.append("| - | - | - | - | - |")
        matrix_path.write_text(prefix + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")

    def _human_title(self, task_run: TaskRun) -> str:
        return task_run.description or Path(task_run.script_path).stem.replace("_", " ")
