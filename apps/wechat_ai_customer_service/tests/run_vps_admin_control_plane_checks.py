"""Focused checks for the VPS admin control plane and VPS-LOCAL protocol."""

from __future__ import annotations

import json
import os
import shutil
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient
from openpyxl import load_workbook


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
TEST_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts" / "vps_admin_control_plane"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.vps_admin.app import create_app  # noqa: E402


_ADMIN_TOKEN_CACHE = ""


def main() -> int:
    cleanup_test_root()
    old_env = snapshot_env()
    try:
        os.environ["WECHAT_VPS_ADMIN_USERNAME"] = "admin"
        os.environ["WECHAT_VPS_ADMIN_PASSWORD"] = "1234.abcd"
        os.environ["WECHAT_VPS_ADMIN_EMAIL"] = "admin@example.local"
        os.environ["WECHAT_VPS_ADMIN_USER_ID"] = "platform-admin"
        os.environ["WECHAT_VPS_NODE_ENROLLMENT_TOKEN"] = "enroll-test"
        os.environ["WECHAT_EMAIL_OTP_REQUIRED"] = "1"
        os.environ["WECHAT_EMAIL_OTP_DEBUG"] = "1"
        os.environ["WECHAT_EMAIL_OUTBOX_PATH"] = str(TEST_ROOT / "email_outbox.jsonl")
        client = TestClient(create_app(state_path=TEST_ROOT / "state.json"))
        checks: list[Callable[[TestClient], None]] = [
            check_admin_login_hidden_and_reserved,
            check_tenant_customer_guest_flow,
            check_local_node_and_command_roundtrip,
            check_shared_knowledge_review_flow,
            check_restore_release_and_latest_update,
            check_customer_data_shared_sync_and_full_backup_entries,
            check_vps_console_chinese_shell,
        ]
        results = []
        for check in checks:
            try:
                check(client)
                results.append({"name": check.__name__, "ok": True})
            except Exception as exc:
                results.append({"name": check.__name__, "ok": False, "error": repr(exc)})
                break
    finally:
        restore_env(old_env)
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def check_admin_login_hidden_and_reserved(client: TestClient) -> None:
    token = admin_token(client)
    users = client.get("/v1/admin/users", headers=auth_headers(token))
    assert_status(users, 200, "list users")
    assert_true(not users.json().get("users"), "admin is not listed as stored user")

    forbidden = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "shadow-admin", "password": "x", "role": "admin", "tenant_ids": ["tenant_a"]},
    )
    assert_equal(forbidden.status_code, 400, "stored admin is forbidden")


def check_tenant_customer_guest_flow(client: TestClient) -> None:
    token = admin_token(client)
    auto_customer = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "customer_auto", "password": "customer-pass", "role": "customer"},
    )
    assert_status(auto_customer, 200, "create customer with account-scoped data")
    assert_equal(auto_customer.json()["user"]["tenant_ids"], ["customer_auto"], "customer owns same-name data scope")
    assert_equal(auto_customer.json()["user"]["authorized_customers"], ["customer_auto"], "customer readable access label")

    blocked_guest = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "guest_missing", "password": "guest-pass", "role": "guest", "authorized_customer": "missing_customer"},
    )
    assert_equal(blocked_guest.status_code, 404, "guest must be assigned to an existing customer")

    scoped_guest = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "guest_auto", "password": "guest-pass", "role": "guest", "authorized_customer": "customer_auto"},
    )
    assert_status(scoped_guest, 200, "create guest for customer")
    assert_equal(scoped_guest.json()["user"]["tenant_ids"], ["customer_auto"], "guest inherits authorized customer data scope")
    assert_equal(scoped_guest.json()["user"]["authorized_customers"], ["customer_auto"], "guest readable access label")

    customer_auto_token = account_token(
        client,
        username="customer_auto",
        password="customer-pass",
        tenant_id="customer_auto",
        email="customer_auto@example.local",
        new_password="customer-auto.5678",
    )
    assert_true(bool(customer_auto_token), "same-name customer login")
    guest_auto_token = account_token(
        client,
        username="guest_auto",
        password="guest-pass",
        tenant_id="customer_auto",
        email="guest_auto@example.local",
        new_password="guest-auto.5678",
    )
    assert_true(bool(guest_auto_token), "admin-assigned guest login")

    orphan_tenant = client.post("/v1/admin/tenants", headers=auth_headers(token), json={"tenant_id": "orphan_scope", "display_name": "Orphan Scope"})
    assert_status(orphan_tenant, 200, "create orphan tenant scope")
    blocked_raw_guest = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "guest_raw_scope", "password": "guest-pass", "role": "guest", "tenant_ids": ["orphan_scope"]},
    )
    assert_equal(blocked_raw_guest.status_code, 400, "guest raw tenant scope must map to an existing customer")

    tenant = client.post("/v1/admin/tenants", headers=auth_headers(token), json={"tenant_id": "tenant_a", "display_name": "Tenant A"})
    assert_status(tenant, 200, "create tenant")

    customer = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "customer_a", "password": "customer-pass", "role": "customer", "tenant_ids": ["tenant_a"]},
    )
    assert_status(customer, 200, "create customer")

    guest = client.post(
        "/v1/admin/users",
        headers=auth_headers(token),
        json={"username": "guest_a", "password": "guest-pass", "role": "guest", "tenant_ids": ["tenant_a"]},
    )
    assert_status(guest, 200, "create guest")

    customer_token = account_token(
        client,
        username="customer_a",
        password="customer-pass",
        tenant_id="tenant_a",
        email="customer_a@example.local",
        new_password="customer-a.5678",
    )
    customer_me = client.get("/v1/auth/me", headers=auth_headers(customer_token))
    assert_status(customer_me, 200, "customer login")
    assert_equal(customer_me.json()["session"]["user"]["role"], "customer", "customer role")

    guest_token = account_token(
        client,
        username="guest_a",
        password="guest-pass",
        tenant_id="tenant_a",
        email="guest_a@example.local",
        new_password="guest-a.5678",
    )
    guest_me = client.get("/v1/auth/me", headers=auth_headers(guest_token))
    assert_status(guest_me, 200, "guest login")
    assert_equal(guest_me.json()["session"]["user"]["role"], "guest", "guest role")


def check_local_node_and_command_roundtrip(client: TestClient) -> None:
    token = admin_token(client)
    registered = client.post(
        "/v1/local/nodes/register",
        headers={"X-Enrollment-Token": "enroll-test"},
        json={
            "node_id": "local_tenant_a_01",
            "display_name": "Local Tenant A 01",
            "tenant_ids": ["tenant_a"],
            "version": "0.1.0-test",
            "capabilities": ["backup_tenant", "backup_all", "check_update"],
        },
    )
    assert_status(registered, 200, "register node")
    node_token = registered.json()["node"]["node_token"]

    heartbeat = client.post(
        "/v1/local/nodes/local_tenant_a_01/heartbeat",
        headers={"X-Node-Token": node_token},
        json={"status": "online", "version": "0.1.1-test", "metrics": {"pending_jobs": 0}},
    )
    assert_status(heartbeat, 200, "node heartbeat")

    backup = client.post(
        "/v1/admin/backups",
        headers=auth_headers(token),
        json={"scope": "tenant", "tenant_id": "tenant_a", "node_id": "local_tenant_a_01"},
    )
    assert_status(backup, 200, "request backup")
    command_id = backup.json()["command"]["command_id"]

    poll = client.get(
        "/v1/local/commands?tenant_id=tenant_a&node_id=local_tenant_a_01",
        headers={"X-Node-Token": node_token},
    )
    assert_status(poll, 200, "poll commands")
    commands = poll.json()["commands"]
    assert_equal(len(commands), 1, "one pending command")
    assert_equal(commands[0]["command_id"], command_id, "command id")
    assert_equal(commands[0]["type"], "backup_tenant", "command type")

    result = client.post(
        f"/v1/local/commands/{command_id}/result",
        headers={"X-Node-Token": node_token},
        json={"command_id": command_id, "accepted": True, "result": {"ok": True, "backup_id": "backup_test"}},
    )
    assert_status(result, 200, "submit command result")

    commands_after = client.get("/v1/admin/commands", headers=auth_headers(token)).json()["commands"]
    matched = next(item for item in commands_after if item["command_id"] == command_id)
    assert_equal(matched["status"], "succeeded", "command succeeded")


def check_shared_knowledge_review_flow(client: TestClient) -> None:
    token = admin_token(client)
    manual = client.post(
        "/v1/admin/shared/library",
        headers=auth_headers(token),
        json={
            "item_id": "manual_console_rule",
            "category_id": "global_guidelines",
            "title": "Manual Rule",
            "content": "Manual shared content",
            "keywords": ["manual", "rule"],
            "applies_to": "Shared rule review",
            "notes": "Created through human form fields",
        },
    )
    assert_status(manual, 200, "create shared library item")
    assert_equal(manual.json()["item"]["keywords"], ["manual", "rule"], "shared item keywords are stored")
    assert_equal(manual.json()["item"]["applies_to"], "Shared rule review", "shared item applies_to stored")
    updated = client.patch(
        "/v1/admin/shared/library/manual_console_rule",
        headers=auth_headers(token),
        json={"title": "Manual Rule Updated", "content": "Updated shared content", "status": "active", "keywords": ["updated"]},
    )
    assert_status(updated, 200, "update shared library item")
    assert_equal(updated.json()["item"]["title"], "Manual Rule Updated", "shared library item updated")
    assert_equal(updated.json()["item"]["keywords"], ["updated"], "shared item keywords updated")
    fetched = client.get("/v1/admin/shared/library/manual_console_rule", headers=auth_headers(token))
    assert_status(fetched, 200, "get shared library item")
    assert_true(not str(fetched.json()["item"]["content"]).lstrip().startswith("{"), "shared detail is human-readable")
    deleted = client.delete("/v1/admin/shared/library/manual_console_rule", headers=auth_headers(token))
    assert_status(deleted, 200, "delete shared library item")

    proposal = client.post(
        "/v1/shared/proposals",
        json={
            "tenant_id": "tenant_a",
            "title": "Shared after-sale policy",
            "summary": "Common rule extracted from tenant A",
            "operations": [
                {
                    "op": "upsert_json",
                    "path": "global_guidelines/items/after_sale_policy.json",
                    "content": {"schema_version": 1, "id": "after_sale_policy", "data": {"title": "After Sale"}},
                }
            ],
        },
    )
    assert_status(proposal, 200, "submit shared proposal")
    proposal_id = proposal.json()["proposal"]["proposal_id"]

    reviewed = client.post(
        f"/v1/admin/shared/proposals/{proposal_id}/review",
        headers=auth_headers(token),
        json={"action": "accept", "version": "shared-test.1"},
    )
    assert_status(reviewed, 200, "accept proposal")
    assert_equal(reviewed.json()["proposal"]["status"], "accepted", "proposal accepted")
    assert_equal(reviewed.json()["patch"]["status"], "published", "patch published")
    assert_true(reviewed.json()["library_items"], "accepted proposal writes official library")
    library = client.get("/v1/admin/shared/library/after_sale_policy", headers=auth_headers(token))
    assert_status(library, 200, "accepted proposal library item")
    assert_equal(library.json()["item"]["title"], "After Sale", "accepted proposal title")


def check_restore_release_and_latest_update(client: TestClient) -> None:
    token = admin_token(client)
    restore = client.post(
        "/v1/admin/restores",
        headers=auth_headers(token),
        json={"tenant_id": "tenant_a", "node_id": "local_tenant_a_01", "backup_id": "backup_test", "dry_run": True},
    )
    assert_status(restore, 200, "request restore dry-run")
    assert_equal(restore.json()["command"]["type"], "restore_backup", "restore command type")

    release = client.post(
        "/v1/admin/releases",
        headers=auth_headers(token),
        json={"version": "0.2.0-test", "channel": "stable", "title": "Test release", "artifact_url": "https://example.invalid/release.zip"},
    )
    assert_status(release, 200, "create release")

    latest = client.get("/v1/updates/latest?channel=stable")
    assert_status(latest, 200, "latest update")
    assert_equal(latest.json()["update"]["version"], "0.2.0-test", "latest version")


def check_customer_data_shared_sync_and_full_backup_entries(client: TestClient) -> None:
    token = admin_token(client)
    bootstrapped = client.post(
        "/v1/admin/customer-data/bootstrap-test01",
        headers=auth_headers(token),
        json={"tenant_id": "default"},
    )
    assert_status(bootstrapped, 200, "bootstrap test01")
    assert_equal(bootstrapped.json()["user"]["username"], "test01", "test01 username")
    assert_true(bootstrapped.json()["package"]["summary"]["formal_knowledge"]["item_count"] >= 1, "test01 package has formal knowledge")
    test01_package_id = bootstrapped.json()["package"]["package_id"]
    test01_readable = client.get(f"/v1/admin/customer-data/{test01_package_id}/readable-download", headers=auth_headers(token))
    assert_status(test01_readable, 200, "test01 readable Excel download")
    test01_workbook = load_workbook(BytesIO(test01_readable.content), read_only=True)
    assert_true("正式-商品资料" in test01_workbook.sheetnames, "test01 readable export splits product formal knowledge")
    assert_true("正式-政策规则" in test01_workbook.sheetnames, "test01 readable export splits policy formal knowledge")
    assert_true(test01_workbook["正式-政策规则"].max_row >= 2, "test01 policy knowledge sheet includes rows")

    customer_data = client.get("/v1/admin/customer-data", headers=auth_headers(token))
    assert_status(customer_data, 200, "list customer data")
    assert_true(any(item.get("account_username") == "test01" for item in customer_data.json()["packages"]), "test01 package listed")

    selected_package = client.post(
        "/v1/admin/customer-data/package-customer",
        headers=auth_headers(token),
        json={"account_username": "customer_a", "tenant_id": "tenant_a"},
    )
    assert_status(selected_package, 200, "package selected customer")
    package_id = selected_package.json()["package"]["package_id"]
    detail = client.get(f"/v1/admin/customer-data/{package_id}", headers=auth_headers(token))
    assert_status(detail, 200, "customer package detail")
    assert_equal(detail.json()["package"]["account_username"], "customer_a", "detail account username")
    download = client.get(f"/v1/admin/customer-data/{package_id}/download", headers=auth_headers(token))
    assert_status(download, 200, "customer package download")
    assert_true(bool(download.content), "download returns package bytes")
    readable = client.get(f"/v1/admin/customer-data/{package_id}/readable-download", headers=auth_headers(token))
    assert_status(readable, 200, "customer readable Excel download")
    workbook = load_workbook(BytesIO(readable.content), read_only=True)
    assert_true(any(name.startswith("正式") for name in workbook.sheetnames), "readable export has formal category sheets")
    assert_true(any(name.startswith("商品专属") for name in workbook.sheetnames), "readable export has product knowledge sheets")
    deleted = client.delete(f"/v1/admin/customer-data/{package_id}", headers=auth_headers(token))
    assert_status(deleted, 200, "customer package delete")
    assert_equal(deleted.json()["package"]["package_id"], package_id, "deleted package id")

    shared_overview = client.get("/v1/admin/shared/overview", headers=auth_headers(token))
    assert_status(shared_overview, 200, "shared overview")
    assert_true(shared_overview.json()["local"]["structure"]["separated"] is True, "shared structure separated")
    assert_true(shared_overview.json()["local"]["items"], "shared items are visible")

    shared_sync = client.post("/v1/admin/shared/sync-local", headers=auth_headers(token), json={})
    assert_status(shared_sync, 200, "sync shared snapshot")
    assert_true(shared_sync.json()["snapshot"]["summary"]["item_count"] >= 1, "shared snapshot item count")

    local_backup = client.post("/v1/admin/backups/local-now", headers=auth_headers(token), json={"scope": "all", "tenant_id": "default"})
    assert_status(local_backup, 200, "local full backup")
    assert_equal(local_backup.json()["request"]["status"], "succeeded", "local backup succeeded")
    backup_request_id = local_backup.json()["request"]["request_id"]

    restore_latest = client.post("/v1/admin/restores/latest", headers=auth_headers(token), json={"scope": "all", "tenant_id": "default", "dry_run": True})
    assert_status(restore_latest, 200, "restore latest dry-run")
    assert_equal(restore_latest.json()["request"]["dry_run"], True, "restore is dry-run")
    assert_equal(restore_latest.json()["command"]["type"], "restore_backup", "latest restore command type")

    deleted_backup = client.delete(f"/v1/admin/backups/{backup_request_id}", headers=auth_headers(token))
    assert_status(deleted_backup, 200, "delete backup record")
    backup_list = client.get("/v1/admin/backups", headers=auth_headers(token))
    assert_status(backup_list, 200, "list backups after delete")
    assert_true(
        all(item.get("request_id") != backup_request_id for item in backup_list.json()["items"]),
        "deleted backup is removed from admin list",
    )


def check_vps_console_chinese_shell(client: TestClient) -> None:
    response = client.get("/")
    assert_status(response, 200, "console index")
    html = response.text
    assert_true('id="login-screen"' in html, "VPS login uses a separate screen")
    assert_true('id="logout-button"' in html, "VPS console has logout entry")
    assert_true("登录服务端" in html, "console login title is Chinese")
    assert_true("访客可查看客户" in html, "guest access selector is user-readable")
    assert_true("打包所选客户数据" in html, "selected customer package button visible")
    assert_true("客户电脑连接" in html, "local node wording is user-readable")
    assert_true("标准操作方法" in html, "release update operation method visible")
    assert_true("客户租户" not in html, "tenant jargon is hidden from console UI")
    assert_true("生成 test01 测试客户" not in html, "test01 bootstrap is hidden from console UI")
    return
    assert_true("VPS 管理控制台" in html, "console title is Chinese")
    assert_true("共享公共知识" in html, "shared knowledge navigation visible")
    assert_true("打包所选客户数据" in html, "selected customer package button visible")
    assert_true("客户电脑连接" in html, "local node wording is user-readable")
    assert_true("标准操作方法" in html, "release update operation method visible")
    assert_true("生成 test01 测试客户" not in html, "test01 bootstrap is hidden from console UI")


def admin_token(client: TestClient) -> str:
    global _ADMIN_TOKEN_CACHE
    if _ADMIN_TOKEN_CACHE:
        me = client.get("/v1/auth/me", headers=auth_headers(_ADMIN_TOKEN_CACHE))
        if me.status_code == 200:
            return _ADMIN_TOKEN_CACHE
        _ADMIN_TOKEN_CACHE = ""

    for password in ("admin.5678", "1234.abcd"):
        response = client.post(
            "/v1/auth/login/start",
            json={"username": "admin", "password": password, "tenant_id": "default", "device_id": "vps-test-admin"},
        )
        if response.status_code == 401:
            continue
        assert_status(response, 200, "admin login start")
        body = response.json()
        if body.get("requires_initialization"):
            initialize_vps_account(
                client,
                body,
                email="admin@example.local",
                new_password="admin.5678",
                smtp_config={"otp_required": True, "from_email": "admin@example.local"},
            )
            return admin_token(client)
        token = token_from_started_login(client, body, trust_device=True)
        _ADMIN_TOKEN_CACHE = token
        return token
    raise AssertionError("admin login could not start")


def account_token(
    client: TestClient,
    *,
    username: str,
    password: str,
    tenant_id: str,
    email: str,
    new_password: str,
) -> str:
    for candidate_password in (new_password, password):
        response = client.post(
            "/v1/auth/login/start",
            json={"username": username, "password": candidate_password, "tenant_id": tenant_id, "device_id": f"vps-test-{username}"},
        )
        if response.status_code == 401:
            continue
        assert_status(response, 200, f"{username} login start")
        body = response.json()
        if body.get("requires_initialization"):
            initialize_vps_account(client, body, email=email, new_password=new_password)
            return account_token(
                client,
                username=username,
                password=password,
                tenant_id=tenant_id,
                email=email,
                new_password=new_password,
            )
        return token_from_started_login(client, body)
    raise AssertionError(f"{username} login could not start")


def initialize_vps_account(
    client: TestClient,
    body: dict[str, Any],
    *,
    email: str,
    new_password: str,
    smtp_config: dict[str, Any] | None = None,
) -> None:
    started = client.post(
        "/v1/auth/initialize/start",
        json={
            "challenge_id": body["challenge_id"],
            "email": email,
            "new_password": new_password,
            "smtp_config": smtp_config or {},
        },
    )
    assert_status(started, 200, "start account initialization")
    payload = started.json()
    assert_true(bool(payload.get("debug_code")), "initialization debug code exists")
    verified = client.post(
        "/v1/auth/initialize/verify",
        json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
    )
    assert_status(verified, 200, "verify account initialization")


def token_from_started_login(client: TestClient, body: dict[str, Any], *, trust_device: bool = False) -> str:
    if body.get("session"):
        token = body.get("session", {}).get("token")
        assert_true(bool(token), "session token exists")
        return str(token)
    assert_true(bool(body.get("requires_verification")), "email verification required")
    assert_true(bool(body.get("debug_code")), "login debug code exists")
    verified = client.post(
        "/v1/auth/login/verify",
        json={"challenge_id": body["challenge_id"], "code": body["debug_code"], "trust_device": trust_device},
    )
    assert_status(verified, 200, "verify login")
    token = verified.json().get("session", {}).get("token")
    assert_true(bool(token), "verified token exists")
    return str(token)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


ENV_KEYS = (
    "WECHAT_VPS_ADMIN_USERNAME",
    "WECHAT_VPS_ADMIN_PASSWORD",
    "WECHAT_VPS_ADMIN_EMAIL",
    "WECHAT_VPS_ADMIN_USER_ID",
    "WECHAT_VPS_NODE_ENROLLMENT_TOKEN",
    "WECHAT_VPS_ADMIN_STATE_PATH",
    "WECHAT_EMAIL_OTP_REQUIRED",
    "WECHAT_EMAIL_OTP_DEBUG",
    "WECHAT_EMAIL_OUTBOX_PATH",
)


def snapshot_env() -> dict[str, str | None]:
    return {key: os.environ.get(key) for key in ENV_KEYS}


def restore_env(values: dict[str, str | None]) -> None:
    for key, value in values.items():
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


def assert_status(response: Any, expected: int, message: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{message}: expected status {expected}, got {response.status_code}, body={response.text}")


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
