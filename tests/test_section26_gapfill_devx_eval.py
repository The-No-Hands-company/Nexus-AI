import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app
from src.api.routes import _make_token


client = TestClient(app)


def test_api_playground_route_available():
    resp = client.get("/playground")
    assert resp.status_code == 200
    assert "Nexus API Playground" in resp.text


def test_dev_sandbox_chat_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NEXUS_DEV_SANDBOX", raising=False)
    resp = client.post("/dev/sandbox/chat", json={"prompt": "hello"})
    assert resp.status_code == 403


def test_dev_sandbox_chat_enabled(monkeypatch):
    monkeypatch.setenv("NEXUS_DEV_SANDBOX", "1")
    resp = client.post("/dev/sandbox/chat", json={"prompt": "return json please"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["sandbox"] is True
    assert payload["model"] == "nexus-sandbox/mock-llm"


def test_eval_suite_supports_advglue_and_multilingual():
    resp = client.post(
        "/benchmark/eval-suite",
        json={
            "model": "nexus-ai/auto",
            "provider": "openai",
            "suites": ["advglue", "multilingual"],
            "n_samples": 3,
        },
    )
    assert resp.status_code == 200
    payload = resp.json()
    suites = {job["suite"] for job in payload["jobs"]}
    assert "advglue" in suites
    assert "multilingual" in suites


def test_capacity_planning_report_endpoint():
    admin_headers = {"Authorization": f"Bearer {_make_token('pytest_admin', role='admin')}"}
    resp = client.get("/admin/capacity/planning?days=14&horizon_days=7", headers=admin_headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["days"] == 14
    assert payload["horizon_days"] == 7
    assert "projected_tokens" in payload
