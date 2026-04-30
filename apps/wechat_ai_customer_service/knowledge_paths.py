"""Path helpers for layered WeChat customer-service knowledge."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Iterator


APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = APP_ROOT / "data"
LEGACY_KNOWLEDGE_BASE_ROOT = DATA_ROOT / "knowledge_bases"
SHARED_KNOWLEDGE_ROOT = DATA_ROOT / "shared_knowledge"
TENANTS_ROOT = DATA_ROOT / "tenants"
DEFAULT_TENANT_ID = "default"
SAFE_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ACTIVE_TENANT: ContextVar[str | None] = ContextVar("wechat_active_tenant_id", default=None)


def active_tenant_id(value: str | None = None) -> str:
    tenant_id = (value or _ACTIVE_TENANT.get() or os.getenv("WECHAT_KNOWLEDGE_TENANT") or DEFAULT_TENANT_ID).strip()
    return normalize_tenant_id(tenant_id)


def normalize_tenant_id(value: str | None) -> str:
    tenant_id = (value or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    if not SAFE_TENANT_ID_RE.fullmatch(tenant_id):
        raise ValueError(f"unsafe tenant id: {tenant_id}")
    return tenant_id


def set_active_tenant_id(tenant_id: str | None) -> Token[str | None]:
    return _ACTIVE_TENANT.set(active_tenant_id(tenant_id))


def reset_active_tenant_id(token: Token[str | None]) -> None:
    _ACTIVE_TENANT.reset(token)


@contextmanager
def tenant_context(tenant_id: str | None) -> Iterator[str]:
    token = set_active_tenant_id(tenant_id)
    try:
        yield active_tenant_id()
    finally:
        reset_active_tenant_id(token)


def tenant_root(tenant_id: str | None = None) -> Path:
    return TENANTS_ROOT / active_tenant_id(tenant_id)


def tenant_metadata_path(tenant_id: str | None = None) -> Path:
    return tenant_root(tenant_id) / "tenant.json"


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


def tenant_sync_root(tenant_id: str | None = None) -> Path:
    return tenant_root(tenant_id) / "sync"


def shared_proposals_root() -> Path:
    return SHARED_KNOWLEDGE_ROOT / "proposals"


def shared_patches_root() -> Path:
    return SHARED_KNOWLEDGE_ROOT / "patches"


def runtime_app_root() -> Path:
    return APP_ROOT.parents[1] / "runtime" / "apps" / "wechat_ai_customer_service"


def tenant_runtime_root(tenant_id: str | None = None) -> Path:
    return runtime_app_root() / "tenants" / active_tenant_id(tenant_id)


def tenant_runtime_admin_root(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "admin"


def tenant_runtime_state_root(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "state"


def tenant_runtime_logs_root(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "logs"


def tenant_runtime_backups_root(tenant_id: str | None = None) -> Path:
    return tenant_runtime_root(tenant_id) / "backups"


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
