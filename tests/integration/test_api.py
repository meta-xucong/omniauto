"""FastAPI REST API 集成测试."""

import pytest
from fastapi.testclient import TestClient

from omniauto.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_plan_endpoint(client):
    resp = client.post("/plan", json={"description": "访问百度搜索影刀RPA"})
    assert resp.status_code == 200
    data = resp.json()
    assert "steps" in data


def test_steps_endpoint(client):
    resp = client.get("/steps")
    assert resp.status_code == 200
    data = resp.json()
    assert any(s["name"] == "NavigateStep" for s in data["steps"])


def test_validate_endpoint(client, tmp_path):
    script = tmp_path / "safe.py"
    script.write_text("async def run(ctx): return None\n", encoding="utf-8")
    resp = client.post("/validate", json={"script_path": str(script)})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
