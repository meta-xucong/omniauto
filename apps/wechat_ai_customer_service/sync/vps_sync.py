"""VPS-LOCAL coordination service."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
from typing import Any
from urllib.parse import urlencode

from apps.wechat_ai_customer_service.auth.vps_client import VpsAuthClient, VpsClientError
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, runtime_app_root
from apps.wechat_ai_customer_service.vps_admin.local_data import build_shared_knowledge_snapshot

from .backup_service import BackupService


class VpsLocalSyncService:
    def __init__(self, *, vps_base_url: str | None = None, backup_service: BackupService | None = None) -> None:
        base_url = (vps_base_url if vps_base_url is not None else os.getenv("WECHAT_VPS_BASE_URL") or "").strip().rstrip("/")
        self.vps = VpsAuthClient(base_url=base_url, timeout_seconds=float(os.getenv("WECHAT_VPS_TIMEOUT_SECONDS") or "8"))
        self.backups = backup_service or BackupService()

    def status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)
        node_cache = self.read_node_cache()
        return {
            "ok": True,
            "tenant_id": tenant,
            "vps_configured": self.vps.configured,
            "mode": "online_configured" if self.vps.configured else "offline_unconfigured",
            "runtime_root": str(runtime_app_root()),
            "node": node_cache,
            "supported_commands": ["backup_all", "backup_tenant", "pull_shared_patch", "check_update", "restore_backup", "push_update"],
        }

    def register_node(self, *, token: str = "", tenant_id: str | None = None, display_name: str = "") -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)
        if not self.vps.configured:
            return {"ok": True, "mode": "offline_unconfigured", "tenant_id": tenant, "node": None}
        node_id = str(os.getenv("WECHAT_LOCAL_NODE_ID") or stable_local_node_id()).strip()
        payload = {
            "node_id": node_id,
            "display_name": display_name or f"{socket.gethostname()} Local 客户端",
            "tenant_ids": [tenant],
            "version": os.getenv("WECHAT_LOCAL_APP_VERSION") or "local-dev",
            "capabilities": ["backup_tenant", "backup_all", "pull_shared_patch", "check_update", "restore_backup", "push_update"],
            "metadata": {
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "runtime_root": str(runtime_app_root()),
            },
        }
        try:
            response = self.vps.post_json("/v1/local/nodes/register", payload, token=token)
        except VpsClientError as exc:
            return {"ok": False, "tenant_id": tenant, "node_id": node_id, "error": str(exc)}
        node = response.get("node") if isinstance(response.get("node"), dict) else response
        self.write_node_cache(node if isinstance(node, dict) else {"node_id": node_id})
        return {"ok": True, "tenant_id": tenant, "node": node}

    def read_node_cache(self) -> dict[str, Any]:
        path = local_node_cache_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def write_node_cache(self, node: dict[str, Any]) -> None:
        path = local_node_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(node, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)

    def poll_commands(
        self,
        *,
        token: str = "",
        tenant_id: str | None = None,
        node_id: str | None = None,
        node_token: str | None = None,
    ) -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)
        if not self.vps.configured:
            return {"ok": True, "tenant_id": tenant, "mode": "offline_unconfigured", "commands": [], "results": []}
        node = str(node_id or os.getenv("WECHAT_LOCAL_NODE_ID") or "").strip()
        node_secret = str(node_token or os.getenv("WECHAT_LOCAL_NODE_TOKEN") or "").strip()
        query = urlencode({"tenant_id": tenant, "node_id": node})
        headers = {"X-Node-Token": node_secret} if node_secret else None
        try:
            payload = self.vps.get_json(f"/v1/local/commands?{query}", token=token, headers=headers)
        except VpsClientError as exc:
            return {"ok": False, "tenant_id": tenant, "error": str(exc), "commands": [], "results": []}
        commands = payload.get("commands", []) if isinstance(payload.get("commands"), list) else []
        results = []
        for command in commands:
            if not isinstance(command, dict):
                continue
            result = self.handle_command(command, tenant_id=tenant)
            report = self.report_command_result(result, token=token, node_token=node_secret)
            if report.get("ok") is False:
                result["report_error"] = report.get("error")
            results.append(result)
        return {"ok": True, "tenant_id": tenant, "commands": commands, "results": results}

    def handle_command(self, command: dict[str, Any], *, tenant_id: str | None = None) -> dict[str, Any]:
        command_type = str(command.get("type") or "")
        tenant = active_tenant_id(command.get("tenant_id") or tenant_id)
        if command_type == "backup_all":
            return {"command_id": command.get("command_id"), "accepted": True, "result": self.backups.build_backup(scope="all", tenant_id=tenant)}
        if command_type == "backup_tenant":
            return {"command_id": command.get("command_id"), "accepted": True, "result": self.backups.build_backup(scope="tenant", tenant_id=tenant)}
        if command_type in {"pull_shared_patch", "check_update"}:
            return {"command_id": command.get("command_id"), "accepted": True, "result": {"ok": True, "deferred": command_type}}
        if command_type in {"restore_backup", "push_update"}:
            return {
                "command_id": command.get("command_id"),
                "accepted": True,
                "result": {"ok": True, "deferred": command_type, "payload": command.get("payload") if isinstance(command.get("payload"), dict) else {}},
            }
        return {"command_id": command.get("command_id"), "accepted": False, "error": f"unsupported command type: {command_type}"}

    def report_command_result(self, result: dict[str, Any], *, token: str = "", node_token: str = "") -> dict[str, Any]:
        command_id = str(result.get("command_id") or "")
        if not command_id or not self.vps.configured:
            return {"ok": True, "skipped": True}
        headers = {"X-Node-Token": node_token} if node_token else None
        try:
            payload = self.vps.post_json(f"/v1/local/commands/{command_id}/result", result, token=token, headers=headers)
        except VpsClientError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "response": payload}

    def check_update(self, *, token: str = "") -> dict[str, Any]:
        if not self.vps.configured:
            return {"ok": True, "mode": "offline_unconfigured", "update": None}
        try:
            payload = self.vps.get_json("/v1/updates/latest", token=token)
        except VpsClientError as exc:
            return {"ok": False, "error": str(exc), "update": None}
        return {"ok": True, "update": payload.get("update") if isinstance(payload.get("update"), dict) else payload}

    def upload_shared_candidates(self, *, token: str = "", tenant_id: str | None = None) -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)
        snapshot = build_shared_knowledge_snapshot()
        cache = self.read_shared_upload_cache()
        if not self.vps.configured:
            return {
                "ok": True,
                "mode": "offline_unconfigured",
                "tenant_id": tenant,
                "uploaded": [],
                "skipped": snapshot.get("items", []),
            }
        uploaded: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for item in snapshot.get("items", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id") or "")
            digest = str(item.get("digest") or "")
            if item_id and digest and cache.get(item_id) == digest:
                skipped.append(item)
                continue
            payload = {
                "tenant_id": tenant,
                "title": f"共享公共知识候选：{item.get('title') or item_id}",
                "summary": f"Local 上传的共享公共知识变更，分类 {item.get('category_id') or '-'}，条目 {item_id}",
                "source": "local_shared_auto_upload",
                "operations": [
                    {
                        "op": "upsert_json",
                        "path": f"{item.get('category_id') or 'global_guidelines'}/items/{item_id}.json",
                        "content": item.get("payload") if isinstance(item.get("payload"), dict) else item,
                    }
                ],
            }
            try:
                response = self.vps.post_json("/v1/shared/proposals", payload, token=token)
            except VpsClientError as exc:
                return {"ok": False, "tenant_id": tenant, "error": str(exc), "uploaded": uploaded, "skipped": skipped}
            cache[item_id] = digest
            uploaded.append({"item": item, "proposal": response.get("proposal") if isinstance(response, dict) else response})
        self.write_shared_upload_cache(cache)
        return {"ok": True, "tenant_id": tenant, "uploaded": uploaded, "skipped": skipped}

    def read_shared_upload_cache(self) -> dict[str, str]:
        path = shared_upload_cache_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def write_shared_upload_cache(self, cache: dict[str, str]) -> None:
        path = shared_upload_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)


def shared_upload_cache_path():
    return runtime_app_root() / "sync" / "shared_candidate_uploads.json"


def local_node_cache_path():
    return runtime_app_root() / "sync" / "local_node.json"


def stable_local_node_id() -> str:
    seed = f"{socket.gethostname()}|{runtime_app_root()}".encode("utf-8", errors="ignore")
    return "local_" + hashlib.sha256(seed).hexdigest()[:16]
