"""Admin-facing wrapper for the local RAG auxiliary layer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_ROOT = APP_ROOT / "workflows"
if str(WORKFLOWS_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOWS_ROOT))

from rag_layer import RagService  # noqa: E402
from rag_experience_store import RagExperienceStore  # noqa: E402
from rag_operations import RagOperationsAnalyzer  # noqa: E402


class RagAdminService:
    def __init__(self) -> None:
        self.rag = RagService()
        self.experiences = RagExperienceStore()
        self.operations = RagOperationsAnalyzer(rag_service=self.rag, experience_store=self.experiences)

    def status(self) -> dict[str, Any]:
        payload = self.rag.status()
        payload["experience_counts"] = self.experiences.counts()
        return payload

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.rag.search(
            str(payload.get("query") or ""),
            product_id=str(payload.get("product_id") or ""),
            category=str(payload.get("category") or ""),
            source_type=str(payload.get("source_type") or ""),
            limit=int(payload.get("limit") or 6),
        )

    def rebuild(self) -> dict[str, Any]:
        return self.rag.rebuild_index()

    def analytics(self) -> dict[str, Any]:
        return self.operations.report()

    def list_experiences(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        status = str(payload.get("status") or "active")
        limit = int(payload.get("limit") or 100)
        return {
            "ok": True,
            "items": self.experiences.list(status=status, limit=limit),
            "counts": self.experiences.counts(),
            "formal_knowledge_policy": "rag_experience_only_not_formal_knowledge",
        }

    def discard_experience(self, experience_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        item = self.experiences.discard(experience_id, reason=str(payload.get("reason") or "discarded in admin"))
        index = self.rag.rebuild_index()
        return {"ok": True, "item": item, "index": index}
