"""Local RAG auxiliary layer for WeChat customer-service knowledge.

The first implementation is intentionally offline-safe: it stores source/chunk
metadata and uses deterministic lexical retrieval. Embedding/vector backends can
be layered behind the same service later without changing the safety contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.knowledge_paths import (  # noqa: E402
    active_tenant_id,
    tenant_rag_cache_root,
    tenant_rag_chunks_root,
    tenant_rag_index_root,
    tenant_rag_sources_root,
)
from apps.wechat_ai_customer_service.storage import get_postgres_store, load_storage_config  # noqa: E402


SUPPORTED_SUFFIXES = {".txt", ".md", ".json", ".csv"}
DEFAULT_SOURCE_TYPES = {"upload", "chat_log", "product_doc", "policy_doc", "erp_export", "manual"}
HIGH_RISK_TERMS = {"最低价", "账期", "月结", "赔偿", "退款", "合同", "盖章", "安装费", "先发货", "虚开"}
RETRIEVAL_MODE = "hybrid_lexical_semantic"
SOURCE_TYPE_BOOSTS = {
    "product_doc": 0.045,
    "manual": 0.04,
    "policy_doc": 0.03,
    "erp_export": 0.02,
    "rag_experience": 0.02,
    "chat_log": -0.02,
}
CATEGORY_BOOSTS = {
    "product_explanations": 0.04,
    "product_faq": 0.035,
    "product_rules": 0.025,
    "products": 0.025,
    "policies": 0.015,
    "rag_experience": 0.01,
}
SEMANTIC_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    "公寓": ("酒店", "酒店公寓", "民宿", "长租公寓"),
    "民宿": ("酒店", "公寓", "酒店公寓", "客房"),
    "酒店": ("公寓", "民宿", "酒店公寓", "客房"),
    "客房": ("酒店", "民宿", "公寓", "酒店公寓"),
    "型号": ("型号命名", "型号说明", "命名规则", "规格型号"),
    "命名": ("型号命名", "型号说明", "命名规则"),
    "怎么看": ("说明", "解读", "命名规则", "型号说明"),
    "预留电源": ("供电方式", "电池", "外接电源", "电源"),
    "供电": ("供电方式", "电池", "外接电源", "电源"),
    "安装": ("安装前", "门厚", "开孔", "开门方向", "锁体"),
    "门厚": ("安装", "开孔", "锁体", "开门方向"),
    "开孔": ("安装", "门厚", "锁体", "开门方向"),
    "适合": ("适用", "场景", "用途", "适配"),
    "场景": ("适合", "适用", "用途", "适配"),
    "办公": ("办公室", "会议室", "企业", "办公场景"),
    "午休": ("午睡", "折叠床", "办公室", "临时休息"),
    "净水": ("饮水", "过滤", "滤芯", "水质"),
}


class RagService:
    def __init__(
        self,
        *,
        tenant_id: str | None = None,
        sources_root: Path | None = None,
        chunks_root: Path | None = None,
        index_root: Path | None = None,
        cache_root: Path | None = None,
    ) -> None:
        self.tenant_id = active_tenant_id(tenant_id)
        self.sources_root = sources_root or tenant_rag_sources_root(self.tenant_id)
        self.chunks_root = chunks_root or tenant_rag_chunks_root(self.tenant_id)
        self.index_root = index_root or tenant_rag_index_root(self.tenant_id)
        self.cache_root = cache_root or tenant_rag_cache_root(self.tenant_id)

    @property
    def sources_path(self) -> Path:
        return self.sources_root / "sources.json"

    @property
    def index_path(self) -> Path:
        return self.index_root / "index.json"

    def ensure_dirs(self) -> None:
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.initialize_schema()
            if not config.mirror_files:
                return
        for root in (self.sources_root, self.chunks_root, self.index_root, self.cache_root):
            root.mkdir(parents=True, exist_ok=True)
        for name in ("uploads", "chat_logs", "product_docs", "policy_docs", "erp_exports"):
            (self.sources_root / name).mkdir(parents=True, exist_ok=True)

    def ingest_file(
        self,
        path: Path,
        *,
        source_type: str = "upload",
        category: str = "",
        product_id: str = "",
        layer: str = "tenant",
        rebuild_index: bool = True,
    ) -> dict[str, Any]:
        self.ensure_dirs()
        path = Path(path)
        text = read_source_text(path)
        if not text.strip():
            return {"ok": False, "message": "source has no readable text", "path": str(path)}
        source_type = normalize_source_type(source_type)
        content_hash = stable_digest(text, 32)
        source_id = "source_" + stable_digest(f"{self.tenant_id}:{path}:{source_type}:{category}:{product_id}:{content_hash}", 16)
        now_text = now()
        source_record = {
            "source_id": source_id,
            "tenant_id": self.tenant_id,
            "layer": layer or "tenant",
            "source_type": source_type,
            "category": category or infer_category_from_path(path),
            "product_id": product_id or "",
            "source_path": str(path),
            "content_hash": content_hash,
            "status": "active",
            "created_at": now_text,
            "updated_at": now_text,
        }
        chunks = build_chunks(
            text,
            source=source_record,
        )
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.upsert_rag_source(source_record)
            db.replace_rag_chunks(source_id, chunks)
            result = {
                "ok": True,
                "source": source_record,
                "source_id": source_id,
                "chunk_count": len(chunks),
                "chunks_path": str(self.chunks_root / f"{source_id}.json"),
            }
            if rebuild_index:
                result["index"] = self.rebuild_index()
            if not config.mirror_files:
                return result
        self.write_source(source_record)
        chunks_path = self.chunks_root / f"{source_id}.json"
        chunks_path.write_text(json.dumps({"source": source_record, "chunks": chunks}, ensure_ascii=False, indent=2), encoding="utf-8")
        result = {
            "ok": True,
            "source": source_record,
            "source_id": source_id,
            "chunk_count": len(chunks),
            "chunks_path": str(chunks_path),
        }
        if rebuild_index:
            result["index"] = self.rebuild_index()
        return result

    def write_source(self, source_record: dict[str, Any]) -> None:
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.upsert_rag_source(source_record)
            if not config.mirror_files:
                return
        records = self.list_sources()
        records = [item for item in records if item.get("source_id") != source_record.get("source_id")]
        records.append(source_record)
        records.sort(key=lambda item: (str(item.get("source_type") or ""), str(item.get("source_id") or "")))
        self.sources_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_sources(self) -> list[dict[str, Any]]:
        db = postgres_store(self.tenant_id)
        if db:
            records = db.list_rag_sources(self.tenant_id)
            if records:
                return records
        if not self.sources_path.exists():
            return []
        return json.loads(self.sources_path.read_text(encoding="utf-8"))

    def delete_source_by_path(self, source_path: Path) -> dict[str, Any]:
        target = str(Path(source_path))
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            deleted_sources = db.delete_rag_source_by_path(self.tenant_id, target)
            self.rebuild_index()
            if not config.mirror_files:
                return {"ok": True, "deleted_sources": deleted_sources, "deleted_chunks": 0}
        records = self.list_sources()
        matched = [item for item in records if str(item.get("source_path") or "") == target]
        if not matched:
            return {"ok": True, "deleted_sources": 0, "deleted_chunks": 0}
        remaining = [item for item in records if str(item.get("source_path") or "") != target]
        self.ensure_dirs()
        self.sources_path.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
        deleted_chunks = 0
        for item in matched:
            chunks_path = self.chunks_root / f"{item.get('source_id')}.json"
            if chunks_path.exists():
                chunks_path.unlink()
                deleted_chunks += 1
        self.rebuild_index()
        return {"ok": True, "deleted_sources": len(matched), "deleted_chunks": deleted_chunks}

    def iter_chunks(self) -> list[dict[str, Any]]:
        db = postgres_store(self.tenant_id)
        if db:
            chunks = db.list_rag_chunks(self.tenant_id)
            chunks.extend(self.iter_experience_chunks())
            if chunks:
                return chunks
        chunks: list[dict[str, Any]] = []
        if not self.chunks_root.exists():
            chunks.extend(self.iter_experience_chunks())
            return chunks
        for path in sorted(self.chunks_root.glob("source_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for chunk in payload.get("chunks", []) or []:
                if chunk.get("status", "active") == "active":
                    chunks.append(chunk)
        chunks.extend(self.iter_experience_chunks())
        return chunks

    def iter_experience_chunks(self) -> list[dict[str, Any]]:
        try:
            from apps.wechat_ai_customer_service.workflows.rag_experience_store import RagExperienceStore
        except Exception:
            return []
        store = RagExperienceStore(tenant_id=self.tenant_id)
        chunks: list[dict[str, Any]] = []
        for item in store.list(status="active", limit=500):
            text = build_experience_chunk_text(item)
            if not text.strip():
                continue
            experience_id = str(item.get("experience_id") or "")
            hit = item.get("rag_hit", {}) or {}
            chunks.append(
                {
                    "chunk_id": "chunk_" + stable_digest(f"rag_experience:{experience_id}:{text}", 16),
                    "source_id": experience_id,
                    "tenant_id": self.tenant_id,
                    "layer": "rag_experience",
                    "source_type": "rag_experience",
                    "category": "rag_experience",
                    "product_id": hit.get("product_id") or "",
                    "source_path": str(store.path),
                    "chunk_index": 0,
                    "text": text,
                    "char_count": len(text),
                    "status": "active",
                    "created_at": item.get("created_at") or now(),
                }
            )
        return chunks

    def rebuild_index(self) -> dict[str, Any]:
        self.ensure_dirs()
        chunks = self.iter_chunks()
        entries = []
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            terms = sorted(tokenize(text))
            semantic_terms = sorted(expand_semantic_terms(text, terms))
            entries.append(
                {
                    **chunk,
                    "terms": terms,
                    "semantic_terms": semantic_terms,
                    "term_count": len(terms),
                    "semantic_term_count": len(semantic_terms),
                    "risk_terms": sorted(term for term in HIGH_RISK_TERMS if term in text),
                }
            )
        payload = {
            "schema_version": 1,
            "tenant_id": self.tenant_id,
            "built_at": now(),
            "entry_count": len(entries),
            "entries": entries,
        }
        db = postgres_store(self.tenant_id)
        config = load_storage_config()
        if db:
            db.replace_rag_index(self.tenant_id, entries)
            if not config.mirror_files:
                return {"ok": True, "index_path": f"postgres://{db.schema}.rag_index_entries", "entry_count": len(entries)}
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "index_path": str(self.index_path), "entry_count": len(entries)}

    def load_index(self) -> dict[str, Any]:
        db = postgres_store(self.tenant_id)
        if db:
            entries = db.list_rag_index(self.tenant_id)
            if not entries:
                self.rebuild_index()
                entries = db.list_rag_index(self.tenant_id)
            return {"schema_version": 1, "tenant_id": self.tenant_id, "entries": entries, "built_at": "postgres"}
        if not self.index_path.exists() or self.index_is_stale():
            self.rebuild_index()
        if not self.index_path.exists():
            return {"schema_version": 1, "tenant_id": self.tenant_id, "entries": []}
        return json.loads(self.index_path.read_text(encoding="utf-8"))

    def index_is_stale(self) -> bool:
        if postgres_store(self.tenant_id):
            return False
        if not self.index_path.exists():
            return True
        index_mtime = self.index_path.stat().st_mtime
        candidates = list(self.chunks_root.glob("source_*.json")) if self.chunks_root.exists() else []
        try:
            from apps.wechat_ai_customer_service.workflows.rag_experience_store import RagExperienceStore

            experience_path = RagExperienceStore(tenant_id=self.tenant_id).path
            if experience_path.exists():
                candidates.append(experience_path)
        except Exception:
            pass
        return any(path.exists() and path.stat().st_mtime > index_mtime for path in candidates)

    def search(
        self,
        query: str,
        *,
        product_id: str = "",
        category: str = "",
        source_type: str = "",
        limit: int = 6,
    ) -> dict[str, Any]:
        query_text = str(query or "").strip()
        if not query_text:
            return {"ok": True, "query": query_text, "hits": [], "confidence": 0.0}
        index = self.load_index()
        query_profile = build_query_profile(query_text)
        hits: list[dict[str, Any]] = []
        for entry in index.get("entries", []) or []:
            if product_id and str(entry.get("product_id") or "") not in {"", product_id}:
                continue
            if category and str(entry.get("category") or "") != category:
                continue
            if source_type and str(entry.get("source_type") or "") != source_type:
                continue
            scoring = score_entry(query_text, query_profile, entry, product_id=product_id)
            score = float(scoring.get("final", 0.0))
            if score <= 0:
                continue
            hit = {
                "chunk_id": entry.get("chunk_id"),
                "source_id": entry.get("source_id"),
                "score": round(score, 4),
                "retrieval_mode": RETRIEVAL_MODE,
                "scoring": scoring,
                "text": entry.get("text"),
                "source_path": entry.get("source_path"),
                "layer": entry.get("layer"),
                "source_type": entry.get("source_type"),
                "category": entry.get("category"),
                "product_id": entry.get("product_id"),
                "risk_terms": entry.get("risk_terms", []),
            }
            hits.append(hit)
        hits.sort(key=lambda item: item["score"], reverse=True)
        hits = hits[: max(1, min(int(limit or 6), 20))]
        confidence = hits[0]["score"] if hits else 0.0
        return {
            "ok": True,
            "query": query_text,
            "query_profile": compact_query_profile(query_profile),
            "tenant_id": self.tenant_id,
            "hits": hits,
            "confidence": round(float(confidence), 4),
            "confidence_band": confidence_band(float(confidence)),
            "retrieval_mode": RETRIEVAL_MODE,
            "rag_can_authorize": False,
            "structured_priority": True,
        }

    def evidence(
        self,
        query: str,
        *,
        context: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        context = context or {}
        result = self.search(
            query,
            product_id=str(context.get("last_product_id") or context.get("product_id") or ""),
            limit=limit,
        )
        return {
            "enabled": True,
            "query": result.get("query"),
            "tenant_id": self.tenant_id,
            "hits": result.get("hits", []),
            "confidence": result.get("confidence", 0.0),
            "rag_can_authorize": False,
            "structured_priority": True,
        }

    def status(self) -> dict[str, Any]:
        db = postgres_store(self.tenant_id)
        if db:
            sources = db.list_rag_sources(self.tenant_id)
            chunks = db.list_rag_chunks(self.tenant_id)
            index_entries = db.list_rag_index(self.tenant_id)
            return {
                "ok": True,
                "tenant_id": self.tenant_id,
                "backend": "postgres",
                "schema": db.schema,
                "sources_root": str(self.sources_root),
                "chunks_root": str(self.chunks_root),
                "index_root": str(self.index_root),
                "cache_root": str(self.cache_root),
                "source_count": len(sources),
                "chunk_count": len(chunks),
                "index_entry_count": len(index_entries),
                "index_exists": bool(index_entries),
                "index_path": f"postgres://{db.schema}.rag_index_entries",
                "updated_at": "postgres",
            }
        sources = self.list_sources()
        chunks = self.iter_chunks()
        index = self.load_index() if self.index_path.exists() else {"entries": []}
        return {
            "ok": True,
            "tenant_id": self.tenant_id,
            "sources_root": str(self.sources_root),
            "chunks_root": str(self.chunks_root),
            "index_root": str(self.index_root),
            "cache_root": str(self.cache_root),
            "source_count": len(sources),
            "chunk_count": len(chunks),
            "index_entry_count": len(index.get("entries", []) or []),
            "index_exists": self.index_path.exists(),
            "index_path": str(self.index_path),
            "updated_at": str(index.get("built_at") or ""),
        }


def read_source_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return path.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def build_chunks(text: str, *, source: dict[str, Any], max_chars: int = 900, overlap: int = 120) -> list[dict[str, Any]]:
    normalized = normalize_text_block(text)
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]
    if not paragraphs:
        paragraphs = [normalized]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = (current + "\n\n" + paragraph).strip()
            continue
        if current:
            chunks.append(current)
        current = paragraph
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max(0, max_chars - overlap) :]
    if current:
        chunks.append(current)

    result = []
    for index, chunk_text in enumerate(chunks):
        chunk_id = "chunk_" + stable_digest(f"{source.get('source_id')}:{index}:{chunk_text}", 16)
        result.append(
            {
                "chunk_id": chunk_id,
                "source_id": source.get("source_id"),
                "tenant_id": source.get("tenant_id"),
                "layer": source.get("layer"),
                "source_type": source.get("source_type"),
                "category": source.get("category"),
                "product_id": source.get("product_id"),
                "source_path": source.get("source_path"),
                "chunk_index": index,
                "text": chunk_text,
                "char_count": len(chunk_text),
                "status": "active",
                "created_at": source.get("created_at") or now(),
            }
        )
    return result


def build_experience_chunk_text(item: dict[str, Any]) -> str:
    hit = item.get("rag_hit", {}) or {}
    parts = [
        f"RAG经验概括：{item.get('summary') or ''}",
        f"客户问法：{item.get('question') or ''}",
        f"历史回复要点：{item.get('reply_text') or ''}",
    ]
    hit_text = str(hit.get("text") or "").strip()
    if hit_text:
        parts.append(f"当时命中的资料：{hit_text}")
    product_id = str(hit.get("product_id") or "").strip()
    if product_id:
        parts.append(f"关联商品：{product_id}")
    return normalize_text_block("\n".join(parts))


def normalize_text_block(text: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in str(text or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def tokenize(text: str) -> set[str]:
    normalized = str(text or "").lower()
    tokens = set(re.findall(r"[a-z0-9_.-]{2,}", normalized, flags=re.IGNORECASE))
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    for run in cjk_runs:
        tokens.add(run)
        for size in (2, 3, 4):
            if len(run) >= size:
                for index in range(0, len(run) - size + 1):
                    tokens.add(run[index : index + size])
    return {token for token in tokens if token.strip()}


def build_query_profile(query: str) -> dict[str, Any]:
    query_text = normalize_search_text(query)
    terms = tokenize(query_text)
    expanded_terms = expand_semantic_terms(query_text, terms)
    variants = sorted(build_query_variants(query_text, expanded_terms))
    variant_terms = set(terms)
    for variant in variants:
        variant_terms.update(tokenize(variant))
    expanded_terms.update(variant_terms)
    return {
        "text": query_text,
        "terms": terms,
        "expanded_terms": expanded_terms,
        "variants": variants,
    }


def build_query_variants(query: str, expanded_terms: set[str]) -> set[str]:
    variants = {query}
    for term in sorted(expanded_terms, key=len, reverse=True):
        if term and term in query:
            for equivalent in semantic_equivalents(term):
                variants.add(query.replace(term, equivalent))
    return {variant for variant in variants if variant.strip()}


def expand_semantic_terms(text: str, terms: set[str] | list[str] | tuple[str, ...] | None = None) -> set[str]:
    base = set(terms or tokenize(text))
    normalized = normalize_search_text(text)
    expanded = set(base)
    for term in list(base):
        expanded.update(semantic_equivalents(term))
    for term, equivalents in SEMANTIC_EQUIVALENTS.items():
        if term in normalized:
            expanded.add(term)
            expanded.update(equivalents)
        elif any(equivalent in normalized for equivalent in equivalents):
            expanded.add(term)
            expanded.update(equivalents)
    return {normalize_search_text(item) for item in expanded if normalize_search_text(item)}


def semantic_equivalents(term: str) -> set[str]:
    normalized = normalize_search_text(term)
    equivalents = set(SEMANTIC_EQUIVALENTS.get(normalized, ()))
    for key, values in SEMANTIC_EQUIVALENTS.items():
        if normalized in values:
            equivalents.add(key)
            equivalents.update(values)
    equivalents.discard(normalized)
    return {normalize_search_text(item) for item in equivalents if normalize_search_text(item)}


def score_entry(query: str, query_profile: dict[str, Any] | set[str], entry: dict[str, Any], *, product_id: str = "") -> dict[str, float]:
    text = str(entry.get("text") or "").lower()
    if isinstance(query_profile, set):
        query_profile = {"text": normalize_search_text(query), "terms": query_profile, "expanded_terms": set(query_profile), "variants": [query]}
    query_text = str(query_profile.get("text") or normalize_search_text(query))
    query_terms = set(query_profile.get("terms", set()) or set())
    expanded_query_terms = set(query_profile.get("expanded_terms", set()) or query_terms)
    entry_terms = set(entry.get("terms", []) or [])
    if not entry_terms:
        entry_terms = tokenize(text)
    entry_semantic_terms = set(entry.get("semantic_terms", []) or [])
    if not entry_semantic_terms:
        entry_semantic_terms = expand_semantic_terms(text, entry_terms)
    overlap = query_terms & entry_terms
    semantic_overlap = expanded_query_terms & (entry_terms | entry_semantic_terms)
    variants = [str(item).lower() for item in query_profile.get("variants", []) or [] if str(item).strip()]
    phrase_match = query_text and query_text in text
    variant_match = any(variant and variant in text for variant in variants)
    if not overlap and not semantic_overlap and not phrase_match and not variant_match:
        return empty_scoring()
    coverage = len(overlap) / max(1, len(query_terms))
    density = len(overlap) / math.sqrt(max(1, len(entry_terms)))
    semantic_coverage = len(semantic_overlap) / max(1, len(expanded_query_terms))
    semantic_density = len(semantic_overlap) / math.sqrt(max(1, len(entry_semantic_terms | entry_terms)))
    phrase_bonus = 0.16 if phrase_match else 0.08 if variant_match else 0.0
    product_bonus = 0.15 if product_id and str(entry.get("product_id") or "") == product_id else 0.0
    boost = SOURCE_TYPE_BOOSTS.get(str(entry.get("source_type") or ""), 0.0) + CATEGORY_BOOSTS.get(str(entry.get("category") or ""), 0.0)
    risk_penalty = 0.08 if entry.get("risk_terms") else 0.0
    lexical = coverage * 0.46 + min(0.16, density)
    semantic = semantic_coverage * 0.2 + min(0.12, semantic_density)
    final = lexical + semantic + phrase_bonus + product_bonus + boost - risk_penalty
    return {
        "lexical": round(max(0.0, lexical), 4),
        "semantic": round(max(0.0, semantic), 4),
        "phrase": round(max(0.0, phrase_bonus), 4),
        "product": round(max(0.0, product_bonus), 4),
        "boost": round(boost, 4),
        "risk_penalty": round(risk_penalty, 4),
        "final": round(min(0.99, max(0.0, final)), 4),
    }


def empty_scoring() -> dict[str, float]:
    return {
        "lexical": 0.0,
        "semantic": 0.0,
        "phrase": 0.0,
        "product": 0.0,
        "boost": 0.0,
        "risk_penalty": 0.0,
        "final": 0.0,
    }


def compact_query_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "terms": sorted(profile.get("terms", set()) or [])[:40],
        "expanded_terms": sorted(profile.get("expanded_terms", set()) or [])[:60],
        "variants": sorted(profile.get("variants", []) or [])[:12],
    }


def confidence_band(score: float) -> str:
    if score >= 0.62:
        return "high"
    if score >= 0.28:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def normalize_search_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def infer_category_from_path(path: Path) -> str:
    parts = {part.lower() for part in path.parts}
    for category in ("products", "chats", "policies", "erp_exports"):
        if category in parts:
            return category
    return ""


def normalize_source_type(value: str) -> str:
    text = str(value or "upload").strip()
    return text if text in DEFAULT_SOURCE_TYPES else "upload"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_digest(value: str, length: int = 16) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:length]


def compact_hits(hits: list[dict[str, Any]], *, limit: int = 3, text_limit: int = 260) -> list[dict[str, Any]]:
    compacted = []
    for hit in hits[:limit]:
        compacted.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "source_id": hit.get("source_id"),
                "score": hit.get("score"),
                "category": hit.get("category"),
                "product_id": hit.get("product_id"),
                "retrieval_mode": hit.get("retrieval_mode"),
                "scoring": hit.get("scoring", {}),
                "text": str(hit.get("text") or "")[:text_limit],
            }
        )
    return compacted


def postgres_store(tenant_id: str):
    config = load_storage_config()
    if not config.use_postgres or not config.postgres_configured:
        return None
    store = get_postgres_store(tenant_id=tenant_id, config=config)
    return store if store.available() else None
