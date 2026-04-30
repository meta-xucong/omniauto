"""Focused checks for Local login and admin-only shared public knowledge console."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient


APP_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = APP_ROOT.parents[1]
TEST_ROOT = PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts" / "local_auth_shared_console"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.wechat_ai_customer_service.admin_backend.app import create_app  # noqa: E402
from apps.wechat_ai_customer_service.knowledge_paths import SHARED_KNOWLEDGE_ROOT  # noqa: E402


TEST_ITEM_ID = "codex_shared_public_test"
_PASSWORD_OVERRIDES: dict[str, str] = {}


def main() -> int:
    old_env = snapshot_env()
    cleanup_test_root()
    cleanup_test_item()
    try:
        os.environ["WECHAT_AUTH_REQUIRED"] = "1"
        os.environ.pop("WECHAT_VPS_BASE_URL", None)
        os.environ["WECHAT_LOCAL_SESSION_PATH"] = str(TEST_ROOT / "sessions.json")
        os.environ["WECHAT_LOCAL_ACCOUNTS_STATE_PATH"] = str(TEST_ROOT / "local_accounts.json")
        os.environ["WECHAT_LOCAL_AUTH_CHALLENGE_PATH"] = str(TEST_ROOT / "local_challenges.json")
        os.environ["WECHAT_LOCAL_TRUSTED_DEVICE_PATH"] = str(TEST_ROOT / "local_trusted_devices.json")
        os.environ["WECHAT_EMAIL_OTP_REQUIRED"] = "1"
        os.environ["WECHAT_EMAIL_OTP_DEBUG"] = "1"
        os.environ["WECHAT_EMAIL_OUTBOX_PATH"] = str(TEST_ROOT / "email_outbox.jsonl")
        client = TestClient(create_app())
        checks: list[Callable[[TestClient], None]] = [
            check_login_shell_present,
            check_test01_customer_login,
            check_customer_register_node_offline,
            check_shared_public_admin_only,
            check_customer_can_upload_candidates_but_not_edit_shared,
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
        cleanup_test_item()
        restore_env(old_env)
    failures = [item for item in results if not item.get("ok")]
    print(json.dumps({"ok": not failures, "count": len(results), "failures": failures, "results": results}, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


def check_login_shell_present(client: TestClient) -> None:
    response = client.get("/")
    assert_status(response, 200, "local index")
    html = response.text
    assert_true('id="login-screen"' in html, "login screen present")
    assert_true('id="local-init-screen"' in html, "first-login initialization screen present")
    assert_true('id="local-login-form"' in html, "login form present")
    assert_true('id="local-logout-button"' in html, "logout button present")
    assert_true("退出登录" in html, "logout label is Chinese")
    assert_true("共享公共知识库" in html, "shared public admin nav present")
    assert_true("admin-only-nav" in html, "shared nav is admin-only")
    assert_true("填入管理员" not in html, "admin shortcut is hidden from customer login")
    assert_true("管理员登录后" not in html, "admin capability is not advertised on customer login")
    assert_true("placeholder=\"请输入账号\"" in html and "placeholder=\"请输入密码\"" in html, "login placeholders are generic")
    return
    assert_true("登录客户端" in html, "login screen present")
    assert_true("共享公共知识库" in html, "shared public admin nav present")
    assert_true("admin-only-nav" in html, "shared nav is admin-only")
    assert_true("test01" in html and "1234.abcd" in html, "customer test01 login hint present")


def check_test01_customer_login(client: TestClient) -> None:
    token = login(client, "test01", "1234.abcd")
    me = client.get("/api/auth/me", headers=auth_headers(token))
    assert_status(me, 200, "customer me")
    assert_equal(me.json()["auth"]["session"]["user"]["role"], "customer", "test01 customer role")


def check_customer_register_node_offline(client: TestClient) -> None:
    token = login(client, "test01", "1234.abcd")
    registered = client.post(
        "/api/sync/register-node",
        headers=auth_headers(token),
        json={"display_name": "test01 Local"},
    )
    assert_status(registered, 200, "customer can register local node route")
    assert_equal(registered.json()["mode"], "offline_unconfigured", "offline node registration is safe")


def check_shared_public_admin_only(client: TestClient) -> None:
    admin = login(client, "admin", "1234.abcd")
    listed = client.get("/api/shared-knowledge/items", headers=auth_headers(admin))
    assert_status(listed, 200, "admin shared list")

    created = client.post(
        "/api/shared-knowledge/items",
        headers=auth_headers(admin),
        json={"item_id": TEST_ITEM_ID, "category_id": "global_guidelines", "title": "Codex Shared Test", "content": "Shared body"},
    )
    assert_status(created, 200, "admin create shared item")
    fetched = client.get(f"/api/shared-knowledge/items/{TEST_ITEM_ID}", headers=auth_headers(admin))
    assert_status(fetched, 200, "admin get shared item")
    assert_equal(fetched.json()["item"]["data"]["title"], "Codex Shared Test", "created title")

    updated = client.put(
        f"/api/shared-knowledge/items/{TEST_ITEM_ID}",
        headers=auth_headers(admin),
        json={"title": "Codex Shared Test Updated", "content": "Updated body", "category_id": "global_guidelines"},
    )
    assert_status(updated, 200, "admin update shared item")
    assert_equal(updated.json()["item"]["data"]["title"], "Codex Shared Test Updated", "updated title")

    deleted = client.delete(f"/api/shared-knowledge/items/{TEST_ITEM_ID}", headers=auth_headers(admin))
    assert_status(deleted, 200, "admin delete shared item")
    missing = client.get(f"/api/shared-knowledge/items/{TEST_ITEM_ID}", headers=auth_headers(admin))
    assert_equal(missing.status_code, 404, "deleted shared item missing")


def check_customer_can_upload_candidates_but_not_edit_shared(client: TestClient) -> None:
    customer = login(client, "test01", "1234.abcd")
    blocked = client.get("/api/shared-knowledge/items", headers=auth_headers(customer))
    assert_equal(blocked.status_code, 403, "customer cannot view admin shared console API")
    upload = client.post("/api/sync/shared/upload-candidates", headers=auth_headers(customer), json={})
    assert_status(upload, 200, "customer can submit shared candidates")
    assert_equal(upload.json()["mode"], "offline_unconfigured", "candidate upload is safely skipped offline")


def login(client: TestClient, username: str, password: str) -> str:
    candidate_passwords = []
    if username in _PASSWORD_OVERRIDES:
        candidate_passwords.append(_PASSWORD_OVERRIDES[username])
    candidate_passwords.append(password)
    for candidate_password in dict.fromkeys(candidate_passwords):
        response = client.post(
            "/api/auth/login/start",
            json={"username": username, "password": candidate_password, "tenant_id": "default", "device_id": f"local-test-{username}"},
        )
        if response.status_code == 401:
            continue
        assert_status(response, 200, f"{username} login start")
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
        assert_status(verified, 200, f"{username} login verify")
        token = verified.json().get("session", {}).get("token")
        assert_true(bool(token), f"{username} token")
        return str(token)
    raise AssertionError(f"{username} login failed")


def initialize_local_account(client: TestClient, body: dict[str, Any], *, email: str, new_password: str) -> None:
    started = client.post(
        "/api/auth/initialize/start",
        json={"challenge_id": body["challenge_id"], "email": email, "new_password": new_password},
    )
    assert_status(started, 200, "start local initialization")
    payload = started.json()
    assert_true(bool(payload.get("debug_code")), "local initialization debug code")
    verified = client.post(
        "/api/auth/initialize/verify",
        json={"challenge_id": payload["challenge_id"], "code": payload["debug_code"]},
    )
    assert_status(verified, 200, "verify local initialization")


def initialized_password(username: str) -> str:
    return {
        "admin": "admin.5678",
        "test01": "test01.5678",
        "customer": "customer.5678",
        "guest": "guest.5678",
    }.get(username, f"{username}.5678")


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-ID": "default"}


def cleanup_test_item() -> None:
    target = SHARED_KNOWLEDGE_ROOT / "global_guidelines" / "items" / f"{TEST_ITEM_ID}.json"
    if not target.exists():
        return
    resolved = target.resolve()
    root = SHARED_KNOWLEDGE_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"unsafe cleanup target: {resolved}") from exc
    resolved.unlink()


def cleanup_test_root() -> None:
    resolved = TEST_ROOT.resolve()
    expected_parent = (PROJECT_ROOT / "runtime" / "apps" / "wechat_ai_customer_service" / "test_artifacts").resolve()
    if expected_parent not in resolved.parents and resolved != expected_parent:
        raise RuntimeError(f"unsafe test cleanup path: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True, exist_ok=True)


ENV_KEYS = (
    "WECHAT_AUTH_REQUIRED",
    "WECHAT_VPS_BASE_URL",
    "WECHAT_LOCAL_SESSION_PATH",
    "WECHAT_LOCAL_ACCOUNTS_STATE_PATH",
    "WECHAT_LOCAL_AUTH_CHALLENGE_PATH",
    "WECHAT_LOCAL_TRUSTED_DEVICE_PATH",
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
