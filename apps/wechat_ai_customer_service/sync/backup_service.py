"""Local-first backup package builder for shared and tenant data."""

from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.wechat_ai_customer_service.knowledge_paths import (
    SHARED_KNOWLEDGE_ROOT,
    TENANTS_ROOT,
    active_tenant_id,
    tenant_runtime_backups_root,
    tenant_root,
)

from .manifest import file_entry, stable_digest


DERIVED_DIRS = {"rag_chunks", "rag_index", "rag_cache"}
SKIP_SUFFIXES = {".tmp", ".lock"}


class BackupService:
    def __init__(self, *, output_root: Path | None = None) -> None:
        self.output_root = output_root

    def build_backup(
        self,
        *,
        scope: str = "tenant",
        tenant_id: str | None = None,
        include_derived: bool = False,
        include_runtime: bool = False,
    ) -> dict[str, Any]:
        scope = normalize_scope(scope)
        tenant = active_tenant_id(tenant_id)
        backup_id = "backup_" + stable_digest(f"{scope}:{tenant}:{now()}", 20)
        output_root = self.output_root or tenant_runtime_backups_root(tenant)
        output_root.mkdir(parents=True, exist_ok=True)
        package_path = output_root / f"{backup_id}.zip"

        files: list[dict[str, Any]] = []
        with zipfile.ZipFile(package_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            roots = self.roots_for_scope(scope, tenant)
            for label, root in roots:
                for path in iter_backup_files(root, include_derived=include_derived):
                    relative = path.relative_to(root).as_posix()
                    archive_path = f"payload/{label}/{relative}"
                    package.write(path, archive_path)
                    files.append(file_entry(path, relative_path=archive_path).to_dict())
            manifest = {
                "schema_version": 1,
                "backup_id": backup_id,
                "scope": scope,
                "tenant_id": tenant,
                "created_at": now(),
                "include_derived": include_derived,
                "include_runtime": include_runtime,
                "file_count": len(files),
                "files": sorted(files, key=lambda item: item["path"]),
            }
            package.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return {
            "ok": True,
            "backup_id": backup_id,
            "scope": scope,
            "tenant_id": tenant,
            "package_path": str(package_path),
            "bytes": package_path.stat().st_size,
            "manifest": manifest,
        }

    def roots_for_scope(self, scope: str, tenant_id: str) -> list[tuple[str, Path]]:
        if scope == "shared":
            return [("shared_knowledge", SHARED_KNOWLEDGE_ROOT)]
        if scope == "tenant":
            return [(f"tenants/{tenant_id}", tenant_root(tenant_id))]
        if scope == "all":
            roots = [("shared_knowledge", SHARED_KNOWLEDGE_ROOT)]
            if TENANTS_ROOT.exists():
                for path in sorted(item for item in TENANTS_ROOT.iterdir() if item.is_dir()):
                    roots.append((f"tenants/{path.name}", path))
            return roots
        raise ValueError(f"unsupported backup scope: {scope}")


def iter_backup_files(root: Path, *, include_derived: bool) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix in SKIP_SUFFIXES:
            continue
        if "__pycache__" in path.parts:
            continue
        if not include_derived and any(part in DERIVED_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return files


def normalize_scope(scope: str) -> str:
    value = str(scope or "tenant").strip().lower()
    if value not in {"tenant", "shared", "all"}:
        raise ValueError(f"unsupported backup scope: {scope}")
    return value


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")
