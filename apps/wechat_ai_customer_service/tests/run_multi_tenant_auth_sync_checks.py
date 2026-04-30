"""Focused checks for multi-tenant auth/RBAC and VPS-LOCAL sync scaffolding."""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
TEST_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts" / "multi_tenant_auth_sync"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.auth import AuthContext, AuthSession, AuthUser, Role, can_access  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import active_tenant_id, tenant_context  # noqa: E402
from apps.wechat_ai_customer_service.sync import BackupService, SharedPatchService, VpsLocalSyncService  # noqa: E402


_PASSWORD_OVERRIDES: dict[str, str] = {}


def main() -> int:
    cleanup_test_root()
    checks: list[Callable[[], None]] = [
        check_tenant_context,
        check_permission_rules,
        check_dev_mode_compatibility,
        check_strict_auth_and_roles,
        check_backup_manifest_package,
        check_shared_patch_safety,
        check_vps_local_offline_and_mock_command,
    ]
    results = []
    try:
        for check in checks:
            try:
                check()
                results.append({"name": check.__name__, "ok": True})
            except Exception as exc:
                results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
                break
    finally:
        restore_auth_env()
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def check_tenant_context() -> None:
    assert_equal(active_tenant_id(), "default", "default tenant")
    with tenant_context("tenant_alpha"):
        assert_equal(active_tenant_id(), "tenant_alpha", "context tenant")
    assert_equal(active_tenant_id(), "default", "context reset")


def check_permission_rules() -> None:
    admin = context_for(Role.ADMIN, "*", "default")
    customer = context_for(Role.CUSTOMER, "default", "default")
    guest = context_for(Role.GUEST, "default", "default")
    assert_true(can_access(admin, resource="shared_knowledge", action="publish", tenant_id="other"), "admin publishes shared")
    assert_true(can_access(customer, resource="tenant_knowledge", action="write", tenant_id="default"), "customer writes own tenant")
    assert_true(not can_access(customer, resource="tenant_knowledge", action="write", tenant_id="other"), "customer blocked from other tenant")
    assert_true(not can_access(customer, resource="shared_knowledge", action="write", tenant_id="default"), "customer cannot write shared")
    assert_true(can_access(customer, resource="shared_knowledge", action="sync", tenant_id="default"), "customer can upload shared candidates")
    assert_true(can_access(guest, resource="tenant_knowledge", action="read", tenant_id="default"), "guest reads")
    assert_true(not can_access(guest, resource="tenant_knowledge", action="write", tenant_id="default"), "guest write denied")
    assert_true(not can_access(guest, resource="shared_knowledge", action="sync", tenant_id="default"), "guest cannot upload shared candidates")


def check_dev_mode_compatibility() -> None:
    set_auth_env(required=False)
    client = TestClient(create_app())
    assert_equal(client.get("/api/auth/me").status_code, 200, "dev auth me")
    assert_equal(client.get("/api/tenants").status_code, 200, "dev tenants")
    status = client.get("/api/sync/status")
    assert_equal(status.status_code, 200, "dev sync status")
    assert_equal(status.json().get("mode"), "offline_unconfigured", "dev sync offline mode")


def check_strict_auth_and_roles() -> None:
    set_auth_env(required=True)
    client = TestClient(create_app())
    assert_equal(client.get("/api/knowledge/overview").status_code, 401, "strict auth blocks anonymous")

    admin_token = login(client, "admin", "1234.abcd")
    assert_equal(client.get("/api/auth/me", headers=auth_headers(admin_token)).status_code, 200, "admin me")
    assert_equal(client.get("/api/tenants", headers=auth_headers(admin_token, tenant_id="default")).status_code, 200, "admin tenants")

    guest_token = login(client, "guest", "guest-local-dev")
    assert_equal(client.get("/api/knowledge/overview", headers=auth_headers(guest_token)).status_code, 200, "guest read")
    assert_equal(client.post("/api/rag/rebuild", headers=auth_headers(guest_token)).status_code, 403, "guest write blocked")

    customer_token = login(client, "customer", "customer-local-dev")
    assert_equal(client.get("/api/knowledge/overview", headers=auth_headers(customer_token, tenant_id="default")).status_code, 200, "customer own tenant")
    assert_equal(client.get("/api/tenants", headers=auth_headers(customer_token, tenant_id="other_tenant")).status_code, 403, "customer other tenant blocked")


def check_backup_manifest_package() -> None:
    output = TEST_ROOT / "backups"
    result = BackupService(output_root=output).build_backup(scope="tenant", tenant_id="default")
    assert_true(result.get("ok") is True, "backup ok")
    package_path = Path(str(result.get("package_path")))
    assert_true(package_path.exists(), "backup package exists")
    with zipfile.ZipFile(package_path) as package:
        names = set(package.namelist())
        assert_true("manifest.json" in names, "manifest in package")
        manifest = json.loads(package.read("manifest.json").decode("utf-8"))
        assert_equal(manifest.get("tenant_id"), "default", "backup tenant")
        assert_true(any(item.get("path", "").endswith("tenant.json") for item in manifest.get("files", [])), "tenant metadata backed up")


def check_shared_patch_safety() -> None:
    root = TEST_ROOT / "shared_patch_root"
    patch = {
        "schema_version": 1,
        "patch_id": "shared_patch_test",
        "version": "test.1",
        "operations": [
            {
                "op": "upsert_json",
                "path": "global_guidelines/items/test_guideline.json",
                "content": {"schema_version": 1, "id": "test_guideline", "data": {"title": "test"}},
            }
        ],
    }
    service = SharedPatchService(root=root)
    preview = service.preview(patch)
    assert_equal(preview.get("operation_count"), 1, "patch preview count")
    applied = service.apply(patch)
    assert_true(applied.get("ok") is True, "patch apply ok")
    assert_true((root / "global_guidelines" / "items" / "test_guideline.json").exists(), "patch target written")
    unsafe = {**patch, "operations": [{**patch["operations"][0], "path": "../escape.json"}]}
    try:
        service.preview(unsafe)
    except ValueError:
        return
    raise AssertionError("unsafe shared patch path should be rejected")


def check_vps_local_offline_and_mock_command() -> None:
    service = VpsLocalSyncService(vps_base_url="", backup_service=BackupService(output_root=TEST_ROOT / "command_backups"))
    status = service.status(tenant_id="default")
    assert_equal(status.get("mode"), "offline_unconfigured", "offline status")
    registered = service.register_node(token="customer-token", tenant_id="default", display_name="Default Local")
    assert_equal(registered.get("mode"), "offline_unconfigured", "offline node registration")
    poll = service.poll_commands(tenant_id="default")
    assert_true(poll.get("ok") is True and poll.get("commands") == [], "offline poll explicit")
    result = service.handle_command({"command_id": "cmd_test", "type": "backup_tenant", "tenant_id": "default"}, tenant_id="default")
    assert_true(result.get("accepted") is True, "mock backup command accepted")
    assert_true(Path(result.get("result", {}).get("package_path", "")).exists(), "mock command created package")


def context_for(role: Role, tenant_scope: str, active_tenant: str) -> AuthContext:
    user = AuthUser(user_id=f"test-{role.value}", role=role, tenant_ids=(tenant_scope,))
    session = AuthSession(session_id=f"sess-{role.value}", user=user, active_tenant_id=active_tenant)
    return AuthContext(session=session, tenant_id=active_tenant)


def login(client: TestClient, username: str, password: str) -> str:
    candidate_passwords = []
    if username in _PASSWORD_OVERRIDES:
        candidate_passwords.append(_PASSWORD_OVERRIDES[username])
    candidate_passwords.append(password)
    for candidate_password in dict.fromkeys(candidate_passwords):
        response = client.post(
            "/api/auth/login/start",
            json={"username": username, "password": candidate_password, "tenant_id": "default", "device_id": f"multi-test-{username}"},
        )
        if response.status_code == 401:
            continue
        assert_equal(response.status_code, 200, f"{username} login start")
        body = response.json()
        if body.get("requires_initialization"):
            new_password = initialized_password(username)
            initialize_local_account(client, body, email=f"{username}@example.local", new_password=new_password)
            _PASSWORD_OVERRIDES[username] = new_password
            return login(client, username, password)
        if body.get("session"):
            token = body.get("session", {}).get("token")
            assert_true(bool(token), f"{username} token")
            return str(token)
        assert_true(bool(body.get("requires_verification")), f"{username} requires verification")
        assert_true(bool(body.get("debug_code")), f"{username} debug code")
        verified = client.post(
            "/api/auth/login/verify",
            json={"challenge_id": body["challenge_id"], "code": body["debug_code"], "trust_device": True},
        )
        assert_equal(verified.status_code, 200, f"{username} login verify")
        token = verified.json().get("session", {}).get("token")
        assert_true(bool(token), f"{username} token")
        return str(token)
    raise AssertionError(f"{username} login failed")


def initialize_local_account(client: TestClient, body: dict[str, Any], *, email: str, new_password: str) -> None:
    started = client.post(
        "/api/auth/initialize/start",
        json={"challenge_id": body["challenge_id"], "email": email, "new_password": new_password},
    )
    assert_equal(started.status_code, 200, "start local initialization")
    payload = started.json()
    assert_true(bool(payload.get("debug_code")), "local initialization debug code")
    verified = client.post(
        "/api/auth/initialize/verify",
        json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
    )
    assert_equal(verified.status_code, 200, "verify local initialization")


def initialized_password(username: str) -> str:
    return {
        "admin": "admin.5678",
        "customer": "customer.5678",
        "guest": "guest.5678",
        "test01": "test01.5678",
    }.get(username, f"{username}.5678")


def auth_headers(token: str, *, tenant_id: str = "default") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant_id}


OLD_AUTH_ENV = {
    "WECHAT_AUTH_REQUIRED": os.environ.get("WECHAT_AUTH_REQUIRED"),
    "WECHAT_VPS_BASE_URL": os.environ.get("WECHAT_VPS_BASE_URL"),
    "WECHAT_LOCAL_SESSION_PATH": os.environ.get("WECHAT_LOCAL_SESSION_PATH"),
    "WECHAT_LOCAL_ACCOUNTS_STATE_PATH": os.environ.get("WECHAT_LOCAL_ACCOUNTS_STATE_PATH"),
    "WECHAT_LOCAL_AUTH_CHALLENGE_PATH": os.environ.get("WECHAT_LOCAL_AUTH_CHALLENGE_PATH"),
    "WECHAT_LOCAL_TRUSTED_DEVICE_PATH": os.environ.get("WECHAT_LOCAL_TRUSTED_DEVICE_PATH"),
    "WECHAT_EMAIL_OTP_REQUIRED": os.environ.get("WECHAT_EMAIL_OTP_REQUIRED"),
    "WECHAT_EMAIL_OTP_DEBUG": os.environ.get("WECHAT_EMAIL_OTP_DEBUG"),
    "WECHAT_EMAIL_OUTBOX_PATH": os.environ.get("WECHAT_EMAIL_OUTBOX_PATH"),
}


def set_auth_env(*, required: bool) -> None:
    os.environ["WECHAT_AUTH_REQUIRED"] = "1" if required else "0"
    os.environ.pop("WECHAT_VPS_BASE_URL", None)
    os.environ["WECHAT_LOCAL_SESSION_PATH"] = str(TEST_ROOT / "sessions.json")
    os.environ["WECHAT_LOCAL_ACCOUNTS_STATE_PATH"] = str(TEST_ROOT / "local_accounts.json")
    os.environ["WECHAT_LOCAL_AUTH_CHALLENGE_PATH"] = str(TEST_ROOT / "local_challenges.json")
    os.environ["WECHAT_LOCAL_TRUSTED_DEVICE_PATH"] = str(TEST_ROOT / "local_trusted_devices.json")
    if required:
        os.environ["WECHAT_EMAIL_OTP_REQUIRED"] = "1"
        os.environ["WECHAT_EMAIL_OTP_DEBUG"] = "1"
        os.environ["WECHAT_EMAIL_OUTBOX_PATH"] = str(TEST_ROOT / "email_outbox.jsonl")
    else:
        os.environ.pop("WECHAT_EMAIL_OTP_REQUIRED", None)
        os.environ.pop("WECHAT_EMAIL_OTP_DEBUG", None)
        os.environ.pop("WECHAT_EMAIL_OUTBOX_PATH", None)


def restore_auth_env() -> None:
    for key, value in OLD_AUTH_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def cleanup_test_root() -> None:
    resolved = TEST_ROOT.resolve()
    expected_parent = (PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts").resolve()
    if expected_parent not in resolved.parents and resolved != expected_parent:
        raise RuntimeError(f"unsafe test cleanup path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
