"""Learning jobs that turn raw uploads into review candidates."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit_log import append_audit
from .knowledge_deduper import KnowledgeDeduper
from .upload_store import UploadStore


APP_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = APP_ROOT.parents[1]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
PENDING_ROOT = APP_ROOT / "data" / "review_candidates" / "pending"
JOBS_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "admin" / "jobs"
if str(WORKFLOWS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOWS_ROOT))

from generate_review_candidates import build_candidates  # noqa: E402
from rag_layer import RagService, compact_hits  # noqa: E402


class LearningService:
    def __init__(self) -> None:
        self.uploads = UploadStore()
        self.deduper = KnowledgeDeduper()
        self.rag = RagService()

    def create_job(self, upload_ids: list[str], *, use_llm: bool = False) -> dict[str, Any]:
        job_id = "job_" + uuid.uuid4().hex[:12]
        selected_uploads = [item for item in self.uploads.list_uploads() if item.get("upload_id") in upload_ids] if upload_ids else []
        candidates = []
        skipped_duplicates = []
        PENDING_ROOT.mkdir(parents=True, exist_ok=True)
        for upload in selected_uploads:
            upload_path = Path(str(upload.get("path") or ""))
            if upload_path.exists():
                rag_ingest = self.rag.ingest_file(
                    upload_path,
                    source_type="upload",
                    category=str(upload.get("kind") or ""),
                    rebuild_index=True,
                )
            else:
                rag_ingest = {"ok": False, "message": "source file is missing", "path": str(upload_path)}
            upload_candidates = build_candidates(upload_path, use_llm=use_llm)
            if not upload_candidates:
                continue
            upload_candidate_ids = []
            for candidate in upload_candidates:
                candidate.setdefault("review", {})["source_upload_id"] = upload.get("upload_id")
                attach_rag_evidence(candidate, self.rag, rag_ingest)
                duplicate = self.deduper.check_candidate(candidate)
                if duplicate.get("duplicate"):
                    candidate.setdefault("review", {}).update(
                        {
                            "status": "skipped_duplicate",
                            "duplicate": duplicate,
                            "updated_at": datetime.now().isoformat(timespec="seconds"),
                        }
                    )
                    skipped_duplicates.append(
                        {
                            "candidate_id": candidate.get("candidate_id"),
                            "upload_id": upload.get("upload_id"),
                            "duplicate": duplicate,
                        }
                    )
                    continue
                output_path = PENDING_ROOT / f"{candidate['candidate_id']}.json"
                output_path.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                candidates.append(candidate)
                upload_candidate_ids.append(str(candidate.get("candidate_id")))
            self.uploads.mark_learned([str(upload.get("upload_id"))], upload_candidate_ids)
        candidate_ids = [str(item.get("candidate_id")) for item in candidates]
        job = {
            "job_id": job_id,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "status": "completed",
            "upload_ids": upload_ids,
            "use_llm": use_llm,
            "candidate_ids": candidate_ids,
            "candidate_count": len(candidates),
            "skipped_duplicate_count": len(skipped_duplicates),
            "skipped_duplicates": skipped_duplicates,
        }
        self.write_job(job)
        append_audit(
            "learning_started",
            {
                "job_id": job_id,
                "upload_ids": upload_ids,
                "candidate_count": len(candidates),
                "skipped_duplicate_count": len(skipped_duplicates),
            },
        )
        return {"ok": True, "job": job, "candidates": candidates}

    def list_jobs(self) -> list[dict[str, Any]]:
        if not JOBS_ROOT.exists():
            return []
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(JOBS_ROOT.glob("*.json"), reverse=True)]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        path = JOBS_ROOT / f"{job_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def write_job(self, job: dict[str, Any]) -> None:
        JOBS_ROOT.mkdir(parents=True, exist_ok=True)
        (JOBS_ROOT / f"{job['job_id']}.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def attach_rag_evidence(candidate: dict[str, Any], rag: RagService, ingest_result: dict[str, Any]) -> None:
    if not ingest_result.get("ok"):
        candidate.setdefault("review", {})["rag_evidence"] = {"enabled": True, "ok": False, "message": ingest_result.get("message")}
        return
    query = candidate_query(candidate)
    search = rag.search(query, limit=4)
    evidence = {
        "enabled": True,
        "ok": bool(search.get("ok")),
        "source_id": ingest_result.get("source_id"),
        "chunk_count": ingest_result.get("chunk_count", 0),
        "query": query,
        "hits": compact_hits(search.get("hits", []), limit=4),
        "rag_can_authorize": False,
        "structured_priority": True,
    }
    candidate.setdefault("review", {})["rag_evidence"] = evidence
    candidate.setdefault("source", {})["rag_hits"] = evidence["hits"]


def candidate_query(candidate: dict[str, Any]) -> str:
    proposal = candidate.get("proposal") if isinstance(candidate.get("proposal"), dict) else {}
    source = candidate.get("source") if isinstance(candidate.get("source"), dict) else {}
    patch = proposal.get("formal_patch") if isinstance(proposal.get("formal_patch"), dict) else {}
    item = patch.get("item") if isinstance(patch.get("item"), dict) else {}
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    parts = [
        proposal.get("summary"),
        source.get("evidence_excerpt"),
        data.get("name"),
        data.get("title"),
        data.get("answer"),
        data.get("service_reply"),
    ]
    return "\n".join(str(part) for part in parts if part not in (None, "", [], {}))[:1200]
