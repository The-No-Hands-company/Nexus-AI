import uuid
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app import app


client = TestClient(app)


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_blueprint_version_lifecycle_endpoints():
    name = _unique("bp-hardening")

    r1 = client.post("/architecture/blueprints", json={"name": name, "notes": "v1"})
    assert r1.status_code == 200
    v1 = r1.json()["blueprint"]["version"]

    r2 = client.post("/architecture/blueprints", json={"name": name, "notes": "v2"})
    assert r2.status_code == 200
    v2 = r2.json()["blueprint"]["version"]
    assert v2 == v1 + 1

    versions = client.get(f"/architecture/blueprints/{name}/versions")
    assert versions.status_code == 200
    payload = versions.json()
    assert payload["name"] == name
    assert payload["latest_version"] == v2
    assert len(payload["versions"]) >= 2

    activate = client.post(
        f"/architecture/blueprints/{name}/activate",
        json={"version": v1, "actor": "pytest"},
    )
    assert activate.status_code == 200
    assert activate.json()["active"]["version"] == v1

    active = client.get(f"/architecture/blueprints/{name}/active")
    assert active.status_code == 200
    assert active.json()["active"]["version"] == v1


def test_auto_generated_test_case_endpoints_roundtrip(monkeypatch):
    # Keep this endpoint test deterministic and fast.
    monkeypatch.setattr(
        "src.api.routes.run_agent_task",
        lambda prompt, history=None, files=None, sid="", usage_principal="": {"result": "reverse values list slicing"},
    )

    # Enable trace collection and store one interaction trace.
    consent = client.post("/feedback/consent", json={"trace_opt_in": True})
    assert consent.status_code == 200

    trace = client.post(
        "/feedback/trace",
        json={
            "chat_id": _unique("chat"),
            "message_idx": 1,
            "prompt": "Write a Python function to reverse a list.",
            "response": "Use slicing: return values[::-1] or list(reversed(values)).",
            "provider": "pytest",
            "model": "pytest-model",
        },
    )
    assert trace.status_code == 200

    generated = client.post(
        "/agent/test-cases/generate",
        json={"max_cases": 5, "source_limit": 100},
    )
    assert generated.status_code == 200
    gp = generated.json()
    assert gp["generated"] >= 1

    listed = client.get("/agent/test-cases?limit=10")
    assert listed.status_code == 200
    lp = listed.json()
    assert lp["total"] >= 1

    run = client.post("/agent/test-cases/run", json={"limit": 1})
    assert run.status_code == 200
    rp = run.json()
    assert "pass_pct" in rp
    assert rp["total"] >= 0


def test_safety_gate_config_roundtrip():
    current = client.get("/benchmark/safety/gate")
    assert current.status_code == 200
    old_cfg = current.json()["config"]

    updated = {
        "enabled": True,
        "min_pass_pct": 77.0,
        "min_cases": 2,
        "window": 4,
    }
    set_resp = client.post("/benchmark/safety/gate", json=updated)
    assert set_resp.status_code == 200
    new_cfg = set_resp.json()["config"]
    assert float(new_cfg["min_pass_pct"]) == 77.0
    assert int(new_cfg["min_cases"]) == 2
    assert int(new_cfg["window"]) == 4

    # Restore prior config to avoid cross-test bleed.
    restore_resp = client.post("/benchmark/safety/gate", json=old_cfg)
    assert restore_resp.status_code == 200


def test_collab_durability_reload_and_events():
    room_create = client.post(
        "/collab/rooms",
        json={"owner": "owner_a", "name": "pytest room", "session_id": _unique("sid")},
    )
    assert room_create.status_code == 200
    room = room_create.json()["room"]
    room_id = room["room_id"]

    join = client.post(f"/collab/rooms/{room_id}/join", json={"username": "member_a"})
    assert join.status_code == 200

    events_before = client.get(f"/collab/rooms/{room_id}/events?limit=20")
    assert events_before.status_code == 200
    assert events_before.json()["count"] >= 2

    # Simulate process memory loss and reload from durable pref store.
    import src.collab as collab

    collab._rooms.clear()  # noqa: SLF001 - intentional state reset for durability test
    assert client.get(f"/collab/rooms/{room_id}").status_code == 404

    reloaded = client.post("/collab/rooms/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["loaded"] >= 1

    room_after = client.get(f"/collab/rooms/{room_id}")
    assert room_after.status_code == 200
    assert "member_a" in room_after.json()["room"]["members"]


def test_federated_round_validation_and_route_status():
    bad_round = client.post(
        "/federated/round",
        json={"samples": [{"foo": "bar"}], "global_round": "abc"},
    )
    assert bad_round.status_code == 422

    bad_samples = client.post(
        "/federated/round",
        json={"samples": [{"input": "", "output": ""}], "global_round": 1},
    )
    assert bad_samples.status_code == 400
    assert bad_samples.json()["status"] == "failed"


def test_federated_local_only_status_when_enabled(monkeypatch):
    import src.federated as fed

    monkeypatch.setattr(fed, "FEDERATED_ENABLED", True)
    monkeypatch.setattr(fed, "FEDERATED_SERVER", "")
    monkeypatch.setattr(fed, "FEDERATED_TOKEN", "")
    monkeypatch.setattr(fed, "_total_privacy_budget_used", 0.0)

    resp = client.post(
        "/federated/round",
        json={"samples": [{"input": "hello", "output": "world"}], "global_round": 2},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "local_only"
    assert payload["local_samples"] == 1


def test_browser_confirmation_flow(monkeypatch):
    import src.browser_agent as ba

    monkeypatch.setattr(ba, "_detect_backend", lambda: "requests")
    monkeypatch.setattr(
        ba,
        "_requests_navigate",
        lambda url: {
            "ok": True,
            "url": url,
            "title": "ok",
            "text_preview": "page text",
            "links": [],
            "status_code": 200,
            "backend": "requests",
        },
    )

    created = client.post("/browser/sessions", json={"start_url": "https://example.com"})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    step = client.post(
        f"/browser/sessions/{sid}/step",
        json={
            "action": "click",
            "params": {
                "selector": "button#buy",
                "sensitive": True,
                "confirmation_reason": "checkout_click",
            },
        },
    )
    assert step.status_code == 200
    assert step.json().get("pending_confirmation") is True

    reject = client.post(f"/browser/sessions/{sid}/confirm", json={"approve": False, "actor": "qa"})
    assert reject.status_code == 200
    assert reject.json()["approved"] is False

    step2 = client.post(
        f"/browser/sessions/{sid}/step",
        json={
            "action": "click",
            "params": {
                "selector": "button#buy",
                "sensitive": True,
            },
        },
    )
    assert step2.status_code == 200
    assert step2.json().get("pending_confirmation") is True

    approve = client.post(f"/browser/sessions/{sid}/confirm", json={"approve": True, "actor": "qa"})
    assert approve.status_code == 200
    assert approve.json()["approved"] is True


def test_browser_pause_resume_and_blocked_step(monkeypatch):
    import src.browser_agent as ba

    monkeypatch.setattr(ba, "_detect_backend", lambda: "requests")
    monkeypatch.setattr(
        ba,
        "_requests_navigate",
        lambda url: {
            "ok": True,
            "url": url,
            "title": "ok",
            "text_preview": "page text",
            "links": [],
            "status_code": 200,
            "backend": "requests",
        },
    )

    created = client.post("/browser/sessions", json={"start_url": "https://example.com"})
    assert created.status_code == 200
    sid = created.json()["session_id"]

    pause = client.post(f"/browser/sessions/{sid}/pause", json={"reason": "operator_pause"})
    assert pause.status_code == 200
    assert pause.json()["session"]["status"] == "paused"

    blocked = client.post(
        f"/browser/sessions/{sid}/step",
        json={"action": "navigate", "params": {"url": "https://example.com/a"}},
    )
    assert blocked.status_code == 400

    resume = client.post(f"/browser/sessions/{sid}/resume", json={"replay_navigation": True})
    assert resume.status_code == 200
    assert resume.json()["session"]["status"] == "idle"

    run = client.post(
        f"/browser/sessions/{sid}/step",
        json={"action": "navigate", "params": {"url": "https://example.com/a"}},
    )
    assert run.status_code == 200
