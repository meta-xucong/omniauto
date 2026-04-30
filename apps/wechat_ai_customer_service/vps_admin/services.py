"""Domain services for the VPS admin control plane."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from apps.wechat_ai_customer_service.auth.email_verification import EmailVerificationService, email_settings_from_config, normalize_email
from apps.wechat_ai_customer_service.auth.models import AuthSession, Role
from apps.wechat_ai_customer_service.knowledge_paths import DEFAULT_TENANT_ID, active_tenant_id, runtime_app_root
from apps.wechat_ai_customer_service.sync import BackupService

from .auth import (
    VpsAdminAuthService,
    ensure_not_reserved_admin,
    ensure_tenant_exists,
    hash_password,
    make_id,
    public_user,
    require_customer_or_guest,
)
from .local_data import build_shared_knowledge_snapshot, build_tenant_data_summary
from .readable_export import build_customer_readable_workbook
from .store import VpsAdminStore, append_audit, now_iso


class TenantService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def list_tenants(self) -> list[dict[str, Any]]:
        tenants = self.store.read().get("tenants", {})
        return sorted(tenants.values(), key=lambda item: str(item.get("tenant_id") or ""))

    def create_tenant(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        tenant_id = active_tenant_id(payload.get("tenant_id") or payload.get("id") or make_id("tenant"))
        record = {
            "tenant_id": tenant_id,
            "display_name": str(payload.get("display_name") or tenant_id),
            "status": str(payload.get("status") or "active"),
            "sync_enabled": bool(payload.get("sync_enabled", False)),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if tenant_id in state["tenants"]:
                raise HTTPException(status_code=409, detail=f"tenant already exists: {tenant_id}")
            state["tenants"][tenant_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="create_tenant", target_type="tenant", target_id=tenant_id)
            return record

        return self.store.update(mutate)

    def update_tenant(self, tenant_id: str, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if tenant not in state["tenants"]:
                raise HTTPException(status_code=404, detail=f"tenant not found: {tenant}")
            record = state["tenants"][tenant]
            for key in ("display_name", "status", "sync_enabled"):
                if key in payload:
                    record[key] = payload[key]
            if isinstance(payload.get("metadata"), dict):
                record["metadata"] = payload["metadata"]
            record["updated_at"] = now_iso()
            append_audit(state, actor_id=actor.user.user_id, action="update_tenant", target_type="tenant", target_id=tenant)
            return record

        return self.store.update(mutate)


class OverviewService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def overview(self) -> dict[str, Any]:
        state = self.store.read()
        pending_commands = [
            item for item in state.get("commands", {}).values() if item.get("status") in {"queued", "sent"}
        ]
        latest_shared_snapshot = latest_by_created_at(state.get("shared_snapshots", {}).values())
        latest_data_package = latest_by_created_at(state.get("customer_data_packages", {}).values())
        return {
            "counts": {
                "tenants": len(state.get("tenants", {})),
                "users": len(state.get("users", {})),
                "nodes": len(state.get("local_nodes", {})),
                "pending_commands": len(pending_commands),
                "customer_data_packages": len(state.get("customer_data_packages", {})),
                "shared_snapshots": len(state.get("shared_snapshots", {})),
                "shared_library_items": len(state.get("shared_library", {})),
                "shared_pending_proposals": len(
                    [
                        item
                        for item in state.get("shared_proposals", {}).values()
                        if item.get("status") == "pending_review"
                    ]
                ),
                "backup_requests": len(state.get("backup_requests", {})),
                "restore_requests": len(state.get("restore_requests", {})),
            },
            "latest_shared_snapshot": latest_shared_snapshot,
            "latest_data_package": latest_data_package,
            "recommendations": [
                {
                    "title": "共享公共知识已和客户专业知识分层",
                    "detail": "共享公共知识位于 data/shared_knowledge；客户正式知识、商品专属知识和 RAG 数据位于 tenant 目录。",
                    "status": "ok",
                },
                {
                    "title": "真实还原仍建议先执行演练",
                    "detail": "当前控制台的一键还原入口默认创建 dry-run 命令，避免误覆盖客户本地数据。",
                    "status": "warning",
                },
            ],
        }


class SecurityConfigService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def smtp_config(self) -> dict[str, Any]:
        state = self.store.read()
        config = state.get("smtp_config") if isinstance(state.get("smtp_config"), dict) else {}
        settings = email_settings_from_config(config)
        return {
            "server": str(config.get("server") or settings.smtp_host or ""),
            "port": int(config.get("port") or settings.smtp_port),
            "use_ssl": bool(config.get("use_ssl", settings.smtp_use_ssl)),
            "use_tls": bool(config.get("use_tls", settings.smtp_use_tls)),
            "username": str(config.get("username") or settings.smtp_username or ""),
            "password_set": bool(config.get("password") or settings.smtp_password),
            "from_email": str(config.get("from_email") or settings.mail_from or ""),
            "sender_name": str(config.get("sender_name") or settings.sender_name or "OmniAuto"),
            "otp_required": bool(config.get("otp_required", settings.otp_required)),
            "code_length": int(config.get("code_length") or settings.code_length),
            "ttl_minutes": int(config.get("ttl_minutes") or settings.ttl_minutes),
            "resend_seconds": int(config.get("resend_seconds") or settings.resend_seconds),
            "trusted_device_days": int(config.get("trusted_device_days") or settings.trusted_device_days),
            "smtp_configured": bool(settings.smtp_host),
        }

    def update_smtp_config(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            current = state.get("smtp_config") if isinstance(state.get("smtp_config"), dict) else {}
            password = str(payload.get("password") or "")
            if not password and not payload.get("clear_password"):
                password = str(current.get("password") or "")
            record = {
                "server": str(payload.get("server") or "").strip(),
                "port": int(payload.get("port") or 465),
                "use_ssl": to_bool(payload.get("use_ssl"), default=True),
                "use_tls": to_bool(payload.get("use_tls"), default=False),
                "username": str(payload.get("username") or "").strip(),
                "password": "" if payload.get("clear_password") else password,
                "from_email": normalize_email(str(payload.get("from_email") or payload.get("username") or "")),
                "sender_name": str(payload.get("sender_name") or "OmniAuto").strip() or "OmniAuto",
                "otp_required": to_bool(payload.get("otp_required"), default=True),
                "code_length": clamp_int(payload.get("code_length"), default=4, minimum=4, maximum=8),
                "ttl_minutes": clamp_int(payload.get("ttl_minutes"), default=15, minimum=1, maximum=60),
                "resend_seconds": clamp_int(payload.get("resend_seconds"), default=60, minimum=10, maximum=600),
                "trusted_device_days": clamp_int(payload.get("trusted_device_days"), default=30, minimum=1, maximum=120),
                "initialized_at": str(current.get("initialized_at") or now_iso()),
                "updated_by": actor.user.user_id,
                "updated_at": now_iso(),
            }
            state["smtp_config"] = record
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="update_smtp_config",
                target_type="security",
                target_id="smtp_config",
                detail={"server": record["server"], "otp_required": record["otp_required"]},
            )
            return self.smtp_config_from_state(state)

        return self.store.update(mutate)

    def test_smtp(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        to_email = normalize_email(str(payload.get("to_email") or payload.get("email") or ""))
        if not to_email:
            raise HTTPException(status_code=400, detail="test email required")
        state = self.store.read()
        try:
            delivery = EmailVerificationService(email_settings_from_config(state.get("smtp_config"))).send_test_email(to_email=to_email)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"test email failed: {exc}") from exc

        def mutate(next_state: dict[str, Any]) -> None:
            append_audit(
                next_state,
                actor_id=actor.user.user_id,
                action="test_smtp_config",
                target_type="security",
                target_id="smtp_config",
                detail={"to_email": to_email, "method": delivery.get("method")},
            )

        self.store.update(mutate)
        return {"sent": True, "delivery": {key: value for key, value in delivery.items() if key != "debug_code"}}

    def smtp_config_from_state(self, state: dict[str, Any]) -> dict[str, Any]:
        config = state.get("smtp_config") if isinstance(state.get("smtp_config"), dict) else {}
        settings = email_settings_from_config(config)
        return {
            "server": str(config.get("server") or settings.smtp_host or ""),
            "port": int(config.get("port") or settings.smtp_port),
            "use_ssl": bool(config.get("use_ssl", settings.smtp_use_ssl)),
            "use_tls": bool(config.get("use_tls", settings.smtp_use_tls)),
            "username": str(config.get("username") or settings.smtp_username or ""),
            "password_set": bool(config.get("password") or settings.smtp_password),
            "from_email": str(config.get("from_email") or settings.mail_from or ""),
            "sender_name": str(config.get("sender_name") or settings.sender_name or "OmniAuto"),
            "otp_required": bool(config.get("otp_required", settings.otp_required)),
            "code_length": int(config.get("code_length") or settings.code_length),
            "ttl_minutes": int(config.get("ttl_minutes") or settings.ttl_minutes),
            "resend_seconds": int(config.get("resend_seconds") or settings.resend_seconds),
            "trusted_device_days": int(config.get("trusted_device_days") or settings.trusted_device_days),
            "smtp_configured": bool(settings.smtp_host),
        }


class UserService:
    def __init__(self, store: VpsAdminStore, auth: VpsAdminAuthService) -> None:
        self.store = store
        self.auth = auth

    def list_users(self) -> list[dict[str, Any]]:
        state = self.store.read()
        users = state.get("users", {})
        return sorted((self.public_user_with_access(item, state=state) for item in users.values()), key=lambda item: str(item.get("username") or ""))

    def create_user(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        username = str(payload.get("username") or "").strip()
        if not username:
            raise HTTPException(status_code=400, detail="username required")
        role = require_customer_or_guest(str(payload.get("role") or "customer"))
        ensure_not_reserved_admin(username, role, self.auth.settings)
        password = str(payload.get("password") or "").strip()
        if not password:
            raise HTTPException(status_code=400, detail="password required")
        raw_tenant_ids = payload.get("tenant_ids", [])
        if not isinstance(raw_tenant_ids, list):
            raw_tenant_ids = [raw_tenant_ids]
        tenant_ids = [active_tenant_id(item) for item in raw_tenant_ids if str(item).strip()]
        if role == Role.CUSTOMER and not tenant_ids:
            tenant_ids = [active_tenant_id(username)]
        guest_customer_username = ""
        if role == Role.GUEST and not tenant_ids:
            guest_customer_username = str(payload.get("authorized_customer") or payload.get("customer_username") or "").strip()
            if not guest_customer_username:
                raise HTTPException(status_code=400, detail="guest account requires an authorized customer")

        user_id = str(payload.get("user_id") or make_id("user"))
        record = {
            "user_id": user_id,
            "username": username,
            "display_name": str(payload.get("display_name") or username),
            "email": normalize_email(str(payload.get("email") or "")),
            "role": role.value,
            "tenant_ids": tenant_ids,
            "resource_scopes": payload.get("resource_scopes") if isinstance(payload.get("resource_scopes"), list) else ["*"],
            "status": str(payload.get("status") or "active"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        record["password_hash"] = hash_password(password)

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            resolved_tenant_ids = list(tenant_ids)
            if role == Role.GUEST and guest_customer_username:
                customer = customer_user_by_username(state, guest_customer_username)
                if not customer:
                    raise HTTPException(status_code=404, detail=f"authorized customer not found: {guest_customer_username}")
                resolved_tenant_ids = [
                    active_tenant_id(item)
                    for item in customer.get("tenant_ids", [])
                    if str(item).strip()
                ]
                if not resolved_tenant_ids:
                    raise HTTPException(status_code=400, detail=f"authorized customer has no data scope: {guest_customer_username}")
                record["tenant_ids"] = resolved_tenant_ids
            if role == Role.GUEST and not guest_customer_username:
                missing_customer = [
                    tenant_id
                    for tenant_id in resolved_tenant_ids
                    if not customer_user_by_tenant(state, tenant_id)
                ]
                if missing_customer:
                    raise HTTPException(status_code=400, detail="guest account must be assigned to an existing customer")
            for tenant_id in resolved_tenant_ids:
                if tenant_id not in state["tenants"]:
                    if role == Role.CUSTOMER and tenant_id == active_tenant_id(username):
                        state["tenants"][tenant_id] = customer_tenant_record(username=username, tenant_id=tenant_id)
                    else:
                        ensure_tenant_exists(state, tenant_id)
            if user_id in state["users"]:
                raise HTTPException(status_code=409, detail=f"user already exists: {user_id}")
            if any(str(item.get("username") or "") == username for item in state["users"].values()):
                raise HTTPException(status_code=409, detail=f"username already exists: {username}")
            state["users"][user_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="create_user", target_type="user", target_id=user_id)
            return self.public_user_with_access(record, state=state)

        return self.store.update(mutate)

    def update_user(self, user_id: str, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if user_id not in state["users"]:
                raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
            record = state["users"][user_id]
            role = require_customer_or_guest(str(payload.get("role") or record.get("role") or "guest"))
            ensure_not_reserved_admin(str(payload.get("username") or record.get("username") or ""), role, self.auth.settings)
            if "username" in payload:
                username = str(payload["username"]).strip()
                if not username:
                    raise HTTPException(status_code=400, detail="username required")
                if any(uid != user_id and str(item.get("username") or "") == username for uid, item in state["users"].items()):
                    raise HTTPException(status_code=409, detail=f"username already exists: {username}")
                record["username"] = username
            if "role" in payload:
                record["role"] = role.value
            if "tenant_ids" in payload:
                tenant_ids = [active_tenant_id(item) for item in payload.get("tenant_ids", []) if str(item).strip()]
                if not tenant_ids:
                    raise HTTPException(status_code=400, detail="tenant_ids required")
                for tenant_id in tenant_ids:
                    ensure_tenant_exists(state, tenant_id)
                record["tenant_ids"] = tenant_ids
            for key in ("display_name", "resource_scopes", "status"):
                if key in payload:
                    record[key] = payload[key]
            if "email" in payload:
                record["email"] = normalize_email(str(payload.get("email") or ""))
            if payload.get("password"):
                record["password_hash"] = hash_password(str(payload["password"]))
            record["updated_at"] = now_iso()
            append_audit(state, actor_id=actor.user.user_id, action="update_user", target_type="user", target_id=user_id)
            return self.public_user_with_access(record, state=state)

        return self.store.update(mutate)

    def delete_user(self, user_id: str, *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if user_id not in state["users"]:
                raise HTTPException(status_code=404, detail=f"user not found: {user_id}")
            record = state["users"].pop(user_id)
            append_audit(state, actor_id=actor.user.user_id, action="delete_user", target_type="user", target_id=user_id)
            return self.public_user_with_access(record, state=state)

        return self.store.update(mutate)

    def public_user_with_access(self, record: dict[str, Any], *, state: dict[str, Any]) -> dict[str, Any]:
        result = public_user(record)
        tenant_ids = [active_tenant_id(item) for item in result.get("tenant_ids", []) if str(item).strip()]
        customer_names: list[str] = []
        for tenant_id in tenant_ids:
            customer = customer_username_for_tenant(state, tenant_id)
            customer_names.append(customer or tenant_id)
        result["authorized_customers"] = customer_names
        if result.get("role") == Role.CUSTOMER.value:
            result["customer_name"] = result.get("username")
        return result


class CustomerDataService:
    def __init__(self, store: VpsAdminStore, auth: VpsAdminAuthService) -> None:
        self.store = store
        self.auth = auth

    def list_packages(self) -> list[dict[str, Any]]:
        packages = self.store.read().get("customer_data_packages", {})
        return sorted(packages.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def get_package(self, package_id: str) -> dict[str, Any]:
        record = self.store.read().get("customer_data_packages", {}).get(package_id)
        if not isinstance(record, dict):
            raise HTTPException(status_code=404, detail=f"customer data package not found: {package_id}")
        return record

    def package_for_customer(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        username = str(payload.get("account_username") or payload.get("username") or "").strip()
        tenant_id = str(payload.get("tenant_id") or "").strip()
        if not username and not tenant_id:
            raise HTTPException(status_code=400, detail="account_username or tenant_id required")

        state = self.store.read()
        user = None
        if username:
            for candidate in state.get("users", {}).values():
                if str(candidate.get("username") or "") == username:
                    user = candidate
                    break
            if not isinstance(user, dict):
                raise HTTPException(status_code=404, detail=f"customer account not found: {username}")
            tenant_ids = [active_tenant_id(item) for item in user.get("tenant_ids", []) if str(item).strip()]
            if tenant_id:
                tenant_id = active_tenant_id(tenant_id)
                if tenant_id not in tenant_ids:
                    raise HTTPException(status_code=403, detail="account is not authorized for this tenant")
            elif tenant_ids:
                tenant_id = tenant_ids[0]
        tenant = active_tenant_id(tenant_id or DEFAULT_TENANT_ID)
        if tenant not in state.get("tenants", {}):
            raise HTTPException(status_code=404, detail=f"tenant not found: {tenant}")

        backup = BackupService(output_root=runtime_app_root() / "vps_admin" / "customer_packages").build_backup(scope="tenant", tenant_id=tenant)
        summary = build_tenant_data_summary(tenant)
        package_id = f"data_pkg_{username or tenant}_{backup['backup_id']}"
        package = {
            "package_id": package_id,
            "account_username": username,
            "tenant_id": tenant,
            "scope": "tenant",
            "backup_id": backup["backup_id"],
            "package_path": backup["package_path"],
            "bytes": backup["bytes"],
            "summary": summary,
            "manifest": backup["manifest"],
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
        }

        def mutate(next_state: dict[str, Any]) -> dict[str, Any]:
            ensure_tenant_exists(next_state, tenant)
            next_state["customer_data_packages"][package_id] = package
            append_audit(
                next_state,
                actor_id=actor.user.user_id,
                action="package_customer_data",
                target_type="customer_data_package",
                target_id=package_id,
                detail={"account_username": username, "tenant_id": tenant, "backup_id": backup["backup_id"]},
            )
            return package

        return self.store.update(mutate)

    def register_package(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        package_id = str(payload.get("package_id") or make_id("data_pkg"))
        tenant_id = active_tenant_id(payload.get("tenant_id") or DEFAULT_TENANT_ID)
        record = {
            "package_id": package_id,
            "account_username": str(payload.get("account_username") or ""),
            "tenant_id": tenant_id,
            "scope": str(payload.get("scope") or "tenant"),
            "backup_id": str(payload.get("backup_id") or ""),
            "package_path": str(payload.get("package_path") or ""),
            "bytes": int(payload.get("bytes") or 0),
            "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
            "manifest": payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {},
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            ensure_tenant_exists(state, tenant_id)
            state["customer_data_packages"][package_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="register_customer_data_package", target_type="customer_data_package", target_id=package_id)
            return record

        return self.store.update(mutate)

    def package_path(self, package_id: str) -> Path:
        record = self.get_package(package_id)
        package_path = Path(str(record.get("package_path") or ""))
        if not package_path.exists() or not package_path.is_file():
            raise HTTPException(status_code=404, detail="package file not found on server")
        return package_path

    def readable_export_path(self, package_id: str) -> Path:
        record = self.get_package(package_id)
        package_path = self.package_path(package_id)
        return build_customer_readable_workbook(record, package_path)

    def delete_package(self, package_id: str, *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if package_id not in state["customer_data_packages"]:
                raise HTTPException(status_code=404, detail=f"customer data package not found: {package_id}")
            record = state["customer_data_packages"].pop(package_id)
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="delete_customer_data_package",
                target_type="customer_data_package",
                target_id=package_id,
            )
            return record

        record = self.store.update(mutate)
        deleted_file = delete_managed_file(Path(str(record.get("package_path") or "")))
        return {"package": record, "deleted_file": deleted_file}

    def bootstrap_test_customer(self, *, actor: AuthSession, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
        tenant = active_tenant_id(tenant_id)
        username = "test01"
        password = "1234.abcd"
        tenant_record = {
            "tenant_id": tenant,
            "display_name": "测试客户 test01（当前客户端数据）",
            "status": "active",
            "sync_enabled": True,
            "metadata": {"source": "local_current_client", "account_username": username},
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        user_record = {
            "user_id": "customer_test01",
            "username": username,
            "display_name": "测试客户 test01",
            "role": Role.CUSTOMER.value,
            "tenant_ids": [tenant],
            "resource_scopes": ["*"],
            "status": "active",
            "email": "test01@example.local",
            "password_hash": hash_password(password),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        backup = BackupService(output_root=runtime_app_root() / "vps_admin" / "customer_packages").build_backup(scope="tenant", tenant_id=tenant)
        summary = build_tenant_data_summary(tenant)
        package_id = f"data_pkg_{username}_{backup['backup_id']}"
        package = {
            "package_id": package_id,
            "account_username": username,
            "tenant_id": tenant,
            "scope": "tenant",
            "backup_id": backup["backup_id"],
            "package_path": backup["package_path"],
            "bytes": backup["bytes"],
            "summary": summary,
            "manifest": backup["manifest"],
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            existing_tenant = state["tenants"].get(tenant)
            if existing_tenant:
                existing_tenant.update({key: value for key, value in tenant_record.items() if key not in {"created_at"}})
                tenant_out = existing_tenant
            else:
                state["tenants"][tenant] = tenant_record
                tenant_out = tenant_record
            state["users"][user_record["user_id"]] = user_record
            state["customer_data_packages"][package_id] = package
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="bootstrap_test01_customer",
                target_type="user",
                target_id=user_record["user_id"],
                detail={"tenant_id": tenant, "backup_id": backup["backup_id"]},
            )
            return {"tenant": tenant_out, "user": public_user(user_record), "package": package}

        return self.store.update(mutate)


class NodeService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def register(self, payload: dict[str, Any], *, actor_id: str = "local-node") -> dict[str, Any]:
        node_id = str(payload.get("node_id") or make_id("node"))
        tenant_ids = [active_tenant_id(item) for item in payload.get("tenant_ids", []) if str(item).strip()]
        if not tenant_ids:
            tenant_ids = [active_tenant_id(payload.get("tenant_id"))]
        token = "node_" + secrets.token_urlsafe(24)
        record = {
            "node_id": node_id,
            "display_name": str(payload.get("display_name") or node_id),
            "tenant_ids": tenant_ids,
            "status": "online",
            "version": str(payload.get("version") or ""),
            "capabilities": payload.get("capabilities") if isinstance(payload.get("capabilities"), list) else [],
            "node_token": token,
            "registered_at": now_iso(),
            "last_seen_at": now_iso(),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            for tenant_id in tenant_ids:
                ensure_tenant_exists(state, tenant_id)
            state["local_nodes"][node_id] = record
            append_audit(state, actor_id=actor_id, action="register_node", target_type="local_node", target_id=node_id)
            return public_node(record, include_token=True)

        return self.store.update(mutate)

    def heartbeat(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if node_id not in state["local_nodes"]:
                raise HTTPException(status_code=404, detail=f"node not found: {node_id}")
            record = state["local_nodes"][node_id]
            record["status"] = str(payload.get("status") or "online")
            record["last_seen_at"] = now_iso()
            if payload.get("version") is not None:
                record["version"] = str(payload.get("version") or "")
            if isinstance(payload.get("metrics"), dict):
                record["metrics"] = payload["metrics"]
            return public_node(record)

        return self.store.update(mutate)

    def list_nodes(self) -> list[dict[str, Any]]:
        nodes = self.store.read().get("local_nodes", {})
        return sorted((public_node(item) for item in nodes.values()), key=lambda item: str(item.get("node_id") or ""))


class CommandService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def create_command(self, payload: dict[str, Any], *, actor: AuthSession, command_type: str | None = None) -> dict[str, Any]:
        command_id = str(payload.get("command_id") or make_id("cmd"))
        tenant_id = active_tenant_id(payload.get("tenant_id"))
        record = {
            "command_id": command_id,
            "type": str(command_type or payload.get("type") or ""),
            "tenant_id": tenant_id,
            "node_id": str(payload.get("node_id") or ""),
            "payload": payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            "status": "queued",
            "attempts": 0,
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        if not record["type"]:
            raise HTTPException(status_code=400, detail="command type required")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            ensure_tenant_exists(state, tenant_id)
            if command_id in state["commands"]:
                raise HTTPException(status_code=409, detail=f"command already exists: {command_id}")
            if record["node_id"] and record["node_id"] not in state["local_nodes"]:
                raise HTTPException(status_code=404, detail=f"node not found: {record['node_id']}")
            state["commands"][command_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="create_command", target_type="command", target_id=command_id)
            return record

        return self.store.update(mutate)

    def poll(self, *, tenant_id: str, node_id: str = "") -> list[dict[str, Any]]:
        tenant = active_tenant_id(tenant_id)

        def mutate(state: dict[str, Any]) -> list[dict[str, Any]]:
            if node_id and node_id in state["local_nodes"]:
                node = state["local_nodes"][node_id]
                if tenant not in node.get("tenant_ids", []):
                    raise HTTPException(status_code=403, detail="node is not authorized for this tenant")
            commands: list[dict[str, Any]] = []
            for record in state["commands"].values():
                if record.get("tenant_id") != tenant:
                    continue
                if record.get("status") not in {"queued", "sent"}:
                    continue
                if record.get("node_id") and record.get("node_id") != node_id:
                    continue
                record["status"] = "sent"
                record["attempts"] = int(record.get("attempts") or 0) + 1
                record["sent_at"] = now_iso()
                record["updated_at"] = now_iso()
                commands.append(command_payload(record))
            return commands

        return self.store.update(mutate)

    def submit_result(self, command_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if command_id not in state["commands"]:
                raise HTTPException(status_code=404, detail=f"command not found: {command_id}")
            record = state["commands"][command_id]
            accepted = payload.get("accepted")
            ok = payload.get("ok")
            if ok is None:
                ok = accepted is not False and not payload.get("error")
            record["status"] = "succeeded" if ok else "failed"
            record["result"] = payload.get("result") if isinstance(payload.get("result"), dict) else payload
            record["error"] = str(payload.get("error") or "")
            record["completed_at"] = now_iso()
            record["updated_at"] = now_iso()
            result_record = {
                "command_id": command_id,
                "status": record["status"],
                "tenant_id": record.get("tenant_id"),
                "node_id": record.get("node_id"),
                "payload": payload,
                "created_at": now_iso(),
            }
            state.setdefault("command_results", []).append(result_record)
            append_audit(state, actor_id="local-node", action="command_result", target_type="command", target_id=command_id)
            return record

        return self.store.update(mutate)

    def list_commands(self) -> list[dict[str, Any]]:
        commands = self.store.read().get("commands", {})
        return sorted(commands.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)


class SharedKnowledgeService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def list_library_items(self, *, include_inactive: bool = False) -> list[dict[str, Any]]:
        def mutate(state: dict[str, Any]) -> list[dict[str, Any]]:
            seed_shared_library_if_empty(state)
            items = list(state.get("shared_library", {}).values())
            if not include_inactive:
                items = [item for item in items if str(item.get("status") or "active") == "active"]
            normalized = [public_shared_library_record(item) for item in items]
            return sorted(normalized, key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)

        return self.store.update(mutate)

    def get_library_item(self, item_id: str) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            seed_shared_library_if_empty(state)
            record = state.get("shared_library", {}).get(item_id)
            if not isinstance(record, dict):
                raise HTTPException(status_code=404, detail=f"shared library item not found: {item_id}")
            return public_shared_library_record(record)

        return self.store.update(mutate)

    def create_library_item(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        record = build_shared_library_record(payload, actor_id=actor.user.user_id)

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            seed_shared_library_if_empty(state)
            if record["item_id"] in state["shared_library"]:
                raise HTTPException(status_code=409, detail=f"shared library item already exists: {record['item_id']}")
            state["shared_library"][record["item_id"]] = record
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="create_shared_library_item",
                target_type="shared_library_item",
                target_id=record["item_id"],
            )
            return public_shared_library_record(record)

        return self.store.update(mutate)

    def update_library_item(self, item_id: str, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            seed_shared_library_if_empty(state)
            if item_id not in state["shared_library"]:
                raise HTTPException(status_code=404, detail=f"shared library item not found: {item_id}")
            record = state["shared_library"][item_id]
            for key in ("category_id", "title", "content", "status", "source", "tenant_id"):
                if key in payload:
                    record[key] = str(payload.get(key) or "")
            if isinstance(payload.get("data"), dict):
                record["data"] = payload["data"]
            if "keywords" in payload:
                record["keywords"] = normalize_text_list(payload.get("keywords"))
            if "applies_to" in payload:
                record["applies_to"] = str(payload.get("applies_to") or "")
            if "notes" in payload:
                record["notes"] = str(payload.get("notes") or "")
            record["updated_by"] = actor.user.user_id
            record["updated_at"] = now_iso()
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="update_shared_library_item",
                target_type="shared_library_item",
                target_id=item_id,
            )
            return public_shared_library_record(record)

        return self.store.update(mutate)

    def delete_library_item(self, item_id: str, *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            seed_shared_library_if_empty(state)
            if item_id not in state["shared_library"]:
                raise HTTPException(status_code=404, detail=f"shared library item not found: {item_id}")
            record = state["shared_library"].pop(item_id)
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="delete_shared_library_item",
                target_type="shared_library_item",
                target_id=item_id,
            )
            return record

        return self.store.update(mutate)

    def submit_proposal(self, payload: dict[str, Any], *, actor_id: str = "local-node") -> dict[str, Any]:
        proposal_id = str(payload.get("proposal_id") or make_id("proposal"))
        tenant_id = active_tenant_id(payload.get("tenant_id"))
        operations = payload.get("operations")
        if not isinstance(operations, list) or not operations:
            raise HTTPException(status_code=400, detail="proposal operations required")
        record = {
            "proposal_id": proposal_id,
            "tenant_id": tenant_id,
            "title": str(payload.get("title") or proposal_id),
            "summary": str(payload.get("summary") or ""),
            "operations": operations,
            "source": str(payload.get("source") or "local"),
            "status": "pending_review",
            "created_by": actor_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            ensure_tenant_exists(state, tenant_id)
            state["shared_proposals"][proposal_id] = record
            append_audit(state, actor_id=actor_id, action="submit_shared_proposal", target_type="shared_proposal", target_id=proposal_id)
            return record

        return self.store.update(mutate)

    def list_proposals(self) -> list[dict[str, Any]]:
        proposals = self.store.read().get("shared_proposals", {})
        return sorted(proposals.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def review_proposal(self, proposal_id: str, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip().lower()
        if action not in {"accept", "reject", "void"}:
            raise HTTPException(status_code=400, detail="review action must be accept, reject, or void")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if proposal_id not in state["shared_proposals"]:
                raise HTTPException(status_code=404, detail=f"proposal not found: {proposal_id}")
            proposal = state["shared_proposals"][proposal_id]
            proposal["reviewed_by"] = actor.user.user_id
            proposal["reviewed_at"] = now_iso()
            proposal["review_note"] = str(payload.get("note") or "")
            proposal["updated_at"] = now_iso()
            if action == "accept":
                patch_id = str(payload.get("patch_id") or make_id("patch"))
                library_items = upsert_shared_library_from_operations(
                    state,
                    proposal.get("operations", []),
                    actor_id=actor.user.user_id,
                    source=f"proposal:{proposal_id}",
                    tenant_id=str(proposal.get("tenant_id") or ""),
                )
                patch = {
                    "schema_version": 1,
                    "patch_id": patch_id,
                    "version": str(payload.get("version") or f"shared-{now_iso()}"),
                    "source_proposal_id": proposal_id,
                    "tenant_id": proposal.get("tenant_id"),
                    "operations": proposal.get("operations", []),
                    "status": "published",
                    "library_item_ids": [item.get("item_id") for item in library_items],
                    "created_by": actor.user.user_id,
                    "created_at": now_iso(),
                }
                state["shared_patches"][patch_id] = patch
                proposal["status"] = "accepted"
                proposal["patch_id"] = patch_id
                append_audit(state, actor_id=actor.user.user_id, action="accept_shared_proposal", target_type="shared_proposal", target_id=proposal_id)
                return {"proposal": proposal, "patch": patch, "library_items": library_items}
            proposal["status"] = "rejected" if action == "reject" else "void"
            append_audit(state, actor_id=actor.user.user_id, action=f"{action}_shared_proposal", target_type="shared_proposal", target_id=proposal_id)
            return {"proposal": proposal, "patch": None, "library_items": []}

        return self.store.update(mutate)

    def list_patches(self) -> list[dict[str, Any]]:
        patches = self.store.read().get("shared_patches", {})
        return sorted(patches.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def overview(self) -> dict[str, Any]:
        state = self.store.read()
        snapshots = sorted(state.get("shared_snapshots", {}).values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {
            "local": build_shared_knowledge_snapshot(),
            "snapshots": snapshots,
            "latest_snapshot": snapshots[0] if snapshots else None,
        }

    def sync_local_snapshot(self, *, actor: AuthSession) -> dict[str, Any]:
        snapshot = build_shared_knowledge_snapshot()
        snapshot_id = str("shared_snapshot_" + make_id("sync"))
        record = {
            "snapshot_id": snapshot_id,
            "source": "local_shared_knowledge",
            "summary": {
                "category_count": len(snapshot.get("categories", [])),
                "item_count": len(snapshot.get("items", [])),
                "file_count": snapshot.get("file_summary", {}).get("file_count", 0),
                "json_file_count": snapshot.get("file_summary", {}).get("json_file_count", 0),
            },
            "snapshot": snapshot,
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
        }

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            state["shared_snapshots"][snapshot_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="sync_shared_knowledge", target_type="shared_snapshot", target_id=snapshot_id)
            return record

        return self.store.update(mutate)


class BackupRestoreService:
    def __init__(self, store: VpsAdminStore, commands: CommandService) -> None:
        self.store = store
        self.commands = commands

    def list_backup_requests(self) -> list[dict[str, Any]]:
        state = self.store.read()
        return sorted(state.get("backup_requests", {}).values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def delete_backup_request(self, request_id: str, *, actor: AuthSession) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if request_id not in state["backup_requests"]:
                raise HTTPException(status_code=404, detail=f"backup request not found: {request_id}")
            record = state["backup_requests"].pop(request_id)
            backup_id = str(record.get("backup_id") or "")
            removed_packages: list[dict[str, Any]] = []
            if backup_id:
                for package_id, package in list(state.get("customer_data_packages", {}).items()):
                    if str(package.get("backup_id") or "") == backup_id:
                        removed_packages.append(state["customer_data_packages"].pop(package_id))
            append_audit(
                state,
                actor_id=actor.user.user_id,
                action="delete_backup_request",
                target_type="backup_request",
                target_id=request_id,
                detail={"backup_id": backup_id, "removed_package_count": len(removed_packages)},
            )
            return {"request": record, "packages": removed_packages}

        result = self.store.update(mutate)
        deleted_files = []
        for item in [result["request"], *result["packages"]]:
            if delete_managed_file(Path(str(item.get("package_path") or ""))):
                deleted_files.append(str(item.get("package_path")))
        return {**result, "deleted_files": deleted_files}

    def list_restore_requests(self) -> list[dict[str, Any]]:
        state = self.store.read()
        return sorted(state.get("restore_requests", {}).values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def request_backup(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        scope = str(payload.get("scope") or "tenant").strip().lower()
        if scope not in {"tenant", "all"}:
            raise HTTPException(status_code=400, detail="backup scope must be tenant or all")
        command_type = "backup_all" if scope == "all" else "backup_tenant"
        command = self.commands.create_command(payload, actor=actor, command_type=command_type)
        request_id = make_id("backup")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            record = {
                "request_id": request_id,
                "scope": scope,
                "tenant_id": command.get("tenant_id"),
                "node_id": command.get("node_id"),
                "command_id": command.get("command_id"),
                "status": "queued",
                "created_by": actor.user.user_id,
                "created_at": now_iso(),
            }
            state["backup_requests"][request_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="request_backup", target_type="backup_request", target_id=request_id)
            return {"request": record, "command": command}

        return self.store.update(mutate)

    def build_local_backup_now(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        scope = str(payload.get("scope") or "all").strip().lower()
        if scope not in {"tenant", "shared", "all"}:
            raise HTTPException(status_code=400, detail="backup scope must be tenant, shared, or all")
        tenant_id = active_tenant_id(payload.get("tenant_id") or DEFAULT_TENANT_ID)
        backup = BackupService(output_root=runtime_app_root() / "vps_admin" / "backups").build_backup(scope=scope, tenant_id=tenant_id)
        request_id = make_id("backup")
        package_id = f"data_pkg_{backup['backup_id']}"
        summary = build_tenant_data_summary(tenant_id) if scope in {"tenant", "all"} else build_shared_knowledge_snapshot()

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            if scope != "shared":
                ensure_tenant_exists(state, tenant_id)
            record = {
                "request_id": request_id,
                "scope": scope,
                "tenant_id": tenant_id,
                "node_id": "",
                "command_id": "",
                "status": "succeeded",
                "mode": "local_immediate",
                "backup_id": backup["backup_id"],
                "package_path": backup["package_path"],
                "bytes": backup["bytes"],
                "created_by": actor.user.user_id,
                "created_at": now_iso(),
            }
            state["backup_requests"][request_id] = record
            state["customer_data_packages"][package_id] = {
                "package_id": package_id,
                "account_username": str(payload.get("account_username") or ""),
                "tenant_id": tenant_id,
                "scope": scope,
                "backup_id": backup["backup_id"],
                "package_path": backup["package_path"],
                "bytes": backup["bytes"],
                "summary": summary,
                "manifest": backup["manifest"],
                "created_by": actor.user.user_id,
                "created_at": now_iso(),
            }
            append_audit(state, actor_id=actor.user.user_id, action="local_backup_now", target_type="backup_request", target_id=request_id)
            return {"request": record, "backup": backup, "package": state["customer_data_packages"][package_id]}

        return self.store.update(mutate)

    def request_restore(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        if not payload.get("backup_id") and not payload.get("backup_url"):
            raise HTTPException(status_code=400, detail="backup_id or backup_url required")
        command = self.commands.create_command({**payload, "payload": payload}, actor=actor, command_type="restore_backup")
        request_id = make_id("restore")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            record = {
                "request_id": request_id,
                "tenant_id": command.get("tenant_id"),
                "node_id": command.get("node_id"),
                "backup_id": str(payload.get("backup_id") or ""),
                "backup_url": str(payload.get("backup_url") or ""),
                "dry_run": bool(payload.get("dry_run", True)),
                "command_id": command.get("command_id"),
                "status": "queued",
                "created_by": actor.user.user_id,
                "created_at": now_iso(),
            }
            state["restore_requests"][request_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="request_restore", target_type="restore_request", target_id=request_id)
            return {"request": record, "command": command}

        return self.store.update(mutate)

    def request_restore_latest(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        scope = str(payload.get("scope") or "all").strip().lower()
        tenant_id = active_tenant_id(payload.get("tenant_id") or DEFAULT_TENANT_ID)
        state = self.store.read()
        packages = [
            item
            for item in state.get("customer_data_packages", {}).values()
            if item.get("scope") == scope and (scope == "shared" or item.get("tenant_id") == tenant_id)
        ]
        packages = sorted(packages, key=lambda item: str(item.get("created_at") or ""), reverse=True)
        if not packages:
            raise HTTPException(status_code=404, detail="no matching backup package found")
        latest = packages[0]
        return self.request_restore(
            {
                "tenant_id": tenant_id,
                "node_id": str(payload.get("node_id") or ""),
                "backup_id": latest.get("backup_id"),
                "backup_url": latest.get("package_path"),
                "dry_run": payload.get("dry_run", True) is not False,
            },
            actor=actor,
        )


class ReleaseService:
    def __init__(self, store: VpsAdminStore) -> None:
        self.store = store

    def create_release(self, payload: dict[str, Any], *, actor: AuthSession) -> dict[str, Any]:
        release_id = str(payload.get("release_id") or make_id("release"))
        channel = str(payload.get("channel") or "stable")
        record = {
            "release_id": release_id,
            "channel": channel,
            "version": str(payload.get("version") or ""),
            "title": str(payload.get("title") or ""),
            "notes": str(payload.get("notes") or ""),
            "artifact_url": str(payload.get("artifact_url") or ""),
            "status": str(payload.get("status") or "published"),
            "created_by": actor.user.user_id,
            "created_at": now_iso(),
        }
        if not record["version"]:
            raise HTTPException(status_code=400, detail="release version required")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            state["releases"][release_id] = record
            append_audit(state, actor_id=actor.user.user_id, action="create_release", target_type="release", target_id=release_id)
            return record

        return self.store.update(mutate)

    def list_releases(self) -> list[dict[str, Any]]:
        releases = self.store.read().get("releases", {})
        return sorted(releases.values(), key=lambda item: str(item.get("created_at") or ""), reverse=True)

    def latest(self, *, channel: str = "stable") -> dict[str, Any] | None:
        for release in self.list_releases():
            if release.get("channel") == channel and release.get("status") == "published":
                return release
        return None


def public_node(record: dict[str, Any], *, include_token: bool = False) -> dict[str, Any]:
    if include_token:
        return dict(record)
    return {key: value for key, value in record.items() if key != "node_token"}


def customer_tenant_record(*, username: str, tenant_id: str) -> dict[str, Any]:
    return {
        "tenant_id": active_tenant_id(tenant_id),
        "display_name": username,
        "status": "active",
        "sync_enabled": False,
        "metadata": {"source": "customer_account", "account_username": username},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def customer_username_for_tenant(state: dict[str, Any], tenant_id: str) -> str:
    tenant = active_tenant_id(tenant_id)
    for user in state.get("users", {}).values():
        if not isinstance(user, dict) or user.get("role") != Role.CUSTOMER.value:
            continue
        if tenant in [active_tenant_id(item) for item in user.get("tenant_ids", []) if str(item).strip()]:
            return str(user.get("username") or "")
    tenant_record = state.get("tenants", {}).get(tenant)
    if isinstance(tenant_record, dict):
        metadata = tenant_record.get("metadata") if isinstance(tenant_record.get("metadata"), dict) else {}
        return str(metadata.get("account_username") or tenant_record.get("display_name") or tenant)
    return tenant


def customer_user_by_username(state: dict[str, Any], username: str) -> dict[str, Any] | None:
    for user in state.get("users", {}).values():
        if not isinstance(user, dict):
            continue
        if user.get("role") != Role.CUSTOMER.value:
            continue
        if str(user.get("username") or "") == username:
            return user
    return None


def customer_user_by_tenant(state: dict[str, Any], tenant_id: str) -> dict[str, Any] | None:
    tenant = active_tenant_id(tenant_id)
    for user in state.get("users", {}).values():
        if not isinstance(user, dict):
            continue
        if user.get("role") != Role.CUSTOMER.value:
            continue
        tenant_ids = [active_tenant_id(item) for item in user.get("tenant_ids", []) if str(item).strip()]
        if tenant in tenant_ids:
            return user
    return None


def build_shared_library_record(
    payload: dict[str, Any],
    *,
    actor_id: str,
    item_id: str | None = None,
    source: str | None = None,
    tenant_id: str | None = None,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    readable_data = readable_shared_data(data)
    resolved_item_id = str(item_id or payload.get("item_id") or payload.get("id") or make_id("shared_item")).strip()
    if not resolved_item_id:
        resolved_item_id = make_id("shared_item")
    category_id = str(payload.get("category_id") or data.get("category_id") or readable_data.get("category_id") or "global_guidelines")
    title = str(payload.get("title") or readable_data.get("title") or readable_data.get("name") or data.get("title") or data.get("name") or resolved_item_id)
    content = str(
        payload.get("content")
        or readable_shared_content(readable_data)
        or readable_shared_content(data)
        or json.dumps(data, ensure_ascii=False, sort_keys=True)
    )
    keywords = payload.get("keywords") if "keywords" in payload else readable_data.get("keywords")
    applies_to = payload.get("applies_to") if "applies_to" in payload else readable_data.get("applies_to")
    notes = payload.get("notes") if "notes" in payload else readable_data.get("notes")
    now = now_iso()
    record = {
        "item_id": resolved_item_id,
        "category_id": category_id,
        "title": title,
        "content": content,
        "keywords": normalize_text_list(keywords),
        "applies_to": str(applies_to or ""),
        "notes": str(notes or ""),
        "status": str(payload.get("status") or data.get("status") or "active"),
        "source": str(source or payload.get("source") or data.get("source") or ""),
        "tenant_id": active_tenant_id(tenant_id or payload.get("tenant_id") or data.get("tenant_id") or DEFAULT_TENANT_ID),
        "data": data if isinstance(data, dict) else {},
        "created_by": existing.get("created_by") if isinstance(existing, dict) else actor_id,
        "created_at": existing.get("created_at") if isinstance(existing, dict) else now,
        "updated_by": actor_id,
        "updated_at": now,
    }
    return record


def public_shared_library_record(record: dict[str, Any]) -> dict[str, Any]:
    result = dict(record)
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    readable_data = readable_shared_data(data)
    if looks_like_json_object(str(result.get("content") or "")):
        result["content"] = readable_shared_content(readable_data) or readable_shared_content(data) or str(result.get("content") or "")
    if not result.get("title"):
        result["title"] = readable_data.get("title") or readable_data.get("name") or result.get("item_id")
    result["keywords"] = normalize_text_list(result.get("keywords") or readable_data.get("keywords"))
    result["applies_to"] = str(result.get("applies_to") or readable_data.get("applies_to") or "")
    result["notes"] = str(result.get("notes") or readable_data.get("notes") or "")
    return result


def readable_shared_data(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    nested = data.get("data") if isinstance(data.get("data"), dict) else None
    if nested:
        return nested
    return data


def readable_shared_content(data: dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    parts = []
    for key in ("guideline_text", "content", "answer", "body", "service_reply", "reply_text"):
        value = data.get(key)
        if value:
            parts.append(str(value))
    if data.get("keywords") and len(parts) <= 1:
        parts.append(f"关键词：{'、'.join(normalize_text_list(data.get('keywords')))}")
    if data.get("applies_to"):
        parts.append(f"适用场景：{data.get('applies_to')}")
    return "\n".join(parts)


def normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).replace("，", ",").replace("、", ",").split(",") if item.strip()]


def looks_like_json_object(value: str) -> bool:
    text = value.strip()
    return text.startswith("{") and text.endswith("}")


def seed_shared_library_if_empty(state: dict[str, Any]) -> None:
    state.setdefault("shared_library", {})
    if state["shared_library"]:
        return
    snapshot = build_shared_knowledge_snapshot()
    for item in snapshot.get("items", []):
        if not isinstance(item, dict):
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else item
        record = build_shared_library_record(
            {
                **payload,
                "item_id": item.get("item_id") or payload.get("id"),
                "category_id": item.get("category_id") or payload.get("category_id"),
                "title": item.get("title") or payload.get("title"),
                "status": item.get("status") or payload.get("status") or "active",
                "data": payload,
            },
            actor_id="system",
            source="local_shared_snapshot",
        )
        state["shared_library"][record["item_id"]] = record


def upsert_shared_library_from_operations(
    state: dict[str, Any],
    operations: list[Any],
    *,
    actor_id: str,
    source: str,
    tenant_id: str,
) -> list[dict[str, Any]]:
    seed_shared_library_if_empty(state)
    updated: list[dict[str, Any]] = []
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        op = str(operation.get("op") or operation.get("action") or "").strip().lower()
        if op not in {"upsert", "upsert_json", "create", "update"}:
            continue
        content = operation.get("content") if isinstance(operation.get("content"), dict) else {}
        if not content:
            continue
        op_path = str(operation.get("path") or "")
        item_id = str(content.get("item_id") or content.get("id") or (Path(op_path).stem if op_path else "")).strip()
        existing = state["shared_library"].get(item_id) if item_id else None
        record = build_shared_library_record(
            content,
            actor_id=actor_id,
            item_id=item_id or None,
            source=source,
            tenant_id=tenant_id,
            existing=existing if isinstance(existing, dict) else None,
        )
        state["shared_library"][record["item_id"]] = record
        updated.append(record)
    return updated


def delete_managed_file(path: Path) -> bool:
    if not str(path) or not path.exists() or not path.is_file():
        return False
    try:
        root = runtime_app_root().resolve()
        resolved = path.resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return False
    path.unlink()
    return True


def command_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_id": record.get("command_id"),
        "type": record.get("type"),
        "tenant_id": record.get("tenant_id"),
        "node_id": record.get("node_id"),
        "payload": record.get("payload") if isinstance(record.get("payload"), dict) else {},
        "created_at": record.get("created_at"),
    }


def latest_by_created_at(items: Any) -> dict[str, Any] | None:
    values = [item for item in items if isinstance(item, dict)]
    if not values:
        return None
    return sorted(values, key=lambda item: str(item.get("created_at") or ""), reverse=True)[0]


def to_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, minimum), maximum)
