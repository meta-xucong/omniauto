"""Path helpers for layered WeChat customer-service knowledge."""

from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = APP_ROOT / "data"
LEGACY_KNOWLEDGE_BASE_ROOT = DATA_ROOT / "knowledge_bases"
SHARED_KNOWLEDGE_ROOT = DATA_ROOT / "shared_knowledge"
TENANTS_ROOT = DATA_ROOT / "tenants"
DEFAULT_TENANT_ID = "default"


def active_tenant_id(value: str | None = None) -> str:
    tenant_id = (value or os.getenv("WECHAT_KNOWLEDGE_TENANT") or DEFAULT_TENANT_ID).strip()
    return tenant_id or DEFAULT_TENANT_ID


def tenant_root(tenant_id: str | None = None) -> Path:
    return TENANTS_ROOT / active_tenant_id(tenant_id)


def tenant_knowledge_base_root(tenant_id: str | None = None) -> Path:
    return tenant_root(tenant_id) / "knowledge_bases"


def tenant_product_item_knowledge_root(tenant_id: str | None = None) -> Path:
    return tenant_root(tenant_id) / "product_item_knowledge"


def tenant_rag_root(tenant_id: str | None = None) -> Path:
    return tenant_root(tenant_id)


def tenant_rag_sources_root(tenant_id: str | None = None) -> Path:
    return tenant_rag_root(tenant_id) / "rag_sources"


def tenant_rag_chunks_root(tenant_id: str | None = None) -> Path:
    return tenant_rag_root(tenant_id) / "rag_chunks"


def tenant_rag_index_root(tenant_id: str | None = None) -> Path:
    return tenant_rag_root(tenant_id) / "rag_index"


def tenant_rag_cache_root(tenant_id: str | None = None) -> Path:
    return tenant_rag_root(tenant_id) / "rag_cache"


def default_admin_knowledge_base_root(tenant_id: str | None = None) -> Path:
    root = tenant_knowledge_base_root(tenant_id)
    if (root / "registry.json").exists():
        return root
    return LEGACY_KNOWLEDGE_BASE_ROOT


def runtime_knowledge_roots(tenant_id: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if (SHARED_KNOWLEDGE_ROOT / "registry.json").exists():
        roots.append(SHARED_KNOWLEDGE_ROOT)
    tenant_root_path = tenant_knowledge_base_root(tenant_id)
    if (tenant_root_path / "registry.json").exists():
        roots.append(tenant_root_path)
    elif (LEGACY_KNOWLEDGE_BASE_ROOT / "registry.json").exists():
        roots.append(LEGACY_KNOWLEDGE_BASE_ROOT)
    return roots
