import json

from starlette.testclient import TestClient

from src.app import app
from src.db import log_usage


client = TestClient(app, raise_server_exceptions=True)


def test_usage_summary_and_export_formats():
    log_usage("groq", "llama-3.3-70b", 120, 240, tt="chat", username="user:alice", cost_usd=0.001)
    log_usage("ollama", "qwen2.5:14b", 90, 130, tt="chat", username="user:bob", cost_usd=0.0)

    summary = client.get("/usage?days=365")
    assert summary.status_code == 200
    payload = summary.json()
    assert "totals" in payload
    assert payload["totals"]["calls"] >= 2
    assert any(entry.get("username") in {"user:alice", "user:bob"} for entry in payload.get("per_user", []))

    export_json = client.get("/usage/export?days=365&format=json")
    assert export_json.status_code == 200
    json_payload = export_json.json()
    assert json_payload["count"] >= 2
    assert any(row.get("username") == "user:alice" for row in json_payload.get("records", []))

    export_csv = client.get("/usage/export?days=365&format=csv")
    assert export_csv.status_code == 200
    assert "text/csv" in export_csv.headers.get("content-type", "")
    assert "provider,model" in export_csv.text


def test_usage_webhook_push(monkeypatch):
    captured = {}
    monkeypatch.setattr("src.api.routes.MULTI_USER", False)

    class _DummyResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = req.data.decode("utf-8")
        captured["timeout"] = timeout
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    cfg = client.post(
        "/usage/webhook",
        json={"enabled": True, "url": "https://example.com/usage-hook", "secret": "test-secret"},  # pragma: allowlist secret
    )
    assert cfg.status_code == 200
    assert cfg.json().get("ok") is True

    pushed = client.post("/usage/webhook/push?days=1")
    assert pushed.status_code == 200
    assert pushed.json().get("ok") is True
    assert captured.get("url") == "https://example.com/usage-hook"
    assert captured.get("timeout") == 10
    assert "x-nexus-signature" in {k.lower() for k in captured.get("headers", {})}

    body = json.loads(captured.get("body") or "{}")
    assert "totals" in body
